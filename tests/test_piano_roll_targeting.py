"""A piano roll tool must say which piano roll it wrote to.

Before this, notes landed in whichever piano roll happened to be focused. The
failure was invisible: the tool reported success, the notes were real, and they
were in the wrong place.
"""

from __future__ import annotations

import json

import pytest

from fl_studio_mcp.tools import piano_roll


@pytest.fixture
def wired(fl_env, monkeypatch):
    """The piano roll tools wired to the in-process controller."""
    from fl_studio_mcp.utils.midi_connection import MIDIConnection

    conn = MIDIConnection()
    conn._command_file = fl_env.command_file
    conn._response_file = fl_env.response_file
    conn._port = fl_env.midi_port
    conn._connected = True

    monkeypatch.setattr(piano_roll, "get_connection", lambda: conn, raising=False)
    monkeypatch.setattr(piano_roll, "piano_roll_scripts_dir", lambda: fl_env.piano_roll_dir)

    def fake_trigger(delay: float = 0.0) -> bool:
        fl_env.pyscript.apply()
        return True

    monkeypatch.setattr(piano_roll, "trigger_fl_studio", fake_trigger)
    yield fl_env


def test_target_asks_the_controller_to_select_the_channel(wired):
    result = piano_roll.target(2)
    assert result["targeted"] == 2
    assert wired.project.selected_channel == 2


def test_target_refuses_a_channel_that_does_not_exist(wired):
    result = piano_roll.target(99)
    assert "error" in result
    assert "99" in result["error"]


def test_send_request_with_a_channel_targets_first(wired):
    result = piano_roll.send_request(
        {"action": "add_notes", "notes": [{"midi": 60, "time": 0.0, "duration": 1.0}]},
        timeout=1.0,
        channel=1,
    )
    assert result["success"] is True
    assert wired.project.selected_channel == 1
    assert result["target_channel"] == 1
    assert result["target_channel_name"] == "Channel 2"


def test_send_request_without_a_channel_does_not_target(wired):
    """Leaving the argument out keeps the old behaviour rather than guessing."""
    wired.project.selected_channel = 2
    piano_roll.send_request(
        {"action": "add_notes", "notes": [{"midi": 60, "time": 0.0, "duration": 1.0}]},
        timeout=1.0,
    )
    assert wired.project.selected_channel == 2


def test_a_failed_target_stops_before_the_trigger(wired, monkeypatch):
    """A trigger after a failed target would write to an unknown piano roll."""
    triggered = []

    def record_trigger(delay: float = 0.0) -> bool:
        triggered.append(1)
        return True

    monkeypatch.setattr(piano_roll, "trigger_fl_studio", record_trigger)

    result = piano_roll.send_request({"action": "clear"}, timeout=0.05, channel=99)

    assert result["success"] is False
    assert "99" in result["error"]
    assert triggered == [], "the script was triggered without a confirmed target"


def test_a_mismatched_selection_stops_before_the_trigger(wired, monkeypatch):
    """FL reporting a different selection than was asked for must abort."""
    triggered = []

    def record_trigger(delay: float = 0.0) -> bool:
        triggered.append(1)
        return True

    monkeypatch.setattr(piano_roll, "trigger_fl_studio", record_trigger)
    monkeypatch.setattr(
        piano_roll,
        "target",
        lambda channel: {"targeted": channel, "selected": 4, "channel_name": "other"},
    )

    result = piano_roll.send_request({"action": "clear"}, timeout=0.05, channel=2)

    assert result["success"] is False
    assert "wrong piano roll" in result["error"]
    assert triggered == []


def test_the_target_is_reported_so_the_caller_knows_where_notes_went(wired):
    result = piano_roll.send_request({"action": "clear"}, timeout=1.0, channel=3)
    assert result["target_channel"] == 3
    assert result["target_channel_name"] == "Channel 4"


def test_the_request_file_records_the_target(wired, monkeypatch):
    """A request left on disk for a manual trigger should say where it was meant to go."""
    monkeypatch.setattr(piano_roll, "trigger_fl_studio", lambda delay=0: True)
    piano_roll.send_request(
        {"action": "add_notes", "notes": [{"midi": 60, "time": 0.0, "duration": 1.0}]},
        timeout=0.05,
        channel=2,
    )
    written = json.loads(wired.request_file.read_text())
    assert written[0]["channel"] == 2
