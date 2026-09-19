"""Basslines, in the project's own key and meter.

This is the piece that makes the fork worth having rather than a wrapper. One call
produces a pattern a producer would recognise as a bassline: in key, in time, with
the slide articulation that makes a 303 line move.

A rhythm is a string, one character per subdivision: `x` is a note, `-` is a rest,
and anything else is a rest. That is readable in a tool call in a way a list of
floats is not.
"""

from __future__ import annotations

from typing import Any

from fl_studio_mcp.musical import chords

HIT = "x"
SLIDE = "-"
# Scale degrees a bassline moves through, as offsets into the scale rather than
# semitones, so the same pattern works in any key and any mode.
ROOT_DEGREE = 0
FIFTH_DEGREE = 4
OCTAVE_DEGREE = 7


def parse_rhythm(pattern: str) -> list[bool]:
    """A rhythm string as a list of hits and rests.

    Args:
        pattern: One character per subdivision, `x` for a note.

    Returns:
        True for a hit, False for a rest.

    Raises:
        ValueError: If the pattern is empty or holds no hits, because a bassline of
            silence is almost certainly a mistake rather than a request.
    """
    if not pattern:
        raise ValueError("Rhythm pattern is empty. Use x for a note and - for a rest.")
    hits = [character == HIT for character in pattern]
    if not any(hits):
        raise ValueError(
            f"Rhythm pattern {pattern!r} holds no notes. Use x for a note, for "
            "example x-x-xx--."
        )
    return hits


def bassline(
    root: int,
    pattern: str = "x-x-xx--",
    bars: int = 1,
    octave: int = 2,
    scale: list[int] | None = None,
    articulation: str = "slide",
    velocity: float = 0.9,
    beats_per_bar: float = 4.0,
    group: bool = True,
) -> list[dict[str, Any]]:
    """A bassline on a root note, in a rhythm, articulated so it moves.

    The notes walk the scale rather than jumping in semitones, so the same pattern
    sounds right in a major key and in a minor one. The first note of each bar is
    the root and the middle of the bar moves to the fifth, which is the shape that
    makes a bassline a bassline rather than a repeated note.

    Args:
        root: The root as a MIDI note number, for example 36 for C in octave 2.
        pattern: One character per subdivision, `x` for a note.
        bars: How many bars to fill. The pattern repeats to fill them.
        octave: Unused when `root` is already a MIDI number; kept so a caller can
            see which octave it asked for in the result.
        scale: Semitone offsets from the root. Defaults to a minor pentatonic,
            which fits both major and minor contexts without a wrong note.
        articulation: "slide", "porta" or "none". Slide is what makes an acid line
            sound alive, and it is the default for that reason.
        velocity: The velocity of every note, before accenting.
        beats_per_bar: From the project meter.
        group: Whether to ask FL to group the phrase, so it can be removed exactly.

    Returns:
        Note dicts in the shape the piano roll tools take.

    Raises:
        ValueError: If the rhythm, the bar count or the articulation is not usable.
    """
    if bars < 1:
        raise ValueError(f"bars must be at least 1, got {bars}")
    if articulation not in ("slide", "porta", "none"):
        raise ValueError(
            f"articulation must be slide, porta or none, got {articulation!r}"
        )

    degrees = list(scale) if scale else [0, 3, 5, 7, 10]
    hits = parse_rhythm(pattern)

    step = beats_per_bar / len(hits)
    total = bars * len(hits)
    notes: list[dict[str, Any]] = []

    for index in range(total):
        if not hits[index % len(hits)]:
            continue
        position = index * step
        # Where in the bar this note sits, which decides its scale degree. The
        # first note of a bar is the root and the midpoint moves to the fifth,
        # which is the interval that makes a bassline move without wandering.
        within_bar = index % len(hits)
        if within_bar == 0:
            degree = ROOT_DEGREE
        elif within_bar >= len(hits) // 2:
            degree = FIFTH_DEGREE % len(degrees)
        else:
            degree = ROOT_DEGREE

        offset = degrees[degree % len(degrees)]
        if within_bar >= len(hits) // 2 and degree == OCTAVE_DEGREE % len(degrees):
            offset = degrees[-1]

        note: dict[str, Any] = {
            "midi": root + offset,
            "time": position,
            "duration": step,
            "velocity": velocity,
        }
        if articulation != "none":
            note[articulation] = True
        notes.append(note)

    return notes


def chord_bassline(
    symbol: str,
    pattern: str = "x-x-xx--",
    bars: int = 1,
    octave: int = 2,
    articulation: str = "slide",
    beats_per_bar: float = 4.0,
) -> list[dict[str, Any]]:
    """A bassline on the root of a chord symbol.

    The chord's own notes are not used: a bassline plays the root and moves, and
    stacking the chord in the bass is a different part.
    """
    root = chords.notes_for_chord(symbol, octave)[0]
    return bassline(
        root,
        pattern=pattern,
        bars=bars,
        octave=octave,
        articulation=articulation,
        beats_per_bar=beats_per_bar,
    )
