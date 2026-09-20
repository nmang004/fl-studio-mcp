"""The plugin calls the controller used to get wrong.

Four `plugins.*` functions take an argument that the controller was filling with
`use_global`, because the fake had the same wrong signature and agreed with it:

    getPluginName(index, slotIndex, userName, useGlobalIndex)
    getParamValueString(paramIndex, index, slotIndex, pickupMode, useGlobalIndex)
    setParamValue(value, paramIndex, index, slotIndex, pickupMode, useGlobalIndex)
    getColor(index, slotIndex, flag, useGlobalIndex)

Read from `plugins/__init__.py` in stubs v37.0.1. The fakes now declare the real
signatures, so these tests can see the difference, and a source level test refuses any
future positional call that could land on the wrong name again.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

CONTROLLER = Path(__file__).resolve().parent.parent / "fl_controller" / "device_FLStudioMCP.py"


@pytest.fixture
def plugin(fl_env):
    """A channel with a plugin whose producer label differs from its own name."""
    fl_env.project.plugin_params[(0, -1)] = {0: 0.25, 1: 0.75}
    fl_env.project.plugin_names[(0, -1)] = "Serum"
    fl_env.project.plugin_user_names[(0, -1)] = "My Bass"
    fl_env.project.plugin_calls.clear()
    return fl_env


def calls(fl_env, name: str) -> list[dict]:
    return [kwargs for called, kwargs in fl_env.project.plugin_calls if called == name]


def test_the_plugin_name_is_the_plugins_own_name(plugin):
    """Not the label the producer typed, which is what userName selects."""
    result = plugin.controller.dispatch_command(
        "plugins.getName", {"index": 0, "slot_index": -1, "use_global": True}
    )
    assert result["name"] == "Serum"


def test_the_producers_label_is_reported_beside_it(plugin):
    """Both are wanted: one identifies the plugin, the other identifies the channel."""
    result = plugin.controller.dispatch_command(
        "plugins.getName", {"index": 0, "slot_index": -1, "use_global": True}
    )
    assert result["user_name"] == "My Bass"


def test_a_parameter_write_carries_no_pickup_mode(plugin):
    """setParamValue's fifth argument is pickupMode. A scripted write wants PIM_None."""
    plugin.controller.dispatch_command(
        "plugins.setParamValue",
        {"param_index": 1, "value": 0.6, "plugin_index": 0, "slot_index": -1, "use_global": True},
    )
    recorded = calls(plugin, "setParamValue")
    assert recorded, "the fake was not called with keywords the audit can see"
    assert recorded[-1]["pickupMode"] == plugin.modules["midi"].PIM_None
    assert plugin.project.plugin_params[(0, -1)][1] == pytest.approx(0.6)


def test_the_display_string_is_read_with_the_global_index_flag(plugin):
    plugin.controller.dispatch_command(
        "plugins.getParams",
        {"index": 0, "slot_index": -1, "use_global": True, "max_params": 2},
    )
    recorded = calls(plugin, "getParamValueString")
    assert recorded, "the fake was not called"
    assert recorded[-1]["useGlobalIndex"] is True
    assert recorded[-1]["pickupMode"] == plugin.modules["midi"].PIM_None


def test_the_colour_flag_asks_for_the_background_colour(plugin):
    """The default flag is GC_BackgroundColor. use_global landed there instead."""
    plugin.controller.dispatch_command(
        "plugins.getColor", {"index": 0, "slot_index": -1, "use_global": True}
    )
    recorded = calls(plugin, "getColor")
    assert recorded[-1]["flag"] == plugin.modules["midi"].GC_BackgroundColor


def test_the_reply_says_whether_a_plugin_is_there_at_all(plugin):
    """An empty slot and a plugin with no name should not look the same."""
    present = plugin.controller.dispatch_command(
        "plugins.getName", {"index": 0, "slot_index": -1, "use_global": True}
    )
    empty = plugin.controller.dispatch_command(
        "plugins.getName", {"index": 1, "slot_index": -1, "use_global": True}
    )
    assert present["valid"] is True
    assert empty["valid"] is False


def test_every_plugin_call_in_the_controller_passes_keywords():
    """The habit that fixes this class of bug, rather than four corrected positions.

    A new argument in a stub signature cannot capture one of ours if every call names
    what it is passing.
    """
    text = CONTROLLER.read_text()
    offenders = []
    for match in re.finditer(r"plugins\.(\w+)\(([^)]*)\)", text):
        arguments = match.group(2).strip()
        if not arguments:
            continue
        for argument in arguments.split(","):
            # A trailing comma after a multi-line call leaves an empty chunk.
            if not argument.strip():
                continue
            if "=" not in argument:
                offenders.append(f"plugins.{match.group(1)}({arguments})")
                break
    assert not offenders, "these calls pass positionally: " + "; ".join(sorted(set(offenders)))
