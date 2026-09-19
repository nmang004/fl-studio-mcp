# name=FL Studio MCP Controller
# url=https://github.com/karl-andres/fl-studio-mcp
# supportedDevices=FL Studio MCP

"""
FL Studio MIDI Controller Script for MCP Integration.

This script runs inside FL Studio and receives MIDI trigger messages from the
MCP server. When triggered, it reads a command from a JSON file, executes the
corresponding FL Studio API function, and writes the response to another JSON file.

Communication flow:
1. MCP server writes command to mcp_command.json
2. MCP server sends MIDI note 127 (trigger)
3. This script receives the trigger via OnMidiMsg()
4. Script reads command JSON, executes FL Studio API
5. Script writes response to mcp_response.json
6. MCP server reads response
"""

import json
import os
import sys
from pathlib import Path

# FL Studio API modules (available when running inside FL Studio)
import channels
import device
import general
import mixer
import patterns
import plugins
import transport
import ui

SETTINGS_DIR_ENV = "FL_STUDIO_MCP_SETTINGS_DIR"


def _get_settings_dir() -> Path:
    """Get the FL Studio Settings directory.

    FL Studio's Python environment doesn't support __file__, so the path is
    constructed from the platform's standard location. FL_STUDIO_MCP_SETTINGS_DIR
    overrides it, which the test harness uses to keep every file inside a
    temporary directory.

    This duplicates fl_studio_mcp.utils.paths on purpose: the controller runs
    inside FL and cannot import the server package.
    """
    override = os.environ.get(SETTINGS_DIR_ENV)
    if override:
        return Path(override).expanduser()

    home = Path.home()
    candidates = [home / "Documents" / "Image-Line" / "FL Studio" / "Settings"]
    if sys.platform == "win32":
        # Windows machines with a Microsoft account often keep Documents inside
        # OneDrive, where the Image-Line folder follows it.
        candidates.append(
            home / "OneDrive" / "Documents" / "Image-Line" / "FL Studio" / "Settings"
        )

    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return candidates[0]


# File paths for JSON communication
#
# This directory is not created here, and must not be: FL Studio's Python
# sandbox blocks Path.mkdir, os.makedirs, os.replace, os.rename, os.remove,
# Path.unlink, Path.glob and open() with "SystemError: <...> returned NULL
# without setting an exception". A blocked call at module scope stops the script
# from importing at all, which looks exactly like FL Studio not running. The
# server creates this directory with fl_studio_mcp.utils.paths.hardware_dir(),
# and the installer puts this script inside it. Path.write_text is the one write
# that works, which is why responses are written rather than renamed into place.
SCRIPT_DIR = _get_settings_dir() / "Hardware" / "FLStudioMCP"
COMMAND_FILE = SCRIPT_DIR / "mcp_command.json"
RESPONSE_FILE = SCRIPT_DIR / "mcp_response.json"

# MIDI trigger note
TRIGGER_NOTE = 127

# From the stubs: ui.showWindow indices. The piano roll is window 3.
WID_PIANO_ROLL = 3


def OnInit():
    """Called when the script is loaded."""
    print("FL Studio MCP Controller initialized")
    print(f"Command file: {COMMAND_FILE}")
    print(f"Response file: {RESPONSE_FILE}")


def OnDeInit():
    """Called when the script is unloaded."""
    print("FL Studio MCP Controller deinitialized")


def OnMidiMsg(event):
    """Called when a MIDI message is received."""
    # Check for trigger note (Note On, note 127)
    if event.midiId == 0x90 and event.data1 == TRIGGER_NOTE and event.data2 > 0:
        execute_pending_command()
        event.handled = True


def OnIdle():
    """Called periodically when FL Studio is idle."""
    pass  # Required FL Studio API hook; no polling needed


def execute_pending_command():
    """Read command from JSON file, execute it, and write response.

    Failure is reported as failure. An unknown action or an exception inside a
    handler used to be merged into `{"success": True, "error": ...}`, which was
    reproduced against live FL Studio and made every error invisible to callers.
    """
    response = {"success": False, "error": None}

    try:
        # Read command file
        if not COMMAND_FILE.exists():
            response["error"] = "No command file found"
            write_response(response)
            return

        command_text = COMMAND_FILE.read_text()
        command = json.loads(command_text)

        action = command.get("action", "")
        params = command.get("params", {})
        request_id = command.get("id")

        # Execute command and get result
        result = dispatch_command(action, params)
        failed = "error" in result
        response = {"success": not failed, "id": request_id, **result}

    except json.JSONDecodeError as e:
        response["error"] = f"Invalid JSON in command file: {e}"
    except ValueError as e:
        # A handler refusing bad input. The message is already written for the
        # caller, so pass it through unwrapped.
        response["error"] = str(e)
    except Exception as e:
        response["error"] = f"Error executing command: {e}"

    write_response(response)


def write_response(response: dict):
    """Write response to JSON file.

    The response ends with a newline so the polling server can tell a finished
    response from one it caught mid write. See
    fl_studio_mcp.utils.midi_connection.MIDIResponseReader for why the write
    cannot be made atomic from inside FL: the sandbox disables the rename
    syscalls, so os.replace and os.rename both raise SystemError here. Writing
    through a Path is the one form of file write this sandbox allows.
    """
    try:
        RESPONSE_FILE.write_text(json.dumps(response, indent=2) + "\n")
    except Exception as e:
        print(f"Error writing response: {e}")


def dispatch_command(action: str, params: dict) -> dict:
    """Route a command and return its result, reporting refusals as errors.

    A handler that rejects its input raises ValueError with a message written for
    the caller. Turning it into an error dict here means every caller, including
    the batch runner, sees a refusal the same way it sees any other failure.
    """
    try:
        return _route_command(action, params)
    except ValueError as e:
        return {"error": str(e)}


def _route_command(action: str, params: dict) -> dict:
    """Send a command to its handler.

    Raises ValueError for a refused call. Returns an error dict when FL reports
    the project is not safe to edit, which is checked here rather than in the
    transport so that every entry point is covered, including a direct call from
    the batch runner or from a test.
    """
    refusal = _check_editable(action)
    if refusal is not None:
        return refusal

    # System commands
    if action == "system.getInfo":
        return handle_system_get_info()
    elif action == "system.ping":
        return handle_system_ping()
    elif action == "system.batch":
        return handle_system_batch(params)

    # Routing and metering commands
    elif action == "mixer.getRouting":
        return handle_mixer_get_routing(params)
    elif action == "mixer.setRouting":
        return handle_mixer_set_routing(params)
    elif action == "mixer.getLevels":
        return handle_mixer_get_levels(params)

    # EQ commands
    elif action == "mixer.getEq":
        return handle_mixer_get_eq(params)
    elif action == "mixer.setEqBands":
        return handle_mixer_set_eq_bands(params)

    # Pattern commands
    elif action == "patterns.getAll":
        return handle_patterns_get_all()
    elif action == "patterns.setName":
        return handle_patterns_set_name(params)
    elif action == "patterns.setColor":
        return handle_patterns_set_color(params)
    elif action == "patterns.select":
        return handle_patterns_select(params)
    elif action == "patterns.clone":
        return handle_patterns_clone(params)
    elif action == "patterns.createEmpty":
        return handle_patterns_create_empty(params)

    # Undo commands
    elif action == "general.saveUndo":
        return handle_general_save_undo(params)
    elif action == "general.undo":
        return handle_general_undo(params)
    elif action == "general.getUndoHistoryCount":
        return handle_general_get_undo_history_count(params)
    elif action == "general.getUndoHistoryLast":
        return handle_general_get_undo_history_last(params)
    elif action == "general.undoUpDown":
        return handle_general_undo_up_down(params)
    elif action == "system.sysExProbe":
        return handle_system_sysex_probe(params)

    # Transport commands
    elif action == "transport.start":
        return handle_transport_start()
    elif action == "transport.stop":
        return handle_transport_stop()
    elif action == "transport.record":
        return handle_transport_record()
    elif action == "transport.getStatus":
        return handle_transport_get_status()
    elif action == "transport.setPosition":
        return handle_transport_set_position(params)
    elif action == "transport.getLength":
        return handle_transport_get_length()
    elif action == "transport.setLoopMode":
        return handle_transport_set_loop_mode(params)
    elif action == "transport.setPlaybackSpeed":
        return handle_transport_set_playback_speed(params)

    # Mixer commands
    elif action == "mixer.getTrackCount":
        return handle_mixer_get_track_count()
    elif action == "mixer.getTrackInfo":
        return handle_mixer_get_track_info(params)
    elif action == "mixer.getAllTracks":
        return handle_mixer_get_all_tracks(params)
    elif action == "mixer.setTrackVolume":
        return handle_mixer_set_track_volume(params)
    elif action == "mixer.setTrackPan":
        return handle_mixer_set_track_pan(params)
    elif action == "mixer.muteTrack":
        return handle_mixer_mute_track(params)
    elif action == "mixer.soloTrack":
        return handle_mixer_solo_track(params)
    elif action == "mixer.armTrack":
        return handle_mixer_arm_track(params)
    elif action == "mixer.setTrackName":
        return handle_mixer_set_track_name(params)
    elif action == "mixer.setTrackColor":
        return handle_mixer_set_track_color(params)
    elif action == "mixer.setStereoSep":
        return handle_mixer_set_stereo_sep(params)

    # Channel commands
    elif action == "channels.getCount":
        return handle_channels_get_count(params)
    elif action == "channels.getInfo":
        return handle_channels_get_info(params)
    elif action == "channels.getAll":
        return handle_channels_get_all()
    elif action == "channels.getSelected":
        return handle_channels_get_selected()
    elif action == "channels.select":
        return handle_channels_select(params)
    elif action == "channels.selectOne":
        return handle_channels_select_one(params)
    elif action == "channels.selectPianoRoll":
        return handle_channels_select_piano_roll(params)
    elif action == "channels.getSelectedChannel":
        return handle_channels_get_selected_channel(params)
    elif action == "channels.triggerNote":
        return handle_channels_trigger_note(params)
    elif action == "channels.setVolume":
        return handle_channels_set_volume(params)
    elif action == "channels.setPan":
        return handle_channels_set_pan(params)
    elif action == "channels.mute":
        return handle_channels_mute(params)
    elif action == "channels.solo":
        return handle_channels_solo(params)
    elif action == "channels.setName":
        return handle_channels_set_name(params)
    elif action == "channels.setColor":
        return handle_channels_set_color(params)
    elif action == "channels.routeToMixer":
        return handle_channels_route_to_mixer(params)

    # Step sequencer commands
    elif action == "channels.getGridBit":
        return handle_channels_get_grid_bit(params)
    elif action == "channels.setGridBit":
        return handle_channels_set_grid_bit(params)
    elif action == "channels.getStepSequence":
        return handle_channels_get_step_sequence(params)
    elif action == "channels.setStepSequence":
        return handle_channels_set_step_sequence(params)

    # Plugin commands
    elif action == "plugins.isValid":
        return handle_plugins_is_valid(params)
    elif action == "plugins.getName":
        return handle_plugins_get_name(params)
    elif action == "plugins.getParamCount":
        return handle_plugins_get_param_count(params)
    elif action == "plugins.getParams":
        return handle_plugins_get_params(params)
    elif action == "plugins.getParamValue":
        return handle_plugins_get_param_value(params)
    elif action == "plugins.setParamValue":
        return handle_plugins_set_param_value(params)
    elif action == "plugins.getPresetCount":
        return handle_plugins_get_preset_count(params)
    elif action == "plugins.nextPreset":
        return handle_plugins_next_preset(params)
    elif action == "plugins.prevPreset":
        return handle_plugins_prev_preset(params)
    elif action == "plugins.getColor":
        return handle_plugins_get_color(params)

    else:
        return {"error": f"Unknown action: {action}"}


# =============================================================================
# System Handlers
# =============================================================================


def handle_system_sysex_probe(params: dict) -> dict:
    """Emit a SysEx message back to the host, for research spike T4.

    Answers the one question the stubs cannot: does a SysEx message written by
    `device.midiOutSysex` actually leave FL Studio, and if so, through which
    port?

    The reply is a JSON payload with its bytes shifted clear of the SysEx
    reserved values (0xF0 to 0xF7) and the realtime range (0xF8 and above), so no
    byte in the body can be mistaken for a message boundary. Only ASCII digits
    and separators are used, so a plain decode is enough on the receiving side.

    Note that `device.midiOutSysex` sends to the output interface linked to this
    controller. The caller is responsible for enabling one in FL Studio's MIDI
    Settings; without one there is nothing to send to and the message is lost
    silently, which is exactly the failure this probe is meant to distinguish.
    """
    payload = {
        "api": None,
        "fl": None,
        "assigned": None,
        "port": None,
        "echo": params.get("echo"),
    }
    try:
        payload["api"] = general.getVersion()
    except Exception:
        pass
    try:
        payload["fl"] = ui.getProgTitle()
    except Exception:
        pass
    try:
        payload["assigned"] = device.isAssigned()
    except Exception:
        pass
    try:
        payload["port"] = device.getPortNumber()
    except Exception:
        pass

    try:
        text = json.dumps(payload)
        body = ",".join(str(ord(ch) + 0x38) for ch in text)
        device.midiOutSysex(bytes(0xF0) + body.encode("ascii") + bytes(0xF7))
        sent_sysex = True
    except Exception as e:
        print(f"Error sending sysex probe: {e}")
        sent_sysex = False

    # Also send a plain note message. If this arrives but the SysEx does not,
    # the problem is SysEx-specific rather than a missing output interface.
    sent_note = False
    try:
        device.midiOutMsg(0x9, 0, 36, 100)
        device.midiOutMsg(0x8, 0, 36, 0)
        sent_note = True
    except Exception as e:
        print(f"Error sending note probe: {e}")

    return {"sent": sent_sysex, "sent_note": sent_note, "payload": payload}


def _safe_to_edit():
    """Whether FL is in a state where the project may be mutated.

    `general.safeToEdit` was added in API 29, so on anything older the function
    does not exist. The honest answer there is "unknown", which is None, not
    False and not an exception.
    """
    try:
        return bool(general.safeToEdit())
    except Exception:
        return None


def _require(params: dict, name: str, action: str):
    """Return a required parameter, or raise a ValueError naming it.

    Every handler used to default its index to 0, and index 0 is the Master mixer
    track or the first channel. A caller that forgot the parameter got a confident
    answer about the wrong object, and a write edited the master track of someone's
    project. Refusing is the only safe default.

    Zero is a real index, so only absence is an error, never falsiness.
    """
    if name not in params or params[name] is None:
        raise ValueError(f"{action} requires a '{name}'")
    return params[name]


def _undo_count():
    """Undo history depth, or None where the API does not provide it."""
    try:
        return general.getUndoHistoryCount()
    except Exception:
        return None


def handle_general_save_undo(params: dict) -> dict:
    """Save an undo point.

    general.saveUndo was added in API 29 along with safeToEdit, so an older FL
    cannot do this. Reporting that honestly is better than letting a caller
    believe an edit is undoable when it is not.
    """
    name = params.get("name") or "MCP edit"
    try:
        general.saveUndo(name, 0)
    except Exception as e:
        return {"error": f"general.saveUndo is unavailable: {e}"}
    return {"saved": True, "name": name, "count": _undo_count()}


def handle_general_undo(params: dict) -> dict:
    """Undo one step."""
    general.undo()
    return {"count": _undo_count()}


def handle_general_get_undo_history_count(params: dict) -> dict:
    """Report undo history depth, so a caller can see its own edit appear."""
    return {"count": _undo_count()}


def handle_general_get_undo_history_last(params: dict) -> dict:
    """Report the current position in the undo history.

    The most recent position is 0, and earlier points have higher indexes, so a
    position plus a count is enough to work out where an edit started and ended.
    """
    try:
        return {"last": general.getUndoHistoryLast(), "count": _undo_count()}
    except Exception as e:
        return {"error": f"general.getUndoHistoryLast is unavailable: {e}"}


def handle_general_undo_up_down(params: dict) -> dict:
    """Move several steps through the undo history at once.

    Undoing an edit that produced several history entries needs this rather than
    a single undo(), which is a toggle and moves by one.
    """
    value = params.get("value")
    if value is None:
        return {"error": "general.undoUpDown requires a 'value'"}
    try:
        general.undoUpDown(int(value))
    except Exception as e:
        return {"error": f"general.undoUpDown is unavailable: {e}"}
    return {"moved": int(value), "count": _undo_count()}


# Actions that change the project. Anything not listed is treated as a read, which
# is the safe default in the only direction that matters: refusing a read would
# break diagnostics exactly when a user needs them, while allowing a write can
# corrupt the project.
MUTATING_ACTIONS = frozenset([
    "channels.mute",
    "channels.muteChannel",
    "channels.routeToMixer",
    "channels.select",
    "channels.selectOne",
    "channels.selectPianoRoll",
    "channels.setChannelColor",
    "channels.setChannelName",
    "channels.setChannelPan",
    "channels.setChannelPitch",
    "channels.setChannelVolume",
    "channels.setColor",
    "channels.setGridBit",
    "channels.setName",
    "channels.setPan",
    "channels.setStepSequence",
    "channels.setTargetFxTrack",
    "channels.setVolume",
    "channels.solo",
    "channels.soloChannel",
    "channels.triggerNote",
    "general.restoreUndo",
    "general.restoreUndoLevel",
    "general.undo",
    "general.undoUpDown",
    "mixer.armTrack",
    "mixer.muteTrack",
    "mixer.setEqBands",
    "mixer.setRouting",
    "mixer.setStereoSep",
    "mixer.setTrackColor",
    "mixer.setTrackName",
    "mixer.setTrackPan",
    "mixer.setTrackVolume",
    "mixer.soloTrack",
    "plugins.nextPreset",
    "plugins.prevPreset",
    "plugins.setParamValue",
    # system.batch is deliberately absent. The batch handler checks editability
    # itself, before running anything, so that a refusal can be reported in the
    # shape a batch response has, with the counts a caller reads. Its individual
    # commands are checked here as they are dispatched.
    "patterns.clone",
    "patterns.createEmpty",
    "patterns.select",
    "patterns.setColor",
    "patterns.setName",
    "transport.record",
    "transport.setLoopMode",
    "transport.setPlaybackSpeed",
    "transport.setPosition",
    "transport.start",
    "transport.stop",
])


def _check_editable(action: str):
    """Refuse a mutation when FL reports the project is not safe to edit.

    None means the question could not be asked, which is what API versions below
    29 give. Unknown is not the same as no: refusing on unknown would break every
    install older than API 29, so unknown proceeds.
    """
    if action not in MUTATING_ACTIONS:
        return None
    if _safe_to_edit() is False:
        return {
            "error": (
                "Refusing to edit: FL Studio reports it is not safe to edit the "
                "project right now, so %s was not run. Try again once the current "
                "operation has finished." % action
            )
        }
    return None


def handle_system_batch(params: dict) -> dict:
    """Run several commands from one trigger, inside one undo point.

    The motivation is atomicity and undo grouping rather than speed: a round trip
    is about a millisecond, so batching sixteen notes saves fifteen of them, which
    does not matter, while turning sixteen Ctrl+Z presses into one does.

    A failure stops the batch and the commands after it are reported as skipped
    rather than run, because a half-applied edit that claims success is worse than
    one that says exactly where it stopped.
    """
    commands = params.get("commands")
    if not isinstance(commands, list) or not commands:
        return {"error": "system.batch requires a non-empty 'commands' list"}

    # Checked once for the whole batch as well as per command. Without this a
    # batch would apply its first command and only then discover it may not edit,
    # which is the half-applied edit the batch exists to prevent.
    if _check_editable("system.batch") is not None:
        return {
            "success": False,
            "results": [],
            "executed": 0,
            "failed": 0,
            "undo_name": None,
            "undo_history_count": _undo_count(),
            "error": (
                "Refusing to edit: FL Studio reports it is not safe to edit the "
                "project right now, so no command in this batch was run."
            ),
        }

    for index, command in enumerate(commands):
        if not isinstance(command, dict) or not command.get("action"):
            return {"error": "system.batch command %d has no 'action'" % index}

    name = params.get("name") or "MCP edit"
    # A descriptive name for the caller. Note what this deliberately is not: a
    # general.saveUndo call. That was tried, and measured on FL Studio 2026 it
    # changes nothing: a bare saveUndo adds no history entry (count 34 -> 34) and
    # does not reduce how many undos the edit needs (2 with it, 2 without). The
    # undo history is not a group stack, so claiming to group here would be a
    # guarantee FL does not offer. What the batch does guarantee is one trigger
    # and all-or-nothing execution.
    undo_name = name

    results = []
    executed = 0
    failed = 0

    for command in commands:
        action = command["action"]
        if action == "system.batch":
            results.append({"error": "a batch may not contain a batch"})
            failed += 1
            break

        result = dispatch_command(action, command.get("params", {}))
        results.append(result)

        if "error" in result:
            failed += 1
            break
        executed += 1

    remaining = len(commands) - len(results)
    results.extend({"skipped": True} for _ in range(remaining))

    # The history size, read rather than derived. FL's undo accounting does not
    # predict how many undo calls an edit needs: measured on FL Studio 2026, two
    # mixer writes moved the count by 1 but needed two undo calls, and four step
    # writes moved it by -1 while needing one. Reporting the count lets a caller
    # see the history move without being told a step figure that may be wrong.
    return {
        "success": failed == 0,
        "results": results,
        "executed": executed,
        "failed": failed,
        "undo_name": undo_name,
        "undo_history_count": _undo_count(),
    }


def handle_system_ping() -> dict:
    """Answer a liveness check.

    This is the only action whose purpose is to prove FL answered. It reports the
    environment alongside, so a caller that pings gets the version facts for free
    rather than paying a second round trip for them.
    """
    try:
        api_version = general.getVersion()
    except Exception:
        api_version = None
    try:
        fl_version = ui.getProgTitle()
    except Exception:
        fl_version = None

    return {
        "pong": True,
        "api_version": api_version,
        "fl_version": fl_version,
        "safe_to_edit": _safe_to_edit(),
    }


def handle_system_get_info() -> dict:
    """Report which FL Studio and scripting API version we are talking to.

    The API version gates which functions exist. general.safeToEdit needs API 29,
    for example, so knowing this before calling anything avoids a silent failure.
    Each lookup is guarded separately because an older FL may lack any of them.
    """
    info = {}

    try:
        info["api_version"] = general.getVersion()
    except Exception as e:
        info["api_version"] = None
        info["api_version_error"] = str(e)

    try:
        info["fl_version"] = ui.getVersion()
    except Exception as e:
        info["fl_version"] = None
        info["fl_version_error"] = str(e)

    try:
        info["program_title"] = ui.getProgTitle()
    except Exception:
        info["program_title"] = None

    # Probe a few version-gated functions so callers know what is usable.
    capabilities = {}
    capabilities["safeToEdit"] = _safe_to_edit()
    try:
        capabilities["getCurrentTempo"] = mixer.getCurrentTempo()
    except Exception:
        capabilities["getCurrentTempo"] = None
    info["capabilities"] = capabilities

    return info


# =============================================================================
# Transport Handlers
# =============================================================================


def handle_transport_start() -> dict:
    """Toggle play/pause."""
    transport.start()
    return {"is_playing": transport.isPlaying() == 1}


def handle_transport_stop() -> dict:
    """Stop playback."""
    transport.stop()
    return {"stopped": True}


def handle_transport_record() -> dict:
    """Toggle recording."""
    transport.record()
    return {"is_recording": transport.isRecording() == 1}


def handle_transport_get_status() -> dict:
    """Get transport status."""
    loop_mode = transport.getLoopMode()
    return {
        "is_playing": transport.isPlaying() == 1,
        "is_recording": transport.isRecording() == 1,
        "position": transport.getSongPosHint(),
        "loop_mode": "song" if loop_mode == 1 else "pattern",
    }


def handle_transport_set_position(params: dict) -> dict:
    """Set playback position.

    mode -1 means the units transport.getSongPosHint returns, which is what a
    caller passing a bare position almost always wants. Modes 0 to 5 are ticks,
    milliseconds, seconds and so on, per transport.setSongPos.
    """
    position = params.get("position", 0)
    mode = params.get("mode", -1)
    transport.setSongPos(position, mode)
    return {"position": transport.getSongPosHint()}


def handle_transport_get_length() -> dict:
    """Get song length."""
    return {
        "ticks": transport.getSongLength(3),
        "seconds": transport.getSongLength(2),
        "milliseconds": transport.getSongLength(1),
    }


def handle_transport_set_loop_mode(params: dict) -> dict:
    """Set loop mode.

    transport.setLoopMode takes no arguments and toggles between the two modes,
    so this compares and toggles rather than passing a value through. Calling it
    unconditionally would flip away from the mode the caller asked for.
    """
    mode = str(params.get("mode", "pattern")).lower()
    target = 1 if mode == "song" else 0
    if transport.getLoopMode() != target:
        transport.setLoopMode()
    return {"mode": "song" if transport.getLoopMode() == 1 else "pattern"}


def handle_transport_set_playback_speed(params: dict) -> dict:
    """Set playback speed."""
    speed = params.get("speed", 1.0)
    transport.setPlaybackSpeed(speed)
    return {"speed": speed}


# =============================================================================
# Mixer Handlers
# =============================================================================


# From the stubs: mixer.getTrackPeaks modes. 2 is the maximum of left and right.
MIXER_PEAK_LEFT = 0
MIXER_PEAK_RIGHT = 1
MIXER_PEAK_MAX = 2

# =============================================================================
# Routing and Metering Handlers
# =============================================================================


def _routing_snapshot(track: int) -> dict:
    """Where a track sends.

    There is no function that lists a track's destinations, so every candidate is
    asked whether it is an active send. That is one call per track per read, which
    is why the caller-facing tool reports one track by default rather than all of
    them.
    """
    sends = []
    for destination in range(mixer.trackCount()):
        if destination == track:
            continue
        try:
            active = bool(mixer.getRouteSendActive(track, destination))
        except Exception:
            continue
        if not active:
            continue
        try:
            level = mixer.getRouteToLevel(track, destination)
        except Exception:
            level = None
        sends.append({
            "track": destination,
            "name": mixer.getTrackName(destination),
            "level": level,
            "active": True,
        })
    return {
        "track": track,
        "name": mixer.getTrackName(track),
        "sends": sends,
    }


def handle_mixer_get_routing(params: dict) -> dict:
    """Report where a mixer track sends, or where every track sends."""
    track = params.get("track")
    if track is None:
        return {
            "tracks": [_routing_snapshot(i) for i in range(mixer.trackCount())]
        }
    track = int(track)
    refusal = _check_track_index(track, "mixer.getRouting")
    if refusal is not None:
        return refusal
    return _routing_snapshot(track)


def handle_mixer_set_routing(params: dict) -> dict:
    """Route a track to destinations, or remove those routings.

    Only the destinations the caller names are touched, so a send they did not
    mention keeps its level. A track routing into itself is refused, because that
    is a feedback loop rather than a routing decision.
    """
    track = _require(params, "track", "mixer.setRouting")
    sends = params.get("sends")
    if not isinstance(sends, list) or not sends:
        return {"error": "mixer.setRouting requires a non-empty 'sends' list"}

    refusal = _check_track_index(track, "mixer.setRouting")
    if refusal is not None:
        return refusal

    count = mixer.trackCount()
    for entry in sends:
        if not isinstance(entry, dict) or "track" not in entry:
            return {"error": "mixer.setRouting: every entry needs a 'track'"}
        destination = int(entry["track"])
        if not 0 <= destination < count:
            return {
                "error": (
                    "mixer.setRouting: destination %d does not exist. This project "
                    "has %d tracks, indexed 0 to %d."
                    % (destination, count, count - 1)
                )
            }
        if destination == track:
            return {
                "error": (
                    "mixer.setRouting: track %d cannot send to itself, which would "
                    "be a feedback loop." % track
                )
            }

        if entry.get("remove"):
            mixer.setRouteTo(track, destination, 0)
        else:
            mixer.setRouteTo(track, destination, 1)
            if "level" in entry:
                mixer.setRouteToLevel(track, destination, float(entry["level"]))

    return _routing_snapshot(track)


def handle_mixer_get_levels(params: dict) -> dict:
    """Sample peak levels, reporting the loudest value seen per track.

    mixer.getTrackPeaks returns the value right now: 0.0 is silence, 1.0 is 0 dB,
    and above 1.0 is clipping. Several readings are taken back to back and the
    loudest is kept, because one reading while stopped is always silence.

    The readings are back to back rather than spaced in time, because the
    controller runs on FL's MIDI thread and sleeping there would stall FL. A
    caller wanting a window longer than a few milliseconds should call this
    repeatedly during playback and keep the loudest result itself.
    """
    tracks = params.get("tracks")
    if tracks is None:
        tracks = list(range(mixer.trackCount()))
    if not isinstance(tracks, list) or not tracks:
        return {"error": "mixer.getLevels: 'tracks' must be a non-empty list"}

    samples = params.get("samples", 1)
    try:
        samples = int(samples)
    except (TypeError, ValueError):
        return {"error": "mixer.getLevels: 'samples' must be a whole number"}
    if samples < 1:
        return {"error": "mixer.getLevels: 'samples' must be at least 1"}

    count = mixer.trackCount()
    for index in tracks:
        if not 0 <= int(index) < count:
            return {
                "error": (
                    "mixer.getLevels: track %s does not exist. This project has %d "
                    "tracks, indexed 0 to %d." % (index, count, count - 1)
                )
            }

    levels = []
    for index in tracks:
        index = int(index)
        peak = 0.0
        for _ in range(samples):
            try:
                # Mode 2 is the maximum of left and right, which is what a level
                # meter shows.
                reading = mixer.getTrackPeaks(index, MIXER_PEAK_MAX)
            except Exception:
                reading = 0.0
            if reading > peak:
                peak = reading
        levels.append({
            "track": index,
            "name": mixer.getTrackName(index),
            "peak": peak,
            "clipping": peak > 1.0,
        })

    return {"levels": levels, "samples": samples}


# =============================================================================
# EQ Handlers
# =============================================================================


# From the stubs: mixer.getEqFrequency and getEqGain take a mode selecting the
# form of the answer. The plain value is what a caller reasoning about the shape
# of a mix wants, and it is the default.
EQ_MODE_DEFAULT = 0


def _eq_band(track: int, band: int) -> dict:
    """One band's settings, with each property read guarded.

    An unreadable property reports None rather than losing the whole band, so a
    partly readable EQ is still useful.
    """
    entry = {"band": band}
    for key, reader in (
        ("gain", lambda: mixer.getEqGain(track, band, EQ_MODE_DEFAULT)),
        ("frequency", lambda: mixer.getEqFrequency(track, band, EQ_MODE_DEFAULT)),
        ("bandwidth", lambda: mixer.getEqBandwidth(track, band)),
    ):
        try:
            entry[key] = reader()
        except Exception:
            entry[key] = None
    return entry


def _eq_snapshot(track: int) -> dict:
    """The whole EQ for a track, which is one round trip rather than twenty one."""
    count = mixer.getEqBandCount()
    return {
        "track": track,
        "name": mixer.getTrackName(track),
        "band_count": count,
        "bands": [_eq_band(track, band) for band in range(count)],
    }


def handle_mixer_get_eq(params: dict) -> dict:
    """Read every band of a mixer track's EQ.

    EQ is seven bands of three properties each, so one tool per property would be
    twenty one round trips to answer one question. The band count is read from FL
    rather than assumed, because a hardcoded seven would be wrong on a version
    that changed it.
    """
    track = _require(params, "track", "mixer.getEq")
    refusal = _check_track_index(track, "mixer.getEq")
    if refusal is not None:
        return refusal
    return _eq_snapshot(track)


def handle_mixer_set_eq_bands(params: dict) -> dict:
    """Set several EQ bands and report the result read back.

    Only the properties the caller named are written, so a band the caller did not
    mention is left alone rather than reset to a default.
    """
    track = _require(params, "track", "mixer.setEqBands")
    bands = params.get("bands")
    if not isinstance(bands, list) or not bands:
        return {"error": "mixer.setEqBands requires a non-empty 'bands' list"}

    refusal = _check_track_index(track, "mixer.setEqBands")
    if refusal is not None:
        return refusal

    count = mixer.getEqBandCount()
    for entry in bands:
        if not isinstance(entry, dict) or "band" not in entry:
            return {"error": "mixer.setEqBands: every entry needs a 'band'"}
        band = int(entry["band"])
        if not 0 <= band < count:
            return {
                "error": (
                    "mixer.setEqBands: band %d does not exist. This mixer track has "
                    "%d bands, indexed 0 to %d." % (band, count, count - 1)
                )
            }
        written = False
        if "gain" in entry:
            mixer.setEqGain(track, band, float(entry["gain"]))
            written = True
        if "frequency" in entry:
            mixer.setEqFrequency(track, band, float(entry["frequency"]))
            written = True
        if "bandwidth" in entry:
            mixer.setEqBandwidth(track, band, float(entry["bandwidth"]))
            written = True
        if not written:
            return {
                "error": (
                    "mixer.setEqBands: band %d has nothing to set. Give at least "
                    "one of gain, frequency or bandwidth." % band
                )
            }

    return _eq_snapshot(track)


def handle_mixer_get_track_count() -> dict:
    """Get number of mixer tracks."""
    return {"count": mixer.trackCount()}


def handle_mixer_get_track_info(params: dict) -> dict:
    """Get info about a mixer track."""
    track = _require(params, "track", "mixer.getTrackInfo")
    return {
        "index": track,
        "name": mixer.getTrackName(track),
        "volume": mixer.getTrackVolume(track),
        "volume_db": mixer.getTrackVolume(track, 1),
        "pan": mixer.getTrackPan(track),
        "stereo_separation": mixer.getTrackStereoSep(track),
        "is_muted": mixer.isTrackMuted(track) == 1,
        "is_solo": mixer.isTrackSolo(track) == 1,
        "is_armed": mixer.isTrackArmed(track) == 1,
        "color": hex(mixer.getTrackColor(track)),
    }


def handle_mixer_get_all_tracks(params: dict) -> dict:
    """Get info about all mixer tracks."""
    include_empty = params.get("include_empty", False)
    tracks = []
    track_count = mixer.trackCount()

    for i in range(track_count):
        name = mixer.getTrackName(i)

        # Skip empty tracks if requested
        if not include_empty and (not name or name.startswith("Insert ")):
            if i != 0:  # Always include master
                continue

        tracks.append({
            "index": i,
            "name": name if name else ("Master" if i == 0 else f"Insert {i}"),
            "volume": mixer.getTrackVolume(i),
            "pan": mixer.getTrackPan(i),
            "is_muted": mixer.isTrackMuted(i) == 1,
            "is_solo": mixer.isTrackSolo(i) == 1,
        })

    return {"tracks": tracks}


def handle_mixer_set_track_volume(params: dict) -> dict:
    """Set mixer track volume."""
    track = _require(params, "track", "mixer.setTrackVolume")
    volume = params.get("volume", 0.8)
    mixer.setTrackVolume(track, volume)
    return {
        "volume": mixer.getTrackVolume(track),
        "volume_db": mixer.getTrackVolume(track, 1),
    }


def handle_mixer_set_track_pan(params: dict) -> dict:
    """Set mixer track pan."""
    track = _require(params, "track", "mixer.setTrackPan")
    pan = params.get("pan", 0.0)
    mixer.setTrackPan(track, pan)
    return {"pan": mixer.getTrackPan(track)}


def handle_mixer_mute_track(params: dict) -> dict:
    """Mute/unmute mixer track."""
    track = _require(params, "track", "mixer.muteTrack")
    muted = params.get("muted")  # None = toggle

    if muted is None:
        mixer.muteTrack(track, -1)
    else:
        mixer.muteTrack(track, 1 if muted else 0)

    return {
        "is_muted": mixer.isTrackMuted(track) == 1,
        "track_name": mixer.getTrackName(track),
    }


def handle_mixer_solo_track(params: dict) -> dict:
    """Solo/unsolo mixer track."""
    track = _require(params, "track", "mixer.soloTrack")
    solo = params.get("solo")  # None = toggle
    mode = params.get("mode", 3)

    if solo is None:
        mixer.soloTrack(track, -1, mode)
    else:
        mixer.soloTrack(track, 1 if solo else 0, mode)

    return {
        "is_solo": mixer.isTrackSolo(track) == 1,
        "track_name": mixer.getTrackName(track),
    }


def handle_mixer_arm_track(params: dict) -> dict:
    """Toggle arm state of mixer track."""
    track = params.get("track", 0)
    mixer.armTrack(track)
    return {
        "is_armed": mixer.isTrackArmed(track) == 1,
        "track_name": mixer.getTrackName(track),
    }


def handle_mixer_set_track_name(params: dict) -> dict:
    """Set mixer track name."""
    track = _require(params, "track", "mixer.setTrackName")
    name = params.get("name", "")
    mixer.setTrackName(track, name)
    return {"name": name}


def handle_mixer_set_track_color(params: dict) -> dict:
    """Set mixer track color."""
    track = _require(params, "track", "mixer.setTrackColor")
    r = params.get("r", 0)
    g = params.get("g", 0)
    b = params.get("b", 0)
    # FL Studio's scripting API takes 0xRRGGBB
    color = (r << 16) | (g << 8) | b
    mixer.setTrackColor(track, color)
    return {"color": f"RGB({r}, {g}, {b})"}


def handle_mixer_set_stereo_sep(params: dict) -> dict:
    """Set mixer track stereo separation."""
    track = _require(params, "track", "mixer.setStereoSep")
    separation = params.get("separation", 0.0)
    mixer.setTrackStereoSep(track, separation)
    return {"separation": separation}


# =============================================================================
# Channel Handlers
# =============================================================================


def handle_channels_get_count(params: dict) -> dict:
    """Get number of channels."""
    global_count = params.get("global_count", True)
    return {"count": channels.channelCount(global_count)}


def handle_channels_get_info(params: dict) -> dict:
    """Get info about a channel."""
    index = _require(params, "index", "channels.getInfo")
    use_global = params.get("use_global", True)

    return {
        "index": index,
        "name": channels.getChannelName(index, use_global),
        "color": hex(channels.getChannelColor(index, use_global)),
        "volume": channels.getChannelVolume(index, use_global),
        "pan": channels.getChannelPan(index, use_global),
        "pitch": channels.getChannelPitch(index, useGlobalIndex=use_global),
        "is_muted": channels.isChannelMuted(index, use_global) == 1,
        "is_solo": channels.isChannelSolo(index, use_global) == 1,
        "is_selected": channels.isChannelSelected(index, use_global) == 1,
        "target_fx_track": channels.getTargetFxTrack(index, use_global),
    }


def handle_channels_get_all() -> dict:
    """Get info about all channels."""
    channels_list = []
    count = channels.channelCount(True)

    for i in range(count):
        channels_list.append({
            "index": i,
            "name": channels.getChannelName(i, True),
            "is_muted": channels.isChannelMuted(i, True) == 1,
            "is_selected": channels.isChannelSelected(i, True) == 1,
            "target_fx_track": channels.getTargetFxTrack(i, True),
        })

    return {"channels": channels_list}


def handle_channels_get_selected() -> dict:
    """Get currently selected channel."""
    index = channels.selectedChannel(canBeNone=True, indexGlobal=True)

    if index is None or index < 0:
        return {"channel": None}

    return {
        "channel": {
            "index": index,
            "name": channels.getChannelName(index, True),
            "volume": channels.getChannelVolume(index, True),
            "pan": channels.getChannelPan(index, True),
            "is_muted": channels.isChannelMuted(index, True) == 1,
            "is_solo": channels.isChannelSolo(index, True) == 1,
        }
    }


def handle_channels_select(params: dict) -> dict:
    """Select/deselect a channel."""
    index = _require(params, "index", "channels.select")
    select = params.get("select", True)
    channels.selectChannel(index, 1 if select else 0, True)
    return {
        "selected": select,
        "channel_name": channels.getChannelName(index, True),
    }


def handle_channels_select_one(params: dict) -> dict:
    """Select only one channel, deselecting others."""
    index = _require(params, "index", "channels.selectOne")
    channels.selectOneChannel(index, True)
    return {"channel_name": channels.getChannelName(index, True)}


def handle_channels_select_piano_roll(params: dict) -> dict:
    """Select a channel and open its piano roll.

    This is how a caller aims the piano roll tools. The piano roll window shows
    whichever channel is selected in the Channel Rack, so selecting first is what
    makes the target unambiguous. A piano roll script cannot do this for itself:
    flpianoroll exposes no channel identity at all.

    The selection is read back rather than assumed, because knowing which piano
    roll is about to be written to is the entire point.
    """
    index = _require(params, "index", "channels.selectPianoRoll")
    count = channels.channelCount(True)
    if not 0 <= index < count:
        return {
            "error": (
                "channels.selectPianoRoll: channel %d does not exist. This project "
                "has %d channels, indexed 0 to %d."
                % (index, count, count - 1)
            )
        }

    channels.selectOneChannel(index, True)
    ui.showWindow(WID_PIANO_ROLL)

    return {
        "targeted": index,
        "selected": channels.selectedChannel(canBeNone=True, indexGlobal=True),
        "channel_name": channels.getChannelName(index, True),
        "piano_roll_visible": bool(ui.getVisible(WID_PIANO_ROLL)),
    }


def handle_channels_get_selected_channel(params: dict) -> dict:
    """Report which channel is selected, and its name.

    Read-only, and never refused: a caller has to be able to ask where it is
    before it can decide whether to move.
    """
    index = channels.selectedChannel(canBeNone=True, indexGlobal=True)
    if index is None or index < 0:
        return {"index": None, "channel_name": None}
    return {"index": index, "channel_name": channels.getChannelName(index, True)}


def handle_channels_trigger_note(params: dict) -> dict:
    """Trigger a MIDI note on a channel."""
    channel = params.get("channel", 0)
    note = params.get("note", 60)
    velocity = params.get("velocity", 100)
    midi_channel = params.get("midi_channel", -1)
    channels.midiNoteOn(channel, note, velocity, midi_channel)
    return {"triggered": True, "note": note, "velocity": velocity}


def handle_channels_set_volume(params: dict) -> dict:
    """Set channel volume."""
    index = _require(params, "index", "channels.setVolume")
    volume = params.get("volume", 0.8)
    channels.setChannelVolume(index, volume, True)
    return {
        "volume": channels.getChannelVolume(index, True),
        "channel_name": channels.getChannelName(index, True),
    }


def handle_channels_set_pan(params: dict) -> dict:
    """Set channel pan."""
    index = _require(params, "index", "channels.setPan")
    pan = params.get("pan", 0.0)
    channels.setChannelPan(index, pan, True)
    return {
        "pan": channels.getChannelPan(index, True),
        "channel_name": channels.getChannelName(index, True),
    }


def handle_channels_mute(params: dict) -> dict:
    """Mute/unmute channel."""
    index = _require(params, "index", "channels.mute")
    muted = params.get("muted")  # None = toggle

    if muted is None:
        channels.muteChannel(index, -1, True)
    else:
        channels.muteChannel(index, 1 if muted else 0, True)

    return {
        "is_muted": channels.isChannelMuted(index, True) == 1,
        "channel_name": channels.getChannelName(index, True),
    }


def handle_channels_solo(params: dict) -> dict:
    """Solo/unsolo channel."""
    index = _require(params, "index", "channels.solo")
    solo = params.get("solo")  # None = toggle

    if solo is None:
        channels.soloChannel(index, -1, True)
    else:
        channels.soloChannel(index, 1 if solo else 0, True)

    return {
        "is_solo": channels.isChannelSolo(index, True) == 1,
        "channel_name": channels.getChannelName(index, True),
    }


def handle_channels_set_name(params: dict) -> dict:
    """Set channel name."""
    index = _require(params, "index", "channels.setName")
    name = params.get("name", "")
    channels.setChannelName(index, name, True)
    return {"name": name}


def handle_channels_set_color(params: dict) -> dict:
    """Set channel color."""
    index = _require(params, "index", "channels.setColor")
    r = params.get("r", 0)
    g = params.get("g", 0)
    b = params.get("b", 0)
    # FL Studio's scripting API takes 0xRRGGBB
    color = (r << 16) | (g << 8) | b
    channels.setChannelColor(index, color, True)
    return {"color": f"RGB({r}, {g}, {b})"}


def handle_channels_route_to_mixer(params: dict) -> dict:
    """Route channel to mixer track."""
    channel_index = _require(params, "channel_index", "channels.routeToMixer")
    mixer_track = params.get("mixer_track", 0)
    channels.setTargetFxTrack(channel_index, mixer_track, True)
    return {
        "channel_name": channels.getChannelName(channel_index, True),
        "mixer_track": mixer_track,
    }


# =============================================================================
# Step Sequencer Handlers
# =============================================================================


def handle_channels_get_grid_bit(params: dict) -> dict:
    """Get whether a step is active."""
    channel = _require(params, "channel", "channels.getGridBit")
    position = params.get("position", 0)
    return {"value": channels.getGridBit(channel, position, True) == 1}


def handle_channels_set_grid_bit(params: dict) -> dict:
    """Set a step on or off."""
    channel = _require(params, "channel", "channels.setGridBit")
    position = params.get("position", 0)
    value = params.get("value", False)
    channels.setGridBit(channel, position, 1 if value else 0, True)
    return {
        "value": value,
        "channel_name": channels.getChannelName(channel, True),
    }


def handle_channels_get_step_sequence(params: dict) -> dict:
    """Get step sequence for a channel."""
    channel = _require(params, "channel", "channels.getStepSequence")
    steps = params.get("steps", 16)
    sequence = []

    for i in range(steps):
        sequence.append(channels.getGridBit(channel, i, True) == 1)

    return {"sequence": sequence}


def handle_channels_set_step_sequence(params: dict) -> dict:
    """Set complete step sequence for a channel."""
    channel = _require(params, "channel", "channels.setStepSequence")
    pattern = params.get("pattern", [])

    for i, value in enumerate(pattern):
        channels.setGridBit(channel, i, 1 if value else 0, True)

    active_steps = sum(pattern)
    return {
        "active_steps": active_steps,
        "total_steps": len(pattern),
        "channel_name": channels.getChannelName(channel, True),
    }


# =============================================================================
# Plugin Handlers
# =============================================================================


def handle_plugins_is_valid(params: dict) -> dict:
    """Check if plugin exists at location."""
    index = params.get("index", 0)
    slot_index = params.get("slot_index", -1)
    use_global = params.get("use_global", True)

    if slot_index >= 0:
        valid = plugins.isValid(index, slot_index, True)
    else:
        valid = plugins.isValid(index, -1, use_global)

    return {"valid": valid == 1}


def handle_plugins_get_name(params: dict) -> dict:
    """Get plugin name."""
    index = params.get("index", 0)
    slot_index = params.get("slot_index", -1)
    use_global = params.get("use_global", True)

    if slot_index >= 0:
        name = plugins.getPluginName(index, slot_index, True)
    else:
        name = plugins.getPluginName(index, -1, use_global)

    return {"name": name}


def handle_plugins_get_param_count(params: dict) -> dict:
    """Get number of plugin parameters."""
    index = params.get("index", 0)
    slot_index = params.get("slot_index", -1)
    use_global = params.get("use_global", True)

    if slot_index >= 0:
        count = plugins.getParamCount(index, slot_index, True)
    else:
        count = plugins.getParamCount(index, -1, use_global)

    return {"count": count}


def handle_plugins_get_params(params: dict) -> dict:
    """Get all plugin parameters."""
    index = params.get("index", 0)
    slot_index = params.get("slot_index", -1)
    use_global = params.get("use_global", True)
    max_params = params.get("max_params", 50)

    if slot_index >= 0:
        param_count = plugins.getParamCount(index, slot_index, True)
    else:
        param_count = plugins.getParamCount(index, -1, use_global)

    param_list = []
    for i in range(min(param_count, max_params)):
        try:
            if slot_index >= 0:
                name = plugins.getParamName(i, index, slot_index, True)
                value = plugins.getParamValue(i, index, slot_index, True)
                value_str = plugins.getParamValueString(i, index, slot_index, True)
            else:
                name = plugins.getParamName(i, index, -1, use_global)
                value = plugins.getParamValue(i, index, -1, use_global)
                value_str = plugins.getParamValueString(i, index, -1, use_global)

            param_list.append({
                "index": i,
                "name": name,
                "value": value,
                "value_string": value_str,
            })
        except Exception as e:
            print(f"Warning: could not read param {i}: {e}")
            continue

    return {"params": param_list}


def handle_plugins_get_param_value(params: dict) -> dict:
    """Get specific parameter value."""
    param_index = params.get("param_index", 0)
    plugin_index = _require(params, "plugin_index", "plugins.getParamValue")
    slot_index = params.get("slot_index", -1)
    use_global = params.get("use_global", True)

    if slot_index >= 0:
        name = plugins.getParamName(param_index, plugin_index, slot_index, True)
        value = plugins.getParamValue(param_index, plugin_index, slot_index, True)
        value_str = plugins.getParamValueString(param_index, plugin_index, slot_index, True)
    else:
        name = plugins.getParamName(param_index, plugin_index, -1, use_global)
        value = plugins.getParamValue(param_index, plugin_index, -1, use_global)
        value_str = plugins.getParamValueString(param_index, plugin_index, -1, use_global)

    return {
        "index": param_index,
        "name": name,
        "value": value,
        "value_string": value_str,
    }


def handle_plugins_set_param_value(params: dict) -> dict:
    """Set plugin parameter value."""
    param_index = params.get("param_index", 0)
    value = params.get("value", 0.0)
    plugin_index = _require(params, "plugin_index", "plugins.setParamValue")
    slot_index = params.get("slot_index", -1)
    use_global = params.get("use_global", True)

    if slot_index >= 0:
        name = plugins.getParamName(param_index, plugin_index, slot_index, True)
        plugins.setParamValue(value, param_index, plugin_index, slot_index, True)
        new_value = plugins.getParamValue(param_index, plugin_index, slot_index, True)
        value_str = plugins.getParamValueString(param_index, plugin_index, slot_index, True)
    else:
        name = plugins.getParamName(param_index, plugin_index, -1, use_global)
        plugins.setParamValue(value, param_index, plugin_index, -1, use_global)
        new_value = plugins.getParamValue(param_index, plugin_index, -1, use_global)
        value_str = plugins.getParamValueString(param_index, plugin_index, -1, use_global)

    return {
        "name": name,
        "value": new_value,
        "value_string": value_str,
    }


def handle_plugins_get_preset_count(params: dict) -> dict:
    """Get number of plugin presets."""
    index = params.get("index", 0)
    slot_index = params.get("slot_index", -1)
    use_global = params.get("use_global", True)

    if slot_index >= 0:
        count = plugins.getPresetCount(index, slot_index, True)
    else:
        count = plugins.getPresetCount(index, -1, use_global)

    return {"count": count}


def handle_plugins_next_preset(params: dict) -> dict:
    """Switch to next preset."""
    index = params.get("index", 0)
    slot_index = params.get("slot_index", -1)
    use_global = params.get("use_global", True)

    if slot_index >= 0:
        plugin_name = plugins.getPluginName(index, slot_index, True)
        plugins.nextPreset(index, slot_index, True)
    else:
        plugin_name = plugins.getPluginName(index, -1, use_global)
        plugins.nextPreset(index, -1, use_global)

    return {"plugin_name": plugin_name}


def handle_plugins_prev_preset(params: dict) -> dict:
    """Switch to previous preset."""
    index = params.get("index", 0)
    slot_index = params.get("slot_index", -1)
    use_global = params.get("use_global", True)

    if slot_index >= 0:
        plugin_name = plugins.getPluginName(index, slot_index, True)
        plugins.prevPreset(index, slot_index, True)
    else:
        plugin_name = plugins.getPluginName(index, -1, use_global)
        plugins.prevPreset(index, -1, use_global)

    return {"plugin_name": plugin_name}


def handle_plugins_get_color(params: dict) -> dict:
    """Get plugin color."""
    index = params.get("index", 0)
    slot_index = params.get("slot_index", -1)
    use_global = params.get("use_global", True)

    if slot_index >= 0:
        color = plugins.getColor(index, slot_index, True)
    else:
        color = plugins.getColor(index, -1, use_global)

    return {"color": hex(color)}


# =============================================================================
# Pattern Handlers
# =============================================================================


def _check_track_index(index: int, action: str) -> dict | None:
    """Refuse a mixer track outside the project, naming the range.

    FL ignores an out-of-range track rather than complaining, so a wrong index
    silently reads or writes nothing. Refusing says which index was wrong.
    """
    count = mixer.trackCount()
    if not 0 <= index < count:
        return {
            "error": (
                "%s: mixer track %d does not exist. This project has %d tracks, "
                "indexed 0 to %d." % (action, index, count, count - 1)
            )
        }
    return None


def _check_pattern_index(index: int, action: str) -> dict | None:
    """Refuse an index outside the project, naming the range.

    `patterns` has no accessor that raises on a bad index, unlike `channels` and
    `mixer`, so the check is explicit. Letting FL decide what pattern 99 means
    would be a guess about the user's project.
    """
    count = patterns.patternCount()
    if not 0 <= index < count:
        return {
            "error": (
                "%s: pattern %d does not exist. This project has %d patterns, "
                "indexed 0 to %d." % (action, index, count, count - 1)
            )
        }
    return None


def _pattern_entry(index: int) -> dict:
    """One pattern's properties, with each read guarded.

    A single unreadable field must not lose the other patterns, so each lookup
    reports None rather than raising.

    Note the index bases, which were measured rather than assumed and which do not
    agree with each other on live FL Studio 2026:

        patternCount()          0-based count
        patternNumber()         1-based number of the current pattern
        getPatternName(0)       0-based, so name 0 exists
        getPatternLength(0)     0-based
        isPatternSelected(0)    1-based: index 0 raises for isPatternDefault and
        isPatternDefault(0)     returns False for isPatternSelected

    This function takes a 0-based index, because that is what the caller sees and
    what every other part of this server uses, and translates for the two
    accessors that need it.
    """
    entry = {"index": index}
    readers = (
        ("name", lambda: patterns.getPatternName(index)),
        ("length", lambda: patterns.getPatternLength(index)),
        ("is_current", lambda: bool(patterns.isPatternSelected(index + 1))),
        ("is_default", lambda: bool(patterns.isPatternDefault(index + 1))),
    )
    for key, reader in readers:
        try:
            entry[key] = reader()
        except Exception:
            entry[key] = None

    try:
        # FL reports the colour as a signed int, so a colour with the high bit set
        # arrives negative. The caller asked for 0xRRGGBB.
        entry["color"] = patterns.getPatternColor(index) & 0xFFFFFF
    except Exception:
        entry["color"] = None
    return entry


def handle_patterns_get_all() -> dict:
    """Every pattern with its properties, in one call rather than five.

    A producer asking what is in this project should not need a round trip per
    pattern per field.
    """
    # patternNumber() is 1-based, and is 1 (not 0) when no pattern is selected,
    # so an index is one less than it reports.
    number = patterns.patternNumber()
    return {
        "patterns": [_pattern_entry(i) for i in range(patterns.patternCount())],
        "current": number - 1 if number else None,
    }


def handle_patterns_set_name(params: dict) -> dict:
    """Rename a pattern."""
    index = _require(params, "index", "patterns.setName")
    name = params.get("name")
    if name is None:
        return {"error": "patterns.setName requires a 'name'"}
    refusal = _check_pattern_index(index, "patterns.setName")
    if refusal is not None:
        return refusal
    patterns.setPatternName(index, name)
    return {"index": index, "name": patterns.getPatternName(index)}


def handle_patterns_set_color(params: dict) -> dict:
    """Recolour a pattern."""
    index = _require(params, "index", "patterns.setColor")
    color = params.get("color")
    if color is None:
        return {"error": "patterns.setColor requires a 'color'"}
    refusal = _check_pattern_index(index, "patterns.setColor")
    if refusal is not None:
        return refusal
    patterns.setPatternColor(index, int(color))
    return {"index": index, "color": patterns.getPatternColor(index)}


def handle_patterns_select(params: dict) -> dict:
    """Make a pattern the current one."""
    index = _require(params, "index", "patterns.select")
    refusal = _check_pattern_index(index, "patterns.select")
    if refusal is not None:
        return refusal
    patterns.selectPattern(index)
    return {"index": index, "current": patterns.patternNumber()}


def handle_patterns_clone(params: dict) -> dict:
    """Copy a pattern, including its name and length."""
    index = _require(params, "index", "patterns.clone")
    refusal = _check_pattern_index(index, "patterns.clone")
    if refusal is not None:
        return refusal
    cloned = patterns.clonePattern(index)
    return {
        "cloned": cloned,
        "name": patterns.getPatternName(cloned),
        "count": patterns.patternCount(),
    }


def handle_patterns_create_empty(params: dict) -> dict:
    """Select the next empty pattern, creating a slot if every one is used.

    patterns.findFirstNextEmptyPat exists in the stubs, which is why the claim
    that patterns cannot be created is overstated: selecting the next empty slot
    and writing into it is creation in practice.

    Only a genuinely new slot is named. A pattern that exists but holds no notes
    is still the next empty one, so calling this twice returns the same pattern
    rather than leaving a stray empty slot behind, and an existing pattern is
    never renamed, because the user may already have called it something.
    """
    before = patterns.patternCount()
    index = patterns.findFirstNextEmptyPat(0)
    if index < before:
        return {
            "created": index,
            "name": patterns.getPatternName(index),
            "was_existing": True,
        }

    # FL names its own patterns "Pattern 0", "Pattern 1", and so on, so a name
    # generated here matches what the user already sees rather than looking like a
    # different convention.
    name = params.get("name") or ("Pattern %d" % index)
    patterns.setPatternName(index, name)
    return {"created": index, "name": name, "was_existing": False}
