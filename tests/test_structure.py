"""Structure is arithmetic over marker times and pattern lengths, in the meter.

The fixtures here are bars, because the arithmetic is about bars: one bar of 4/4 at
96 PPQ is 384 ticks and one bar of 3/4 is 288, and every expectation is written from
that rather than from a magic number.

No marker time is readable on this build. The controller's API has no function that
reads one, and the piano roll's own accessors were measured on live FL Studio 2026
build 5406 and report zero markers for a project whose arrangement holds three. So
this file pins both halves of that: the arithmetic that still measures a time it was
given, and the report that says the times are unavailable and claims no bar position
instead of inventing one.
"""

from __future__ import annotations

import pytest

from fl_studio_mcp.musical import structure
from fl_studio_mcp.tools import structure as structure_tool

PPQ = 96
BAR_4_4 = PPQ * 4
BAR_3_4 = PPQ * 3


def context(**overrides) -> dict:
    """A 4/4 project at 96 PPQ, with the meter read rather than assumed."""
    base = {
        "key": "A minor",
        "time_signature": "4/4",
        "beats_per_bar": 4.0,
        "ppq": PPQ,
        "meter_read": True,
    }
    base.update(overrides)
    return base


def kinds(report: dict) -> dict:
    """The observations by kind, so a test can name the one it is about."""
    return {observation["kind"]: observation for observation in report["observations"]}


def context_reply(tsnum: int = 4, tsden: int = 4) -> dict:
    """What the piano roll script writes for get_context.

    The tool sends the same request `project_context` sends, so this is the reply
    shape the context converter reads. It carries no marker list and never did: no
    marker time is readable anywhere on this build, so the tests that need one call
    the arithmetic directly instead.
    """
    return {
        "success": True,
        "action": "get_context",
        "id": "structure-context",
        "root_note": 9,
        # A minor, C-aligned: the helper is always twelve values starting at C, and
        # 0 means in the scale. Nine is A, so this is A minor.
        "scale_helper": "0,1,0,1,0,0,1,0,1,0,1,0",
        "tsnum": tsnum,
        "tsden": tsden,
        "ppq": PPQ,
        "error": None,
    }


# --- sections -----------------------------------------------------------------


def test_markers_become_sections_with_starts_and_lengths():
    markers = [
        {"index": 0, "name": "Intro", "time": 0},
        {"index": 1, "name": "Verse 1", "time": 16 * BAR_4_4},
        {"index": 2, "name": "Chorus 1", "time": 32 * BAR_4_4},
    ]
    result = structure.sections(markers, PPQ, 4.0)

    assert [section["name"] for section in result] == ["Intro", "Verse 1", "Chorus 1"]
    assert [section["start_bar"] for section in result] == [1, 17, 33]
    # Each length is measured to the next marker: 16 bars twice, and open at the end.
    assert [section["length_bars"] for section in result] == [16.0, 16.0, None]
    assert all(section["on_bar_line"] for section in result)


def test_a_marker_at_tick_zero_is_bar_one():
    result = structure.sections([{"index": 0, "name": "Intro", "time": 0}], PPQ, 4.0)
    assert result[0]["start_bar"] == 1
    assert result[0]["ticks"] == 0
    assert result[0]["length_bars"] is None


def test_the_last_section_has_no_length_rather_than_zero():
    """An open section is not a section of no length, and zero would say it was."""
    markers = [{"name": "A", "time": 0}, {"name": "B", "time": 8 * BAR_4_4}]
    result = structure.sections(markers, PPQ, 4.0)
    assert result[1]["length_bars"] is None
    assert result[0]["length_bars"] == 8.0


def test_markers_are_reported_in_timeline_order():
    """Index order is placement order, which is not timeline order after a drag."""
    markers = [
        {"index": 0, "name": "Late", "time": 8 * BAR_4_4},
        {"index": 1, "name": "Early", "time": 0},
    ]
    result = structure.sections(markers, PPQ, 4.0)
    assert [section["name"] for section in result] == ["Early", "Late"]
    assert result[0]["length_bars"] == 8.0


def test_a_marker_with_no_time_reports_none_rather_than_a_guess():
    """The controller cannot read a marker's time: the API has no such function."""
    markers = [{"index": 0, "name": "Intro", "time": None}]
    result = structure.sections(markers, PPQ, 4.0)
    assert result[0]["start_bar"] is None
    assert result[0]["length_bars"] is None
    assert result[0]["on_bar_line"] is None


def test_sections_in_three_four_measure_four_bars_as_twelve_beats():
    """Four bars of 3/4 is twelve beats. This is the arithmetic that was wrong before."""
    markers = [{"name": "A", "time": 0}, {"name": "B", "time": 12 * PPQ}]
    result = structure.sections(markers, PPQ, 3.0)
    assert result[0]["length_bars"] == 4.0
    assert result[1]["start_bar"] == 5


def test_a_position_that_is_a_bar_line_in_four_four_is_not_one_in_three_four():
    """Sixteen beats is four bars of 4/4 and five and a third bars of 3/4."""
    marker = [{"name": "X", "time": 16 * PPQ}]
    assert structure.sections(marker, PPQ, 4.0)[0]["on_bar_line"] is True
    assert structure.sections(marker, PPQ, 3.0)[0]["on_bar_line"] is False


def test_an_unusable_timebase_is_refused_rather_than_divided_by():
    with pytest.raises(ValueError):
        structure.sections([], 0, 4.0)
    with pytest.raises(ValueError):
        structure.pattern_report([], PPQ, 0)


# --- pattern lengths ----------------------------------------------------------


def test_a_pattern_that_fills_four_bar_blocks_is_marked_as_such():
    result = structure.pattern_report(
        [{"index": 0, "name": "eight bars", "length": 32}], PPQ, 4.0
    )
    assert result[0]["length_beats"] == 32.0
    assert result[0]["length_bars"] == 8.0
    assert result[0]["divides_into_four_bar_blocks"] is True


def test_a_pattern_that_does_not_fill_four_bar_blocks_is_marked_as_such():
    result = structure.pattern_report(
        [{"index": 1, "name": "three bars", "length": 12}], PPQ, 4.0
    )
    assert result[0]["length_bars"] == 3.0
    assert result[0]["divides_into_four_bar_blocks"] is False


def test_the_same_pattern_length_divides_in_one_meter_and_not_the_other():
    """Twelve beats is exactly four bars of 3/4 and three bars of 4/4."""
    in_three_four = structure.pattern_report(
        [{"index": 0, "name": "waltz", "length": 12}], PPQ, 3.0
    )[0]
    in_four_four = structure.pattern_report(
        [{"index": 0, "name": "waltz", "length": 12}], PPQ, 4.0
    )[0]
    assert in_three_four["length_bars"] == 4.0
    assert in_three_four["divides_into_four_bar_blocks"] is True
    assert in_four_four["length_bars"] == 3.0
    assert in_four_four["divides_into_four_bar_blocks"] is False


def test_a_pattern_length_is_beats_not_ticks():
    """The stub says beats, so sixteen beats is four bars and not sixteen ticks."""
    result = structure.pattern_report(
        [{"index": 0, "name": "Pattern 0", "length": 16}], PPQ, 4.0
    )[0]
    assert result["length_bars"] == 4.0
    assert result["length_ticks"] == 16 * PPQ


def test_an_unreadable_pattern_length_is_none_rather_than_zero():
    result = structure.pattern_report([{"index": 0, "name": "hm", "length": None}], PPQ, 4.0)
    assert result[0]["length_beats"] is None
    assert result[0]["divides_into_four_bar_blocks"] is None


# --- the critique -------------------------------------------------------------


def test_a_project_with_no_markers_says_there_is_no_structure():
    report = structure.critique(context(), [], [])
    finding = kinds(report)["no_structure"]
    assert finding["severity"] == "informational"
    assert "no structure to read" in finding["detail"]
    assert report["summary"]["problem_count"] == 0


def test_a_marker_off_the_bar_line_is_a_problem():
    """1500 ticks is three bars and 348 ticks into 4/4, which is not a bar line."""
    markers = [{"name": "Intro", "time": 0}, {"name": "Verse", "time": 1500}]
    report = structure.critique(context(), [], markers)
    finding = kinds(report)["marker_off_bar_line"]
    assert finding["severity"] == "problem"
    assert "Verse" in finding["detail"]
    assert "348 ticks after the bar line" in finding["detail"]


def test_a_marker_on_the_bar_line_is_not_reported():
    markers = [{"name": "Intro", "time": 0}, {"name": "Verse", "time": 16 * BAR_4_4}]
    report = structure.critique(context(), [], markers)
    assert "marker_off_bar_line" not in kinds(report)
    assert report["summary"]["problem_count"] == 0


def test_a_section_that_is_not_whole_bars_is_a_problem():
    """The same off-grid marker seen from the other side: the span it ends.

    A marker that sits between bar lines ends a section whose length is not a whole
    number of bars, so both findings are stated and neither is hidden.
    """
    markers = [{"name": "Intro", "time": 0}, {"name": "Verse", "time": 200}]
    report = structure.critique(context(), [], markers)
    finding = kinds(report)["section_not_whole_bars"]
    assert finding["severity"] == "problem"
    assert "Intro" in finding["detail"]
    assert "0.521 bars" in finding["detail"]


def test_a_section_between_two_bar_lines_is_not_reported():
    markers = [{"name": "Intro", "time": 0}, {"name": "Verse", "time": 4 * BAR_4_4}]
    report = structure.critique(context(), [], markers)
    assert "section_not_whole_bars" not in kinds(report)


def test_a_pattern_that_does_not_fill_four_bar_blocks_is_informational():
    report = structure.critique(context(), [{"index": 2, "name": "three bars", "length": 12}], [])
    finding = kinds(report)["pattern_not_four_bar_blocks"]
    assert finding["severity"] == "informational"
    assert finding["pattern"] == 2
    assert "3 bars in 4/4" in finding["detail"]


def test_a_pattern_that_fills_four_bar_blocks_is_not_reported():
    report = structure.critique(context(), [{"index": 0, "name": "Pattern 0", "length": 16}], [])
    assert "pattern_not_four_bar_blocks" not in kinds(report)


def test_markers_without_times_are_reported_as_unmeasurable():
    """The arrangement gives names and no times, so no position is claimed."""
    markers = [
        {"index": 0, "name": "Intro", "time": None},
        {"index": 1, "name": "Verse", "time": None},
    ]
    report = structure.critique(context(), [], markers)
    finding = kinds(report)["marker_times_unreadable"]
    assert finding["severity"] == "informational"
    assert report["summary"]["problem_count"] == 0
    assert [section["ticks"] for section in report["sections"]] == [None, None]
    assert [section["start_bar"] for section in report["sections"]] == [None, None]
    assert [section["length_bars"] for section in report["sections"]] == [None, None]
    assert [section["on_bar_line"] for section in report["sections"]] == [None, None]


def test_the_unreadable_reason_says_what_was_measured():
    """Both halves of the reason are measurements, so both are in the sentence."""
    markers = [{"index": 0, "name": "Intro", "time": None}]
    report = structure.critique(context(), [], markers)
    detail = kinds(report)["marker_times_unreadable"]["detail"]
    assert "1 of 1 marker(s) have no readable time" in detail
    assert "the controller's API has no function that reads one" in detail
    assert "report zero markers on this build" in detail


def test_the_last_section_is_compared_with_the_others():
    """"The last section is four bars and the others are sixteen" is arithmetic."""
    markers = [
        {"name": "Intro", "time": 0},
        {"name": "Verse", "time": 16 * BAR_4_4},
        {"name": "Chorus", "time": 32 * BAR_4_4},
        {"name": "Outro", "time": 48 * BAR_4_4},
        {"name": "End", "time": 52 * BAR_4_4},
    ]
    report = structure.critique(context(), [], markers)
    finding = kinds(report)["last_section_differs"]
    assert finding["severity"] == "informational"
    assert "4 bars" in finding["detail"]
    assert "16 bars" in finding["detail"]


def test_an_assumed_meter_is_stated_in_the_observations():
    report = structure.critique(context(meter_read=False, beats_per_bar=None), [], [])
    finding = kinds(report)["meter_assumed"]
    assert finding["severity"] == "informational"
    assert "assumption" in finding["detail"]
    assert report["summary"]["beats_per_bar"] == 4.0


def test_the_summary_says_the_observations_are_arithmetic():
    report = structure.critique(context(), [], [])
    assert "arithmetic" in report["summary"]["note"]


def test_the_critique_does_not_reorder_the_data_it_was_given():
    markers = [{"name": "B", "time": 0}, {"name": "A", "time": 4 * BAR_4_4}]
    patterns = [{"index": 0, "name": "P", "length": 16}]
    structure.critique(context(), patterns, markers)
    assert markers[0]["name"] == "B"
    assert len(patterns) == 1


# --- the tool -----------------------------------------------------------------


@pytest.fixture
def wired(fl_env, monkeypatch):
    """The structure tool wired to the in-process controller and a known context reply.

    The context read goes through the real converter here and only its reply is
    faked, because the converter is what turns tsnum and tsden into beats per bar.
    The reply is the get_context one, which is the only piano roll request the tool
    makes, and it carries no marker times because none are readable on this build.

    Every request the tool sends to the piano roll is recorded on
    `fl_env.piano_roll_requests`, so a test can count them and read the action.
    """
    from fl_studio_mcp.utils.midi_connection import MIDIConnection

    conn = MIDIConnection()
    conn._command_file = fl_env.command_file
    conn._response_file = fl_env.response_file
    conn._port = fl_env.midi_port
    conn._connected = True
    monkeypatch.setattr(structure_tool, "get_connection", lambda: conn, raising=False)

    requests: list[dict] = []

    def send_request(request, **kwargs):
        requests.append(dict(request))
        return context_reply()

    monkeypatch.setattr(structure_tool.piano_roll, "send_request", send_request)
    fl_env.connection = conn
    fl_env.piano_roll_requests = requests
    return fl_env


def test_the_whole_report_is_one_round_trip(wired):
    """One controller trigger and one piano roll request, and the report says so."""
    before = wired.trigger_count
    result = structure_tool.structure_critique()
    assert result["success"] is True, result
    assert wired.trigger_count - before == 1
    assert result["round_trips"] == 1
    assert [request["action"] for request in wired.piano_roll_requests] == ["get_context"]


def test_the_context_request_is_the_one_other_callers_send(wired):
    """The critique reads the key and meter through the shared get_context path.

    Pinned by comparing the two requests byte for byte: the template tools call
    `project_context`, the critique calls it too, and a second request shape would
    mean the critique had grown its own piano roll protocol again.
    """
    structure_tool.structure_critique()
    structure_tool.project_context()

    assert len(wired.piano_roll_requests) == 2
    assert wired.piano_roll_requests[0] == wired.piano_roll_requests[1]
    assert wired.piano_roll_requests[0]["action"] == "get_context"


def test_the_context_comes_back_through_the_piano_roll_request(wired):
    """The meter is measured rather than assumed, and the reply names its source."""
    result = structure_tool.structure_critique()
    assert result["context"]["meter_read"] is True
    assert result["context"]["time_signature"] == "4/4"
    assert result["summary"]["beats_per_bar"] == 4.0
    assert "piano roll" in result["context"]["meter_source"]


def test_the_real_script_answers_the_context_request(piano_roll_wired, monkeypatch):
    """Both sides of the request, without a faked reply on either side.

    The tool writes its request through the piano roll transport, the in-process
    trigger runs the real script, and the key and meter come back through the real
    converter. The project's meter is 3/4, so a measured meter is distinguishable
    from the 4/4 assumption, and the arrangement holds two markers whose times
    cannot be read, so no section may claim a bar position.
    """
    monkeypatch.setattr(
        structure_tool, "get_connection", lambda: piano_roll_wired.connection, raising=False
    )
    piano_roll_wired.project.tsnum = 3
    piano_roll_wired.project.tsden = 4
    piano_roll_wired.project.markers = [(0, "Intro"), (16 * BAR_4_4, "Verse")]

    result = structure_tool.structure_critique()

    assert result["success"] is True
    assert result["context"]["meter_read"] is True
    assert result["context"]["time_signature"] == "3/4"
    assert result["summary"]["beats_per_bar"] == 3.0
    assert [section["name"] for section in result["sections"]] == ["Intro", "Verse"]
    assert [section["start_bar"] for section in result["sections"]] == [None, None]
    assert result["marker_times_source"] == "unavailable"


def test_the_batch_carries_the_timebase_the_patterns_and_the_markers(wired, monkeypatch):
    sent = {}
    original = wired.connection.send_command

    def record(command, params=None, **kwargs):
        sent["command"] = command
        sent["params"] = params
        return original(command, params, **kwargs)

    monkeypatch.setattr(wired.connection, "send_command", record)
    structure_tool.structure_critique()

    assert sent["command"] == "system.batch"
    assert [command["action"] for command in sent["params"]["commands"]] == [
        "system.getPpq",
        "patterns.getAll",
        "arrangement.getMarkers",
    ]


def test_the_report_reads_the_patterns_fl_holds(wired):
    wired.project.patterns[0].length = 32
    result = structure_tool.structure_critique()
    assert result["patterns"][0]["length_beats"] == 32.0
    assert result["patterns"][0]["divides_into_four_bar_blocks"] is True


def test_the_report_uses_the_project_meter(wired, monkeypatch):
    monkeypatch.setattr(
        structure_tool.piano_roll,
        "send_request",
        lambda request, **kwargs: context_reply(tsnum=3, tsden=4),
    )
    wired.project.patterns[0].length = 12
    result = structure_tool.structure_critique()
    assert result["summary"]["time_signature"] == "3/4"
    assert result["patterns"][0]["length_bars"] == 4.0
    assert result["patterns"][0]["divides_into_four_bar_blocks"] is True


def test_system_getppq_is_the_primary_timebase(wired, monkeypatch):
    """The batch reading wins over the PPQ that arrives with the context."""
    monkeypatch.setattr(
        structure_tool.piano_roll,
        "send_request",
        lambda request, **kwargs: dict(context_reply(), ppq=192),
    )
    result = structure_tool.structure_critique()
    assert result["context"]["ppq"] == PPQ
    assert result["context"]["ppq_source"] == "system.getPpq"


def test_the_timebase_falls_back_to_the_piano_rolls_own_ppq(wired, monkeypatch):
    """A batch without a timebase still measures, from the reading beside the context."""
    original = wired.connection.send_command

    def without_ppq(command, params=None, **kwargs):
        reply = original(command, params, **kwargs)
        for result in reply.get("results") or []:
            result.pop("ppq", None)
        return reply

    monkeypatch.setattr(wired.connection, "send_command", without_ppq)
    monkeypatch.setattr(
        structure_tool.piano_roll,
        "send_request",
        lambda request, **kwargs: dict(context_reply(), ppq=192),
    )

    result = structure_tool.structure_critique()

    assert result["context"]["ppq"] == 192
    assert "own PPQ" in result["context"]["ppq_source"]
    # 16 beats at 192 PPQ, so the tick count proves which reading measured it.
    assert result["patterns"][0]["length_ticks"] == 16 * 192


def test_the_observed_ppq_is_the_last_resort(wired, monkeypatch):
    """Neither reading arrived, so the value observed on live FL is named as assumed."""
    original = wired.connection.send_command

    def without_ppq(command, params=None, **kwargs):
        reply = original(command, params, **kwargs)
        for result in reply.get("results") or []:
            result.pop("ppq", None)
        return reply

    monkeypatch.setattr(wired.connection, "send_command", without_ppq)
    context_without_ppq = context_reply()
    del context_without_ppq["ppq"]
    monkeypatch.setattr(
        structure_tool.piano_roll,
        "send_request",
        lambda request, **kwargs: context_without_ppq,
    )

    result = structure_tool.structure_critique()

    assert result["context"]["ppq"] == structure.DEFAULT_PPQ
    assert "assumed 96" in result["context"]["ppq_source"]
    assert result["context"]["meter_read"] is True


def test_markers_arrive_with_names_and_no_times(wired):
    """The arrangement is the source of marker names and of the marker count.

    arrangement.getMarkerName is the only marker reader in the controller's API, and
    the piano roll's own accessors report zero markers on this build, so every marker
    time is unavailable. Saying that is the honest answer, so the report says it and
    does not invent a bar position.
    """
    wired.project.markers = [(0, "Intro"), (16 * BAR_4_4, "Verse")]
    result = structure_tool.structure_critique()
    assert [section["name"] for section in result["sections"]] == ["Intro", "Verse"]
    assert result["summary"]["marker_count"] == 2
    assert result["sections"][0]["ticks"] is None
    assert result["sections"][0]["start_bar"] is None
    assert result["sections"][0]["length_bars"] is None
    assert result["marker_times_source"] == "unavailable"
    observed = {observation["kind"] for observation in result["observations"]}
    assert observed == {"marker_times_unreadable"}


def test_the_unreadable_finding_carries_the_measured_reason(wired):
    """The sentence names both measurements, so a later session has the evidence."""
    wired.project.markers = [(0, "Intro")]
    result = structure_tool.structure_critique()
    finding = {
        observation["kind"]: observation for observation in result["observations"]
    }["marker_times_unreadable"]
    assert finding["severity"] == "informational"
    assert "the controller's API has no function that reads one" in finding["detail"]
    assert "report zero markers on this build" in finding["detail"]
    assert result["summary"]["problem_count"] == 0


def test_an_unreadable_meter_is_stated_and_four_four_is_used(wired, monkeypatch):
    monkeypatch.setattr(
        structure_tool.piano_roll,
        "send_request",
        lambda request, **kwargs: {"success": False, "error": "no reply from the script"},
    )
    result = structure_tool.structure_critique()
    assert result["context"]["meter_read"] is False
    assert result["summary"]["beats_per_bar"] == 4.0
    assert any(
        observation["kind"] == "meter_assumed" for observation in result["observations"]
    )


def test_no_markers_is_informational_not_an_error(wired):
    result = structure_tool.structure_critique()
    assert result["success"] is True
    assert result["sections"] == []
    assert result["marker_times_source"] == "not_needed"
    assert any(
        observation["kind"] == "no_structure" for observation in result["observations"]
    )


def test_a_failed_batch_is_reported(wired, monkeypatch):
    monkeypatch.setattr(
        wired.connection,
        "send_command",
        lambda command, params=None, **kwargs: {"success": False, "error": "FL said no"},
    )
    result = structure_tool.structure_critique()
    assert result["success"] is False
    assert "FL said no" in result["error"]


def test_a_partly_read_batch_is_reported(wired, monkeypatch):
    """A short reply must not read as a project with no patterns and no markers."""
    monkeypatch.setattr(
        wired.connection,
        "send_command",
        lambda command, params=None, **kwargs: {"success": True, "results": [{"ppq": PPQ}]},
    )
    result = structure_tool.structure_critique()
    assert result["success"] is False
    assert "partly read" in result["error"]


def test_the_critique_changes_nothing(wired):
    wired.project.markers = [(0, "Intro")]
    before = (list(wired.project.markers), wired.project.patterns[0].name)
    structure_tool.structure_critique()
    assert (wired.project.markers, wired.project.patterns[0].name) == before


def test_the_context_read_converts_the_piano_roll_reply(wired, monkeypatch):
    """The real conversion runs here: a fake reply in, beats_per_bar out."""
    monkeypatch.setattr(
        structure_tool.piano_roll,
        "send_request",
        lambda request, **kwargs: {
            "success": True,
            "action": "get_context",
            "root_note": 9,
            "scale_helper": "0,1,0,1,0,0,1,0,1,0,1,0",
            "tsnum": 3,
            "tsden": 4,
            "ppq": PPQ,
            "error": None,
        },
    )
    result = structure_tool.project_context()
    assert result["time_signature"] == "3/4"
    assert result["beats_per_bar"] == 3.0
    assert result["key"] == "A minor"


def test_a_context_reply_that_failed_is_not_read_as_a_measurement(wired, monkeypatch):
    monkeypatch.setattr(
        structure_tool.piano_roll,
        "send_request",
        lambda request, **kwargs: {"success": False, "error": "no reply from the script"},
    )
    assert structure_tool.project_context() == {}


def test_a_context_reply_with_nothing_in_it_is_not_read_as_four_four(wired, monkeypatch):
    monkeypatch.setattr(
        structure_tool.piano_roll,
        "send_request",
        lambda request, **kwargs: {"success": True, "action": "get_context", "error": None},
    )
    assert structure_tool.project_context() == {}


def test_a_context_reply_that_cannot_be_converted_is_not_an_exception(wired, monkeypatch):
    """A malformed scale helper costs the context, not the whole report.

    scale_degrees refuses a helper that is not twelve values, which is right at the
    musical layer. A structure report must survive that rather than raise out of the
    tool.
    """
    monkeypatch.setattr(
        structure_tool.piano_roll,
        "send_request",
        lambda request, **kwargs: {
            "success": True,
            "action": "get_context",
            "root_note": 0,
            "scale_helper": "0,1,0",
            "tsnum": 4,
            "tsden": 4,
            "error": None,
        },
    )
    assert structure_tool.project_context() == {}
