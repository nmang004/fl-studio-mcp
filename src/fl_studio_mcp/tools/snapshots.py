"""Project snapshots: capture the settings, compare two, plan a restore.

A snapshot is taken in one batch, because the alternative is a round trip per track and
that is the shape of question this server exists to avoid. It holds settings, not
material: the notes live in the piano roll's own sandbox and are reached only through
the script file and a keystroke, and the playlist has no clip API at all, so neither is
in a snapshot and both are named as unrestorable when a restore is planned.

The diff and the restore plan are arithmetic in `musical/snapshots.py`. This module is
the part that knows which FL actions to call.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from fl_studio_mcp.musical import snapshots
from fl_studio_mcp.tools import batch
from fl_studio_mcp.utils import store
from fl_studio_mcp.utils.connection import get_connection

if TYPE_CHECKING:
    from fastmcp import FastMCP

SNAPSHOT_TIMEOUT = 60.0
DEFAULT_LIMIT = 20

# How many effect slots per mixer track are asked about when plugins are included.
# Ten is FL's slot count in practice, and an empty slot answers with no parameters.
MIXER_SLOTS = 10

# A plugin can report thousands of parameters: a VST reports 4240, made up of 4096
# real ones plus MIDI CC and aftertouch. A snapshot is not the place to store all of
# that, so the cap is named in the document when it is reached.
PLUGIN_PARAM_CAP = 200

CAPTURE_NOTE = (
    "A snapshot holds settings, not material. Notes live in the piano roll's own "
    "sandbox and playlist clips have no scripting API at all, so neither is captured, "
    "and a restore reports them as differences it cannot put back rather than "
    "pretending they are unchanged."
)


def capture(include_plugins: bool = False, include_eq: bool = True) -> dict[str, Any]:
    """Read the whole project's settings, in one batch where possible.

    Args:
        include_plugins: Also read every plugin's parameters. Off by default, because
            a single VST can report 4240 of them.
        include_eq: Also read every mixer track's EQ bands.

    Returns:
        The snapshot document, plus how many round trips it took.
    """
    connection = get_connection()

    # Two small reads first, because the batch has to be built before it is sent and
    # the per-object commands need to know how many objects there are.
    track_count = _count(connection, "mixer.getTrackCount", "count")
    channel_count = _count(connection, "channels.getCount", "count")

    commands: list[dict[str, Any]] = [
        {"action": "system.getInfo", "params": {}},
        {"action": "system.getPpq", "params": {}},
        {"action": "patterns.getAll", "params": {}},
        {"action": "mixer.getSnapshot", "params": {}},
        # include_all, because an unnamed lane is still a lane: without it, naming a
        # lane after the snapshot looks like something appearing from nowhere.
        {"action": "playlist.getAll", "params": {"include_all": True}},
        {"action": "arrangement.getMarkers", "params": {}},
    ]
    for index in range(channel_count):
        commands.append({"action": "channels.getInfo", "params": {"index": index}})
    if include_eq:
        for track in range(track_count):
            commands.append({"action": "mixer.getEq", "params": {"track": track}})
    if include_plugins:
        for index in range(channel_count):
            commands.append({
                "action": "plugins.getParams",
                "params": {
                    "index": index,
                    "slot_index": -1,
                    "use_global": True,
                    "max_params": PLUGIN_PARAM_CAP,
                },
            })
        for track in range(track_count):
            for slot in range(MIXER_SLOTS):
                commands.append({
                    "action": "plugins.getParams",
                    "params": {
                        "index": track,
                        "slot_index": slot,
                        "use_global": True,
                        "max_params": PLUGIN_PARAM_CAP,
                    },
                })

    reply = connection.send_command(
        "system.batch",
        {"commands": commands, "name": "MCP: snapshot project"},
        timeout=SNAPSHOT_TIMEOUT,
    )
    if not reply.get("success"):
        return {
            "success": False,
            "error": reply.get("error") or "The snapshot batch did not complete.",
            "results": reply.get("results"),
        }

    results = reply.get("results") or []
    if len(results) < len(commands):
        return {
            "success": False,
            "error": (
                f"The snapshot batch returned {len(results)} result(s) for "
                f"{len(commands)} command(s), so the project was only partly read."
            ),
        }

    document, problems = _document(
        results,
        channel_count=channel_count,
        track_count=track_count,
        include_plugins=include_plugins,
        include_eq=include_eq,
    )
    document["problems"] = problems
    document["round_trips"] = 2 + 1
    return {"success": True, "snapshot": document}


def snapshot_project(
    label: str | None = None,
    include_plugins: bool = False,
    include_eq: bool = True,
) -> dict[str, Any]:
    """Capture the project and store the snapshot in the library."""
    captured = capture(include_plugins=include_plugins, include_eq=include_eq)
    if not captured.get("success"):
        return captured

    document = captured["snapshot"]
    name = label or "snapshot"
    record_id = store.unique_record_id("snapshots", name)
    # Metadata sits beside the state rather than inside it. Mixing them made a diff of
    # two identical projects report the id, the label and the timestamp as changes.
    record = {
        "schema": snapshots.SCHEMA,
        "id": record_id,
        "label": label,
        "created": datetime.now().astimezone().isoformat(),
        "state": document,
    }
    try:
        path = store.write_record("snapshots", record_id, record)
    except ValueError as error:
        return {"success": False, "error": str(error)}

    counts = {
        "mixer_tracks": len(document["mixer"]["tracks"]),
        "channels": len(document["channels"]),
        "patterns": len(document["patterns"]),
        "playlist_tracks": len(document["playlist"]["tracks"]),
        "markers": len(document["markers"]),
    }
    if include_eq:
        counts["eq_bands"] = sum(
            len((track.get("eq") or {}).get("bands") or [])
            for track in document["mixer"]["tracks"].values()
        )
    if include_plugins:
        counts["plugins"] = len(document.get("plugins") or {})

    result: dict[str, Any] = {
        "success": True,
        "id": record_id,
        "file": str(path),
        "captured": counts,
        "round_trips": document.get("round_trips"),
        "note": CAPTURE_NOTE,
        "message": (
            f"Snapshotted {counts['mixer_tracks']} mixer track(s), {counts['channels']} "
            f"channel(s) and {counts['patterns']} pattern(s) as {record_id}."
        ),
    }
    if document.get("problems"):
        result["problems"] = document["problems"]
    if not include_plugins:
        result["plugins_note"] = (
            "Plugin parameters were not captured. Pass include_plugins=True if you "
            "want the snapshot to cover them too."
        )
    return result


def project_changes(
    since: str | None = None,
    against: str | None = None,
    include_plugins: bool = False,
) -> dict[str, Any]:
    """What changed, either live against a stored snapshot or between two of them."""
    if against:
        # `since` is the baseline and `against` is the other side, so the diff reads
        # as "from since to against" whichever two snapshots were named.
        baseline = _load(since) if since else _newest()
        if baseline is None:
            return _no_snapshots()
        if baseline.get("error"):
            return {"success": False, "error": baseline["error"]}
        other = _load(against)
        if other.get("error"):
            return {"success": False, "error": other["error"]}
        return _compare(baseline, other, live=False)

    stored = _load(since) if since else _newest()
    if stored is None:
        return _no_snapshots()
    if stored.get("error"):
        return {"success": False, "error": stored["error"]}

    captured = capture(include_plugins=include_plugins)
    if not captured.get("success"):
        return captured
    return _compare(stored, _live_record(captured["snapshot"]), live=True)


def restore_snapshot(
    snapshot: str | None = None,
    apply: bool = False,
    include_plugins: bool = False,
) -> dict[str, Any]:
    """Plan, and with apply=True make, the moves that put a stored snapshot back."""
    stored = _load(snapshot) if snapshot else _newest()
    if stored is None:
        return _no_snapshots()
    if stored.get("error"):
        return {"success": False, "error": stored["error"]}

    captured = capture(include_plugins=include_plugins)
    if not captured.get("success"):
        return captured

    plan = snapshots.restore_commands(_state(stored), _state(_live_record(captured["snapshot"])))
    result: dict[str, Any] = {
        "success": True,
        "snapshot": stored.get("id"),
        "snapshot_created": stored.get("created"),
        "moves": plan["commands"],
        "counts": plan["counts"],
        "applied": False,
        "note": CAPTURE_NOTE,
    }
    if plan["unrestorable"]:
        result["unrestorable"] = plan["unrestorable"]
    if plan["truncated"]:
        result["truncated"] = True
        result["truncated_note"] = (
            f"Only the first {len(plan['commands'])} move(s) are listed. Restoring in "
            "one pass is capped so a snapshot cannot bury the reply."
        )

    if not plan["commands"]:
        result["message"] = (
            "Nothing to restore: the project already matches the snapshot for every "
            "setting this version can write back."
        )
        return result

    if not apply:
        result["message"] = (
            f"{len(plan['commands'])} setting(s) differ. Nothing has been changed: "
            "pass apply=True to make the moves, which go through one batch so one "
            "undo reverses them."
        )
        return result

    batch_result = batch.run_batch(plan["commands"], "MCP: restore snapshot")
    result["batch"] = batch_result
    result["applied"] = bool(batch_result.get("success"))
    if not result["applied"]:
        result["success"] = False
        result["error"] = batch_result.get("error") or "The restore batch did not complete."
        return result
    result["message"] = (
        f"Restored {len(plan['commands'])} setting(s) from {stored.get('id')}. One undo "
        "reverses the whole restore."
    )
    return result


def _compare(first: dict, second: dict, live: bool) -> dict[str, Any]:
    difference = snapshots.diff(
        _state(first), _state(second), limit=snapshots.MAX_DIFF
    )
    summary = snapshots.summarise_diff(difference)
    result: dict[str, Any] = {
        "success": True,
        "snapshot": first.get("id"),
        "snapshot_created": first.get("created"),
        "compared_with": second.get("id"),
        "summary": summary,
        "changed": difference["changed"],
        "added": difference["added"],
        "removed": difference["removed"],
        "truncated": difference["truncated"],
        "note": CAPTURE_NOTE,
    }
    if live:
        result["live"] = True
        result["live_captured"] = second.get("created")
    result["message"] = (
        f"{summary['headline']} Comparing {first.get('id')} with "
        + ("the live project." if live else f"{second.get('id')}.")
    )
    if not summary["counts"]["total"]:
        result["message"] = (
            f"Nothing has changed since {first.get('id')} in any setting a snapshot "
            "covers."
        )
    return result


def _load(record_id: str | None) -> dict[str, Any] | None:
    """A stored snapshot by id, or the newest one at or before a timestamp."""
    if not record_id:
        return None
    record = store.read_record("snapshots", record_id)
    if record is not None:
        return record

    # Not an id, so treat it as a moment: "what changed since yesterday" is a time,
    # and a caller should not have to look up which snapshot that was.
    try:
        moment = datetime.fromisoformat(str(record_id))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.astimezone()
    listing = store.list_records("snapshots")
    for record in listing["records"]:
        created = record.get("created")
        if not created:
            continue
        try:
            when = datetime.fromisoformat(str(created))
        except ValueError:
            continue
        if when <= moment:
            return record
    return {
        "error": (
            f"No snapshot was taken at or before {record_id}, and no snapshot has that "
            "id. Take one with fl_snapshot_project."
        )
    }


def _state(record: dict[str, Any]) -> dict[str, Any]:
    """The project state inside a stored record, without its metadata."""
    state = record.get("state")
    return state if isinstance(state, dict) else {}


def _live_record(state: dict[str, Any]) -> dict[str, Any]:
    """A live capture dressed as a record, so one comparison path reads both."""
    return {
        "id": "the live project",
        "created": datetime.now().astimezone().isoformat(),
        "state": state,
    }


def _newest() -> dict[str, Any] | None:
    listing = store.list_records("snapshots", limit=1)
    if not listing["records"]:
        return None
    return listing["records"][0]


def _no_snapshots() -> dict[str, Any]:
    return {
        "success": False,
        "error": (
            "There are no snapshots in the library yet. Take one with "
            "fl_snapshot_project, which is a read of the project's settings."
        ),
    }


def _count(connection: Any, action: str, key: str) -> int:
    reply = connection.send_command(action, {}, timeout=10.0)
    value = reply.get(key)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _document(
    results: list[Any],
    *,
    channel_count: int,
    track_count: int,
    include_plugins: bool,
    include_eq: bool,
) -> tuple[dict[str, Any], list[str]]:
    """Turn the batch's results, in order, into the snapshot document."""
    problems: list[str] = []
    info = results[0] or {}
    ppq_reply = results[1] or {}
    patterns_reply = results[2] or {}
    mixer_reply = results[3] or {}
    playlist_reply = results[4] or {}
    markers_reply = results[5] or {}
    cursor = 6

    channel_entries = results[cursor : cursor + channel_count]
    cursor += channel_count

    eq_entries: list[Any] = []
    if include_eq:
        eq_entries = results[cursor : cursor + track_count]
        cursor += track_count

    plugin_entries: list[Any] = []
    if include_plugins:
        count = channel_count + track_count * MIXER_SLOTS
        plugin_entries = results[cursor : cursor + count]
        cursor += count

    capabilities = info.get("capabilities") or {}
    raw_tempo = capabilities.get("getCurrentTempo")
    document: dict[str, Any] = {
        "project": {
            "tempo": round(raw_tempo / 1000.0, 3) if raw_tempo else None,
            "ppq": ppq_reply.get("ppq"),
            "fl_version": info.get("fl_version"),
            "api_version": info.get("api_version"),
        },
        "mixer": {"tracks": _mixer_tracks(mixer_reply, eq_entries)},
        "channels": _channels(channel_entries),
        "patterns": _patterns(patterns_reply),
        "playlist": {"tracks": _playlist(playlist_reply)},
        "markers": _markers(markers_reply),
    }
    if include_plugins:
        document["plugins"] = _plugins(
            plugin_entries, channel_count=channel_count, problems=problems
        )

    if document["project"]["tempo"] is None:
        problems.append(
            "FL did not report a tempo, so a tempo change cannot be seen or restored."
        )
    return document, problems


def _mixer_tracks(reply: dict[str, Any], eq_entries: list[Any]) -> dict[str, Any]:
    tracks: dict[str, Any] = {}
    eq_by_track = {
        str(entry.get("track")): entry for entry in eq_entries if isinstance(entry, dict)
    }
    for entry in reply.get("tracks") or []:
        index = str(entry.get("index"))
        record = {
            "name": entry.get("name"),
            "volume": entry.get("volume"),
            "pan": entry.get("pan"),
            "is_muted": entry.get("is_muted"),
            "is_solo": entry.get("is_solo"),
            "is_armed": entry.get("is_armed"),
            "stereo_separation": entry.get("stereo_separation"),
            "color": entry.get("color"),
            "sends": list(entry.get("sends") or []),
        }
        # volume_db is deliberately left out: it is the same fact as volume in other
        # units, and a diff that reported both would report every fader move twice.
        bands = (eq_by_track.get(index) or {}).get("bands")
        if bands:
            record["eq"] = {"bands": bands}
        tracks[index] = record
    return tracks


def _channels(entries: list[Any]) -> dict[str, Any]:
    channels: dict[str, Any] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        color = entry.get("color")
        channels[str(entry.get("index"))] = {
            "name": entry.get("name"),
            "color": int(color, 16) if isinstance(color, str) else color,
            "volume": entry.get("volume"),
            "pan": entry.get("pan"),
            "is_muted": entry.get("is_muted"),
            "is_solo": entry.get("is_solo"),
            "target_fx_track": entry.get("target_fx_track"),
        }
    return channels


def _patterns(reply: dict[str, Any]) -> dict[str, Any]:
    """Pattern settings, without which pattern is selected: that is UI state."""
    patterns: dict[str, Any] = {}
    for entry in reply.get("patterns") or []:
        patterns[str(entry.get("index"))] = {
            "name": entry.get("name"),
            "color": entry.get("color") & 0xFFFFFF
            if isinstance(entry.get("color"), int) and entry.get("color") < 0
            else entry.get("color"),
            "length": entry.get("length"),
        }
    return patterns


def _playlist(reply: dict[str, Any]) -> dict[str, Any]:
    tracks: dict[str, Any] = {}
    for entry in reply.get("tracks") or []:
        tracks[str(entry.get("index"))] = {
            "name": entry.get("name"),
            "color": entry.get("color"),
            "is_muted": entry.get("is_muted"),
            "is_solo": entry.get("is_solo"),
        }
    return tracks


def _markers(reply: dict[str, Any]) -> dict[str, Any]:
    markers: dict[str, Any] = {}
    for entry in reply.get("markers") or []:
        markers[str(entry.get("index"))] = {
            "name": entry.get("name"),
            "time": entry.get("time"),
        }
    return markers


def _plugins(
    entries: list[Any], *, channel_count: int, problems: list[str]
) -> dict[str, Any]:
    """Plugin parameters by scope, with the cap named when it was reached."""
    scopes: dict[str, Any] = {}
    for position, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        params = entry.get("params") or []
        if not params:
            continue
        if position < channel_count:
            scope = f"channels.{position}"
        else:
            offset = position - channel_count
            scope = f"mixer.{offset // MIXER_SLOTS}.{offset % MIXER_SLOTS}"
        values = {
            str(param.get("index")): {
                "name": param.get("name"),
                "value": param.get("value"),
            }
            for param in params
            if isinstance(param, dict) and param.get("index") is not None
        }
        scopes[scope] = {"params": values}
        if len(params) >= PLUGIN_PARAM_CAP:
            problems.append(
                f"{scope} reports at least {PLUGIN_PARAM_CAP} parameters, which is the "
                "cap this version reads, so the rest are not in the snapshot."
            )
    return scopes


def register_snapshot_tools(mcp: FastMCP) -> None:
    """Register the snapshot tools."""

    @mcp.tool()
    def fl_snapshot_project(
        label: str | None = None,
        include_plugins: bool = False,
        include_eq: bool = True,
    ) -> dict:
        """Save the project's current settings so changes can be seen and undone.

        This is FL's undo taken further: a snapshot is a file on disk, so it survives
        a restart and it can answer what changed since yesterday, which the undo
        history cannot.

        It holds settings, not material. Notes live in the piano roll's own scripting
        sandbox and playlist clips have no API at all, so a snapshot cannot see either,
        and a restore says so rather than implying they were unchanged.

        Args:
            label: A name to remember it by. The id carries the date either way.
            include_plugins: Also capture every plugin's parameters. Off by default,
                            because one VST can report 4240 of them.
            include_eq: Capture every mixer track's EQ bands.

        Returns:
            id: the library id, which the other snapshot tools take
            captured: how many tracks, channels, patterns and bands went in
            note: what a snapshot cannot contain
        """
        return snapshot_project(
            label=label, include_plugins=include_plugins, include_eq=include_eq
        )

    @mcp.tool()
    def fl_project_changes(
        since: str | None = None,
        against: str | None = None,
        include_plugins: bool = False,
    ) -> dict:
        """What changed, live against a stored snapshot or between two of them.

        Use this to answer "what changed since yesterday": pass a timestamp and the
        newest snapshot taken at or before it is used. Pass two snapshot ids to compare
        two stored snapshots without touching FL Studio at all.

        Args:
            since: A snapshot id, or an ISO timestamp such as "2026-09-19T10:00:00".
            against: A second snapshot id, to compare two stored snapshots with each
                     other instead of with the live project.
            include_plugins: Also capture plugin parameters before comparing, which is
                             only meaningful for snapshots that captured them.

        Returns:
            summary: counts by namespace and a sentence
            changed, added, removed: the settings themselves, changed being
                                     path to before and after
        """
        return project_changes(
            since=since, against=against, include_plugins=include_plugins
        )

    @mcp.tool()
    def fl_restore_snapshot(
        snapshot: str | None = None,
        apply: bool = False,
        include_plugins: bool = False,
    ) -> dict:
        """Put the settings from a snapshot back.

        Reports first and acts only when asked. Every move goes through one batch, so
        a single undo reverses the whole restore.

        It moves values back and deletes nothing. Something that appeared since the
        snapshot is reported rather than removed, and something that has gone is
        reported rather than recreated. Notes and playlist clips are never touched,
        because a snapshot cannot see them.

        Args:
            snapshot: A snapshot id, or an ISO timestamp to use the newest snapshot at
                      or before it. Defaults to the most recent one.
            apply: False reports the moves. True makes them.
            include_plugins: Also compare plugin parameters, which are reported as
                             unrestorable and are handled by the preset tools.
        """
        return restore_snapshot(
            snapshot=snapshot, apply=apply, include_plugins=include_plugins
        )
