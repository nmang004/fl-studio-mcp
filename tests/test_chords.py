"""Chord symbols: parse the vocabulary a producer types, refuse the rest."""

from __future__ import annotations

import pytest

from fl_studio_mcp.musical import chords


def test_a_major_triad():
    assert chords.parse_chord("C") == [0, 4, 7]


def test_a_minor_triad():
    assert chords.parse_chord("Cm") == [0, 3, 7]


def test_a_diminished_triad():
    assert chords.parse_chord("Cdim") == [0, 3, 6]


def test_an_augmented_triad():
    assert chords.parse_chord("Caug") == [0, 4, 8]


@pytest.mark.parametrize("symbol,expected", [
    ("Cmaj7", [0, 4, 7, 11]),
    ("Cm7", [0, 3, 7, 10]),
    ("C7", [0, 4, 7, 10]),
    ("Cm7b5", [0, 3, 6, 10]),
    ("Cdim7", [0, 3, 6, 9]),
    ("CmMaj7", [0, 3, 7, 11]),
])
def test_sevenths(symbol, expected):
    assert chords.parse_chord(symbol) == expected


@pytest.mark.parametrize("symbol,expected", [
    ("Csus2", [0, 2, 7]),
    ("Csus4", [0, 5, 7]),
    ("Cadd9", [0, 4, 7, 14]),
    ("C6", [0, 4, 7, 9]),
    ("Cm6", [0, 3, 7, 9]),
    ("C5", [0, 7]),
])
def test_suspended_added_and_power_chords(symbol, expected):
    assert chords.parse_chord(symbol) == expected


@pytest.mark.parametrize("symbol,expected", [
    ("C9", [0, 4, 7, 10, 14]),
    ("Cm9", [0, 3, 7, 10, 14]),
    ("Cmaj9", [0, 4, 7, 11, 14]),
    ("C11", [0, 4, 7, 10, 14, 17]),
    ("C13", [0, 4, 7, 10, 14, 17, 21]),
])
def test_extensions(symbol, expected):
    assert chords.parse_chord(symbol) == expected


@pytest.mark.parametrize("symbol,expected", [
    ("C7b9", [0, 4, 7, 10, 13]),
    ("C7#9", [0, 4, 7, 10, 15]),
    ("C7#11", [0, 4, 7, 10, 18]),
    ("Cmaj7#5", [0, 4, 8, 11]),
])
def test_alterations(symbol, expected):
    assert chords.parse_chord(symbol) == expected


def test_sharp_and_flat_roots_are_the_same_pitch_class():
    assert chords.root_of("F#") == chords.root_of("Gb") == 6
    assert chords.root_of("Bb") == 10
    assert chords.root_of("Eb") == 3


def test_a_slash_chord_reports_its_bass():
    assert chords.bass_of("C/G") == 7
    assert chords.bass_of("Am7/G") == 7
    assert chords.bass_of("C") is None


def test_the_chord_itself_ignores_the_slash():
    assert chords.parse_chord("C/G") == chords.parse_chord("C")


def test_octave_placement():
    assert chords.notes_for_chord("C", 4) == [60, 64, 67]
    # A major is A, C#, E. A minor would be A, C, E, and the first version of this
    # expectation asked for the minor third from a major symbol.
    assert chords.notes_for_chord("A", 4) == [69, 73, 76]
    assert chords.notes_for_chord("Am", 4) == [69, 72, 76]
    assert chords.notes_for_chord("C", 2)[0] == 36


def test_the_root_is_the_lowest_note():
    for symbol in ("C", "F#m7b5", "Bbmaj7", "Eb9"):
        assert chords.parse_chord(symbol)[0] == 0


def test_intervals_ascend():
    for symbol in ("Cmaj13", "Cm11", "C13", "Cdim7"):
        intervals = chords.parse_chord(symbol)
        assert intervals == sorted(intervals), f"{symbol} is not ascending"


def test_an_unknown_quality_is_refused_by_name():
    with pytest.raises(ValueError, match="Cxyz"):
        chords.parse_chord("Cxyz")


def test_a_symbol_without_a_note_is_refused():
    for symbol in ("", "H", "7m", "maj7"):
        with pytest.raises(ValueError):
            chords.parse_chord(symbol)


def test_a_slash_without_a_bass_is_refused():
    with pytest.raises(ValueError, match="bass"):
        chords.bass_of("C/")


def test_lowercase_note_names_are_accepted():
    assert chords.parse_chord("cmaj7") == chords.parse_chord("Cmaj7")
