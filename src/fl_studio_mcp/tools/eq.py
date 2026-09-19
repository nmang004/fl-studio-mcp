"""Mixer track EQ.

FL gives every mixer insert a multi-band EQ. Reading it one property at a time is
twenty one round trips for a single question about a single track, so the tools
here read and write the whole EQ at once.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fl_studio_mcp.utils.connection import get_connection

if TYPE_CHECKING:
    from fastmcp import FastMCP


def get_eq(track: int) -> dict[str, Any]:
    """Read every EQ band of a mixer track."""
    return get_connection().send_command("mixer.getEq", {"track": track}, timeout=5.0)


def set_eq(track: int, bands: list[dict]) -> dict[str, Any]:
    """Set EQ bands, then read the whole EQ back."""
    reply = get_connection().send_command(
        "mixer.setEqBands", {"track": track, "bands": bands}, timeout=5.0
    )
    if reply.get("success"):
        reply["message"] = (
            f"Set {len(bands)} band(s) on track {track} ({reply.get('name')})."
        )
    return reply


def register_eq_tools(mcp: FastMCP) -> None:
    """Register EQ tools with the MCP server."""

    @mcp.tool()
    def fl_get_eq(track: int) -> dict:
        """Read the EQ of a mixer track, all bands at once.

        Args:
            track: Mixer track index. 0 is the Master.

        Returns:
            track, name: which track this is
            band_count: how many bands FL reports, which is not assumed
            bands: one entry per band with its index, gain, frequency and
                   bandwidth. Gain and frequency are the values the API reports,
                   which for most bands are normalised rather than in Hz or dB.
        """
        return get_eq(track)

    @mcp.tool()
    def fl_set_eq(track: int, bands: list[dict]) -> dict:
        """Set EQ bands on a mixer track and report the result.

        Bands are set together because they are one decision about one track. Only
        the properties you name are written, so a band you do not mention is left
        exactly as it was rather than reset.

        The reply is the EQ read back from FL Studio, not a claim about what was
        sent, so a band that did not take is visible.

        Args:
            track: Mixer track index. 0 is the Master.
            bands: Bands to change. Each entry needs:
                   - band (int): band index, from fl_get_eq's band_count
                   - gain (float, optional)
                   - frequency (float, optional)
                   - bandwidth (float, optional)
                   At least one of the three must be given per entry.

        Example:
            fl_set_eq(track=3, bands=[
                {"band": 0, "gain": 0.3},
                {"band": 6, "gain": 0.7, "frequency": 0.8},
            ])
        """
        return set_eq(track, bands)
