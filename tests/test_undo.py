"""fl_batch, fl_undo and fl_undo_history, through the round trip.

These go through the tools module rather than the controller, so the argument
handling and the reporting the model actually sees are both covered.
"""

from __future__ import annotations

import pytest

from fl_studio_mcp.tools import batch


@pytest.fixture
def wired(fl_env, monkeypatch):
    """The batch tools wired to the in-process controller."""
    from fl_studio_mcp.utils.midi_connection import MIDIConnection

    conn = MIDIConnection()
    conn._command_file = fl_env.command_file
    conn._response_file = fl_env.response_file
    conn._port = fl_env.midi_port
    conn._connected = True
    monkeypatch.setattr(batch, "get_connection", lambda: conn)
    return fl_env


def test_batch_runs_commands_and_reports_success(wired):
    result = batch.run_batch(
        [
            {"action": "channels.setVolume", "params": {"index": 1, "volume": 0.1}},
            {"action": "channels.setVolume", "params": {"index": 2, "volume": 0.2}},
        ],
        name="two volumes",
    )
    assert result["success"] is True
    assert result["executed"] == 2
    assert wired.project.channel(1).volume == pytest.approx(0.1)


def test_batch_needs_commands(wired):
    result = batch.run_batch([], name="nothing")
    assert result["success"] is False
    assert "command" in result["error"].lower()


def test_batch_requires_a_name(wired):
    """The name is what the user reads in FL Studio's undo history."""
    result = batch.run_batch([{"action": "mixer.getTrackCount", "params": {}}], name="")
    assert result["success"] is False
    assert "name" in result["error"].lower()


def test_batch_requires_a_name_that_is_not_whitespace(wired):
    result = batch.run_batch([{"action": "mixer.getTrackCount", "params": {}}], name="   ")
    assert result["success"] is False


def test_batch_rejects_a_command_without_an_action(wired):
    result = batch.run_batch([{"params": {}}], name="no action")
    assert result["success"] is False
    assert "action" in result["error"]


def test_batch_reports_where_it_stopped(wired):
    result = batch.run_batch(
        [
            {"action": "channels.setVolume", "params": {"index": 1, "volume": 0.1}},
            {"action": "channels.setVolume", "params": {"volume": 0.2}},
        ],
        name="half bad",
    )
    assert result["success"] is False
    assert result["executed"] == 1
    assert result["results"][1]["error"]
    assert result["results"][1]["error"].startswith("channels.setVolume requires")


def test_batch_is_one_trigger(wired):
    batch.run_batch(
        [
            {"action": "channels.setVolume", "params": {"index": 1, "volume": 0.1}},
            {"action": "channels.setVolume", "params": {"index": 2, "volume": 0.2}},
        ],
        name="two volumes",
    )
    assert wired.trigger_count == 1


def test_a_batch_still_runs_when_the_undo_history_is_unreadable(wired, monkeypatch):
    """An FL whose undo API is missing must still run the batch."""

    def unavailable(*args, **kwargs):
        raise RuntimeError("no undo API")

    monkeypatch.setattr(wired.modules["general"], "getUndoHistoryCount", unavailable)
    result = batch.run_batch(
        [{"action": "mixer.getTrackCount", "params": {}}], name="no undo api"
    )
    assert result["success"] is True
    assert result["undo_history_count"] is None


def test_undo_reports_the_remaining_depth(wired):
    wired.project.undo_stack = ["a", "b", "c"]
    result = batch.run_undo()
    assert result["success"] is True
    assert result["count"] == 2
    assert result["message"] == "Undid 1 step(s)."


def test_undo_uses_the_relative_move_not_the_toggle(wired, monkeypatch):
    """general.undo is a toggle, so two calls undo once and then redo.

    The stub documents that, and live FL Studio 2026 behaves that way. Moving
    relatively is the only way a caller can ask for two steps and get two.
    """
    sent = []
    original = wired.controller.dispatch_command

    def record(action, params):
        sent.append(action)
        return original(action, params)

    monkeypatch.setattr(wired.controller, "dispatch_command", record)
    wired.project.undo_stack = ["a", "b", "c", "d"]

    result = batch.run_undo(steps=2)

    assert sent == ["general.undoUpDown"], f"used {sent}"
    assert result["success"] is True
    assert len(wired.project.undo_stack) == 2, "two steps were not undone"


def test_undo_history_reports_the_depth(wired):
    wired.project.undo_stack = ["a", "b"]
    result = batch.run_undo_history()
    assert result["success"] is True
    assert result["count"] == 2


def test_undo_can_move_several_steps(wired):
    """FL files some edits as several entries, so one call must reverse them all."""
    wired.project.undo_stack = ["a", "b", "c", "d"]
    result = batch.run_undo(steps=3)
    assert result["success"] is True
    assert result["message"] == "Undid 3 step(s)."
    assert len(wired.project.undo_stack) == 1


def test_undo_rejects_a_zero_step_count(wired):
    result = batch.run_undo(steps=0)
    assert result["success"] is False
    assert "at least 1" in result["error"]


def test_batch_reports_the_observed_undo_history_size(wired):
    """The history size is read, not derived.

    FL's undo accounting does not predict how many undo calls an edit needs, so
    the batch reports what the history actually says and leaves the interpretation
    to the caller rather than inventing a step figure.
    """
    wired.project.undo_entries_per_write = 3
    result = batch.run_batch(
        [
            {"action": "mixer.setTrackVolume", "params": {"track": 1, "volume": 0.1}},
            {"action": "mixer.setTrackPan", "params": {"track": 1, "pan": 0.5}},
        ],
        name="mixer edit",
    )
    assert result["undo_history_count"] == 6, "two writes of three entries each"
    assert "undo_entries" not in result, "a derived step count was reported as fact"


def test_batch_does_not_claim_to_group_undo(wired):
    """FL has no grouping, so nothing in the reply may imply there is."""
    result = batch.run_batch(
        [{"action": "channels.setVolume", "params": {"index": 1, "volume": 0.1}}],
        name="channel edit",
    )
    assert "warning" not in result
    assert result["undo_name"] == "channel edit"


def test_batch_does_not_call_save_undo(wired, monkeypatch):
    """It was measured to change nothing, so calling it would imply otherwise."""
    called = []
    monkeypatch.setattr(
        wired.modules["general"], "saveUndo", lambda *a, **k: called.append(a)
    )
    batch.run_batch(
        [{"action": "channels.setVolume", "params": {"index": 1, "volume": 0.1}}],
        name="channel edit",
    )
    assert called == [], "the batch called saveUndo, which does nothing on FL"
