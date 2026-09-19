"""Groove transforms over note dicts.

Pure functions, so they are testable without FL Studio, and every one returns new
dicts rather than editing the caller's. A caller that wants the original still has
it, which matters because these are usually applied to a copy that gets written to
FL and compared against what was there before.

Notes are dicts with at least `time` and `length` in beats, and `velocity` from 0.0
to 1.0. That is the shape the piano roll tools already take, so a transform's output
is another transform's input and a tool's input.
"""

from __future__ import annotations

import random
from typing import Any

Note = dict[str, Any]


def swing(notes: list[Note], amount: float = 0.5, subdivision: int = 2) -> list[Note]:
    """Delay every second subdivision, which is what swing is.

    Args:
        notes: The notes to transform.
        amount: 0.0 leaves the notes where they are. 0.5 is a triplet feel, pushing
            the offbeat halfway to the next subdivision. 1.0 pushes it all the way,
            which is a different rhythm rather than a groove.
        subdivision: How many notes per beat the groove divides into. 2 swings
            eighth notes, which is the usual meaning.

    Returns:
        New note dicts, in the same order.
    """
    if subdivision < 1:
        raise ValueError(f"subdivision must be at least 1, got {subdivision}")
    if not 0.0 <= amount <= 1.0:
        raise ValueError(f"amount must be between 0 and 1, got {amount}")

    step = 1.0 / subdivision
    shifted = []
    for note in notes:
        new_note = dict(note)
        position = float(new_note.get("time", 0.0))
        # Which subdivision this note sits on, and how far into it.
        index = int(round(position / step))
        if index % 2 == 1:
            new_note["time"] = position + amount * step * 0.5
        shifted.append(new_note)
    return shifted


def humanize(
    notes: list[Note],
    timing: float = 0.02,
    velocity: float = 0.1,
    seed: int | None = None,
) -> list[Note]:
    """Nudge timing and velocity, so a part stops sounding mechanical.

    Args:
        notes: The notes to transform.
        timing: Maximum timing shift in beats, either direction.
        velocity: Maximum velocity change, either direction.
        seed: Set it for a reproducible result, which a test or a diff wants.

    Returns:
        New note dicts. Timing never goes below zero, because a note before the
        start of the pattern is not a note FL can hold.
    """
    rng = random.Random(seed)
    humanized = []
    for note in notes:
        new_note = dict(note)
        position = float(new_note.get("time", 0.0))
        new_note["time"] = max(0.0, position + rng.uniform(-timing, timing))
        if "velocity" in new_note:
            weight = float(new_note["velocity"])
            new_note["velocity"] = _clamp(weight + rng.uniform(-velocity, velocity))
        humanized.append(new_note)
    return humanized


def quantize(notes: list[Note], grid: float = 0.25, strength: float = 1.0) -> list[Note]:
    """Pull note starts towards the grid.

    Args:
        notes: The notes to transform.
        grid: Grid size in beats. 0.25 is a sixteenth.
        strength: 1.0 lands exactly on the grid, 0.0 leaves the note alone, and
            anything between moves it part of the way. Partial strength is what
            keeps a performance feeling played rather than programmed.

    Returns:
        New note dicts. Lengths are untouched, because quantizing a start is not a
        reason to change how long a note is held.
    """
    if grid <= 0:
        raise ValueError(f"grid must be positive, got {grid}")
    if not 0.0 <= strength <= 1.0:
        raise ValueError(f"strength must be between 0 and 1, got {strength}")

    quantized = []
    for note in notes:
        new_note = dict(note)
        position = float(new_note.get("time", 0.0))
        target = round(position / grid) * grid
        new_note["time"] = position + (target - position) * strength
        quantized.append(new_note)
    return quantized


def accent(notes: list[Note], pattern: str = "x-x-", strength: float = 0.2) -> list[Note]:
    """Raise the velocity of the notes the pattern marks.

    Args:
        notes: The notes to transform.
        pattern: One character per note in time order. `x` accents, anything else
            leaves alone, so "x-x-" is four on the floor with the offbeats lighter.
        strength: How much to raise an accented note's velocity.

    Returns:
        New note dicts. The pattern repeats if it is shorter than the note list.

    Raises:
        ValueError: If the pattern is empty, which would silently do nothing.
    """
    if not pattern:
        raise ValueError("pattern must not be empty")
    accented = []
    for index, note in enumerate(notes):
        new_note = dict(note)
        if pattern[index % len(pattern)] == "x" and "velocity" in new_note:
            new_note["velocity"] = _clamp(float(new_note["velocity"]) + strength)
        accented.append(new_note)
    return accented


def crescendo(notes: list[Note], start: float = 0.5, end: float = 1.0) -> list[Note]:
    """Ramp velocity across the notes, in time order.

    Args:
        notes: The notes to transform. Order does not matter; they are sorted by
            time first, because a crescendo is a shape in time.
        start: Velocity of the first note.
        end: Velocity of the last.

    Returns:
        New note dicts in time order. With one note it gets the start value, since
        a ramp needs somewhere to ramp to.
    """
    if not notes:
        return []
    ordered = sorted(notes, key=lambda note: float(note.get("time", 0.0)))
    if len(ordered) == 1:
        single = dict(ordered[0])
        if "velocity" in single:
            single["velocity"] = _clamp(start)
        return [single]

    ramped = []
    span = len(ordered) - 1
    for index, note in enumerate(ordered):
        new_note = dict(note)
        if "velocity" in new_note:
            weight = start + (end - start) * (index / span)
            new_note["velocity"] = _clamp(weight)
        ramped.append(new_note)
    return ramped


def _clamp(value: float) -> float:
    """Hold a velocity inside the range the API accepts."""
    return max(0.0, min(1.0, value))
