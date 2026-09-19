"""Read the few fields an .flp index needs, and refuse to guess the rest.

An index of somebody's project folder has to answer "which sketch was the 130 BPM one"
without opening FL Studio, and the .flp container holds just enough to do that. The
measurements behind this reader are in docs/spikes/2026-09-19-flp-format.md, and two of
them decide its shape.

The event size rule published in the Kaitai spec, and implemented identically by PyFLP,
reads a four byte value for every id from 128 to 191. FL Studio 2026 does not: the 0xAC
event carries three value bytes, so the published rule shifts by one byte and then
re-synchronises on the UTF-16 grid. It still lands on the end of the payload, which is
why the damage is invisible: the walk looks clean and reports no tempo, no title and no
meter. This reader handles that one event by name, and then requires the walk to end
exactly at the end of the payload before it believes any field that came out of it.

The payload is uncompressed and little-endian, scalar events hold their value directly,
and ids from 192 up hold a base-128 length followed by text or a blob. Nothing here
raises on a bad file: a producer's folder holds autosaves, exports and half written
downloads, so a file that is not a project comes back with ok false, a status and a
reason, and no guessed numbers.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, NamedTuple

# The container. Measured on six FL Studio 2026 projects: FLhd, a uint32 header length
# of 6, three uint16s (format, channel count, PPQ), then FLdt and the payload length.
# That length is the file size minus these 22 bytes in every one of them, which is the
# integrity check this reader leans on hardest.
_HEADER_MAGIC = b"FLhd"
_DATA_MAGIC = b"FLdt"
_HEADER_SIZE = 6
_PREAMBLE_SIZE = 22

# Event ids. Each one was read out of a real file, and the value that proves it is
# quoted here: event 156 held 130000, events 17 and 18 held 4 and 4, event 194 held an
# empty UTF-16 string, event 199 held "26.1.6.5406" as single byte text, event 159 held
# 5406, and events 21, 201, 203 and 196 held the five channels, four samplers and one
# FLEX instance of the measured project.
_EVENT_METER_NUMERATOR = 17
_EVENT_METER_DENOMINATOR = 18
_EVENT_CHANNEL_TYPE = 21
_EVENT_TEMPO = 156
_EVENT_BUILD = 159
_EVENT_TITLE = 194
_EVENT_SAMPLE = 196
_EVENT_VERSION = 199
_EVENT_PLUGIN_FACTORY = 201
_EVENT_CHANNEL_NAME = 203

# Ids from 192 up are text or blob events: a base-128 little-endian length, then that
# many bytes. Ids below 192 carry a scalar whose width the id chooses and have nothing
# after it, which is why the tempo event is five bytes long and not nine.
_FIRST_TEXT_EVENT = 192

# The one place the published rule is wrong for FL Studio 2026. It reads four value
# bytes for the 128 to 191 band, which makes this event five bytes and shifts every
# event after it by one. The shift re-synchronises on the UTF-16 grid, so the walk still
# lands on the end of the payload and only the missing fields give it away: the
# published rule reported no tempo, no title and no meter for all five projects it was
# measured on. The 0xAC event carries three value bytes. See
# docs/spikes/2026-09-19-flp-format.md.
_QUIRK_EVENT = 0xAC
_QUIRK_VALUE_WIDTH = 3

# Thousandths of a BPM, guarded. A desynced walk can land on a plausible looking
# integer, and a wrong tempo in an index is worse than a blank one, so a tempo outside
# this range is refused by name rather than reported.
TEMPO_MIN_BPM = 10.0
TEMPO_MAX_BPM = 522.0


class _WalkError(Exception):
    """The event stream ran off the end of the payload, so nothing after it is known."""


class _Walk(NamedTuple):
    """What the event walk found, and whether the walk can be believed."""

    fields: dict[str, Any]
    plugins: list[dict[str, Any]]
    channel_starts: int
    events: int
    landed: bool
    stopped_at: int


def read_flp(path: str | Path) -> dict[str, Any]:
    """Read one project file, and say how much of it was believed.

    The status is one of "ok", "not_a_project", "truncated", "size_mismatch",
    "unexpected_header", "walk_failed" or "unreadable", and ok is true only for the
    first. Everything that came out of the event walk is None whenever the walk did not
    land exactly on the end of the payload, because a desynced walk can produce
    plausible looking numbers and a wrong one in an index is worse than a blank.

    The reply always carries the same keys, so a caller never has to guard a lookup:
    header, version, build, tempo, title, time_signature, plugins, size, modified,
    problems and walk. size and modified come from os.stat, and modified is a Unix
    timestamp, which is what an index sorts on.
    """
    target = Path(path)
    try:
        info = os.stat(target)
    except OSError as error:
        return _result(False, "unreadable", [f"could not read the file's details: {error}"])

    size = info.st_size
    modified = info.st_mtime

    try:
        data = target.read_bytes()
    except OSError as error:
        return _result(
            False,
            "unreadable",
            [f"could not read the file: {error}"],
            size=size,
            modified=modified,
        )

    if not data.startswith(_HEADER_MAGIC):
        return _result(
            False,
            "not_a_project",
            ["the file does not begin with the FLhd magic, so it is not a project"],
            size=size,
            modified=modified,
        )
    if len(data) < _PREAMBLE_SIZE:
        return _result(
            False,
            "truncated",
            [f"the file is {len(data)} bytes, too short for the {_PREAMBLE_SIZE} byte preamble"],
            size=size,
            modified=modified,
        )

    header_size = int.from_bytes(data[4:8], "little")
    if header_size != _HEADER_SIZE:
        return _result(
            False,
            "unexpected_header",
            [
                f"the FLhd chunk declares {header_size} bytes where this reader knows "
                f"{_HEADER_SIZE}"
            ],
            size=size,
            modified=modified,
        )
    if data[14:18] != _DATA_MAGIC:
        return _result(
            False,
            "not_a_project",
            ["the FLhd chunk is not followed by the FLdt data magic"],
            size=size,
            modified=modified,
        )

    declared = int.from_bytes(data[18:22], "little")
    available = len(data) - _PREAMBLE_SIZE
    if declared > available:
        return _result(
            False,
            "truncated",
            [f"the FLdt chunk declares {declared} bytes but only {available} follow it"],
            size=size,
            modified=modified,
        )
    if declared != available:
        return _result(
            False,
            "size_mismatch",
            [
                f"the FLdt chunk declares {declared} bytes but {available} follow the "
                "preamble, so the file is not what it claims"
            ],
            size=size,
            modified=modified,
        )

    header = {
        "format": int.from_bytes(data[8:10], "little"),
        "channels": int.from_bytes(data[10:12], "little"),
        "ppq": int.from_bytes(data[12:14], "little"),
    }

    walk = _walk(data[_PREAMBLE_SIZE:], header["channels"])
    if not walk.landed:
        return _result(
            False,
            "walk_failed",
            [
                f"the event walk stopped at byte {walk.stopped_at} of {available} instead "
                "of the end of the payload, so nothing it read is trusted"
            ],
            header=header,
            size=size,
            modified=modified,
            events=walk.events,
        )

    problems: list[str] = []
    fields = walk.fields

    raw_tempo = fields.get("tempo")
    tempo = None
    if raw_tempo is None:
        problems.append("no tempo event (156) was found, so the tempo is unknown")
    elif not TEMPO_MIN_BPM <= raw_tempo / 1000.0 <= TEMPO_MAX_BPM:
        problems.append(
            f"the tempo event says {raw_tempo / 1000.0} BPM, outside the "
            f"{TEMPO_MIN_BPM:g} to {TEMPO_MAX_BPM:g} BPM this reader trusts, so it was refused"
        )
    else:
        tempo = round(raw_tempo / 1000.0, 3)

    tsnum = fields.get("tsnum")
    tsden = fields.get("tsden")
    time_signature = None
    if tsnum is not None and tsden is not None:
        time_signature = {"tsnum": tsnum, "tsden": tsden}
    elif tsnum is not None or tsden is not None:
        problems.append(
            "only one of the time signature events (17 and 18) was found, so the meter "
            "is unknown"
        )

    version = fields.get("version")
    if version is None:
        problems.append("no version event (199) was found, so the version is unknown")
    raw_build = fields.get("build")
    build = None if raw_build is None else str(raw_build)
    if build is None:
        problems.append("no build event (159) was found, so the build is unknown")

    if walk.channel_starts != header["channels"]:
        problems.append(
            f"the header declares {header['channels']} channels but the walk found "
            f"{walk.channel_starts} channel starts"
        )

    return _result(
        True,
        "ok",
        problems,
        header=header,
        version=version,
        build=build,
        tempo=tempo,
        title=fields.get("title"),
        time_signature=time_signature,
        plugins=walk.plugins,
        size=size,
        modified=modified,
        events=walk.events,
        landed=True,
    )


def _walk(payload: bytes, channel_count: int) -> _Walk:
    """Walk every event in the payload and collect the fields an index needs.

    Each field is taken from the first event that carries it: FL writes the project's
    tempo and meter once near the front, and anything later is automation. A channel
    opens at a channel type event (21) and the identity events that follow belong to it,
    but only the first of each is recorded, because a real project carries a mixer
    effect's factory event after the last channel's events.
    """
    fields: dict[str, Any] = {}
    channels: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    channel_starts = 0
    index = 0
    events = 0
    landed = True
    try:
        while index < len(payload):
            event_id = payload[index]
            index += 1
            body: bytes | None = None
            value: int | None = None
            if event_id >= _FIRST_TEXT_EVENT:
                size, index = _read_varint(payload, index)
                if index + size > len(payload):
                    raise _WalkError
                body = payload[index : index + size]
                index += size
            else:
                width = _value_width(event_id)
                if index + width > len(payload):
                    raise _WalkError
                value = int.from_bytes(payload[index : index + width], "little")
                index += width
            events += 1

            if body is not None:
                if event_id == _EVENT_TITLE and "title" not in fields:
                    fields["title"] = _utf16_text(body)
                elif event_id == _EVENT_VERSION and "version" not in fields:
                    fields["version"] = _version_text(body)
                elif current is not None:
                    _record_channel(current, event_id, body)
            elif event_id == _EVENT_CHANNEL_TYPE:
                channel_starts += 1
                if len(channels) < channel_count:
                    current = {"type": value}
                    channels.append(current)
                else:
                    # More channel starts than the header declares. The header is FL's
                    # own count, so the extras are not channels this reader can name.
                    current = None
            elif event_id == _EVENT_TEMPO and "tempo" not in fields:
                fields["tempo"] = value
            elif event_id == _EVENT_BUILD and "build" not in fields:
                fields["build"] = value
            elif event_id == _EVENT_METER_NUMERATOR and "tsnum" not in fields:
                fields["tsnum"] = value
            elif event_id == _EVENT_METER_DENOMINATOR and "tsden" not in fields:
                fields["tsden"] = value
    except _WalkError:
        landed = False

    plugins = [
        {
            "name": channel.get("name") or "",
            "factory": channel.get("factory") or None,
            "type": channel.get("type"),
            "sample": channel.get("sample") or None,
        }
        for channel in channels
    ]
    return _Walk(fields, plugins, channel_starts, events, landed, index)


def _record_channel(channel: dict[str, Any], event_id: int, body: bytes) -> None:
    """Attach one identity event to a channel, first one wins.

    The first-wins rule is measured, not cautious: a real project carries the mixer
    effect's factory event ("Emphasizer") after the last channel's events, so a reader
    that let the last value win would report the FLEX channel as an effect.
    """
    if event_id == _EVENT_CHANNEL_NAME and "name" not in channel:
        channel["name"] = _utf16_text(body)
    elif event_id == _EVENT_PLUGIN_FACTORY and "factory" not in channel:
        channel["factory"] = _utf16_text(body)
    elif event_id == _EVENT_SAMPLE and "sample" not in channel:
        channel["sample"] = _utf16_text(body)


def _value_width(event_id: int) -> int:
    """How many bytes a scalar event's value takes.

    One byte below 64, two below 128, four below 192, with the single measured
    exception documented on _QUIRK_EVENT. An id from 192 up carries a length instead of
    a value and never reaches here.
    """
    if event_id < 64:
        return 1
    if event_id < 128:
        return 2
    if event_id == _QUIRK_EVENT:
        return _QUIRK_VALUE_WIDTH
    return 4


def _read_varint(payload: bytes, index: int) -> tuple[int, int]:
    """Read a base-128 little-endian length, or raise when the payload runs out."""
    value = 0
    shift = 0
    while True:
        if index >= len(payload):
            raise _WalkError
        byte = payload[index]
        index += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, index
        shift += 7
        if shift > 63:
            raise _WalkError


def _utf16_text(payload: bytes) -> str:
    """A UTF-16LE string, up to its NUL terminator.

    The payload uses UTF-16LE for its text, so this is what the title, the channel names
    and the sample paths are decoded with. Replacement rather than an exception, because
    a mangled title must not cost the caller the rest of the file.
    """
    return payload.decode("utf-16-le", "replace").split("\x00", 1)[0].strip()


def _single_byte_text(payload: bytes) -> str:
    """A one byte per character string, up to its NUL terminator.

    The version event is written this way rather than as UTF-16: measured, its payload
    is 12 bytes holding "26.1.6.5406" and a terminator, and reading those bytes as UTF-16
    produces mojibake rather than a version number.
    """
    return payload.decode("latin-1").split("\x00", 1)[0].strip()


def _version_text(payload: bytes) -> str:
    """The version event's text, whichever of the two encodings it turns out to use.

    Every measured file writes it as single byte text, so that is the default. A UTF-16
    payload is detected rather than decoded into mojibake, because a version is printed
    in an index and has to be readable.
    """
    if len(payload) % 2 == 0 and payload[1::2] == b"\x00" * (len(payload) // 2):
        return _utf16_text(payload)
    return _single_byte_text(payload)


def _result(
    ok: bool,
    status: str,
    problems: list[str],
    *,
    header: dict[str, Any] | None = None,
    version: str | None = None,
    build: str | None = None,
    tempo: float | None = None,
    title: str | None = None,
    time_signature: dict[str, int] | None = None,
    plugins: list[dict[str, Any]] | None = None,
    size: int | None = None,
    modified: float | None = None,
    events: int = 0,
    landed: bool = False,
) -> dict[str, Any]:
    """Every field a caller may read, present on every path out of this module.

    A caller that has to check whether a key exists will get it wrong once, so a refused
    file carries the same keys with None in them. plugins stays a list, because "no
    channels were read" is an empty list and not an unknown.
    """
    return {
        "ok": ok,
        "status": status,
        "problems": problems,
        "header": header,
        "version": version,
        "build": build,
        "tempo": tempo,
        "title": title,
        "time_signature": time_signature,
        "plugins": plugins if plugins is not None else [],
        "size": size,
        "modified": modified,
        "walk": {"events": events, "landed": landed},
    }
