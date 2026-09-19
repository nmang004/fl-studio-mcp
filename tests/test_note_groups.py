"""A group makes "remove the arpeggio you added" exact.

Without one, removing a phrase means matching on pitch and time, which is wrong the
moment the user has written something similar by hand. The group index comes from
score.getNextFreeGroupIndex, which lives in the piano roll sandbox and nowhere else,
which is why the script assigns it rather than the server.
"""

from __future__ import annotations

import json


def write(fl_env, requests):
    fl_env.request_file.write_text(json.dumps(requests))
    fl_env.pyscript.apply()


def reply(fl_env):
    return json.loads(fl_env.piano_roll_response_file.read_text())


def test_a_request_asking_for_a_group_gets_one(fl_env):
    write(fl_env, [{"action": "add_notes", "id": "g", "group": True, "notes": [
        {"midi": 60, "time": 0.0, "duration": 1.0},
        {"midi": 64, "time": 1.0, "duration": 1.0},
    ]}])
    groups = {note.group for note in fl_env.project.notes}
    assert len(groups) == 1, "the notes are not one group"
    assert groups != {0}, "group 0 means ungrouped, so it is not an assignment"
    assert reply(fl_env)["group"] in groups


def test_two_grouped_requests_get_different_groups(fl_env):
    write(fl_env, [
        {"action": "add_notes", "id": "a", "group": True,
         "notes": [{"midi": 60, "time": 0.0, "duration": 1.0}]},
        {"action": "add_notes", "id": "b", "group": True,
         "notes": [{"midi": 67, "time": 0.0, "duration": 1.0}]},
    ])
    assert len({note.group for note in fl_env.project.notes}) == 2


def test_a_grouped_chord_is_one_group(fl_env):
    write(fl_env, [{"action": "add_chord", "id": "c", "group": True, "time": 0.0,
                    "duration": 1.0, "notes": [{"midi": 60}, {"midi": 64}, {"midi": 67}]}])
    assert len({note.group for note in fl_env.project.notes}) == 1


def test_an_explicit_group_number_is_honoured(fl_env):
    write(fl_env, [{"action": "add_notes", "id": "e", "notes": [
        {"midi": 60, "time": 0.0, "duration": 1.0, "group": 5},
    ]}])
    assert fl_env.project.notes[0].group == 5
    assert reply(fl_env)["group"] is None, "nothing was assigned"


def test_a_per_note_group_beats_the_request_group(fl_env):
    """A caller that named a group for one note meant it."""
    write(fl_env, [{"action": "add_notes", "id": "m", "group": True, "notes": [
        {"midi": 60, "time": 0.0, "duration": 1.0},
        {"midi": 64, "time": 1.0, "duration": 1.0, "group": 9},
    ]}])
    assigned = reply(fl_env)["group"]
    assert fl_env.project.notes[0].group == assigned
    assert fl_env.project.notes[1].group == 9


def test_notes_without_a_group_stay_ungrouped(fl_env):
    write(fl_env, [{"action": "add_notes", "id": "n", "notes": [
        {"midi": 60, "time": 0.0, "duration": 1.0},
    ]}])
    assert fl_env.project.notes[0].group == 0
    assert reply(fl_env)["group"] is None


def test_the_reply_names_the_group(fl_env):
    write(fl_env, [{"action": "add_notes", "id": "named", "group": True,
                    "group_name": "bassline", "notes": [
                        {"midi": 36, "time": 0.0, "duration": 1.0},
                    ]}])
    response = reply(fl_env)
    assert response["group"] is not None
    assert response["group_name"] == "bassline"


def test_a_second_queued_request_does_not_erase_the_first_ones_fields(fl_env):
    """Found live: a context read followed by a write made the context fields null.

    The reply echoed those fields only when exactly one response came back, so two
    queued requests erased all of them and the caller was told the project's key was
    unknown when the script had answered it.
    """
    write(fl_env, [
        {"action": "get_context", "id": "ctx"},
        {"action": "add_notes", "id": "notes", "group": True,
         "notes": [{"midi": 36, "time": 0.0, "duration": 1.0}]},
    ])
    response = reply(fl_env)
    assert response["success"] is True
    assert response["requests_processed"] == 2
    by_id = {entry["id"]: entry for entry in response["responses"]}
    assert by_id["ctx"]["root_note"] == fl_env.project.snap_root_note
    assert by_id["ctx"]["scale_helper"] == fl_env.project.snap_scale_helper
    assert by_id["ctx"]["tsnum"] == fl_env.project.tsnum
    assert by_id["notes"]["group"] is not None, "the write's group was lost too"
