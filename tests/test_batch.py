"""Many commands, one trigger, one undo step.

The motivation is atomicity and undo grouping, not speed: a round trip is about a
millisecond, so sixteen notes cost sixteen milliseconds and nobody cares. What is
a problem is that sixteen edits are sixteen Ctrl+Z presses, and that a failure
half way through leaves a project in a state nobody asked for.
"""

from __future__ import annotations

import pytest


def test_a_batch_executes_every_command_in_order(fl_env):
    result = fl_env.controller.dispatch_command("system.batch", {
        "commands": [
            {"action": "channels.setVolume", "params": {"index": 1, "volume": 0.1}},
            {"action": "channels.setVolume", "params": {"index": 2, "volume": 0.2}},
            {"action": "channels.setVolume", "params": {"index": 3, "volume": 0.3}},
        ],
        "name": "three volumes",
    })
    assert result["success"] is True
    assert result["executed"] == 3
    assert fl_env.project.channel(1).volume == pytest.approx(0.1)
    assert fl_env.project.channel(2).volume == pytest.approx(0.2)
    assert fl_env.project.channel(3).volume == pytest.approx(0.3)


def test_a_batch_reports_the_undo_history_it_left(fl_env):
    """The history size is reported, not a step count derived from it.

    The roadmap asked for a batch to be one undo step through general.saveUndo.
    Measured on FL Studio 2026 that does not work: a bare saveUndo adds no history
    entry and does not reduce how many undos an edit needs. The batch therefore
    does not claim grouping it cannot deliver, and reports what the history says.
    """
    fl_env.project.undo_entries_per_write = 2
    result = fl_env.controller.dispatch_command("system.batch", {
        "commands": [
            {"action": "channels.setVolume", "params": {"index": 1, "volume": 0.1}},
            {"action": "channels.setVolume", "params": {"index": 2, "volume": 0.2}},
        ],
        "name": "AI edit: two volumes",
    })
    assert result["undo_history_count"] == 4, "two writes of two entries each"
    assert "undo_entries" not in result


def test_a_batch_reports_the_undo_name(fl_env):
    result = fl_env.controller.dispatch_command("system.batch", {
        "commands": [
            {"action": "channels.setVolume", "params": {"index": 1, "volume": 0.1}},
        ],
        "name": "AI edit: one volume",
    })
    assert result["undo_name"] == "AI edit: one volume"


def test_a_batch_names_the_edit_itself_when_the_caller_does_not(fl_env):
    result = fl_env.controller.dispatch_command("system.batch", {
        "commands": [
            {"action": "channels.setVolume", "params": {"index": 1, "volume": 0.1}},
        ],
    })
    assert result["undo_name"] == "MCP edit"


def test_a_batch_stops_at_the_first_failure(fl_env):
    """Continuing past a failure would leave a half-applied edit."""
    result = fl_env.controller.dispatch_command("system.batch", {
        "commands": [
            {"action": "channels.setVolume", "params": {"index": 1, "volume": 0.1}},
            {"action": "channels.setVolume", "params": {"volume": 0.2}},  # no index
            {"action": "channels.setVolume", "params": {"index": 3, "volume": 0.3}},
        ],
        "name": "half bad",
    })
    assert result["success"] is False
    assert result["executed"] == 1
    assert result["failed"] == 1
    assert result["results"][1]["error"]
    assert result["results"][2].get("skipped") is True
    assert fl_env.project.channel(1).volume == pytest.approx(0.1)
    assert fl_env.project.channel(3).volume == pytest.approx(0.8), "a skipped command ran"


def test_a_batch_reports_every_result(fl_env):
    result = fl_env.controller.dispatch_command("system.batch", {
        "commands": [
            {"action": "mixer.getTrackCount", "params": {}},
            {"action": "channels.getCount", "params": {}},
        ],
        "name": "two reads",
    })
    assert [entry.get("count") for entry in result["results"]] == [8, 4]


def test_an_empty_batch_is_refused(fl_env):
    result = fl_env.controller.dispatch_command("system.batch", {"commands": []})
    assert "error" in result
    assert "commands" in result["error"]


def test_a_batch_without_a_commands_key_is_refused(fl_env):
    result = fl_env.controller.dispatch_command("system.batch", {})
    assert "error" in result


def test_a_command_without_an_action_is_refused(fl_env):
    result = fl_env.controller.dispatch_command("system.batch", {
        "commands": [{"params": {}}],
        "name": "bad entry",
    })
    assert "error" in result
    assert "action" in result["error"]


def test_a_batch_refuses_to_nest(fl_env):
    """A batch inside a batch would produce a second undo entry."""
    result = fl_env.controller.dispatch_command("system.batch", {
        "commands": [{"action": "system.batch", "params": {"commands": []}}],
        "name": "nested",
    })
    assert result["success"] is False
    assert "batch" in result["results"][0]["error"].lower()


def test_a_batch_refuses_an_unknown_action(fl_env):
    result = fl_env.controller.dispatch_command("system.batch", {
        "commands": [{"action": "bogus.doesNotExist", "params": {}}],
        "name": "unknown",
    })
    assert result["success"] is False
    assert result["results"][0]["error"]


def test_a_batch_through_the_round_trip_is_one_trigger(fl_env):
    """One trigger, not one per entry, which is what makes it atomic."""
    from fl_studio_mcp.utils.midi_connection import MIDIConnection

    conn = MIDIConnection()
    conn._command_file = fl_env.command_file
    conn._response_file = fl_env.response_file
    conn._port = fl_env.midi_port
    conn._connected = True

    result = conn.send_command("system.batch", {
        "commands": [
            {"action": "channels.setVolume", "params": {"index": 1, "volume": 0.1}},
            {"action": "channels.setVolume", "params": {"index": 2, "volume": 0.2}},
        ],
        "name": "two volumes",
    }, timeout=2.0)

    assert result["success"] is True
    assert fl_env.trigger_count == 1, "the batch triggered more than once"


def test_the_undo_actions_are_reachable(fl_env):
    assert fl_env.controller.dispatch_command(
        "general.getUndoHistoryCount", {}
    )["count"] == 0
    fl_env.controller.dispatch_command("general.saveUndo", {"name": "manual"})
    assert fl_env.controller.dispatch_command(
        "general.getUndoHistoryCount", {}
    )["count"] == 1
