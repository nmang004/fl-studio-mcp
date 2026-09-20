"""The snapshot tools, driving the real scripts against a fake FL."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from fl_studio_mcp.tools import snapshots as snapshot_tools
from fl_studio_mcp.utils import store


@pytest.fixture
def wired(fl_env, monkeypatch):
    """The snapshot tools wired to the in-process controller."""
    from fl_studio_mcp.utils.midi_connection import MIDIConnection

    conn = MIDIConnection()
    conn._command_file = fl_env.command_file
    conn._response_file = fl_env.response_file
    conn._port = fl_env.midi_port
    conn._connected = True
    monkeypatch.setattr(snapshot_tools, "get_connection", lambda: conn, raising=False)
    monkeypatch.setattr(snapshot_tools.batch, "get_connection", lambda: conn, raising=False)
    fl_env.connection = conn
    return fl_env


def take(wired, **kwargs) -> dict:
    return snapshot_tools.snapshot_project(**kwargs)


# --- capture ------------------------------------------------------------------


def test_a_snapshot_is_stored_and_reported(wired):
    result = take(wired, label="before the mix")
    assert result["success"] is True, result
    stored = store.read_record("snapshots", result["id"])
    assert stored["label"] == "before the mix"
    assert stored["schema"] == 1
    assert stored["created"]


def test_the_capture_is_a_fixed_number_of_round_trips(wired):
    """Two counts to build the batch, then the batch itself. Not one per track."""
    before = wired.trigger_count
    take(wired)
    assert wired.trigger_count - before == 3


def test_the_snapshot_holds_the_settings_that_can_be_restored(wired):
    wired.project.track(1).volume = 0.55
    wired.project.track(1).routes = {0: 0.8}
    result = take(wired)
    state = store.read_record("snapshots", result["id"])["state"]
    assert state["mixer"]["tracks"]["1"]["volume"] == pytest.approx(0.55)
    assert state["mixer"]["tracks"]["1"]["sends"] == [0]
    assert state["channels"]["0"]["name"]
    assert state["project"]["tempo"] == 130.0


def test_a_snapshot_says_what_it_cannot_contain(wired):
    result = take(wired)
    assert "notes" in result["note"].lower()
    assert "clip" in result["note"].lower()


def test_eq_bands_are_captured_by_default(wired):
    result = take(wired)
    state = store.read_record("snapshots", result["id"])["state"]
    bands = state["mixer"]["tracks"]["1"]["eq"]["bands"]
    assert bands, "EQ bands were not captured"
    assert "gain" in bands[0]


def test_eq_can_be_left_out(wired):
    before = wired.trigger_count
    take(wired, include_eq=False)
    state = store.read_record("snapshots", take(wired, include_eq=False)["id"])["state"]
    assert "eq" not in state["mixer"]["tracks"]["1"]
    # Two captures with EQ are 18 commands heavier than two without.
    assert wired.trigger_count - before == 6


def test_plugin_parameters_are_not_read_unless_asked(wired):
    """A single VST reports 4240 of them, so this must be opt in."""
    result = take(wired)
    state = store.read_record("snapshots", result["id"])["state"]
    assert "plugins" not in state
    assert "include_plugins" in result["plugins_note"]


def test_plugin_parameters_can_be_included(wired):
    """The fake keeps parameters per (channel, slot), and channel 0 holds a plugin."""
    wired.project.plugin_params[(0, -1)] = {0: 0.25, 1: 0.75}
    result = take(wired, include_plugins=True)
    state = store.read_record("snapshots", result["id"])["state"]
    assert state["plugins"]["channels.0"]["params"]["0"]["value"] == pytest.approx(0.25)


def test_an_unlabelled_snapshot_still_has_an_id_that_says_when(wired):
    result = take(wired)
    assert result["id"].startswith(datetime.now().strftime("%Y-%m-%d"))


# --- comparing ----------------------------------------------------------------


def test_changes_against_the_live_project_are_reported(wired):
    take(wired)
    wired.project.track(1).volume = 0.42
    result = snapshot_tools.project_changes()
    assert result["success"] is True, result
    assert result["changed"]["mixer.tracks.1.volume"]["after"] == pytest.approx(0.42)
    assert "1 setting(s) changed" in result["message"]


def test_nothing_changed_says_so(wired):
    take(wired)
    result = snapshot_tools.project_changes()
    assert result["summary"]["counts"]["total"] == 0
    assert "Nothing has changed" in result["message"]


def test_two_stored_snapshots_can_be_compared_without_touching_fl(wired):
    first = take(wired, label="one")
    wired.project.track(1).volume = 0.3
    second = take(wired, label="two")
    before = wired.trigger_count
    result = snapshot_tools.project_changes(since=first["id"], against=second["id"])
    assert wired.trigger_count == before, "comparing two files must not read FL"
    assert result["changed"]["mixer.tracks.1.volume"]["before"] == pytest.approx(0.8)
    assert result["changed"]["mixer.tracks.1.volume"]["after"] == pytest.approx(0.3)


def test_since_selects_a_snapshot_by_time(wired):
    """`since yesterday` is a time, not an id, and it should just work."""
    early = take(wired, label="morning")
    # Rewrite the stored timestamp so the snapshot is two hours old.
    record = store.read_record("snapshots", early["id"])
    record["created"] = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    store.write_record("snapshots", early["id"], record, overwrite=True)

    moment = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    result = snapshot_tools.project_changes(since=moment)
    assert result["success"] is True
    assert result["snapshot"] == early["id"]


def test_an_unknown_moment_is_explained(wired):
    take(wired)
    result = snapshot_tools.project_changes(since="2020-01-01T00:00:00")
    assert result["success"] is False
    assert "fl_snapshot_project" in result["error"]


def test_comparing_with_no_snapshots_names_the_tool_that_makes_one(fl_env):
    result = snapshot_tools.project_changes()
    assert result["success"] is False
    assert "fl_snapshot_project" in result["error"]


# --- restoring ----------------------------------------------------------------


def test_a_restore_reports_before_it_moves_anything(wired):
    take(wired)
    wired.project.track(1).volume = 0.2
    result = snapshot_tools.restore_snapshot()
    assert result["success"] is True
    assert result["applied"] is False
    assert result["moves"], "the move should be listed"
    assert wired.project.track(1).volume == pytest.approx(0.2), "nothing may have moved"
    assert "apply=True" in result["message"]


def test_a_restore_puts_the_value_back_in_one_batch(wired):
    take(wired)
    wired.project.track(1).volume = 0.2
    result = snapshot_tools.restore_snapshot(apply=True)
    assert result["applied"] is True, result
    assert wired.project.track(1).volume == pytest.approx(0.8)
    assert result["batch"]["undo_name"] == "MCP: restore snapshot"


def test_a_restore_with_nothing_to_do_sends_no_batch(wired):
    take(wired)
    before = wired.trigger_count
    result = snapshot_tools.restore_snapshot(apply=True)
    assert result["applied"] is False
    assert "already matches" in result["message"]
    assert wired.trigger_count == before + 3, "only the capture should have run"


def test_a_restore_never_touches_notes(wired):
    """A snapshot cannot see the piano roll, so a restore must not clear it."""
    take(wired)
    wired.project.track(1).volume = 0.2
    notes = [object()]
    wired.project.notes_by_pattern = {0: notes}
    snapshot_tools.restore_snapshot(apply=True)
    assert wired.project.notes_by_pattern[0] is notes, "the notes were touched"


def test_a_restore_names_the_settings_it_cannot_put_back(wired):
    take(wired)
    wired.project.playlist_tracks.append(("New Lane", 0x00FF00, False, False))
    result = snapshot_tools.restore_snapshot()
    assert result["unrestorable"], "a new playlist lane must be reported"
    assert any("appeared" in entry["reason"] for entry in result["unrestorable"])


def test_an_unknown_snapshot_id_is_explained(wired):
    result = snapshot_tools.restore_snapshot(snapshot="2026-01-01-000000-nope")
    assert result["success"] is False
    assert "fl_snapshot_project" in result["error"]
