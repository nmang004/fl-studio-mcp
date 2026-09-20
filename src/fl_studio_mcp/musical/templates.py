"""Template specs as plain data, validated before anything is planned.

A template here is data rather than code: mixer tracks with a name, a colour and the
sends they feed, playlist lanes with a name and a colour, and markers with the bar
they fall on. The built-in catalogue stays readable that way, and a producer's own
spec is a thing they can write without reading this module.

What a template cannot do is load an instrument. `plugins` has no load function and
`channels` has no add function, so an insert a template names is an insert with a
name and nothing playing into it. The reply lists those inserts rather than implying
that the template made a sound.

Validation happens before anything is planned, and a spec that fails it plans
nothing. A half-applied template is worse than one that never ran, because the
producer cannot tell which half took effect.

A target is only touched when the spec names it and it still carries FL's generated
name. Those names are the ones this project has measured: a mixer insert nobody has
renamed is "Insert N", and a playlist lane is "Track N" (`_is_placeholder_track_name`
in the controller, measured on live FL Studio 2026). A Channel Rack channel's
generated name has not been measured, so a spec that names a channel is only planned
with `overwrite`, which is the safe direction: skipping is recoverable, renaming
somebody's work is not.
"""

from __future__ import annotations

from typing import Any

# FL's own names for objects nobody has touched. Kept beside the rule that reads
# them, so the two cannot drift apart.
INSERT_NAME = "Insert {index}"
LANE_NAME = "Track {index}"

# The bar a marker is placed on becomes ticks through the project's PPQ and meter,
# both of which the controller reports. Neither has a default here: a marker placed
# from an assumed meter is silently in the wrong place.
MAX_COLOR = 0xFFFFFF

_TOP_LEVEL_FIELDS = frozenset({"description", "tracks", "lanes", "channels", "markers"})
_TRACK_FIELDS = frozenset({"track", "name", "color", "sends"})
_LANE_FIELDS = frozenset({"lane", "name", "color"})
_CHANNEL_FIELDS = frozenset({"channel", "name", "color"})
_MARKER_FIELDS = frozenset({"bar", "name"})

_MIXING: dict[str, Any] = {
    "description": (
        "Name and colour eight mixer inserts and send six of them into two returns, "
        "one reverb and one delay. Tracks 1 to 6 are the sources and 7 and 8 are the "
        "returns they feed."
    ),
    "tracks": [
        {"track": 1, "name": "Drums", "color": 0xE15759, "sends": [7]},
        {"track": 2, "name": "Bass", "color": 0x4E79A7, "sends": []},
        {"track": 3, "name": "Keys", "color": 0x59A14F, "sends": [7, 8]},
        {"track": 4, "name": "Lead", "color": 0xF28E2B, "sends": [7, 8]},
        {"track": 5, "name": "Pads", "color": 0xB07AA1, "sends": [7, 8]},
        {"track": 6, "name": "Vocals", "color": 0xEDC948, "sends": [7, 8]},
        {"track": 7, "name": "Reverb", "color": 0x76B7B2, "sends": []},
        {"track": 8, "name": "Delay", "color": 0x9C755F, "sends": []},
    ],
}

_SECTIONS: dict[str, Any] = {
    "description": (
        "Place eight bar markers for a conventional song: an intro, two verses, "
        "three choruses, a bridge and an outro, each on its own bar line."
    ),
    "markers": [
        {"bar": 1, "name": "Intro"},
        {"bar": 9, "name": "Verse 1"},
        {"bar": 17, "name": "Chorus 1"},
        {"bar": 25, "name": "Verse 2"},
        {"bar": 33, "name": "Chorus 2"},
        {"bar": 41, "name": "Bridge"},
        {"bar": 49, "name": "Chorus 3"},
        {"bar": 57, "name": "Outro"},
    ],
}

TEMPLATES: dict[str, dict] = {
    "mixing": _MIXING,
    "sections": _SECTIONS,
}


def catalogue() -> list[dict]:
    """Every built-in template, with what it does and how much it touches.

    The counts are what the spec names, not what a particular project would accept:
    a track that is already named by the producer is skipped, so the reply to an
    application is the place to read what actually happened.
    """
    entries = []
    for name, spec in TEMPLATES.items():
        tracks = spec.get("tracks") or []
        lanes = spec.get("lanes") or []
        channels = spec.get("channels") or []
        markers = spec.get("markers") or []
        entries.append({
            "name": name,
            "description": spec.get("description") or "",
            "objects": len(tracks) + len(lanes) + len(channels) + len(markers),
            "touches": {
                "mixer_tracks": len(tracks),
                "playlist_lanes": len(lanes),
                "channels": len(channels),
                "markers": len(markers),
            },
            "loads_instruments": False,
        })
    return entries


def validate(
    spec: dict,
    track_count: int,
    channel_count: int,
    overwrite: bool = False,
    project: dict | None = None,
) -> dict:
    """Turn a spec into batch commands, skipping the targets it does not own.

    Args:
        spec: The spec, as `TEMPLATES` holds them or as a caller wrote one.
        track_count: How many mixer tracks the project has. Index 0 is the Master,
            which no template names.
        channel_count: How many Channel Rack channels the project has.
        overwrite: Touch a target even when the producer named it themselves.
        project: What FL reported, when it was read: `ppq`, `beats_per_bar`,
            `track_names`, `lane_names` and `lane_count`. A marker's bar cannot
            become ticks without the first two, and the generated-name rule needs
            the names, so a spec that names markers or targets without this is
            refused rather than planned on a guess. The tool always passes it.

    Returns:
        commands: ready for `system.batch`, ordered names, colours, sends, lanes,
            channels, then markers
        skipped: what was left alone, each entry naming its path and the reason
        problems: the paths that made the spec unusable. A spec with any problem
            plans nothing at all, so a typo cannot half-apply.
    """
    if not isinstance(spec, dict):
        return _refused("the spec must be an object")

    readings = project if isinstance(project, dict) else {}
    commands: list[dict] = []
    skipped: list[dict] = []
    problems: list[str] = []

    problems.extend(_unknown_fields(spec, _TOP_LEVEL_FIELDS, ""))
    problems.extend(_description_problem(spec))
    _plan_tracks(spec, track_count, overwrite, readings, commands, skipped, problems)
    _plan_lanes(spec, overwrite, readings, commands, skipped, problems)
    _plan_channels(spec, channel_count, overwrite, commands, skipped, problems)
    _plan_markers(spec, readings, commands, problems)

    if problems:
        return {"commands": [], "skipped": [], "problems": problems}
    return {"commands": commands, "skipped": skipped, "problems": []}


def tracks_without_instruments(spec: dict, channels: list[dict]) -> list[dict]:
    """The spec's named mixer tracks that no channel is routed into.

    An instrument lives on a Channel Rack channel, and a channel reaches a mixer
    track through `target_fx_track`. An insert nothing targets has nothing playing
    into it, which is the only evidence this list offers: it names channels, not
    plugins. FL's scripting API cannot load a plugin or add a channel, so the reply
    says which inserts will stay silent instead of implying the template made a
    sound.

    The channel list is an argument rather than a call, because this module never
    talks to FL.
    """
    routed = set()
    for entry in channels:
        if not isinstance(entry, dict):
            continue
        target = entry.get("target_fx_track")
        if isinstance(target, int) and not isinstance(target, bool):
            routed.add(target)

    empty = []
    for entry in spec.get("tracks") or []:
        if not isinstance(entry, dict) or entry.get("track") in routed:
            continue
        empty.append({"track": entry.get("track"), "name": entry.get("name")})
    return empty


def _plan_tracks(
    spec: dict,
    track_count: int,
    overwrite: bool,
    readings: dict,
    commands: list[dict],
    skipped: list[dict],
    problems: list[str],
) -> None:
    """Plan the mixer inserts a spec names."""
    entries = spec.get("tracks")
    if entries is None:
        return
    if not isinstance(entries, list):
        problems.append("tracks must be a list")
        return

    names = _name_map(readings.get("track_names"))
    seen: set[int] = set()
    for position, entry in enumerate(entries):
        path = f"tracks[{position}]"
        if not isinstance(entry, dict):
            problems.append(f"{path} must be an object")
            continue
        problems.extend(_unknown_fields(entry, _TRACK_FIELDS, path))
        index = _integer(entry, "track", path, problems)
        name = _text(entry, "name", path, problems)
        color = _color(entry, path, problems)
        sends = _sends(entry, path, track_count, problems)
        if index is None or name is None:
            continue
        if not 1 <= index < track_count:
            problems.append(
                f"{path}.track is {index}, and this project has "
                f"{_range_text(track_count)}."
            )
            continue
        if index in seen:
            problems.append(
                f"{path}.track repeats track {index}, which another entry already names."
            )
            continue
        seen.add(index)
        if index in sends:
            problems.append(
                f"{path}.sends sends track {index} to itself, which is a feedback loop."
            )
            continue

        leave_alone = _leave_alone(
            path=path,
            kind="mixer track",
            index=index,
            name=name,
            current=names.get(index),
            generated=INSERT_NAME.format(index=index),
            overwrite=overwrite,
        )
        if leave_alone is not None:
            skipped.append(leave_alone)
            continue

        commands.append({
            "action": "mixer.setTrackName",
            "params": {"track": index, "name": name},
        })
        if color is not None:
            commands.append({
                "action": "mixer.setTrackColor",
                "params": _color_params(index, color),
            })
        if sends:
            commands.append({
                "action": "mixer.setRouting",
                "params": {"track": index, "sends": [{"track": item} for item in sends]},
            })


def _plan_lanes(
    spec: dict,
    overwrite: bool,
    readings: dict,
    commands: list[dict],
    skipped: list[dict],
    problems: list[str],
) -> None:
    """Plan the playlist lanes a spec names."""
    entries = spec.get("lanes")
    if entries is None:
        return
    if not isinstance(entries, list):
        problems.append("lanes must be a list")
        return

    lane_count = readings.get("lane_count")
    names = _name_map(readings.get("lane_names"))
    seen: set[int] = set()
    for position, entry in enumerate(entries):
        path = f"lanes[{position}]"
        if not isinstance(entry, dict):
            problems.append(f"{path} must be an object")
            continue
        problems.extend(_unknown_fields(entry, _LANE_FIELDS, path))
        index = _integer(entry, "lane", path, problems)
        name = _text(entry, "name", path, problems)
        color = _color(entry, path, problems)
        if index is None or name is None:
            continue
        if not isinstance(lane_count, int) or isinstance(lane_count, bool):
            problems.append(
                f"{path}.lane cannot be checked, because the playlist's lane count "
                "was not read."
            )
            continue
        if not 0 <= index < lane_count:
            problems.append(
                f"{path}.lane is {index}, and this project has {lane_count} playlist "
                f"lane(s), indexed 0 to {lane_count - 1}."
            )
            continue
        if index in seen:
            problems.append(f"{path}.lane repeats lane {index}, which another entry already names.")
            continue
        seen.add(index)

        leave_alone = _leave_alone(
            path=path,
            kind="playlist lane",
            index=index,
            name=name,
            current=names.get(index),
            generated=LANE_NAME.format(index=index),
            overwrite=overwrite,
        )
        if leave_alone is not None:
            skipped.append(leave_alone)
            continue

        params: dict[str, Any] = {"index": index, "name": name}
        if color is not None:
            params["color"] = color
        commands.append({"action": "playlist.setTrack", "params": params})


def _plan_channels(
    spec: dict,
    channel_count: int,
    overwrite: bool,
    commands: list[dict],
    skipped: list[dict],
    problems: list[str],
) -> None:
    """Plan the Channel Rack channels a spec names.

    A channel is only renamed with overwrite. Unlike an insert or a lane, FL's
    generated name for a channel has not been measured, so there is no way to tell
    an untouched channel from one somebody named, and guessing in the destructive
    direction is not a guess worth making.
    """
    entries = spec.get("channels")
    if entries is None:
        return
    if not isinstance(entries, list):
        problems.append("channels must be a list")
        return

    seen: set[int] = set()
    for position, entry in enumerate(entries):
        path = f"channels[{position}]"
        if not isinstance(entry, dict):
            problems.append(f"{path} must be an object")
            continue
        problems.extend(_unknown_fields(entry, _CHANNEL_FIELDS, path))
        index = _integer(entry, "channel", path, problems)
        name = _text(entry, "name", path, problems)
        color = _color(entry, path, problems)
        if index is None or name is None:
            continue
        if not 0 <= index < channel_count:
            problems.append(
                f"{path}.channel is {index}, and this project has {channel_count} "
                f"channel(s), indexed 0 to {channel_count - 1}."
            )
            continue
        if index in seen:
            problems.append(
                f"{path}.channel repeats channel {index}, which another entry already names."
            )
            continue
        seen.add(index)

        if not overwrite:
            skipped.append({
                "path": path,
                "kind": "channel",
                "channel": index,
                "name": name,
                "reason": (
                    f"channel {index} is only renamed with overwrite=True: FL's "
                    "generated name for a Channel Rack channel has not been measured, "
                    "so an untouched channel cannot be told from one the producer "
                    "named."
                ),
            })
            continue

        commands.append({
            "action": "channels.setName",
            "params": {"index": index, "name": name},
        })
        if color is not None:
            commands.append({
                "action": "channels.setColor",
                "params": _color_params(index, color, key="index"),
            })


def _plan_markers(
    spec: dict, readings: dict, commands: list[dict], problems: list[str]
) -> None:
    """Plan the arrangement markers a spec names, from bar to tick."""
    entries = spec.get("markers")
    if entries is None:
        return
    if not isinstance(entries, list):
        problems.append("markers must be a list")
        return

    ppq = readings.get("ppq")
    beats_per_bar = readings.get("beats_per_bar")
    timebase_known = (
        isinstance(ppq, int)
        and not isinstance(ppq, bool)
        and ppq > 0
        and isinstance(beats_per_bar, (int, float))
        and not isinstance(beats_per_bar, bool)
        and beats_per_bar > 0
    )

    seen: set[int] = set()
    for position, entry in enumerate(entries):
        path = f"markers[{position}]"
        if not isinstance(entry, dict):
            problems.append(f"{path} must be an object")
            continue
        problems.extend(_unknown_fields(entry, _MARKER_FIELDS, path))
        bar = _integer(entry, "bar", path, problems)
        name = _text(entry, "name", path, problems)
        if bar is None or name is None:
            continue
        if bar < 1:
            problems.append(f"{path}.bar is {bar}, and bar counting starts at 1.")
            continue
        if not timebase_known:
            problems.append(
                f"{path}.bar cannot be turned into ticks: the project's ppq and "
                "meter were not read, and a marker placed from an assumed meter "
                "lands in the wrong place."
            )
            continue
        if bar in seen:
            problems.append(f"{path}.bar repeats bar {bar}, which another marker already uses.")
            continue
        seen.add(bar)

        commands.append({
            "action": "arrangement.addMarker",
            "params": {
                "time": int(round((bar - 1) * float(beats_per_bar) * ppq)),
                "name": name,
            },
        })


def _leave_alone(
    *,
    path: str,
    kind: str,
    index: int,
    name: str,
    current: Any,
    generated: str,
    overwrite: bool,
) -> dict | None:
    """The skipped entry for a target the template must not touch, or None.

    The generated name is the only evidence the API offers that nobody has claimed
    an object. A name that was not read at all is not evidence either way, so it is
    treated as claimed: refusing to rename a track that was already named is
    recoverable, overwriting one is not.
    """
    if overwrite:
        return None
    if not current:
        return {
            "path": path,
            "kind": kind,
            "index": index,
            "name": name,
            "current_name": current,
            "reason": (
                f"{kind} {index} has no name this report can compare with FL's "
                f"generated {generated!r}, so it was left alone. Pass overwrite=True "
                f"to name it {name!r} anyway."
            ),
        }
    if current != generated:
        return {
            "path": path,
            "kind": kind,
            "index": index,
            "name": name,
            "current_name": current,
            "reason": (
                f"{kind} {index} is named {current!r}, which the producer chose, so it "
                f"was left alone. Pass overwrite=True to name it {name!r} anyway."
            ),
        }
    return None


def _unknown_fields(entry: dict, allowed: frozenset[str], path: str) -> list[str]:
    """Every field a spec carries that this module does not know.

    Naming the path rather than the field alone is the point: a spec with a typo in
    its ninth track is otherwise reported as a template that did nothing.
    """
    problems = []
    for field in sorted(entry):
        if field in allowed:
            continue
        where = f"{path}.{field}" if path else str(field)
        problems.append(
            f"{where} is not a field a template knows. Allowed here: "
            f"{', '.join(sorted(allowed))}."
        )
    return problems


def _description_problem(spec: dict) -> list[str]:
    description = spec.get("description")
    if description is None or isinstance(description, str):
        return []
    return ["description must be a string"]


def _integer(entry: dict, field: str, path: str, problems: list[str]) -> int | None:
    """A required whole number, refused when it is missing or not one."""
    if field not in entry:
        problems.append(f"{path}.{field} is missing, and every entry needs one.")
        return None
    value = entry[field]
    if isinstance(value, bool) or not isinstance(value, int):
        problems.append(
            f"{path}.{field} must be an integer, got {type(value).__name__}."
        )
        return None
    return value


def _text(entry: dict, field: str, path: str, problems: list[str]) -> str | None:
    """A required name, refused when it is missing, empty or not a string."""
    value = entry.get(field)
    if not isinstance(value, str) or not value.strip():
        problems.append(f"{path}.{field} must be a non-empty string.")
        return None
    return value


def _color(entry: dict, path: str, problems: list[str]) -> int | None:
    """An optional colour as one 0xRRGGBB integer."""
    if "color" not in entry:
        return None
    value = entry["color"]
    if isinstance(value, bool) or not isinstance(value, int):
        problems.append(f"{path}.color must be an integer such as 0xFF5A5A.")
        return None
    if not 0 <= value <= MAX_COLOR:
        problems.append(f"{path}.color is {value:#x}, outside 0x000000 to 0xFFFFFF.")
        return None
    return value


def _sends(entry: dict, path: str, track_count: int, problems: list[str]) -> list[int]:
    """An optional list of mixer track destinations, every one of them real."""
    if "sends" not in entry:
        return []
    value = entry["sends"]
    if not isinstance(value, list):
        problems.append(f"{path}.sends must be a list of mixer track indices.")
        return []

    destinations = []
    for position, destination in enumerate(value):
        if isinstance(destination, bool) or not isinstance(destination, int):
            problems.append(
                f"{path}.sends[{position}] must be an integer mixer track index."
            )
            continue
        if not 1 <= destination < track_count:
            problems.append(
                f"{path}.sends[{position}] is {destination}, and this project has "
                f"{_range_text(track_count)}."
            )
            continue
        destinations.append(destination)
    return destinations


def _color_params(index: int, color: int, key: str = "track") -> dict:
    """One 0xRRGGBB colour as the r, g and b the controller's setters take."""
    return {
        key: index,
        "r": (color >> 16) & 0xFF,
        "g": (color >> 8) & 0xFF,
        "b": color & 0xFF,
    }


def _name_map(value: Any) -> dict[int, Any]:
    """A read mapping of index to name, with integer keys.

    JSON has no integer keys, so readings that travelled through a file arrive with
    strings. Both are accepted rather than treating every track as unread.
    """
    result: dict[int, Any] = {}
    if not isinstance(value, dict):
        return result
    for key, name in value.items():
        try:
            result[int(key)] = name
        except (TypeError, ValueError):
            continue
    return result


def _range_text(track_count: int) -> str:
    if track_count <= 1:
        return "no mixer inserts beyond the Master"
    return f"mixer tracks 1 to {track_count - 1}, with 0 the Master"


def _refused(problem: str) -> dict:
    return {"commands": [], "skipped": [], "problems": [problem]}
