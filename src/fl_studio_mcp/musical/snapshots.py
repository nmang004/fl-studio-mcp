"""Snapshot arithmetic: flatten a project, diff two of them, and plan a restore.

A snapshot is a nested dictionary of everything the host can read about a project, and
these functions turn that into the two answers a producer asks for: what changed, and
how do I put it back.

Two decisions are worth stating, because both come from measurements:

- Floats are rounded when flattening. FL returns 0.7999999998137355 for a fader that was
  set to 0.8, because the value travels through a 32 bit float. Comparing those raw
  makes every snapshot differ from the next by noise, and a diff that always reports a
  change is a diff nobody reads.
- A restore only moves values that were in the snapshot. Something that appeared since
  then is reported rather than deleted, and something that disappeared is reported
  rather than recreated, because "restore" must not mean "delete the last hour of work".

The writer table is data: a path pattern, an action, and how the action's parameters are
filled from the captured index and value. Adding a restorable setting is adding a row.
"""

from __future__ import annotations

import re
from typing import Any

SCHEMA = 1

# The flag word that made a live tempo write work, measured on FL Studio 2026 build
# 5406 and recorded in docs/spikes/2026-09-19-T1-tempo-write.md. It is REC_UpdateValue
# combined with REC_UpdateControl. The tempo tool owns the same constant, and a test
# pins the two together so they cannot drift.
TEMPO_WRITE_FLAGS = 17

# Enough of a diff or a command list to be useful, small enough to read. Both report
# when they cut the answer short rather than quietly returning a prefix.
MAX_DIFF = 200
MAX_COMMANDS = 500

# How a parameter is filled from the path and the value being restored.
_INDEX = object()
_VALUE = object()


def flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    """Every scalar in a nested document, keyed by its dotted path.

    Empty dictionaries and lists stay as values rather than vanishing, because
    "no sends" and "no sends key at all" are different facts about a project.
    """
    flat: dict[str, Any] = {}

    if isinstance(value, dict):
        if not value:
            flat[prefix] = {}
            return flat
        for key, item in value.items():
            child = f"{prefix}.{key}" if prefix else str(key)
            flat.update(flatten(item, child))
        return flat

    if isinstance(value, (list, tuple)):
        # A list of scalars is one value, not a structure: a track's sends are a set
        # of destinations, and diffing them index by index turned a single routing
        # change into a puzzle of added and removed positions. A list of objects is a
        # structure, so EQ bands are still addressed band by band.
        if not value or all(not isinstance(item, (dict, list, tuple)) for item in value):
            flat[prefix] = list(value)
            return flat
        for index, item in enumerate(value):
            child = f"{prefix}.{index}" if prefix else str(index)
            flat.update(flatten(item, child))
        return flat

    if isinstance(value, float):
        flat[prefix] = round(value, 6)
    else:
        flat[prefix] = value
    return flat


def diff(before: dict, after: dict, limit: int = MAX_DIFF) -> dict[str, Any]:
    """What changed between two snapshots.

    Returns:
        added, removed and changed, each capped at `limit` entries, with the true
        counts alongside so a caller can tell a small diff from a large one.
    """
    first = flatten(before)
    second = flatten(after)

    added = {path: second[path] for path in second if path not in first}
    removed = {path: first[path] for path in first if path not in second}
    changed = {
        path: {"before": first[path], "after": second[path]}
        for path in first
        if path in second and not _same(first[path], second[path])
    }

    counts = {
        "added": len(added),
        "removed": len(removed),
        "changed": len(changed),
        "total": len(added) + len(removed) + len(changed),
    }
    truncated = counts["total"] > limit
    return {
        "added": _cap(added, limit),
        "removed": _cap(removed, limit),
        "changed": _cap(changed, limit),
        "counts": counts,
        "truncated": truncated,
    }


def summarise_diff(difference: dict[str, Any]) -> dict[str, Any]:
    """The counts by namespace, and one sentence a producer reads first."""
    counts = difference.get("counts") or {}
    by_namespace: dict[str, int] = {}
    for bucket in ("added", "removed", "changed"):
        for path in difference.get(bucket) or {}:
            namespace = str(path).split(".", 1)[0]
            by_namespace[namespace] = by_namespace.get(namespace, 0) + 1

    changed = counts.get("changed", 0)
    added = counts.get("added", 0)
    removed = counts.get("removed", 0)
    total = counts.get("total", 0)
    if not total:
        headline = "Nothing changed."
    else:
        parts = []
        if changed:
            parts.append(f"{changed} setting(s) changed")
        if added:
            parts.append(f"{added} added")
        if removed:
            parts.append(f"{removed} removed")
        headline = ", ".join(parts) + "."
    return {
        "counts": counts,
        "by_namespace": dict(sorted(by_namespace.items())),
        "headline": headline,
        "truncated": bool(difference.get("truncated")),
    }


def restore_commands(
    snapshot: dict, current: dict, limit: int = MAX_COMMANDS
) -> dict[str, Any]:
    """The commands that would turn `current` back into `snapshot`.

    Args:
        snapshot: The state to go back to.
        current: The state now.
        limit: The most commands to plan.

    Returns:
        commands, each ready for a batch; unrestorable, one entry per thing this
        version cannot put back, each with a reason; counts, and whether the list was
        capped.
    """
    difference = diff(snapshot, current, limit=max(limit, MAX_DIFF))
    flat_snapshot = flatten(snapshot)
    commands: list[dict[str, Any]] = []
    unrestorable: list[dict[str, str]] = []

    eq_tracks: dict[int, bool] = {}
    for path in difference["changed"]:
        band = _EQ_PATH.match(path)
        if band:
            eq_tracks[int(band.group(1))] = True

    if eq_tracks:
        for track in sorted(eq_tracks):
            bands = _snapshot_bands(snapshot, track)
            if bands is None:
                unrestorable.append({
                    "path": f"mixer.tracks.{track}.eq",
                    "reason": (
                        "the snapshot has no EQ bands recorded for this track, so "
                        "there is nothing to write back"
                    ),
                })
                continue
            commands.append({
                "action": "mixer.setEqBands",
                "params": {"track": track, "bands": bands},
                "reason": f"EQ band(s) on track {track} differ from the snapshot",
            })

    for path, sides in sorted(difference["changed"].items()):
        if _EQ_PATH.match(path):
            continue  # handled as one command per track above

        sends = _SENDS_PATH.match(path)
        if sends:
            track = int(sends.group(1))
            commands.append({
                "action": "mixer.setRouting",
                "params": {
                    "track": track,
                    "sends": _sends_to_restore(
                        sides["before"], sides["after"], flat_snapshot, path
                    ),
                },
                "reason": f"track {track} sends differ from the snapshot",
            })
            continue

        writer = _writer_for(path)
        if writer is None:
            unrestorable.append({"path": path, "reason": _no_writer_reason(path)})
            continue

        action, template, is_toggle = writer
        # Not every writer is indexed: project.tempo is a scalar with no object.
        found = _PATH_INDEX.search(path)
        index = int(found.group(1)) if found else None
        params = {}
        for name, source in template.items():
            if source is _INDEX:
                params[name] = index
            elif source is _VALUE:
                params[name] = sides["before"]
            else:
                params[name] = source
        command = {
            "action": action,
            "params": params,
            "reason": f"{path} is {sides['before']!r} in the snapshot and "
                      f"{sides['after']!r} now",
        }
        if is_toggle:
            # mixer.armTrack takes no value, it flips the state. Both sides are known
            # so the flip is correct, but the caller should know it is a toggle.
            command["toggle"] = True
            command["reason"] = (
                f"{path} is {sides['before']!r} in the snapshot and {sides['after']!r} "
                "now, so one toggle puts it back"
            )
        commands.append(command)

    for path in sorted(difference["added"]):
        unrestorable.append({
            "path": _parent(path),
            "reason": (
                "this appeared since the snapshot, and this version only moves values "
                "back rather than removing what you added"
            ),
        })

    for path in sorted(difference["removed"]):
        unrestorable.append({
            "path": _parent(path),
            "reason": (
                "this is gone from the project, and this version cannot recreate it"
            ),
        })

    needed = len(commands)
    truncated = needed > limit
    commands = commands[:limit]

    return {
        "commands": commands,
        "unrestorable": _dedupe(unrestorable),
        "counts": {
            "commands": len(commands),
            "needed": needed,
            "unrestorable": len(_dedupe(unrestorable)),
        },
        "truncated": truncated,
    }


# --- the writer table --------------------------------------------------------

def _re_track(field: str) -> re.Pattern[str]:
    return re.compile(rf"^mixer\.tracks\.(\d+)\.{field}$")


def _re_channel(field: str) -> re.Pattern[str]:
    return re.compile(rf"^channels\.(\d+)\.{field}$")


# Path, action, parameter template. `_INDEX` is the number in the path, `_VALUE` is
# the value from the snapshot, and a literal is written as itself.
_SCALAR_WRITERS: tuple[tuple[re.Pattern[str], str, dict[str, Any], bool], ...] = (
    (_re_track("volume"), "mixer.setTrackVolume", {"track": _INDEX, "volume": _VALUE}, False),
    (_re_track("pan"), "mixer.setTrackPan", {"track": _INDEX, "pan": _VALUE}, False),
    (_re_track("is_muted"), "mixer.muteTrack", {"track": _INDEX, "muted": _VALUE}, False),
    (_re_track("is_solo"), "mixer.soloTrack", {"track": _INDEX, "solo": _VALUE}, False),
    # A toggle: no value parameter exists.
    (_re_track("is_armed"), "mixer.armTrack", {"track": _INDEX}, True),
    (
        _re_track("stereo_separation"),
        "mixer.setStereoSep",
        {"track": _INDEX, "separation": _VALUE},
        False,
    ),
    (_re_track("name"), "mixer.setTrackName", {"track": _INDEX, "name": _VALUE}, False),
    (_re_track("color"), "mixer.setTrackColor", {"track": _INDEX, "color": _VALUE}, False),
    (_re_channel("volume"), "channels.setVolume", {"index": _INDEX, "volume": _VALUE}, False),
    (_re_channel("pan"), "channels.setPan", {"index": _INDEX, "pan": _VALUE}, False),
    (_re_channel("is_muted"), "channels.mute", {"index": _INDEX, "muted": _VALUE}, False),
    (_re_channel("name"), "channels.setName", {"index": _INDEX, "name": _VALUE}, False),
    (_re_channel("color"), "channels.setColor", {"index": _INDEX, "color": _VALUE}, False),
    (
        re.compile(r"^patterns\.(\d+)\.name$"),
        "patterns.setName",
        {"index": _INDEX, "name": _VALUE},
        False,
    ),
    (
        re.compile(r"^patterns\.(\d+)\.color$"),
        "patterns.setColor",
        {"index": _INDEX, "color": _VALUE},
        False,
    ),
    (
        re.compile(r"^playlist\.tracks\.(\d+)\.name$"),
        "playlist.setTrack",
        {"index": _INDEX, "name": _VALUE},
        False,
    ),
    (
        re.compile(r"^playlist\.tracks\.(\d+)\.color$"),
        "playlist.setTrack",
        {"index": _INDEX, "color": _VALUE},
        False,
    ),
    (
        re.compile(r"^playlist\.tracks\.(\d+)\.is_muted$"),
        "playlist.setTrack",
        {"index": _INDEX, "muted": _VALUE},
        False,
    ),
    (
        re.compile(r"^playlist\.tracks\.(\d+)\.is_solo$"),
        "playlist.setTrack",
        {"index": _INDEX, "solo": _VALUE},
        False,
    ),
    (
        re.compile(r"^project\.tempo$"),
        "system.tempoProbe",
        {"bpm": _VALUE, "restore": False, "flags": TEMPO_WRITE_FLAGS},
        False,
    ),
)

_PREFIX_INDEX = re.compile(r"^(?:mixer\.tracks|channels|patterns|playlist\.tracks)\.(\d+)\.")


_PATH_INDEX = _PREFIX_INDEX
_SENDS_PATH = re.compile(r"^mixer\.tracks\.(\d+)\.sends$")
_EQ_PATH = re.compile(r"^mixer\.tracks\.(\d+)\.eq\.bands\.\d+\.")


def _writer_for(path: str) -> tuple[str, dict[str, Any], bool] | None:
    for pattern, action, template, is_toggle in _SCALAR_WRITERS:
        if pattern.match(path):
            return action, template, is_toggle
    return None


def _no_writer_reason(path: str) -> str:
    if path.startswith("plugins."):
        return (
            "plugin parameters are restored by the preset tools rather than by a "
            "snapshot restore, because a preset can be checked before it is applied"
        )
    return (
        "this version has no writer for this setting, so it is reported rather than "
        "silently left different"
    )


def _snapshot_bands(snapshot: dict, track: int) -> list[dict[str, Any]] | None:
    """The EQ bands recorded for a track, in the shape mixer.setEqBands wants."""
    tracks = ((snapshot.get("mixer") or {}).get("tracks") or {})
    entry = tracks.get(str(track)) or {}
    bands = (entry.get("eq") or {}).get("bands")
    if not isinstance(bands, list) or not bands:
        return None
    return [
        {
            "band": int(band.get("band", index)),
            "gain": band.get("gain"),
            "frequency": band.get("frequency"),
            "bandwidth": band.get("bandwidth"),
        }
        for index, band in enumerate(bands)
    ]


def _sends_to_restore(
    before: Any, after: Any, flat_snapshot: dict[str, Any], path: str
) -> list[dict[str, Any]]:
    """Enable what the snapshot had and remove what it did not, in one command."""
    wanted = {int(index) for index in (before or [])}
    present = {int(index) for index in (after or [])}
    sends: list[dict[str, Any]] = []
    for index in sorted(present - wanted):
        sends.append({"track": index, "remove": True})
    for index in sorted(wanted - present):
        sends.append({"track": index})
    if not sends:
        # The lists are equal, or the difference is in a level this version does not
        # capture. Refuse rather than send an empty command the controller rejects.
        sends.append({"track": next(iter(wanted | present), 0)})
    return sends


def _same(first: Any, second: Any) -> bool:
    """Type-aware equality, because True == 1 in Python and a flag is not a number."""
    if isinstance(first, bool) != isinstance(second, bool):
        return False
    return first == second


def _cap(mapping: dict[str, Any], limit: int) -> dict[str, Any]:
    if limit < 0 or len(mapping) <= limit:
        return dict(sorted(mapping.items()))
    return dict(sorted(mapping.items())[:limit])


def _parent(path: str) -> str:
    """The object a path belongs to, so a removed track is one entry, not eight."""
    parts = str(path).split(".")
    return ".".join(parts[:2]) if len(parts) >= 2 else str(path)


def _dedupe(entries: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: dict[str, str] = {}
    for entry in entries:
        seen.setdefault(entry["path"], entry["reason"])
    return [{"path": path, "reason": reason} for path, reason in sorted(seen.items())]
