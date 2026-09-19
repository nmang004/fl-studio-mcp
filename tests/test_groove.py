"""Groove transforms: pure functions over note dicts, tested without FL."""

from __future__ import annotations

import pytest

from fl_studio_mcp.musical import groove


def note(time=0.0, length=1.0, velocity=0.8, **extra):
    base = {"midi": 60, "time": time, "length": length, "velocity": velocity}
    base.update(extra)
    return base


EIGHTHS = [note(time=i * 0.5) for i in range(8)]


def test_swing_moves_the_offbeats_and_leaves_the_beats():
    swung = groove.swing(EIGHTHS, amount=0.5)
    assert swung[0]["time"] == pytest.approx(0.0)
    assert swung[1]["time"] == pytest.approx(0.625)
    assert swung[2]["time"] == pytest.approx(1.0)


def test_swing_with_zero_amount_changes_nothing():
    swung = groove.swing(EIGHTHS, amount=0.0)
    assert [n["time"] for n in swung] == [n["time"] for n in EIGHTHS]


def test_swing_respects_the_subdivision():
    sixteenths = [note(time=i * 0.25) for i in range(4)]
    swung = groove.swing(sixteenths, amount=0.5, subdivision=4)
    assert swung[1]["time"] == pytest.approx(0.3125)


def test_swing_refuses_a_bad_amount():
    with pytest.raises(ValueError):
        groove.swing(EIGHTHS, amount=2.0)
    with pytest.raises(ValueError):
        groove.swing(EIGHTHS, subdivision=0)


def test_humanize_with_a_seed_is_reproducible():
    first = groove.humanize(EIGHTHS, seed=7)
    second = groove.humanize(EIGHTHS, seed=7)
    assert [n["time"] for n in first] == [n["time"] for n in second]


def test_humanize_without_a_seed_varies():
    first = groove.humanize(EIGHTHS)
    second = groove.humanize(EIGHTHS)
    assert [n["time"] for n in first] != [n["time"] for n in second]


def test_humanize_never_pushes_a_note_before_zero():
    """A negative start is not a note FL can hold."""
    first = note(time=0.0)
    for seed in range(50):
        assert groove.humanize([first], timing=0.5, seed=seed)[0]["time"] >= 0.0


def test_humanize_keeps_velocity_in_range():
    loud = [note(velocity=0.99), note(velocity=0.01)]
    for seed in range(50):
        weights = [n["velocity"] for n in groove.humanize(loud, velocity=0.5, seed=seed)]
        assert all(0.0 <= w <= 1.0 for w in weights)


def test_humanize_leaves_a_note_without_velocity_alone():
    bare = {"midi": 60, "time": 0.0, "length": 1.0}
    assert "velocity" not in groove.humanize([bare], seed=1)[0]


def test_quantize_full_strength_lands_on_the_grid():
    sloppy = [note(time=0.06), note(time=0.44), note(time=0.99)]
    snapped = groove.quantize(sloppy, grid=0.25, strength=1.0)
    assert [n["time"] for n in snapped] == [0.0, 0.5, 1.0]


def test_quantize_zero_strength_changes_nothing():
    sloppy = [note(time=0.06), note(time=0.44)]
    kept = groove.quantize(sloppy, grid=0.25, strength=0.0)
    assert [n["time"] for n in kept] == [0.06, 0.44]


def test_quantize_with_partial_strength_moves_part_of_the_way():
    result = groove.quantize([note(time=0.0 + 0.1)], grid=0.25, strength=0.5)
    assert result[0]["time"] == pytest.approx(0.05)


def test_quantize_does_not_change_lengths():
    sloppy = [note(time=0.06, length=0.75)]
    assert groove.quantize(sloppy, strength=1.0)[0]["length"] == 0.75


def test_quantize_refuses_a_bad_grid_or_strength():
    with pytest.raises(ValueError):
        groove.quantize(EIGHTHS, grid=0)
    with pytest.raises(ValueError):
        groove.quantize(EIGHTHS, strength=1.5)


def test_accent_raises_the_marked_notes():
    result = groove.accent(EIGHTHS, pattern="x-x-", strength=0.2)
    assert result[0]["velocity"] == pytest.approx(1.0)  # clamped from 1.0
    assert result[1]["velocity"] == pytest.approx(0.8)
    assert result[2]["velocity"] == pytest.approx(1.0)


def test_accent_repeats_a_short_pattern():
    four = [note(velocity=0.5) for _ in range(4)]
    result = groove.accent(four, pattern="x.", strength=0.1)
    assert [n["velocity"] for n in result] == pytest.approx([0.6, 0.5, 0.6, 0.5])


def test_accent_refuses_an_empty_pattern():
    with pytest.raises(ValueError):
        groove.accent(EIGHTHS, pattern="")


def test_crescendo_ramps_up_in_time_order():
    jumbled = [note(time=1.0, velocity=0.5), note(time=0.0, velocity=0.5),
               note(time=2.0, velocity=0.5)]
    result = groove.crescendo(jumbled, start=0.2, end=1.0)
    assert [n["time"] for n in result] == [0.0, 1.0, 2.0]
    assert [n["velocity"] for n in result] == pytest.approx([0.2, 0.6, 1.0])


def test_crescendo_of_one_note_takes_the_start_value():
    result = groove.crescendo([note(velocity=0.5)], start=0.3, end=1.0)
    assert result[0]["velocity"] == pytest.approx(0.3)


def test_no_transform_mutates_its_input():
    original = EIGHTHS
    snapshot = [dict(n) for n in original]
    groove.swing(original, amount=0.5)
    groove.humanize(original, seed=1)
    groove.quantize(original, strength=1.0)
    groove.accent(original)
    groove.crescendo(original)
    assert original == snapshot


@pytest.mark.parametrize("transform", [
    lambda notes: groove.swing(notes),
    lambda notes: groove.humanize(notes),
    lambda notes: groove.quantize(notes),
    lambda notes: groove.accent(notes),
    lambda notes: groove.crescendo(notes),
])
def test_an_empty_list_is_returned_unchanged(transform):
    assert transform([]) == []
