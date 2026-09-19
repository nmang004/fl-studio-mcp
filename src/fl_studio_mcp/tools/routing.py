"""Mixer routing and peak metering.

Routing is how audio gets from a channel's insert to the master, and how a send
reaches a reverb. Metering is how you find out what is actually loud, which is the
cheapest half of giving the server ears.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fl_studio_mcp.utils.connection import get_connection

if TYPE_CHECKING:
    from fastmcp import FastMCP


def get_routing(track: int | None = None) -> dict[str, Any]:
    """Where a track sends, or where every track sends."""
    params: dict[str, Any] = {}
    if track is not None:
        params["track"] = track
    return get_connection().send_command("mixer.getRouting", params, timeout=10.0)


def set_routing(track: int, sends: list[dict]) -> dict[str, Any]:
    """Route a track, then report the result read back."""
    reply = get_connection().send_command(
        "mixer.setRouting", {"track": track, "sends": sends}, timeout=10.0
    )
    if reply.get("success"):
        reply["message"] = (
            f"Track {track} ({reply.get('name')}) now sends to "
            f"{[s['track'] for s in reply.get('sends', [])]}."
        )
    return reply


def get_levels(tracks: list[int] | None = None, samples: int = 1) -> dict[str, Any]:
    """Peak levels, sampled."""
    params: dict[str, Any] = {"samples": samples}
    if tracks is not None:
        params["tracks"] = tracks
    return get_connection().send_command("mixer.getLevels", params, timeout=15.0)


def register_routing_tools(mcp: FastMCP) -> None:
    """Register routing and metering tools with the MCP server."""

    @mcp.tool()
    def fl_get_routing(track: int | None = None) -> dict:
        """Find out where a mixer track sends its audio.

        Args:
            track: Mixer track index. 0 is the Master. Omit it to report every
                   track at once, which costs one call per track and is slower.

        Returns:
            track, name: which track this is
            sends: each destination with its index, name and level. A track that
                   sends nowhere is a track nobody will hear.
        """
        return get_routing(track)

    @mcp.tool()
    def fl_set_routing(track: int, sends: list[dict]) -> dict:
        """Route a mixer track to other tracks, or remove its routings.

        Only the destinations you name are touched, so a send you do not mention
        keeps its level.

        Args:
            track: Mixer track index to route from.
            sends: Destinations to change. Each entry needs:
                   - track (int): destination mixer track index
                   - level (float, optional): 0.0 to 1.0
                   - remove (bool, optional): true to remove this send instead

        Example:
            fl_set_routing(track=3, sends=[{"track": 0, "level": 0.7}])
        """
        return set_routing(track, sends)

    @mcp.tool()
    def fl_get_levels(tracks: list[int] | None = None, samples: int = 1) -> dict:
        """Read peak levels to find what clips and what never sounds.

        FL reports the level right now, so a single reading while stopped is
        always silence. The samples are taken back to back rather than spaced in
        time, because the controller runs on FL's MIDI thread and waiting there
        would stall FL. To measure a whole passage, call this repeatedly during
        playback and keep the loudest peak for each track.

        Args:
            tracks: Mixer track indexes to read. Omit for every track.
            samples: How many readings to take per track, keeping the loudest.

        Returns:
            levels: one entry per track with its index, name, peak (0.0 silence,
                    1.0 is 0 dB, above 1.0 is clipping) and a clipping flag
            samples: how many readings each peak came from
        """
        return get_levels(tracks, samples)
