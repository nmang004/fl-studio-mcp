"""MIDI import and export, so notes can leave FL and come back."""

from __future__ import annotations

import pytest

from fl_studio_mcp.musical import midi


def note(midi_number=60, time=0.0, duration=1.0, velocity=0.8):
    return {"midi": midi_number, "time": time, "duration": duration, "velocity": velocity}


def test_a_round_trip_keeps_pitch_and_time(tmp_path):
    notes = [note(60, 0.0, 1.0), note(64, 1.0, 0.5), note(67, 2.0, 2.0)]
    path = midi.to_midi_file(notes, tmp_path / "a.mid", ppq=96)
    read = midi.from_midi_file(path)
    assert [n["midi"] for n in read["notes"]] == [60, 64, 67]
    assert [n["time"] for n in read["notes"]] == pytest.approx([0.0, 1.0, 2.0])
    assert [n["duration"] for n in read["notes"]] == pytest.approx([1.0, 0.5, 2.0])


def test_a_round_trip_keeps_velocity(tmp_path):
    path = midi.to_midi_file([note(60, 0.0, 1.0, 0.9)], tmp_path / "v.mid")
    read = midi.from_midi_file(path)
    assert read["notes"][0]["velocity"] == pytest.approx(0.9, abs=0.01)


def test_the_file_declares_its_own_ppq(tmp_path):
    """Importing a 480 PPQ file into a 96 PPQ project must not stretch it."""
    path = midi.to_midi_file([note(60, 0.0, 1.0)], tmp_path / "p.mid", ppq=480)
    read = midi.from_midi_file(path)
    assert read["ppq"] == 480
    assert read["notes"][0]["duration"] == pytest.approx(1.0)


def test_the_tempo_and_meter_are_written(tmp_path):
    path = midi.to_midi_file(
        [note()], tmp_path / "t.mid", tempo=130.0, time_signature=(3, 4)
    )
    read = midi.from_midi_file(path)
    # MIDI stores tempo as microseconds per quarter note, an integer, so 130 BPM
    # comes back as 130.0001. The tolerance is for that, not for sloppiness.
    assert read["tempo"] == pytest.approx(130.0, abs=0.01)
    assert read["time_signature"] == (3, 4)


def test_a_chord_survives(tmp_path):
    notes = [note(pitch, 0.0, 1.0) for pitch in (60, 64, 67)]
    path = midi.to_midi_file(notes, tmp_path / "c.mid")
    read = midi.from_midi_file(path)
    assert sorted(n["midi"] for n in read["notes"]) == [60, 64, 67]
    assert all(n["time"] == 0.0 for n in read["notes"])


def test_adjacent_notes_do_not_cut_each_other_off(tmp_path):
    """A note ending where the next starts must keep its full length."""
    notes = [note(60, 0.0, 1.0), note(60, 1.0, 1.0)]
    path = midi.to_midi_file(notes, tmp_path / "adj.mid")
    read = midi.from_midi_file(path)
    assert [n["duration"] for n in read["notes"]] == pytest.approx([1.0, 1.0])


def test_a_very_quiet_note_does_not_vanish(tmp_path):
    """A velocity of zero is a note-off, so it is clamped rather than dropped."""
    path = midi.to_midi_file([note(60, 0.0, 1.0, 0.0)], tmp_path / "q.mid")
    read = midi.from_midi_file(path)
    assert len(read["notes"]) == 1
    assert read["notes"][0]["velocity"] > 0


def test_an_empty_note_list_writes_a_readable_file(tmp_path):
    path = midi.to_midi_file([], tmp_path / "e.mid")
    read = midi.from_midi_file(path)
    assert read["notes"] == []
    assert read["ppq"] == 96


def test_a_missing_file_raises_rather_than_returning_nothing(tmp_path):
    """An empty list would look like an empty pattern, which is a different problem."""
    with pytest.raises(ValueError, match="Could not read"):
        midi.from_midi_file(tmp_path / "nope.mid")


def test_a_file_that_is_not_midi_raises(tmp_path):
    junk = tmp_path / "junk.mid"
    junk.write_text("this is not a MIDI file")
    with pytest.raises(ValueError, match="Could not read"):
        midi.from_midi_file(junk)


def test_a_non_positive_ppq_is_refused(tmp_path):
    with pytest.raises(ValueError):
        midi.to_midi_file([note()], tmp_path / "x.mid", ppq=0)


def test_articulation_is_not_claimed_to_survive(tmp_path):
    """Slide has no standard MIDI form, so the export drops it and says so."""
    notes = [note(60, 0.0, 1.0)]
    notes[0]["slide"] = True
    path = midi.to_midi_file(notes, tmp_path / "s.mid")
    read = midi.from_midi_file(path)
    assert "slide" not in read["notes"][0]
    assert "slide" in midi.to_midi_file.__doc__
