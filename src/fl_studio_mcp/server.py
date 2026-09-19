"""FL Studio MCP Server - Control FL Studio via Model Context Protocol.

This MCP server provides tools to control FL Studio through two mechanisms:
1. MIDI + JSON - Real-time control of mixer, transport, channels, patterns and
   plugins, plus arrangement markers and window state
2. Piano Roll Scripts - Persistent note placement via JSON + keystroke triggering

Requirements:
- FL Studio 20.7+ running, though general.safeToEdit and related functions want
  API version 29 and the controller reports those as unknown below it
- The FL Studio MCP controller script installed in FL Studio's Hardware folder
- On macOS: nothing, because the server creates its own virtual MIDI port
- On Windows: a loopMIDI port, because Windows has no virtual MIDI API
- For piano roll: ComposeWithLLM.pyscript installed and bound to a keystroke

Limitations:
- Cannot load new VST or AU plugins, only control ones already loaded
- Cannot place clips in the playlist. Markers are the ceiling
- Cannot render or export audio
- Cannot write the project tempo. The only function that could is documented as
  incomplete and buggy, so it is a research spike rather than a tool
"""

from __future__ import annotations

from fastmcp import FastMCP

from fl_studio_mcp.tools import (
    register_batch_tools,
    register_channel_tools,
    register_describe_tools,
    register_eq_tools,
    register_journal_tools,
    register_metering_tools,
    register_mixer_tools,
    register_pattern_tools,
    register_piano_roll_tools,
    register_plugin_tools,
    register_project_tools,
    register_review_tools,
    register_riff_tools,
    register_routing_tools,
    register_sample_tools,
    register_score_tools,
    register_tempo_tools,
    register_transport_tools,
)
from fl_studio_mcp.utils.connection import get_connection, reset_connection

# Create the MCP server
mcp = FastMCP(
    name="fl-studio-mcp",
    instructions="""
FL Studio MCP Server - Control FL Studio from AI assistants.

This server provides tools to control FL Studio through its Python scripting API.
FL Studio must be running with the FL Studio MCP Controller enabled in Options >
MIDI Settings.

Available tool categories:
- Connection: connect, and confirm FL actually answers
- Transport: play, stop, record, position, loop mode, playback speed
- Mixer: volume, pan, mute, solo, naming, colour, EQ, routing, peak levels
- Channels: channel info, properties, note triggering, step sequencer
- Patterns: list, rename, recolour, select, clone, create
- Plugins: parameter control and preset navigation, for already loaded plugins
- Piano roll: write, delete and read notes, targeted at a named channel
- Playlist and arrangement: arrangement lanes, markers, window state
- Undo and batching: undo steps, and running several commands as one edit

Reading the tempo works: it comes back in thousandths of a BPM, so 130000 is 130
BPM. Writing it is a research spike, and no tempo write tool exists yet.

Important limitations:
1. Cannot load new VST or AU plugins, only control ones already loaded
2. Cannot place clips in the playlist. Markers and live clips are the ceiling
3. Cannot render or export audio
4. Note triggering (fl_trigger_note) is real-time only, and notes do not persist
   unless FL Studio is recording. Use the piano roll tools or the step sequencer
   (fl_set_grid_bit) for notes that stay.
""",
)


# Register connection status resource
@mcp.resource("fl://status")
def get_fl_status() -> str:
    """Get FL Studio connection status."""
    conn = get_connection()
    if conn.is_connected:
        return "Connected to FL Studio via MIDI"
    else:
        return f"Not connected: {conn.connection_error}"


@mcp.resource("fl://project")
def get_project_info() -> dict:
    """Get current FL Studio project information."""
    conn = get_connection()

    if not conn.is_connected:
        return {"error": conn.connection_error}

    try:
        result = conn.send_command("transport.getStatus")
        if not result.get("success", False) and "error" in result:
            return {"error": result["error"]}

        return {
            "is_playing": result.get("is_playing", False),
            "is_recording": result.get("is_recording", False),
            "position": result.get("position", ""),
            "loop_mode": result.get("loop_mode", "pattern"),
        }
    except Exception as e:
        return {"error": str(e)}


# Connection management tools
@mcp.tool()
def fl_connect() -> str:
    """Connect to FL Studio and confirm it answers.

    Opening a MIDI port only proves the port opened. FL Studio takes two to three
    seconds to bind a new virtual port, and commands sent before that vanish, so
    this sends a ping and reports success only when FL replies to it.
    """
    # Reset connection state to force a fresh connection attempt
    reset_connection()

    conn = get_connection()
    try:
        conn.ensure_connected()
    except RuntimeError as e:
        return f"Connection failed: {e}"

    if not conn.wait_until_responsive():
        return (
            "Opened the MIDI port, but FL Studio did not answer a ping. Check "
            "that FL Studio is running and that the FL Studio MCP Controller is "
            "enabled in Options > MIDI Settings."
        )

    status = conn.get_status()
    return f"Connected to FL Studio, and it is answering, on port {status['port_name']}."


@mcp.tool()
def fl_get_version() -> dict:
    """Get the FL Studio version and MIDI scripting API version.

    The API version gates which scripting functions exist, so check this before
    relying on anything recent. Also reports whether a couple of version-gated
    functions actually work, and the current project tempo.

    Tempo is returned by FL in thousandths of a BPM, so 130000 means 130 BPM.
    """
    conn = get_connection()
    result = conn.send_command("system.getInfo")

    if not result.get("success", False):
        return {"error": result.get("error", "Unknown error")}

    tempo_raw = result.get("capabilities", {}).get("getCurrentTempo")
    return {
        "fl_version": result.get("fl_version"),
        "program_title": result.get("program_title"),
        "api_version": result.get("api_version"),
        "tempo_bpm": tempo_raw / 1000 if isinstance(tempo_raw, (int, float)) else None,
        "capabilities": result.get("capabilities", {}),
    }


@mcp.tool()
def fl_connection_status() -> dict:
    """Get the current FL Studio connection status.

    Returns information about whether FL Studio is connected
    and any error messages if not.
    """
    conn = get_connection()
    # Eagerly attempt a connection so the reported status reflects actual
    # reachability rather than the lazily-initialized flag.
    try:
        conn.ensure_connected()
    except RuntimeError:
        pass
    status = conn.get_status()
    return {
        "connected": status.get("connected", False),
        "port_name": status.get("port_name"),
        "available_ports": status.get("available_ports", []),
        "error": status.get("error"),
    }


# Register all tools
register_transport_tools(mcp)
register_mixer_tools(mcp)
register_channel_tools(mcp)
register_plugin_tools(mcp)
register_piano_roll_tools(mcp)
register_batch_tools(mcp)
register_pattern_tools(mcp)
register_eq_tools(mcp)
register_routing_tools(mcp)
register_project_tools(mcp)
register_tempo_tools(mcp)
register_score_tools(mcp)
register_describe_tools(mcp)
register_metering_tools(mcp)
register_review_tools(mcp)
register_journal_tools(mcp)
register_riff_tools(mcp)
register_sample_tools(mcp)


def main():
    """Run the FL Studio MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
