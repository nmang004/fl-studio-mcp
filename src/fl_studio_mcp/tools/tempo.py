"""Project tempo.

Reading is settled and has been since the start: mixer.getCurrentTempo returns
thousandths of a BPM, so 130000 is 130 BPM.

Writing has no dedicated API. The only path in the entire stub package is
general.processRECEvent with midi.REC_Tempo, and that function's own docstring
advises trying other functions first because that part of the API is incomplete,
poorly documented, and filled with hidden bugs. It was measured on live FL Studio
2026 build 5406 and it works: setting the value with flags 17 moved the tempo, an
independent read agreed, and a restore came back. The finding is
docs/spikes/2026-09-19-T1-tempo-write.md.

This tool verifies rather than trusts. A write that FL accepts and does not act on
looks exactly like a success from the outside, which is the worst possible failure
for a tempo change, so the value is read back and a non-move is reported as a
failure.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fl_studio_mcp.utils.connection import get_connection

if TYPE_CHECKING:
    from fastmcp import FastMCP

# Measured on FL Studio 2026 build 5406: REC_UpdateValue | REC_UpdateControl. Any
# other word is a guess, which is why this is one named constant rather than a
# parameter the caller has to reason about.
TEMPO_WRITE_FLAGS = 17

# The tempo event has no documented range, and the stubs warn that an invalid value
# can crash FL. This range is the tool's own guard, not a value FL reported, and it
# is deliberately far wider than any usable tempo.
MIN_BPM = 10.0
MAX_BPM = 999.0

# processRECEvent takes thousandths of a BPM, the same unit getCurrentTempo returns.
BPM_SCALE = 1000


def set_tempo(bpm: float) -> dict[str, Any]:
    """Set the project tempo, and confirm that it moved.

    Args:
        bpm: Beats per minute.

    Returns:
        The controller's tempo report, with "success": False and a specific
        "error" when the value was out of range or the tempo did not change.
    """
    try:
        bpm = float(bpm)
    except (TypeError, ValueError):
        return {"success": False, "error": f"Tempo must be a number, got {bpm!r}."}

    if not MIN_BPM <= bpm <= MAX_BPM:
        return {
            "success": False,
            "error": (
                f"Tempo {bpm} is outside the supported range of {MIN_BPM:g} to "
                f"{MAX_BPM:g} BPM. FL gives this event no documented range, so this "
                "limit is the tool's own guard rather than something FL reported."
            ),
        }

    report = get_connection().send_command(
        "system.tempoProbe",
        {"bpm": bpm, "restore": False, "flags": TEMPO_WRITE_FLAGS},
        timeout=10.0,
    )

    if report.get("error"):
        return {**report, "success": False}

    # The tempo was already the requested value, so nothing needed to change. That
    # is a no-op rather than a failure, and treating it as one would fail a
    # perfectly reasonable "make sure the tempo is 130". Note the conjunction: a
    # successful write also leaves bpm_after equal to bpm, so identity alone would
    # mislabel every real change.
    if not report.get("changed") and report.get("bpm_after") is not None:
        if float(report["bpm_after"]) == bpm:
            report["success"] = True
            report["message"] = (
                f"Tempo is {report['bpm_after']} BPM, read back from FL Studio. It "
                "was already that value, so nothing needed to change."
            )
            report["already_set"] = True
            return report

    if not report.get("changed"):
        return {
            **report,
            "success": False,
            "error": (
                f"FL Studio accepted the tempo write but the tempo did not change: it "
                f"is still {report.get('bpm_after')} BPM, not {bpm}. The write path is "
                "general.processRECEvent, whose own documentation warns it is "
                "incomplete and buggy, so this is reported as a failure rather than "
                "assumed to have worked."
            ),
        }

    if not report.get("write_verified"):
        return {
            **report,
            "success": False,
            "error": (
                f"The tempo moved to {report.get('bpm_after')} BPM rather than the "
                f"{bpm} that was asked for, so the value was not stored exactly."
            ),
        }

    report["success"] = True
    report["message"] = (
        f"Tempo is now {report.get('bpm_after')} BPM, read back from FL Studio."
    )
    return report


def get_tempo() -> dict[str, Any]:
    """Read the project tempo."""
    info = get_connection().send_command("system.getInfo", timeout=5.0)
    raw = (info.get("capabilities") or {}).get("getCurrentTempo")
    if raw is None:
        return {"success": False, "error": "FL Studio did not report a tempo."}
    return {
        "success": True,
        "tempo_raw": raw,
        "bpm": raw / BPM_SCALE,
        "note": "FL reports tempo in thousandths of a BPM, so 130000 is 130 BPM.",
    }


def register_tempo_tools(mcp: FastMCP) -> None:
    """Register tempo tools with the MCP server."""

    @mcp.tool()
    def fl_get_tempo() -> dict:
        """Read the project tempo in BPM.

        FL reports tempo in thousandths of a BPM, so this converts it. The raw
        value is included, so a caller can see what FL actually said.
        """
        return get_tempo()

    @mcp.tool()
    def fl_set_tempo(bpm: float) -> dict:
        """Set the project tempo.

        The value is read back and the result is reported from that read, so a
        write FL accepted but did not act on comes back as a failure rather than a
        success. Setting a tempo the user did not ask for is disruptive, so confirm
        before changing it in someone's project.

        Args:
            bpm: Beats per minute, 10 to 999.

        Returns:
            bpm_before, bpm_after: what the tempo was and what it is now
            write_verified: whether the read-back matched what was asked for
        """
        return set_tempo(bpm)
