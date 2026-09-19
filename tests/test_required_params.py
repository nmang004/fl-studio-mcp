"""A missing target must be an error, not a guess.

Every handler that takes an index defaulted to 0, and index 0 is the Master mixer
track or the first channel. A caller that forgot the parameter got a confident
report about the wrong object, and for a write that means editing the master track
of someone's project.
"""

from __future__ import annotations

import pytest

# action, params that omit the target, the field the caller forgot
REQUIRED = [
    ("mixer.getTrackInfo", {}, "track"),
    ("mixer.setTrackVolume", {"volume": 0.5}, "track"),
    ("mixer.setTrackPan", {"pan": 0.0}, "track"),
    ("mixer.setTrackName", {"name": "x"}, "track"),
    ("mixer.setTrackColor", {"r": 1, "g": 2, "b": 3}, "track"),
    ("mixer.muteTrack", {"muted": True}, "track"),
    ("mixer.soloTrack", {"solo": True}, "track"),
    ("mixer.setStereoSep", {"separation": 0.0}, "track"),
    ("channels.getInfo", {}, "index"),
    ("channels.setVolume", {"volume": 0.5}, "index"),
    ("channels.setPan", {"pan": 0.0}, "index"),
    ("channels.setName", {"name": "x"}, "index"),
    ("channels.setColor", {"r": 1, "g": 2, "b": 3}, "index"),
    ("channels.mute", {"muted": True}, "index"),
    ("channels.solo", {"solo": True}, "index"),
    ("channels.select", {"select": True}, "index"),
    ("channels.selectOne", {}, "index"),
    ("channels.routeToMixer", {"mixer_track": 1}, "channel_index"),
    ("channels.getGridBit", {"position": 0}, "channel"),
    ("channels.setGridBit", {"position": 0, "value": True}, "channel"),
    ("channels.getStepSequence", {}, "channel"),
    ("channels.setStepSequence", {"pattern": [True]}, "channel"),
    ("plugins.getParamValue", {"param_index": 0}, "plugin_index"),
    ("plugins.setParamValue", {"param_index": 0, "value": 0.5}, "plugin_index"),
]


@pytest.mark.parametrize("action,params,field", REQUIRED)
def test_a_missing_target_is_refused(fl_env, action, params, field):
    result = fl_env.controller.dispatch_command(action, params)
    assert "error" in result, f"{action} accepted params with no {field}"
    assert field in result["error"], f"{action} did not name the missing {field}"


@pytest.mark.parametrize("action,params,field", REQUIRED)
def test_a_supplied_target_is_accepted(fl_env, action, params, field):
    """The guard must not reject a caller that did supply the target."""
    supplied = dict(params)
    supplied[field] = 1
    result = fl_env.controller.dispatch_command(action, supplied)
    assert "requires" not in str(result.get("error", "")), (
        f"{action} refused a call that supplied {field}: {result.get('error')}"
    )


def test_an_index_of_zero_is_still_accepted(fl_env):
    """Zero is a real index. Only its absence is an error."""
    result = fl_env.controller.dispatch_command("mixer.getTrackInfo", {"track": 0})
    assert "error" not in result


def test_the_error_names_the_action_and_the_field(fl_env):
    result = fl_env.controller.dispatch_command("mixer.setTrackVolume", {"volume": 0.5})
    assert result["error"] == "mixer.setTrackVolume requires a 'track'"


def test_a_missing_target_through_the_round_trip_is_a_failure(fl_env):
    """The server must turn the controller's error into a reported failure."""
    from fl_studio_mcp.utils.midi_connection import MIDIConnection

    conn = MIDIConnection()
    conn._command_file = fl_env.command_file
    conn._response_file = fl_env.response_file
    conn._port = fl_env.midi_port
    conn._connected = True

    result = conn.send_command("mixer.setTrackVolume", {"volume": 0.5}, timeout=2.0)

    assert result["success"] is False
    assert "track" in result["error"]
    assert fl_env.project.track(0).volume == pytest.approx(0.8), "the master was edited"
