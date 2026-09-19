"""The riff library: save what is in the piano roll, find it, put it back.

Saving reads the piano roll, which costs a script run, because a cached state file
could be minutes old and a riff captured from a stale cache is a riff that never
existed. Recalling writes through the same path the note tools use, so targeting,
verification and the journal all behave the same way.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fl_studio_mcp.musical import riffs
from fl_studio_mcp.tools import piano_roll, score
from fl_studio_mcp.utils import store

if TYPE_CHECKING:
    from fastmcp import FastMCP

DEFAULT_LIMIT = 20
MAX_LIMIT = 200


def load_records() -> dict[str, Any]:
    """Every stored riff, with anything unreadable named rather than raised."""
    return store.list_records("riffs")


def save_riff(
    name: str,
    tags: list[str] | None = None,
    mood: str | None = None,
    channel: int | None = None,
) -> dict[str, Any]:
    """Capture the piano roll as a tagged riff.

    Args:
        name: What to call it.
        tags: Free labels for finding it later.
        mood: One more label, kept separate because producers use it separately.
        channel: The channel whose piano roll holds the phrase. Given, the channel is
            selected first, so the notes come from a known piano roll rather than from
            whichever one has focus.

    Returns:
        The saved record's id, name and summary, or an error naming what was missing.
    """
    if not name or not str(name).strip():
        return {
            "success": False,
            "error": "A riff needs a name. An unnamed riff cannot be found again.",
        }

    state = piano_roll.refresh_and_read_state(channel=channel)
    if state.get("error"):
        return {"success": False, "error": state["error"]}

    notes = state.get("notes") or []
    if not notes:
        return {
            "success": False,
            "error": (
                "The piano roll holds no notes, so there is nothing to save. An empty "
                "riff in the library is noise, so it is refused rather than stored."
            ),
        }

    context = _context(channel)
    instrument = _instrument(state, channel)
    record_id = store.unique_record_id("riffs", str(name))
    record = riffs.make_riff(
        str(name).strip(),
        notes,
        context=context,
        instrument=instrument,
        tags=tags or [],
        mood=mood,
        source={
            "channel": channel if channel is not None else state.get("target_channel"),
            "channel_name": state.get("target_channel_name"),
            "plugin": instrument,
            "ppq": state.get("ppq"),
        },
        record_id=record_id,
    )
    # The tempo is worth recording: a phrase written against 130 BPM sits differently
    # against 90, and a producer searching later will want to know.
    if context.get("tempo") is not None:
        record["tempo"] = context["tempo"]

    try:
        path = store.write_record("riffs", record_id, record)
    except ValueError as error:
        return {"success": False, "error": str(error)}

    summary = riffs.summarise(record)
    summary["file"] = str(path)
    return {
        "success": True,
        "id": record_id,
        "riff": summary,
        "message": (
            f"Saved {record['note_count']} note(s) as {record['name']!r}"
            + (f" in {record['key']['name']}" if record.get("key") else " with no key set")
            + f". Find it with fl_find_riffs, id {record_id}."
        ),
    }


def find_riffs(
    query: str | None = None,
    tags: list[str] | None = None,
    key: str | None = None,
    instrument: str | None = None,
    min_notes: int | None = None,
    limit: int = DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Search the library, newest first.

    Args:
        query: Matched against the name, tags, mood, instrument and key.
        tags: Every tag named has to be present.
        key: A pitch class such as "A", or a key name such as "A minor".
        instrument: A substring of the instrument, plugin or channel name.
        min_notes: Ignore anything shorter than this.
        limit: How many to return, up to MAX_LIMIT.

    Returns:
        Matches as summaries, without their note lists, so the answer stays small
        enough to read.
    """
    listing = load_records()
    capped = max(1, min(int(limit), MAX_LIMIT))
    found = riffs.search(
        listing["records"],
        query=query,
        tags=tags or [],
        key=key,
        instrument=instrument,
        min_notes=min_notes,
        limit=capped,
    )

    result: dict[str, Any] = {
        "success": True,
        "riffs": [riffs.summarise(record) for record in found],
        "total": len(found),
        "library_size": len(listing["records"]),
    }
    if listing["skipped"]:
        result["skipped_files"] = listing["skipped"]
    if not found:
        result["message"] = _nothing_found(query, tags, key, instrument, len(listing["records"]))

    project = _project_key()
    if project:
        result["project_key"] = project
    return result


def recall_riff(
    riff: str,
    channel: int | None = None,
    transpose: bool = True,
    direction: str = "nearest",
    mode: str = "replace",
    verify: bool = True,
) -> dict[str, Any]:
    """Write a stored riff into the piano roll, in this project's key.

    Args:
        riff: The record id, or a name that matches exactly one record.
        channel: Which channel's piano roll to write into. Without one, the notes go
            to whichever piano roll has focus, and the reply says so.
        transpose: Move the phrase into the project's key.
        direction: "nearest", "up" or "down" when transposing.
        mode: "replace" clears the piano roll first, "append" adds to what is there.
        verify: Read the piano roll back and report whether the notes are there.

    Returns:
        What was written, how far it moved, and how many notes were clamped.
    """
    found = _resolve(riff)
    if found.get("error"):
        return {"success": False, "error": found["error"]}

    record = found["record"]
    semitones = 0
    key_note = None
    if transpose:
        project = _project_key()
        record_root = (record.get("key") or {}).get("root")
        if project is None:
            return {
                "success": False,
                "error": (
                    "This project has no key set, because the piano roll's snap to "
                    "scale is off, so there is nothing to transpose into. Turn snap "
                    "to scale on, or call again with transpose=False to write the "
                    "riff as it was saved."
                ),
            }
        if record_root is None:
            key_note = (
                f"{record.get('name')!r} was saved without a key, so it is written as "
                "it was. Nothing was transposed."
            )
        else:
            semitones = riffs.transpose_semitones(
                record_root, project["root"], direction=direction
            )

    notes, clamped = riffs.recall_notes(record, semitones)
    if mode == "replace":
        cleared = piano_roll.send_request({"action": "clear"}, channel=channel)
        if not cleared.get("success"):
            return {
                "success": False,
                "error": f"Could not clear the piano roll first: {cleared.get('error')}",
            }

    written = piano_roll.send_request(
        {"action": "add_notes", "notes": notes, "group_name": record.get("name")},
        wait_for_manual_trigger=piano_roll.RESPONSE_TIMEOUT,
        channel=channel,
        verify=verify,
    )
    if not written.get("success"):
        return {
            "success": False,
            "error": written.get("error") or "The notes did not land.",
            "notes_attempted": len(notes),
        }

    result: dict[str, Any] = {
        "success": True,
        "id": record.get("id"),
        "name": record.get("name"),
        "notes_written": len(notes),
        "transposed_by": semitones,
        "mode": mode,
        "verified": written.get("verified"),
        "verified_notes": written.get("verified_notes"),
        "channel": written.get("target_channel", channel),
        "channel_name": written.get("target_channel_name"),
        "group": written.get("group"),
    }
    if clamped:
        result["clamped_notes"] = clamped
        result["clamped_note"] = (
            f"{clamped} note(s) were clamped to the MIDI range, so the top or bottom of "
            "the phrase is flat. Try direction='down' or 'up' to move it into a range "
            "the instrument has."
        )
    if key_note:
        result["key_note"] = key_note
    result["message"] = _recall_message(record, len(notes), semitones, mode, result)
    return result


def _resolve(riff: str) -> dict[str, Any]:
    """Find one record by id, or by a name that matches exactly one."""
    wanted = str(riff or "").strip()
    if not wanted:
        return {"error": "A riff id or name is required."}

    by_id = store.read_record("riffs", wanted)
    if by_id:
        return {"record": by_id}

    listing = load_records()
    matches = [
        record
        for record in listing["records"]
        if str(record.get("name") or "").lower() == wanted.lower()
    ]
    if not matches:
        return {
            "error": (
                f"No riff called {wanted!r} and no record with that id. Use "
                "fl_find_riffs to see what is in the library."
            )
        }
    if len(matches) > 1:
        ids = ", ".join(str(record.get("id")) for record in matches)
        return {
            "error": (
                f"{len(matches)} riffs are called {wanted!r}, so the name is ambiguous. "
                f"Recall one by id: {ids}."
            )
        }
    return {"record": matches[0]}


def _context(channel: int | None) -> dict[str, Any]:
    """The project context, plus the tempo, which the context read does not carry."""
    context: dict[str, Any] = {}
    try:
        context = dict(score.get_project_context())
    except Exception:  # noqa: BLE001 - a missing context must not stop a save
        context = {}
    context.setdefault("ppq", 96)
    tempo = _tempo()
    if tempo is not None:
        context["tempo"] = tempo
    return context


def _tempo() -> float | None:
    """The project tempo, through the tempo tool's own reader."""
    from fl_studio_mcp.tools.tempo import get_tempo

    reply = get_tempo()
    bpm = reply.get("bpm")
    return round(float(bpm), 3) if bpm is not None else None


def _instrument(state: dict[str, Any], channel: int | None) -> str | None:
    """What the phrase came from, which is how it is found again.

    The user-facing name is preferred over the plugin's own name, because that is what
    the producer sees on the channel and what they will search for: a FLEX channel
    called "808 Astronomic" should not be filed as "FLEX".
    """
    from fl_studio_mcp.utils.connection import get_connection

    target = channel if channel is not None else state.get("target_channel")
    if target is None:
        return state.get("target_channel_name")
    reply = get_connection().send_command(
        "plugins.getName", {"index": target, "slot_index": -1, "use_global": True}, timeout=5.0
    )
    name = reply.get("user_name") or reply.get("name")
    if name and str(name).strip():
        return str(name)
    return state.get("target_channel_name")


def _project_key() -> dict[str, Any] | None:
    """The project's key as the patterns layer reports it, or None when unset."""
    try:
        context = score.get_project_context()
    except Exception:  # noqa: BLE001 - an unreadable key means no transposition
        return None
    if not context.get("scale_set") or context.get("root_note") is None:
        return None
    return {"root": int(context["root_note"]), "name": context.get("key")}


def _nothing_found(
    query: str | None,
    tags: list[str] | None,
    key: str | None,
    instrument: str | None,
    library_size: int,
) -> str:
    if not library_size:
        return (
            "The riff library is empty. Save something with fl_save_riff, which captures "
            "whatever the piano roll holds."
        )
    asked = [
        f"query={query!r}" if query else None,
        f"tags={tags}" if tags else None,
        f"key={key!r}" if key else None,
        f"instrument={instrument!r}" if instrument else None,
    ]
    return (
        f"Nothing matched {', '.join(part for part in asked if part)} out of "
        f"{library_size} stored riff(s). Loosen one of those filters and try again."
    )


def _recall_message(
    record: dict[str, Any],
    count: int,
    semitones: int,
    mode: str,
    result: dict[str, Any],
) -> str:
    where = (
        f"channel {result['channel']} ({result['channel_name']})"
        if result.get("channel") is not None
        else "the focused piano roll"
    )
    moved = (
        f", moved {semitones:+d} semitones into this project's key" if semitones else ""
    )
    replaced = "after clearing it" if mode == "replace" else "without clearing it"
    confirmed = (
        f" Read back and confirmed {result['verified_notes']} note(s)."
        if result.get("verified")
        else ""
    )
    return (
        f"Wrote {count} note(s) from {record.get('name')!r} into {where}{moved}, "
        f"{replaced}.{confirmed}"
    )


def register_riff_tools(mcp: FastMCP) -> None:
    """Register the riff library tools."""

    @mcp.tool()
    def fl_save_riff(
        name: str,
        tags: list[str] | None = None,
        mood: str | None = None,
        channel: int | None = None,
    ) -> dict:
        """Save the notes currently in the piano roll as a tagged riff.

        The notes are stored exactly as the piano roll reports them, expression flags
        included, together with the project's key, meter and tempo and the instrument
        they came from. That is what makes them findable later and recallable in
        another key.

        An empty piano roll is refused rather than saved, because an empty riff in a
        library is noise.

        Args:
            name: What to call it.
            tags: Free labels, matched case-insensitively when searching.
            mood: One more label, kept separate because producers use it separately.
            channel: The channel whose piano roll holds the phrase. Given, that channel
                    is selected first, so the notes come from a known piano roll.
        """
        return save_riff(name, tags=tags, mood=mood, channel=channel)

    @mcp.tool()
    def fl_find_riffs(
        query: str | None = None,
        tags: list[str] | None = None,
        key: str | None = None,
        instrument: str | None = None,
        min_notes: int | None = None,
        limit: int = DEFAULT_LIMIT,
    ) -> dict:
        """Search the riff library, newest first.

        Results are summaries without note lists, so the answer stays readable. Use the
        id it returns with fl_recall_riff.

        Args:
            query: Matched against the name, tags, mood, instrument and key.
            tags: Every tag named has to be present.
            key: A pitch class such as "A", or a key name such as "A minor".
            instrument: A substring of the instrument, plugin or channel name.
            min_notes: Ignore anything shorter than this.
            limit: How many to return, up to 200.
        """
        return find_riffs(
            query=query,
            tags=tags,
            key=key,
            instrument=instrument,
            min_notes=min_notes,
            limit=limit,
        )

    @mcp.tool()
    def fl_recall_riff(
        riff: str,
        channel: int | None = None,
        transpose: bool = True,
        direction: str = "nearest",
        mode: str = "replace",
        verify: bool = True,
    ) -> dict:
        """Write a stored riff into the piano roll, in this project's key.

        Transposing uses the key the riff was saved in and the key this project is in,
        taking the shorter way round so a phrase does not leap an octave to reach a
        neighbouring key. If the riff was saved without a key, or this project has none
        set, the notes are written as they were and the reply says so rather than
        guessing a key.

        Notes pushed outside the MIDI range are clamped and counted, so a phrase that
        came back flat at the top tells you instead of hiding it.

        Args:
            riff: The record id, or a name that matches exactly one record.
            channel: Which channel's piano roll to write into. Without one the notes go
                    to whichever piano roll has focus, which the reply states.
            transpose: Move the phrase into the project's key.
            direction: "nearest", "up" or "down".
            mode: "replace" clears the piano roll first, "append" adds to what is there.
            verify: Read the piano roll back and report whether the notes are there.
        """
        return recall_riff(
            riff,
            channel=channel,
            transpose=transpose,
            direction=direction,
            mode=mode,
            verify=verify,
        )
