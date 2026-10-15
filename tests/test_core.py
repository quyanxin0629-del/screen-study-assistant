import json
from threading import Event

import httpx
import pytest

from screen_study_assistant.api import ApiError, Cancelled, ChatClient
from screen_study_assistant.config import ConfigStore, Settings, normalize_shortcut, normalize_url
from screen_study_assistant.notes import NoteStore, read_markdown, write_markdown


def test_endpoint_normalization_and_secret_rejection():
    assert normalize_url(" https://example.com/v1/chat/completions/ ") == "https://example.com/v1"
    assert normalize_url("http://localhost:8080/v1") == "http://localhost:8080/v1"
    for url in [
        "example.com",
        "ftp://example.com",
        "https://user:secret@example.com",
        "https://example.com?key=secret",
    ]:
        with pytest.raises(ValueError):
            normalize_url(url)


def test_shortcut_validation_and_saving_without_model(tmp_path):
    assert normalize_shortcut("Ctrl+Meta+Shift+k") == "Meta+Ctrl+Shift+K"
    assert normalize_shortcut("Alt+F8") == "Alt+F8"
    for shortcut in ["K", "Shift+K", "Meta+Shift+K, Meta+J", "Meta+Escape", "Ctrl+Ctrl+K"]:
        with pytest.raises(ValueError):
            normalize_shortcut(shortcut)
    store = ConfigStore(tmp_path)
    store.save(Settings(shortcut="Alt+Shift+L"))
    assert store.load().shortcut == "Alt+Shift+L"


def test_credentials_never_written_to_settings(tmp_path, monkeypatch):
    vault = {}
    monkeypatch.setattr(
        "keyring.set_password", lambda service, user, key: vault.update({(service, user): key})
    )
    monkeypatch.setattr("keyring.get_password", lambda service, user: vault.get((service, user)))
    monkeypatch.setattr(
        "keyring.delete_password", lambda service, user: vault.pop((service, user), None)
    )
    store = ConfigStore(tmp_path)
    settings = Settings("https://example.com/v1", "test-model", str(tmp_path / "notes"))
    store.save(settings, "test-secret-do-not-write")
    assert store.get_key(settings.api_url) == "test-secret-do-not-write"
    assert "test-secret" not in (tmp_path / "settings.json").read_text()
    assert store.load() == settings
    store.save(settings, clear_key=True)
    assert store.get_key(settings.api_url) == ""


def test_launcher_preference_round_trips_and_old_configs_default_to_enabled(tmp_path):
    store = ConfigStore(tmp_path)
    assert store.load().launcher_enabled
    path = tmp_path / "settings.json"
    path.write_text('{"model":"","shortcut":"Ctrl+Shift+K"}')
    assert store.load().launcher_enabled
    store.save(Settings(launcher_enabled=False))
    assert json.loads(path.read_text())["launcher_enabled"] is False
    assert store.load().launcher_enabled is False
    for invalid in ("false", 0, None):
        path.write_text(json.dumps({"launcher_enabled": invalid}))
        assert store.load().launcher_enabled is True
        with pytest.raises(ValueError, match="悬浮入口"):
            Settings(launcher_enabled=invalid).validate()


def test_chat_json_and_streaming_only_send_text():
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer test-only"
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=(
                'data: {"choices":[{"delta":{"content":"你好"}}]}\n\n'
                'data: {"choices":[{"delta":{"content":"世界"},"finish_reason":"stop"}]}\n\n'
                "data: [DONE]\n\n"
            ).encode(),
        )

    client = ChatClient(
        Settings("https://example.com/v1", "model"), "test-only", httpx.MockTransport(handler)
    )
    chunks = []
    assert (
        client.complete([{"role": "user", "content": "什么是过拟合"}], chunks.append, Event())
        == "你好世界"
    )
    assert chunks == ["你好", "世界"]
    assert requests[0]["messages"] == [{"role": "user", "content": "什么是过拟合"}]
    assert "image" not in json.dumps(requests)


def test_connection_test_nonstream_and_errors():
    client = ChatClient(
        Settings("https://example.com/v1", "model"),
        transport=httpx.MockTransport(
            lambda req: httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}]})
        ),
    )
    assert client.test(Event()) == "OK"
    client.transport = httpx.MockTransport(lambda req: httpx.Response(401))
    with pytest.raises(ApiError, match="鉴权失败"):
        client.test(Event())
    cancel = Event()
    cancel.set()
    with pytest.raises(Cancelled):
        client.test(cancel)


def test_truncated_stream_is_not_a_success():
    transport = httpx.MockTransport(
        lambda req: httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content='data: {"choices":[{"delta":{"content":"未完成"}}]}\n\n'.encode(),
        )
    )
    client = ChatClient(Settings("https://example.com/v1", "model"), transport=transport)
    with pytest.raises(ApiError, match="中断"):
        client.complete([], lambda _: None, Event())


def test_notes_deduplicate_encounters_preserve_personal_understanding(tmp_path):
    store = NoteStore(tmp_path)
    qa = store.append_qa("Contrastive Learning", "解释正文", "a" * 32, "2026-10-14 10:00:00")
    card = {
        "name": "对比学习",
        "aliases": ["Contrastive Learning"],
        "summary": "拉近相似样本",
        "explanation": "详细解释",
        "tags": ["机器学习"],
    }
    path, meta, body = store.upsert_concept(card, qa, qa_id="session-one")
    meta["status"] = "似懂非懂"
    body += "我自己的理解，不能覆盖。\n"
    write_markdown(path, meta, body)
    store.upsert_concept(card, qa, qa_id="session-one")
    assert len(read_markdown(path)[0]["encounters"]) == 1
    qa2 = store.append_qa("对比学习", "解释正文", "b" * 32, "2026-10-14 11:00:00")
    store.upsert_concept(card, qa2, qa_id="session-two")
    metadata, body = read_markdown(path)
    assert len(metadata["encounters"]) == 2
    assert metadata["status"] == "似懂非懂"
    assert "我自己的理解" in body
    assert len(list((tmp_path / "知识图鉴").glob("*.md"))) == 1
    assert store.find_concept("contrastive learning") is not None
    assert store.find_concept("论文中使用了 contrastive learning 进行训练") is None
    store.append_qa("举例", "例子", "c" * 32, "2026-10-14 11:01:00")
    assert "例子" in qa2.read_text()
    assert qa == qa2 == tmp_path / "学习笔记.md"
    assert all(p.suffix == ".md" or p == store.index_path
               for p in tmp_path.rglob("*") if p.is_file())


def test_same_name_ambiguous_concepts_are_not_auto_merged(tmp_path):
    store = NoteStore(tmp_path)
    for name, identifier in [("计算机缓存", "one"), ("地理缓存", "two")]:
        write_markdown(
            tmp_path / "知识图鉴" / f"{identifier}.md",
            {"id": identifier, "name": name, "aliases": ["cache"]},
            "正文",
        )
    assert store.find_concept("cache") is None


def test_one_markdown_notebook_appends_bold_questions_preserves_manual_edits(tmp_path):
    store = NoteStore(tmp_path)
    store.qa_path.write_text("我手动写的开头。\n", encoding="utf-8")
    store.append_qa("你是谁？", "这是回答。", "d" * 32, "2026-10-14 12:00:00")
    prefix = store.qa_path.read_text(encoding="utf-8")
    store.append_qa("再举个例子？", "一个例子。", "e" * 32, "2026-10-14 12:01:00")
    content = store.qa_path.read_text(encoding="utf-8")
    assert content.startswith(prefix)
    assert "**你是谁？**\n\n这是回答。" in content
    assert "**再举个例子？**" in content
    assert "## 问题" not in content and "## 回答" not in content
    store.append_qa("你是谁？", "这是回答。", "d" * 32, "2026-10-14 12:00:00")
    assert store.qa_path.read_text(encoding="utf-8") == content
    assert list(tmp_path.glob("*.md")) == [store.qa_path]


def test_keychain_is_read_once_per_endpoint_and_cache_is_memory_only(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "keyring.get_password", lambda service, url: calls.append(url) or "test-memory-key"
    )
    monkeypatch.setattr("keyring.set_password", lambda *args: None)
    monkeypatch.setattr("keyring.delete_password", lambda *args: None)
    store = ConfigStore(tmp_path)
    for _ in range(5):
        assert store.get_key("https://example.com/v1/chat/completions") == "test-memory-key"
    assert calls == ["https://example.com/v1"]
    store.save(Settings("https://example.com/v1", "model"), key="new-test-key")
    assert store.get_key("https://example.com/v1") == "new-test-key"
    assert len(calls) == 1
    assert "new-test-key" not in (tmp_path / "settings.json").read_text()
    store.save(Settings("https://example.com/v1", "model"), clear_key=True)
    assert store.get_key("https://example.com/v1") == ""
    assert len(calls) == 1
    store.get_key("https://other.invalid/v1")
    assert len(calls) == 2
    store.forget_key()
    store.get_key("https://other.invalid/v1")
    assert len(calls) == 3
