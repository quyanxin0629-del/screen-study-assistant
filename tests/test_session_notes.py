"""One capture owns one note, even when background summaries complete late."""

import json
import os
from threading import Event

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import httpx
import pytest
from PySide6.QtCore import QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from screen_study_assistant.api import ApiError, ChatClient, StudyReply
from screen_study_assistant.config import ConfigStore, Settings
from screen_study_assistant.notes import NoteStore


def wait_until(predicate):
    for _ in range(500):
        if predicate():
            return
        QTest.qWait(10)
    assert predicate()


def test_note_organization_sends_only_current_completed_turns_and_preserves_math():
    turns = [{"question": "面积是多少？", "answer": r"面积是 $ab/2$。"},
             {"question": "面积公式如何推导？", "answer": "三角形是矩形的一半。"}]
    calls = []

    def handler(request):
        payload = json.loads(request.content)
        calls.append(payload)
        assert json.loads(payload["messages"][1]["content"]) == {"turns": turns}
        assert "最多500字" in payload["messages"][0]["content"]
        assert not payload["stream"]
        content = json.dumps({"question": "面积是多少，公式如何推导？",
                              "answer": r"面积为 $ab/2$，因为三角形是矩形的一半。"},
                             ensure_ascii=False)
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    client = ChatClient(Settings("https://test.invalid/v1", "model"),
                        transport=httpx.MockTransport(handler))
    result = client.summarize_note(turns, Event())
    assert result.question == "面积是多少，公式如何推导？"
    assert "$ab/2$" in result.answer and len(calls) == 1


@pytest.mark.parametrize("invalid", ["not json", "null", "[]",
                                     '{"question":"问题？","answer":""}',
                                     '{"question":1,"answer":"回答"}'])
def test_invalid_organization_cannot_be_used_to_replace_complete_notes(invalid):
    client = ChatClient(Settings("https://test.invalid/v1", "model"), transport=
                        httpx.MockTransport(lambda _: httpx.Response(200, json={
                            "choices": [{"message": {"content": invalid}}]})))
    with pytest.raises(ApiError):
        client.summarize_note([{"question": "问题？", "answer": "回答"}], Event())


@pytest.mark.parametrize("next_action", ["followup", "new_capture", "close", "error"])
def test_slow_note_organization_does_not_block_answers_or_mix_captures(
        tmp_path, monkeypatch, next_action):
    import screen_study_assistant.app as application

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(application, "ConfigStore", lambda: ConfigStore(tmp_path / "config"))
    monkeypatch.setattr(application, "recognize_details", lambda *_: "新截图材料")
    started, release = Event(), Event()
    summaries = []

    class MockClient:
        def __init__(self, *_):
            pass

        def study(self, messages, chunk, _cancel, **_kwargs):
            content = messages[-1]["content"]
            question, answer = {
                "再举例": ("什么是对比学习，能举例吗？", "两张猫照片的表示靠近。"),
                "有什么用途": ("对比学习有什么用途？", "用于学习图像表示。"),
            }.get(content, ("新概念是什么？", "新截图的答案。"))
            chunk(answer)
            return StudyReply("answer", question=question, answer=answer)

        def concept(self, *_):
            return None

        def summarize_note(self, turns, _cancel):
            summaries.append(turns)
            if len(turns) == 2:
                started.set()
                assert release.wait(5)
                if next_action == "error":
                    raise ApiError("simulated summary failure")
                return StudyReply("answer", question="对比学习是什么，能举例吗？",
                                  answer="合并：相似样本靠近，例如两张猫照片。")
            return StudyReply("answer", question="对比学习是什么，能举例并说明用途吗？",
                              answer="最新合并：猫照片靠近，用于图像表示。")

    monkeypatch.setattr(application, "ChatClient", MockClient)
    controller = application.Controller(app, preview=True)
    controller.settings = Settings("https://test.invalid/v1", "model", str(tmp_path / "notes"))
    controller.session_settings = controller.settings
    controller.session_key = "test-only"
    controller.concept_ready = True
    controller.text = "Contrastive Learning"
    controller.messages = [{"role": "user", "content": "材料"}]
    controller.answer.show()
    controller.answer.current_question = "什么是对比学习？"
    try:
        controller.answer_finished("让相似样本靠近。")
        wait_until(lambda: controller.qa_path is not None and not controller.io.pending)
        assert not summaries  # first answer uses the existing request, no extra note call
        controller.followup("再举例")
        wait_until(lambda: started.is_set() and not controller.busy and not controller.io.pending)
        assert controller.answer.send.isEnabled()
        path = NoteStore(controller.settings.notes_dir).qa_path
        fallback = path.read_text()
        assert "猫照片" in fallback and fallback.count("\n---\n") == 1
        if next_action == "followup":
            controller.followup("有什么用途")
            wait_until(lambda: "最新合并" in path.read_text() and not controller.io.pending)
            assert not controller.busy and controller.answer.send.isEnabled()
        elif next_action == "new_capture":
            controller.cancel_session()
            controller.process_capture(b"test-only", QPoint(30, 30))
            wait_until(lambda: "新截图的答案" in path.read_text() and not controller.io.pending)
        elif next_action == "close":
            controller.answer.close()
            assert not controller.answer.isVisible()
        release.set()
        wait_until(lambda: not controller.tasks and not controller.io.pending)
        body = path.read_text()
        assert body.count("\n---\n") == (2 if next_action == "new_capture" else 1)
        if next_action == "followup":
            assert "最新合并" in body and "合并：相似样本" not in body
            assert "已保存" == controller.answer.saved.text()
        elif next_action == "error":
            assert body == fallback
            assert "整理失败" in controller.answer.saved.text()
            assert controller.answer.send.isEnabled()
        else:
            assert "合并：" in body and "让相似样本靠近。" not in body
            if next_action == "new_capture":
                assert "新截图的答案" in body
        index = json.loads(NoteStore(controller.settings.notes_dir).index_path.read_text())
        assert len(index["entries"]) == (2 if next_action == "new_capture" else 1)
    finally:
        release.set()
        controller.quit()
        wait_until(lambda: not controller.tasks and not controller.io.pending)
        for widget in (controller.window, controller.answer, controller.launcher, controller.menu_bar):
            if widget:
                widget.deleteLater()
        controller.deleteLater()
