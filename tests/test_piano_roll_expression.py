"""Every Note property the API exposes has to survive a round trip.

The server wrote four of sixteen. Slide and portamento are what make a 303 line
sound like a 303 line, and no generic MIDI tool writes them, so this is the part of
the fork that is not a wrapper.

The types come from flpianoroll/__note.py rather than from intuition: pitchofs and
repeats are ints, release and velocity and pan and fcut and fres are floats, and
slide, porta, muted and selected are the only four flags.
"""

from __future__ import annotations

import json

import pytest

EXPRESSIVE = {
    "midi": 36,
    "time": 0.0,
    "duration": 0.5,
    "velocity": 0.9,
    "pan": 0.25,
    "color": 0x334455,
    "fcut": 0.6,
    "fres": 0.3,
    "group": 7,
    "muted": True,
    "pitchofs": 12,
    "porta": True,
    "release": 0.4,
    "repeats": 3,
    "selected": True,
    "slide": True,
}


def write(fl_env, notes, action="add_notes"):
    fl_env.request_file.write_text(
        json.dumps([{"action": action, "id": "x", "notes": notes}])
    )
    fl_env.pyscript.apply()


def state(fl_env):
    return json.loads(fl_env.state_file.read_text())


def test_every_property_survives_the_round_trip(fl_env):
    write(fl_env, [EXPRESSIVE])
    note = fl_env.project.notes[0]
    for key, expected in EXPRESSIVE.items():
        if key in ("midi", "time", "duration"):
            continue
        assert getattr(note, key) == pytest.approx(expected), f"{key} did not survive"


def test_the_export_reports_every_property(fl_env):
    write(fl_env, [EXPRESSIVE])
    exported = state(fl_env)["notes"][0]
    for key in ("fcut", "fres", "group", "pitchofs", "release", "repeats",
                "slide", "porta", "pan", "color", "muted", "selected"):
        assert key in exported, f"the export omits {key}"
    assert exported["slide"] is True
    assert exported["pitchofs"] == 12
    assert exported["release"] == pytest.approx(0.4)
    assert exported["repeats"] == 3


def test_pitchofs_is_an_integer(fl_env):
    """The stubs give pitchofs as an int. Writing a float would be a silent change."""
    write(fl_env, [{"midi": 60, "time": 0.0, "duration": 1.0, "pitchofs": 7}])
    assert isinstance(fl_env.project.notes[0].pitchofs, int)


def test_repeats_is_an_integer(fl_env):
    write(fl_env, [{"midi": 60, "time": 0.0, "duration": 1.0, "repeats": 4}])
    assert isinstance(fl_env.project.notes[0].repeats, int)


def test_release_is_numeric_not_a_flag(fl_env):
    """The stubs give release as a float, so it is a value, not a switch."""
    write(fl_env, [{"midi": 60, "time": 0.0, "duration": 1.0, "release": 0.75}])
    assert fl_env.project.notes[0].release == pytest.approx(0.75)


def test_a_flag_is_coerced_to_a_bool(fl_env):
    """FL treats these as flags, so a truthy value must become True."""
    write(fl_env, [{"midi": 60, "time": 0.0, "duration": 1.0, "slide": 1}])
    assert fl_env.project.notes[0].slide is True


def test_an_unspecified_property_keeps_the_note_default(fl_env):
    """An untouched note must not be flattened to zero by the writer.

    The neutral values are measured, not assumed: FL normalises pan, fcut, fres and
    release to 0.5, so writing a zero for them would move a note away from where the
    user had it rather than leaving it alone.
    """
    write(fl_env, [{"midi": 60, "time": 0.0, "duration": 1.0}])
    note = fl_env.project.notes[0]
    assert note.slide is False
    assert note.pitchofs == 0
    assert note.velocity == pytest.approx(0.8), "the Note default, not zero"
    assert note.release == pytest.approx(0.5), "neutral, not zero"
    assert note.fcut == pytest.approx(0.5)
    assert note.fres == pytest.approx(0.5)
    assert note.pan == pytest.approx(0.5)


def test_a_bad_value_is_reported_rather_than_crashing_the_script(fl_env):
    write(fl_env, [{"midi": 60, "time": 0.0, "duration": 1.0, "pitchofs": "nope"}])
    response = json.loads(fl_env.piano_roll_response_file.read_text())
    assert response["success"] is False
    assert response["error"]


def test_the_expression_properties_reach_fl_from_a_chord_too(fl_env):
    """add_chord shares the note builder, so it must not have its own idea."""
    fl_env.request_file.write_text(json.dumps([{
        "action": "add_chord", "id": "c", "time": 0.0, "duration": 1.0,
        "notes": [{"midi": 60, "slide": True, "fcut": 0.7}],
    }]))
    fl_env.pyscript.apply()
    note = fl_env.project.notes[0]
    assert note.slide is True
    assert note.fcut == pytest.approx(0.7)


def test_a_pitch_offset_outside_the_documented_range_is_refused(fl_env):
    """The stub gives pitchofs a range of -120 to 120, in 10 cent units.

    FL clamps or truncates rather than complaining, so an out of range value would
    land as something the caller did not ask for and never hear about.
    """
    write(fl_env, [{"midi": 60, "time": 0.0, "duration": 1.0, "pitchofs": 500}])
    response = json.loads(fl_env.piano_roll_response_file.read_text())
    assert response["success"] is False
    assert "pitchofs" in response["error"]


def test_a_repeat_rate_outside_the_documented_range_is_refused(fl_env):
    """The stub gives repeats a range of 0 to 14, each naming a repeat rate."""
    write(fl_env, [{"midi": 60, "time": 0.0, "duration": 1.0, "repeats": 99}])
    response = json.loads(fl_env.piano_roll_response_file.read_text())
    assert response["success"] is False
    assert "repeats" in response["error"]


def test_the_edges_of_the_documented_ranges_are_accepted(fl_env):
    write(fl_env, [
        {"midi": 60, "time": 0.0, "duration": 1.0, "pitchofs": 120},
        {"midi": 62, "time": 1.0, "duration": 1.0, "pitchofs": -120},
        {"midi": 64, "time": 2.0, "duration": 1.0, "repeats": 14},
        {"midi": 65, "time": 3.0, "duration": 1.0, "repeats": 0},
    ])
    response = json.loads(fl_env.piano_roll_response_file.read_text())
    assert response["success"] is True
    assert response["notes_added"] == 4
