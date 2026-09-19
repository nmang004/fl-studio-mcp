"""The mix review and the gain staging pass.

A review reads the mixer's settings and, when the project is playing, samples peak
levels. The gain staging pass turns those readings into fader moves, and by default
only says what it would do. Changing a producer's faders without being asked is not a
diagnostic.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fl_studio_mcp.musical import analysis
from fl_studio_mcp.tools import batch, metering
from fl_studio_mcp.utils.connection import get_connection

if TYPE_CHECKING:
    from fastmcp import FastMCP

DEFAULT_TARGET_DB = -3.0
DEFAULT_SAMPLE_SECONDS = 4.0


def get_snapshot() -> dict[str, Any]:
    """Every mixer track's settings in one round trip."""
    return get_connection().send_command("mixer.getSnapshot", {}, timeout=20.0)


def mix_review(sample_seconds: float = DEFAULT_SAMPLE_SECONDS) -> dict[str, Any]:
    """Review the mix, with levels when the project is playing.

    Args:
        sample_seconds: How long to sample levels for. Ignored when the transport is
            stopped, because sampling then measures nothing.

    Returns:
        findings, ordered worst first, and a summary. The level findings are absent
        when the transport was stopped, and the summary says so rather than implying
        that nothing was found.
    """
    snapshot = get_snapshot()
    if not snapshot.get("success"):
        return {
            "success": False,
            "error": snapshot.get("error") or "Could not read the mixer",
        }

    sampled = metering.sample_peaks(duration=sample_seconds)
    levels = sampled.get("levels") if sampled.get("success") else None

    reviewed = analysis.review_mix(snapshot, levels)
    reviewed["success"] = True
    if levels is None:
        # Saying why matters: a caller who ran this with the transport stopped has to
        # know the level findings are missing rather than absent because the mix is
        # clean.
        reviewed["levels_unavailable"] = sampled.get("error")
    return reviewed


def gain_staging(
    target_db: float = DEFAULT_TARGET_DB,
    apply: bool = False,
    sample_seconds: float = DEFAULT_SAMPLE_SECONDS,
) -> dict[str, Any]:
    """Trim the tracks that are over a target level.

    Args:
        target_db: Where to aim. The default trims to leave headroom rather than
            matching loudness, which a peak reading cannot do.
        apply: Whether to make the moves. False by default, so the first call reports
            and the second one, if the caller wants it, changes the project.
        sample_seconds: How long to sample levels for.

    Returns:
        moves: what was found or done, each with the track, the volume before and
            after, and the reason
        applied: whether the faders were actually moved
        batch: the batch report when the moves were applied, so a caller can see the
            undo name and undo the whole pass in one step
    """
    snapshot = get_snapshot()
    if not snapshot.get("success"):
        return {
            "success": False,
            "error": snapshot.get("error") or "Could not read the mixer",
        }

    sampled = metering.sample_peaks(duration=sample_seconds)
    if not sampled.get("success"):
        return {
            "success": False,
            "error": sampled.get("error"),
            "requires_playback": True,
        }

    plan = analysis.plan_gain_staging(snapshot, sampled.get("levels"), target_db)
    moves = plan["moves"]

    result: dict[str, Any] = {
        "success": True,
        "moves": moves,
        "applied": False,
        "target_db": target_db,
        "sample_seconds": sample_seconds,
        "note": plan["note"],
    }

    if not moves:
        result["message"] = (
            f"Nothing is over {target_db} dB, so no fader needs moving."
        )
        return result

    if not apply:
        result["message"] = (
            f"{len(moves)} fader(s) would move. Nothing has been changed: pass "
            "apply=True to make the moves."
        )
        return result

    # Applied as one batch, so the whole pass is one undo step rather than one per
    # fader. A producer who dislikes the result presses Ctrl+Z once.
    commands = [
        {
            "action": "mixer.setTrackVolume",
            "params": {"track": move["track"], "volume": move["proposed_volume"]},
        }
        for move in moves
    ]
    batch_result = batch.run_batch(commands, "MCP: gain staging")
    result["batch"] = batch_result
    result["applied"] = bool(batch_result.get("success"))
    if not result["applied"]:
        result["success"] = False
        result["error"] = batch_result.get("error") or "The batch did not complete."
        return result

    result["message"] = (
        f"Moved {len(moves)} fader(s). One undo reverses the whole pass."
    )
    return result


def register_review_tools(mcp: FastMCP) -> None:
    """Register the mix review and gain staging tools."""

    @mcp.tool()
    def fl_mix_review(sample_seconds: float = DEFAULT_SAMPLE_SECONDS) -> dict:
        """Review the mix and report what needs attention.

        Read only: this never changes the project.

        It reports two kinds of thing. The settings findings, which need no playback:
        a track with no sends, every fader left at FL's default, everything panned
        centre. And the level findings, which need the project to be playing: what
        clips, and what is routed into something that never sounds.

        Levels are a peak hold, not a loudness measurement. It finds clipping and
        silence. It cannot tell you that a track is too loud in the sense a listener
        means, because that needs the audio and capturing audio is not supported.

        Args:
            sample_seconds: How long to sample levels for. Ignored while stopped.

        Returns:
            findings: worst first, each naming the track and the reason
            summary: the counts, and whether levels were part of the review
            levels_unavailable: present when the transport was stopped, saying why
        """
        return mix_review(sample_seconds=sample_seconds)

    @mcp.tool()
    def fl_gain_staging(
        target_db: float = DEFAULT_TARGET_DB,
        apply: bool = False,
        sample_seconds: float = DEFAULT_SAMPLE_SECONDS,
    ) -> dict:
        """Trim the mixer tracks that are peaking above a target.

        Playback must be running, because the decision is based on sampled peaks rather
        than on the current fader values, and a fader value says nothing about how hot
        the signal arriving at it is.

        Nothing changes unless apply is true. Call it once without to see the moves,
        then again with apply to make them, which is deliberate: moving a producer's
        faders is disruptive and should not be a side effect of asking a question.

        Only trims down. Raising a quiet track would fight the balance the producer
        already set, which is their decision rather than a peak reading's.

        Args:
            target_db: Where to aim. The default leaves headroom rather than matching
                        loudness, which a peak reading cannot do.
            apply: Whether to move the faders. False reports only.
            sample_seconds: How long to sample levels for.

        Returns:
            moves: each with the track, the volume before and after, and the reason
            applied: whether the faders were moved
            batch: when applied, the batch report and its undo name
        """
        return gain_staging(
            target_db=target_db, apply=apply, sample_seconds=sample_seconds
        )
