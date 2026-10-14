"""Native glass backdrops with a translucent fallback for older systems."""

from __future__ import annotations

import sys

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget


class GlassWindow(QWidget):
    def __init__(self):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.native_glass = False
        self._effect = None
        self._native_attempted = False

    def showEvent(self, event):
        super().showEvent(event)
        if not self._native_attempted and QGuiApplication.platformName() != "offscreen":
            self._native_attempted = True
            QTimer.singleShot(0, self._enable_native)

    def _enable_native(self):
        try:
            if sys.platform == "darwin":
                import ctypes

                import AppKit
                import objc

                view = objc.objc_object(c_void_p=ctypes.c_void_p(int(self.winId())))
                window = view.window()
                if hasattr(AppKit, "NSGlassEffectView"):
                    effect = AppKit.NSGlassEffectView.alloc().initWithFrame_(view.frame())
                    effect.setStyle_(AppKit.NSGlassEffectViewStyleClear)
                    effect.setCornerRadius_(28)
                    # Preserve Qt's content view and accessibility hierarchy.
                    effect.setContentView_(AppKit.NSView.alloc().initWithFrame_(effect.bounds()))
                    view.superview().addSubview_positioned_relativeTo_(
                        effect, AppKit.NSWindowBelow, view
                    )
                else:
                    effect = AppKit.NSVisualEffectView.alloc().initWithFrame_(view.frame())
                    effect.setMaterial_(AppKit.NSVisualEffectMaterialHUDWindow)
                    effect.setBlendingMode_(AppKit.NSVisualEffectBlendingModeBehindWindow)
                    effect.setState_(AppKit.NSVisualEffectStateActive)
                    view.addSubview_positioned_relativeTo_(effect, AppKit.NSWindowBelow, None)
                effect.setAppearance_(
                    AppKit.NSAppearance.appearanceNamed_(AppKit.NSAppearanceNameAqua)
                )
                if hasattr(effect, "setTintColor_"):
                    effect.setTintColor_(AppKit.NSColor.colorWithCalibratedWhite_alpha_(1.0, 0.04))
                effect.setAutoresizingMask_(18)  # width + height
                effect.setWantsLayer_(True)
                effect.layer().setCornerRadius_(28)
                effect.layer().setMasksToBounds_(True)
                view.setWantsLayer_(True)
                view.layer().setCornerRadius_(28)
                view.layer().setMasksToBounds_(True)
                window.setOpaque_(False)
                window.setBackgroundColor_(AppKit.NSColor.clearColor())
                window.setHasShadow_(True)
                self._effect = effect
                self.native_glass = True
            elif sys.platform == "win32":
                import ctypes
                from ctypes import wintypes

                dwm = ctypes.WinDLL("dwmapi")
                set_attribute = dwm.DwmSetWindowAttribute
                set_attribute.argtypes = [
                    wintypes.HWND,
                    wintypes.DWORD,
                    ctypes.c_void_p,
                    wintypes.DWORD,
                ]
                set_attribute.restype = ctypes.c_long
                hwnd = int(self.winId())
                corners = ctypes.c_int(2)
                set_attribute(hwnd, 33, ctypes.byref(corners), ctypes.sizeof(corners))
                backdrop = ctypes.c_int(3)  # Windows 11 desktop acrylic
                result = set_attribute(hwnd, 38, ctypes.byref(backdrop), ctypes.sizeof(backdrop))
                self.native_glass = result == 0
        except Exception:
            # Native effects are optional; functional UI remains available.
            self.native_glass = False
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.8, 0.8, -0.8, -0.8)
        path = QPainterPath()
        path.addRoundedRect(rect, 28, 28)
        gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
        alpha = 48 if self.native_glass else 165
        gradient.setColorAt(0, QColor(255, 255, 255, alpha))
        gradient.setColorAt(0.48, QColor(247, 248, 252, alpha))
        gradient.setColorAt(1, QColor(235, 239, 247, alpha))
        painter.fillPath(path, gradient)
        rim = QLinearGradient(rect.topLeft(), rect.bottomRight())
        rim.setColorAt(0, QColor(255, 255, 255, 245))
        rim.setColorAt(0.5, QColor(255, 255, 255, 90))
        rim.setColorAt(1, QColor(176, 193, 224, 150))
        painter.setPen(QPen(rim, 1.4))
        painter.drawPath(path)
