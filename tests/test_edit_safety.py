"""Refuse to mutate a project FL says is not safe to edit.

general.safeToEdit was added in API 29 and reports whether FL is in a state where
the project may be changed. Editing anyway can corrupt it, so the honest response
is to refuse.

An FL older than API 29 cannot answer the question at all. That is "unknown", and
refusing on unknown would break every install below API 29, so unknown proceeds.
"""

from __future__ import annotations

import pytest

MUTATING = [
    ("channels.setVolume", {"index": 1, "volume": 0.5}),
    ("channels.mute", {"index": 1, "muted": True}),
    ("channels.setGridBit", {"channel": 1, "position": 0, "value": True}),
    ("mixer.setTrackVolume", {"track": 1, "volume": 0.5}),
    ("mixer.setTrackName", {"track": 1, "name": "x"}),
    ("mixer.muteTrack", {"track": 1, "muted": True}),
    ("transport.start", {}),
    ("transport.stop", {}),
]

READ_ONLY = [
    ("channels.getInfo", {"index": 1}),
    ("mixer.getTrackInfo", {"track": 1}),
    ("mixer.getTrackCount", {}),
    ("transport.getStatus", {}),
    ("system.getInfo", {}),
    ("system.ping", {}),
    ("general.getUndoHistoryCount", {}),
]


@pytest.mark.parametrize("action,params", MUTATING)
def test_a_mutation_is_refused_when_fl_is_not_safe_to_edit(fl_env, action, params):
    fl_env.project.safe_to_edit = False
    result = fl_env.controller.dispatch_command(action, params)
    assert "error" in result, f"{action} edited a project FL said not to touch"
    assert "safe to edit" in result["error"].lower()


@pytest.mark.parametrize("action,params", READ_ONLY)
def test_reads_are_never_refused(fl_env, action, params):
    """Reading cannot corrupt anything, and diagnostics must work when stuck."""
    fl_env.project.safe_to_edit = False
    result = fl_env.controller.dispatch_command(action, params)
    assert "error" not in result, f"{action} was refused but only reads"


@pytest.mark.parametrize("action,params", MUTATING)
def test_a_mutation_proceeds_when_it_is_safe(fl_env, action, params):
    fl_env.project.safe_to_edit = True
    result = fl_env.controller.dispatch_command(action, params)
    assert "error" not in result, f"{action} was refused while safe to edit"


def test_an_unknown_answer_proceeds(fl_env):
    """API 29 is a floor, and below it the question cannot be asked.

    Deleting the function is exactly what an FL older than API 29 looks like from
    the controller's side.
    """
    del fl_env.modules["general"].safeToEdit
    result = fl_env.controller.dispatch_command(
        "channels.setVolume", {"index": 1, "volume": 0.5}
    )
    assert "error" not in result, "an older FL was refused for an unanswerable question"


def test_the_refusal_changes_nothing(fl_env):
    fl_env.project.safe_to_edit = False
    fl_env.controller.dispatch_command("channels.setVolume", {"index": 1, "volume": 0.1})
    assert fl_env.project.channel(1).volume == pytest.approx(0.8)


def test_the_refusal_through_the_round_trip_is_a_failure(fl_env):
    """The server must see the refusal as a failure, not as a success."""
    from fl_studio_mcp.utils.midi_connection import MIDIConnection

    fl_env.project.safe_to_edit = False
    conn = MIDIConnection()
    conn._command_file = fl_env.command_file
    conn._response_file = fl_env.response_file
    conn._port = fl_env.midi_port
    conn._connected = True

    result = conn.send_command("channels.setVolume", {"index": 1, "volume": 0.1}, timeout=2.0)

    assert result["success"] is False
    assert "safe to edit" in result["error"].lower()
    assert fl_env.project.channel(1).volume == pytest.approx(0.8)


def test_a_batch_is_refused_whole(fl_env):
    """A batch must not apply its first command and then hit the guard."""
    fl_env.project.safe_to_edit = False
    result = fl_env.controller.dispatch_command("system.batch", {
        "commands": [
            {"action": "channels.setVolume", "params": {"index": 1, "volume": 0.1}},
            {"action": "channels.setVolume", "params": {"index": 2, "volume": 0.2}},
        ],
        "name": "refused batch",
    })
    assert result["success"] is False
    assert result["executed"] == 0, "a command ran before the refusal"
    assert result["results"][0]["error"], "the refusal was not reported"
    assert "safe to edit" in result["results"][0]["error"].lower()
    assert result["results"][1].get("skipped") is True
    assert fl_env.project.channel(1).volume == pytest.approx(0.8)
    assert fl_env.project.channel(2).volume == pytest.approx(0.8)


def test_a_batch_of_reads_still_runs(fl_env):
    """The guard must not block a diagnostic batch while FL is busy."""
    fl_env.project.safe_to_edit = False
    result = fl_env.controller.dispatch_command("system.batch", {
        "commands": [{"action": "mixer.getTrackCount", "params": {}}],
        "name": "reads",
    })
    assert result["success"] is True
    assert result["results"][0]["count"] == 8
