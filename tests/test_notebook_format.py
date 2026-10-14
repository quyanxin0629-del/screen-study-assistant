import json

import pytest

from screen_study_assistant.notes import NoteStore, format_note_answer, format_note_question


def test_notes_reduce_heading_sizes_and_use_editor_math_delimiters():
    source = "# 答案\n\n若问全部平面，则为：\n\\[\\boxed{5}\\]\n\n## 解释\n\n行内 \\(x^2\\)。"
    result = format_note_answer(source)
    assert result == "**答案**\n\n若问全部平面，则为：\n\n$$\n\\boxed{5}\n$$\n\n**解释**\n\n行内 $x^2$。"
    assert format_note_answer(result) == result
    question = format_note_question("面积 \\(x^2\\) 如何计算？\n条件是 a > 0。")
    assert "$x^2$" in question and "**如何计算？**" in question
    assert "  \n" in question and "\\>" in question


def test_formatting_leaves_code_and_currency_intact():
    source = "## 示范\n\n```latex\n# 标题\n\\[\\boxed{5}\\]\n```\n\n`# 代码 $x$`，价格 $5 和 $10。"
    result = format_note_answer(source)
    assert result.startswith("**示范**")
    assert "```latex\n# 标题\n\\[\\boxed{5}\\]\n```" in result
    assert "`# 代码 $x$`，价格 $5 和 $10。" in result


def test_other_heading_styles_and_question_line_breaks():
    assert format_note_answer("答案\n===\n\n<h1>说明</h1>") == "**答案**\n\n**说明**"
    question = format_note_question("条件：\n\\(x^2\\)\n求面积。")
    assert question == "**条件：**  \n$x^2$  \n**求面积。**"


def test_note_index_is_hidden_and_same_content_with_new_id_still_appends(tmp_path):
    store = NoteStore(tmp_path)
    args = ("问题", "## 小标题\n\n[ \\boxed{2} ]")
    store.append_qa(*args, "a" * 32, "2026-10-14 15:00:00")
    store.append_qa(*args, "b" * 32, "2026-10-14 15:00:00")
    text = store.qa_path.read_text()
    assert "entry:" not in text and "a" * 32 not in text
    assert text.count("**问题**") == 2 and text.count(r"\boxed{2}") == 2
    assert "## 小标题" not in text
    assert store.index_path.name.startswith(".")
    store.append_qa(*args, "a" * 32, "2026-10-14 15:00:00")
    assert store.qa_path.read_text() == text


def test_migrate_old_visible_markers_and_keep_manual_intro_backup_and_dedup(tmp_path):
    store = NoteStore(tmp_path)
    original = "# 我手动写的开头\n\n" + (
        f"<!-- entry:{'c' * 32} -->\n*2026-10-14 14:39:58*\n\n**问题**\n\n"
        "# 答案\n\n\\[\\boxed{5}\\]\n\n---\n"
    )
    store.qa_path.write_text(original)
    store.prepare_notebook()
    text = store.qa_path.read_text()
    assert text.startswith("# 我手动写的开头\n\n")
    assert "entry:" not in text and "# 答案" not in text
    assert "**答案**" in text and "$$\n\\boxed{5}\n$$" in text
    assert (tmp_path / ".学习笔记排版前备份.md").read_text() == original
    store.prepare_notebook()
    assert store.qa_path.read_text() == text
    store.append_qa("问题", "旧答案", "c" * 32, "2026-10-14 14:39:58")
    assert store.qa_path.read_text() == text


def test_legacy_looking_code_sample_is_not_removed(tmp_path):
    store = NoteStore(tmp_path)
    original = f"```md\n<!-- entry:{'d' * 32} -->\n*2026-10-14 14:39:58*\n```\n"
    store.qa_path.write_text(original)
    store.prepare_notebook()
    assert store.qa_path.read_text() == original


def test_retry_after_notebook_write_before_index_commit_does_not_duplicate(tmp_path, monkeypatch):
    store = NoteStore(tmp_path)
    save_index = store._save_index
    calls = []

    def fail_second_save(index):
        calls.append(True)
        if len(calls) == 2:
            raise OSError("simulated interrupted index commit")
        save_index(index)

    monkeypatch.setattr(store, "_save_index", fail_second_save)
    with pytest.raises(OSError):
        store.append_qa("问题", "回答", "e" * 32, "2026-10-14 15:00:00")
    text = store.qa_path.read_text()
    assert json.loads(store.index_path.read_text())["entries"]["e" * 32]["state"] == "pending"
    # A new process/store recovers the durable write from its offset and hash.
    NoteStore(tmp_path).append_qa("问题", "回答", "e" * 32, "2026-10-14 15:00:00")
    assert store.qa_path.read_text() == text


def test_partial_write_never_overwrites_a_manual_edit(tmp_path):
    store = NoteStore(tmp_path)
    store.index_path.write_text(json.dumps({"version": 1, "entries": {
        "f" * 32: {"state": "pending", "offset": 0, "hash": None}
    }}))
    store.qa_path.write_text("手动编辑，必须保留")
    with pytest.raises(OSError):
        store.append_qa("问题", "回答", "f" * 32, "2026-10-14 15:00:00")
    assert store.qa_path.read_text() == "手动编辑，必须保留"


def test_capture_followups_replace_one_entry_without_changing_other_captures(tmp_path):
    store = NoteStore(tmp_path)
    stamp = "2026-10-14 15:00:00"
    store.save_session("什么是对比学习？", "初始答案", "a" * 32, stamp, 1)
    store.save_session("面积是多少？", r"\[\boxed{5}\]", "b" * 32, stamp, 1)
    other = store.qa_path.read_text().split("\n---\n")[1]
    store.qa_path.write_bytes("# 我的笔记\r\n".encode() + store.qa_path.read_bytes())
    store.save_session("什么是对比学习？能举例吗？", "## 解释\n\n合并后的答案",
                       "a" * 32, stamp, 2, organized=True)
    text = store.qa_path.read_text()
    assert text.startswith("# 我的笔记\n")
    assert store.qa_path.read_bytes().startswith("# 我的笔记\r\n".encode())
    assert "初始答案" not in text and "合并后的答案" in text
    assert text.count("\n---\n") == 2
    assert text.split("\n---\n")[1] == other
    assert "**什么是对比学习？能举例吗？**" in text
    assert "## 解释" not in text and r"\boxed{5}" in text
    assert len(json.loads(store.index_path.read_text())["entries"]) == 2


def test_late_summaries_and_repeated_writes_cannot_undo_newer_followups(tmp_path):
    store = NoteStore(tmp_path)
    args = ("a" * 32, "2026-10-14 15:00:00")
    store.save_session("问题一和二？", "两轮完整内容", *args, 2)
    store.save_session("问题一二三？", "最新内容", *args, 3)
    store.save_session("问题一和二？", "迟到的摘要", *args, 2, organized=True)
    assert "迟到" not in store.qa_path.read_text()
    store.save_session("整理的问题？", "最新整合", *args, 3, organized=True)
    text = store.qa_path.read_text()
    store.save_session("问题一二三？", "未整理版本", *args, 3)
    store.save_session("整理的问题？", "重复", *args, 3, organized=True)
    assert store.qa_path.read_text() == text
    assert text.count("\n---\n") == 1


@pytest.mark.parametrize("interrupt_before_replace", [False, True])
def test_session_update_recovers_after_interruption_without_duplicate_entries(
        tmp_path, monkeypatch, interrupt_before_replace):
    store = NoteStore(tmp_path)
    args = ("a" * 32, "2026-10-14 15:00:00")
    store.save_session("问题？", "原答案", *args, 1)
    original = store._save_index
    calls = []

    def interrupt(index):
        calls.append(True)
        if len(calls) == 2:
            raise OSError("interrupted final index save")
        original(index)

    def interrupt_replace(_text):
        raise OSError("interrupted atomic replace")

    if interrupt_before_replace:
        monkeypatch.setattr(store, "_replace_notebook", interrupt_replace)
    else:
        monkeypatch.setattr(store, "_save_index", interrupt)
    with pytest.raises(OSError):
        store.save_session("问题和追问？", "整合的答案", *args, 2, organized=True)
    recovered = NoteStore(tmp_path)
    recovered.prepare_notebook()
    recovered.save_session("问题和追问？", "整合的答案", *args, 2, organized=True)
    text = recovered.qa_path.read_text()
    assert "原答案" not in text and "整合的答案" in text
    assert text.count("\n---\n") == 1
    assert "pending" not in json.loads(recovered.index_path.read_text())["entries"]["a" * 32]


def test_session_update_preserves_manually_edited_current_entry(tmp_path):
    store = NoteStore(tmp_path)
    args = ("a" * 32, "2026-10-14 15:00:00")
    store.save_session("问题？", "原答案", *args, 1)
    store.qa_path.write_text(store.qa_path.read_text().replace("原答案", "我的理解"))
    text = store.qa_path.read_text()
    with pytest.raises(OSError):
        store.save_session("更多问题？", "模型新内容", *args, 2)
    assert store.qa_path.read_text() == text
