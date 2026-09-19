"""Piano Roll tools for FL Studio - persistent note placement.

This module provides tools for creating, editing, and deleting notes in
FL Studio's piano roll. Unlike MIDI real-time note triggering, these tools
create persistent notes by communicating with FL Studio's Piano Roll scripting
API via JSON files.

Communication flow:
1. MCP server writes requests to mcp_request.json
2. Keystroke trigger (Cmd+Opt+Y) executes FL Studio's ComposeWithLLM script
3. Script reads the request, modifies the piano roll, exports
   piano_roll_state.json, and writes its reply to mcp_response.json
4. This module reads that reply and reports what actually happened

Step 4 is why this module looks the way it does. It used to be missing: the old
code wrote a request, sent a keystroke, slept two seconds and reported success
unconditionally, so editing the wrong piano roll, lacking Accessibility
permission, and never having installed the script all looked identical.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from fl_studio_mcp.utils.connection import get_connection
from fl_studio_mcp.utils.fl_trigger import get_trigger, trigger_fl_studio
from fl_studio_mcp.utils.paths import piano_roll_scripts_dir

if TYPE_CHECKING:
    from fastmcp import FastMCP

# How long to wait for the piano roll script's reply. The script itself is fast;
# the wait is dominated by the keystroke and FL Studio taking focus.
RESPONSE_TIMEOUT = 5.0

# Poll interval while waiting for the reply.
POLL_INTERVAL = 0.005


def _request_file() -> Path:
    """Get the path to the MCP request JSON file."""
    return piano_roll_scripts_dir() / "mcp_request.json"


def _response_file() -> Path:
    """Get the path to the MCP response JSON file."""
    return piano_roll_scripts_dir() / "mcp_response.json"


def _state_file() -> Path:
    """Get the path to the piano roll state JSON file."""
    return piano_roll_scripts_dir() / "piano_roll_state.json"


def _midi_to_note_name(midi: int) -> str:
    """Convert MIDI note number to note name."""
    note_names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    return f"{note_names[midi % 12]}{(midi // 12) - 1}"


def _read_reply(response_file: Path) -> dict | None:
    """Read a reply, or None if there is not a complete one yet.

    The script writes this file in place, so a poll can catch it mid write. A
    reply that does not parse is treated as unfinished rather than as an error.
    """
    try:
        text = response_file.read_text()
    except OSError:
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def target(channel: int) -> dict:
    """Select a channel and open its piano roll, so writes land somewhere known.

    Args:
        channel: Global channel index in the Channel Rack.

    Returns:
        The controller's reply, with "targeted", "selected", "channel_name" and
        "piano_roll_visible", or an "error". A caller must not trigger the piano
        roll script unless this succeeded and "selected" matches "targeted".
    """
    return get_connection().send_command(
        "channels.selectPianoRoll", {"index": channel}, timeout=5.0
    )


def send_request(
    request: dict,
    timeout: float = RESPONSE_TIMEOUT,
    wait_for_manual_trigger: float = 0.0,
    channel: int | None = None,
) -> dict:
    """Send one request to the piano roll script and return its reply.

    Sequence: clear any stale reply, write the request, trigger the script, then
    poll for a reply carrying this request's id. Every step can fail, and every
    failure comes back with a specific reason.

    Args:
        request: The request dict, with an "action" key. An "id" is added when
            the caller did not supply one, so the reply can be matched to it.
        timeout: Seconds to wait for the reply.
        wait_for_manual_trigger: Seconds to keep waiting when the automatic
            keystroke could not be delivered. The request is already on disk, so
            pressing the hotkey by hand still runs it. This turns a hard failure
            into a slower success, which matters on a machine where the
            Accessibility permission has not been granted.
        channel: Channel Rack index to write into. When given, the channel is
            selected and its piano roll opened first, and the script is not
            triggered unless FL confirms the selection. Without it, the notes go
            to whichever piano roll has focus, which is why the reply says so.

    Returns:
        The script's reply, or a dict with "success": False and a specific
        "error". A FL-side failure is reported, not raised.
    """
    scripts_dir = piano_roll_scripts_dir()
    request_file = scripts_dir / "mcp_request.json"
    response_file = scripts_dir / "mcp_response.json"

    request = dict(request)
    request.setdefault("id", uuid.uuid4().hex)

    # Aim before writing anything. A trigger without a confirmed target would run
    # the script against whichever piano roll happens to be focused.
    target_info: dict = {}
    if channel is not None:
        targeted = target(channel)
        if "error" in targeted:
            return {
                "success": False,
                "error": (
                    f"Could not target channel {channel}, so the piano roll script "
                    f"was not triggered: {targeted['error']}"
                ),
            }
        if targeted.get("selected") != channel:
            return {
                "success": False,
                "error": (
                    f"Asked FL Studio to select channel {channel} but it reports "
                    f"channel {targeted.get('selected')} selected, so the piano roll "
                    "script was not triggered. Running it now would edit the wrong "
                    "piano roll."
                ),
            }
        target_info = {
            "target_channel": channel,
            "target_channel_name": targeted.get("channel_name"),
        }
        # Recorded in the file too, so a request waiting for a manual trigger says
        # where it was meant to go rather than only where it will actually land.
        request["channel"] = channel

    # A reply left over from an earlier call must not be read as this one's.
    if response_file.exists():
        response_file.unlink()
    # The file holds exactly this request. Appending to a stale queue is what made
    # previously failed requests replay on the next success.
    request_file.write_text(json.dumps([request], indent=2))

    trigger = get_trigger()
    trigger_error = None
    if not trigger_fl_studio(delay=0):
        trigger_error = trigger.last_error or "the keystroke could not be delivered"
        if wait_for_manual_trigger <= 0:
            return {
                "success": False,
                "error": (
                    f"Could not send the trigger keystroke to FL Studio: "
                    f"{trigger_error} You can also press {trigger.keystroke} in "
                    "FL Studio with a piano roll focused, and the queued request "
                    "will run."
                ),
            }
        timeout = max(timeout, wait_for_manual_trigger)

    deadline = time.time() + timeout
    while time.time() < deadline:
        reply = _read_reply(response_file)
        if reply is not None and reply.get("id") in (None, request["id"]):
            return {**reply, **target_info}
        time.sleep(POLL_INTERVAL)

    if trigger_error:
        return {
            "success": False,
            "error": (
                f"Could not send the trigger keystroke to FL Studio: "
                f"{trigger_error} The request is queued, so pressing "
                f"{trigger.keystroke} in FL Studio will still run it."
            ),
        }
    return {
        "success": False,
        "error": (
            f"No reply from the piano roll script within {timeout}s. Check that "
            "ComposeWithLLM is installed in FL Studio's Piano roll scripts "
            "folder, that a piano roll window had focus, and that this process "
            "has Accessibility permission to send the trigger keystroke."
        ),
    }


def read_state() -> dict | None:
    """Read the exported piano roll state, or None if there is not one."""
    state_file = _state_file()
    if not state_file.exists():
        return None
    try:
        return json.loads(state_file.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def refresh_and_read_state(
    timeout: float = RESPONSE_TIMEOUT, channel: int | None = None
) -> dict:
    """Trigger the script, then read the state it exports.

    Reading without triggering returned whatever the last run happened to leave
    behind, which could be minutes or days old.
    """
    reply = send_request({"action": "get_state"}, timeout=timeout, channel=channel)
    state = read_state()
    if state is None:
        reason = reply.get("error") or "the script did not export any state"
        return {"error": f"No piano roll state available: {reason}"}
    for note in state.get("notes", []):
        if "midi" in note:
            note["note_name"] = _midi_to_note_name(note["midi"])
    if channel is not None:
        state["target_channel"] = channel
        state["target_channel_name"] = reply.get("target_channel_name")
    return state


def _trigger_note() -> str:
    """A suffix noting whether auto-trigger exists on this platform."""
    trigger = get_trigger()
    if not trigger.is_supported:
        return (
            f" Auto-trigger is not supported on {trigger.platform}. "
            f"Press {trigger.keystroke} manually."
        )
    return ""


def register_piano_roll_tools(mcp: FastMCP) -> None:
    """Register piano roll tools with the MCP server."""

    @mcp.tool()
    def fl_send_notes(
        notes: list[dict],
        channel: int | None = None,
        mode: str = "add",
    ) -> str:
        """Add or replace notes in the FL Studio piano roll.

        Creates persistent notes in whichever piano roll has focus. Select the
        channel first if you need a specific channel's piano roll.

        Args:
            notes: List of note objects with properties:
                   - midi (int): MIDI note number (60 = C4/Middle C)
                   - duration (float): Length in quarter notes (1.0 = quarter note)
                   - time (float, optional): Start position in quarter notes (default 0)
                   - velocity (float, optional): Velocity 0.0-1.0 (default 0.8)
                   - slide (bool, optional): FL slide note, for 303-style lines
                   - porta (bool, optional): Portamento
                   - pitchofs (float, optional): Fine pitch offset
                   - fcut (float, optional): Per-note filter cutoff
                   - fres (float, optional): Per-note filter resonance
                   - pan (float, optional): Per-note pan, -1.0 to 1.0
                   - group (int, optional): Note group, for removing a phrase later
            mode: "add" to add notes, "replace" to clear existing notes first
            channel: Channel Rack index to write into. Give this: the piano roll
                     window shows whichever channel is selected, so without it the
                     notes land in whichever piano roll happens to have focus. The
                     reply names the channel that was targeted.

        Reports what actually landed, read back from FL Studio, or a specific
        failure. It does not report success it has not confirmed.

        Example:
            [
                {"midi": 60, "duration": 1.0, "time": 0},
                {"midi": 64, "duration": 1.0, "time": 0},
                {"midi": 67, "duration": 1.0, "time": 0},
            ]
        """
        if not notes:
            raise ValueError("No notes provided")

        for index, note in enumerate(notes):
            if "midi" not in note:
                raise ValueError(f"Note {index} is missing its 'midi' field")
            if "duration" not in note:
                raise ValueError(f"Note {index} is missing its 'duration' field")
            note.setdefault("time", 0)
            note.setdefault("velocity", 0.8)

        if mode == "replace":
            cleared = send_request({"action": "clear"}, channel=channel)
            if not cleared.get("success"):
                return f"Failed to clear the piano roll: {cleared.get('error')}"

        result = send_request(
            {"action": "add_notes", "notes": notes},
            wait_for_manual_trigger=RESPONSE_TIMEOUT,
            channel=channel,
        )
        if not result.get("success"):
            return f"Notes did not land: {result.get('error')}"

        summary = ", ".join(
            f"{_midi_to_note_name(n['midi'])}@{n.get('time', 0)}" for n in notes[:5]
        )
        if len(notes) > 5:
            summary += f", ... ({len(notes) - 5} more)"
        landed = result.get("notes_added", 0)
        return f"Added {landed} note(s): {summary}.{_trigger_note()}"

    @mcp.tool()
    def fl_send_chord(
        midi_notes: list[int],
        time: float = 0,
        duration: float = 1.0,
        velocity: float = 0.8,
        channel: int | None = None,
    ) -> str:
        """Add a chord (multiple simultaneous notes) to the FL Studio piano roll.

        Args:
            midi_notes: List of MIDI note numbers (e.g. [60, 64, 67] for C major)
            time: Start position in quarter notes (default 0)
            duration: Length in quarter notes for all notes (default 1.0)
            velocity: Velocity 0.0-1.0 for all notes (default 0.8)
            channel: Channel Rack index to write into. Give this: the piano roll
                     window shows whichever channel is selected, so without it the
                     notes land in whichever piano roll happens to have focus. The
                     reply names the channel that was targeted.

        Example:
            fl_send_chord([60, 64, 67], time=0, duration=1.0)
        """
        if not midi_notes:
            raise ValueError("No MIDI notes provided")

        result = send_request(
            {
                "action": "add_chord",
                "time": time,
                "duration": duration,
                "notes": [{"midi": midi, "velocity": velocity} for midi in midi_notes],
            },
            wait_for_manual_trigger=RESPONSE_TIMEOUT,
            channel=channel,
        )
        if not result.get("success"):
            return f"Chord did not land: {result.get('error')}"

        names = ", ".join(_midi_to_note_name(n) for n in midi_notes)
        return (
            f"Added chord [{names}] at beat {time}, duration {duration}."
            f"{_trigger_note()}"
        )

    @mcp.tool()
    def fl_delete_notes(notes: list[dict], channel: int | None = None) -> str:
        """Delete specific notes from the FL Studio piano roll.

        Args:
            notes: List of notes to delete, matching on midi and time:
                   - midi (int): MIDI note number
                   - time (float): Start position in quarter notes
            channel: Channel Rack index to write into. Give this: the piano roll
                     window shows whichever channel is selected, so without it the
                     notes land in whichever piano roll happens to have focus. The
                     reply names the channel that was targeted.

        Example:
            [{"midi": 60, "time": 0}, {"midi": 64, "time": 0}]
        """
        if not notes:
            raise ValueError("No notes specified for deletion")

        result = send_request(
            {"action": "delete_notes", "notes": notes},
            wait_for_manual_trigger=RESPONSE_TIMEOUT,
            channel=channel,
        )
        if not result.get("success"):
            return f"Deletion failed: {result.get('error')}"

        deleted = result.get("notes_deleted", 0)
        if deleted == 0:
            return (
                "Nothing matched those notes. Check the pitch and the time, and "
                "note that time is in quarter notes, not ticks."
            )
        return f"Deleted {deleted} note(s).{_trigger_note()}"

    @mcp.tool()
    def fl_clear_piano_roll(channel: int | None = None) -> str:
        """Clear all notes from the FL Studio piano roll.

        Args:
            channel: Channel Rack index whose piano roll to clear. Give this: the
                     piano roll window shows whichever channel is selected, so
                     without it the wrong piano roll may be cleared.
        """
        result = send_request(
            {"action": "clear"},
            wait_for_manual_trigger=RESPONSE_TIMEOUT,
            channel=channel,
        )
        if not result.get("success"):
            return f"Could not clear the piano roll: {result.get('error')}"
        return f"Cleared {result.get('notes_deleted', 0)} note(s).{_trigger_note()}"

    @mcp.tool()
    def fl_get_piano_roll_state(channel: int | None = None) -> dict:
        """Get the notes currently in the FL Studio piano roll, refreshed.

        Triggers FL Studio to export the current state before reading it, so the
        result describes the piano roll now rather than whatever the last run
        happened to leave behind.

        Args:
            channel: Channel Rack index whose piano roll to read. Give this: the
                     piano roll window shows whichever channel is selected, so
                     without it the state read is whichever piano roll has focus.

        Returns:
            ppq: Pulses per quarter note, which is ticks per beat
            noteCount: How many notes the piano roll holds
            notes: Every note, with all sixteen flpianoroll properties
            target_channel: The channel that was targeted, when one was given
        """
        return refresh_and_read_state(channel=channel)

    @mcp.tool()
    def fl_get_piano_roll_info() -> dict:
        """Get information about the Piano Roll integration status.

        Returns platform info, file paths, and whether auto-triggering works.
        """
        trigger = get_trigger()
        return {
            "platform": trigger.platform,
            "auto_trigger_supported": trigger.is_supported,
            "trigger_keystroke": trigger.keystroke,
            "scripts_dir": str(piano_roll_scripts_dir()),
            "request_file": str(_request_file()),
            "response_file": str(_response_file()),
            "state_file": str(_state_file()),
            "request_file_exists": _request_file().exists(),
            "response_file_exists": _response_file().exists(),
            "state_file_exists": _state_file().exists(),
        }
