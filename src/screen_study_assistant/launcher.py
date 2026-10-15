"""An interactive liquid-glass particle that morphs into one continuous capsule."""

from __future__ import annotations

from math import pi, sin
from time import monotonic

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRect,
    QRectF,
    Qt,
    QTimer,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QCursor,
    QGuiApplication,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QPushButton,
    QWidget,
)

from .glass import GlassWindow


def radial(painter, path, center, radius, color, alpha):
    gradient = QRadialGradient(center, radius)
    tint = QColor(color)
    tint.setAlpha(max(0, min(255, round(alpha))))
    gradient.setColorAt(0, tint)
    gradient.setColorAt(0.45, QColor(tint.red(), tint.green(), tint.blue(), round(tint.alpha() * .42)))
    gradient.setColorAt(1, QColor(tint.red(), tint.green(), tint.blue(), 0))
    painter.fillPath(path, gradient)


class CapsuleAction(QPushButton):
    def __init__(self, text, primary, parent):
        super().__init__(text, parent)
        self.primary = primary
        self.hover = 0.0
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setFixedSize(80, 62)
        self.setStyleSheet("background: transparent; border: none;")
        self.setAccessibleName(text)
        self._hover = QVariantAnimation(self)
        self._hover.setDuration(170)
        self._hover.valueChanged.connect(self._set_hover)

    def _set_hover(self, value):
        self.hover = float(value)
        self.update()

    def _animate_hover(self, value):
        self._hover.stop()
        self._hover.setStartValue(self.hover)
        self._hover.setEndValue(value)
        self._hover.start()

    def enterEvent(self, event):
        self._animate_hover(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._animate_hover(0.0)
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        amount = max(self.hover, .7 if self.hasFocus() else 0)
        inset = 4 if self.primary else 2
        rect = QRectF(self.rect()).adjusted(inset, 2, -inset, -2)
        if self.isDown():
            rect.adjust(2, 2, -2, -2)
        # Only the central action has a lens. The sides merge with the capsule.
        if self.primary or amount:
            sheen = QLinearGradient(rect.topLeft(), rect.bottomRight())
            sheen.setColorAt(0, QColor(255, 255, 255, round(48 + amount * 28)))
            sheen.setColorAt(.5, QColor(255, 255, 255, 4))
            sheen.setColorAt(1, QColor(205, 222, 255, round(18 + amount * 18)))
            painter.setBrush(sheen)
            rim = QLinearGradient(rect.topLeft(), rect.bottomRight())
            rim.setColorAt(0, QColor(255, 255, 255, round(105 if self.primary else amount * 65)))
            rim.setColorAt(.45, QColor(255, 255, 255, 0))
            rim.setColorAt(1, QColor(194, 220, 249, round(58 if self.primary else amount * 35)))
            painter.setPen(QPen(rim, .8))
            painter.drawRoundedRect(rect, 29, 29)
        font = self.font()
        font.setPixelSize(14)
        font.setWeight(font.Weight.Medium)
        painter.setFont(font)
        # A small shadow keeps the unchanged labels readable over bright windows.
        painter.setPen(QColor(15, 25, 39, 140))
        painter.drawText(rect.translated(0, 1), Qt.AlignCenter, self.text())
        painter.setPen(QColor("#F7FAFF"))
        painter.drawText(rect, Qt.AlignCenter, self.text())


class LauncherWindow(GlassWindow):
    capture_requested = Signal()
    settings_requested = Signal()
    notes_requested = Signal()

    COMPACT_WIDTH = 46
    COMPACT_HEIGHT = 70
    EXPANDED_WIDTH = 296
    HEIGHT = 82
    MORPH_MS = 520

    def __init__(self):
        super().__init__()
        self.setObjectName("launcher")
        self.setWindowTitle("屏幕学习助手 · 快捷入口")
        self.setAccessibleName("快捷入口 · 点击或拖拽展开框选、设置和笔记")
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet("QWidget#launcher { background: transparent; }")
        self.expanded = False
        self._unfold = 0.0
        self._press = 0.0
        self._pulse = 1.0
        self._pointer = QPointF(.5, .5)
        self._drag_origin = None
        self._drag_anchor = None
        self._dragged = False
        self._keyboard_open = False
        self._anchor_right = True
        self._glow_started = monotonic()
        self.resize(self.COMPACT_WIDTH, self.COMPACT_HEIGHT)
        area = QGuiApplication.primaryScreen().availableGeometry()
        self.move(area.right() - self.width() - 24, area.bottom() - self.height() - 24)
        self._anchor = QPoint(self.geometry().right() + 1, self.geometry().center().y())
        self._actions = QWidget(self)
        layout = QHBoxLayout(self._actions)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.capture_button = CapsuleAction("框选", True, self._actions)
        self.settings_button = CapsuleAction("设置", False, self._actions)
        self.notes_button = CapsuleAction("笔记", False, self._actions)
        for item, signal in (
            (self.settings_button, self.settings_requested),
            (self.capture_button, self.capture_requested),
            (self.notes_button, self.notes_requested),
        ):
            item.clicked.connect(signal)
            layout.addWidget(item)
        self._actions.setFixedSize(256, 62)
        self._opacity = QGraphicsOpacityEffect(self._actions)
        self._actions.setGraphicsEffect(self._opacity)
        self._actions.hide()
        self._animation = QPropertyAnimation(self, b"unfold", self)
        self._animation.setDuration(self.MORPH_MS)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)
        self._animation.finished.connect(self._finish_transition)
        self._press_animation = QPropertyAnimation(self, b"pressure", self)
        self._press_animation.setDuration(150)
        self._press_animation.setEasingCurve(QEasingCurve.OutCubic)
        self._pulse_animation = QPropertyAnimation(self, b"pulse", self)
        self._pulse_animation.setDuration(650)
        self._collapse_timer = QTimer(self)
        self._collapse_timer.setSingleShot(True)
        self._collapse_timer.setInterval(2600)
        self._collapse_timer.timeout.connect(self._collapse_if_idle)
        self._glow_timer = QTimer(self)
        self._glow_timer.setInterval(33)
        self._glow_timer.timeout.connect(self.update)
        self.setToolTip("点击或拖拽展开 · 拖动边缘移动 · Esc 收起")

    def glass_is_dark(self):
        return True

    def glass_corner_radius(self):
        return min(self.width(), self.height()) / 2

    def _get_unfold(self):
        return self._unfold

    def _set_unfold(self, value):
        self._unfold = float(value)
        self._apply_shape()
        fade = max(0, min(1, (self._unfold - .35) / .65))
        self._opacity.setOpacity(fade)
        self._actions.setVisible(fade > 0)
        self.update()

    unfold = Property(float, _get_unfold, _set_unfold)

    def _get_pressure(self):
        return self._press

    def _set_pressure(self, value):
        self._press = float(value)
        self._apply_shape()
        self.update()

    pressure = Property(float, _get_pressure, _set_pressure)

    def _get_pulse(self):
        return self._pulse

    def _set_pulse(self, value):
        self._pulse = float(value)
        self.update()

    pulse = Property(float, _get_pulse, _set_pulse)

    def _area(self):
        screen = QGuiApplication.screenAt(self.geometry().center()) or self.screen()
        return screen.availableGeometry()

    def _bounded(self, rect):
        screen = QGuiApplication.screenAt(rect.center()) or self.screen()
        area = screen.availableGeometry()
        rect.moveLeft(max(area.left(), min(rect.left(), area.right() - rect.width() + 1)))
        rect.moveTop(max(area.top(), min(rect.top(), area.bottom() - rect.height() + 1)))
        return rect

    def _remember_anchor(self):
        rect = self.geometry()
        self._anchor_right = rect.center().x() >= self._area().center().x()
        self._anchor = QPoint(rect.right() + 1 if self._anchor_right else rect.left(),
                              rect.center().y())

    def _apply_shape(self):
        p = self._unfold
        width = round(self.COMPACT_WIDTH + (self.EXPANDED_WIDTH - self.COMPACT_WIDTH) * p)
        height = round(self.COMPACT_HEIGHT + (self.HEIGHT - self.COMPACT_HEIGHT) * p
                       + sin(pi * p) * 6 - self._press * 3)
        left = self._anchor.x() - width if self._anchor_right else self._anchor.x()
        rect = QRect(left, self._anchor.y() - height // 2, width, height)
        self.setGeometry(self._bounded(rect))
        self._actions.move((width - self._actions.width()) // 2,
                           (height - self._actions.height()) // 2 + round((1 - p) * 6))

    def set_expanded(self, expanded, animate=True):
        target = 1.0 if expanded else 0.0
        if (animate and self.expanded == expanded
                and self._animation.state() == QPropertyAnimation.Running
                and self._animation.endValue() == target):
            return
        if self.expanded == expanded and abs(self._unfold - target) < .001:
            return
        if self._drag_origin is None:
            self._remember_anchor()
        self.expanded = expanded
        self._collapse_timer.stop()
        self._animation.stop()
        self._actions.setEnabled(False)
        if animate:
            self._animation.setStartValue(self._unfold)
            self._animation.setEndValue(target)
            self._animation.start()
        else:
            self._set_unfold(target)
            self._finish_transition()
        self.setAccessibleName("快捷入口" if expanded else "快捷入口 · 点击或拖拽展开框选、设置和笔记")

    def _finish_transition(self):
        self._actions.setEnabled(self.expanded)
        self._actions.setVisible(self.expanded)
        if self.expanded and self._keyboard_open:
            self.capture_button.setFocus(Qt.TabFocusReason)
        if self.expanded and not self._keyboard_open:
            self._collapse_timer.start()
        self.update()

    def _collapse_if_idle(self):
        # Native glass can leave QWidget.underMouse() stale after a resize.
        # Use the actual desktop pointer to avoid a permanently expanded particle.
        if self._drag_origin is not None or self._keyboard_open:
            return
        if self.geometry().contains(QCursor.pos()):
            self._collapse_timer.start()
            return
        self.set_expanded(False)

    def enterEvent(self, event):
        self._collapse_timer.stop()
        # Hover changes the light only; the unfolding belongs to the user's gesture.
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        if self.expanded and not self._keyboard_open:
            self._collapse_timer.start()
        super().leaveEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        self._glow_timer.start()

    def hideEvent(self, event):
        self._collapse_timer.stop()
        self._glow_timer.stop()
        self._animation.stop()
        self._press_animation.stop()
        self._pulse_animation.stop()
        self._drag_origin = None
        self._keyboard_open = False
        self._press = 0.0
        self._pulse = 1.0
        self.set_expanded(False, animate=False)
        self._set_unfold(0.0)
        super().hideEvent(event)

    def _animate_pressure(self, value):
        self._press_animation.stop()
        self._press_animation.setStartValue(self._press)
        self._press_animation.setEndValue(value)
        self._press_animation.start()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._collapse_timer.stop()
            self._keyboard_open = False
            self._remember_anchor()
            self._drag_origin = event.globalPosition().toPoint()
            self._drag_anchor = QPoint(self._anchor)
            self._dragged = False
            self._pointer = QPointF(event.position().x() / self.width(),
                                    event.position().y() / self.height())
            self._animate_pressure(1.0)
            self._pulse_animation.stop()
            self._pulse_animation.setStartValue(0.0)
            self._pulse_animation.setEndValue(1.0)
            self._pulse_animation.start()

    def mouseMoveEvent(self, event):
        self._pointer = QPointF(max(0, min(1, event.position().x() / self.width())),
                                max(0, min(1, event.position().y() / self.height())))
        if self._drag_origin is not None and event.buttons() & Qt.LeftButton:
            delta = event.globalPosition().toPoint() - self._drag_origin
            if delta.manhattanLength() >= QApplication.startDragDistance():
                self._dragged = True
                # Do not stop the morph: the particle unfolds while following the hand.
                self.set_expanded(True)
            if self._dragged:
                self._anchor = self._drag_anchor + delta
                self._apply_shape()
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._drag_origin is not None:
            self._animate_pressure(0.0)
            self.set_expanded(True)
            self._drag_origin = None
            self._drag_anchor = None
            if self._animation.state() != QPropertyAnimation.Running:
                self._finish_transition()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._keyboard_open = False
            self.set_expanded(False)
        elif event.key() in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter) and not self.expanded:
            self._keyboard_open = True
            self.set_expanded(True)
        else:
            super().keyPressEvent(event)

    def paintEvent(self, event):
        # Native blur is behind this canvas. Avoid the old opaque grey overlay.
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        radius = self.glass_corner_radius()
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        painter.setClipPath(path)
        tint = QLinearGradient(rect.topLeft(), rect.bottomRight())
        alpha = 1 if self.native_glass else 3.3
        tint.setColorAt(0, QColor(64, 76, 90, round(49 * alpha)))
        tint.setColorAt(.45, QColor(23, 33, 49, round(60 * alpha)))
        tint.setColorAt(1, QColor(48, 55, 76, round(55 * alpha)))
        painter.fillPath(path, tint)
        phase = (monotonic() - self._glow_started) * 1.25
        center = QPointF(self.width() / 2, self.height() / 2)
        spread = 10 + self._unfold * 7
        # A single small iridescent core survives the morph; the whole shell is not rainbow.
        for dx, dy, color in ((-.65, -.55, '#82F1DE'), (.65, -.05, '#A6B2FF'),
                               (.12, .7, '#ECA8E3')):
            spot = center + QPointF(dx * spread + sin(phase + dy * 3) * 2,
                                    dy * spread + sin(phase * .8 + dx * 4) * 2)
            radial(painter, path, spot, 18 + self._unfold * 12, color,
                   104 + 15 * sin(phase + dx))
        touch = QPointF(self.width() * self._pointer.x(), self.height() * self._pointer.y())
        radial(painter, path, touch, 42, '#DBF8FF', 10 + self._press * 32)
        # Curved specular streaks and paired bright/dark rims give thickness to the glass.
        sheen = QLinearGradient(0, rect.top(), 0, rect.bottom())
        sheen.setColorAt(0, QColor(255, 255, 255, 37))
        sheen.setColorAt(.22, QColor(255, 255, 255, 2))
        sheen.setColorAt(.72, QColor(255, 255, 255, 0))
        sheen.setColorAt(1, QColor(190, 224, 250, 18))
        painter.fillPath(path, sheen)
        inner = rect.adjusted(2, 2, -2, -2)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor(4, 16, 30, 65), 1.5))
        painter.drawRoundedRect(inner, max(0, radius - 2), max(0, radius - 2))
        rim = QLinearGradient(rect.topLeft(), rect.bottomRight())
        rim.setColorAt(0, QColor(255, 255, 255, 220))
        rim.setColorAt(.25, QColor(226, 247, 255, 65))
        rim.setColorAt(.52, QColor(255, 255, 255, 13))
        rim.setColorAt(1, QColor(215, 225, 255, 155))
        painter.setPen(QPen(rim, 1.1))
        painter.drawPath(path)
        glint = QPainterPath()
        glint.moveTo(rect.left() + radius * .5, rect.top() + radius * .3)
        glint.quadTo(rect.left() + radius * .8, rect.top() + 2,
                     rect.left() + radius * 1.45, rect.top() + 3)
        painter.setPen(QPen(QColor(255, 255, 255, 100), 1.4, Qt.SolidLine, Qt.RoundCap))
        painter.drawPath(glint)
        if self._pulse < 1:
            painter.setPen(QPen(QColor(211, 243, 255, round(70 * (1 - self._pulse))), 1.2))
            r = 7 + self._pulse * 65
            painter.drawEllipse(touch, r, r)
