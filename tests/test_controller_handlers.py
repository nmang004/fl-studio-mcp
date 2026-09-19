"""Handler behaviour, asserted against the in-memory project.

Each test names the wrong behaviour it would catch. A test that only asserts "no
exception" is not worth having, and a test that asserts on the fake's own
bookkeeping rather than on the project state would pass even if the handler did
nothing.
"""

from __future__ import annotations

import pytest


def test_get_all_channels_reports_every_channel(fl_env):
    result = fl_env.controller.handle_channels_get_all()
    assert [c["name"] for c in result["channels"]] == [
        "Channel 1",
        "Channel 2",
        "Channel 3",
        "Channel 4",
    ]


def test_get_channel_count(fl_env):
    assert fl_env.controller.handle_channels_get_count({})["count"] == 4


def test_get_channel_info_reports_the_properties_the_api_exposes(fl_env):
    fl_env.project.channel(1).volume = 0.25
    fl_env.project.channel(1).pan = -0.5
    fl_env.project.channel(1).muted = True
    info = fl_env.controller.handle_channels_get_info({"index": 1})
    assert info["name"] == "Channel 2"
    assert info["volume"] == pytest.approx(0.25)
    assert info["pan"] == pytest.approx(-0.5)
    assert info["is_muted"] is True


def test_set_channel_volume_writes_through_to_the_named_channel(fl_env):
    fl_env.controller.handle_channels_set_volume({"index": 2, "volume": 0.25})
    assert fl_env.project.channel(2).volume == pytest.approx(0.25)
    assert fl_env.project.channel(0).volume == pytest.approx(0.8), "channel 0 was touched"


def test_set_channel_volume_is_clamped_to_the_documented_range(fl_env):
    """FL clamps silently, so a value out of range is a caller bug worth seeing."""
    fl_env.controller.handle_channels_set_volume({"index": 1, "volume": 4.0})
    assert fl_env.project.channel(1).volume == pytest.approx(1.0)


def test_out_of_range_channel_index_raises_rather_than_editing_channel_zero(fl_env):
    """The upstream default was index 0, which silently edited the wrong channel."""
    with pytest.raises(IndexError):
        fl_env.controller.handle_channels_set_volume({"index": 99, "volume": 0.5})


def test_mute_without_a_value_toggles(fl_env):
    assert fl_env.controller.handle_channels_mute({"index": 0})["is_muted"] is True
    assert fl_env.controller.handle_channels_mute({"index": 0})["is_muted"] is False


def test_mute_with_an_explicit_value_sets_rather_than_toggles(fl_env):
    fl_env.controller.handle_channels_mute({"index": 0, "muted": True})
    assert fl_env.controller.handle_channels_mute({"index": 0, "muted": True})["is_muted"] is True


def test_select_one_channel_deselects_the_others(fl_env):
    fl_env.controller.handle_channels_select_one({"index": 2})
    assert fl_env.project.channel(2).selected is True
    assert fl_env.project.channel(0).selected is False


def test_step_sequence_round_trips(fl_env):
    pattern = [True, False] * 8
    fl_env.controller.handle_channels_set_step_sequence({"channel": 3, "pattern": pattern})
    result = fl_env.controller.handle_channels_get_step_sequence({"channel": 3, "steps": 16})
    assert result["sequence"] == pattern


def test_set_step_sequence_reports_how_many_steps_are_active(fl_env):
    result = fl_env.controller.handle_channels_set_step_sequence(
        {"channel": 1, "pattern": [True, True, False, True]}
    )
    assert result["active_steps"] == 3
    assert result["total_steps"] == 4


def test_step_sequences_do_not_leak_between_channels(fl_env):
    fl_env.controller.handle_channels_set_step_sequence({"channel": 0, "pattern": [True] * 4})
    other = fl_env.controller.handle_channels_get_step_sequence({"channel": 1, "steps": 4})
    assert other["sequence"] == [False, False, False, False]


def test_set_track_color_writes_rrggbb(fl_env):
    """The byte order was wrong upstream; 0xRRGGBB is what the API takes."""
    fl_env.controller.handle_mixer_set_track_color({"track": 2, "r": 0x11, "g": 0x22, "b": 0x33})
    assert fl_env.project.track(2).color == 0x112233


def test_set_channel_color_writes_rrggbb(fl_env):
    fl_env.controller.handle_channels_set_color({"index": 1, "r": 0xAA, "g": 0xBB, "b": 0xCC})
    assert fl_env.project.channel(1).color == 0xAABBCC


def test_get_all_tracks_skips_empty_inserts_but_keeps_the_master(fl_env):
    """The upstream behaviour, kept, because callers rely on the short list."""
    result = fl_env.controller.handle_mixer_get_all_tracks({})
    names = [t["name"] for t in result["tracks"]]
    assert names[0] == "Master"
    assert len(names) == 1, "the empty Insert tracks should be skipped by default"


def test_get_all_tracks_can_include_empty_tracks(fl_env):
    result = fl_env.controller.handle_mixer_get_all_tracks({"include_empty": True})
    assert len(result["tracks"]) == 8


def test_get_track_info_reports_volume_in_both_units(fl_env):
    fl_env.project.track(1).volume = 0.4
    result = fl_env.controller.handle_mixer_get_track_info({"track": 1})
    assert result["volume"] == pytest.approx(0.4)
    assert result["volume_db"] < 0, "0.4 is below FL's 0.8 default, so it is negative dB"


def test_mixer_track_count(fl_env):
    assert fl_env.controller.handle_mixer_get_track_count()["count"] == 8


def test_transport_status_reports_position_and_mode(fl_env):
    fl_env.project.is_playing = True
    result = fl_env.controller.handle_transport_get_status()
    assert result["is_playing"] is True
    assert result["loop_mode"] == "pattern"


def test_transport_start_reports_the_state_it_left_behind(fl_env):
    result = fl_env.controller.handle_transport_start()
    assert result["is_playing"] is True
    assert fl_env.project.is_playing is True


def test_transport_stop_actually_stops(fl_env):
    fl_env.project.is_playing = True
    fl_env.controller.handle_transport_stop()
    assert fl_env.project.is_playing is False


def test_trigger_note_plays_the_named_channel(fl_env):
    fl_env.controller.handle_channels_trigger_note(
        {"channel": 2, "note": 64, "velocity": 90}
    )
    assert fl_env.project.midi_notes == [(2, 64, 90, -1)]


def test_route_channel_to_mixer_sets_the_target_track(fl_env):
    result = fl_env.controller.handle_channels_route_to_mixer(
        {"channel_index": 1, "mixer_track": 5}
    )
    assert fl_env.project.channel(1).target_fx_track == 5
    assert result["mixer_track"] == 5


def test_plugin_param_write_reads_back(fl_env):
    """Nothing is loaded until a test loads it, so set one up first."""
    fl_env.project.plugin_params[(0, -1)] = {}
    fl_env.project.plugin_names[(0, -1)] = "Fake Synth"
    fl_env.controller.handle_plugins_set_param_value(
        {"param_index": 3, "value": 0.75, "plugin_index": 0}
    )
    assert fl_env.project.plugin_params[(0, -1)][3] == pytest.approx(0.75)


def test_plugin_is_valid_is_false_for_an_empty_slot(fl_env):
    assert fl_env.controller.handle_plugins_is_valid({"index": 0})["valid"] is False


def test_system_get_info_reports_the_fake_environment(fl_env):
    info = fl_env.controller.handle_system_get_info()
    assert info["api_version"] == 45
    assert info["fl_version"] == "Producer Edition v26.1.6 [build 5406]"
    assert info["capabilities"]["getCurrentTempo"] == 130000
