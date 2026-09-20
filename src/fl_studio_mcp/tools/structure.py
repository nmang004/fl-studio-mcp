"""Read the song's structure in one controller round trip, plus one piano roll request.

The controller readings go in one batch: the timebase, every pattern and the
arrangement's markers. One trigger, one reply.

The key and the meter cannot ride in that batch, and the reason is architectural
rather than an oversight: both live on `flpianoroll.score`, in the piano roll's
sandbox, and the controller cannot see them at all. One `get_context` request carries
them, the same request `project_context` sends for the template tools, so the critique
costs exactly one piano roll script run.

No marker time is readable anywhere, and this module no longer looks for one. The
controller's API has no function that reads a marker's time: `arrangement.getMarkerName`
is its only marker reader, so `arrangement.getMarkers` reports a name and a null time
for every marker. The piano roll's own accessors were measured on live FL Studio 2026
build 5406 and report zero markers for an arrangement that holds three, so they are a
silent no-op rather than a second source. Section times are therefore unavailable on
this build, and the report says so instead of guessing a bar position.

The piano roll reading is a bonus for the report, never a reason to lose it. When the
script does not answer, the report still runs, the meter falls back to 4/4, the section
times are reported as unreadable, and the observations say which of those happened.

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
# How long to wait for the piano roll script's reply. The script itself is fast; the
# wait is dominated by the keystroke and FL Studio taking focus. The same five
# seconds the riff and bassline tools use.
PIANO_ROLL_TIMEOUT = 5.0
CONTEXT_REQUEST_ID = "structure-context"


def project_context() -> dict[str, Any]:
    """The key and meter, or an empty dict when the piano roll did not answer.

    Returning an empty dict rather than a defaulted one matters: the converter has
    to put something in `beats_per_bar`, and a default is not a measurement. The
    caller can then say the meter was assumed.

    This is the standalone key and meter read, used by the template tools and by
    `structure_critique`, so one request shape serves every caller.
    """
    reply = _piano_roll_request({"action": "get_context", "id": CONTEXT_REQUEST_ID})
    return _context_from_readings(reply)


def _piano_roll_request(request: dict[str, Any]) -> dict[str, Any]:
    """Send one read-only request to the piano roll script, or an empty dict.

    The timeout and the manual trigger wait match the other piano roll callers: a
    keystroke that could not be delivered leaves the request on disk, and pressing
    the hotkey by hand still runs it.
    """
    try:
        reply = piano_roll.send_request(
            request,
            timeout=PIANO_ROLL_TIMEOUT,
            wait_for_manual_trigger=PIANO_ROLL_TIMEOUT,
        )
    except Exception:
        # A piano roll read is a bonus for the report, never a reason to lose it.
        return {}
    if not isinstance(reply, dict):
        return {}
    return reply


def structure_critique() -> dict[str, Any]:
    """Sections, pattern lengths and arithmetic findings, at a known cost.

    Returns:
        The critique, the context the arithmetic ran in, and how many controller
        round trips it took. A batch that fails is reported rather than raised, so a
        caller always has an answer. The cost is one controller round trip plus one
        piano roll request, which is also what `round_trips` counts: the controller's
        triggers, because that is the transport the caller paid for.
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
    markers = markers_reply.get("markers") or []

    # The key and the meter come from one get_context request, which is the request
    # the template tools make through project_context. It is sent after the batch: a
    # batch that failed has already returned, so a piano roll reading would have no
    # report to contribute to.
    context = project_context()
    meter_read = bool(context)
    # A missing timebase would leave the pattern arithmetic without a unit, so it
    # falls back to the PPQ the piano roll reported with the context, and only then
    # to the value observed on live FL Studio. The reply says which of the three
    # happened rather than presenting a fallback as a reading.
    ppq = ppq_reply.get("ppq")
    ppq_read = isinstance(ppq, int) and not isinstance(ppq, bool) and ppq > 0
    if ppq_read:
        ppq_source = "system.getPpq"
    elif isinstance(context.get("ppq"), int) and context["ppq"] > 0:
        ppq = context["ppq"]
        ppq_source = "the piano roll's own PPQ, because the batch did not report one"
    else:
        ppq = structure.DEFAULT_PPQ
        ppq_source = f"assumed {structure.DEFAULT_PPQ}, because the batch did not report it"
    context["ppq"] = ppq
    context["meter_read"] = meter_read

    report = structure.critique(context, patterns_reply.get("patterns") or [], markers)
    summary = report["summary"]
    return {
        "success": True,
        "round_trips": 1,
        "context": {
            "key": context.get("key"),
            "time_signature": summary["time_signature"],
            "beats_per_bar": summary["beats_per_bar"],
            "ppq": context["ppq"],
            "ppq_source": ppq_source,
            "meter_read": meter_read,
            "meter_source": (
                "score.tsnum and score.tsden, in the piano roll's sandbox"
                if meter_read
                else "assumed 4/4, because the piano roll script did not answer"
            ),
        },
        # The one machine readable field about marker times. Nothing can read one on
        # this build, so an arrangement holding markers has no time to give and an
        # arrangement holding none has nothing to time.
        "marker_times_source": (
            structure.TIMES_UNAVAILABLE if markers else structure.TIMES_NOT_NEEDED
        ),
        "sections": report["sections"],
        "patterns": report["patterns"],
        "observations": report["observations"],
        "summary": summary,
        "note": (
            "One controller round trip: the timebase, the patterns and the markers "
            "arrive in a single batch. One piano roll request carries the key and the "
            "meter, which no controller batch can reach. No marker time is readable "
            "on this build, so no section claims a bar position."
        ),
    }


def _context_from_readings(reply: dict[str, Any]) -> dict[str, Any]:
    """The key and meter from a piano roll reply, or an empty dict.

    Returning an empty dict rather than a defaulted one matters: the converter has
    to put something in `beats_per_bar`, and a default is not a measurement. The
    caller can then say the meter was assumed.

    A reply the converter refuses is an empty dict too. `scale_degrees` raises on a
    malformed scale helper, which is right at the musical layer, and a malformed
    helper must cost the context rather than take the whole structure report down
    with it.
    """
    if not reply:
        return {}
    if reply.get("success") is False or reply.get("error"):
        return {}
    if not _carries_context(reply):
        return {}
    try:
        return score.context_from_reply(reply)
    except Exception:
        return {}


def _response_entries(reply: dict[str, Any]) -> list[dict[str, Any]]:
    """The reply's per response entries, when it carries a well formed list of them.

    A reply from a different script version can hold anything under this key, and this
    module reads a reply rather than trusting it, so a shape it does not recognise
    yields no entries instead of an exception.
    """
    responses = reply.get("responses")
    if not isinstance(responses, list):
        return []
    return [entry for entry in responses if isinstance(entry, dict)]


def _carries_context(reply: dict[str, Any]) -> bool:
    """Whether a reply holds the piano roll's own context fields.

    An empty reply converts to a context anyway, because the converter has to
    default the meter to something. That default must not be reported as a
    measurement of 4/4, so it is rejected here. A null tsnum is rejected with it: the
    script writes the key whether or not the read behind it worked, and a present but
    null meter is not a measurement either.
    """
    candidates = [reply, *_response_entries(reply)]
    return any(
        entry.get("tsnum") is not None or bool(entry.get("scale_helper"))
        for entry in candidates
    )


def register_structure_tools(mcp: FastMCP) -> None:
    """Register the structure critique tool."""

    @mcp.tool()
    def fl_structure_critique() -> dict:
        """Read the song's structure: markers, section lengths and pattern lengths.

        Every observation is arithmetic over what FL reported. It will say that the
        last section is four bars and the others are sixteen, because that is a
        fact. It will not say that the chorus is too short, because that is taste
        and this tool has none.

        Cost: one controller round trip plus one piano roll request. The controller
        batch carries the timebase, every pattern and the arrangement's markers, and
        one piano roll script run carries the key and the meter, which the controller
        cannot reach. The arrangement reports a marker's name and no time, because
        its API has no function that reads one, and the piano roll's own marker
        accessors were measured on live FL Studio 2026 build 5406 and report zero
        markers on a project whose arrangement holds three. Marker times are
        therefore unreadable on this build, and no section is given a start bar or a
        length by guesswork: those fields come back as None.

        Read only: nothing in the project is changed.

        Returns:
            sections: one per marker, whose start_bar, length_bars and ticks are all
                      None because no marker time is readable
            patterns: every pattern's length in beats and bars, and whether it fills
                      a whole number of four bar blocks
            observations: the arithmetic findings, problems first, including the
                      informational marker_times_unreadable note
            summary: the counts, the meter the arithmetic used and the key when the
                      piano roll reported one
            marker_times_source: "unavailable" when the arrangement holds markers
                      whose times cannot be read, and "not_needed" when it holds none
        """
        return structure_critique()
