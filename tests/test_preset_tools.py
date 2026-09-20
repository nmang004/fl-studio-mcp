"""Saving, finding, recalling and blending presets against the fake FL."""

from __future__ import annotations

import pytest

from fl_studio_mcp.musical import presets as preset_math
from fl_studio_mcp.tools import presets as preset_tools
from fl_studio_mcp.utils import store


@pytest.fixture
def wired(fl_env, monkeypatch):
    """A plugin on channel 0 with eight named parameters."""
    from fl_studio_mcp.utils.midi_connection import MIDIConnection

    conn = MIDIConnection()
    conn._command_file = fl_env.command_file
    conn._response_file = fl_env.response_file
    conn._port = fl_env.midi_port
    conn._connected = True
    monkeypatch.setattr(preset_tools, "get_connection", lambda: conn, raising=False)
    monkeypatch.setattr(preset_tools.batch, "get_connection", lambda: conn, raising=False)
    # preset_tools follows the pages with tools.plugins.get_plugin_params, and that
    # module holds its own reference to get_connection. Patching only preset_tools left
    # it building a real connection, which read a different project entirely and
    # reported the reader's defaults as if they were the plugin's values.
    from fl_studio_mcp.tools import plugins as plugin_module

    monkeypatch.setattr(plugin_module, "get_connection", lambda: conn, raising=False)

    fl_env.project.plugin_params[(0, -1)] = {index: 0.5 for index in range(8)}
    fl_env.project.plugin_names[(0, -1)] = "Serum"
    fl_env.project.plugin_user_names[(0, -1)] = "My Bass"
    fl_env.connection = conn
    return fl_env


def test_saving_stores_every_named_parameter(wired):
    result = preset_tools.save_plugin_preset("bright lead", 0, tags=["lead"])
    assert result["success"] is True, result
    record = store.read_record("presets", result["id"])
    assert record["param_count"] == 8
    assert record["plugin"] == "Serum"
    assert record["user_name"] == "My Bass"


def test_saving_an_empty_slot_is_refused(wired):
    result = preset_tools.save_plugin_preset("nothing", 2)
    assert result["success"] is False
    assert "no plugin" in result["error"].lower()


def test_saving_without_a_name_is_refused(wired):
    assert preset_tools.save_plugin_preset("  ", 0)["success"] is False


def test_a_saved_preset_can_be_found(wired):
    preset_tools.save_plugin_preset("bright lead", 0, tags=["lead"])
    assert preset_tools.find_plugin_presets(query="bright")["total"] == 1
    assert preset_tools.find_plugin_presets(tags=["lead"])["total"] == 1
    assert preset_tools.find_plugin_presets(plugin="serum")["total"] == 1
    assert preset_tools.find_plugin_presets(query="pad")["total"] == 0


def test_search_results_omit_the_parameter_lists(wired):
    preset_tools.save_plugin_preset("bright lead", 0)
    found = preset_tools.find_plugin_presets()["presets"][0]
    assert "params" not in found
    assert found["param_count"] == 8


def test_an_empty_library_says_how_to_add_to_it(wired):
    result = preset_tools.find_plugin_presets()
    assert result["total"] == 0
    assert "fl_save_plugin_preset" in result["message"]


def test_recall_reports_the_difference_and_changes_nothing(wired):
    saved = preset_tools.save_plugin_preset("bright lead", 0)
    wired.project.plugin_params[(0, -1)][0] = 0.9
    result = preset_tools.recall_plugin_preset(saved["id"])
    assert result["success"] is True
    assert result["applied"] is False
    assert result["would_change"] == 1
    assert wired.project.plugin_params[(0, -1)][0] == pytest.approx(0.9), "nothing may move"
    assert "apply=True" in result["message"]


def test_recall_puts_the_value_back_through_one_batch(wired):
    saved = preset_tools.save_plugin_preset("bright lead", 0)
    wired.project.plugin_params[(0, -1)][0] = 0.9
    result = preset_tools.recall_plugin_preset(saved["id"], apply=True)
    assert result["applied"] is True, result
    assert wired.project.plugin_params[(0, -1)][0] == pytest.approx(0.5)
    assert result["batch"]["undo_name"] == "MCP: recall bright lead"


def test_recall_with_nothing_to_do_says_so(wired):
    saved = preset_tools.save_plugin_preset("bright lead", 0)
    result = preset_tools.recall_plugin_preset(saved["id"], apply=True)
    assert result["applied"] is False
    assert "already matches" in result["message"]


def test_recall_into_another_slot_uses_that_slot(wired):
    saved = preset_tools.save_plugin_preset("bright lead", 0)
    wired.project.plugin_params[(1, 2)] = {index: 0.5 for index in range(8)}
    wired.project.plugin_names[(1, 2)] = "Serum"
    wired.project.plugin_params[(1, 2)][0] = 0.1
    result = preset_tools.recall_plugin_preset(saved["id"], index=1, slot_index=2, apply=True)
    assert result["success"] is True, result
    assert wired.project.plugin_params[(1, 2)][0] == pytest.approx(0.5)


def test_a_parameter_the_plugin_no_longer_has_is_reported(wired):
    """A plugin update renumbers parameters, so a blind write is a wrong write."""
    saved = preset_tools.save_plugin_preset("bright lead", 0)
    # The plugin now reports only four parameters, so the rest cannot be written.
    wired.project.plugin_params[(0, -1)] = {index: 0.5 for index in range(4)}
    wired.project.plugin_param_counts[(0, -1)] = 4
    result = preset_tools.recall_plugin_preset(saved["id"])
    assert result["missing"], "the four lost parameters should be named"
    assert "not on the plugin now" in result["missing_note"]


def test_an_ambiguous_preset_name_is_refused_with_both_ids(wired):
    preset_tools.save_plugin_preset("bright lead", 0)
    preset_tools.save_plugin_preset("bright lead", 0)
    result = preset_tools.recall_plugin_preset("bright lead")
    assert result["success"] is False
    assert "ambiguous" in result["error"]


def test_an_unknown_preset_names_the_tool_that_lists_them(wired):
    result = preset_tools.recall_plugin_preset("never saved")
    assert result["success"] is False
    assert "fl_find_plugin_presets" in result["error"]


def test_a_morph_of_a_preset_with_itself_changes_nothing(wired):
    saved = preset_tools.save_plugin_preset("bright lead", 0)
    result = preset_tools.morph_plugin_preset(saved["id"], saved["id"], 0.5)
    assert result["success"] is True
    assert result["would_change"] == 0
    assert result["blend"]["only_in_first"] == []
    assert result["blend"]["only_in_second"] == []
    assert result["message"].startswith("Nothing to do")


def test_a_morph_reports_the_switches_it_cannot_blend(wired):
    first = preset_tools.save_plugin_preset("first", 0)
    wired.project.plugin_params[(0, -1)] = {index: 0.1 for index in range(8)}
    second = preset_tools.save_plugin_preset("second", 0)
    result = preset_tools.morph_plugin_preset(first["id"], second["id"], 0.5, apply=True)
    assert result["success"] is True, result
    notes = " ".join(result["blend"]["notes"]).lower()
    assert "switch" in notes
    assert "frequency" in notes
    assert wired.project.plugin_params[(0, -1)][0] == pytest.approx(0.3)


def test_the_morph_maths_is_the_pure_module(fl_env):
    """The tool must not grow its own copy of the blend."""
    assert preset_tools.presets.interpolate is preset_math.interpolate
