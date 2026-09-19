"""Bars and beats, honouring the project's meter.

A caller says "bar 3 beat 2", not "beat 9.0", and in 3/4 the second of those is
wrong in a way that is easy to miss. Everything here takes the meter as an
argument rather than assuming four, and there is no bare 4 anywhere in the
arithmetic.

The one escape hatch is `b7`, meaning seven beats from the start with no bar
arithmetic at all, for a caller who is thinking in beats rather than in bars.
"""

from __future__ import annotations

BEATS_PREFIX = "b"


def beats_to_ticks(beats: float, ppq: int) -> int:
    """Convert beats to ticks."""
    return int(round(beats * ppq))


def ticks_to_beats(ticks: int, ppq: int) -> float:
    """Convert ticks to beats."""
    if ppq <= 0:
        raise ValueError(f"ppq must be positive, got {ppq}")
    return ticks / ppq


def parse_position(text: str | float | int, beats_per_bar: float) -> float:
    """Convert a musical position to beats from the start of the song.

    Accepted forms, with `beats_per_bar` set by the project's meter:

    - `1`, `3`: a bar number, so bar 1 is beat 0
    - `3.2`: bar 3, beat 2
    - `3.2.1`: bar 3, beat 2, sixteenth 1
    - `3.2.50%`: halfway through bar 3 beat 2
    - `b7`: seven beats, no bar arithmetic

    Args:
        text: The position. A bare number is a bar number, which is the form a
            producer uses most.
        beats_per_bar: From the project's meter. In 3/4 this is 3.0, and in 6/8 it
            is 3.0 as well, because six eighth notes are three quarter notes.

    Returns:
        Beats from the start of the song, as a float.

    Raises:
        ValueError: If the text is not a recognised form, or names a bar or beat
            below 1.
    """
    if beats_per_bar <= 0:
        raise ValueError(f"beats_per_bar must be positive, got {beats_per_bar}")

    if isinstance(text, (int, float)):
        # A number is a bar number, and 4.0 means bar 4 rather than bar 4 beat 0.
        value = float(text)
        if value != int(value):
            raise ValueError(
                f"Position {text!r} is not a whole bar number. Write bar.beat, for "
                "example 4.2, if you meant a beat within a bar."
            )
        text = str(int(value))

    raw = str(text).strip()
    if not raw:
        raise ValueError("Position is empty")

    if raw.lower().startswith(BEATS_PREFIX):
        return _positive_float(raw[1:], "beats")

    if raw.endswith("%"):
        # The percentage applies to the last unit named, which is a beat when the
        # form is bar.beat.percent%.
        body = raw[:-1]
        parts = body.split(".")
        if len(parts) < 2:
            raise ValueError(
                f"Position {text!r} uses a percentage without a beat, so there is "
                "nothing to take a percentage of"
            )
        bar_text, beat_text = parts[0], parts[1]
        percent_text = ".".join(parts[2:]) if len(parts) > 2 else None
        if not percent_text:
            raise ValueError(f"Position {text!r} is missing its percentage")
        bar, beat = _bar_and_beat(bar_text, beat_text)
        percent = _positive_float(percent_text, "percentage")
        if percent > 100:
            raise ValueError(f"percentage {percent} is above 100")
        return (bar - 1) * beats_per_bar + (beat - 1) + percent / 100.0

    parts = raw.split(".")
    if len(parts) == 1:
        bar = _positive_int(parts[0], "bar")
        return (bar - 1) * beats_per_bar

    if len(parts) > 3:
        raise ValueError(
            f"Position {text!r} has too many parts. Use bar.beat.sixteenth or "
            "bar.beat.percent%"
        )

    bar, beat = _bar_and_beat(parts[0], parts[1])
    position = (bar - 1) * beats_per_bar + (beat - 1)
    if len(parts) == 3:
        position += _fraction(parts[2])
    return position


def format_position(beats: float, beats_per_bar: float) -> str:
    """The musical position of a beat count, as bar.beat.

    The inverse of the simple forms of `parse_position`, so a caller can read a
    position back in the terms it was given.
    """
    if beats_per_bar <= 0:
        raise ValueError(f"beats_per_bar must be positive, got {beats_per_bar}")
    bar = int(beats // beats_per_bar) + 1
    beat = beats - (bar - 1) * beats_per_bar + 1
    if abs(beat - round(beat)) < 1e-9:
        return f"{bar}.{int(round(beat))}"
    return f"{bar}.{beat:.3f}".rstrip("0").rstrip(".")


def _positive_int(text: str, name: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise ValueError(f"{name} {text!r} is not a whole number") from None
    if value < 1:
        raise ValueError(f"{name} {value} is below 1, and counting starts at 1")
    return value


def _positive_float(text: str, name: str) -> float:
    try:
        value = float(text)
    except ValueError:
        raise ValueError(f"{name} {text!r} is not a number") from None
    if value < 0:
        raise ValueError(f"{name} {value} is negative")
    return value


def _bar_and_beat(bar_text: str, beat_text: str) -> tuple[int, int]:
    return _positive_int(bar_text, "bar"), _positive_int(beat_text, "beat")


def _fraction(text: str) -> float:
    """A sixteenth within a beat, as a fraction of the beat.

    Sixteenths are counted from 1, so sixteenth 1 is the start of the beat and
    sixteenth 3 is halfway through it, which is how a step sequencer numbers them.
    """
    step = _positive_int(text, "sixteenth")
    if step > 64:
        raise ValueError(f"sixteenth {step} is beyond any usable subdivision")
    return (step - 1) / 4.0


def _last(parts: list[str]) -> str:
    return parts[-1]
