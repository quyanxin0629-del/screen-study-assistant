"""An interactive liquid-glass particle that morphs into one continuous capsule."""

from __future__ import annotations

from math import pi, sin
from time import monotonic

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QEvent,
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
        self._pointer_hover = False
        self._keyboard_focus = False
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setFixedSize(60, 46)
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
        self.set_pointer_hover(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.set_pointer_hover(False)
        super().leaveEvent(event)

    def set_pointer_hover(self, hovered):
        if hovered != self._pointer_hover:
            self._pointer_hover = hovered
            self._animate_hover(1.0 if hovered else 0.0)

    def focusInEvent(self, event):
        self._keyboard_focus = event.reason() in (
            Qt.TabFocusReason, Qt.BacktabFocusReason, Qt.ShortcutFocusReason
        )
        self.update()
        super().focusInEvent(event)

    def focusOutEvent(self, event):
        self._keyboard_focus = False
        self.update()
        super().focusOutEvent(event)

    def _paint_icon(self, painter, center):
        # Clear glass adopts its backdrop; a dark keyline and white stroke keep
        # the symbol readable over both a white page and a dark desktop.
        for color, width in ((QColor(25, 43, 64, 125), 3.3), (QColor(255, 255, 255, 245), 1.7)):
            painter.save()
            painter.translate(center - QPointF(10, 10))
            painter.scale(5 / 6, 5 / 6)
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(color, width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            if self.text() == "框选":
                path = QPainterPath()
                for a, b, c in (
                    ((8, 3), (3, 3), (3, 8)), ((16, 3), (21, 3), (21, 8)),
                    ((3, 16), (3, 21), (8, 21)), ((16, 21), (21, 21), (21, 16)),
                ):
                    path.moveTo(*a)
                    path.lineTo(*b)
                    path.lineTo(*c)
                painter.drawPath(path)
                painter.drawLine(QPointF(8, 12), QPointF(16, 12))
                painter.drawLine(QPointF(12, 8), QPointF(12, 16))
            elif self.text() == "设置":
                painter.drawEllipse(QPointF(12, 12), 7, 7)
                painter.drawEllipse(QPointF(12, 12), 2.8, 2.8)
                painter.translate(12, 12)
                for _ in range(8):
                    painter.drawLine(QPointF(0, -7), QPointF(0, -10))
                    painter.rotate(45)
            else:
                painter.drawRoundedRect(QRectF(4, 3, 16, 18), 2.5, 2.5)
                painter.drawLine(QPointF(8, 3), QPointF(8, 21))
                for y in (8, 12, 16):
                    painter.drawLine(QPointF(11, y), QPointF(16, y))
            painter.restore()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        amount = max(self.hover, 1.0 if self._keyboard_focus and self.hasFocus() else 0)
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
            painter.drawRoundedRect(rect, 21, 21)
        self._paint_icon(painter, QPointF(rect.center().x(), rect.center().y() - amount * 5))
        if amount > 0:
            font = self.font()
            font.setPixelSize(10)
            font.setWeight(font.Weight.Medium)
            painter.setFont(font)
            painter.setOpacity(amount)
            tip = QRectF(self.width() / 2 - 18, 30, 36, 15)
            painter.setPen(QPen(QColor(255, 255, 255, 190), .7))
            painter.setBrush(QColor(248, 251, 255, 225))
            painter.drawRoundedRect(tip, 8, 8)
            painter.setPen(QColor(38, 57, 80))
            painter.drawText(tip, Qt.AlignCenter, self.text())


class LauncherWindow(GlassWindow):
    capture_requested = Signal()
    settings_requested = Signal()
    notes_requested = Signal()

    COMPACT_WIDTH = 40
    COMPACT_HEIGHT = 40
    COMPACT_RADIUS = 20
    EXPANDED_WIDTH = 224
    HEIGHT = 62
    MORPH_MS = 360
    COLLAPSE_MS = 560
    LEAVE_DELAY_MS = 180

    def __init__(self):
        # A real frameless window keeps native mouse activation/dragging on the
        # same path as the settings window, rather than an auxiliary NSPanel.
        super().__init__(Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setObjectName("launcher")
        self.setWindowTitle("屏幕学习助手 · 快捷入口")
        self.setAccessibleName("快捷入口 · 鼠标移入展开框选、设置和笔记")
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
        self._hover_inside = False
        self._hover_suppressed = False
        self._anchor_right = True
        self._glow_started = monotonic()
        self.resize(self.COMPACT_WIDTH, self.COMPACT_HEIGHT)
        area = QGuiApplication.primaryScreen().availableGeometry()
        self.move(area.right() - self.width() - 24, area.bottom() - self.height() - 24)
        self._anchor = QPoint(self.geometry().right() + 1, self.y() + self.height() // 2)
        self._actions = QWidget(self)
        layout = QHBoxLayout(self._actions)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.capture_button = CapsuleAction("框选", True, self._actions)
        self.settings_button = CapsuleAction("设置", False, self._actions)
        self.notes_button = CapsuleAction("笔记", False, self._actions)
        for item, signal in (
            (self.settings_button, self.settings_requested),
            (self.capture_button, self.capture_requested),
            (self.notes_button, self.notes_requested),
        ):
            item.clicked.connect(signal)
            item.installEventFilter(self)
            layout.addWidget(item)
        self._actions.setFixedSize(192, 46)
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
        self._collapse_timer.setInterval(self.LEAVE_DELAY_MS)
        self._collapse_timer.timeout.connect(self._collapse_if_idle)
        self._glow_timer = QTimer(self)
        self._glow_timer.setTimerType(Qt.PreciseTimer)
        self._glow_timer.setInterval(33)
        self._glow_timer.timeout.connect(self._tick)
        self.setAccessibleDescription("鼠标移入展开，悬停图标显示功能名称；拖动任意位置移动，Esc 收起")

    def glass_is_dark(self):
        return False

    def glass_frost_strength(self):
        # Match the other pages' native Clear glass, without an extra matte layer.
        return 0.0

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

    def _remember_anchor(self, choose_side=True):
        rect = self.geometry()
        if choose_side:
            self._anchor_right = rect.center().x() >= self._area().center().x()
        self._anchor = QPoint(rect.right() + 1 if self._anchor_right else rect.left(),
                              rect.top() + rect.height() // 2)

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
            self._remember_anchor(choose_side=expanded and self._unfold == 0)
        self.expanded = expanded
        self._collapse_timer.stop()
        self._animation.stop()
        self._actions.setEnabled(False)
        if animate:
            self._animation.setDuration(self.MORPH_MS if expanded else self.COLLAPSE_MS)
            self._animation.setEasingCurve(QEasingCurve.OutCubic if expanded else QEasingCurve.InOutCubic)
            self._glow_timer.setInterval(16)
            self._animation.setStartValue(self._unfold)
            self._animation.setEndValue(target)
            self._animation.start()
        else:
            self._set_unfold(target)
            self._finish_transition()
        self.setAccessibleName("快捷入口" if expanded else "快捷入口 · 鼠标移入展开框选、设置和笔记")

    def _finish_transition(self):
        self._glow_timer.setInterval(33)
        self._actions.setEnabled(self.expanded)
        self._actions.setVisible(self.expanded)
        if self.expanded and self._keyboard_open:
            self.capture_button.setFocus(Qt.TabFocusReason)
        if self.expanded and not self._pointer_inside():
            self._schedule_collapse()
        self.update()

    def _schedule_collapse(self):
        if (self.expanded and not self._keyboard_open and self._drag_origin is None
                and not self._collapse_timer.isActive()):
            self._collapse_timer.start()

    def _pointer_inside(self):
        point = self.mapFromGlobal(QCursor.pos())
        radius = self.glass_corner_radius()
        cx = max(radius, min(point.x(), self.width() - radius))
        cy = max(radius, min(point.y(), self.height() - radius))
        return (self.rect().contains(point)
                and (point.x() - cx) ** 2 + (point.y() - cy) ** 2 <= radius ** 2)

    def _collapse_if_idle(self):
        # Native glass can leave QWidget.underMouse() stale after a resize.
        # Use the actual desktop pointer to avoid a permanently expanded particle.
        if self._drag_origin is not None or self._keyboard_open:
            return
        if self._pointer_inside():
            return
        self.set_expanded(False)

    def _tick(self):
        if QGuiApplication.platformName() != "offscreen":
            self._sync_pointer_hover()
        self.update()

    def _sync_pointer_hover(self):
        if not self.isVisible():
            return
        inside = self._pointer_inside()
        if inside:
            self._collapse_timer.stop()
            self._keyboard_open = False
            if not self._hover_suppressed and self._drag_origin is None:
                self.set_expanded(True)
        else:
            self._hover_suppressed = False
            self._schedule_collapse()
        self._hover_inside = inside
        for action in (self.capture_button, self.settings_button, self.notes_button):
            hovered = (inside and action.isVisible() and action.isEnabled()
                       and action.rect().contains(action.mapFromGlobal(QCursor.pos())))
            action.set_pointer_hover(hovered)

    def enterEvent(self, event):
        self._collapse_timer.stop()
        self._keyboard_open = False
        if self._drag_origin is None and not self._hover_suppressed:
            self.set_expanded(True)
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._schedule_collapse()
        super().leaveEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        self._glow_timer.start()

    def hideEvent(self, event):
        self._collapse_timer.stop()
        self._glow_timer.stop()
        self._glow_timer.setInterval(33)
        self._animation.stop()
        self._press_animation.stop()
        self._pulse_animation.stop()
        self._drag_origin = None
        self._keyboard_open = False
        self._hover_inside = False
        self._hover_suppressed = False
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
            point = self.mapFromGlobal(event.globalPosition().toPoint())
            self._pointer = QPointF(point.x() / self.width(), point.y() / self.height())
            self._animate_pressure(1.0)
            self._pulse_animation.stop()
            self._pulse_animation.setStartValue(0.0)
            self._pulse_animation.setEndValue(1.0)
            self._pulse_animation.start()

    def mouseMoveEvent(self, event):
        point = self.mapFromGlobal(event.globalPosition().toPoint())
        self._pointer = QPointF(max(0, min(1, point.x() / self.width())),
                                max(0, min(1, point.y() / self.height())))
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

    def eventFilter(self, watched, event):
        # QPushButton consumes press/move events before its parent sees them.
        # Observe the whole press, but preserve an ordinary click until movement
        # crosses Qt's drag threshold. After a drag, swallow release so the action
        # is not triggered while moving the capsule.
        if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            self.mousePressEvent(event)
        elif event.type() == QEvent.MouseMove and self._drag_origin is not None:
            self.mouseMoveEvent(event)
            if self._dragged:
                watched.setDown(False)
                return True
        elif event.type() == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
            if self._drag_origin is not None:
                if self._dragged:
                    watched.setDown(False)
                    self.mouseReleaseEvent(event)
                    return True
                self._animate_pressure(0.0)
                self._drag_origin = None
                self._drag_anchor = None
                self._collapse_timer.start()
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._keyboard_open = False
            self._hover_suppressed = True
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
        alpha = 1 if self.native_glass else 4.5
        tint.setColorAt(0, QColor(255, 255, 255, round(26 * alpha)))
        tint.setColorAt(.45, QColor(244, 249, 255, round(12 * alpha)))
        tint.setColorAt(1, QColor(218, 233, 251, round(20 * alpha)))
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
                   50 + 10 * sin(phase + dx))
        touch = QPointF(self.width() * self._pointer.x(), self.height() * self._pointer.y())
        radial(painter, path, touch, 42, '#DBF8FF', 10 + self._press * 32)
        # Curved specular streaks and paired bright/dark rims give thickness to the glass.
        sheen = QLinearGradient(0, rect.top(), 0, rect.bottom())
        sheen.setColorAt(0, QColor(255, 255, 255, 24))
        sheen.setColorAt(.22, QColor(255, 255, 255, 2))
        sheen.setColorAt(.72, QColor(255, 255, 255, 0))
        sheen.setColorAt(1, QColor(190, 224, 250, 12))
        painter.fillPath(path, sheen)
        inner = rect.adjusted(2, 2, -2, -2)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor(4, 16, 30, 35), .9))
        painter.drawRoundedRect(inner, max(0, radius - 2), max(0, radius - 2))
        rim = QLinearGradient(rect.topLeft(), rect.bottomRight())
        rim.setColorAt(0, QColor(255, 255, 255, 180))
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
