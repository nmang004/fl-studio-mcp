"""The server must read the reply the piano roll script writes.

Before this, fl_send_notes wrote a file, sent a keystroke, slept two seconds and
reported success unconditionally. Every failure mode looked identical: notes
landing in the wrong piano roll, no piano roll open at all, a missing
Accessibility permission, and a script that was never installed.
"""

from __future__ import annotations

import json

import pytest

from fl_studio_mcp.tools import piano_roll


@pytest.fixture
def wired(fl_env, monkeypatch):
    """Point the piano roll tools at the harness and stub the keystroke.

    The keystroke is the one thing that cannot be faked usefully: it needs a real
    FL Studio, real focus and a real Accessibility permission. Here it runs the
    script in process, which is what a successful keystroke would cause.
    """

    def fake_trigger(delay: float = 0.0) -> bool:
        fl_env.pyscript.apply()
        return True

    monkeypatch.setattr(piano_roll, "piano_roll_scripts_dir", lambda: fl_env.piano_roll_dir)
    monkeypatch.setattr(piano_roll, "trigger_fl_studio", fake_trigger)
    return fl_env


def test_send_request_reports_what_landed(wired):
    result = piano_roll.send_request(
        {"action": "add_notes", "notes": [{"midi": 60, "time": 0.0, "duration": 1.0}]},
        timeout=1.0,
    )
    assert result["success"] is True
    assert result["notes_added"] == 1
    assert [n.number for n in wired.project.notes] == [60]


def test_send_request_reports_a_specific_failure(wired):
    result = piano_roll.send_request(
        {"action": "add_notes", "notes": [{"no_midi": True}]}, timeout=1.0
    )
    assert result["success"] is False
    assert result["error"]


def test_a_failed_keystroke_is_reported(wired, monkeypatch):
    """The old trigger returned True even when osascript failed."""
    monkeypatch.setattr(piano_roll, "trigger_fl_studio", lambda delay=0: False)
    result = piano_roll.send_request({"action": "clear"}, timeout=0.05)
    assert result["success"] is False
    assert "trigger" in result["error"].lower()


def test_a_missing_reply_times_out_rather_than_claiming_success(wired, monkeypatch):
    monkeypatch.setattr(piano_roll, "trigger_fl_studio", lambda delay=0: True)
    result = piano_roll.send_request({"action": "clear"}, timeout=0.05)
    assert result["success"] is False
    assert "reply" in result["error"].lower() or "no " in result["error"].lower()


def test_send_request_assigns_an_id_when_the_caller_does_not(wired):
    result = piano_roll.send_request(
        {"action": "add_notes", "notes": [{"midi": 60, "time": 0.0, "duration": 1.0}]},
        timeout=1.0,
    )
    assert result["id"]


def test_send_request_keeps_the_callers_id(wired):
    result = piano_roll.send_request(
        {"action": "add_notes", "id": "mine", "notes": [
            {"midi": 60, "time": 0.0, "duration": 1.0},
        ]},
        timeout=1.0,
    )
    assert result["id"] == "mine"


def test_send_request_leaves_only_the_request_it_just_wrote(wired, monkeypatch):
    """Appending to a stale queue is what made failed requests replay.

    The trigger is captured rather than run, because a successful run empties the
    queue (that is the script's job, tested in test_piano_roll_script.py). What
    is under test here is that the server replaces the file instead of adding to
    whatever was already in it.
    """
    monkeypatch.setattr(piano_roll, "trigger_fl_studio", lambda delay=0: True)
    wired.request_file.write_text(json.dumps([{"action": "clear", "id": "stale"}]))

    piano_roll.send_request(
        {"action": "add_notes", "id": "fresh", "notes": [
            {"midi": 60, "time": 0.0, "duration": 1.0},
        ]},
        timeout=0.05,
    )

    written = json.loads(wired.request_file.read_text())
    assert [entry["id"] for entry in written] == ["fresh"]


def test_a_stale_reply_is_not_read_as_this_requests_answer(wired):
    """A reply from an earlier request must not be consumed as this one's."""
    wired.piano_roll_response_file.write_text(
        json.dumps({"success": True, "id": "someone-elses", "notes_added": 99})
    )
    result = piano_roll.send_request(
        {"action": "add_notes", "id": "mine", "notes": [
            {"midi": 60, "time": 0.0, "duration": 1.0},
        ]},
        timeout=1.0,
    )
    assert result["id"] == "mine"
    assert result["notes_added"] == 1


def test_send_notes_reports_the_notes_it_landed(wired):
    """The tool itself, through the shared request path."""
    from tests.helpers import load_pyscript  # noqa: F401  (loaded by the fixture)

    # fl_send_notes is a closure registered on the MCP server, so the shared
    # path is what gets exercised here.
    result = piano_roll.send_request(
        {"action": "add_notes", "notes": [
            {"midi": 60, "time": 0.0, "duration": 1.0},
            {"midi": 64, "time": 0.0, "duration": 1.0},
        ]},
        timeout=1.0,
    )
    assert result["success"] is True
    assert result["notes_added"] == 2
    assert sorted(n.number for n in wired.project.notes) == [60, 64]


def test_get_piano_roll_state_refreshes_before_reading(wired):
    """Returning a stale file was the old behaviour."""
    result = piano_roll.refresh_and_read_state()
    assert result["noteCount"] == 0
    wired.project.notes.append(wired.modules["flpianoroll"].Note(number=60))

    result = piano_roll.refresh_and_read_state()
    assert result["noteCount"] == 1, "the state was not refreshed"
