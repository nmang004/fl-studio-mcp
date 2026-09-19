"""Bars and beats, honouring the project meter rather than assuming 4/4."""

from __future__ import annotations

import pytest

from fl_studio_mcp.musical import time as mtime

FOUR_FOUR = 4.0
THREE_FOUR = 3.0
SIX_EIGHT = 3.0  # six eighth notes are three quarter notes


def test_bar_one_is_the_start():
    assert mtime.parse_position("1", FOUR_FOUR) == 0.0


def test_bar_two_starts_one_bar_in():
    assert mtime.parse_position("2", FOUR_FOUR) == 4.0


def test_a_bar_number_honours_the_meter():
    """The whole reason this module takes beats_per_bar as an argument."""
    assert mtime.parse_position("2", THREE_FOUR) == 3.0
    assert mtime.parse_position("3", THREE_FOUR) == 6.0


def test_bar_and_beat():
    assert mtime.parse_position("3.2", FOUR_FOUR) == 9.0


def test_bar_and_beat_in_three_four():
    assert mtime.parse_position("2.3", THREE_FOUR) == 5.0


def test_a_sixteenth_within_a_beat():
    assert mtime.parse_position("1.1.1", FOUR_FOUR) == 0.0
    assert mtime.parse_position("1.1.3", FOUR_FOUR) == 0.5
    assert mtime.parse_position("1.2.1", FOUR_FOUR) == 1.0


def test_a_percentage_through_a_beat():
    assert mtime.parse_position("1.2.50%", FOUR_FOUR) == pytest.approx(1.5)
    assert mtime.parse_position("2.1.25%", FOUR_FOUR) == pytest.approx(4.25)


def test_the_beat_escape_hatch():
    """For a caller thinking in beats, with no bar arithmetic."""
    assert mtime.parse_position("b7", THREE_FOUR) == 7.0
    assert mtime.parse_position("b0", THREE_FOUR) == 0.0


def test_a_float_is_treated_as_a_bar_number():
    assert mtime.parse_position(4.0, FOUR_FOUR) == mtime.parse_position("4", FOUR_FOUR)


def test_a_bar_below_one_is_refused():
    with pytest.raises(ValueError, match="below 1"):
        mtime.parse_position("0", FOUR_FOUR)


def test_a_beat_below_one_is_refused():
    with pytest.raises(ValueError, match="below 1"):
        mtime.parse_position("1.0", FOUR_FOUR)


def test_an_unrecognised_position_is_refused():
    for text in ("", "x", "1.y", "1.2.3.4.5"):
        with pytest.raises(ValueError):
            mtime.parse_position(text, FOUR_FOUR)


def test_a_percentage_without_a_beat_is_refused():
    with pytest.raises(ValueError, match="percentage"):
        mtime.parse_position("1.50%", FOUR_FOUR)


def test_ticks_round_trip():
    assert mtime.beats_to_ticks(2.5, 96) == 240
    assert mtime.ticks_to_beats(240, 96) == 2.5


def test_a_non_positive_ppq_is_refused():
    with pytest.raises(ValueError):
        mtime.ticks_to_beats(10, 0)


def test_formatting_a_position():
    assert mtime.format_position(0.0, FOUR_FOUR) == "1.1"
    assert mtime.format_position(4.0, FOUR_FOUR) == "2.1"
    assert mtime.format_position(5.0, FOUR_FOUR) == "2.2"


def test_formatting_honours_the_meter():
    assert mtime.format_position(3.0, THREE_FOUR) == "2.1"


def test_positions_round_trip_through_formatting():
    for text in ("1.1", "2.1", "3.4", "2.3"):
        beats = mtime.parse_position(text, FOUR_FOUR)
        assert mtime.format_position(beats, FOUR_FOUR) == text


def test_a_non_positive_meter_is_refused():
    with pytest.raises(ValueError):
        mtime.parse_position("1", 0)
    with pytest.raises(ValueError):
        mtime.format_position(0.0, 0)
