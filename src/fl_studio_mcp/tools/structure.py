"""Read the song's structure in one controller round trip, and report what is arithmetic.

The controller readings go in one batch: the timebase, every pattern and the
arrangement's markers. One trigger, one reply.

Neither the key and meter nor a marker's time can ride in that batch, and the reason
is architectural rather than an oversight: both live on `flpianoroll.score`, in the
piano roll's sandbox, and the controller cannot see them at all. `arrangement` can
read a marker's name and has no function that reads its time, so the arrangement is
the source of names and of the marker count while the piano roll is the source of
times. One piano roll request carries the marker times and the meter together,
because one script run can answer both and a second request would spend a second
keystroke on data the first run already had.

Both piano roll readings are bonuses for the report, never a reason to lose it. When
the script does not answer, the report still runs, the meter falls back to 4/4, the
section times are reported as unreadable rather than guessed, and the observations
say which of those happened.

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
MARKERS_REQUEST_ID = "structure-markers"


def project_context() -> dict[str, Any]:
    """The key and meter, or an empty dict when the piano roll did not answer.

    Returning an empty dict rather than a defaulted one matters: the converter has
    to put something in `beats_per_bar`, and a default is not a measurement. The
    caller can then say the meter was assumed.

    This is the standalone key and meter read, used by the template tools.
    `structure_critique` does not call it: it asks for the marker times and the meter
    in one request, so its piano roll cost stays at one script run.
    """
    reply = _piano_roll_request({"action": "get_context", "id": CONTEXT_REQUEST_ID})
    return _context_from_readings(reply)


def piano_roll_readings() -> dict[str, Any]:
    """One piano roll request: the marker times, the key and the meter.

    The critique needs the meter for its bar arithmetic and the times to measure a
    section at all, and one script run answers both, so they travel together. The
    action is the script's `get_markers`.

    Never raises. A piano roll read is a bonus for the report, never a reason to lose
    it: an empty dict comes back when the script does not answer, and the caller says
    which readings were missing.
    """
    return _piano_roll_request({"action": "get_markers", "id": MARKERS_REQUEST_ID})


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

    # One piano roll request answers the marker times and the meter together. It is
    # sent after the batch: a batch that failed has already returned, so a piano roll
    # reading would have no report to contribute to.
    readings = piano_roll_readings()
    context = _context_from_readings(readings)
    meter_read = bool(context)
    # A missing timebase would leave every marker unmeasurable, so it falls back. The
    # marker ticks arrived with the piano roll score's own PPQ, so that reading
    # measures them when the controller did not report one; only when neither did does
    # this fall back to the value observed on live FL Studio. The reply says which of
    # the three happened rather than presenting a fallback as a reading.
    ppq = ppq_reply.get("ppq")
    ppq_read = isinstance(ppq, int) and not isinstance(ppq, bool) and ppq > 0
    if ppq_read:
        ppq_source = "system.getPpq"
    elif isinstance(context.get("ppq"), int) and context["ppq"] > 0:
        ppq = context["ppq"]
        ppq_source = "the piano roll score's own PPQ, because the batch did not report one"
    else:
        ppq = structure.DEFAULT_PPQ
        ppq_source = f"assumed {structure.DEFAULT_PPQ}, because the batch did not report it"
    context["ppq"] = ppq
    context["meter_read"] = meter_read

    piano_roll_markers, markers_error = _markers_from_readings(readings)
    marker_times = structure.merge_marker_times(
        markers_reply.get("markers") or [], piano_roll_markers, markers_error
    )

    report = structure.critique(
        context,
        patterns_reply.get("patterns") or [],
        marker_times["markers"],
        marker_times=marker_times,
    )
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
        "marker_times_source": summary["marker_times_source"],
        "sections": report["sections"],
        "patterns": report["patterns"],
        "observations": report["observations"],
        "summary": summary,
        "note": (
            "One controller round trip: the timebase, the patterns and the markers "
            "arrive in a single batch. One piano roll request, which carries the key, "
            "the meter and the marker times together: a controller batch cannot reach "
            "any of them, and the arrangement's own reader returns a marker's name "
            "without its time."
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


def _markers_from_readings(reply: dict[str, Any]) -> tuple[list[dict] | None, str | None]:
    """The piano roll's marker list and the reason it is missing, from a reply.

    A marker list that is there is used even when the reply also carries an error,
    because a failed state export says nothing about whether the markers were read. A
    reply with no list at all is reported as missing rather than as an empty list:
    "the piano roll holds no markers" and "nobody could read its markers" are
    different facts, and the merge has to tell them apart.
    """
    entry = _markers_entry(reply)
    if entry is None:
        error = reply.get("error")
        if error:
            return None, str(error)
        return None, (
            "the reply carried no marker list, which is what a piano roll script that "
            "does not know the get_markers action returns"
        )

    markers = entry.get("markers")
    if isinstance(markers, list):
        return markers, None
    error = entry.get("markers_error") or reply.get("error")
    if error:
        return None, str(error)
    if markers is None:
        return None, "the piano roll reported no marker list"
    return None, "the piano roll reported its markers in a shape this server does not read"


def _markers_entry(reply: dict[str, Any]) -> dict[str, Any] | None:
    """The response entry that carries the marker list.

    The top level of the script's reply is the lead response, which is the whole
    answer for the single request this module sends. A reply that answered more than
    one request carries each answer separately, so the entry with this module's id is
    preferred over whichever one happened to be first.
    """
    candidates = [reply, *_response_entries(reply)]
    for candidate in candidates:
        if candidate.get("id") == MARKERS_REQUEST_ID and "markers" in candidate:
            return candidate
    for candidate in candidates:
        if "markers" in candidate or "markers_error" in candidate:
            return candidate
    return None


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
        one piano roll script run answers the marker times and the meter together.
        A second piano roll request would spend a second keystroke on data the first
        run already had.

        The arrangement reports a marker's name and no time, because the controller's
        API has no function that reads a time. The times come from the piano roll's
        own sandbox, matched to the arrangement's markers by index, and
        `marker_times_source` says what happened: "piano_roll" when the times were
        read, "mismatch" when the two sources counted a different number of markers,
        "unavailable" when no time could be read, and "not_needed" when the
        arrangement holds no markers. A section is only given a start bar and a
        length when its time was read; nothing here guesses one.

        Read only: nothing in the project is changed.

        Returns:
            sections: one per marker, with its start bar and its length to the next
                      marker, or None for the last one
            patterns: every pattern's length in beats and bars, and whether it fills
                      a whole number of four bar blocks
            observations: the arithmetic findings, problems first
            summary: the counts, the meter the arithmetic used, the key when the
                     piano roll reported one, and where the marker times came from
            marker_times_source: the summary value, repeated at the top level so a
                     caller can check it without reading the summary
        """
        return structure_critique()
