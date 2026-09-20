"""Preset records and interpolation, as pure functions.

The API exposes a parameter only as a normalised 0.0 to 1.0 value, so that is what a
preset stores and what interpolation works in. It is honest arithmetic and it is not a
musical morph, and the tests pin both halves of that: what it does, and what it says it
cannot do.
"""

from __future__ import annotations

import pytest

from fl_studio_mcp.musical import presets


def params(**values) -> dict:
    return {
        str(index): {"name": name, "value": value}
        for index, (name, value) in enumerate(values.items())
    }


def preset(name: str = "bright lead", **overrides) -> dict:
    payload = {
        "name": name,
        "plugin": "Serum",
        "params": params(cutoff=0.8, resonance=0.2, attack=0.1),
        "tags": ["lead", "bright"],
    }
    payload.update(overrides)
    return presets.make_preset(**payload, record_id="2026-09-19-120000-bright-lead")


def test_a_record_carries_the_plugin_and_the_parameters():
    record = preset()
    assert record["schema"] == presets.SCHEMA
    assert record["plugin"] == "Serum"
    assert record["params"]["0"]["name"] == "cutoff"
    assert record["param_count"] == 3
    assert record["created"]


def test_a_record_can_hold_both_names_for_the_plugin():
    """The plugin's own name identifies it, the label identifies the channel."""
    record = preset(plugin="Serum", user_name="My Bass")
    assert record["plugin"] == "Serum"
    assert record["user_name"] == "My Bass"


def test_matching_finds_a_preset_by_name_tag_or_plugin():
    record = preset()
    assert presets.match(record, query="bright") is True
    assert presets.match(record, tags=["lead"]) is True
    assert presets.match(record, plugin="ser") is True
    assert presets.match(record, query="pad") is False
    assert presets.match(record, tags=["pad"]) is False
    assert presets.match(record, plugin="Massive") is False


def test_an_empty_filter_matches_everything():
    assert presets.match(preset()) is True


def test_summarising_a_preset_leaves_the_parameters_out():
    summary = presets.summarise(preset())
    assert "params" not in summary
    assert summary["param_count"] == 3
    assert summary["plugin"] == "Serum"


def test_interpolating_at_zero_is_the_first_preset():
    values = presets.interpolate(preset(), preset(name="dark pad"), 0.0)
    assert values["values"]["0"]["value"] == pytest.approx(0.8)


def test_interpolating_at_one_is_the_second_preset():
    second = preset(name="dark pad", params=params(cutoff=0.2, resonance=0.2, attack=0.1))
    blended = presets.interpolate(preset(), second, 1.0)
    assert blended["values"]["0"]["value"] == pytest.approx(0.2)


def test_interpolating_at_half_is_between_them():
    second = preset(params=params(cutoff=0.2, resonance=0.6, attack=0.1))
    blended = presets.interpolate(preset(), second, 0.5)
    assert blended["values"]["0"]["value"] == pytest.approx(0.5)
    assert blended["values"]["1"]["value"] == pytest.approx(0.4)


def test_an_amount_outside_zero_to_one_is_clamped():
    second = preset(params=params(cutoff=0.0, resonance=0.2, attack=0.1))
    assert presets.interpolate(preset(), second, 5.0)["values"]["0"]["value"] == 0.0
    assert presets.interpolate(preset(), second, -5.0)["values"]["0"]["value"] == 0.8


def test_a_parameter_in_only_one_preset_is_named_not_invented():
    """There is no midpoint between a value and no value."""
    # Different indices, because a parameter at the same index with a different name
    # is the rename case, which is a separate test.
    first = preset(params={"0": {"name": "cutoff", "value": 0.8}})
    second = preset(params={"1": {"name": "resonance", "value": 0.4}})
    blended = presets.interpolate(first, second, 0.5)
    assert blended["only_in_first"] == ["cutoff"]
    assert blended["only_in_second"] == ["resonance"]
    assert blended["values"]["0"]["name"] == "cutoff", "the value that exists is kept"
    assert blended["values"]["1"]["name"] == "resonance"
    assert any("only one" in note for note in blended["notes"])


def test_a_parameter_renamed_between_presets_is_reported_by_name():
    """The index is the same but the parameter is not, so blending them is wrong."""
    first = preset(params={"0": {"name": "cutoff", "value": 0.8}})
    second = preset(params={"0": {"name": "drive", "value": 0.2}})
    blended = presets.interpolate(first, second, 0.5)
    assert blended["renamed"] == [{"index": "0", "first": "cutoff", "second": "drive"}]
    assert blended["values"]["0"]["value"] == pytest.approx(0.8), "not blended"


def test_the_notes_say_that_switches_snap_and_frequency_is_not_linear():
    blended = presets.interpolate(preset(), preset(), 0.5)
    text = " ".join(blended["notes"]).lower()
    assert "switch" in text
    assert "frequency" in text


def test_recall_commands_carry_every_parameter_with_no_pickup_mode():
    commands = presets.recall_commands(preset(), index=4, slot_index=-1)
    assert all(command["action"] == "plugins.setParamValue" for command in commands)
    assert commands[0]["params"]["plugin_index"] == 4
    assert commands[0]["params"]["param_index"] == 0
    assert commands[0]["params"]["value"] == pytest.approx(0.8)
    assert commands[0]["params"]["slot_index"] == -1


def test_recall_commands_can_write_to_a_mixer_slot():
    commands = presets.recall_commands(preset(), index=2, slot_index=1)
    assert commands[0]["params"]["slot_index"] == 1


def test_a_parameter_that_no_longer_exists_is_reported():
    """A plugin update can renumber its parameters, so a preset is checked first."""
    checked = presets.recall_commands(
        preset(), index=0, current_total=1, current_names={"0": "cutoff"}
    )
    assert [command["params"]["param_index"] for command in checked["commands"]] == [0]
    assert checked["missing"] == ["resonance", "attack"]
