"""Channel properties, playlist tracks, arrangement markers and UI state.

The playlist and the Channel Rack are different things in FL. A playlist track is
a lane in the arrangement; a Channel Rack channel is an instrument or a sample. A
generic DAW tool conflates them, and a test here pins that they stay separate.
"""

from __future__ import annotations


def test_channel_properties_report_type_pitch_and_routing(fl_env):
    fl_env.project.channel(1).pitch = 0
    fl_env.project.channel(1).target_fx_track = 3
    result = fl_env.controller.dispatch_command("channels.getProperties", {"index": 1})
    assert result["index"] == 1
    assert result["name"] == "Channel 2"
    assert "channel_type" in result
    assert result["pitch"] == 0
    assert result["target_fx_track"] == 3


def test_channel_properties_report_mute_solo_and_selection(fl_env):
    fl_env.project.channel(2).muted = True
    fl_env.project.channel(2).solo = True
    result = fl_env.controller.dispatch_command("channels.getProperties", {"index": 2})
    assert result["is_muted"] is True
    assert result["is_solo"] is True
    assert "is_selected" in result


def test_setting_channel_pitch_writes_it(fl_env):
    fl_env.controller.dispatch_command(
        "channels.setProperties", {"index": 1, "pitch": 5}
    )
    assert fl_env.project.channel(1).pitch == 5


def test_setting_channel_pitch_reads_it_back(fl_env):
    result = fl_env.controller.dispatch_command(
        "channels.setProperties", {"index": 1, "pitch": -3}
    )
    assert result["pitch"] == -3


def test_channel_pitch_is_clamped(fl_env):
    fl_env.controller.dispatch_command(
        "channels.setProperties", {"index": 1, "pitch": 100000}
    )
    assert fl_env.project.channel(1).pitch <= 120


def test_quantize_is_reported(fl_env):
    result = fl_env.controller.dispatch_command(
        "channels.setProperties", {"index": 1, "quantize": True}
    )
    assert result["quantized"] is True


def test_set_properties_needs_an_index(fl_env):
    result = fl_env.controller.dispatch_command("channels.setProperties", {"pitch": 1})
    assert "error" in result
    assert "index" in result["error"]


def test_set_properties_needs_something_to_set(fl_env):
    result = fl_env.controller.dispatch_command("channels.setProperties", {"index": 1})
    assert "error" in result


def test_channel_properties_are_refused_when_not_safe_to_edit(fl_env):
    fl_env.project.safe_to_edit = False
    result = fl_env.controller.dispatch_command(
        "channels.setProperties", {"index": 1, "pitch": 2}
    )
    assert "error" in result
    assert "safe to edit" in result["error"].lower()


def test_playlist_tracks_report_their_properties(fl_env):
    fl_env.modules["playlist"].setTrackName(1, "Drums")
    result = fl_env.controller.dispatch_command("playlist.getAll", {})
    assert result["tracks"][1]["name"] == "Drums"
    assert "color" in result["tracks"][1]


def test_playlist_and_mixer_tracks_stay_separate(fl_env):
    """Renaming a playlist track must not rename the mixer track of that index."""
    fl_env.controller.dispatch_command(
        "playlist.setTrack", {"index": 1, "name": "Arrangement Lane"}
    )
    assert fl_env.modules["playlist"].getTrackName(1) == "Arrangement Lane"
    assert fl_env.modules["mixer"].getTrackName(1) == "Insert 1"


def test_setting_playlist_mute_and_solo(fl_env):
    fl_env.controller.dispatch_command("playlist.setTrack", {"index": 1, "muted": True})
    fl_env.controller.dispatch_command("playlist.setTrack", {"index": 2, "solo": True})
    assert fl_env.modules["playlist"].isTrackMuted(1) is True
    assert fl_env.modules["playlist"].isTrackSolo(2) is True


def test_playlist_set_needs_a_track(fl_env):
    result = fl_env.controller.dispatch_command("playlist.setTrack", {"name": "x"})
    assert "error" in result
    assert "index" in result["error"]


def test_playlist_writes_are_refused_when_not_safe_to_edit(fl_env):
    fl_env.project.safe_to_edit = False
    result = fl_env.controller.dispatch_command(
        "playlist.setTrack", {"index": 1, "name": "x"}
    )
    assert "error" in result
    assert "safe to edit" in result["error"].lower()


def test_markers_are_added_and_read_back(fl_env):
    fl_env.controller.dispatch_command(
        "arrangement.addMarker", {"time": 384, "name": "Drop"}
    )
    result = fl_env.controller.dispatch_command("arrangement.getMarkers", {})
    assert result["markers"] == [{"index": 0, "name": "Drop", "time": None}], (
        "the name comes back, and the time cannot: there is no API to read it"
    )


def test_markers_report_an_empty_project_honestly(fl_env):
    result = fl_env.controller.dispatch_command("arrangement.getMarkers", {})
    assert result["markers"] == []


def test_add_marker_needs_a_name(fl_env):
    result = fl_env.controller.dispatch_command("arrangement.addMarker", {"time": 0})
    assert "error" in result
    assert "name" in result["error"]


def test_add_marker_needs_a_time(fl_env):
    result = fl_env.controller.dispatch_command("arrangement.addMarker", {"name": "x"})
    assert "error" in result
    assert "time" in result["error"]


def test_marker_writes_are_refused_when_not_safe_to_edit(fl_env):
    fl_env.project.safe_to_edit = False
    result = fl_env.controller.dispatch_command(
        "arrangement.addMarker", {"time": 0, "name": "x"}
    )
    assert "error" in result
    assert "safe to edit" in result["error"].lower()


def test_ui_state_reports_visibility_and_focus(fl_env):
    fl_env.modules["ui"].showWindow(3)
    fl_env.modules["ui"].setFocused(3)
    result = fl_env.controller.dispatch_command("ui.getState", {})
    assert result["piano_roll_visible"] is True
    assert result["focused"] == 3
    assert "snap_mode" in result


def test_show_window_and_hide_window(fl_env):
    fl_env.controller.dispatch_command("ui.showWindow", {"index": 1})
    assert fl_env.modules["ui"].getVisible(1) is True
    fl_env.controller.dispatch_command("ui.hideWindow", {"index": 1})
    assert fl_env.modules["ui"].getVisible(1) is False


def test_show_window_needs_an_index(fl_env):
    result = fl_env.controller.dispatch_command("ui.showWindow", {})
    assert "error" in result
    assert "index" in result["error"]


def test_ui_get_state_is_never_refused(fl_env):
    fl_env.project.safe_to_edit = False
    assert "error" not in fl_env.controller.dispatch_command("ui.getState", {})
