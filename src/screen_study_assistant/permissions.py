"""Screen capture access checks without confusing packaged apps with Python."""

from __future__ import annotations

import sys


def screen_capture_allowed(quartz, may_request=True) -> bool:
    if quartz.CGPreflightScreenCaptureAccess():
        return True
    # A permission grant may become visible through the request before preflight refreshes.
    if not may_request:
        return False
    if quartz.CGRequestScreenCaptureAccess():
        return True
    return bool(quartz.CGPreflightScreenCaptureAccess())


def screen_capture_message() -> str:
    if getattr(sys, "frozen", False):
        return (
            "macOS 尚未允许当前版本截图。请在系统设置 → 隐私与安全性 → 录屏与系统录音中"
            "允许 ScreenStudyAssistant，再用 ⌘Q 完整退出后重新打开。"
            "若开关已经打开且最近更新过开发版，请移除旧的 ScreenStudyAssistant 条目，"
            "重新添加当前启动的 ScreenStudyAssistant.app 并允许。"
        )
    return (
        "macOS 尚未允许当前 Python 进程截图。请在系统设置 → 隐私与安全性 → "
        "录屏与系统录音中允许实际启动它的 Python 或终端，然后完整退出并重新启动。"
    )
