"""Targeting is a controller job, because only the controller can see channels.

The piano roll script has one FL module, flpianoroll, and that module exposes no
channel identity at all: no name, no index, nothing. So the side that knows which
channel was asked for has to be the side that arranges for its piano roll to be
open.
"""

from __future__ import annotations


def test_targeting_selects_the_channel_and_shows_its_piano_roll(fl_env):
    result = fl_env.controller.dispatch_command("channels.selectPianoRoll", {"index": 2})
    assert result["targeted"] == 2
    assert result["channel_name"] == "Channel 3"
    assert result["piano_roll_visible"] is True
    assert fl_env.project.selected_channel == 2


def test_targeting_deselects_the_others(fl_env):
    """A half-selected rack would leave the piano roll ambiguous."""
    fl_env.project.selected_channel = 0
    fl_env.controller.dispatch_command("channels.selectPianoRoll", {"index": 3})
    assert fl_env.project.channel(3).selected is True
    assert fl_env.project.channel(0).selected is False


def test_targeting_reports_the_window_it_showed(fl_env):
    fl_env.controller.dispatch_command("channels.selectPianoRoll", {"index": 1})
    assert fl_env.project.ui_state.get("visible_3") is True, "widPianoRoll is 3"


def test_targeting_refuses_a_missing_index(fl_env):
    result = fl_env.controller.dispatch_command("channels.selectPianoRoll", {})
    assert "error" in result
    assert "index" in result["error"]


def test_targeting_refuses_an_index_that_does_not_exist(fl_env):
    """Better to refuse than to let FL decide what index 99 means."""
    result = fl_env.controller.dispatch_command("channels.selectPianoRoll", {"index": 99})
    assert "error" in result
    assert "99" in result["error"]


def test_targeting_is_refused_when_fl_is_not_safe_to_edit(fl_env):
    """Opening a window and moving the selection is not a read."""
    fl_env.project.safe_to_edit = False
    result = fl_env.controller.dispatch_command("channels.selectPianoRoll", {"index": 1})
    assert "error" in result
    assert "safe to edit" in result["error"].lower()


def test_targeting_reports_the_selection_it_achieved(fl_env):
    """Read back rather than assumed, which is the point of the whole exercise."""
    result = fl_env.controller.dispatch_command("channels.selectPianoRoll", {"index": 2})
    assert result["selected"] == 2


def test_get_selected_channel_reports_the_selection(fl_env):
    fl_env.controller.dispatch_command("channels.selectPianoRoll", {"index": 2})
    result = fl_env.controller.dispatch_command("channels.getSelectedChannel", {})
    assert result["index"] == 2
    assert result["channel_name"] == "Channel 3"


def test_get_selected_channel_reports_nothing_selected(fl_env):
    fl_env.project.selected_channel = None
    result = fl_env.controller.dispatch_command("channels.getSelectedChannel", {})
    assert result["index"] is None
    assert result["channel_name"] is None


def test_get_selected_channel_is_never_refused(fl_env):
    """A caller has to be able to ask where it is before it can decide to move."""
    fl_env.project.safe_to_edit = False
    result = fl_env.controller.dispatch_command("channels.getSelectedChannel", {})
    assert "error" not in result
