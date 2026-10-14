"""Render the formula fix and notebook layout with synthetic data, offline."""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from screen_study_assistant.notes import NoteStore
from screen_study_assistant.ui import AnswerWindow

app = QApplication([])
output = Path(sys.argv[1])
output.mkdir(parents=True, exist_ok=True)
source = (
    "## 答案\n\n第一种问法的结果：\n\\[\\boxed{5}\\]\n\n"
    "另一种问法的结果：\n[ \\boxed{2} ]\n\n"
    "### 公式示例\n\n盒子里也可以放分数：\n\\[\\boxed{\\frac{5}{2}}\\]\n\n"
    "行内公式 \\(x^2 + y^2 = z^2\\) 与正文一起显示。"
)
answer = AnswerWindow()
answer.show()
app.processEvents()
answer.start_answer("解释这段内容")
answer.finish_answer(source)
answer.saved.setText("已保存")
answer.browser.verticalScrollBar().setValue(0)
app.processEvents()
answer.grab().save(str(output / "公式悬浮窗.png"))

notes = NoteStore(output / "笔记排版示例")
notes.append_qa("怎样理解这些结论？", source, "0" * 32, "2026-10-14 15:00:00")
note_view = AnswerWindow()
note_view.resize(560, 660)
note_view.show()
app.processEvents()
note_view.start_answer("解释这段内容")
note_view.finish_answer(notes.qa_path.read_text(encoding="utf-8"))
note_view.browser.verticalScrollBar().setValue(0)
note_view.question.hide()
note_view.send.hide()
app.processEvents()
note_view.grab().save(str(output / "笔记排版预览.png"))
print("Rendered offline formula and notebook previews")
