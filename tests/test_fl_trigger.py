"""The trigger must report what osascript actually did.

The old code ran osascript and returned True without looking at the result, so a
denied Accessibility permission, a missing FL Studio and a working keystroke were
indistinguishable. Reproduced on this machine:

    osascript -e '...keystroke "y"...'
    execution error: System Events got an error:
    osascript is not allowed to send keystrokes. (1002)

The runner used for the real call is injectable so the exit codes can be tested
without a GUI, a permission grant, or FL Studio.
"""

from __future__ import annotations

import subprocess

from fl_studio_mcp.utils.fl_trigger import FLStudioTrigger


class Completed:
    """Just enough of subprocess.CompletedProcess for the trigger to inspect."""

    def __init__(self, returncode: int, stderr: bytes = b"") -> None:
        self.returncode = returncode
        self.stdout = b""
        self.stderr = stderr


def make_trigger(monkeypatch, runner) -> FLStudioTrigger:
    """A macOS trigger whose subprocess calls go through `runner`."""
    monkeypatch.setattr(subprocess, "run", runner)
    trigger = FLStudioTrigger.__new__(FLStudioTrigger)
    trigger._system = "Darwin"
    trigger._trigger_func = trigger._trigger_macos
    return trigger


def test_a_failed_osascript_is_reported_as_failure(monkeypatch):
    def denied(*args, **kwargs):
        return Completed(1, b"not allowed to send keystrokes. (1002)")

    trigger = make_trigger(monkeypatch, denied)
    assert trigger.trigger(delay=0) is False


def test_a_successful_osascript_is_reported_as_success(monkeypatch):
    def allowed(*args, **kwargs):
        return Completed(0)

    trigger = make_trigger(monkeypatch, allowed)
    assert trigger.trigger(delay=0) is True


def test_the_permission_error_is_explained_not_just_denied(monkeypatch):
    """A bare False sends the user hunting. The reason has to be specific."""
    def denied(*args, **kwargs):
        return Completed(1, b"osascript is not allowed to send keystrokes. (1002)")

    trigger = make_trigger(monkeypatch, denied)
    trigger.trigger(delay=0)
    assert "Accessibility" in trigger.last_error
    assert "1002" in trigger.last_error or "keystrokes" in trigger.last_error


def test_a_missing_fl_studio_is_reported_as_failure(monkeypatch):
    def no_fl(*args, **kwargs):
        return Completed(1, b'Can\'t get application "FL Studio".')

    trigger = make_trigger(monkeypatch, no_fl)
    assert trigger.trigger(delay=0) is False


def test_the_runner_is_not_called_when_no_trigger_exists(monkeypatch):
    calls = []

    def runner(*args, **kwargs):
        calls.append(args)
        return Completed(0)

    trigger = make_trigger(monkeypatch, runner)
    trigger._trigger_func = None
    assert trigger.trigger(delay=0) is False
    assert calls == []


def test_a_timeout_is_reported_as_failure(monkeypatch):
    def hangs(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="osascript", timeout=10)

    trigger = make_trigger(monkeypatch, hangs)
    assert trigger.trigger(delay=0) is False


def test_unexpected_errors_fall_back_rather_than_claiming_success(monkeypatch):
    """Any other exception must not be swallowed into a True.

    With osascript unusable, the trigger falls back to pynput, which has no
    display to type into here, so the outcome must be a reported failure.
    """
    def broken(*args, **kwargs):
        raise OSError("no osascript")

    trigger = make_trigger(monkeypatch, broken)
    assert trigger.trigger(delay=0) is False
    assert trigger.last_error
