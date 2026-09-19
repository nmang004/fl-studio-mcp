"""The piano roll script, whose reply the server never used to read.

The script already wrote mcp_response.json. No test existed, so nobody noticed
that the server ignored it, that a failed request stayed in the queue to replay on
the next success, or that the reply had no way to say which request it answered.
"""

from __future__ import annotations

import json

import pytest


def write_request(fl_env, requests) -> None:
    fl_env.request_file.write_text(json.dumps(requests))


def read_response(fl_env) -> dict:
    return json.loads(fl_env.piano_roll_response_file.read_text())


def read_state(fl_env) -> dict:
    return json.loads(fl_env.state_file.read_text())


def test_add_notes_writes_notes_into_the_score(fl_env):
    write_request(fl_env, [{"action": "add_notes", "notes": [
        {"midi": 60, "time": 0.0, "duration": 1.0, "velocity": 0.8},
        {"midi": 64, "time": 0.0, "duration": 1.0, "velocity": 0.8},
    ]}])
    fl_env.pyscript.apply()
    assert sorted(n.number for n in fl_env.project.notes) == [60, 64]
    assert fl_env.project.notes[0].length == fl_env.project.ppq


def test_time_is_converted_from_beats_to_ticks(fl_env):
    """The API works in ticks; callers think in beats. The conversion is ppq."""
    write_request(fl_env, [{"action": "add_notes", "notes": [
        {"midi": 60, "time": 2.0, "duration": 0.5},
    ]}])
    fl_env.pyscript.apply()
    note = fl_env.project.notes[0]
    assert note.time == 2 * fl_env.project.ppq
    assert note.length == fl_env.project.ppq // 2


def test_the_response_says_which_request_it_answered(fl_env):
    write_request(fl_env, [{"action": "add_notes", "id": "abc-123", "notes": [
        {"midi": 60, "time": 0.0, "duration": 1.0},
    ]}])
    fl_env.pyscript.apply()
    assert read_response(fl_env)["id"] == "abc-123"


def test_a_successful_request_reports_success(fl_env):
    write_request(fl_env, [{"action": "add_notes", "id": "ok", "notes": [
        {"midi": 60, "time": 0.0, "duration": 1.0},
    ]}])
    fl_env.pyscript.apply()
    response = read_response(fl_env)
    assert response["success"] is True
    assert response["notes_added"] == 1
    assert response["error"] is None


def test_a_failed_request_reports_failure(fl_env):
    write_request(fl_env, [{"action": "add_notes", "id": "bad", "notes": [
        {"no_midi_key": True},
    ]}])
    fl_env.pyscript.apply()
    response = read_response(fl_env)
    assert response["success"] is False
    assert response["error"]


def test_a_failed_request_does_not_stay_in_the_queue(fl_env):
    """Leaving it queued replays it on the next trigger and duplicates notes."""
    write_request(fl_env, [{"action": "add_notes", "id": "bad", "notes": [{"x": 1}]}])
    fl_env.pyscript.apply()
    assert json.loads(fl_env.request_file.read_text()) == []


def test_an_unknown_action_reports_failure_rather_than_silence(fl_env):
    write_request(fl_env, [{"action": "not_a_real_action", "id": "nope"}])
    fl_env.pyscript.apply()
    response = read_response(fl_env)
    assert response["success"] is False
    assert "not_a_real_action" in response["error"]


def test_a_trigger_with_nothing_queued_still_answers(fl_env):
    """The server waits for a reply, and no reply looks like FL not running."""
    fl_env.pyscript.apply()
    response = read_response(fl_env)
    assert response["success"] is True
    assert response["requests_processed"] == 0


def test_get_state_changes_nothing_and_succeeds(fl_env):
    """Used by fl_get_piano_roll_state, which wants a fresh export and no edits."""
    notes = fl_env.modules["flpianoroll"].Note
    fl_env.project.notes.append(notes(number=60))
    write_request(fl_env, [{"action": "get_state", "id": "g1"}])
    fl_env.pyscript.apply()
    response = read_response(fl_env)
    assert response["success"] is True
    assert response["notes_added"] == 0
    assert len(fl_env.project.notes) == 1


def test_a_corrupt_request_file_reports_failure(fl_env):
    fl_env.request_file.write_text("{not json")
    fl_env.pyscript.apply()
    assert read_response(fl_env)["success"] is False


def test_clear_removes_every_note(fl_env):
    notes = fl_env.modules["flpianoroll"].Note
    fl_env.project.notes.extend([notes(number=60), notes(number=62)])
    write_request(fl_env, [{"action": "clear", "id": "c1"}])
    fl_env.pyscript.apply()
    assert fl_env.project.notes == []
    assert read_response(fl_env)["notes_deleted"] == 2


def test_delete_notes_matches_on_number_and_time(fl_env):
    notes = fl_env.modules["flpianoroll"].Note
    fl_env.project.notes.extend([
        notes(number=60, time=0),
        notes(number=64, time=0),
        notes(number=60, time=96),
    ])
    write_request(fl_env, [{"action": "delete_notes", "id": "d1", "notes": [
        {"midi": 60, "time": 0.0},
    ]}])
    fl_env.pyscript.apply()
    remaining = [(n.number, n.time) for n in fl_env.project.notes]
    assert remaining == [(64, 0), (60, 96)]


def test_add_chord_places_every_note_at_the_base_time(fl_env):
    write_request(fl_env, [{"action": "add_chord", "id": "ch", "time": 1.0,
                            "duration": 2.0, "notes": [
                                {"midi": 60}, {"midi": 64}, {"midi": 67},
                            ]}])
    fl_env.pyscript.apply()
    assert [(n.number, n.time, n.length) for n in fl_env.project.notes] == [
        (60, 96, 192),
        (64, 96, 192),
        (67, 96, 192),
    ]


def test_state_export_reports_the_documented_ppq_and_note_count(fl_env):
    fl_env.project.notes.append(fl_env.modules["flpianoroll"].Note(number=60))
    fl_env.pyscript.apply()
    state = read_state(fl_env)
    assert state["ppq"] == fl_env.project.ppq
    assert state["noteCount"] == 1


def test_slide_porta_and_filter_survive_a_round_trip(fl_env):
    """Phase 4 depends on the fake carrying all sixteen Note properties."""
    write_request(fl_env, [{"action": "add_notes", "id": "expr", "notes": [
        {"midi": 36, "time": 0.0, "duration": 0.5, "slide": True, "porta": True,
         "pitchofs": 0.25, "fcut": 0.6, "fres": 0.3, "pan": -0.4, "group": 7,
         "repeats": 2, "muted": True},
    ]}])
    fl_env.pyscript.apply()
    note = fl_env.project.notes[0]
    assert note.slide is True
    assert note.porta is True
    assert note.pitchofs == pytest.approx(0.25)
    assert note.fcut == pytest.approx(0.6)
    assert note.fres == pytest.approx(0.3)
    assert note.pan == pytest.approx(-0.4)
    assert note.group == 7
    assert note.repeats == 2
    assert note.muted is True


def test_unspecified_expression_is_left_at_the_note_default(fl_env):
    """Writing a zero for every property would flatten expression silently."""
    write_request(fl_env, [{"action": "add_notes", "id": "plain", "notes": [
        {"midi": 60, "time": 0.0, "duration": 1.0, "slide": True},
    ]}])
    fl_env.pyscript.apply()
    note = fl_env.project.notes[0]
    assert note.slide is True
    assert note.velocity == pytest.approx(0.8), "the Note default, not zero"


def test_the_state_export_includes_every_documented_property(fl_env):
    write_request(fl_env, [{"action": "add_notes", "id": "s", "notes": [
        {"midi": 60, "time": 0.0, "duration": 1.0},
    ]}])
    fl_env.pyscript.apply()
    note = read_state(fl_env)["notes"][0]
    for key in ("number", "midi", "time", "time_ticks", "duration", "length_ticks",
                "velocity", "pan", "color", "fcut", "fres", "slide", "porta",
                "pitchofs", "selected", "muted"):
        assert key in note, f"state export is missing {key}"


def test_the_request_queue_is_emptied_before_the_notes_are_written(fl_env):
    """So a crash part way through cannot leave work to replay later."""
    write_request(fl_env, [{"action": "add_notes", "id": "q", "notes": [
        {"midi": 60, "time": 0.0, "duration": 1.0},
    ]}])
    fl_env.pyscript.apply()
    assert json.loads(fl_env.request_file.read_text()) == []
