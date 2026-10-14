"""Synthetic choice/answer preview. --native tests glass over a colored backdrop."""

import argparse
import os
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QLinearGradient, QPainter
from PySide6.QtWidgets import QApplication, QWidget

from screen_study_assistant.ui import AnswerWindow

parser = argparse.ArgumentParser()
parser.add_argument("output", type=Path)
parser.add_argument("--native", action="store_true")
args = parser.parse_args()
if not args.native:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

QApplication.setAttribute(Qt.AA_MacDontSwapCtrlAndMeta, True)
app = QApplication([])
app.setApplicationName("Screen Study Preview")
args.output.mkdir(parents=True, exist_ok=True)


class Backdrop(QWidget):
    def paintEvent(self, event):
        painter = QPainter(self)
        gradient = QLinearGradient(0, 0, self.width(), self.height())
        gradient.setColorAt(0, QColor("#63ABCC"))
        gradient.setColorAt(0.5, QColor("#687ECD"))
        gradient.setColorAt(1, QColor("#C6A0C7"))
        painter.fillRect(self.rect(), gradient)
        for x in range(40, self.width(), 85):
            painter.fillRect(x, 0, 6, self.height(), QColor(255, 255, 255, 110))


backdrop = Backdrop()
backdrop.setWindowTitle("玻璃背景验证 · 合成画面")
backdrop.resize(740, 680)
backdrop.move(100, 70)
if args.native:
    backdrop.show()
window = AnswerWindow()
window.move(235, 120)
window.show()


def choices():
    window.reset()
    window.show_clarification("你想了解哪个领域的 MCP？", [
        "计算机 / AI 领域的 Model Context Protocol",
        "生物或医学领域的 MCP",
        "芯片领域的多芯片封装",
    ])


def answer(direction="计算机 / AI 领域的 Model Context Protocol"):
    window.start_answer("AI 领域的 MCP 协议是什么？")
    window.finish_answer(
        "**一句话理解**\n\nMCP 是连接 AI 应用与外部工具、数据的一种协议。\n\n"
        "**举个例子**\n\n你可以让 AI 应用通过统一接口查询日历，或读取你指定的文档。\n\n"
        "**你的选择**\n\n" + direction
    )
    window.saved.setText("预览 · 未保存笔记")


window.clarified.connect(answer)
choices()
app.processEvents()
window.grab().save(str(args.output / "澄清选项预览.png"))
if args.native:
    def ready():
        print("native_glass=" + str(window.native_glass), flush=True)

    QTimer.singleShot(1000, ready)
    raise SystemExit(app.exec())
answer()
app.processEvents()
window.grab().save(str(args.output / "整理问题回答预览.png"))
print("Rendered synthetic clarification and answer previews")
