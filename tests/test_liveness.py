"""A port that opened is not a connection.

FL Studio takes 2.0 to 2.3 seconds to bind a newly created virtual port, and
commands sent before that are dropped silently, which is indistinguishable from
FL not being started at all. Opening a port proves only that CoreMIDI accepted the
name.
"""

from __future__ import annotations

import pytest

from fl_studio_mcp.utils.midi_connection import MIDIConnection


@pytest.fixture
def connection(fl_env):
    """A MIDIConnection wired to the in-process controller."""
    conn = MIDIConnection()
    conn._command_file = fl_env.command_file
    conn._response_file = fl_env.response_file
    conn._port = fl_env.midi_port
    conn._port_name = fl_env.midi_port.name
    conn._connected = True
    return conn


def test_ping_answers_with_the_environment(connection):
    """One round trip, and the version facts come with it.

    45 and "FL Studio 2026" are what the fake reports, and both match what live
    FL Studio 2026 build 5406 reported in the Phase 0 run.
    """
    result = connection.ping()
    assert result["success"] is True
    assert result["pong"] is True
    assert result["api_version"] == 45
    assert result["fl_version"] == "FL Studio 2026"
    assert result["safe_to_edit"] is True


def test_wait_until_responsive_succeeds_immediately_when_fl_answers(connection):
    assert connection.wait_until_responsive(timeout=1.0) is True


def test_wait_until_responsive_fails_when_nothing_answers(connection, fl_env, monkeypatch):
    """It must give up and say so, rather than hang for the whole timeout."""
    monkeypatch.setattr(fl_env.controller, "execute_pending_command", lambda: None)
    assert connection.wait_until_responsive(timeout=0.3, interval=0.05) is False


def test_wait_until_responsive_retries_through_the_bind_window(
    connection, fl_env, monkeypatch
):
    """What FL does while it is still binding a new port: drop, drop, answer."""
    original = fl_env.controller.execute_pending_command
    attempts = {"n": 0}

    def drop_the_first_two():
        attempts["n"] += 1
        if attempts["n"] <= 2:
            return
        original()

    monkeypatch.setattr(fl_env.controller, "execute_pending_command", drop_the_first_two)

    assert connection.wait_until_responsive(timeout=2.0, interval=0.05) is True
    assert attempts["n"] >= 3, "the retry loop did not retry"


def test_ping_reports_failure_when_nothing_answers(connection, fl_env, monkeypatch):
    monkeypatch.setattr(fl_env.controller, "execute_pending_command", lambda: None)
    result = connection.ping(timeout=0.05)
    assert result["success"] is False
    assert "Timeout" in result["error"]


def test_ping_survives_a_controller_without_the_action(connection, fl_env, monkeypatch):
    """An older controller answers the ping with an unknown action error."""
    monkeypatch.setattr(
        fl_env.controller,
        "dispatch_command",
        lambda action, params: {"error": f"Unknown action: {action}"},
    )
    result = connection.ping(timeout=1.0)
    assert result["success"] is False
    assert "unknown action" in result["error"].lower()
