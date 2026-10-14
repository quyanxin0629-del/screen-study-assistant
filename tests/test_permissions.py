from types import SimpleNamespace

import pytest

from screen_study_assistant.permissions import screen_capture_allowed, screen_capture_message


@pytest.mark.parametrize(
    "preflight, grant, expected, requests",
    [
        ([True], False, True, 0),
        ([False], True, True, 1),
        ([False, True], False, True, 1),
        ([False, False], False, False, 1),
    ],
)
def test_capture_access_accepts_a_successful_grant(preflight, grant, expected, requests):
    values = iter(preflight)
    calls = []
    api = SimpleNamespace(
        CGPreflightScreenCaptureAccess=lambda: next(values),
        CGRequestScreenCaptureAccess=lambda: calls.append(True) or grant,
    )
    assert screen_capture_allowed(api) is expected
    assert len(calls) == requests


def test_packaged_permission_message_targets_app_not_python(monkeypatch):
    import sys

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    message = screen_capture_message()
    assert "ScreenStudyAssistant" in message
    assert "Python" not in message and "终端" not in message
    assert "移除旧的" in message
    monkeypatch.setattr(sys, "frozen", False)
    assert "Python" in screen_capture_message()


def test_denied_capture_does_not_repeat_os_permission_dialog():
    calls = []
    api = SimpleNamespace(
        CGPreflightScreenCaptureAccess=lambda: False,
        CGRequestScreenCaptureAccess=lambda: calls.append(True) or False,
    )
    assert not screen_capture_allowed(api)
    for _ in range(5):
        assert not screen_capture_allowed(api, may_request=False)
    assert calls == [True]
