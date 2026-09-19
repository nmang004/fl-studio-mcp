"""The fakes have to cover what Phase 3 calls, or the tests prove nothing.

Each of these asserts on the project model rather than on the fake's own
bookkeeping, so a fake that records a call without changing state fails here.
"""

from __future__ import annotations


def test_patterns_carry_name_colour_and_length(fl_env):
    patterns = fl_env.modules["patterns"]
    assert patterns.patternCount() == 1
    patterns.setPatternName(0, "Verse")
    assert patterns.getPatternName(0) == "Verse"
    patterns.setPatternColor(0, 0x123456)
    assert patterns.getPatternColor(0) == 0x123456
    assert patterns.getPatternLength(0) > 0


def test_cloning_a_pattern_adds_one_and_names_it(fl_env):
    patterns = fl_env.modules["patterns"]
    patterns.setPatternName(0, "Verse")
    new_index = patterns.clonePattern(0)
    assert patterns.patternCount() == 2
    assert new_index == 1
    assert "Verse" in patterns.getPatternName(1)


def test_cloning_copies_the_length_too(fl_env):
    patterns = fl_env.modules["patterns"]
    fl_env.project.pattern(0).length = 32
    patterns.clonePattern(0)
    assert patterns.getPatternLength(1) == 32


def test_selecting_a_pattern_moves_the_current_one(fl_env):
    patterns = fl_env.modules["patterns"]
    patterns.clonePattern(0)
    patterns.selectPattern(1)
    assert patterns.patternNumber() == 2, "patternNumber is 1-based on live FL"
    assert patterns.isPatternSelected(2) is True, "isPatternSelected is 1-based too"
    assert patterns.isPatternSelected(1) is False


def test_find_first_next_empty_pattern_skips_a_used_one(fl_env):
    """Pattern 0 holds notes, so the next empty slot is 1."""
    patterns = fl_env.modules["patterns"]
    fl_env.project.notes_by_pattern = {0: [object()]}
    patterns.clonePattern(0)
    assert patterns.findFirstNextEmptyPat(0) == 1


def test_playlist_tracks_report_their_properties(fl_env):
    playlist = fl_env.modules["playlist"]
    playlist.setTrackName(1, "Drums")
    playlist.setTrackColor(1, 0x00FF00)
    playlist.muteTrack(1, 1)
    playlist.soloTrack(2, 1)
    assert playlist.getTrackName(1) == "Drums"
    assert playlist.getTrackColor(1) == 0x00FF00
    assert playlist.isTrackMuted(1) is True
    assert playlist.isTrackSolo(2) is True


def test_playlist_and_mixer_tracks_are_separate(fl_env):
    """FL keeps them apart, and a generic DAW tool conflates them."""
    fl_env.modules["playlist"].setTrackName(1, "Playlist Name")
    assert fl_env.modules["mixer"].getTrackName(1) == "Insert 1"


def test_markers_are_recorded_and_named(fl_env):
    arrangement = fl_env.modules["arrangement"]
    arrangement.addAutoTimeMarker(384, "Drop")
    arrangement.addAutoTimeMarker(768, "Break")
    assert arrangement.getMarkerName(0) == "Drop"
    assert arrangement.getMarkerName(1) == "Break"
    assert arrangement.selectionStart() == 0


def test_current_time_is_readable_and_settable(fl_env):
    arrangement = fl_env.modules["arrangement"]
    fl_env.project.arrangement_time = 480
    assert arrangement.currentTime(0) == 480


def test_ui_reports_visibility_and_focus(fl_env):
    ui = fl_env.modules["ui"]
    ui.showWindow(3)
    assert ui.getVisible(3) is True
    ui.hideWindow(3)
    assert ui.getVisible(3) is False
    ui.setFocused(3)
    assert ui.getFocused(3) is True


def test_ui_reports_the_snap_mode_round_trip(fl_env):
    ui = fl_env.modules["ui"]
    ui.setSnapMode(2)
    assert ui.getSnapMode() == 2


def test_the_fakes_still_refuse_a_playlist_clip_function(fl_env):
    """This phase adds playlist tools, so the absence must stay pinned."""
    playlist = fl_env.modules["playlist"]
    for forbidden in ("add", "insert", "create", "addClip", "insertClip", "placeClip"):
        assert not hasattr(playlist, forbidden), f"the fake gained {forbidden}()"
