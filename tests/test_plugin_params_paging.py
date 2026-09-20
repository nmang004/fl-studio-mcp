"""Reading plugin parameters in pages, and skipping the unnamed ones.

A VST reports 4240 parameters, of which most are unused and come back with an empty
name. The old action read the first 50 and stopped, which made most of a plugin
invisible and said nothing about it.
"""

from __future__ import annotations

import pytest

from fl_studio_mcp.tools import plugins as plugin_tools
from fl_studio_mcp.utils.midi_connection import MIDIConnection


@pytest.fixture
def wired(fl_env, monkeypatch):
    conn = MIDIConnection()
    conn._command_file = fl_env.command_file
    conn._response_file = fl_env.response_file
    conn._port = fl_env.midi_port
    conn._connected = True
    monkeypatch.setattr(plugin_tools, "get_connection", lambda: conn, raising=False)
    fl_env.project.plugin_params[(0, -1)] = {index: index / 10.0 for index in range(8)}
    fl_env.project.plugin_names[(0, -1)] = "Serum"
    fl_env.connection = conn
    return fl_env


def ask(fl_env, **params) -> dict:
    payload = {"index": 0, "slot_index": -1, "use_global": True}
    payload.update(params)
    return fl_env.controller.dispatch_command("plugins.getParams", payload)


def test_a_page_reports_the_total_so_a_caller_knows_how_many_there_are(wired):
    result = ask(wired, max_params=3)
    assert result["total"] == 8
    assert len(result["params"]) == 3
    assert result["offset"] == 0


def test_the_next_page_starts_where_the_last_one_stopped(wired):
    first = ask(wired, max_params=3)
    second = ask(wired, max_params=3, offset=3)
    first_indexes = [param["index"] for param in first["params"]]
    second_indexes = [param["index"] for param in second["params"]]
    assert first_indexes == [0, 1, 2]
    assert second_indexes == [3, 4, 5]
    assert not set(first_indexes) & set(second_indexes), "a page repeated itself"


def test_an_offset_past_the_end_is_an_empty_page_not_an_error(wired):
    result = ask(wired, max_params=3, offset=99)
    assert result["params"] == []
    assert result["total"] == 8


def test_a_page_is_one_round_trip(wired):
    """Counted through the MIDI port, because dispatch_command is direct."""
    before = wired.trigger_count
    wired.connection.send_command(
        "plugins.getParams",
        {"index": 0, "slot_index": -1, "use_global": True, "max_params": 8},
        timeout=5.0,
    )
    assert wired.trigger_count - before == 1


def test_unnamed_parameters_can_be_skipped_and_are_counted(wired):
    """They are the parameters a VST reserves and does not use."""
    wired.project.plugin_unnamed = {1, 2, 3}
    result = ask(wired, max_params=8, skip_unnamed=True)
    assert [param["index"] for param in result["params"]] == [0, 4, 5, 6, 7]
    assert result["skipped_unnamed"] == 3


def test_unnamed_parameters_are_kept_when_asked_for(wired):
    wired.project.plugin_unnamed = {1}
    result = ask(wired, max_params=8, skip_unnamed=False)
    assert [param["index"] for param in result["params"]] == [0, 1, 2, 3, 4, 5, 6, 7]
    assert result["skipped_unnamed"] == 0


def test_skipping_happens_before_the_page_is_capped(wired):
    """A page of three means three usable parameters, not three examined ones."""
    wired.project.plugin_unnamed = {0, 1, 2, 3}
    result = ask(wired, max_params=2, skip_unnamed=True)
    assert [param["index"] for param in result["params"]] == [4, 5]


def test_the_tool_skips_unnamed_parameters_by_default(wired):
    wired.project.plugin_unnamed = {7}
    result = plugin_tools.get_plugin_params(0, max_params=50)
    assert [param["index"] for param in result["params"]] == [0, 1, 2, 3, 4, 5, 6]
    assert result["skipped_unnamed"] == 1
    assert result["total"] == 8


def test_the_tool_can_keep_the_unnamed_ones(wired):
    wired.project.plugin_unnamed = {7}
    result = plugin_tools.get_plugin_params(0, max_params=50, include_unnamed=True)
    assert len(result["params"]) == 8
    assert result["skipped_unnamed"] == 0


def test_the_tool_says_where_the_next_page_starts(wired):
    result = plugin_tools.get_plugin_params(0, max_params=3)
    assert result["next_offset"] == 3
    assert "offset=3" in result["message"]
    last = plugin_tools.get_plugin_params(0, max_params=50)
    assert "next_offset" not in last, "the last page must not offer another"
