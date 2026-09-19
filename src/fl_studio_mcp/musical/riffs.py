"""Riffs: a phrase plus what makes it findable, and how to move it into another key.

A riff is captured from a piano roll, so it carries the notes exactly as they were,
including the expression flags that make a 303 line a 303 line. Flattening those on the
way in would make the library a collection of transcriptions rather than of the
producer's own playing.

Everything here is arithmetic over dictionaries. Matching, transposing and clamping are
the decisions a recall makes, and they are all testable with no FL Studio and no library
directory: the disk work lives in `utils/store.py` and the tool layer.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

# Bumped when the shape changes in a way an older reader would misread.
SCHEMA = 1

# The state export carries tick aliases beside the beat values. The piano roll script
# reads beats and ignores ticks, and a stale tick value in a request would be a trap
# for anyone reading the request file, so a recall leaves them out.
_TICK_ALIASES = ("time_ticks", "length_ticks")

# The MIDI range a note can be clamped into. Not an FL Studio claim: the stubs document
# no range for a note number, and 0 to 127 is where every MIDI tool agrees.
LOWEST_NOTE = 0
HIGHEST_NOTE = 127

_DIRECTIONS = ("nearest", "up", "down")


def make_riff(
    name: str,
    notes: list[dict[str, Any]],
    *,
    context: dict[str, Any] | None = None,
    instrument: str | None = None,
    tags: list[str] | tuple[str, ...] = (),
    mood: str | None = None,
    when: datetime | None = None,
    source: dict[str, Any] | None = None,
    record_id: str | None = None,
) -> dict[str, Any]:
    """Build a record from a piano roll state, a project context and some tags.

    Args:
        name: What the producer calls it.
        notes: The notes as the piano roll exported them, expression and all.
        context: The project context, used for the key, the meter and the PPQ.
        instrument: The channel or plugin it came from, which is how it is found again.
        tags: Free labels, matched case-insensitively.
        mood: One more label, kept separate because producers use it separately.
        when: When it was captured. Defaults to now.
        source: Where it came from, for provenance.
        record_id: The library id, which the store chooses because it has to be unique
            across the library rather than only within this record.

    Returns:
        A record with a schema number, a timestamp, the key when the project has one
        and the length in beats.
    """
    moment = when or datetime.now()
    context = context or {}
    ppq = context.get("ppq") or 96
    copied = [dict(note) for note in notes]

    return {
        "schema": SCHEMA,
        "id": record_id,
        "created": moment.astimezone().isoformat() if moment.tzinfo else moment.isoformat(),
        "name": name,
        "tags": [str(tag) for tag in tags],
        "mood": mood,
        "instrument": instrument,
        "notes": copied,
        "note_count": len(copied),
        "length_beats": length_beats(copied, ppq),
        "key": _key_of(context),
        "meter": {"tsnum": context.get("tsnum") or 4, "tsden": context.get("tsden") or 4},
        "tempo": context.get("tempo"),
        "ppq": ppq,
        "source": source or {},
    }


def length_beats(notes: list[dict[str, Any]], ppq: int = 96) -> float:
    """How long the phrase is, from the start to the end of the last note."""
    end = 0.0
    for note in notes:
        start = float(note.get("time") or 0.0)
        duration = float(note.get("duration") or 0.0)
        end = max(end, start + duration)
    return round(end, 6)


def match(
    record: dict[str, Any],
    query: str | None = None,
    tags: list[str] | tuple[str, ...] = (),
    key: str | None = None,
    instrument: str | None = None,
    min_notes: int | None = None,
) -> bool:
    """Whether a record answers a search.

    Every filter given has to pass, and a filter that was not given does not narrow
    anything. An empty tag list therefore matches everything, which is what a caller
    who did not ask about tags means.
    """
    if query:
        needle = query.strip().lower()
        haystack = [
            str(record.get("name") or ""),
            str(record.get("mood") or ""),
            str(record.get("instrument") or ""),
            *[str(tag) for tag in record.get("tags") or []],
            *_key_names(record),
        ]
        if not any(needle in field.lower() for field in haystack):
            return False

    if tags:
        present = {str(tag).lower() for tag in record.get("tags") or []}
        for tag in tags:
            if str(tag).lower() not in present:
                return False

    if key:
        wanted = key.strip().lower()
        names = [name.lower() for name in _key_names(record)]
        if not any(wanted == name or wanted in name for name in names):
            return False

    if instrument:
        needle = instrument.strip().lower()
        fields = [str(record.get("instrument") or "")]
        source = record.get("source") or {}
        fields.extend(str(source.get(fieldname) or "") for fieldname in ("plugin", "channel_name"))
        if not any(needle in field.lower() for field in fields):
            return False

    if min_notes is not None and int(record.get("note_count") or 0) < int(min_notes):
        return False

    return True


def search(
    records: list[dict[str, Any]],
    *,
    query: str | None = None,
    tags: list[str] | tuple[str, ...] = (),
    key: str | None = None,
    instrument: str | None = None,
    min_notes: int | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """The records that match, newest first."""
    found = [
        record
        for record in records
        if match(
            record,
            query=query,
            tags=tags,
            key=key,
            instrument=instrument,
            min_notes=min_notes,
        )
    ]
    found.sort(
        key=lambda record: str(record.get("created") or record.get("id") or ""),
        reverse=True,
    )
    if limit is not None and limit >= 0:
        found = found[:limit]
    return found


def transpose_semitones(from_root: int, to_root: int, direction: str = "nearest") -> int:
    """How far to move a phrase written in one key so it sits in another.

    Only the pitch class matters: moving from A to C is moving by the interval
    between those roots, whatever octave either one was written in.

    Args:
        from_root: The riff's root note, 0 to 11 with C as 0.
        to_root: The project's root note, same numbering.
        direction: "nearest" takes the shorter way and never moves more than six
            semitones, so a phrase does not leap an octave to reach a neighbouring
            key. "up" and "down" force the long way, which is sometimes wanted for
            register rather than for harmony.

    Returns:
        The semitone offset, which may be negative.
    """
    if direction not in _DIRECTIONS:
        raise ValueError(
            f"direction must be one of {_DIRECTIONS}, got {direction!r}"
        )
    difference = (int(to_root) - int(from_root)) % 12
    if direction == "up":
        return difference
    if direction == "down":
        return difference - 12 if difference else 0
    if difference > 6:
        return difference - 12
    return difference


def transpose_notes(
    notes: list[dict[str, Any]],
    semitones: int,
    low: int = LOWEST_NOTE,
    high: int = HIGHEST_NOTE,
) -> tuple[list[dict[str, Any]], int]:
    """Move every note, clamping the ones that would leave the range.

    Clamped rather than dropped, and counted rather than silent. A note pushed off the
    top of the range is a musical event the caller should know about: it means the
    transposition asked for more room than the instrument has.

    Returns:
        The moved notes, and how many were clamped.
    """
    moved = []
    clamped = 0
    for note in notes:
        entry = dict(note)
        original = int(entry.get("midi") or 0)
        target = original + int(semitones)
        if target < low:
            target = low
            clamped += 1
        elif target > high:
            target = high
            clamped += 1
        entry["midi"] = target
        # The state export carries `number` as an alias of `midi`. Leaving it at its
        # old value would make the record contradict itself.
        if "number" in entry:
            entry["number"] = target
        moved.append(entry)
    return moved, clamped


def recall_notes(
    record: dict[str, Any], semitones: int = 0
) -> tuple[list[dict[str, Any]], int]:
    """The notes to send to the piano roll, moved and stripped of tick aliases."""
    moved, clamped = transpose_notes(record.get("notes") or [], semitones)
    cleaned = [
        {key: value for key, value in note.items() if key not in _TICK_ALIASES}
        for note in moved
    ]
    return cleaned, clamped


def summarise(record: dict[str, Any]) -> dict[str, Any]:
    """A record without its notes, so a search result can be read cheaply."""
    source = record.get("source") or {}
    return {
        "id": record.get("id"),
        "name": record.get("name"),
        "tags": record.get("tags") or [],
        "mood": record.get("mood"),
        "instrument": record.get("instrument") or source.get("plugin"),
        "channel": source.get("channel"),
        "channel_name": source.get("channel_name"),
        "key": (record.get("key") or {}).get("name"),
        "root_note": (record.get("key") or {}).get("root"),
        "meter": _meter_text(record.get("meter")),
        "tempo": record.get("tempo"),
        "note_count": record.get("note_count"),
        "length_beats": record.get("length_beats"),
        "created": record.get("created"),
    }


def _key_of(context: dict[str, Any]) -> dict[str, Any] | None:
    """The key, or None when the project has not declared one.

    Snap to scale off means FL reports no scale at all. Naming C major there would be
    an invention, and it would make every riff captured in such a project look like it
    was in C.
    """
    if not context.get("scale_set"):
        return None
    root = context.get("root_note")
    if root is None:
        return None
    return {
        "root": int(root),
        "name": context.get("key") or _pitch_class_name(int(root)),
        "scale_helper": context.get("scale_helper"),
    }


def _key_names(record: dict[str, Any]) -> list[str]:
    """Every string a key filter might reasonably be written as."""
    key = record.get("key") or {}
    if not key:
        return []
    names = [str(key.get("name") or "")]
    root = key.get("root")
    if root is not None:
        names.append(_pitch_class_name(int(root)))
    return [name for name in names if name]


def _pitch_class_name(root: int) -> str:
    names = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
    return names[int(root) % 12]


def _meter_text(meter: dict[str, Any] | None) -> str | None:
    if not meter:
        return None
    return f"{meter.get('tsnum')}/{meter.get('tsden')}"
