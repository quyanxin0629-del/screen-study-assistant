"""Native glass backdrops with a translucent fallback for older systems."""

from __future__ import annotations

import json
import math
import sys

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from .config import app_directory


class GlassWindow(QWidget):
    def glass_corner_radius(self):
        return 28

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._effect is None:
            return
        radius = self.glass_corner_radius()
        for effect in (self._effect, self._frost):
            if effect is not None:
                if hasattr(effect, "setCornerRadius_"):
                    effect.setCornerRadius_(radius)
                effect.layer().setCornerRadius_(radius)
        if self._effect is not None and not self.windowFlags() & Qt.FramelessWindowHint:
            return
        if self._effect is not None:
            import ctypes

            import objc

            view = objc.objc_object(c_void_p=ctypes.c_void_p(int(self.winId())))
            view.layer().setCornerRadius_(radius)

    def __init__(self, flags=None):
        if flags is None:
            flags = Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
        super().__init__(None, flags)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.native_glass = False
        self._effect = None
        self._frost = None
        self._titlebar_tint = None
        self._native_titlebar_height = 0
        self._native_attempted = False
        self.blur_strength = 0.40
        self._appearance_path = app_directory() / "appearance.json"
        self._appearance_stamp = object()
        self._refresh_appearance()
        self._appearance_timer = QTimer(self)
        self._appearance_timer.setInterval(800)
        self._appearance_timer.timeout.connect(self._refresh_appearance)
        self._appearance_timer.start()

    def _refresh_appearance(self):
        """Reload only numeric appearance data; never modify the signed bundle."""
        try:
            stat = self._appearance_path.stat()
            stamp = (stat.st_mtime_ns, stat.st_size)
        except FileNotFoundError:
            stat, stamp = None, None
        except OSError:
            return
        if stamp == self._appearance_stamp:
            return
        self._appearance_stamp = stamp
        strength = 0.40
        if stat is not None:
            try:
                if stat.st_size > 8192:
                    return
                data = json.loads(self._appearance_path.read_text(encoding="utf-8"))
                strength = data["blur_strength"]
                if (isinstance(strength, bool) or not isinstance(strength, (int, float))
                        or not math.isfinite(strength) or not 0 <= strength <= 1):
                    return
            except (OSError, ValueError, TypeError, KeyError):
                return
        self.blur_strength = float(strength)
        if self._frost is not None:
            self._frost.setAlphaValue_(self.blur_strength)
        self._update_titlebar_tint()
        self.update()

    def _update_titlebar_tint(self):
        if self._titlebar_tint is not None:
            import Quartz

            alpha = round(48 + 80 * self.blur_strength) / 255
            self._titlebar_tint.layer().setBackgroundColor_(
                Quartz.CGColorCreateGenericRGB(1.0, 1.0, 1.0, alpha)
            )

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_appearance()
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
                parent = view.superview()
                framed = not self.windowFlags() & Qt.FramelessWindowHint
                radius = self.glass_corner_radius()
                # A titled Qt view stops below the traffic lights. Cover the
                # entire native frame so the titlebar receives the same blur.
                backdrop_frame = parent.bounds() if framed else view.frame()
                if hasattr(AppKit, "NSGlassEffectView"):
                    effect = AppKit.NSGlassEffectView.alloc().initWithFrame_(backdrop_frame)
                    effect.setStyle_(AppKit.NSGlassEffectViewStyleClear)
                    effect.setCornerRadius_(radius)
                    # Preserve Qt's content view and accessibility hierarchy.
                    effect.setContentView_(AppKit.NSView.alloc().initWithFrame_(effect.bounds()))
                    parent.addSubview_positioned_relativeTo_(
                        effect, AppKit.NSWindowBelow, view
                    )
                    # A lightly blended native blur softens the clear glass
                    # without replacing it with the opaque regular material.
                    frost = AppKit.NSVisualEffectView.alloc().initWithFrame_(backdrop_frame)
                    frost.setMaterial_(AppKit.NSVisualEffectMaterialHUDWindow)
                    frost.setBlendingMode_(AppKit.NSVisualEffectBlendingModeBehindWindow)
                    frost.setState_(AppKit.NSVisualEffectStateActive)
                    frost.setAppearance_(
                        AppKit.NSAppearance.appearanceNamed_(AppKit.NSAppearanceNameAqua)
                    )
                    frost.setAlphaValue_(self.blur_strength)
                    frost.setAutoresizingMask_(18)
                    frost.setWantsLayer_(True)
                    frost.layer().setCornerRadius_(radius)
                    frost.layer().setMasksToBounds_(True)
                    parent.addSubview_positioned_relativeTo_(
                        frost, AppKit.NSWindowBelow, effect
                    )
                    self._frost = frost
                else:
                    effect = AppKit.NSVisualEffectView.alloc().initWithFrame_(backdrop_frame)
                    effect.setMaterial_(AppKit.NSVisualEffectMaterialHUDWindow)
                    effect.setBlendingMode_(AppKit.NSVisualEffectBlendingModeBehindWindow)
                    effect.setState_(AppKit.NSVisualEffectStateActive)
                    if framed:
                        parent.addSubview_positioned_relativeTo_(effect, AppKit.NSWindowBelow, view)
                    else:
                        view.addSubview_positioned_relativeTo_(effect, AppKit.NSWindowBelow, None)
                effect.setAppearance_(
                    AppKit.NSAppearance.appearanceNamed_(AppKit.NSAppearanceNameAqua)
                )
                if hasattr(effect, "setTintColor_"):
                    effect.setTintColor_(AppKit.NSColor.colorWithCalibratedWhite_alpha_(1.0, 0.06))
                effect.setAutoresizingMask_(18)  # width + height
                effect.setWantsLayer_(True)
                effect.layer().setCornerRadius_(radius)
                effect.layer().setMasksToBounds_(True)
                view.setWantsLayer_(True)
                view.layer().setCornerRadius_(0 if framed else radius)
                view.layer().setMasksToBounds_(True)
                window.setOpaque_(False)
                window.setBackgroundColor_(AppKit.NSColor.clearColor())
                window.setHasShadow_(True)
                if framed:
                    window.setTitlebarAppearsTransparent_(True)
                    if (hasattr(window, "setTitlebarSeparatorStyle_")
                            and hasattr(AppKit, "NSTitlebarSeparatorStyleNone")):
                        window.setTitlebarSeparatorStyle_(AppKit.NSTitlebarSeparatorStyleNone)
                    top = view.frame().origin.y + view.frame().size.height
                    height = max(0, parent.bounds().size.height - top)
                    self._native_titlebar_height = height
                    if height:
                        tint = AppKit.NSView.alloc().initWithFrame_(
                            AppKit.NSMakeRect(0, top, parent.bounds().size.width, height)
                        )
                        tint.setWantsLayer_(True)
                        tint.setAutoresizingMask_(AppKit.NSViewWidthSizable | AppKit.NSViewMinYMargin)
                        parent.addSubview_positioned_relativeTo_(tint, AppKit.NSWindowBelow, view)
                        self._titlebar_tint = tint
                        self._update_titlebar_tint()
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
        if self.native_glass and self._native_titlebar_height:
            # Extend the painted surface past the content edge: no second pair
            # of rounded corners or horizontal rim underneath the titlebar.
            rect.setTop(-self._native_titlebar_height)
        path = QPainterPath()
        radius = self.glass_corner_radius()
        path.addRoundedRect(rect, radius, radius)
        gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
        alpha = round(48 + 80 * self.blur_strength) if self.native_glass else 165
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
