"""Describe the whole project in one call.

The alternative is twenty round trips: ask for the tempo, then the key, then the
patterns, then each channel, then each mixer track. A model doing that spends its
whole budget on questions and remembers none of the answers by the time it acts.

What this does instead is batch the readings. `system.batch` runs several commands
from one trigger, so the whole description costs a small fixed number of round trips
rather than one per object.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fl_studio_mcp.utils.connection import get_connection

if TYPE_CHECKING:
    from fastmcp import FastMCP

# The readings that make up a description. Kept as data so the batch and the
# labelling stay in step, and so a test can assert the shape without running FL.
READINGS: tuple[tuple[str, str, dict[str, Any]], ...] = (
    ("tempo", "system.getInfo", {}),
    ("patterns", "patterns.getAll", {}),
    ("channels", "channels.getAll", {}),
    ("tracks", "mixer.getAllTracks", {"include_empty": True}),
)

DESCRIBE_TIMEOUT = 30.0


def describe_project() -> dict[str, Any]:
    """One call for tempo, key, meter, patterns, channels and mixer tracks."""
    connection = get_connection()

    commands = [{"action": action, "params": params} for _, action, params in READINGS]
    batch = connection.send_command(
        "system.batch", {"commands": commands, "name": "MCP: describe project"},
        timeout=DESCRIBE_TIMEOUT,
    )

    if not batch.get("success"):
        return {
            "success": False,
            "error": batch.get("error") or "The describe batch did not complete.",
            "results": batch.get("results"),
        }

    described: dict[str, Any] = {"success": True}
    for (label, _, _), result in zip(READINGS, batch.get("results", []), strict=False):
        described[label] = result

    described["summary"] = _summarise(described)
    return described


def _summarise(described: dict[str, Any]) -> dict[str, Any]:
    """The parts a caller reads first, pulled out of the raw replies."""
    info = described.get("tempo") or {}
    capabilities = info.get("capabilities") or {}
    tempo_raw = capabilities.get("getCurrentTempo")

    patterns = (described.get("patterns") or {}).get("patterns") or []
    channels = (described.get("channels") or {}).get("channels") or []
    tracks = (described.get("tracks") or {}).get("tracks") or []

    return {
        "tempo_bpm": tempo_raw / 1000 if isinstance(tempo_raw, (int, float)) else None,
        "fl_version": info.get("fl_version"),
        "api_version": info.get("api_version"),
        "pattern_count": len(patterns),
        "current_pattern": (described.get("patterns") or {}).get("current"),
        "channel_count": len(channels),
        "mixer_track_count": len(tracks),
        "channel_names": [entry.get("name") for entry in channels][:32],
        "pattern_names": [entry.get("name") for entry in patterns][:32],
    }


def register_describe_tools(mcp: FastMCP) -> None:
    """Register the project description tool."""

    @mcp.tool()
    def fl_describe_project() -> dict:
        """Describe the open FL Studio project in one call.

        Use this once at the start of a session instead of asking for the tempo, the
        patterns, the channels and the mixer separately. It is a handful of round
        trips rather than one per object.

        Returns:
            summary: tempo, FL and API version, pattern and channel and mixer track
                     counts, and their names, which is what a caller usually needs
            patterns: every pattern with its length and colour
            channels: every Channel Rack channel with its mute and solo state
            tracks: every mixer track with its volume and routing state
        """
        return describe_project()
