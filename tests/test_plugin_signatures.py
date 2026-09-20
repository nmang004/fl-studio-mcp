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


def test_a_parameter_write_uses_the_five_parameter_form(plugin):
    """The runtime has no pickupMode, and its first parameter is named paramValue.

    Passing the stub's pickupMode raised "function takes at most 4 keyword arguments"
    on the string reader, and calling the writer by keyword raised "missing required
    argument paramValue". Both were measured with the probe action, so the write is
    positional and the index flag lands where the runtime expects it.
    """
    plugin.controller.dispatch_command(
        "plugins.setParamValue",
        {"param_index": 1, "value": 0.6, "plugin_index": 0, "slot_index": -1, "use_global": True},
    )
    recorded = calls(plugin, "setParamValue")
    assert recorded, "the fake was not called"
    assert recorded[-1]["useGlobalIndex"] is True, "the index flag did not arrive"
    assert plugin.project.plugin_params[(0, -1)][1] == pytest.approx(0.6)


def test_the_display_string_is_read_with_the_global_index_flag(plugin):
    plugin.controller.dispatch_command(
        "plugins.getParams",
        {"index": 0, "slot_index": -1, "use_global": True, "max_params": 2},
    )
    recorded = calls(plugin, "getParamValueString")
    assert recorded, "the fake was not called"
    assert recorded[-1]["useGlobalIndex"] is True


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


def test_every_plugin_call_matches_a_form_the_build_accepts():
    """Pinned against measurement, because the stubs are not the runtime signature.

    `plugins.probeCalls` asked FL Studio 2026 build 5406 what each function accepts:

        getParamName, getParamValue, getParamCount, getPluginName, isValid
            keywords with the stub's names work
        getParamValueString
            four parameters. The stub's fifth, pickupMode, raises
            "function takes at most 4 keyword arguments"
        setParamValue
            five parameters, first one named paramValue, and a keyword call raises
            "function missing required argument 'paramValue'", so it is called
            positionally

    That is why this test allows one positional call rather than demanding keywords
    everywhere: demanding keywords everywhere is what emptied a parameter page while
    the handler still reported success.
    """
    text = CONTROLLER.read_text()
    # The probe action's whole purpose is to try both forms, so it is exempt.
    probe_start = text.index("def handle_plugins_probe_calls")
    probe_end = text.index("def handle_plugins_get_color")
    text = text[:probe_start] + text[probe_end:]
    positional_allowed = {"setParamValue"}
    offenders = []
    for match in re.finditer(r"plugins\.(\w+)\(([^)]*)\)", text):
        function = match.group(1)
        arguments = match.group(2).strip()
        if not arguments:
            continue
        bare = [
            argument
            for argument in arguments.split(",")
            if argument.strip() and "=" not in argument
        ]
        if bare and function not in positional_allowed:
            offenders.append(f"plugins.{function}({arguments})")
        if function == "getParamValueString" and "pickupMode" in arguments:
            offenders.append(f"plugins.{function} passes a pickupMode the build has not got")
    assert not offenders, "; ".join(sorted(set(offenders)))


def test_the_probe_action_is_still_there_to_ask_again():
    """The next FL release can change this, and the probe is how it gets re-asked."""
    assert "def handle_plugins_probe_calls" in CONTROLLER.read_text()
