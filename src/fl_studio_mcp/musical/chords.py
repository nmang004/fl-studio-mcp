"""Chord symbols, because Cmaj7 is clearer than three MIDI numbers.

A producer writes `Cmaj7`, not `[60, 64, 67, 71]`, and a model reasoning about
harmony should not have to compute either. This parses the vocabulary people
actually type and refuses the rest, because a wrong chord that looks plausible is
worse than an error naming the symbol.

Interval tables are in semitones from the root.
"""

from __future__ import annotations

import re

NOTE_NAMES = {
    "C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "Fb": 4,
    "E#": 5, "F": 5, "F#": 6, "Gb": 6, "G": 7, "G#": 8, "Ab": 8, "A": 9,
    "A#": 10, "Bb": 10, "B": 11, "Cb": 11, "B#": 0,
}

# The quality suffix to intervals from the root. Ordered longest first so that
# matching is unambiguous: "maj7" has to be tried before "maj", and "m7b5" before
# "m7".
QUALITIES: tuple[tuple[str, tuple[int, ...]], ...] = (
    ("maj13", (0, 4, 7, 11, 14, 17, 21)),
    ("m13", (0, 3, 7, 10, 14, 17, 21)),
    ("13", (0, 4, 7, 10, 14, 17, 21)),
    ("maj11", (0, 4, 7, 11, 14, 17)),
    ("m11", (0, 3, 7, 10, 14, 17)),
    ("11", (0, 4, 7, 10, 14, 17)),
    ("maj9", (0, 4, 7, 11, 14)),
    ("m9", (0, 3, 7, 10, 14)),
    ("9", (0, 4, 7, 10, 14)),
    ("maj7#5", (0, 4, 8, 11)),
    ("maj7#11", (0, 4, 7, 11, 18)),
    ("maj7", (0, 4, 7, 11)),
    ("mMaj7", (0, 3, 7, 11)),
    ("m7b5", (0, 3, 6, 10)),
    ("m7", (0, 3, 7, 10)),
    ("7sus4", (0, 5, 7, 10)),
    ("7b9", (0, 4, 7, 10, 13)),
    ("7#9", (0, 4, 7, 10, 15)),
    ("7#11", (0, 4, 7, 10, 18)),
    ("7b5", (0, 4, 6, 10)),
    ("7", (0, 4, 7, 10)),
    ("dim7", (0, 3, 6, 9)),
    ("dim", (0, 3, 6)),
    ("m7", (0, 3, 7, 10)),
    ("m6", (0, 3, 7, 9)),
    ("madd9", (0, 3, 7, 14)),
    ("m", (0, 3, 7)),
    ("aug", (0, 4, 8)),
    ("+", (0, 4, 8)),
    ("sus2", (0, 2, 7)),
    ("sus4", (0, 5, 7)),
    ("sus", (0, 5, 7)),
    ("add9", (0, 4, 7, 14)),
    ("add11", (0, 4, 7, 17)),
    ("6", (0, 4, 7, 9)),
    ("5", (0, 7)),
    ("", (0, 4, 7)),
)

_MATCH = re.compile(r"^([A-Ga-g][#b]?)(.*)$")


def parse_chord(symbol: str) -> list[int]:
    """The intervals of a chord symbol, in semitones above the root.

    Args:
        symbol: A chord symbol, for example "Cmaj7", "F#m7b5" or "Bb13".

    Returns:
        Intervals ascending from 0.

    Raises:
        ValueError: If the symbol is not recognised, naming it. Guessing would be
            worse: a plausible wrong chord is harder to notice than an error.
    """
    text = str(symbol).strip()
    if not text:
        raise ValueError("Chord symbol is empty")

    match = _MATCH.match(text)
    if not match:
        raise ValueError(
            f"{symbol!r} does not start with a note name. Expected something like "
            "C, F#m7 or Bbmaj7."
        )
    note_text, quality_text = match.group(1), match.group(2)

    slash = quality_text.find("/")
    if slash >= 0:
        quality_text = quality_text[:slash]

    # The intervals are relative to the root, so the root's own pitch class is not
    # added here. notes_for_chord does that, because it knows the octave.
    _note_number(note_text)
    return list(_intervals_for(quality_text, symbol))


def notes_for_chord(symbol: str, root_octave: int = 4) -> list[int]:
    """The MIDI note numbers of a chord.

    Args:
        symbol: A chord symbol, for example "Am7".
        root_octave: Which octave the root sits in. 4 puts C at MIDI 60, which is
            middle C in FL Studio's own numbering.

    Returns:
        MIDI note numbers, ascending.
    """
    root = root_of(symbol)
    base = (root_octave + 1) * 12 + root
    return [base + interval for interval in parse_chord(symbol)]


def root_of(symbol: str) -> int:
    """The root of a chord symbol as a pitch class, where C is 0."""
    text = str(symbol).strip()
    match = _MATCH.match(text)
    if not match:
        raise ValueError(f"{symbol!r} does not start with a note name")
    return _note_number(match.group(1))


def bass_of(symbol: str) -> int | None:
    """The bass note of a slash chord, or None for a plain one."""
    text = str(symbol).strip()
    slash = text.find("/")
    if slash < 0:
        return None
    bass_text = text[slash + 1:].strip()
    if not bass_text:
        raise ValueError(f"{symbol!r} has a slash but no bass note")
    return _note_number(bass_text)


def _note_number(text: str) -> int:
    canonical = text[0].upper() + text[1:]
    if canonical not in NOTE_NAMES:
        raise ValueError(
            f"{text!r} is not a note name. Use a letter A to G with an optional "
            "sharp or flat."
        )
    return NOTE_NAMES[canonical]


def _intervals_for(quality: str, symbol: str) -> tuple[int, ...]:
    for name, intervals in QUALITIES:
        if quality == name:
            return intervals
    # An unknown suffix is refused with the list of what is understood, because
    # "Cxyz" silently returning a C major triad is the failure that matters.
    known = ", ".join(sorted({name for name, _ in QUALITIES if name}))
    raise ValueError(
        f"{symbol!r} has an unrecognised quality {quality!r}. Understood: {known}"
    )
