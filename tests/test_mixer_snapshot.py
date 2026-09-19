"""A review needs every track's settings, so it must not be one call per track.

Phase 4 deleted twenty round trips from the project description for exactly this
reason, and a mix review with one call per track would put them back.
"""

from __future__ import annotations

import pytest


def snapshot(fl_env, **params):
    return fl_env.controller.dispatch_command("mixer.getSnapshot", params)


def entry(fl_env, index, **params):
    return next(t for t in snapshot(fl_env, **params)["tracks"] if t["index"] == index)


def test_the_snapshot_reports_every_track(fl_env):
    result = snapshot(fl_env)
    assert result["track_count"] == 8
    assert len(result["tracks"]) == 8


def test_the_snapshot_reports_volume_pan_and_state(fl_env):
    fl_env.project.track(1).volume = 0.5
    fl_env.project.track(1).pan = -0.3
    fl_env.project.track(1).muted = True
    fl_env.project.track(1).armed = True
    found = entry(fl_env, 1)
    assert found["volume"] == pytest.approx(0.5)
    assert found["pan"] == pytest.approx(-0.3)
    assert found["is_muted"] is True
    assert found["is_armed"] is True


def test_the_snapshot_reports_loudness_units(fl_env):
    """A fader value means nothing without knowing how hot the signal is."""
    result = snapshot(fl_env)
    assert all("volume_db" in track for track in result["tracks"])
    assert all("stereo_separation" in track for track in result["tracks"])


def test_the_snapshot_reports_where_a_track_sends(fl_env):
    fl_env.project.track(1).routes = {0: 0.8}
    assert entry(fl_env, 1)["sends"] == [0]


def test_the_snapshot_reports_a_track_with_no_sends(fl_env):
    assert entry(fl_env, 1)["sends"] == []


def test_the_snapshot_names_every_track(fl_env):
    assert snapshot(fl_env)["tracks"][0]["name"] == "Master"


def test_the_snapshot_reports_the_colour(fl_env):
    fl_env.project.track(2).color = 0x112233
    assert entry(fl_env, 2)["color"] == 0x112233


def test_the_snapshot_is_one_command(fl_env):
    """The whole point. More than one and a review pays a round trip per track."""
    from fl_studio_mcp.utils.midi_connection import MIDIConnection

    conn = MIDIConnection()
    conn._command_file = fl_env.command_file
    conn._response_file = fl_env.response_file
    conn._port = fl_env.midi_port
    conn._connected = True
    before = fl_env.trigger_count
    result = conn.send_command("mixer.getSnapshot", {}, timeout=2.0)
    assert result["success"] is True
    assert fl_env.trigger_count == before + 1


def test_the_snapshot_is_a_read(fl_env):
    """A review must not be able to change anything."""
    fl_env.project.safe_to_edit = False
    assert "error" not in snapshot(fl_env)
