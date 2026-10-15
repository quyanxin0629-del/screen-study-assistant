import os
from threading import Event

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from screen_study_assistant.api import StudyReply
from screen_study_assistant.config import ConfigStore, Settings
from screen_study_assistant.notes import NoteStore
from screen_study_assistant.ui import AnswerWindow


def wait_until(predicate):
    for _ in range(500):
        if predicate():
            return
        QTest.qWait(10)
    assert predicate()


def test_sent_question_is_visible_before_first_byte_and_keeps_its_original_wording(
        tmp_path, monkeypatch):
    import screen_study_assistant.app as application

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(application, "ConfigStore", lambda: ConfigStore(tmp_path / "config"))
    started, first_byte, finish = Event(), Event(), Event()
    typed = "它能存数学公式吗？"

    class Client:
        def __init__(self, *_):
            pass

        def study(self, messages, chunk, _cancel, **_kwargs):
            assert messages[-1]["content"] == typed
            started.set()
            assert first_byte.wait(5)
            chunk("可以保存公式。")
            assert finish.wait(5)
            return StudyReply("answer", question="Markdown 如何保存数学公式？",
                              answer="可以保存公式，使用支持数学扩展的编辑器即可显示。")

    monkeypatch.setattr(application, "ChatClient", Client)
    controller = application.Controller(app, preview=True)
    controller.settings = Settings("https://test.invalid/v1", "model", str(tmp_path / "notes"))
    controller.session_settings = controller.settings
    controller.session_key = "test-only"
    controller.concept_ready = True
    controller.text = "Markdown"
    controller.messages = [{"role": "user", "content": "Markdown"},
                           {"role": "assistant", "content": "一种标记语法。"}]
    window = controller.answer
    window.show()
    window.start_answer("什么是 Markdown？")
    window.finish_answer("一种标记语法。")
    try:
        window.question.setText(typed)
        QTest.keyClick(window.question, Qt.Key_Return)
        # The question is already in the widget tree before the worker returns anything.
        assert window.browser.bubbles[-2].body.text() == typed
        assert window.browser.bubbles[-1].status.text() == "正在思考…"
        assert not window.output and len(window.turns) == 1
        assert window.question.text() == "" and not window.send.isEnabled()
        wait_until(started.is_set)
        assert not NoteStore(controller.settings.notes_dir).qa_path.exists()
        first_byte.set()
        wait_until(lambda: window.output == "可以保存公式。")
        assert window.browser.bubbles[-1].body.toPlainText() == "可以保存公式。"
        assert len(window.browser.bubbles) == 4
        finish.set()
        wait_until(lambda: not controller.tasks and not controller.io.pending)
        assert window.browser.bubbles[-2].body.text() == typed
        assert window.current_question == "Markdown 如何保存数学公式？"
        assert len(window.browser.bubbles) == 4 and window.send.isEnabled()
        body = NoteStore(controller.settings.notes_dir).qa_path.read_text()
        assert "**Markdown 如何保存数学公式？**" in body
        assert "正在思考" not in body
    finally:
        first_byte.set()
        finish.set()
        controller.quit()
        wait_until(lambda: not controller.tasks and not controller.io.pending)
        for widget in (controller.window, window, controller.launcher, controller.menu_bar):
            if widget:
                widget.deleteLater()
        controller.deleteLater()


def test_chat_alignment_wrapping_and_stop_do_not_lose_the_sent_question():
    app = QApplication.instance() or QApplication([])
    window = AnswerWindow()
    window.show()
    window.start_answer("第一个问题")
    window.finish_answer("第一个回答。")
    window.start_answer("<img src='file:///private'> 这是一段需要自动换行的追问。" * 3)
    window.append_answer("已经生成的部分。")
    window.interrupt_answer()
    app.processEvents()
    user, assistant = window.browser.bubbles[-2:]
    assert user.x() > assistant.x() == 0
    assert user.width() < window.browser.viewport().width()
    assert user.height() > 40
    assert "<img" in user.body.text()  # user input is literal text
    assert assistant.status.text() == "已停止"
    window.start_answer("重新追问")
    window.show_error("网络暂时不可用")
    assert "已经生成的部分" in window.browser.toPlainText()
    assert window.browser.bubbles[-2].body.text() == "重新追问"
    assert window.browser.bubbles[-1].status.text() == "网络暂时不可用"
    assert len(window.turns) == 1  # interrupted/failed answers are not completed notes
    window.reset()
    assert not window.browser.bubbles and not window.chat_history and not window.pending
    window.hide()
    window.deleteLater()


def test_streaming_does_not_drag_a_reader_away_from_earlier_messages():
    app = QApplication.instance() or QApplication([])
    window = AnswerWindow()
    window.show()
    for index in range(6):
        window.start_answer(f"问题 {index}")
        window.finish_answer("这是一段较长的解释，用来阅读前面的对话。" * 20)
    window.start_answer("最后一个问题")
    QTest.qWait(20)
    bar = window.browser.verticalScrollBar()
    assert bar.maximum() > 0 and bar.value() == bar.maximum()
    bar.setValue(0)
    window.append_answer("正在逐步生成新的解答。" * 5)
    app.processEvents()
    assert bar.value() == 0
    for bubble in window.browser.bubbles:
        if bubble.role == "assistant" and bubble.text:
            assert bubble.body.height() >= bubble.body.document().size().height()
            assert bubble.body.verticalScrollBar().maximum() == 0
    window.hide()
    window.deleteLater()
