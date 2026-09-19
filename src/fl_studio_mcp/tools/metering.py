"""Peak metering over time, sampled from the host.

The controller cannot do this. It runs on FL's MIDI thread, so sleeping between
readings would stall the audio engine there, which is why the controller's own levels
action reads back to back and cannot see a peak that falls between two polls. The
host has a real clock and can wait.

What this measures is a peak hold: the loudest level seen per track across the
window. It is not loudness. There is no RMS, no LUFS and no frequency content,
because all of those need the audio itself, and capturing the audio is tabled. Peak
and loudness disagree in both directions, so a peak hold must not be read as one.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from fl_studio_mcp.utils.connection import get_connection

if TYPE_CHECKING:
    from fastmcp import FastMCP

DEFAULT_DURATION = 4.0
DEFAULT_INTERVAL = 0.05

# Readings per round trip. The controller can read several tracks per command, so
# asking for all of them in one command keeps the round trips down rather than one
# per track.
SAMPLES_PER_COMMAND = 1


def sample_peaks(
    duration: float = DEFAULT_DURATION,
    interval: float = DEFAULT_INTERVAL,
    tracks: list[int] | None = None,
) -> dict[str, Any]:
    """Sample peak levels for a window and keep the loudest reading per track.

    Args:
        duration: How long to sample, in seconds.
        interval: How long to wait between readings. Shorter catches narrower peaks
            at the cost of more round trips.
        tracks: Mixer track indexes to read. None reads every track.

    Returns:
        success, samples, duration: what was done
        levels: one entry per track with its index, name, peak and a clipping flag
        transport: the playing and recording state during the window

    Raises nothing: a refused sample comes back with "success": False and a reason.
    """
    if duration <= 0:
        return {
            "success": False,
            "error": f"duration must be positive, got {duration}. A sample needs a window.",
        }
    if interval <= 0:
        return {
            "success": False,
            "error": f"interval must be positive, got {interval}",
        }

    connection = get_connection()

    status = connection.send_command("transport.getStatus", timeout=5.0)
    if not status.get("success"):
        return {
            "success": False,
            "error": f"Could not read the transport: {status.get('error')}",
        }

    # Refusing while stopped is the most important behaviour here. Every reading is
    # zero when nothing is playing, and zero is indistinguishable from a track that is
    # routed nowhere, so a review would report a silent mix as a routing problem.
    if not status.get("is_playing"):
        return {
            "success": False,
            "error": (
                "The transport is stopped, so every level would read zero and that "
                "looks exactly like a track that never sounds. Start playback and "
                "sample again."
            ),
            "transport": {
                "is_playing": status.get("is_playing"),
                "is_recording": status.get("is_recording"),
            },
        }

    params: dict[str, Any] = {"samples": SAMPLES_PER_COMMAND}
    if tracks is not None:
        params["tracks"] = tracks

    peaks: dict[int, float] = {}
    names: dict[int, str] = {}

    # How many readings the window calls for, counted rather than compared against a
    # clock. Comparing elapsed time to the duration looked right and was off by one,
    # because ten waits of 0.05 seconds sum to 0.49999999999999994, which is just
    # under 0.5. Counting makes a 0.5 second window at 0.05 second intervals exactly
    # ten samples.
    planned = max(1, int(round(duration / interval)))
    readings = 0

    for reading in range(planned):
        if reading:
            # The wait is on the host, not in the controller. Sleeping in the
            # controller would stall FL's MIDI thread and take the audio with it.
            time.sleep(interval)
        reply = connection.send_command("mixer.getLevels", params, timeout=15.0)
        if not reply.get("success"):
            return {
                "success": False,
                "error": reply.get("error") or "Could not read levels",
                "samples": readings,
            }

        for entry in reply.get("levels", []):
            index = entry["track"]
            names[index] = entry.get("name")
            peak = entry.get("peak") or 0.0
            if peak > peaks.get(index, float("-inf")):
                peaks[index] = peak
        readings += 1

    after = connection.send_command("transport.getStatus", timeout=5.0)

    return {
        "success": True,
        "samples": readings,
        "duration": duration,
        "levels": [
            {
                "track": index,
                "name": names.get(index),
                "peak": peak,
                "clipping": peak > 1.0,
            }
            for index, peak in sorted(peaks.items())
        ],
        "transport": {
            "is_playing": after.get("is_playing"),
            "is_recording": after.get("is_recording"),
        },
    }


def register_metering_tools(mcp: FastMCP) -> None:
    """Register the peak sampling tool."""

    @mcp.tool()
    def fl_sample_levels(
        duration: float = DEFAULT_DURATION, tracks: list[int] | None = None
    ) -> dict:
        """Sample peak levels over a window while the project plays.

        This is a peak hold, not a loudness measurement. It finds what clips and what
        never sounds. It cannot tell you what is too loud in the sense a listener
        means, because that needs the audio and capturing audio is not supported.

        Playback must already be running. Sampling while stopped is refused, because
        every reading would be zero and zero is indistinguishable from a track that is
        routed nowhere.

        Args:
            duration: How long to listen, in seconds. Four is enough for a loop.
            tracks: Mixer track indexes. Omit for every track.

        Returns:
            levels: each track's loudest peak, where 1.0 is 0 dB and above 1.0 is
                    clipping, plus a clipping flag
            samples: how many readings the peak came from
            transport: the playing and recording state during the window
        """
        return sample_peaks(duration=duration, tracks=tracks)
