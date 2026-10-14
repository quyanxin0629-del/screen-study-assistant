"""Render product UI with synthetic data, without keys, network or screen capture."""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from screen_study_assistant.config import Settings
from screen_study_assistant.ui import AnswerWindow, SettingsWindow

QApplication.setAttribute(Qt.AA_MacDontSwapCtrlAndMeta, True)
app = QApplication([])
output = Path(sys.argv[1])
output.mkdir(parents=True, exist_ok=True)
settings = SettingsWindow(Settings(), "⌘ ⇧ K")
settings.hotkey_status.setText("快捷键已就绪 · 关闭此窗口后仍在菜单栏运行")
settings.show()
app.processEvents()
settings.grab().save(str(output / "模型设置页.png"))
answer = AnswerWindow()
answer.show()
answer.source.setPlainText("Contrastive Learning")
answer.start_answer("什么是对比学习？")
answer.finish_answer(
    "**一句话理解**\n\n让相似的样本靠近，让不同的样本远离，从而学习数据的表示。\n\n"
    "### 用照片来打个比方\n\n同一只猫的两张照片，角度和光线可能不同，但模型应该把它们看作相似。"
    "猫与汽车的照片，则应该有不同的表示。\n\n"
    "### 它能帮你做什么\n\n即使没有给每张图片标注类别，模型也能从这些相似关系中学到有用的特征。"
)
answer.saved.setText("已保存")
answer.encounter.setText("第 3 次遇见「对比学习」 · 似懂非懂")
answer.encounter.show()
app.processEvents()
answer.grab().save(str(output / "回答悬浮窗.png"))
print("Rendered settings and floating answer previews")
