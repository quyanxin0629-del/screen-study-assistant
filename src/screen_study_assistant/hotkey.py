"""Register native global shortcuts without recording keyboard input."""

from __future__ import annotations

import ctypes
import sys
from itertools import count

from PySide6.QtCore import QAbstractNativeEventFilter, QCoreApplication, QObject, Signal
from PySide6.QtGui import QKeySequence

from .config import Settings, normalize_shortcut

_identifiers = count(1)


class WindowsMessageFilter(QAbstractNativeEventFilter):
    def __init__(self, hotkey):
        super().__init__()
        self.hotkey = hotkey

    def nativeEventFilter(self, event_type, message):
        if bytes(event_type) not in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
            return False, 0
        from ctypes import wintypes

        native = ctypes.cast(int(message), ctypes.POINTER(wintypes.MSG)).contents
        if native.message == 0x0312 and native.wParam == self.hotkey.identifier:
            self.hotkey.activated.emit()
            return True, 0
        return False, 0


# Explicit ANSI key codes; keyboard layouts keep these physical key positions.
MAC_KEYS = {
    "A": 0,
    "S": 1,
    "D": 2,
    "F": 3,
    "H": 4,
    "G": 5,
    "Z": 6,
    "X": 7,
    "C": 8,
    "V": 9,
    "B": 11,
    "Q": 12,
    "W": 13,
    "E": 14,
    "R": 15,
    "Y": 16,
    "T": 17,
    "1": 18,
    "2": 19,
    "3": 20,
    "4": 21,
    "6": 22,
    "5": 23,
    "9": 25,
    "7": 26,
    "8": 28,
    "0": 29,
    "O": 31,
    "U": 32,
    "I": 34,
    "P": 35,
    "L": 37,
    "J": 38,
    "K": 40,
    "N": 45,
    "M": 46,
    "Space": 49,
    "F1": 122,
    "F2": 120,
    "F3": 99,
    "F4": 118,
    "F5": 96,
    "F6": 97,
    "F7": 98,
    "F8": 100,
    "F9": 101,
    "F10": 109,
    "F11": 103,
    "F12": 111,
}


class Hotkey(QObject):
    activated = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.native = None
        self.ref = ctypes.c_void_p()
        self.handler_ref = ctypes.c_void_p()
        self.listener = None
        self.win_filter = None
        self.shortcut = Settings().shortcut
        self.identifier = next(_identifiers)
        self.active = False

    @property
    def label(self):
        return QKeySequence(self.shortcut).toString(QKeySequence.NativeText)

    def start(self, shortcut=None):
        if self.active:
            return
        self.shortcut = normalize_shortcut(shortcut or self.shortcut)
        if sys.platform == "darwin":
            self._mac()
        elif sys.platform == "win32":
            self._windows()
        else:
            from pynput.keyboard import GlobalHotKeys

            names = {
                "Meta": "<cmd>",
                "Ctrl": "<ctrl>",
                "Alt": "<alt>",
                "Shift": "<shift>",
                "Space": "<space>",
            }
            sequence = "+".join(
                names.get(p, f"<{p.lower()}>" if p.startswith("F") else p.lower())
                for p in self.shortcut.split("+")
            )
            self.listener = GlobalHotKeys({sequence: self.activated.emit})
            self.listener.start()
        self.active = True

    def _mac(self):
        class EventSpec(ctypes.Structure):
            _fields_ = [("eventClass", ctypes.c_uint32), ("eventKind", ctypes.c_uint32)]

        class HotKeyID(ctypes.Structure):
            _fields_ = [("signature", ctypes.c_uint32), ("id", ctypes.c_uint32)]

        self.native = ctypes.CDLL("/System/Library/Frameworks/Carbon.framework/Carbon")
        lib = self.native
        callback_type = ctypes.CFUNCTYPE(
            ctypes.c_int32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p
        )
        lib.GetApplicationEventTarget.restype = ctypes.c_void_p
        lib.InstallEventHandler.argtypes = [
            ctypes.c_void_p,
            callback_type,
            ctypes.c_uint32,
            ctypes.POINTER(EventSpec),
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        lib.InstallEventHandler.restype = ctypes.c_int32
        lib.RegisterEventHotKey.argtypes = [
            ctypes.c_uint32,
            ctypes.c_uint32,
            HotKeyID,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        lib.RegisterEventHotKey.restype = ctypes.c_int32
        lib.GetEventParameter.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        lib.GetEventParameter.restype = ctypes.c_int32
        lib.UnregisterEventHotKey.argtypes = [ctypes.c_void_p]
        lib.RemoveEventHandler.argtypes = [ctypes.c_void_p]

        def callback(_next, event, _data):
            identifier = HotKeyID()
            status = lib.GetEventParameter(
                event,
                int.from_bytes(b"----", "big"),
                int.from_bytes(b"hkid", "big"),
                None,
                ctypes.sizeof(identifier),
                None,
                ctypes.byref(identifier),
            )
            if (
                status == 0
                and identifier.signature == int.from_bytes(b"SSAI", "big")
                and identifier.id == self.identifier
            ):
                self.activated.emit()
                return 0
            return -9874  # eventNotHandledErr

        self._callback = callback_type(callback)
        spec = EventSpec(int.from_bytes(b"keyb", "big"), 5)  # kEventHotKeyPressed
        target = lib.GetApplicationEventTarget()
        status = lib.InstallEventHandler(
            target,
            self._callback,
            1,
            ctypes.byref(spec),
            None,
            ctypes.byref(self.handler_ref),
        )
        if status != 0:
            raise RuntimeError(f"全局快捷键初始化失败（{status}）。")
        parts = self.shortcut.split("+")
        modifier_codes = {"Meta": 256, "Shift": 512, "Alt": 2048, "Ctrl": 4096}
        modifiers = sum(modifier_codes[p] for p in parts[:-1])
        status = lib.RegisterEventHotKey(
            MAC_KEYS[parts[-1]],
            modifiers,
            HotKeyID(int.from_bytes(b"SSAI", "big"), self.identifier),
            target,
            0,
            ctypes.byref(self.ref),
        )
        if status != 0:
            self.stop()
            raise RuntimeError(f"{self.label} 已被其他应用占用，请换一个组合键。")

    def _windows(self):

        self.native = ctypes.windll.user32
        parts = self.shortcut.split("+")
        modifier_codes = {"Meta": 8, "Shift": 4, "Alt": 1, "Ctrl": 2}
        key = parts[-1]
        code = 32 if key == "Space" else (111 + int(key[1:]) if key.startswith("F") else ord(key))
        modifiers = sum(modifier_codes[p] for p in parts[:-1]) | 0x4000
        if not self.native.RegisterHotKey(None, self.identifier, modifiers, code):
            raise RuntimeError(f"{self.label} 已被其他应用占用，请换一个组合键。")
        self.win_filter = WindowsMessageFilter(self)
        QCoreApplication.instance().installNativeEventFilter(self.win_filter)

    def stop(self):
        self.active = False
        if self.listener:
            self.listener.stop()
        if self.win_filter:
            QCoreApplication.instance().removeNativeEventFilter(self.win_filter)
            self.win_filter = None
        if self.native and sys.platform == "darwin":
            if self.ref.value:
                self.native.UnregisterEventHotKey(self.ref)
                self.ref = ctypes.c_void_p()
            if self.handler_ref.value:
                self.native.RemoveEventHandler(self.handler_ref)
                self.handler_ref = ctypes.c_void_p()
        elif self.native and sys.platform == "win32":
            self.native.UnregisterHotKey(None, self.identifier)
