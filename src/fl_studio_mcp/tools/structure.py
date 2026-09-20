"""Read the song's structure in one round trip, and report what is arithmetic.

The controller readings go in one batch: the timebase, every pattern and the
arrangement's markers. One trigger, one reply.

The key and meter cannot ride in that batch, and the reason is architectural rather
than an oversight: they live on `flpianoroll.score` in the piano roll's sandbox, and
the controller cannot see them at all. That read goes through the same request path
the riff and bassline tools use. When it does not answer, the report still runs, the
meter falls back to 4/4, and the observations say the meter was assumed rather than
measured.

The critique itself is arithmetic in `musical/structure.py`. This module knows which
FL actions to call, and nothing about what an answer means.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fl_studio_mcp.musical import score, structure
from fl_studio_mcp.tools import piano_roll
from fl_studio_mcp.utils.connection import get_connection

if TYPE_CHECKING:
    from fastmcp import FastMCP

# The readings that make up the report. Kept as data so the batch, the labelling and
# the tests stay in step.
READINGS: tuple[tuple[str, str, dict[str, Any]], ...] = (
    ("ppq", "system.getPpq", {}),
    ("patterns", "patterns.getAll", {}),
    ("markers", "arrangement.getMarkers", {}),
)

STRUCTURE_TIMEOUT = 20.0
CONTEXT_TIMEOUT = 5.0
CONTEXT_REQUEST_ID = "structure-context"


def project_context() -> dict[str, Any]:
    """The key and meter, or an empty dict when the piano roll did not answer.

    Returning an empty dict rather than a defaulted one matters: the converter has
    to put something in `beats_per_bar`, and a default is not a measurement. The
    caller can then say the meter was assumed.
    """
    try:
        reply = piano_roll.send_request(
            {"action": "get_context", "id": CONTEXT_REQUEST_ID},
            timeout=CONTEXT_TIMEOUT,
            wait_for_manual_trigger=CONTEXT_TIMEOUT,
        )
    except Exception:
        # A context read is a bonus for the report, never a reason to lose it.
        return {}

    if reply.get("success") is False or reply.get("error"):
        return {}
    if not _carries_context(reply):
        return {}
    return score.context_from_reply(reply)


def structure_critique() -> dict[str, Any]:
    """Sections, pattern lengths and arithmetic findings, in one round trip.

    Returns:
        The critique, the context the arithmetic ran in, and how many controller
        round trips it took. A batch that fails is reported rather than raised, so a
        caller always has an answer.
    """
    connection = get_connection()
    commands = [{"action": action, "params": params} for _, action, params in READINGS]
    reply = connection.send_command(
        "system.batch",
        {"commands": commands, "name": "MCP: read structure"},
        timeout=STRUCTURE_TIMEOUT,
    )
    if not reply.get("success"):
        return {
            "success": False,
            "error": reply.get("error") or "The structure batch did not complete.",
            "results": reply.get("results"),
        }

    results = reply.get("results") or []
    if len(results) < len(READINGS):
        return {
            "success": False,
            "error": (
                f"The structure batch returned {len(results)} result(s) for "
                f"{len(READINGS)} command(s), so the project was only partly read."
            ),
        }

    ppq_reply, patterns_reply, markers_reply = results[0] or {}, results[1] or {}, results[2] or {}
    context = project_context()
    context["ppq"] = ppq_reply.get("ppq")
    context["meter_read"] = bool(context)

    report = structure.critique(
        context,
        patterns_reply.get("patterns") or [],
        markers_reply.get("markers") or [],
    )
    summary = report["summary"]
    return {
        "success": True,
        "round_trips": 1,
        "context": {
            "key": context.get("key"),
            "time_signature": summary["time_signature"],
            "beats_per_bar": summary["beats_per_bar"],
            "ppq": context.get("ppq"),
            "meter_read": context["meter_read"],
            "meter_source": (
                "score.tsnum and score.tsden, in the piano roll's sandbox"
                if context["meter_read"]
                else "assumed 4/4, because the piano roll script did not answer"
            ),
        },
        "sections": report["sections"],
        "patterns": report["patterns"],
        "observations": report["observations"],
        "summary": summary,
        "note": (
            "One controller round trip: the timebase, the patterns and the markers "
            "arrive in a single batch. The key and meter are read from the piano "
            "roll's own sandbox, which a controller batch cannot reach."
        ),
    }


def _carries_context(reply: dict[str, Any]) -> bool:
    """Whether a reply holds the piano roll's own context fields.

    An empty reply converts to a context anyway, because the converter has to
    default the meter to something. That default must not be reported as a
    measurement of 4/4, so it is rejected here.
    """
    candidates = [reply]
    candidates.extend(
        entry for entry in reply.get("responses") or [] if isinstance(entry, dict)
    )
    return any("tsnum" in entry or "scale_helper" in entry for entry in candidates)


def register_structure_tools(mcp: FastMCP) -> None:
    """Register the structure critique tool."""

    @mcp.tool()
    def fl_structure_critique() -> dict:
        """Read the song's structure: markers, section lengths and pattern lengths.

        Every observation is arithmetic over what FL reported. It will say that the
        last section is four bars and the others are sixteen, because that is a
        fact. It will not say that the chorus is too short, because that is taste
        and this tool has none.

        One round trip: the timebase, every pattern and the arrangement's markers go
        in a single batch. The key and meter come from the piano roll's own sandbox,
        which a controller batch cannot reach, and when that read does not answer
        the report says the meter was assumed to be 4/4.

        Read only: nothing in the project is changed.

        Returns:
            sections: one per marker, with its start bar and its length to the next
                      marker, or None for the last one
            patterns: every pattern's length in beats and bars, and whether it fills
                      a whole number of four bar blocks
            observations: the arithmetic findings, problems first
            summary: the counts, the meter the arithmetic used, and the key when the
                     piano roll reported one
        """
        return structure_critique()
