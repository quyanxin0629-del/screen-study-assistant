"""Desktop orchestration: native hotkey, local OCR, API, floating answers."""

from __future__ import annotations

import argparse
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime
from threading import Event

from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QCursor, QIcon, QKeySequence
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QFileDialog, QMenu, QMenuBar, QSystemTrayIcon

from .api import SYSTEM_PROMPT, Cancelled, ChatClient, StudyReply
from .config import ConfigStore, Settings, normalize_url
from .hotkey import Hotkey
from .notes import NoteStore
from .ocr import OcrResult, recognize_details
from .permissions import screen_capture_allowed, screen_capture_message
from .ui import AnswerWindow, CaptureOverlay, LauncherWindow, SettingsWindow, icon_pixmap


class Task(QThread):
    result = Signal(object)
    error = Signal(str)
    chunk = Signal(str)

    def __init__(self, operation, parent=None):
        super().__init__(parent)
        self.operation = operation
        self.cancel = Event()

    def run(self):
        try:
            value = self.operation(self.cancel, self.chunk.emit)
            if not self.cancel.is_set():
                self.result.emit(value)
        except Cancelled:
            pass
        except Exception as exc:
            if not self.cancel.is_set():
                # Known exceptions expose user-facing errors; no headers or request bodies.
                from .api import ApiError

                message = (
                    str(exc)
                    if isinstance(exc, (ApiError, ValueError, RuntimeError))
                    else "操作失败，请检查配置后重试。"
                )
                self.error.emit(message)
        finally:
            self.operation = None  # release image bytes and captured credentials


class BackgroundIO(QObject):
    completed = Signal(object)
    idle = Signal()

    def __init__(self, parent):
        super().__init__(parent)
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="local-notes")
        self.pending = 0
        self.completed.connect(self._complete, Qt.QueuedConnection)

    def submit(self, operation, success, error):
        self.pending += 1
        future = self.pool.submit(operation)
        future.add_done_callback(lambda done: self.completed.emit((done, success, error)))

    def _complete(self, payload):
        future, success, error = payload
        self.pending -= 1
        try:
            value = future.result()
        except Exception:
            error()
        else:
            success(value)
        if self.pending == 0:
            self.idle.emit()

    def shutdown(self):
        # Drain completed answers even when the UI is closed or the app exits.
        self.pool.shutdown(wait=False)


class Controller(QObject):
    def __init__(self, app: QApplication, preview=False):
        super().__init__()
        self.app = app
        self.store = ConfigStore()
        load_error = ""
        try:
            self.settings = self.store.load()
        except ValueError as exc:
            self.settings = Settings()
            load_error = str(exc)
        self.hotkey = Hotkey(self)
        self.hotkey.shortcut = self.settings.shortcut
        self.preview = preview
        self.window = SettingsWindow(self.settings, self.hotkey.label)
        self.answer = AnswerWindow()
        self.launcher = LauncherWindow()
        self.overlay = None
        self.tasks: set[Task] = set()
        self.session_tasks: set[Task] = set()
        self.generation = 0
        self.busy = False
        self.capture_pending = False
        self.capture_permission_requested = False
        self.qa_path = None
        self.text = ""
        self.messages = []
        self.pending_clarification = None
        self.clarification_used = False
        self.confirmed_direction = ""
        self.session_settings = None
        self.session_key = ""
        self.concept_ready = False
        self.pending_card = None
        self.existing_card = None
        self.test_task = None
        self.quitting = False
        self.qa_session_id = uuid.uuid4().hex
        self.note_turns = []
        self.note_revision = 0
        self.note_timestamp = ""
        self.note_summary_task = None
        self.io = BackgroundIO(self)
        self.io.idle.connect(self.maybe_quit)
        self.menu_bar = None
        if sys.platform == "darwin":
            # Override Qt's default Quit, which asks hide-on-close windows to close.
            self.menu_bar = QMenuBar()
            app_menu = self.menu_bar.addMenu("应用")
            self.settings_action = QAction("打开主页面", self)
            self.settings_action.setMenuRole(QAction.PreferencesRole)
            self.settings_action.setShortcut(QKeySequence("Meta+,"))
            self.settings_action.setShortcutContext(Qt.ApplicationShortcut)
            self.settings_action.triggered.connect(self.show_settings)
            app_menu.addAction(self.settings_action)
            self.quit_action = QAction("退出", self)
            self.quit_action.setMenuRole(QAction.QuitRole)
            self.quit_action.setShortcut(QKeySequence("Meta+Q"))
            self.quit_action.triggered.connect(self.quit)
            app_menu.addAction(self.quit_action)

        self.window.save_requested.connect(self.save_settings)
        self.window.test_requested.connect(self.test_connection)
        self.window.clear_requested.connect(self.clear_key)
        self.window.directory_requested.connect(self.choose_directory)
        self.window.notes_requested.connect(self.open_notes)
        self.window.url.textChanged.connect(self.url_changed)
        self.window.shortcut.recording_changed.connect(self.record_shortcut)
        self.answer.submitted.connect(self.followup)
        self.answer.clarified.connect(self.clarify)
        self.answer.retry_requested.connect(self.retry)
        self.answer.cancelled.connect(self.cancel_session)
        self.answer.settings_requested.connect(self.show_settings)
        self.answer.notes_requested.connect(self.open_notes)
        self.answer.closed.connect(self.show_launcher)
        self.window.hidden.connect(self.show_launcher)
        self.window.minimized.connect(self.show_launcher)
        self.window.restored.connect(self.launcher.hide)
        self.window.launcher_toggle.toggled.connect(self.set_launcher_enabled)
        self.launcher.capture_requested.connect(self.capture)
        self.launcher.settings_requested.connect(self.show_settings)
        self.launcher.notes_requested.connect(self.open_notes)
        self.hotkey.activated.connect(self.capture, Qt.QueuedConnection)
        self.tray = QSystemTrayIcon(QIcon(icon_pixmap()), self)
        self.tray.setToolTip("屏幕学习助手 · " + self.hotkey.label)
        menu = QMenu()
        self.capture_action = menu.addAction("框选并解释  " + self.hotkey.label, self.capture)
        menu.addAction("打开主页面", self.show_settings)
        menu.addAction("打开本地笔记", self.open_notes)
        menu.addAction("显示快捷工具条", self.show_launcher)
        menu.addSeparator()
        menu.addAction("退出", self.quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda reason: (
                self.show_settings()
                if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick)
                else None
            )
        )
        if not preview:
            self.tray.show()
            if sys.platform == "darwin":
                # Cocoa forwards every Dock/Finder reopen as ApplicationActive,
                # even when already active. A hidden Qt window needs restoring.
                app.applicationStateChanged.connect(self.application_state_changed)
            try:
                self.hotkey.start(self.settings.shortcut)
                self.window.hotkey_status.setText("快捷键已就绪 · 关闭此窗口后仍在菜单栏运行")
            except Exception as exc:
                self.window.hotkey_status.setText(str(exc))
                self.window.hotkey_status.setStyleSheet("color: #D65C5C;")
        else:
            self.window.hotkey_status.setText("界面预览 · 未注册全局快捷键")
        self.window.clear_key.setEnabled(bool(self.settings.api_url))
        if self.settings.api_url:
            self.window.key.setPlaceholderText("留空以继续使用已保存的密钥；本地服务可不填")
        if load_error:
            self.window.show_status(load_error, True)
        geometry = app.primaryScreen().availableGeometry()
        self.window.resize(590, min(805, geometry.height() - 60))
        self.window.move(geometry.center() - self.window.rect().center())
        self.window.show()

    def launch_task(self, operation, success, error=None, chunk=None, session=False):
        task = Task(operation, self)
        self.tasks.add(task)
        generation = self.generation
        if session:
            self.session_tasks.add(task)

        def valid():
            return (
                not self.quitting
                and not task.cancel.is_set()
                and (not session or generation == self.generation)
            )

        task.result.connect(lambda value: success(value) if valid() else None)
        task.error.connect(lambda message: (error or self.fail)(message) if valid() else None)
        if chunk:
            task.chunk.connect(lambda value: chunk(value) if valid() else None)

        def cleanup():
            self.tasks.discard(task)
            self.session_tasks.discard(task)
            task.deleteLater()
            self.maybe_quit()

        task.finished.connect(cleanup)
        task.start()
        return task

    def show_settings(self):
        if self.quitting:
            return
        if self.window.isMinimized():
            self.window.showNormal()
        else:
            self.window.show()
        self.window.raise_()
        self.window.activateWindow()
        self.launcher.hide()

    def application_state_changed(self, state):
        if state == Qt.ApplicationActive:
            # Let capture/window transitions settle before deciding whether the
            # activation came back to an app with no usable window.
            QTimer.singleShot(0, self.reopen_if_hidden)

    def reopen_if_hidden(self):
        if (self.quitting or self.capture_pending or self.busy or self.overlay is not None
                or self.answer.isVisible() or self.launcher.isVisible()):
            return
        if not self.window.isVisible() or self.window.isMinimized():
            self.show_settings()

    def show_launcher(self):
        if self.settings.launcher_enabled and not self.quitting and not self.capture_pending:
            self.launcher.show()
            self.launcher.raise_()

    def set_launcher_enabled(self, enabled):
        try:
            settings = replace(self.settings, launcher_enabled=enabled)
            # Save only this preference, without reading the vault or consuming
            # unsaved API fields in the form.
            self.store.save(settings)
            self.settings = settings
        except Exception:
            self.window.launcher_toggle.blockSignals(True)
            self.window.launcher_toggle.setChecked(self.settings.launcher_enabled)
            self.window.launcher_toggle.blockSignals(False)
            self.window.show_status("悬浮入口设置保存失败，请检查配置目录权限。", True)
            return
        if not enabled:
            self.launcher.hide()
        elif not self.window.isVisible() or self.window.isMinimized():
            self.show_launcher()

    def open_notes(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        settings = self.session_settings if self.answer.isVisible() else self.settings
        notes = NoteStore((settings or self.settings).notes_dir)

        def prepare():
            return notes.prepare_notebook()

        def failed():
            if not self.quitting:
                self.show_settings()
                self.window.show_status("无法打开学习笔记，请检查保存位置。", True)

        def opened(path):
            if not self.quitting and not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
                failed()

        self.io.submit(prepare, opened, failed)

    def draft(self, require_model=True) -> tuple[Settings, str]:
        settings = Settings(
            self.window.url.text(),
            self.window.model.text(),
            self.window.notes_dir,
            self.window.shortcut.keySequence().toString(QKeySequence.PortableText),
            self.window.ocr_device.currentData(),
            self.window.launcher_toggle.isChecked(),
        ).validate()
        if require_model and not settings.model:
            raise ValueError("请填写 API URL 和模型名称（模型 ID）。")
        key = self.window.key.text().strip()
        # Only reuse a stored key for the currently saved, unchanged endpoint.
        if (
            not key
            and self.settings.api_url
            and normalize_url(self.settings.api_url) == settings.api_url
        ):
            try:
                key = self.store.get_key(settings.api_url)
            except Exception as exc:
                raise ValueError("无法读取系统钥匙串，请重新填写 API Key。") from exc
        return settings, key

    def url_changed(self):
        # This field only contains a key explicitly typed by the user; stored keys
        # are never filled into it. Editing the URL must not erase that input.
        # draft() separately prevents reusing a stored key for another endpoint.
        try:
            same = bool(self.settings.api_url) and normalize_url(
                self.window.url.text()
            ) == normalize_url(self.settings.api_url)
        except ValueError:
            same = False
        self.window.key.setPlaceholderText(
            "留空以继续使用已保存的密钥" if same else "填写此服务的 API Key；本地服务可留空"
        )
        self.window.clear_key.setEnabled(same)
        if self.window.key.text():
            self.window.key_state.setText("已保留手动输入的密钥，请确认它适用于当前 API 地址。")
        else:
            self.window.key_state.setText(
                "密钥保存在系统钥匙串。" if same else "新服务不会自动使用旧服务已保存的密钥。"
            )

    def save_settings(self):
        candidate = None
        try:
            settings, key = self.draft(require_model=False)
            new_key = self.window.key.text().strip()
            new_endpoint = (
                not self.settings.api_url
                or not settings.api_url
                or normalize_url(self.settings.api_url) != settings.api_url
            )
            if not self.preview and (
                settings.shortcut != self.settings.shortcut or not self.hotkey.active
            ):
                candidate = Hotkey(self)
                candidate.activated.connect(self.capture, Qt.QueuedConnection)
                candidate.start(settings.shortcut)
            # A new endpoint with an empty key is explicitly saved as unauthenticated.
            self.store.save(
                settings,
                key=new_key if new_key else None,
                clear_key=new_endpoint and not new_key,
            )
            self.settings = settings
            if candidate:
                old = self.hotkey
                old.stop()
                self.hotkey = candidate
                old.deleteLater()
                candidate = None
            elif self.preview:
                self.hotkey.shortcut = settings.shortcut
            self.tray.setToolTip("屏幕学习助手 · " + self.hotkey.label)
            self.capture_action.setText("框选并解释  " + self.hotkey.label)
            self.window.hotkey_status.setText("快捷键已就绪 · " + self.hotkey.label)
            self.window.hotkey_status.setStyleSheet("")
            self.window.key.clear()
            self.window.key.setEchoMode(self.window.key.EchoMode.Password)
            self.window.show_key.setText("显示")
            self.window.key_state.setText("密钥已安全保存。" if key else "当前服务未设置密钥。")
            self.window.key.setPlaceholderText("留空以继续使用已保存的密钥")
            self.window.clear_key.setEnabled(bool(settings.api_url))
            self.window.show_status("设置已保存 · 可以使用 " + self.hotkey.label + " 框选文字")
        except Exception as exc:
            if candidate:
                candidate.stop()
                candidate.deleteLater()
            message = (
                str(exc)
                if isinstance(exc, (ValueError, RuntimeError))
                else "保存失败，请检查系统钥匙串和配置目录权限。"
            )
            self.window.show_status(message, True)

    def record_shortcut(self, recording):
        if self.preview or self.quitting:
            return
        if recording:
            self.hotkey.stop()
            self.window.hotkey_status.setText("正在录入快捷键，原快捷键暂时停用…")
        else:
            try:
                self.hotkey.start(self.settings.shortcut)
                self.window.hotkey_status.setText(
                    "当前快捷键 · " + self.hotkey.label + " · 保存设置后更新"
                )
            except RuntimeError as exc:
                self.window.hotkey_status.setText(str(exc))

    def clear_key(self):
        try:
            if not self.settings.api_url:
                return
            self.store.save(self.settings, clear_key=True)
            self.window.key.clear()
            self.window.key_state.setText("已清除保存的密钥。")
            self.window.show_status("密钥已清除，后续新请求不再使用原密钥。")
        except Exception:
            self.window.show_status("清除失败，请检查系统钥匙串权限。", True)

    def test_connection(self):
        if self.test_task and self.test_task.isRunning():
            return
        try:
            settings, key = self.draft()
        except Exception as exc:
            self.window.show_status(str(exc), True)
            return
        self.window.test_button.setEnabled(False)
        self.window.test_button.setText("连接中…")
        self.window.show_status("正在测试当前表单中的模型配置…")
        client = ChatClient(settings, key)

        def finish(message, error=False):
            self.window.test_button.setEnabled(True)
            self.window.test_button.setText("测试连接")
            self.window.show_status(message, error)
            self.test_task = None

        self.test_task = self.launch_task(
            lambda cancel, _chunk: client.test(cancel),
            lambda _result: finish("连接成功 · 当前文本模型接口可用，请保存设置"),
            lambda message: finish(message, True),
        )

    def choose_directory(self):
        directory = QFileDialog.getExistingDirectory(
            self.window, "选择本地笔记文件夹", self.window.notes_dir
        )
        if directory:
            self.window.notes_dir = directory
            self.window.show_status("已选择保存位置，请点击保存设置。")

    def cancel_session(self):
        self.generation += 1
        for task in self.session_tasks:
            task.cancel.set()
        self.busy = False
        self.pending_clarification = None
        self.session_key = ""
        self.answer.interrupt_answer()
        if self.answer.isVisible():
            self.answer.phase.setText("已停止 · 可修改识别文字后重新解答")

    def capture(self):
        if self.quitting or self.capture_pending or (self.overlay and self.overlay.isVisible()):
            return
        if not self.settings.api_url or not self.settings.model:
            self.show_settings()
            self.window.show_status("请先填写 API URL、模型名称并保存设置。", True)
            return
        if sys.platform == "darwin":
            import Quartz

            allowed = screen_capture_allowed(
                Quartz, may_request=not self.capture_permission_requested
            )
            self.capture_permission_requested = True
            if not allowed:
                self.show_settings()
                self.window.show_status(screen_capture_message(), True)
                return
            self.window.show_status("截图权限已就绪。")
        try:
            # The vault is read once per endpoint per process, not once per screenshot.
            key = self.store.get_key(self.settings.api_url)
        except Exception:
            self.show_settings()
            self.window.show_status("无法读取密钥，请重新填写并保存。", True)
            return
        self.cancel_session()
        self.session_settings = Settings(
            self.settings.api_url,
            self.settings.model,
            self.settings.notes_dir,
            self.settings.shortcut,
            self.settings.ocr_device,
            self.settings.launcher_enabled,
        )
        self.session_key = key
        self.answer.hide()
        self.window.hide()
        self.launcher.hide()
        self.capture_pending = True
        # Let native windows disappear before capturing the frozen background.
        QTimer.singleShot(180, self.capture_screen)

    def capture_screen(self):
        self.capture_pending = False
        screen = self.app.screenAt(QCursor.pos()) or self.app.primaryScreen()
        pixmap = screen.grabWindow(0)
        if pixmap.isNull():
            self.show_settings()
            self.window.show_status("无法捕获屏幕，请检查屏幕录制权限。", True)
            return
        self.overlay = CaptureOverlay(screen, pixmap)
        self.overlay.selected.connect(self.process_capture)
        self.overlay.dismissed.connect(self.capture_dismissed)
        self.overlay.show()
        self.overlay.raise_()
        self.overlay.activateWindow()
        self.overlay.setFocus()

    def capture_dismissed(self):
        self.show_launcher()
        self.session_key = ""
        if self.overlay:
            self.overlay.deleteLater()
            self.overlay = None

    def process_capture(self, png: bytes, point):
        if self.overlay:
            self.overlay.deleteLater()
            self.overlay = None
        self.qa_path = None
        self.qa_session_id = uuid.uuid4().hex
        self.note_turns = []
        self.note_revision = 0
        self.note_timestamp = ""
        # A previous capture's completed note may still be organizing in the background.
        self.note_summary_task = None
        self.pending_card = None
        self.existing_card = None
        self.concept_ready = False
        self.messages = []
        self.pending_clarification = None
        self.clarification_used = False
        self.confirmed_direction = ""
        self.text = ""
        self.answer.reset()
        self.launcher.hide()
        self.answer.position_near(point)
        self.answer.show()
        self.answer.raise_()
        self.answer.phase.setText("正在本地识别文字…")
        self.busy = True
        self.launch_task(
            lambda cancel, _chunk: (
                recognize_details(png, (self.session_settings or self.settings).ocr_device)
                if not cancel.is_set()
                else ""
            ),
            self.ocr_finished,
            session=True,
        )

    def ocr_finished(self, text):
        if isinstance(text, OcrResult):
            result = text
            status = f"{result.device} · 识别 {result.seconds:.2f} 秒"
            if result.fallback:
                status += "\n" + result.fallback
            self.answer.ocr_status.setText(status)
            self.answer.toggle_ocr.setToolTip("查看或修改识别文字\n" + status)
            text = result.text
        self.busy = False
        self.text = text
        self.answer.source.setPlainText(text)
        if not text.strip():
            self.answer.show_error("未识别到文字。请重新框选，或在下方手动输入。")
            self.answer.source_panel.show()
            return
        self.messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "请解释或解答以下识别文字：\n\n" + text},
        ]
        if self.confirmed_direction:
            self.messages.append({
                "role": "user", "content": "已确认方向：" + self.confirmed_direction,
            })
        self.request_answer("解释这段内容")
        # Concept lookup never delays the API request.
        notes = NoteStore(self.session_settings.notes_dir)
        generation = self.generation

        def found(card):
            if generation != self.generation or self.quitting or not card:
                return
            self.existing_card = card
            _, metadata, _ = card
            count = len(metadata.get("encounters", []))
            self.answer.encounter.setText(f"你曾遇见「{metadata['name']}」{count} 次")
            self.answer.encounter.show()

        self.io.submit(lambda: notes.find_concept(text), found, lambda: None)

    def request_answer(self, question):
        if self.busy:
            return
        self.busy = True
        # Display the sent question before credentials or any model work.
        self.answer.start_answer(question)
        if not self.session_key:
            try:
                if self.session_settings.api_url == self.settings.api_url:
                    self.session_key = self.store.get_key(self.session_settings.api_url)
            except Exception:
                self.fail("无法读取密钥，请打开模型设置。")
                return
        client = ChatClient(self.session_settings, self.session_key)
        messages = [dict(message) for message in self.messages]
        allow_clarification = not self.clarification_used
        self.launch_task(
            lambda cancel, chunk: client.study(
                messages, chunk, cancel, allow_clarification=allow_clarification
            ),
            self.study_finished,
            chunk=self.answer.append_answer,
            session=True,
        )

    def study_finished(self, reply: StudyReply):
        self.busy = False
        if reply.action == "clarify":
            if self.clarification_used:
                self.fail("已有信息不足以给出可靠解答。你的选择已保留，可修改原文后重试。")
                return
            self.clarification_used = True
            self.existing_card = None
            self.answer.encounter.hide()
            self.pending_clarification = reply
            self.messages.append({
                "role": "assistant",
                "content": reply.prompt + "\n" + "\n".join(reply.options),
            })
            self.answer.show_clarification(reply.prompt, reply.options)
            return
        self.pending_clarification = None
        self.answer.current_question = reply.question
        self.answer_finished(reply.answer)

    def clarify(self, direction):
        if self.busy or not self.pending_clarification or not direction.strip():
            return
        self.confirmed_direction = direction.strip()
        self.pending_clarification = None
        self.messages.append({
            "role": "user", "content": "我补充确认：" + direction.strip() + "。请结合原文继续。",
        })
        self.request_answer("解释这段内容")

    def answer_finished(self, answer):
        self.busy = False
        self.messages.append({"role": "assistant", "content": answer})
        self.answer.finish_answer(answer)  # Re-enable follow-ups before scheduling disk work.
        self.save_session_note(self.answer.current_question, answer)
        notes = NoteStore(self.session_settings.notes_dir)
        question = self.answer.current_question
        generation = self.generation
        session_id = self.qa_session_id
        settings = self.session_settings

        def current():
            return generation == self.generation and not self.quitting

        if not self.concept_ready:
            self.concept_ready = True
            client = ChatClient(settings, self.session_key)

            def card_ready(card):
                if self.quitting or not card:
                    return

                def record():
                    existing = notes.find_concept(card["name"])
                    return notes.upsert_concept(card, notes.qa_path, existing, qa_id=session_id)

                def recorded(value):
                    if current():
                        path, metadata, _body = value
                        self.pending_card = path
                        count = len(metadata.get("encounters", []))
                        if count > 1:
                            self.answer.encounter.setText(
                                f"第 {count} 次遇见「{metadata['name']}」"
                            )
                            self.answer.encounter.show()

                self.io.submit(record, recorded, lambda: None)

            # Use the confirmed question so ambiguous abbreviations cannot merge
            # unrelated domains just because their OCR spelling was identical.
            self.launch_task(
                lambda cancel, _chunk: client.concept(question, answer, cancel),
                card_ready,
                lambda _message: None,
                session=False,
            )

    def save_session_note(self, question, answer):
        self.note_turns.append({"question": question, "answer": answer})
        self.note_revision += 1
        if not self.note_timestamp:
            self.note_timestamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
        turns = [dict(turn) for turn in self.note_turns]
        revision, session_id = self.note_revision, self.qa_session_id
        stamp, generation = self.note_timestamp, self.generation
        notes = NoteStore(self.session_settings.notes_dir)
        multiple = len(turns) > 1
        summary_failed = False
        storage_failed = False
        self.answer.saved.setText("保存中…")

        def current():
            return (not self.quitting and generation == self.generation
                    and session_id == self.qa_session_id and revision == self.note_revision)

        def saved(path, organized=False):
            nonlocal storage_failed
            storage_failed = False
            if current():
                self.qa_path = path
                status = "已保存"
                if multiple and not organized:
                    status += " · 未整理" if summary_failed else " · 整理中…"
                self.answer.saved.setText(status)
                self.answer.saved.setToolTip(str(path))

        def failed():
            nonlocal storage_failed
            storage_failed = True
            if current():
                self.answer.saved.setText("保存失败")
                self.answer.saved.setToolTip("请检查目录权限或外部编辑。现有笔记不会被覆盖。")

        # Persist all completed turns in one entry before the optional model request.
        # If organization fails or exit cancels it, this readable fallback survives.
        fallback_question = " ".join(dict.fromkeys(turn["question"] for turn in turns))
        fallback_answer = "\n\n".join(turn["answer"] for turn in turns)
        self.io.submit(
            lambda: notes.save_session(fallback_question, fallback_answer, session_id, stamp,
                                       revision), saved, failed,
        )
        if self.note_summary_task:
            self.note_summary_task.cancel.set()
            self.note_summary_task = None
        if not multiple:
            return
        settings, key = self.session_settings, self.session_key

        def organized(reply):
            self.io.submit(
                lambda: notes.save_session(reply.question, reply.answer, session_id, stamp,
                                           revision, organized=True),
                lambda path: saved(path, organized=True), failed,
            )

        def organization_failed(_message):
            nonlocal summary_failed
            summary_failed = True
            if current() and not storage_failed:
                self.answer.saved.setText("已保留完整问答 · 整理失败")
                self.answer.saved.setToolTip("本次截图仍是一条笔记，下次追问会重新整理。")

        task = self.launch_task(
            lambda cancel, _chunk: ChatClient(settings, key).summarize_note(turns, cancel),
            organized, organization_failed, session=False,
        )
        self.note_summary_task = task

        def clear_summary_task():
            if self.note_summary_task is task:
                self.note_summary_task = None

        task.finished.connect(clear_summary_task)

    def followup(self, question):
        if not self.text or self.busy or not self.messages or self.pending_clarification:
            return
        # Failed follow-ups must not leave an unanswered message in the conversation.
        if self.messages[-1]["role"] == "user" and len(self.messages) > 2:
            self.messages.pop()
        self.messages.append({"role": "user", "content": question})
        self.request_answer(question)

    def retry(self, text):
        if not text:
            self.answer.show_error("请先填写要解释的文字。")
            return
        self.cancel_session()
        self.concept_ready = False
        self.pending_card = None
        self.answer.clear_conversation()
        self.note_turns = []  # corrected OCR replaces this capture, retaining its ID/revision
        self.answer.output = ""
        self.answer.encounter.hide()
        # Keep the same Q&A file for retrying, update its content on success.
        if self.session_settings is None:
            self.session_settings = self.settings
        self.ocr_finished(text)

    def fail(self, message):
        self.busy = False
        self.answer.show_error(message)

    def maybe_quit(self):
        if self.quitting and not self.tasks and self.io.pending == 0:
            self.app.quit()

    def quit(self):
        if self.quitting:
            return
        self.quitting = True
        self.store.forget_key()
        self.session_key = ""
        self.hotkey.stop()
        for task in self.tasks:
            task.cancel.set()
        self.window.hide()
        self.answer.hide()
        if self.overlay:
            self.overlay.close()
        self.tray.hide()
        self.launcher.hide()
        self.io.shutdown()
        self.maybe_quit()


def main():
    parser = argparse.ArgumentParser(description="屏幕学习助手")
    parser.add_argument("--preview", action="store_true", help="只预览界面，不注册快捷键")
    args = parser.parse_args()
    if sys.platform == "darwin":
        QApplication.setAttribute(Qt.AA_MacDontSwapCtrlAndMeta, True)
    app = QApplication(sys.argv[:1])
    app.setApplicationName("Screen Study Assistant")
    app.setOrganizationName("ScreenStudyAssistant")
    app.setQuitOnLastWindowClosed(False)
    # Prevent duplicate processes from competing for one native shortcut.
    server = QLocalServer()
    if not args.preview:
        socket = QLocalSocket()
        socket.connectToServer("screen-study-assistant-desktop")
        if socket.waitForConnected(300):
            socket.write(b"show")
            socket.waitForBytesWritten(300)
            return 0
        QLocalServer.removeServer("screen-study-assistant-desktop")
        if not server.listen("screen-study-assistant-desktop"):
            print("无法启动应用本地实例服务。", file=sys.stderr)
            return 1
    controller = Controller(app, preview=args.preview)

    def activate():
        socket = server.nextPendingConnection()
        if socket:
            controller.show_settings()
            socket.disconnectFromServer()
            socket.deleteLater()

    server.newConnection.connect(activate)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
