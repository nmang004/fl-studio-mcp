"""The Phase 4 exit criterion: a slide-articulated bassline in the project's key."""

from __future__ import annotations

import pytest

from fl_studio_mcp.musical import bassline


def test_a_bassline_has_notes_in_the_rhythm():
    notes = bassline.bassline(36, pattern="x-x-", bars=1, beats_per_bar=4.0)
    assert [n["time"] for n in notes] == [0.0, 2.0]


def test_the_first_note_of_each_bar_is_the_root():
    notes = bassline.bassline(36, pattern="x-x-", bars=2, beats_per_bar=4.0)
    first_bar = [n for n in notes if n["time"] < 4.0]
    second_bar = [n for n in notes if n["time"] >= 4.0]
    assert first_bar[0]["midi"] == 36
    assert second_bar[0]["midi"] == 36


def test_a_bassline_moves_off_the_root():
    """A repeated root is a pulse, not a bassline."""
    notes = bassline.bassline(36, pattern="x-x-", bars=1, beats_per_bar=4.0)
    assert len({n["midi"] for n in notes}) > 1


def test_slide_is_the_default_articulation():
    notes = bassline.bassline(36, pattern="x-x-", bars=1, beats_per_bar=4.0)
    assert all(n.get("slide") is True for n in notes)


def test_portamento_can_be_asked_for_instead():
    notes = bassline.bassline(36, pattern="x-x-", articulation="porta")
    assert all(n.get("porta") is True for n in notes)
    assert all("slide" not in n for n in notes)


def test_articulation_can_be_turned_off():
    notes = bassline.bassline(36, pattern="x-x-", articulation="none")
    assert all("slide" not in n and "porta" not in n for n in notes)


def test_the_meter_decides_the_bar_length():
    """One bar of a 3/4 pattern covers three beats, and the second bar starts there."""
    three_four = bassline.bassline(36, pattern="xxx", bars=2, beats_per_bar=3.0)
    # Three hits per bar at one beat each: beats 0, 1, 2 then 3, 4, 5.
    assert [n["time"] for n in three_four] == pytest.approx([0, 1, 2, 3, 4, 5])
    second_bar = [n for n in three_four if n["time"] >= 3.0]
    assert second_bar[0]["midi"] == 36, "the second bar should start on the root"

    four_four = bassline.bassline(36, pattern="xxxx", bars=2, beats_per_bar=4.0)
    assert [n["time"] for n in four_four] == pytest.approx([0, 1, 2, 3, 4, 5, 6, 7])


def test_notes_ascend_from_the_root_using_the_scale():
    """The note offsets come from the scale, so the line stays in key."""
    scale = [0, 3, 5, 7, 10]  # minor pentatonic
    notes = bassline.bassline(36, pattern="x-x-", scale=scale, beats_per_bar=4.0)
    for note in notes:
        assert (note["midi"] - 36) in scale


def test_a_major_scale_keeps_the_line_in_that_scale():
    scale = [0, 2, 4, 5, 7, 9, 11]
    notes = bassline.bassline(36, pattern="x-x-", scale=scale, beats_per_bar=4.0)
    for note in notes:
        assert (note["midi"] - 36) in scale


def test_a_rhythm_with_no_hits_is_refused():
    with pytest.raises(ValueError, match="no notes"):
        bassline.bassline(36, pattern="----")


def test_an_empty_rhythm_is_refused():
    with pytest.raises(ValueError):
        bassline.bassline(36, pattern="")


def test_a_bar_count_below_one_is_refused():
    with pytest.raises(ValueError):
        bassline.bassline(36, bars=0)


def test_an_unknown_articulation_is_refused():
    with pytest.raises(ValueError, match="articulation"):
        bassline.bassline(36, articulation="wobble")


def test_the_pattern_repeats_to_fill_the_bars():
    one_bar = bassline.bassline(36, pattern="x-x-", bars=1, beats_per_bar=4.0)
    two_bars = bassline.bassline(36, pattern="x-x-", bars=2, beats_per_bar=4.0)
    assert len(two_bars) == len(one_bar) * 2


def test_a_chord_symbol_gives_the_root():
    """A bassline plays the root, not the chord."""
    notes = bassline.chord_bassline("Am7", pattern="x-", octave=2)
    assert notes[0]["midi"] == 45  # A in octave 2, where C is 36


def test_the_tool_writes_in_the_project_key(fl_env, monkeypatch):
    """The exit criterion: one call, the project's key, verified by read-back."""
    from fl_studio_mcp.tools import score as score_tool
    from fl_studio_mcp.utils.midi_connection import MIDIConnection

    conn = MIDIConnection()
    conn._command_file = fl_env.command_file
    conn._response_file = fl_env.response_file
    conn._port = fl_env.midi_port
    conn._connected = True

    monkeypatch.setattr(score_tool, "get_connection", lambda: conn, raising=False)
    monkeypatch.setattr(score_tool, "piano_roll_script", lambda: fl_env.pyscript)
    monkeypatch.setattr(
        score_tool.piano_roll, "piano_roll_scripts_dir", lambda: fl_env.piano_roll_dir
    )
    monkeypatch.setattr(
        score_tool.piano_roll,
        "trigger_fl_studio",
        lambda delay=0: (fl_env.pyscript.apply(), True)[1],
    )

    # A minor project, and the key has to come through rather than C major.
    fl_env.project.snap_root_note = 9
    fl_env.project.snap_scale_helper = "0,1,0,1,0,0,1,0,1,0,1,0"
    fl_env.project.tsnum = 4
    fl_env.project.tsden = 4
    fl_env.project.ppq = 96

    result = score_tool.write_bassline(channel=1, pattern="x-x-xx--", bars=1, octave=2)

    assert result["success"] is True, result.get("error")
    assert result["key"] == "A minor"
    assert result["time_signature"] == "4/4"
    assert result["notes_written"] > 0
    assert result["notes_read_back"] == result["notes_written"]
    assert result["group"], "the phrase should be grouped so it can be removed"

    # Every note is in A minor, which is the whole point.
    a_minor = {0, 2, 3, 5, 7, 8, 10}
    for note in fl_env.project.notes:
        assert (note.number - 45) % 12 in a_minor, f"{note.number} is out of key"
    # And articulated.
    assert all(note.slide for note in fl_env.project.notes)


def test_the_tool_honours_a_three_four_project(fl_env, monkeypatch):
    from fl_studio_mcp.tools import score as score_tool
    from fl_studio_mcp.utils.midi_connection import MIDIConnection

    conn = MIDIConnection()
    conn._command_file = fl_env.command_file
    conn._response_file = fl_env.response_file
    conn._port = fl_env.midi_port
    conn._connected = True

    monkeypatch.setattr(score_tool, "get_connection", lambda: conn, raising=False)
    monkeypatch.setattr(score_tool, "piano_roll_script", lambda: fl_env.pyscript)
    monkeypatch.setattr(
        score_tool.piano_roll, "piano_roll_scripts_dir", lambda: fl_env.piano_roll_dir
    )
    monkeypatch.setattr(
        score_tool.piano_roll,
        "trigger_fl_studio",
        lambda delay=0: (fl_env.pyscript.apply(), True)[1],
    )

    fl_env.project.tsnum = 3
    fl_env.project.tsden = 4

    result = score_tool.write_bassline(channel=1, pattern="xxx", bars=2)

    assert result["time_signature"] == "3/4"
    assert result["beats_per_bar"] == 3.0
    # Two 3/4 bars of three hits at one beat each ends on beat 5.
    assert max(n["time"] for n in result["notes"]) == pytest.approx(5.0)


def test_a_channel_that_does_not_exist_is_refused(fl_env, monkeypatch):
    from fl_studio_mcp.tools import score as score_tool
    from fl_studio_mcp.utils.midi_connection import MIDIConnection

    conn = MIDIConnection()
    conn._command_file = fl_env.command_file
    conn._response_file = fl_env.response_file
    conn._port = fl_env.midi_port
    conn._connected = True

    monkeypatch.setattr(score_tool, "get_connection", lambda: conn, raising=False)
    monkeypatch.setattr(score_tool, "piano_roll_script", lambda: fl_env.pyscript)
    monkeypatch.setattr(
        score_tool.piano_roll, "piano_roll_scripts_dir", lambda: fl_env.piano_roll_dir
    )

    result = score_tool.write_bassline(channel=99)
    assert result["success"] is False
    assert "99" in result["error"]
    assert fl_env.project.notes == [], "a note was written anyway"
