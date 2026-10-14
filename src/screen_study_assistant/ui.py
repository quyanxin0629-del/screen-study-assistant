"""A single iOS-inspired settings page and a dismissible answer panel."""

from __future__ import annotations

import sys
import uuid

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt, QUrl, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QGuiApplication,
    QIcon,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextImageFormat,
)
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QKeySequenceEdit,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from .config import Settings
from .glass import GlassWindow
from .math_rendering import MathRenderer
from .math_text import Formula, split_formulas
from .notes import format_question

STYLE = """
QWidget { color: #20232C; font-family: 'SF Pro Display', 'PingFang SC', sans-serif; font-size: 13px; }
QWidget#settings { background: #F4F5F8; }
QScrollArea { border: none; background: transparent; }
QScrollArea > QWidget > QWidget { background: transparent; }
QLabel { background: transparent; }
QLabel#eyebrow { color: #858B9A; font-size: 11px; font-weight: 600; }
QLabel#hero { font-size: 33px; font-weight: 700; color: #161C2A; }
QLabel#subtitle { color: #818797; font-size: 13px; }
QLabel#section { font-size: 11px; font-weight: 600; color: #8A8F9C; }
QLabel#cardTitle { font-size: 16px; font-weight: 600; }
QLabel#muted { color: #8A8F9C; font-size: 11px; }
QLabel#badge { background: #E9F5EE; color: #438265; border-radius: 10px; padding: 4px 10px; font-size: 10px; }
QFrame#card { background: white; border: 1px solid #E8EAF0; border-radius: 19px; }
QFrame#divider { background: #EFF0F4; border: none; max-height: 1px; }
QLineEdit { border: 1px solid #E7E9EF; border-radius: 10px; padding: 10px 12px; background: #F8F9FC; selection-background-color: #DCE8FF; }
QLineEdit:focus { border: 1px solid #719EFA; background: #FFFFFF; }
QPushButton { background: #EFF2F8; border: none; border-radius: 11px; padding: 10px 15px; font-weight: 500; }
QPushButton:hover { background: #E6EAF3; }
QPushButton:pressed { background: #DDE3EF; }
QPushButton:disabled { color: #A4A8B3; background: #EFF0F4; }
QPushButton#primary { background: #3478F6; color: white; }
QPushButton#primary:hover { background: #246BE9; }
QPushButton#primary:disabled { background: #AEC9FA; color: white; }
QPushButton#link { background: transparent; color: #3478F6; padding: 3px 0; font-size: 11px; }
QKeySequenceEdit { background: #F0F3FA; border: 1px solid #E3E7F1; border-radius: 10px; padding: 3px; min-width: 135px; }
QKeySequenceEdit QLineEdit { background: transparent; border: none; color: #53627C; padding: 5px; font-size: 14px; }
QPushButton#icon { background: #F2F4F8; border-radius: 13px; padding: 0; min-width: 26px; max-width: 26px; min-height: 26px; max-height: 26px; font-size: 17px; color: #747C8D; }
QPushButton#icon:hover { background: #E8EBF2; }
QLabel#shortcut { background: #F0F3FA; border: 1px solid #E3E7F1; border-radius: 9px; padding: 6px 11px; color: #53627C; font-size: 15px; font-weight: 600; }
QWidget#answer, QWidget#launcher { background: transparent; }
QWidget#answer QWidget, QWidget#launcher QWidget { background: transparent; }
QWidget#answer QPushButton#primary, QWidget#launcher QPushButton#primary { background: #3478F6; color: white; }
QWidget#answer QPushButton#primary:disabled { background: #AEC9FA; color: white; }
QWidget#launcher QPushButton { background: rgba(255,255,255,155); }
QWidget#answer QPushButton#icon { background: rgba(255,255,255,150); }
QWidget#answer QLineEdit { background: rgba(255,255,255,170); border-color: rgba(255,255,255,220); border-radius: 17px; }
QWidget#answer QTextBrowser { background: transparent; border: none; border-radius: 16px; padding: 8px 4px; }
QWidget#answer QPushButton#choice { background: rgba(255,255,255,65); border: 1px solid rgba(255,255,255,150); border-radius: 16px; padding: 0; }
QWidget#answer QPushButton#choice:hover { background: rgba(255,255,255,125); border-color: rgba(75,120,220,90); }
QWidget#answer QPushButton#choice:pressed { background: rgba(225,234,255,150); }
QWidget#answer QPushButton#link { color: #677183; }
QWidget#answer QLabel#muted { color: #687080; }
QWidget#answer QPlainTextEdit { background: rgba(255,255,255,155); }
QComboBox { padding: 8px 12px; background: #F0F3FA; border: 1px solid #E3E7F1; border-radius: 10px; }
QFrame#answerHeader { background: transparent; border: none; }
QTextBrowser { background: white; border: 1px solid #E9EDF4; border-radius: 14px; padding: 14px; font-size: 14px; }
QPlainTextEdit { border: 1px solid #E4E8F0; border-radius: 11px; background: #FFFFFF; padding: 8px; }
QScrollBar:vertical { border: none; background: transparent; width: 5px; margin: 6px 0; }
QScrollBar::handle:vertical { background: #D3D8E3; border-radius: 2px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
"""


def label(text, name=None, wrap=False):
    result = QLabel(text)
    if name:
        result.setObjectName(name)
    result.setWordWrap(wrap)
    return result


def button(text, name=None):
    result = QPushButton(text)
    if name:
        result.setObjectName(name)
    result.setCursor(Qt.PointingHandCursor)
    return result


def icon_pixmap(size=64):
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.scale(size / 64, size / 64)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor("#3478F6"))
    painter.drawRoundedRect(0, 0, 64, 64, 17, 17)
    painter.setPen(QPen(QColor("white"), 2.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    for x, y, dx, dy in [
        (17, 20, 10, 10),
        (47, 20, -10, 10),
        (17, 44, 10, -10),
        (47, 44, -10, -10),
    ]:
        painter.drawLine(x, y, x + dx, y)
        painter.drawLine(x, y, x, y + dy)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor("white"))
    path = QPainterPath()
    path.moveTo(32, 23)
    path.lineTo(34.5, 29.5)
    path.lineTo(41, 32)
    path.lineTo(34.5, 34.5)
    path.lineTo(32, 41)
    path.lineTo(29.5, 34.5)
    path.lineTo(23, 32)
    path.lineTo(29.5, 29.5)
    path.closeSubpath()
    painter.drawPath(path)
    painter.end()
    return pixmap


class ShortcutEdit(QKeySequenceEdit):
    recording_changed = Signal(bool)

    def __init__(self, sequence):
        super().__init__(sequence)
        self.installEventFilter(self)
        self.findChild(QLineEdit).installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.FocusIn:
            self.recording_changed.emit(True)
        elif event.type() == QEvent.FocusOut:
            self.recording_changed.emit(False)
        return super().eventFilter(watched, event)


class SettingsWindow(QWidget):
    save_requested = Signal()
    test_requested = Signal()
    clear_requested = Signal()
    directory_requested = Signal()
    notes_requested = Signal()
    hidden = Signal()

    def __init__(self, settings: Settings, shortcut: str):
        super().__init__()
        self.setObjectName("settings")
        self.setWindowTitle("屏幕学习助手 · 模型设置")
        self.setWindowIcon(QIcon(icon_pixmap()))
        self.setMinimumWidth(510)
        self.resize(590, 805)
        self.setStyleSheet(STYLE)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)
        content = QWidget()
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(32, 25, 32, 20)
        layout.setSpacing(12)

        brand = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(icon_pixmap(34))
        logo.setFixedSize(34, 34)
        brand.addWidget(logo)
        brand.addSpacing(3)
        names = QVBoxLayout()
        names.setSpacing(1)
        names.addWidget(label("屏幕学习助手", "cardTitle"))
        names.addWidget(label("SCREEN STUDY", "eyebrow"))
        brand.addLayout(names)
        brand.addStretch()
        brand.addWidget(label("本地笔记", "badge"))
        layout.addLayout(brand)
        layout.addSpacing(2)
        layout.addWidget(label("随手一框，读懂一点。", "hero"))
        layout.addWidget(label("从一个陌生名词，到自己的知识。", "subtitle"))

        layout.addWidget(label("模型连接", "section"))
        card = QFrame()
        card.setObjectName("card")
        fields = QVBoxLayout(card)
        fields.setContentsMargins(20, 18, 20, 18)
        fields.setSpacing(8)
        heading = QHBoxLayout()
        heading.addWidget(label("连接你的 AI", "cardTitle"))
        heading.addStretch()
        heading.addWidget(label("文本接口", "muted"))
        fields.addLayout(heading)
        fields.addWidget(
            label("支持 Chat Completions 兼容接口，使用自己的模型与密钥。", "muted", True)
        )
        fields.addSpacing(2)
        fields.addWidget(label("API URL"))
        self.url = QLineEdit(settings.api_url)
        self.url.setObjectName("api_url")
        self.url.setPlaceholderText("https://your-provider.com/v1")
        self.url.setClearButtonEnabled(True)
        fields.addWidget(self.url)
        fields.addWidget(
            label("填写基础地址；也可以粘贴完整的 /chat/completions 地址。", "muted", True)
        )
        fields.addWidget(label("API Key"))
        keyrow = QHBoxLayout()
        self.key = QLineEdit()
        self.key.setObjectName("api_key")
        self.key.setEchoMode(QLineEdit.Password)
        self.key.setPlaceholderText("填写 API Key，本地免鉴权服务可留空")
        keyrow.addWidget(self.key)
        self.show_key = button("显示")
        self.show_key.setFixedWidth(59)
        self.show_key.clicked.connect(self.toggle_key)
        keyrow.addWidget(self.show_key)
        fields.addLayout(keyrow)
        keyhelp = QHBoxLayout()
        self.key_state = label("密钥保存在系统钥匙串。", "muted")
        keyhelp.addWidget(self.key_state)
        keyhelp.addStretch()
        self.clear_key = button("清除已存密钥", "link")
        self.clear_key.clicked.connect(self.clear_requested)
        keyhelp.addWidget(self.clear_key)
        fields.addLayout(keyhelp)
        fields.addWidget(label("模型名称"))
        self.model = QLineEdit(settings.model)
        self.model.setObjectName("model")
        self.model.setPlaceholderText("填写服务商提供的模型 ID")
        self.model.setClearButtonEnabled(True)
        fields.addWidget(self.model)
        actions = QHBoxLayout()
        self.test_button = button("测试连接")
        self.save_button = button("保存设置", "primary")
        self.test_button.clicked.connect(self.test_requested)
        self.save_button.clicked.connect(self.save_requested)
        actions.addWidget(self.test_button, 1)
        actions.addWidget(self.save_button, 1)
        fields.addLayout(actions)
        self.status = label("测试会发送一次简短文本请求，可能产生少量费用。", "muted", True)
        self.status.setObjectName("connection_status")
        fields.addWidget(self.status)
        layout.addWidget(card)

        shortcut_card = QFrame()
        shortcut_card.setObjectName("card")
        shortcut_layout = QVBoxLayout(shortcut_card)
        shortcut_layout.setContentsMargins(20, 16, 20, 16)
        shortcut_layout.setSpacing(10)
        shortcut_top = QHBoxLayout()
        shortcut_titles = QVBoxLayout()
        shortcut_titles.setSpacing(3)
        shortcut_titles.addWidget(label("随时框选，立即解答", "cardTitle"))
        shortcut_titles.addWidget(label("在任意软件按下快捷键，拖动选择文字。", "muted"))
        shortcut_top.addLayout(shortcut_titles)
        shortcut_top.addStretch()
        self.shortcut = ShortcutEdit(QKeySequence(settings.shortcut))
        self.shortcut.setMaximumSequenceLength(1)
        self.shortcut.setClearButtonEnabled(True)
        self.shortcut.setFixedWidth(160)
        self.shortcut.setToolTip("点击后按下新的组合键，保存设置后生效")
        shortcut_top.addWidget(self.shortcut)
        shortcut_layout.addLayout(shortcut_top)
        self.hotkey_status = label("正在注册快捷键…", "muted", True)
        shortcut_layout.addWidget(self.hotkey_status)
        shortcut_layout.addWidget(
            label("点击右侧键位，按下新的组合键；保存设置后生效。", "muted", True)
        )
        divider = QFrame()
        divider.setObjectName("divider")
        divider.setFixedHeight(1)
        shortcut_layout.addWidget(divider)
        self.ocr_device = QComboBox()
        self.ocr_device.addItem("自动 · 优先 GPU，不可用时使用 CPU", "auto")
        self.ocr_device.addItem("仅使用 CPU", "cpu")
        self.ocr_device.setCurrentIndex(max(0, self.ocr_device.findData(settings.ocr_device)))
        if sys.platform == "darwin":
            self.ocr_device.hide()
            shortcut_layout.addWidget(
                label("本地识别 · Apple Vision 自动调度硬件加速", "muted", True)
            )
        else:
            shortcut_layout.addWidget(label("本地文字识别", "muted"))
            shortcut_layout.addWidget(self.ocr_device)
        location = QHBoxLayout()
        location.addWidget(label("问答与知识卡片 · 本地 Markdown", "muted"), 1)
        change = button("保存位置", "link")
        change.clicked.connect(self.directory_requested)
        location.addWidget(change)
        folder = button("打开笔记", "link")
        folder.clicked.connect(self.notes_requested)
        location.addWidget(folder)
        shortcut_layout.addLayout(location)
        self.notes_dir = settings.notes_dir
        layout.addWidget(shortcut_card)
        layout.addWidget(
            label("截图只在内存中识别。仅文字发送给 AI，笔记留在你的电脑。", "muted", True)
        )
        layout.addStretch()

    def toggle_key(self):
        hidden = self.key.echoMode() == QLineEdit.Password
        self.key.setEchoMode(QLineEdit.Normal if hidden else QLineEdit.Password)
        self.show_key.setText("隐藏" if hidden else "显示")

    def show_status(self, text: str, error=False):
        self.status.setText(text)
        self.status.setStyleSheet("color: #D65C5C;" if error else "color: #438265;")

    def closeEvent(self, event):
        self.hide()
        self.hidden.emit()
        event.ignore()


class DragHeader(QFrame):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.offset = None
        self.setObjectName("answerHeader")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.offset = event.globalPosition().toPoint() - self.owner.pos()

    def mouseMoveEvent(self, event):
        if self.offset is not None and event.buttons() & Qt.LeftButton:
            self.owner.move(event.globalPosition().toPoint() - self.offset)

    def mouseReleaseEvent(self, event):
        self.offset = None


class SafeDocument(QTextDocument):
    def loadResource(self, _type, _name):
        # Only pre-added formula images are available; never load provider resources.
        return None


class SafeTextBrowser(QTextBrowser):
    def __init__(self):
        super().__init__()
        self.math_renderer = MathRenderer()

    def loadResource(self, _type, _name):
        return None

    def set_answer_markdown(self, markdown):
        parts = split_formulas(markdown)
        text, images = [], []
        prefix = "STUDYMATH" + uuid.uuid4().hex
        font_size = self.font().pixelSize()
        if font_size <= 0:
            font_size = self.font().pointSizeF() * self.logicalDpiY() / 72
        for part in parts:
            if not isinstance(part, Formula):
                text.append(part)
                continue
            try:
                image = self.math_renderer.render(part, font_size)
            except (RuntimeError, ValueError, OSError):
                image = None
            if image is None:
                text.append(part.original)
                continue
            token = f"{prefix}TOKEN{len(images)}END"
            text.append("\n\n" + token + "\n\n" if part.display else token)
            images.append((token, image))

        previous = self.document()
        document = SafeDocument(self)
        document.setDefaultFont(self.font())
        document.setDefaultStyleSheet(previous.defaultStyleSheet())
        document.setMarkdown("".join(text))
        for token, image in images:
            cursor = document.find(token)
            if cursor.isNull():
                continue
            url = QUrl("study-math:" + token)
            document.addResource(QTextDocument.ImageResource, url, image)
            fmt = QTextImageFormat()
            fmt.setName(url.toString())
            fmt.setWidth(image.width() / image.devicePixelRatio())
            fmt.setHeight(image.height() / image.devicePixelRatio())
            fmt.setVerticalAlignment(QTextCharFormat.AlignMiddle)
            cursor.insertImage(fmt)
        block = document.begin()
        while block.isValid():
            cursor = QTextCursor(block)
            fmt = block.blockFormat()
            fmt.setLineHeight(135, QTextBlockFormat.ProportionalHeight.value)
            fmt.setTopMargin(0)
            fmt.setBottomMargin(3 if block.textList() else 9)
            if fmt.headingLevel():
                fmt.setTopMargin(9)
                cursor.select(QTextCursor.BlockUnderCursor)
                title = QTextCharFormat()
                title.setFontPointSize(font_size * 72 / self.logicalDpiY())
                cursor.mergeCharFormat(title)
            cursor.setBlockFormat(fmt)
            block = block.next()
        self.setDocument(document)


class ChoiceButton(QPushButton):
    """Include wrapped child labels in the button's layout measurement."""

    def __init__(self, text):
        super().__init__()
        self.setObjectName("choice")
        self.setAccessibleName(text)
        policy = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        self.setCursor(Qt.PointingHandCursor)

    def heightForWidth(self, width):
        return max(58, self.layout().heightForWidth(width) if self.layout() else 58)

    def sizeHint(self):
        return QSize(300, self.heightForWidth(300))

    def minimumSizeHint(self):
        return QSize(100, 58)


class AnswerWindow(GlassWindow):
    submitted = Signal(str)
    clarified = Signal(str)
    retry_requested = Signal(str)
    cancelled = Signal()
    settings_requested = Signal()
    notes_requested = Signal()
    closed = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("answer")
        self.setWindowTitle("屏幕学习助手 · 回答")
        self.setStyleSheet(STYLE)
        self.resize(440, 550)
        self.setMinimumSize(380, 400)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 17, 20, 18)
        layout.setSpacing(10)
        header = DragHeader(self)
        top = QHBoxLayout(header)
        top.setContentsMargins(0, 0, 0, 0)
        top.addStretch()
        settings = button("⋯", "icon")
        settings.setToolTip("打开模型设置")
        settings.clicked.connect(self.settings_requested)
        top.addWidget(settings)
        close = button("×", "icon")
        close.setToolTip("关闭悬浮窗 · Esc")
        close.clicked.connect(self.close)
        top.addWidget(close)
        layout.addWidget(header)
        self.phase = label("准备识别…", "muted", True)
        layout.addWidget(self.phase)
        self.ocr_status = label("", "muted", True)
        self.ocr_status.hide()
        layout.addWidget(self.ocr_status)
        self.encounter = label("", "muted", True)
        self.encounter.hide()
        layout.addWidget(self.encounter)
        self.browser = SafeTextBrowser()
        # QTextBrowser's viewport otherwise auto-fills its opaque palette Base.
        self.browser.viewport().setAutoFillBackground(False)
        self.browser.viewport().setStyleSheet("background: transparent;")
        self.browser.setOpenExternalLinks(False)
        self.browser.setOpenLinks(False)
        self.browser.document().setDefaultStyleSheet(
            "body {line-height:1.6;} h2,h3 {font-size:15px;} p {margin-top:6px;margin-bottom:9px;} code {background:#f0f3f8;}"
        )
        layout.addWidget(self.browser, 1)
        self.clarification_panel = QScrollArea()
        self.clarification_panel.setWidgetResizable(True)
        self.clarification_panel.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.clarification_panel.viewport().setAutoFillBackground(False)
        self.clarification_body = QWidget()
        self.clarification_layout = QVBoxLayout(self.clarification_body)
        self.clarification_layout.setContentsMargins(0, 5, 0, 5)
        self.clarification_layout.setSpacing(10)
        self.clarification_panel.setWidget(self.clarification_body)
        self.clarification_panel.hide()
        layout.addWidget(self.clarification_panel, 1)
        self.choice_buttons = []
        self.clarification_active = False
        self.toggle_ocr = button("原文", "link")
        self.toggle_ocr.setToolTip("查看或修改本地识别文字")
        self.toggle_ocr.clicked.connect(self.toggle_source)
        self.source_panel = QWidget()
        source_layout = QVBoxLayout(self.source_panel)
        source_layout.setContentsMargins(0, 0, 0, 0)
        self.source = QPlainTextEdit()
        self.source.setPlaceholderText("未识别到文字时，可在这里手动填写。")
        self.source.setMaximumHeight(105)
        source_layout.addWidget(self.source)
        retry = button("用这段文字重新解答")
        retry.clicked.connect(lambda: self.retry_requested.emit(self.source.toPlainText().strip()))
        source_layout.addWidget(retry)
        self.source_panel.hide()
        layout.addWidget(self.source_panel)
        follow = QHBoxLayout()
        self.question = QLineEdit()
        self.question.setPlaceholderText("继续追问…")
        self.question.returnPressed.connect(self.submit)
        self.send = button("↑", "primary")
        self.send.setToolTip("发送追问")
        self.send.setFixedSize(38, 38)
        self.send.setStyleSheet(
            "background: #242A35; color: white; border-radius: 19px; padding: 0; font-size: 20px;"
        )
        self.send.clicked.connect(self.submit)
        follow.addWidget(self.question, 1)
        follow.addWidget(self.send)
        layout.addLayout(follow)
        bottom = QHBoxLayout()
        self.saved = label("", "muted")
        bottom.addWidget(self.saved, 1)
        bottom.addWidget(self.toggle_ocr)
        bottom.addSpacing(10)
        self.notes_button = button("笔记", "link")
        self.notes_button.clicked.connect(self.notes_requested)
        bottom.addWidget(self.notes_button)
        bottom.addSpacing(10)
        self.stop = button("停止", "link")
        self.stop.clicked.connect(self.cancelled)
        bottom.addWidget(self.stop)
        self.copy = button("复制", "link")
        self.copy.clicked.connect(self.copy_answer)
        bottom.addWidget(self.copy)
        layout.addLayout(bottom)
        self.rendered = ""
        self.turns = []
        self.current_question = ""
        self.output = ""

    def position_near(self, selection):
        if isinstance(selection, QPoint):
            selection = QRect(selection, selection)
        screen = QGuiApplication.screenAt(selection.center()) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry().adjusted(12, 12, -12, -12)
        self.resize(min(440, area.width()), min(550, area.height()))
        self.move(adjacent_position(selection, self.size(), area))

    def reset(self):
        self.clear_clarification()
        self.turns = []
        self.current_question = ""
        self.output = ""
        self.rendered = ""
        self.browser.clear()
        self.source.clear()
        self.ocr_status.clear()
        self.ocr_status.hide()
        self.source_panel.hide()
        self.encounter.hide()
        self.question.clear()
        self.saved.clear()
        self.phase.show()
        self.phase.setStyleSheet("")
        self.busy(True)

    def busy(self, value):
        self.question.setEnabled(not value)
        self.send.setEnabled(not value)
        self.stop.setVisible(value)

    def start_answer(self, question):
        self.clear_clarification()
        self.current_question = question
        self.output = ""
        self.phase.setText("正在解答…")
        self.phase.show()
        self.phase.setStyleSheet("")
        self.busy(True)

    def clear_clarification(self):
        self.clarification_active = False
        self.clarification_panel.hide()
        self.browser.show()
        self.question.show()
        self.send.show()
        self.copy.setEnabled(True)
        while self.clarification_layout.count():
            item = self.clarification_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.choice_buttons = []

    def show_clarification(self, prompt, options):
        self.clear_clarification()
        self.clarification_active = True
        self.browser.hide()
        self.question.hide()
        self.send.hide()
        self.stop.hide()
        self.phase.hide()
        self.copy.setEnabled(bool(self.turns))
        title = label(prompt, wrap=True)
        title.setTextFormat(Qt.PlainText)
        title.setStyleSheet("font-size: 17px; font-weight: 600; padding: 0 3px 5px;")
        self.clarification_layout.addWidget(title)
        hint = label("选一个方向，再继续解答。", "muted", True)
        self.clarification_layout.addWidget(hint)

        def choice(index, text):
            item = ChoiceButton(f"{chr(65 + index)} {text}")
            row = QHBoxLayout(item)
            row.setContentsMargins(14, 13, 14, 13)
            badge = label(chr(65 + index), "muted")
            badge.setFixedWidth(18)
            content = label(text, wrap=True)
            content.setTextFormat(Qt.PlainText)
            for widget in (badge, content):
                widget.setAttribute(Qt.WA_TransparentForMouseEvents)
                row.addWidget(widget)
            row.setStretch(1, 1)
            self.clarification_layout.addWidget(item)
            self.choice_buttons.append(item)
            return item

        for index, option in enumerate(options):
            item = choice(index, option)
            item.clicked.connect(lambda _checked=False, text=option: self.clarified.emit(text))
        other = choice(len(options), "其他，自己填写")
        self.custom_direction = QLineEdit()
        self.custom_direction.setPlaceholderText("输入领域、含义或补充条件，按回车继续")
        self.custom_direction.returnPressed.connect(self.submit_direction)
        self.custom_direction.hide()
        self.clarification_layout.addWidget(self.custom_direction)
        self.custom_confirm = button("继续解答", "primary")
        self.custom_confirm.clicked.connect(self.submit_direction)
        self.custom_confirm.hide()
        self.clarification_layout.addWidget(self.custom_confirm)

        def show_custom():
            self.custom_direction.show()
            self.custom_confirm.show()
            self.custom_direction.setFocus()

        other.clicked.connect(show_custom)
        self.clarification_layout.addStretch()
        self.clarification_panel.show()
        self.saved.setText("等待确认")

    def submit_direction(self):
        text = self.custom_direction.text().strip()
        if self.clarification_active and text:
            self.clarified.emit(text)

    def append_answer(self, text):
        self.output += text
        self.phase.hide()
        self.render()

    def render(self):
        sections = []
        for turn in self.turns:
            heading = (
                ""
                if turn["question"] == "解释这段内容"
                else format_question(turn["question"]) + "\n\n"
            )
            sections.append(heading + turn["answer"])
        if self.output:
            heading = (
                ""
                if self.current_question == "解释这段内容"
                else format_question(self.current_question) + "\n\n"
            )
            sections.append(heading + self.output)
        self.rendered = "\n\n---\n\n".join(sections)
        self.browser.set_answer_markdown(self.rendered)
        self.browser.verticalScrollBar().setValue(self.browser.verticalScrollBar().maximum())

    def finish_answer(self, answer):
        self.turns.append({"question": self.current_question, "answer": answer})
        self.output = ""
        self.render()
        self.phase.clear()
        self.phase.hide()
        self.busy(False)

    def show_error(self, text):
        self.phase.setText(text)
        self.phase.show()
        self.phase.setStyleSheet("color: #D65C5C;")
        self.busy(False)

    def toggle_source(self):
        self.source_panel.setVisible(not self.source_panel.isVisible())

    def submit(self):
        text = self.question.text().strip()
        if text and self.send.isEnabled():
            self.question.clear()
            self.submitted.emit(text)

    def copy_answer(self):
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(self.rendered)
        self.saved.setText("已复制")

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        self.cancelled.emit()
        self.hide()
        self.closed.emit()
        event.ignore()


def adjacent_position(selection, size, area, gap=14):
    """Choose a visible side of the selection, minimizing overlap on small screens."""
    w, h = size.width(), size.height()

    def clamp_x(x):
        return max(area.left(), min(x, area.right() - w + 1))

    def clamp_y(y):
        return max(area.top(), min(y, area.bottom() - h + 1))

    candidates = [
        QPoint(selection.right() + gap + 1, clamp_y(selection.top())),
        QPoint(selection.left() - gap - w, clamp_y(selection.top())),
        QPoint(clamp_x(selection.left()), selection.bottom() + gap + 1),
        QPoint(clamp_x(selection.left()), selection.top() - gap - h),
    ]
    for point in candidates:
        if area.contains(QRect(point, size)) and not selection.intersects(QRect(point, size)):
            return point
    clamped = [QPoint(clamp_x(p.x()), clamp_y(p.y())) for p in candidates]

    def overlap(point):
        rect = selection.intersected(QRect(point, size))
        return max(0, rect.width()) * max(0, rect.height())

    return min(clamped, key=overlap)


class LauncherWindow(GlassWindow):
    capture_requested = Signal()
    settings_requested = Signal()
    notes_requested = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("launcher")
        self.setWindowTitle("屏幕学习助手 · 快捷入口")
        self.setStyleSheet(STYLE)
        self.setFixedSize(260, 60)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        handle = DragHeader(self)
        handle.setFixedWidth(24)
        grip = QHBoxLayout(handle)
        grip.setContentsMargins(0, 0, 0, 0)
        grip.addWidget(label("⠿", "muted"))
        layout.addWidget(handle)
        self.capture_button = button("框选", "primary")
        self.settings_button = button("设置")
        self.notes_button = button("笔记")
        for item, signal in (
            (self.capture_button, self.capture_requested),
            (self.settings_button, self.settings_requested),
            (self.notes_button, self.notes_requested),
        ):
            item.setStyleSheet("padding: 9px 12px; border-radius: 17px;")
            item.clicked.connect(signal)
            layout.addWidget(item)
        self.setToolTip("拖动左侧手柄可移动 · 关闭回答后仍可打开设置和笔记")
        area = QGuiApplication.primaryScreen().availableGeometry()
        self.move(area.right() - self.width() - 24, area.bottom() - self.height() - 24)


class CaptureOverlay(QWidget):
    selected = Signal(bytes, QRect)
    dismissed = Signal()

    def __init__(self, screen, pixmap):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setWindowTitle("屏幕学习助手 · 框选")
        self.setGeometry(screen.geometry())
        self.pixmap = pixmap
        self.origin = None
        self.selection = QRect()
        self.setCursor(Qt.CrossCursor)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.was_selected = False

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.drawPixmap(self.rect(), self.pixmap)
        painter.fillRect(self.rect(), QColor(15, 24, 44, 95))
        if not self.selection.isEmpty():
            painter.save()
            painter.setClipRect(self.selection)
            painter.drawPixmap(self.rect(), self.pixmap)
            painter.restore()
            painter.setPen(QPen(QColor("#6199FF"), 2))
            painter.drawRect(self.selection.adjusted(0, 0, -1, -1))
        painter.setPen(QColor("white"))
        painter.setFont(QFont("PingFang SC", 15))
        painter.drawText(
            QRect(0, 28, self.width(), 40),
            Qt.AlignCenter,
            "拖动框选文字，松开即可解释   ·   Esc 取消",
        )

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.origin = event.position().toPoint()

    def mouseMoveEvent(self, event):
        if self.origin is not None:
            self.selection = (
                QRect(self.origin, event.position().toPoint()).normalized().intersected(self.rect())
            )
            self.update()

    def mouseReleaseEvent(self, event):
        if self.origin is None or event.button() != Qt.LeftButton:
            return
        self.selection = (
            QRect(self.origin, event.position().toPoint()).normalized().intersected(self.rect())
        )
        if self.selection.width() < 8 or self.selection.height() < 8:
            self.origin = None
            self.selection = QRect()
            self.update()
            return
        scale_x = self.pixmap.width() / self.width()
        scale_y = self.pixmap.height() / self.height()
        crop = self.pixmap.copy(
            QRect(
                round(self.selection.x() * scale_x),
                round(self.selection.y() * scale_y),
                round(self.selection.width() * scale_x),
                round(self.selection.height() * scale_y),
            )
        )
        from PySide6.QtCore import QBuffer, QByteArray, QIODevice

        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.WriteOnly)
        crop.save(buffer, "PNG")
        selection = QRect(self.mapToGlobal(self.selection.topLeft()), self.selection.size())
        self.was_selected = True
        self.hide()
        self.pixmap = QPixmap()
        self.selected.emit(bytes(data), selection)
        self.close()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()

    def closeEvent(self, event):
        self.pixmap = QPixmap()
        if not self.was_selected:
            self.dismissed.emit()
        event.accept()
