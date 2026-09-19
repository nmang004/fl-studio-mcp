"""The roadmap asks for read-back verification, not just a reported count.

This is the done-condition: fl_send_notes(channel=3, ...) either reports that the
notes landed on channel 3, verified by read-back, or reports a specific failure.
The script's reply says what the script believes it did; the exported state says
what is actually there, and the two can disagree.
"""

from __future__ import annotations

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
    return fl_env


def test_a_successful_write_is_confirmed_by_reading_the_notes_back(wired):
    result = piano_roll.send_request(
        {"action": "add_notes", "notes": [{"midi": 60, "time": 0.0, "duration": 1.0}]},
        timeout=1.0,
        channel=1,
        verify=True,
    )
    assert result["success"] is True
    assert result["verified"] is True
    assert result["verified_notes"] == 1


def test_the_verified_count_is_read_not_taken_from_the_reply(wired):
    """Two notes written and reported, and the read-back agrees independently."""
    result = piano_roll.send_request(
        {"action": "add_notes", "notes": [
            {"midi": 60, "time": 0.0, "duration": 1.0},
            {"midi": 64, "time": 1.0, "duration": 1.0},
        ]},
        timeout=1.0,
        channel=1,
        verify=True,
    )
    assert result["notes_added"] == 2
    assert result["verified_notes"] == 2
    assert len(wired.project.notes) == 2


def test_a_write_that_did_not_land_is_reported_as_a_failure(wired, monkeypatch):
    """The script claims notes were added but the piano roll holds none.

    This is the failure the old code could not see, because it never read the
    state it already exported.
    """
    def claims_success(request):
        return {
            "action": request.get("action"),
            "id": request.get("id"),
            "notes_added": 1,
            "notes_deleted": 0,
            "error": None,
        }

    monkeypatch.setattr(wired.pyscript, "_handle", claims_success)

    result = piano_roll.send_request(
        {"action": "add_notes", "notes": [{"midi": 60, "time": 0.0, "duration": 1.0}]},
        timeout=1.0,
        channel=1,
        verify=True,
    )

    assert result["success"] is False
    assert result["verified"] is False
    assert "did not land" in result["error"]


def test_a_missing_state_export_is_reported_as_unverified(wired, monkeypatch):
    monkeypatch.setattr(piano_roll, "read_state", lambda: None)
    result = piano_roll.send_request(
        {"action": "add_notes", "notes": [{"midi": 60, "time": 0.0, "duration": 1.0}]},
        timeout=1.0,
        channel=1,
        verify=True,
    )
    assert result["success"] is False
    assert result["verified"] is False
    assert "could not be confirmed" in result["error"]


def test_verification_is_off_by_default(wired):
    """Confirming costs a second script run, so it is opt in."""
    result = piano_roll.send_request({"action": "clear"}, timeout=1.0, channel=1)
    assert "verified" not in result


def test_a_clear_that_left_notes_behind_is_reported_as_a_failure(wired, monkeypatch):
    def claims_cleared(request):
        return {
            "action": request.get("action"),
            "id": request.get("id"),
            "notes_added": 0,
            "notes_deleted": 5,
            "error": None,
        }

    monkeypatch.setattr(wired.pyscript, "_handle", claims_cleared)
    wired.project.notes.append(wired.modules["flpianoroll"].Note(number=60))

    result = piano_roll.send_request(
        {"action": "clear"}, timeout=1.0, channel=1, verify=True
    )
    assert result["verified"] is True, "notes remaining is correct for a clear"
    assert result["verified_notes"] == 1
