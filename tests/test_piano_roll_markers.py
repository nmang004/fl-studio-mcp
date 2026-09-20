"""Marker times, read in the piano roll sandbox and merged with the arrangement.

The controller can read a marker's name and has no function that reads its time, so
`arrangement.getMarkers` reports every time as None. `flpianoroll.score` is the one
sandbox where a time can be read, and this file pins the read, the reply shape and the
merge that carries the times into the structure critique.

The two fakes cannot agree by construction. `project.markers` is the arrangement as the
controller sees it, and `project.piano_roll_markers` is the piano roll's own list, kept
apart so a test can make the two sandboxes disagree. That disagreement is the case the
critique has to report rather than smooth over, and a fake that made them agree would
hide it.

The stubs define markerCount, getMarker and Marker.time. That is documentation, not a
measurement: nothing in this repository has seen the running piano roll sandbox expose
them, so the script probes before reading and says in its own reply when they are
absent. That path is tested here with a score object that has none of them.
"""

from __future__ import annotations

import json
import types

import pytest

from fl_studio_mcp.musical import structure
from fl_studio_mcp.tools import structure as structure_tool
from tests.fakes.project import Marker

PPQ = 96
BAR_4_4 = PPQ * 4


def write_request(fl_env, requests) -> None:
    fl_env.request_file.write_text(json.dumps(requests))


def read_response(fl_env) -> dict:
    return json.loads(fl_env.piano_roll_response_file.read_text())


def get_markers_reply(fl_env, markers=None) -> dict:
    """Run the real script on a get_markers request and return its real reply.

    The reply is produced by the handler under test rather than written to match what
    the server expects, because a reply that agrees with the parser is how this
    project has twice shipped a fake that agreed with the code instead of with FL.

    The action and the id are written as literals here rather than imported from the
    tool, for the same reason the harness keeps its own trigger note: a constant that
    is read from the code under test cannot disagree with it.
    """
    if markers is not None:
        fl_env.project.piano_roll_markers = list(markers)
    write_request(fl_env, [{"action": "get_markers", "id": "structure-markers"}])
    fl_env.pyscript.apply()
    return read_response(fl_env)


def kinds(report: dict) -> dict:
    """The observations by kind, so a test can name the one it is about."""
    return {observation["kind"]: observation for observation in report["observations"]}


class _BareMarker:
    """A marker whose time read raises, the way a runtime property can.

    The fake stores plain markers, and a marker that could never fail would never
    exercise the guard. This object is what a stubs-versus-runtime disagreement looks
    like from inside a request.
    """

    def __init__(self, name: str) -> None:
        self.name = name

    @property
    def time(self) -> int:
        raise RuntimeError("marker.time is not readable here")


# --- the script's get_markers handler -----------------------------------------


def test_the_handler_reports_each_marker_with_a_name_and_a_tick_time(fl_env):
    reply = get_markers_reply(fl_env, [Marker("Intro", 0), Marker("Verse", 4 * PPQ)])
    assert reply["markers"] == [
        {"index": 0, "name": "Intro", "time": 0},
        {"index": 1, "name": "Verse", "time": 4 * PPQ},
    ]


def test_the_handler_reports_the_scripts_own_ppq(fl_env):
    fl_env.project.ppq = 192
    reply = get_markers_reply(fl_env, [Marker("Intro", 0)])
    # The top level carries the lead response's ppq under the context name, and each
    # response entry carries it as ppq. Both are pinned: the server reads the top
    # level, and a caller matching by id reads the entry.
    assert reply["context_ppq"] == 192
    assert reply["responses"][0]["ppq"] == 192


def test_the_handler_reports_no_markers_rather_than_failing(fl_env):
    reply = get_markers_reply(fl_env, [])
    assert reply["success"] is True
    assert reply["markers"] == []
    assert reply["markers_error"] is None


def test_one_unreadable_marker_does_not_lose_the_others(fl_env):
    reply = get_markers_reply(fl_env, [_BareMarker("Broken"), Marker("Verse", 4 * PPQ)])
    markers = reply["markers"]
    assert [entry["name"] for entry in markers] == ["Broken", "Verse"]
    assert markers[0]["time"] is None
    assert "RuntimeError" in markers[0]["time_error"]
    assert markers[1]["time"] == 4 * PPQ


def test_a_marker_read_that_raises_costs_only_that_marker(fl_env, monkeypatch):
    """getMarker itself can fail, and the markers after it still arrive."""
    score = fl_env.modules["flpianoroll"].score
    original = score.getMarker

    def getMarker(index: int):
        if index == 0:
            raise RuntimeError("marker 0 is not readable")
        return original(index)

    monkeypatch.setattr(score, "getMarker", getMarker)
    reply = get_markers_reply(fl_env, [Marker("Broken", 0), Marker("Verse", 4 * PPQ)])
    assert [entry["name"] for entry in reply["markers"]] == [None, "Verse"]
    assert "RuntimeError" in reply["markers"][0]["error"]
    assert reply["markers"][1]["time"] == 4 * PPQ


def test_a_score_without_marker_accessors_says_so_rather_than_raising(fl_env, monkeypatch):
    """The one case the stubs cannot settle: a sandbox with no marker readers.

    The handler reports the absence in its own reply and still answers the key and
    meter, so the critique keeps its honest fallback instead of losing the request to
    an exception.
    """
    bare = types.SimpleNamespace(
        PPQ=fl_env.project.ppq,
        noteCount=0,
        snap_root_note=0,
        snap_scale_helper="",
        tsnum=3,
        tsden=4,
    )
    monkeypatch.setattr(fl_env.modules["flpianoroll"], "score", bare)

    reply = get_markers_reply(fl_env)

    assert reply["success"] is True
    assert reply["markers"] is None
    assert "getMarker" in reply["markers_error"]
    assert reply["error"] is None
    assert reply["tsnum"] == 3
    assert reply["tsden"] == 4


def test_the_marker_read_changes_nothing(fl_env):
    fl_env.project.piano_roll_markers = [Marker("Intro", 0)]
    fl_env.project.notes.append(fl_env.modules["flpianoroll"].Note(number=60))
    before = (list(fl_env.project.piano_roll_markers), list(fl_env.project.notes))
    get_markers_reply(fl_env)
    assert (fl_env.project.piano_roll_markers, fl_env.project.notes) == before


def test_the_script_registers_the_action_the_tool_asks_for(fl_env):
    """Half of the both-sides pin: the other half is the request the tool sends."""
    assert "get_markers" in fl_env.pyscript.HANDLERS


# --- merging the two sources --------------------------------------------------


def test_times_are_matched_by_index_not_by_list_position():
    markers = [
        {"index": 0, "name": "Intro", "time": None},
        {"index": 1, "name": "Verse", "time": None},
    ]
    piano_roll = [
        {"index": 1, "name": "Verse", "time": 4 * BAR_4_4},
        {"index": 0, "name": "Intro", "time": 0},
    ]
    merged = structure.merge_marker_times(markers, piano_roll)
    assert merged["source"] == structure.TIMES_FROM_PIANO_ROLL
    assert [(entry["name"], entry["time"]) for entry in merged["markers"]] == [
        ("Intro", 0),
        ("Verse", 4 * BAR_4_4),
    ]


def test_a_time_that_is_not_a_number_is_not_a_time():
    merged = structure.merge_marker_times(
        [{"index": 0, "name": "Intro", "time": None}],
        [{"index": 0, "name": "Intro", "time": "not a tick"}],
    )
    assert merged["markers"][0]["time"] is None
    assert merged["source"] == structure.TIMES_UNAVAILABLE


def test_the_piano_roll_reporting_no_list_is_not_an_empty_marker_list():
    """Nobody could read the markers and the piano roll holding none are different."""
    merged = structure.merge_marker_times(
        [{"index": 0, "name": "Intro", "time": None}], None, "the script did not answer"
    )
    assert merged["markers"][0]["time"] is None
    assert merged["source"] == structure.TIMES_UNAVAILABLE
    assert "the script did not answer" in merged["detail"]


def test_a_piano_roll_with_more_markers_than_the_arrangement_is_a_mismatch():
    merged = structure.merge_marker_times(
        [{"index": 0, "name": "Intro", "time": None}],
        [
            {"index": 0, "name": "Intro", "time": 0},
            {"index": 1, "name": "Time signature", "time": 0},
        ],
    )
    assert merged["source"] == structure.TIMES_MISMATCH
    assert merged["piano_roll_marker_count"] == 2
    assert merged["markers"][0]["time"] == 0


# --- the tool, with both real paths -------------------------------------------


@pytest.fixture
def wired(piano_roll_wired, monkeypatch):
    """The structure tool with both paths real: the controller batch and the script.

    The piano roll is not faked here. The tool writes its request through
    `piano_roll.send_request`, the in-process trigger runs the real script, and the
    reply the tool parses was written by the handler under test.
    """
    monkeypatch.setattr(
        structure_tool, "get_connection", lambda: piano_roll_wired.connection, raising=False
    )
    return piano_roll_wired


def capture_requests(fl_env, monkeypatch) -> list[dict]:
    """Record each piano roll request, before the script consumes the file it is in."""
    from fl_studio_mcp.tools import piano_roll

    requests: list[dict] = []

    def trigger(delay: float = 0.0) -> bool:
        requests.extend(json.loads(fl_env.request_file.read_text()))
        fl_env.pyscript.apply()
        return True

    monkeypatch.setattr(piano_roll, "trigger_fl_studio", trigger)
    return requests


def set_markers(fl_env, markers) -> None:
    """One song's markers, on both sides of the sandbox split.

    The arrangement stores (time, name) and reports the name only, because that is
    all its API can read. The piano roll stores named markers with tick times.
    """
    fl_env.project.markers = [(marker.time, marker.name) for marker in markers]
    fl_env.project.piano_roll_markers = list(markers)


def test_the_request_the_tool_sends_is_the_one_the_handler_answers(wired, monkeypatch):
    """The action name is pinned from both sides, so a rename cannot pass.

    The tool's request is read back from the file the script consumed, and the same
    run's reply is what gave the sections below their times. A rename in the script
    leaves the captured request unanswered, and a rename in the tool changes the
    captured request.
    """
    requests = capture_requests(wired, monkeypatch)
    set_markers(wired, [Marker("Intro", 0), Marker("Verse", 16 * BAR_4_4)])

    result = structure_tool.structure_critique()

    assert requests == [{"action": "get_markers", "id": "structure-markers"}]
    assert [section["start_bar"] for section in result["sections"]] == [1, 17]
    assert result["marker_times_source"] == "piano_roll"


def test_the_critique_costs_one_controller_round_trip_and_one_piano_roll_run(
    wired, monkeypatch
):
    requests = capture_requests(wired, monkeypatch)
    set_markers(wired, [Marker("Intro", 0)])
    before = wired.trigger_count

    structure_tool.structure_critique()

    assert wired.trigger_count - before == 1
    assert len(requests) == 1


def test_marker_times_give_sections_their_start_bars_and_lengths(wired):
    set_markers(
        wired,
        [
            Marker("Intro", 0),
            Marker("Verse 1", 16 * BAR_4_4),
            Marker("Chorus 1", 32 * BAR_4_4),
        ],
    )
    result = structure_tool.structure_critique()

    assert result["marker_times_source"] == "piano_roll"
    assert result["summary"]["marker_times_source"] == "piano_roll"
    assert [section["name"] for section in result["sections"]] == [
        "Intro", "Verse 1", "Chorus 1",
    ]
    assert [section["start_bar"] for section in result["sections"]] == [1, 17, 33]
    assert [section["length_bars"] for section in result["sections"]] == [16.0, 16.0, None]
    assert "marker_times_unreadable" not in kinds(result)


def test_the_marker_timebase_falls_back_to_the_scripts_own_ppq(wired, monkeypatch):
    """A batch without a timebase does not make the times unmeasurable.

    The ticks arrived with the piano roll score's own PPQ, so that reading measures
    them when system.getPpq did not report one. Only the value observed live is left
    as the assumption of last resort, and the reply names which one was used.
    """
    original = wired.connection.send_command

    def without_ppq(command, params=None, **kwargs):
        reply = original(command, params, **kwargs)
        for result in reply.get("results") or []:
            result.pop("ppq", None)
        return reply

    monkeypatch.setattr(wired.connection, "send_command", without_ppq)
    wired.project.ppq = 192
    # Sixteen bars of 4/4 at 192 PPQ. Read at 96 it would be bar 33, so the bars below
    # prove which reading measured the ticks.
    set_markers(wired, [Marker("Intro", 0), Marker("Verse", 16 * 4 * 192)])

    result = structure_tool.structure_critique()

    assert result["context"]["ppq"] == 192
    assert "own PPQ" in result["context"]["ppq_source"]
    assert [section["start_bar"] for section in result["sections"]] == [1, 17]
    assert result["sections"][0]["length_bars"] == 16.0


def test_sections_are_measured_in_three_four_too(wired):
    """Four bars of 3/4 is twelve beats, which is where this arithmetic was wrong."""
    wired.project.tsnum = 3
    wired.project.tsden = 4
    set_markers(wired, [Marker("A", 0), Marker("B", 12 * PPQ)])

    result = structure_tool.structure_critique()

    assert result["summary"]["time_signature"] == "3/4"
    assert [section["start_bar"] for section in result["sections"]] == [1, 5]
    assert result["sections"][0]["length_bars"] == 4.0


def test_a_marker_off_the_bar_line_is_a_problem_when_its_time_is_known(wired):
    set_markers(wired, [Marker("Intro", 0), Marker("Verse", 1500)])

    result = structure_tool.structure_critique()

    finding = kinds(result)["marker_off_bar_line"]
    assert finding["severity"] == "problem"
    assert "348 ticks after the bar line" in finding["detail"]


def test_the_arrangement_is_the_source_of_the_names(wired):
    """A name the piano roll reports is not used, even where the two disagree.

    The arrangement is the arrangement; the piano roll is asked for a time and
    nothing else.
    """
    set_markers(wired, [Marker("Intro", 0)])
    wired.project.piano_roll_markers = [Marker("a marker the arrangement never showed", 0)]

    result = structure_tool.structure_critique()

    assert [section["name"] for section in result["sections"]] == ["Intro"]
    assert result["sections"][0]["start_bar"] == 1


def test_an_unavailable_piano_roll_leaves_the_honest_fallback(wired, monkeypatch):
    """No reply is a normal outcome: names arrive, no bar position is claimed."""
    monkeypatch.setattr(
        structure_tool.piano_roll,
        "send_request",
        lambda request, **kwargs: {"success": False, "error": "no reply from the script"},
    )
    set_markers(wired, [Marker("Intro", 0), Marker("Verse", 16 * BAR_4_4)])

    result = structure_tool.structure_critique()

    assert result["marker_times_source"] == "unavailable"
    assert [section["name"] for section in result["sections"]] == ["Intro", "Verse"]
    assert [section["start_bar"] for section in result["sections"]] == [None, None]
    assert [section["length_bars"] for section in result["sections"]] == [None, None]
    finding = kinds(result)["marker_times_unreadable"]
    assert finding["severity"] == "informational"
    assert "no reply from the script" in finding["detail"]
    assert "marker_count_mismatch" not in kinds(result)
    assert result["context"]["meter_read"] is False


def test_a_reply_without_a_marker_list_is_unavailable_not_a_mismatch(wired, monkeypatch):
    """An older script answers get_context and knows nothing about markers."""
    monkeypatch.setattr(
        structure_tool.piano_roll,
        "send_request",
        lambda request, **kwargs: {
            "success": True,
            "action": "get_context",
            "id": "structure-markers",
            "root_note": 0,
            "scale_helper": "",
            "tsnum": 4,
            "tsden": 4,
            "error": None,
        },
    )
    set_markers(wired, [Marker("Intro", 0)])

    result = structure_tool.structure_critique()

    assert result["marker_times_source"] == "unavailable"
    assert "marker_count_mismatch" not in kinds(result)
    assert result["sections"][0]["start_bar"] is None
    assert result["context"]["meter_read"] is True


def test_a_marker_count_mismatch_is_reported_and_unmatched_markers_claim_no_bar(wired):
    """The arrangement is the count; the piano roll disagreed, so say so."""
    set_markers(
        wired,
        [
            Marker("Intro", 0),
            Marker("Verse", 16 * BAR_4_4),
            Marker("Chorus", 32 * BAR_4_4),
        ],
    )
    wired.project.piano_roll_markers = [Marker("Intro", 0), Marker("Verse", 16 * BAR_4_4)]

    result = structure_tool.structure_critique()

    assert result["marker_times_source"] == "mismatch"
    finding = kinds(result)["marker_count_mismatch"]
    assert finding["severity"] == "problem"
    assert finding["controller_marker_count"] == 3
    assert finding["piano_roll_marker_count"] == 2
    assert "reports 2" in finding["detail"]
    assert [section["name"] for section in result["sections"]] == [
        "Intro", "Verse", "Chorus",
    ]
    assert [section["start_bar"] for section in result["sections"]] == [1, 17, None]
    assert result["sections"][2]["length_bars"] is None
    # Why the third entry has no time is stated too, rather than left to be inferred.
    assert kinds(result)["marker_times_unreadable"]["severity"] == "informational"


def test_a_project_with_no_markers_has_nothing_to_time(wired):
    result = structure_tool.structure_critique()
    assert result["marker_times_source"] == "not_needed"
    assert "no_structure" in kinds(result)
    assert result["sections"] == []
