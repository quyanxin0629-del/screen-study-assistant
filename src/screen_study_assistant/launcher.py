"""A small frosted capsule that unfolds into the existing desktop actions."""

from __future__ import annotations

from math import sin
from time import monotonic

from PySide6.QtCore import (
    QEasingCurve,
    QPointF,
    QPropertyAnimation,
    QRect,
    QRectF,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QGuiApplication,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import QApplication, QHBoxLayout, QPushButton, QWidget

from .glass import GlassWindow


class CapsuleAction(QPushButton):
    def __init__(self, text, accent, parent):
        super().__init__(text, parent)
        self.accent = QColor(accent)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        self.setFixedSize(76, 58)
        self.setStyleSheet("background: transparent; border: none;")
        self.setAccessibleName(text)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        active = self.underMouse() or self.hasFocus()
        wash = QRadialGradient(rect.center() + QPointF(-8, 7), 49)
        color = QColor(self.accent)
        color.setAlpha(100 if active else 48)
        wash.setColorAt(0, color)
        wash.setColorAt(1, QColor(255, 255, 255, 3))
        painter.setBrush(wash)
        rim = QLinearGradient(rect.topLeft(), rect.bottomRight())
        rim.setColorAt(0, QColor(255, 255, 255, 100 if active else 45))
        rim.setColorAt(0.5, QColor(255, 255, 255, 4))
        rim.setColorAt(1, QColor(255, 255, 255, 50 if active else 22))
        painter.setPen(QPen(rim, 0.8))
        painter.drawRoundedRect(rect, 29, 29)
        if self.isDown():
            painter.setBrush(QColor(255, 255, 255, 22))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(rect, 29, 29)
        font = self.font()
        font.setPixelSize(14)
        font.setWeight(font.Weight.Medium)
        painter.setFont(font)
        painter.setPen(QColor("#F5F8FC"))
        painter.drawText(rect, Qt.AlignCenter, self.text())


class LauncherWindow(GlassWindow):
    capture_requested = Signal()
    settings_requested = Signal()
    notes_requested = Signal()

    COMPACT_WIDTH = 50
    EXPANDED_WIDTH = 268
    HEIGHT = 78

    def __init__(self):
        super().__init__()
        self.setObjectName("launcher")
        self.setWindowTitle("屏幕学习助手 · 快捷入口")
        self.setAccessibleName("快捷入口 · 展开框选、设置和笔记")
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        self.setStyleSheet("QWidget#launcher { background: transparent; }")
        self.resize(self.COMPACT_WIDTH, self.HEIGHT)
        self.expanded = False
        self._drag_origin = None
        self._drag_position = None
        self._dragged = False
        self._glow_started = monotonic()
        self._actions = QWidget(self)
        layout = QHBoxLayout(self._actions)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        self.capture_button = CapsuleAction("框选", "#89E7CF", self._actions)
        self.settings_button = CapsuleAction("设置", "#B7AEF5", self._actions)
        self.notes_button = CapsuleAction("笔记", "#AEC4F2", self._actions)
        for item, signal in (
            (self.capture_button, self.capture_requested),
            (self.settings_button, self.settings_requested),
            (self.notes_button, self.notes_requested),
        ):
            item.clicked.connect(signal)
            layout.addWidget(item)
        self._actions.setFixedSize(234, 58)
        self._actions.hide()
        self._animation = QPropertyAnimation(self, b"geometry", self)
        self._animation.setDuration(240)
        self._animation.setEasingCurve(QEasingCurve.InOutCubic)
        self._animation.finished.connect(self._finish_transition)
        self._collapse_timer = QTimer(self)
        self._collapse_timer.setSingleShot(True)
        self._collapse_timer.setInterval(1100)
        self._collapse_timer.timeout.connect(self._collapse_if_idle)
        self._glow_timer = QTimer(self)
        self._glow_timer.setInterval(80)
        self._glow_timer.timeout.connect(self.update)
        self.setToolTip("移入或点击展开 · 拖动胶囊边缘可移动")
        area = QGuiApplication.primaryScreen().availableGeometry()
        self.move(area.right() - self.width() - 24, area.bottom() - self.height() - 24)

    def glass_corner_radius(self):
        return min(self.width(), self.height()) / 2

    def _area(self):
        screen = QGuiApplication.screenAt(self.geometry().center()) or self.screen()
        return screen.availableGeometry()

    def _bounded(self, rect):
        screen = QGuiApplication.screenAt(rect.center()) or self.screen()
        area = screen.availableGeometry()
        rect.moveLeft(max(area.left(), min(rect.left(), area.right() - rect.width() + 1)))
        rect.moveTop(max(area.top(), min(rect.top(), area.bottom() - rect.height() + 1)))
        return rect

    def set_expanded(self, expanded, animate=True):
        target_width = self.EXPANDED_WIDTH if expanded else self.COMPACT_WIDTH
        if self.expanded == expanded and self.width() == target_width:
            return
        self.expanded = expanded
        self._collapse_timer.stop()
        self._animation.stop()
        self._actions.hide()
        area = self._area()
        rect = QRect(self.geometry())
        width = target_width
        # Keep the nearest screen edge anchored, including on displays left of the main one.
        if rect.center().x() >= area.center().x():
            rect.setLeft(rect.right() - width + 1)
        else:
            rect.setWidth(width)
        rect = self._bounded(rect)
        if animate:
            self._animation.setStartValue(self.geometry())
            self._animation.setEndValue(rect)
            self._animation.start()
        else:
            self.setGeometry(rect)
            self._finish_transition()
        self.setAccessibleName("快捷入口" if expanded else "快捷入口 · 展开框选、设置和笔记")

    def _finish_transition(self):
        self._actions.move((self.width() - self._actions.width()) // 2, 10)
        self._actions.setVisible(self.expanded)
        if self.expanded and not self.underMouse():
            self._collapse_timer.start()
        self.update()

    def _collapse_if_idle(self):
        focused = QApplication.focusWidget()
        if self.underMouse() or (focused and self.isAncestorOf(focused)):
            return
        self.set_expanded(False)

    def enterEvent(self, event):
        self._collapse_timer.stop()
        if self._drag_origin is None:
            self.set_expanded(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        if self.expanded:
            self._collapse_timer.start()
        super().leaveEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        self._glow_timer.start()
        if self.expanded:
            self._collapse_timer.start()

    def hideEvent(self, event):
        self._collapse_timer.stop()
        self._glow_timer.stop()
        self._animation.stop()
        # Next return to the desktop starts with the discreet capsule again.
        self.set_expanded(False, animate=False)
        super().hideEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._collapse_timer.stop()
            self._drag_origin = event.globalPosition().toPoint()
            self._drag_position = self.pos()
            self._dragged = False

    def mouseMoveEvent(self, event):
        if self._drag_origin is not None and event.buttons() & Qt.LeftButton:
            delta = event.globalPosition().toPoint() - self._drag_origin
            if delta.manhattanLength() >= QApplication.startDragDistance():
                self._animation.stop()
                self._dragged = True
            if self._dragged:
                self.move(self._bounded(QRect(self._drag_position + delta, self.size())).topLeft())

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._drag_origin is not None:
            dragged = self._dragged
            self._drag_origin = None
            self._drag_position = None
            if not dragged:
                self.set_expanded(True)
            else:
                self.set_expanded(self.expanded)
                if self._animation.state() != QPropertyAnimation.Running:
                    self._finish_transition()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.set_expanded(False)
        elif event.key() in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter) and not self.expanded:
            self.set_expanded(True)
        else:
            super().keyPressEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        radius = self.glass_corner_radius()
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        painter.setClipPath(path)
        tint = QLinearGradient(rect.topLeft(), rect.bottomRight())
        tint.setColorAt(0, QColor(49, 58, 76, 165))
        tint.setColorAt(0.55, QColor(24, 31, 44, 195))
        tint.setColorAt(1, QColor(41, 48, 65, 180))
        painter.fillPath(path, tint)
        phase = (monotonic() - self._glow_started) * 0.85
        folded = max(0.0, min(1.0, (self.EXPANDED_WIDTH - self.width()) / 218))
        # Glows stay inside one continuous surface; no independent square tiles.
        for x, y, color in ((0.38, 0.36, "#7CE7CF"), (0.62, 0.62, "#ACA2F7"),
                            (0.42, 0.72, "#E8A4CA")):
            center = QPointF(self.width() * x + sin(phase + y * 6) * 2, self.height() * y)
            glow = QRadialGradient(center, 15 + (1 - folded) * 30)
            bright = QColor(color)
            bright.setAlpha(round((70 + 30 * sin(phase + x * 4)) * (0.45 + folded * 0.55)))
            glow.setColorAt(0, bright)
            glow.setColorAt(1, QColor(0, 0, 0, 0))
            painter.fillPath(path, glow)
        rim = QLinearGradient(rect.topLeft(), rect.bottomRight())
        rim.setColorAt(0, QColor(255, 255, 255, 200))
        rim.setColorAt(0.4, QColor(255, 255, 255, 40))
        rim.setColorAt(1, QColor(199, 220, 244, 125))
        painter.setPen(QPen(rim, 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)
        inner = rect.adjusted(2, 2, -2, -2)
        painter.setPen(QPen(QColor(255, 255, 255, 18), 0.7))
        painter.drawRoundedRect(inner, max(0, radius - 2), max(0, radius - 2))
