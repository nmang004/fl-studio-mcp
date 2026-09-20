"""Read a song's structure as arithmetic over markers and pattern lengths.

Every observation this module makes is arithmetic. "The last section is four bars
and the others are sixteen" is a fact, and a fact is all this module is allowed to
report. "The chorus is too short" is taste, and this tool has none, so nothing here
prefers one shape of song to another: a finding says what was counted, and where,
and the producer decides whether it matters.

Two units meet here and they are not the same one. `patterns.getPatternLength`
returns a length in beats, which the stub says in as many words
(`patterns/__properties.py:152-165`), so a pattern length is taken as beats and
never divided by the timebase: sixteen beats read as sixteen ticks would report a
four bar pattern as a sixteenth of a bar. A marker's time is in ticks because it
sits on the transport's timeline, so it is divided by the PPQ and then by the meter.

The meter is an argument rather than a four. Four bars of 3/4 is twelve beats, which
is the kind of arithmetic that has been wrong in this project before, so every
function takes `beats_per_bar` and the tests pin 3/4 beside 4/4.
"""

from __future__ import annotations

from typing import Any

from fl_studio_mcp.musical import time as musical_time
from fl_studio_mcp.musical.analysis import INFORMATIONAL, PROBLEM

# The timebase this project has been observed at, used only when a caller supplied
# no reading. Live FL Studio 2026 reports 96 through system.getPpq.
DEFAULT_PPQ = 96

# The meter assumed when a context carries none. Four is FL's default and the most
# common meter, and the summary says when it was assumed rather than measured.
DEFAULT_BEATS_PER_BAR = 4.0

# Four bars is what a loop most often is, so it is the block a pattern length is
# measured against. It is a fraction of the meter, never a bare sixteen.
FOUR_BAR_BLOCKS = 4.0

# Float division noise, not sloppy placement. A marker half a tick off a bar line is
# a real finding and stays one.
TOLERANCE = 1e-9


def sections(markers: list[dict], ppq: int, beats_per_bar: float) -> list[dict]:
    """Turn markers into sections, each measured to the next marker.

    Args:
        markers: Entries with a name and a time in ticks, as `arrangement.getMarkers`
            returns them. A time of None means FL did not report one, which is what
            the controller's reader gives today: the API can read a marker's name
            and has no function that reads its time, so a section with no time
            reports None rather than a guess.
        ppq: Ticks per quarter note, from `system.getPpq`. 96 on live FL Studio.
        beats_per_bar: From the project's meter. A 4/4 bar is 4.0 and a 3/4 bar is
            3.0, and a 6/8 bar is 3.0 because six eighths are three quarters.

    Returns:
        One entry per marker, in timeline order, each with name, start_bar,
        length_bars, ticks and on_bar_line. The last marker has no next marker to
        measure to, so its length is None rather than zero: an open section is not a
        section of no length.
    """
    _require_timebase(ppq, beats_per_bar)
    ordered = _in_timeline_order(markers)
    result = []
    for position, marker in enumerate(ordered):
        ticks = _tick(marker.get("time"))
        beats = musical_time.ticks_to_beats(ticks, ppq) if ticks is not None else None
        following = None
        if position + 1 < len(ordered):
            following = _tick(ordered[position + 1].get("time"))
        result.append({
            "name": marker.get("name"),
            "start_bar": _bar_of(beats, beats_per_bar),
            "length_bars": _length_bars(ticks, following, ppq, beats_per_bar),
            "ticks": ticks,
            "on_bar_line": _on_bar_line(beats, beats_per_bar),
        })
    return result


def pattern_report(patterns: list[dict], ppq: int, beats_per_bar: float) -> list[dict]:
    """Each pattern's length, in beats, in bars, and against a four bar block.

    Args:
        patterns: Entries from `patterns.getAll`. The length is in beats, because
            that is what `patterns.getPatternLength` returns, so it is never
            converted from ticks.
        ppq: Ticks per quarter note. Used for the tick count reported beside the
            beat count, so the reply shows one length in both units instead of
            leaving a caller to do the multiplication and get it wrong.
        beats_per_bar: From the project's meter.

    Returns:
        One entry per pattern, each with index, name, length_beats, length_bars,
        length_ticks and divides_into_four_bar_blocks. A pattern whose length FL did
        not report has None in the measured fields rather than a zero, because an
        unreadable length is not a length of nothing.
    """
    _require_timebase(ppq, beats_per_bar)
    block = FOUR_BAR_BLOCKS * beats_per_bar
    result = []
    for pattern in patterns:
        beats = _number(pattern.get("length"))
        result.append({
            "index": pattern.get("index"),
            "name": pattern.get("name"),
            "length_beats": beats,
            "length_bars": round(beats / beats_per_bar, 6) if beats is not None else None,
            "length_ticks": (
                musical_time.beats_to_ticks(beats, ppq) if beats is not None else None
            ),
            "divides_into_four_bar_blocks": (
                _is_whole(beats / block) if beats is not None else None
            ),
        })
    return result


def critique(context: dict, patterns: list[dict], markers: list[dict]) -> dict:
    """Sections, pattern lengths, and every arithmetic observation about them.

    Args:
        context: The project context. `beats_per_bar` and `ppq` drive the
            arithmetic, and `key`, `time_signature` and `meter_read` are carried
            into the summary so a caller can see what the numbers were measured
            against.
        patterns: Entries from `patterns.getAll`, whose length is in beats.
        markers: Entries from `arrangement.getMarkers`, whose time is in ticks when
            FL reports one and None when it does not.

    Returns:
        sections, patterns, observations and summary, with the problems first. One
        observation per fact: a marker off the bar line and the section it ends are
        two ways of stating one placement, so both appear and neither is hidden.
    """
    beats_per_bar = _meter(context.get("beats_per_bar"))
    ppq = _timebase(context.get("ppq"))
    signature = _signature(context, beats_per_bar)
    section_list = sections(markers, ppq, beats_per_bar)
    pattern_list = pattern_report(patterns, ppq, beats_per_bar)

    problems: list[dict] = []
    informational: list[dict] = []

    if not markers:
        informational.append({
            "kind": "no_structure",
            "severity": INFORMATIONAL,
            "detail": (
                "The arrangement has no markers, so there is no structure to read. "
                "Until some are placed this report covers pattern lengths only."
            ),
        })
    else:
        unreadable = [entry for entry in markers if _tick(entry.get("time")) is None]
        if unreadable:
            informational.append({
                "kind": "marker_times_unreadable",
                "severity": INFORMATIONAL,
                "detail": (
                    f"FL reported {len(unreadable)} of {len(markers)} marker name(s) "
                    "without a time, so those sections have no measured start or "
                    "length. The controller reads a marker's name through "
                    "arrangement.getMarkerName, and the API has no function that "
                    "reads its time."
                ),
            })

    for section in section_list:
        if section["on_bar_line"] is False:
            problems.append(_off_bar_line(section, ppq, beats_per_bar, signature))

    for section in section_list:
        length = section["length_bars"]
        if length is None or _is_whole(length):
            continue
        problems.append({
            "kind": "section_not_whole_bars",
            "severity": PROBLEM,
            "section": section["name"],
            "detail": (
                f"The section {section['name']!r} spans {_number_text(length)} bars, "
                "measured from its marker to the next one, which is not a whole "
                "number of bars."
            ),
        })

    for pattern in pattern_list:
        beats = pattern["length_beats"]
        if beats is None:
            informational.append({
                "kind": "pattern_length_unreadable",
                "severity": INFORMATIONAL,
                "pattern": pattern["index"],
                "detail": (
                    f"FL reported no length for pattern {pattern['name'] or pattern['index']}, "
                    "so its length is unknown rather than zero."
                ),
            })
            continue
        if pattern["divides_into_four_bar_blocks"]:
            continue
        label = pattern["name"] or f"pattern {pattern['index']}"
        informational.append({
            "kind": "pattern_not_four_bar_blocks",
            "severity": INFORMATIONAL,
            "pattern": pattern["index"],
            "name": pattern["name"],
            "detail": (
                f"{label} is {_number_text(beats)} beats, which is "
                f"{_number_text(pattern['length_bars'])} bars in {signature}. That is "
                "not a whole number of four bar blocks, which is arithmetic about "
                "its length rather than a fault in it."
            ),
        })

    informational.extend(_last_section_differs(section_list))
    if context.get("meter_read") is False:
        informational.insert(0, {
            "kind": "meter_assumed",
            "severity": INFORMATIONAL,
            "detail": (
                "The meter could not be read, so bars here are counted in "
                f"{signature}, which is an assumption rather than a measurement. The "
                "meter lives on score.tsnum and score.tsden in the piano roll's own "
                "sandbox, and the controller cannot reach them."
            ),
        })

    return {
        "sections": section_list,
        "patterns": pattern_list,
        "observations": problems + informational,
        "summary": {
            "problem_count": len(problems),
            "informational_count": len(informational),
            "marker_count": len(markers),
            "section_count": len(section_list),
            "pattern_count": len(pattern_list),
            "beats_per_bar": beats_per_bar,
            "time_signature": signature,
            "key": context.get("key"),
            "note": (
                "Every observation is arithmetic over the marker times and pattern "
                "lengths FL reported. None of it is a judgement about the song."
            ),
        },
    }


def _off_bar_line(section: dict, ppq: int, beats_per_bar: float, signature: str) -> dict:
    """The finding for a marker whose time is not a whole number of bars."""
    ticks = section["ticks"]
    bar_ticks = beats_per_bar * ppq
    return {
        "kind": "marker_off_bar_line",
        "severity": PROBLEM,
        "section": section["name"],
        "detail": (
            f"The marker {section['name']!r} starts at {_number_text(ticks)} ticks, "
            f"and a bar of {signature} at {ppq} PPQ is {_number_text(bar_ticks)} "
            f"ticks, so it falls {_number_text(ticks % bar_ticks)} ticks after the "
            f"bar line at bar {section['start_bar']}."
        ),
    }


def _last_section_differs(section_list: list[dict]) -> list[dict]:
    """The last measured section beside the others, when the others all agree.

    This is the fact the module docstring uses as its example: "the last section is
    four bars and the others are sixteen". It is only said when every earlier
    section really does share one length, because otherwise there is no single
    number to compare the last one against.
    """
    measured = [section for section in section_list if section["length_bars"] is not None]
    if len(measured) < 2:
        return []
    others = [section["length_bars"] for section in measured[:-1]]
    if not all(_is_close(length, others[0]) for length in others[1:]):
        return []
    last = measured[-1]["length_bars"]
    if _is_close(last, others[0]):
        return []
    return [{
        "kind": "last_section_differs",
        "severity": INFORMATIONAL,
        "section": measured[-1]["name"],
        "detail": (
            f"The last measured section is {_number_text(last)} bars and the other "
            f"{len(others)} are {_number_text(others[0])} bars."
        ),
    }]


def _in_timeline_order(markers: list[dict]) -> list[dict]:
    """Markers in timeline order when every time is known, otherwise as given.

    The controller returns markers in index order, which is placement order and is
    not necessarily timeline order once a marker has been dragged earlier. Sorting
    needs a time to sort on, so a set with an unreadable time is left as it arrived
    rather than rearranged on a guess.
    """
    entries = list(markers)
    if entries and all(_tick(entry.get("time")) is not None for entry in entries):
        return sorted(entries, key=lambda entry: _tick(entry.get("time")))
    return entries


def _length_bars(
    ticks: int | None, following: int | None, ppq: int, beats_per_bar: float
) -> float | None:
    """How many bars a section spans, or None when either end is unreadable."""
    if ticks is None or following is None:
        return None
    return round((following - ticks) / ppq / beats_per_bar, 6)


def _bar_of(beats: float | None, beats_per_bar: float) -> int | None:
    """The bar a beat position falls in, where bar 1 starts at beat 0."""
    if beats is None:
        return None
    return int(beats // beats_per_bar) + 1


def _on_bar_line(beats: float | None, beats_per_bar: float) -> bool | None:
    """Whether a beat position is a whole number of bars into the song."""
    if beats is None:
        return None
    return _is_whole(beats / beats_per_bar)


def _tick(value: Any) -> int | None:
    """A marker time in ticks, or None when FL did not report one."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _number(value: Any) -> float | None:
    """A number, or None when the value is not one."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _meter(value: Any) -> float:
    """Beats per bar, falling back to four when the reading is missing or unusable."""
    meter = _number(value)
    if meter is None or meter <= 0:
        return DEFAULT_BEATS_PER_BAR
    return meter


def _timebase(value: Any) -> int:
    """Ticks per quarter note, falling back to the observed default."""
    ppq = _tick(value)
    if ppq is None or ppq <= 0:
        return DEFAULT_PPQ
    return ppq


def _signature(context: dict, beats_per_bar: float) -> str:
    """The meter as a name, falling back to what the arithmetic actually used."""
    name = context.get("time_signature")
    if name:
        return str(name)
    return f"{_number_text(beats_per_bar)}/4"


def _is_whole(value: float) -> bool:
    return abs(value - round(value)) < TOLERANCE


def _is_close(first: float, second: float) -> bool:
    return abs(first - second) < TOLERANCE


def _number_text(value: float) -> str:
    """A number for a sentence, without a trailing decimal point or a fake precision."""
    if _is_whole(value):
        return str(int(round(value)))
    return f"{value:.3f}".rstrip("0").rstrip(".")


def _require_timebase(ppq: int, beats_per_bar: float) -> None:
    """Refuse a timebase that cannot measure anything, as musical/time.py does."""
    if ppq <= 0:
        raise ValueError(f"ppq must be positive, got {ppq}")
    if beats_per_bar <= 0:
        raise ValueError(f"beats_per_bar must be positive, got {beats_per_bar}")
