import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPoint, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from screen_study_assistant.config import Settings
from screen_study_assistant.hotkey import MAC_KEYS, Hotkey, WindowsMessageFilter
from screen_study_assistant.ocr import recognize
from screen_study_assistant.ui import AnswerWindow, CaptureOverlay, SettingsWindow


@pytest.fixture(scope="module")
def app():
    if sys.platform == "darwin":
        QApplication.setAttribute(Qt.AA_MacDontSwapCtrlAndMeta, True)
    return QApplication.instance() or QApplication([])


def test_single_settings_page_and_key_visibility(app):
    page = SettingsWindow(Settings(), "⌘ ⇧ K")
    assert page.key.echoMode() == page.key.EchoMode.Password
    page.key.setText("test-only-key")
    page.toggle_key()
    assert page.key.echoMode() == page.key.EchoMode.Normal
    assert page.url.placeholderText().startswith("https://")
    assert page.model is not None
    if sys.platform == "darwin":
        from PySide6.QtGui import QKeySequence

        assert "⌘" in page.shortcut.keySequence().toString(QKeySequence.NativeText)
    page.deleteLater()


@pytest.fixture
def controller(app, tmp_path, monkeypatch):
    import screen_study_assistant.app as application
    from screen_study_assistant.config import ConfigStore

    monkeypatch.setattr(application, "ConfigStore", lambda: ConfigStore(tmp_path / "config"))
    instance = application.Controller(app, preview=True)
    instance.settings.notes_dir = str(tmp_path / "notes")
    instance.window.notes_dir = instance.settings.notes_dir
    yield instance
    instance.io.shutdown()
    for _ in range(200):
        if not instance.io.pending:
            break
        QTest.qWait(10)
    assert not instance.io.pending
    if instance.menu_bar:
        instance.menu_bar.deleteLater()
    instance.launcher.hide()
    instance.launcher.deleteLater()
    instance.window.hide()
    instance.answer.hide()
    instance.window.deleteLater()
    instance.answer.deleteLater()
    instance.deleteLater()


@pytest.mark.parametrize("key_first", [True, False])
def test_model_fields_accept_either_input_order(controller, monkeypatch, key_first):
    from screen_study_assistant.config import normalize_url

    vault = {}
    monkeypatch.setattr("keyring.set_password", lambda service, url, key: vault.update({url: key}))
    monkeypatch.setattr("keyring.get_password", lambda service, url: vault.get(url, ""))
    window = controller.window
    window.model.setText("test-model")
    if key_first:
        QTest.keyClicks(window.key, "manual-test-key")
    # Type the URL character by character to exercise every textChanged event.
    QTest.keyClicks(window.url, "https://test.invalid/v1/chat/completions/")
    if not key_first:
        QTest.keyClicks(window.key, "manual-test-key")
    assert window.key.text() == "manual-test-key"
    assert window.key.echoMode() == window.key.EchoMode.Password
    settings, key = controller.draft()
    assert key == "manual-test-key"
    controller.save_settings()
    assert vault[normalize_url(settings.api_url)] == "manual-test-key"
    assert "manual-test-key" not in (controller.store.directory / "settings.json").read_text()


def test_url_change_preserves_manual_key_but_never_reuses_stored_key(controller, monkeypatch):
    controller.settings = Settings("https://old.invalid/v1", "test-model")
    reads = []

    def get_key(_service, url):
        reads.append(url)
        return "stored-old-service-key"

    monkeypatch.setattr("keyring.get_password", get_key)
    controller.window.model.setText("test-model")
    controller.window.url.setText("https://old.invalid/v1/chat/completions")
    assert controller.draft()[1] == "stored-old-service-key"
    reads.clear()
    controller.window.url.setText("https://new.invalid/v1")
    assert controller.draft()[1] == ""
    assert not reads
    controller.window.key.setText("manual-new-service-key")
    controller.window.url.setText("https://new.invalid/v1/chat/completions/")
    assert controller.window.key.text() == "manual-new-service-key"
    assert controller.draft()[1] == "manual-new-service-key"
    assert not reads


def test_windows_native_message_routing(app):
    import ctypes
    from ctypes import wintypes

    hotkey = Hotkey()
    activations = []
    hotkey.activated.connect(lambda: activations.append(True))
    event_filter = WindowsMessageFilter(hotkey)
    message = wintypes.MSG()
    message.message = 0x0312
    message.wParam = hotkey.identifier
    assert event_filter.nativeEventFilter(b"windows_dispatcher_MSG", ctypes.addressof(message)) == (
        True,
        0,
    )
    assert activations == [True]
    message.wParam += 1
    assert event_filter.nativeEventFilter(b"windows_generic_MSG", ctypes.addressof(message)) == (
        False,
        0,
    )


@pytest.mark.skipif(sys.platform != "darwin", reason="Native macOS hotkey")
def test_native_hotkey_conflict_and_recovery(app):
    assert set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789").issubset(MAC_KEYS)
    first = Hotkey()
    second = Hotkey()
    try:
        first.start("Meta+Ctrl+Alt+Shift+F8")
        assert first.active
        with pytest.raises(RuntimeError, match="占用"):
            second.start("Meta+Ctrl+Alt+Shift+F8")
        assert first.active
        first.stop()
        second.start("Meta+Ctrl+Alt+Shift+F8")
        assert second.active
    finally:
        first.stop()
        second.stop()


def test_float_can_close_and_followup_is_separate(app):
    window = AnswerWindow()
    cancellations = []
    window.cancelled.connect(lambda: cancellations.append(True))
    window.show()
    window.start_answer("解释这段内容")
    window.append_answer("这是一个解释。")
    window.finish_answer("这是一个解释。")
    window.start_answer("举例")
    window.append_answer("这是一个例子。")
    window.finish_answer("这是一个例子。")
    assert len(window.turns) == 2
    assert "例子" in window.browser.toPlainText()
    window.close()
    assert not window.isVisible()
    assert cancellations == [True]
    window.show()
    window.close()
    window.deleteLater()


def test_retina_crop_keeps_physical_pixel_size(app):
    screen = app.primaryScreen()
    geometry = screen.geometry()
    pixmap = QPixmap(geometry.width() * 2, geometry.height() * 2)
    pixmap.fill(QColor("white"))
    pixmap.setDevicePixelRatio(2)
    overlay = CaptureOverlay(screen, pixmap)
    captures = []
    overlay.selected.connect(lambda image, position: captures.append(image))
    overlay.show()
    QTest.mousePress(overlay, Qt.LeftButton, pos=QPoint(50, 100))
    QTest.mouseMove(overlay, QPoint(150, 180))
    QTest.mouseRelease(overlay, Qt.LeftButton, pos=QPoint(150, 180))
    assert captures
    result = QPixmap()
    result.loadFromData(captures[0])
    assert result.width() == 202  # QRect endpoints are inclusive
    assert result.height() == 162
    assert overlay.pixmap.isNull()
    overlay.deleteLater()


@pytest.mark.skipif(sys.platform != "darwin", reason="Apple Vision only")
def test_real_local_ocr_on_generated_text(app):
    pixmap = QPixmap(900, 180)
    pixmap.fill(QColor("white"))
    painter = QPainter(pixmap)
    painter.setPen(QColor("black"))
    painter.setFont(QFont("Arial", 34))
    painter.drawText(30, 75, "Contrastive Learning")
    painter.drawText(30, 135, "A learning concept")
    painter.end()
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.WriteOnly)
    pixmap.save(buffer, "PNG")
    text = recognize(bytes(data))
    assert "Contrastive" in text
    assert "Learning" in text


@pytest.mark.skipif(sys.platform != "darwin", reason="Full pipeline uses Apple Vision")
def test_full_ocr_api_followup_local_notes_pipeline(app, tmp_path, monkeypatch):
    import json
    import time

    import httpx

    import screen_study_assistant.app as application
    from screen_study_assistant.api import ChatClient
    from screen_study_assistant.config import ConfigStore

    monkeypatch.setattr(application, "ConfigStore", lambda: ConfigStore(tmp_path / "config"))
    monkeypatch.setattr("keyring.get_password", lambda *_: "")
    monkeypatch.setattr("keyring.delete_password", lambda *_: None)
    requests = []

    def handler(request):
        payload = json.loads(request.content)
        requests.append(payload)
        if "只返回 JSON" in payload["messages"][0]["content"]:
            answer = json.dumps(
                {
                    "name": "对比学习",
                    "aliases": ["Contrastive Learning"],
                    "summary": "学习相似关系",
                    "explanation": "概念解释",
                    "tags": ["机器学习"],
                },
                ensure_ascii=False,
            )
        else:
            answer = "学习相似关系，让相似样本靠近。"
        return httpx.Response(200, json={"choices": [{"message": {"content": answer}}]})

    class MockClient(ChatClient):
        def __init__(self, settings, key=""):
            super().__init__(settings, key, httpx.MockTransport(handler))

    monkeypatch.setattr(application, "ChatClient", MockClient)
    controller = application.Controller(app, preview=True)
    controller.window.url.setText("https://test.invalid/v1")
    controller.window.model.setText("test-model")
    controller.window.notes_dir = str(tmp_path / "notes")
    controller.save_settings()
    assert controller.settings.model == "test-model"
    controller.session_settings = controller.settings
    pixmap = QPixmap(900, 150)
    pixmap.fill(QColor("white"))
    painter = QPainter(pixmap)
    painter.setPen(QColor("black"))
    painter.setFont(QFont("Arial", 34))
    painter.drawText(30, 85, "Contrastive Learning")
    painter.end()
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.WriteOnly)
    pixmap.save(buffer, "PNG")
    controller.process_capture(bytes(data), QPoint(100, 100))

    def wait_until(predicate):
        end = time.monotonic() + 10
        while not predicate() and time.monotonic() < end:
            QTest.qWait(20)
        assert predicate()

    wait_until(
        lambda: (
            controller.qa_path is not None and not controller.tasks and not controller.io.pending
        )
    )
    assert "Contrastive" in controller.text
    assert controller.pending_card is not None
    controller.followup("再举一个例子")
    wait_until(
        lambda: (
            len(controller.answer.turns) == 2 and not controller.tasks and not controller.io.pending
        )
    )
    body = controller.qa_path.read_text(encoding="utf-8")
    assert "**再举一个例子**" in body
    assert "## 问题" not in body and "## 回答" not in body
    assert "<!-- entry:" not in body
    assert len(json.loads((tmp_path / "notes" / ".学习笔记索引.json").read_text())["entries"]) == 2
    assert controller.qa_path.name == "学习笔记.md"
    assert len(list((tmp_path / "notes" / "知识图鉴").glob("*.md"))) == 1
    assert all(path.suffix == ".md" or path.name == ".学习笔记索引.json"
               for path in (tmp_path / "notes").rglob("*") if path.is_file())
    assert len(requests) == 3  # initial answer, concept extraction, follow-up
    controller.answer.close()
    assert not controller.answer.isVisible()
    controller.io.shutdown()
    controller.launcher.hide()
    controller.launcher.deleteLater()
    controller.window.hide()
    controller.window.deleteLater()
    controller.answer.deleteLater()
    controller.deleteLater()


def test_answer_close_exposes_settings_and_notes_without_main_page(controller, monkeypatch):
    from PySide6.QtGui import QDesktopServices

    urls = []
    monkeypatch.setattr(
        QDesktopServices, "openUrl", lambda url: urls.append(url.toLocalFile()) or True
    )
    controller.window.close()
    assert controller.launcher.isVisible()
    QTest.mouseClick(controller.launcher.settings_button, Qt.LeftButton)
    assert controller.window.isVisible()
    assert not controller.launcher.isVisible()
    controller.window.hide()
    controller.answer.show()
    controller.answer.close()
    assert controller.launcher.isVisible()
    QTest.mouseClick(controller.launcher.notes_button, Qt.LeftButton)
    for _ in range(100):
        if urls:
            break
        QTest.qWait(10)
    assert urls == [str(__import__("pathlib").Path(controller.settings.notes_dir) / "学习笔记.md")]
    QTest.mouseClick(controller.launcher.settings_button, Qt.LeftButton)
    assert controller.window.isVisible()


def test_float_position_prefers_free_side_and_clamps_negative_monitor_coordinates(app):
    from PySide6.QtCore import QRect, QSize

    from screen_study_assistant.ui import adjacent_position

    area = QRect(-1600, 30, 1600, 950)
    size = QSize(440, 550)
    for selection in (
        QRect(-1400, 180, 200, 100),
        QRect(-300, 180, 250, 100),
        QRect(-1450, 35, 1350, 130),
        QRect(-1450, 760, 1350, 130),
    ):
        panel = QRect(adjacent_position(selection, size, area), size)
        assert area.contains(panel)
        assert not panel.intersects(selection)
    huge = QRect(-1595, 35, 1590, 930)
    assert area.contains(QRect(adjacent_position(huge, size, area), size))


def test_capture_emits_whole_global_selection_rectangle(app):
    screen = app.primaryScreen()
    pixmap = QPixmap(screen.geometry().size())
    pixmap.fill(QColor("white"))
    overlay = CaptureOverlay(screen, pixmap)
    selections = []
    overlay.selected.connect(lambda image, selection: selections.append(selection))
    overlay.show()
    QTest.mousePress(overlay, Qt.LeftButton, pos=QPoint(50, 100))
    QTest.mouseRelease(overlay, Qt.LeftButton, pos=QPoint(150, 180))
    assert selections
    assert selections[0].topLeft() == overlay.mapToGlobal(QPoint(50, 100))
    assert selections[0].width() == 101
    assert selections[0].height() == 81
    overlay.deleteLater()


def test_note_writes_are_async_ordered_and_survive_closed_answer(controller, monkeypatch):
    from threading import Event, current_thread

    from screen_study_assistant.notes import NoteStore

    started, release = Event(), Event()
    real_append = NoteStore.append_qa
    calls = []

    def slow_append(store, question, answer, entry_id, timestamp):
        calls.append((question, current_thread().name))
        if len(calls) == 1:
            started.set()
            assert release.wait(3)
        return real_append(store, question, answer, entry_id, timestamp)

    monkeypatch.setattr(NoteStore, "append_qa", slow_append)
    controller.session_settings = controller.settings
    controller.text = "第一个截图中的问题"
    controller.concept_ready = True  # Isolate persistence from model calls.
    controller.answer.show()
    controller.answer.start_answer("解释这段内容")
    try:
        controller.answer_finished("第一个回答")
        assert started.wait(0.5)
        assert controller.answer.send.isEnabled()
        assert "第一个回答" in controller.answer.browser.toPlainText()
        assert not controller.busy
        assert not NoteStore(controller.settings.notes_dir).qa_path.exists()
        controller.answer.start_answer("再举个例子")
        controller.answer_finished("第二个回答")
        controller.answer.close()
        assert controller.launcher.isVisible()
    finally:
        release.set()
    for _ in range(200):
        if not controller.io.pending:
            break
        QTest.qWait(10)
    assert not controller.io.pending
    content = NoteStore(controller.settings.notes_dir).qa_path.read_text(encoding="utf-8")
    assert content.index("第一个回答") < content.index("第二个回答")
    assert "**第一个截图中的问题**" in content
    assert len(calls) == 2
    assert all(name.startswith("local-notes") for _, name in calls)


def test_note_failure_does_not_disable_answer_or_followup(controller, monkeypatch):
    from screen_study_assistant.notes import NoteStore

    def fail_write(*args):
        raise OSError("test-only disk error")

    monkeypatch.setattr(NoteStore, "append_qa", fail_write)
    controller.session_settings = controller.settings
    controller.text = "测试问题"
    controller.concept_ready = True
    controller.answer.start_answer("解释这段内容")
    controller.answer_finished("回答不应因笔记失败消失")
    for _ in range(100):
        if not controller.io.pending:
            break
        QTest.qWait(10)
    assert controller.answer.saved.text() == "保存失败"
    assert "回答不应因笔记失败消失" in controller.answer.browser.toPlainText()
    assert controller.answer.send.isEnabled()
    assert not controller.busy


def test_slow_concept_lookup_never_delays_model_request(controller, monkeypatch):
    from threading import Event

    from screen_study_assistant.notes import NoteStore

    started, release = Event(), Event()
    calls = []

    def slow_lookup(store, text):
        started.set()
        assert release.wait(3)
        return None

    monkeypatch.setattr(NoteStore, "find_concept", slow_lookup)
    monkeypatch.setattr(controller, "request_answer", lambda question: calls.append(question))
    controller.session_settings = controller.settings
    try:
        controller.ocr_finished("一个新的概念")
        assert calls == ["解释这段内容"]
        assert started.wait(0.5)
    finally:
        release.set()


def test_native_quit_hides_all_windows_and_drains_notes(controller, monkeypatch):
    from threading import Event

    completed, release = [], Event()
    monkeypatch.setattr(controller.app, "quit", lambda: completed.append(True))
    controller.io.submit(lambda: release.wait(3), lambda _: None, lambda: None)
    controller.answer.show()
    controller.launcher.show()
    try:
        if controller.menu_bar:
            controller.quit_action.trigger()
        else:
            controller.quit()
        assert controller.quitting
        assert not controller.window.isVisible()
        assert not controller.answer.isVisible()
        assert not controller.launcher.isVisible()
        assert not completed
    finally:
        release.set()
    for _ in range(100):
        if completed:
            break
        QTest.qWait(10)
    assert completed == [True]


def test_missing_screen_access_never_reads_keychain(controller, monkeypatch):
    import screen_study_assistant.app as application

    monkeypatch.setattr(application.sys, "platform", "darwin")
    attempts, key_reads = [], []
    monkeypatch.setattr(
        application,
        "screen_capture_allowed",
        lambda api, may_request: attempts.append(may_request) or False,
    )
    monkeypatch.setattr(
        controller.store, "get_key", lambda url: key_reads.append(url) or "test-key"
    )
    controller.settings = Settings("https://example.invalid/v1", "test-model")
    for _ in range(3):
        controller.capture()
    assert attempts == [True, False, False]
    assert key_reads == []
    assert not controller.capture_pending
