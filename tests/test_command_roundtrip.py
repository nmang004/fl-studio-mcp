"""The full path: server writes a command, sends a trigger, reads a response.

This runs with no FL Studio and no MIDI hardware. Everything except the MIDI
cable is real: the server's own MIDIConnection, the controller's own
execute_pending_command, and the real JSON files in a temporary directory.
"""

from __future__ import annotations

import json

import pytest

from fl_studio_mcp.utils.midi_connection import MIDIConnection


@pytest.fixture
def connection(fl_env):
    """A MIDIConnection pointed at the in-process controller."""
    conn = MIDIConnection()
    conn._command_file = fl_env.command_file
    conn._response_file = fl_env.response_file
    # The port is already wired by the fixture; skip the virtual port handshake.
    conn._port = fl_env.midi_port
    conn._port_name = fl_env.midi_port.name
    conn._connected = True
    return conn


def test_round_trip_returns_the_controllers_answer(connection):
    result = connection.send_command("mixer.getTrackCount", timeout=2.0)
    assert result["success"] is True
    assert result["count"] == 8


def test_exactly_one_trigger_per_command(connection, fl_env):
    connection.send_command("mixer.getTrackCount", timeout=2.0)
    assert fl_env.trigger_count == 1


def test_the_command_file_records_what_was_sent(connection, fl_env):
    connection.send_command("channels.getCount", {"global_count": True}, timeout=2.0)
    written = json.loads(fl_env.command_file.read_text())
    assert written["action"] == "channels.getCount"
    assert written["params"] == {"global_count": True}


def test_no_stray_trigger_notes_are_sent(connection, fl_env):
    """A trigger note on a real port is audible on someone's hardware."""
    connection.send_command("mixer.getTrackCount", timeout=2.0)
    notes = [m for m in fl_env.midi_port.sent if getattr(m, "type", None) == "note_on"]
    assert [m.note for m in notes] == [127]


def test_a_mutation_through_the_round_trip_lands_on_the_right_channel(connection, fl_env):
    result = connection.send_command(
        "channels.setVolume", {"index": 2, "volume": 0.25}, timeout=2.0
    )
    assert result["success"] is True
    assert fl_env.project.channel(2).volume == pytest.approx(0.25)
    assert fl_env.project.channel(0).volume == pytest.approx(0.8)


def test_a_timeout_reports_failure_not_success(connection, fl_env, monkeypatch):
    """FL not answering must never look like success."""
    monkeypatch.setattr(fl_env.controller, "execute_pending_command", lambda: None)
    result = connection.send_command("mixer.getTrackCount", timeout=0.05)
    assert result["success"] is False
    assert "Timeout" in result["error"]


def test_an_unknown_action_is_not_reported_as_success(connection):
    """The reproduced live bug: success True alongside an error string."""
    result = connection.send_command("bogus.doesNotExist", timeout=2.0)
    assert result.get("success") is not True, (
        "an unknown action must not be reported as a success; see the "
        "unknown-action finding in ROADMAP.md"
    )
    assert result["error"]


def test_the_response_is_consumed_so_the_next_command_sees_a_fresh_one(connection, fl_env):
    first = connection.send_command("mixer.getTrackCount", timeout=2.0)
    second = connection.send_command("channels.getCount", timeout=2.0)
    assert first["count"] == 8
    assert second["count"] == 4, "the second command read the first command's response"


def test_a_context_manager_free_call_does_not_leak_the_response_file(connection, fl_env):
    connection.send_command("mixer.getTrackCount", timeout=2.0)
    assert not fl_env.response_file.exists()
