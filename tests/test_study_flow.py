"""Exercise routing, streamed answers, user choices and actual note persistence."""

import json
import os
from threading import Event

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import httpx
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from screen_study_assistant.api import ApiError, ChatClient, StudyStream
from screen_study_assistant.config import Settings
from screen_study_assistant.notes import NoteStore
from screen_study_assistant.ui import AnswerWindow


def envelope(meta, body=""):
    return "<study>" + json.dumps(meta, ensure_ascii=False) + "</study>\n" + body


def test_routing_handles_every_stream_split_without_exposing_metadata():
    answer = r"面积是 $\frac{1}{2}ab$。" + "\n\n```python\nprint('ok')\n```"
    question = "已知直角三角形两直角边为 a、b，面积是多少？"
    raw = envelope({"action": "answer", "question": question}, answer)
    for split in range(1, len(raw)):
        chunks = []
        parser = StudyStream(chunks.append)
        parser.feed(raw[:split])
        parser.feed(raw[split:])
        result = parser.finish()
        assert result.question == question
        assert result.answer == answer
        assert "".join(chunks).strip() == answer


def test_clarification_never_streams_a_guessed_answer():
    chunks = []
    parser = StudyStream(chunks.append)
    parser.feed(envelope({"action": "clarify", "prompt": "你指的是哪个领域？",
                          "options": ["计算机 / AI", "生物 / 医学"]}, "不应显示的猜测"))
    result = parser.finish()
    assert result.options == ("计算机 / AI", "生物 / 医学")
    assert not chunks and not result.answer


@pytest.mark.parametrize("raw", [
    "直接猜测的答案",
    '<study>{"action":"answer","question":""}</study>答案',
    '<study>{"action":"clarify","prompt":"哪种？","options":["重复","重复"]}</study>',
    '<study>{"action":"answer"',
    '<study>{"action":"answer","question":"什么是缓存？"}</study>',
])
def test_invalid_or_incomplete_model_result_cannot_be_saved_as_an_answer(raw):
    parser = StudyStream(lambda _: None)
    with pytest.raises(ApiError):
        parser.feed(raw)
        parser.finish()


@pytest.mark.parametrize("stream", [True, False])
def test_chat_routing_uses_one_request_for_question_and_answer(stream):
    calls = []
    raw = envelope({"action": "answer", "question": "什么是对比学习？"}, "让相似样本靠近。")

    def handler(request):
        calls.append(json.loads(request.content))
        if not stream:
            return httpx.Response(200, json={"choices": [{"message": {"content": raw}}]})
        events = []
        for index in range(0, len(raw), 3):
            events.append("data: " + json.dumps({"choices": [
                {"delta": {"content": raw[index:index + 3]}}
            ]}, ensure_ascii=False) + "\n\n")
        events.append('data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n')
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              content="".join(events).encode())

    client = ChatClient(Settings("https://test.invalid/v1", "model"),
                        transport=httpx.MockTransport(handler))
    chunks = []
    reply = client.study([{"role": "user", "content": "Contrastive Learning"}],
                         chunks.append, Event())
    assert reply.question == "什么是对比学习？"
    assert "".join(chunks).strip() == reply.answer == "让相似样本靠近。"
    assert len(calls) == 1
    assert calls[0]["stream"] is True


def wait_until(predicate):
    for _ in range(250):
        if predicate():
            return
        QTest.qWait(10)
    assert predicate()


@pytest.mark.parametrize("custom", [False, True])
def test_choices_continue_answer_and_save_only_confirmed_question(tmp_path, monkeypatch, custom):
    import screen_study_assistant.app as application
    from screen_study_assistant.config import ConfigStore

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(application, "ConfigStore", lambda: ConfigStore(tmp_path / "config"))
    calls = []
    direction = "芯片领域的多芯片封装" if custom else "计算机 / AI 领域的 MCP"
    question = "什么是多芯片封装 MCP？" if custom else "AI 领域的 MCP 协议是什么？"
    options = ["计算机 / AI 领域的 MCP", "生物 / 医学领域的 MCP"]

    def handler(request):
        messages = json.loads(request.content)["messages"]
        calls.append(messages)
        if len(calls) == 1:
            result = envelope({"action": "clarify", "prompt": "MCP 指哪个领域？",
                               "options": options})
        else:
            assert direction in messages[-1]["content"]
            result = envelope({"action": "answer", "question": question}, "这是确认方向后的回答。")
        return httpx.Response(200, json={"choices": [{"message": {"content": result}}]})

    class MockClient(ChatClient):
        def __init__(self, settings, key=""):
            super().__init__(settings, key, httpx.MockTransport(handler))

    monkeypatch.setattr(application, "ChatClient", MockClient)
    controller = application.Controller(app, preview=True)
    controller.settings = Settings("https://test.invalid/v1", "test-model", str(tmp_path / "notes"))
    controller.session_settings = controller.settings
    controller.session_key = "test-only"
    controller.concept_ready = True
    controller.answer.show()
    try:
        controller.ocr_finished("MCP")
        wait_until(lambda: controller.pending_clarification is not None and not controller.tasks)
        assert len(controller.answer.choice_buttons) == 2
        assert controller.answer.custom_direction.isVisible()
        assert controller.answer.custom_direction.parent() is controller.answer.custom_choice
        assert not controller.qa_path
        assert not NoteStore(controller.settings.notes_dir).qa_path.exists()
        assert not controller.answer.turns
        if custom:
            controller.answer.custom_direction.setText(direction)
            QTest.keyClick(controller.answer.custom_direction, Qt.Key_Return)
        else:
            QTest.mouseClick(controller.answer.choice_buttons[0], Qt.LeftButton)
        wait_until(lambda: controller.qa_path is not None and not controller.tasks
                   and not controller.io.pending)
        body = controller.qa_path.read_text(encoding="utf-8")
        assert f"**{question}**" in body
        assert "**MCP**" not in body
        assert "这是确认方向后的回答。" in body
        assert "<study>" not in body and '"action"' not in body
        assert "---" in body
        assert len(controller.answer.turns) == 1
        assert len(calls) == 2
        assert controller.answer.send.isEnabled()
        assert not controller.answer.clarification_active
    finally:
        controller.quit()
        wait_until(lambda: not controller.tasks and not controller.io.pending)
        for widget in (controller.window, controller.answer, controller.launcher, controller.menu_bar):
            if widget:
                widget.deleteLater()
        controller.deleteLater()


def test_close_or_reset_dismisses_pending_choices_without_submitting():
    app = QApplication.instance() or QApplication([])
    window = AnswerWindow()
    selected = []
    window.clarified.connect(selected.append)
    window.show()
    window.show_clarification("哪个领域？", ["AI", "医学"])
    assert window.custom_direction.isVisible()
    assert not window.custom_confirm.isEnabled()
    QTest.keyClick(window.custom_direction, Qt.Key_Return)
    assert not selected
    window.reset()
    app.processEvents()
    assert not window.clarification_active and not window.choice_buttons
    assert window.browser.isVisible()
    assert not selected
    window.close()
    window.deleteLater()


def test_answer_after_choice_instructs_model_to_answer_without_reasking():
    calls = []

    def handler(request):
        payload = json.loads(request.content)
        calls.append(payload)
        assert "不允许再次反问" in payload["messages"][0]["content"]
        result = envelope({"action": "answer", "question": "什么是苹果 iOS？"},
                          "iOS 是苹果手机使用的操作系统。原文的其他部分不足以确定。")
        return httpx.Response(200, json={"choices": [{"message": {"content": result}}]})

    client = ChatClient(Settings("https://test.invalid/v1", "model"),
                        transport=httpx.MockTransport(handler))
    result = client.study([{"role": "user", "content": "已确认方向：苹果 iOS"}],
                          lambda _: None, Event(), allow_clarification=False)
    assert result.action == "answer" and len(calls) == 1


@pytest.mark.parametrize("repair_succeeds", [True, False])
def test_second_clarification_is_repaired_once_and_never_exposed(repair_succeeds):
    calls, chunks = [], []

    def handler(request):
        calls.append(json.loads(request.content))
        meta = {"action": "clarify", "prompt": "还要问一次？", "options": ["A", "B"]}
        body = ""
        if len(calls) == 2 and repair_succeeds:
            meta = {"action": "answer", "question": "怎样理解已确认的 iOS？"}
            body = "以下只解释能够确认的概念。"
        return httpx.Response(200, json={"choices": [{"message": {
            "content": envelope(meta, body)
        }}]})

    client = ChatClient(Settings("https://test.invalid/v1", "model"),
                        transport=httpx.MockTransport(handler))
    if repair_succeeds:
        result = client.study([], chunks.append, Event(), allow_clarification=False)
        assert result.action == "answer"
        assert "".join(chunks).strip() == result.answer
    else:
        with pytest.raises(ApiError):
            client.study([], chunks.append, Event(), allow_clarification=False)
        assert not chunks
    assert len(calls) == 2
    assert "还要问一次" not in "".join(chunks)
