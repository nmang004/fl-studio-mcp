"""Templates validate before they apply, and they never claim to load an instrument."""

from __future__ import annotations

import pytest

from fl_studio_mcp.musical import templates
from fl_studio_mcp.tools import templates as template_tools
from tests.fakes.project import FakeProject

PPQ = 96
MIXING = templates.TEMPLATES["mixing"]
SECTIONS = templates.TEMPLATES["sections"]


def readings(
    track_count: int = 16,
    lane_count: int = 0,
    ppq: int = PPQ,
    beats_per_bar: float = 4.0,
    track_names: dict | None = None,
    lane_names: dict | None = None,
) -> dict:
    """What the tool reads before a plan.

    Every track starts at FL's generated name and `track_names` overrides the ones a
    test wants renamed, so a test says which track the producer touched rather than
    listing all sixteen.
    """
    names = {index: f"Insert {index}" for index in range(1, track_count)}
    names.update(track_names or {})
    return {
        "ppq": ppq,
        "beats_per_bar": beats_per_bar,
        "track_names": names,
        "lane_names": lane_names if lane_names is not None else {},
        "lane_count": lane_count,
    }


def actions(plan: dict) -> list[str]:
    return [command["action"] for command in plan["commands"]]


def named(plan: dict, index: int) -> list[str]:
    """The names a plan would give to one mixer track, if any."""
    return [
        command["params"]["name"]
        for command in plan["commands"]
        if command["action"] == "mixer.setTrackName" and command["params"]["track"] == index
    ]


# --- the catalogue and the spec data ------------------------------------------


def test_the_catalogue_lists_the_built_ins():
    entries = {entry["name"]: entry for entry in templates.catalogue()}
    assert set(entries) == {"mixing", "sections"}
    for entry in entries.values():
        assert entry["description"]
        assert entry["objects"] > 0
        assert entry["loads_instruments"] is False


def test_the_built_in_specs_are_plain_data():
    """A spec is data, so a producer can write one without reading any code."""
    allowed = {
        "tracks": {"track", "name", "color", "sends"},
        "lanes": {"lane", "name", "color"},
        "channels": {"channel", "name", "color"},
        "markers": {"bar", "name"},
    }
    for spec in templates.TEMPLATES.values():
        for key, value in spec.items():
            if key == "description":
                assert isinstance(value, str)
                continue
            assert key in allowed, key
            assert isinstance(value, list)
            for entry in value:
                assert isinstance(entry, dict)
                assert set(entry) <= allowed[key], entry
                for field, inner in entry.items():
                    assert isinstance(inner, (int, str, list)), (field, inner)
                    if isinstance(inner, list):
                        assert all(isinstance(item, int) for item in inner)


def test_the_mixing_template_names_colours_and_routes_eight_inserts():
    plan = templates.validate(MIXING, 16, 4, project=readings())
    assert plan["problems"] == []
    assert plan["skipped"] == []
    assert len(named(plan, 1)) == 1
    assert "mixer.setTrackColor" in actions(plan)
    assert "mixer.setRouting" in actions(plan)
    names = [
        command for command in plan["commands"] if command["action"] == "mixer.setTrackName"
    ]
    assert len(names) == 8
    routes = [
        command["params"]["sends"] for command in plan["commands"]
        if command["action"] == "mixer.setRouting" and command["params"]["track"] == 3
    ]
    assert routes == [[{"track": 7}, {"track": 8}]]


def test_the_returns_are_named_too():
    plan = templates.validate(MIXING, 16, 4, project=readings())
    assert named(plan, 7) == ["Reverb"]
    assert named(plan, 8) == ["Delay"]


def test_a_track_the_producer_named_is_skipped():
    plan = templates.validate(
        MIXING, 16, 4, project=readings(track_names={3: "My Bass"})
    )
    assert [entry["index"] for entry in plan["skipped"]] == [3]
    assert plan["skipped"][0]["current_name"] == "My Bass"
    assert "My Bass" in plan["skipped"][0]["reason"]
    assert named(plan, 3) == []
    assert named(plan, 2) == ["Bass"], "the rest of the template is still planned"


def test_overwrite_touches_a_named_track():
    plan = templates.validate(
        MIXING, 16, 4, overwrite=True, project=readings(track_names={3: "My Bass"})
    )
    assert plan["skipped"] == []
    assert named(plan, 3) == ["Keys"]


def test_a_track_whose_name_was_not_read_is_left_alone():
    """An unread name is not evidence that nobody has claimed the track."""
    plan = templates.validate(MIXING, 16, 4)
    assert plan["commands"] == []
    assert len(plan["skipped"]) == 8
    assert "overwrite=True" in plan["skipped"][0]["reason"]


def test_a_lane_that_still_carries_fls_generated_name_is_named():
    spec = {"lanes": [{"lane": 2, "name": "Verse", "color": 0x4E79A7}]}
    plan = templates.validate(
        spec, 16, 4, project=readings(lane_count=4, lane_names={2: "Track 2"})
    )
    assert plan["commands"] == [{
        "action": "playlist.setTrack",
        "params": {"index": 2, "name": "Verse", "color": 0x4E79A7},
    }]


def test_a_lane_the_producer_named_is_skipped():
    spec = {"lanes": [{"lane": 2, "name": "Verse"}]}
    plan = templates.validate(
        spec, 16, 4, project=readings(lane_count=4, lane_names={2: "Drop"})
    )
    assert plan["commands"] == []
    assert plan["skipped"][0]["current_name"] == "Drop"


def test_a_lane_out_of_range_is_a_problem():
    spec = {"lanes": [{"lane": 9, "name": "Verse"}]}
    plan = templates.validate(spec, 16, 4, project=readings(lane_count=4))
    assert "lanes[0].lane" in plan["problems"][0]


def test_a_lane_cannot_be_checked_without_the_lane_count():
    spec = {"lanes": [{"lane": 0, "name": "Verse"}]}
    plan = templates.validate(spec, 16, 4, project={"lane_names": {}})
    assert "lanes[0].lane" in plan["problems"][0]


def test_a_channel_is_only_renamed_with_overwrite():
    """FL's generated name for a Channel Rack channel has not been measured."""
    spec = {"channels": [{"channel": 1, "name": "Bass", "color": 0x4E79A7}]}
    plan = templates.validate(spec, 16, 4, project=readings())
    assert plan["commands"] == []
    assert plan["skipped"][0]["kind"] == "channel"

    overwritten = templates.validate(spec, 16, 4, overwrite=True, project=readings())
    assert actions(overwritten) == ["channels.setName", "channels.setColor"]


def test_a_channel_out_of_range_is_a_problem():
    spec = {"channels": [{"channel": 9, "name": "Bass"}]}
    plan = templates.validate(spec, 16, 4, project=readings())
    assert "channels[0].channel" in plan["problems"][0]


# --- specs that are refused ---------------------------------------------------


def test_a_spec_that_is_not_an_object_is_refused():
    plan = templates.validate(["tracks"], 16, 4)
    assert plan == {
        "commands": [],
        "skipped": [],
        "problems": ["the spec must be an object"],
    }


def test_an_unknown_field_is_a_problem_with_its_path():
    spec = {"tracks": [{"track": 1, "name": "Kick", "colour": 0xFF0000}]}
    plan = templates.validate(spec, 16, 4, project=readings())
    assert plan["commands"] == []
    assert "tracks[0].colour" in plan["problems"][0]


def test_an_unknown_top_level_field_is_a_problem():
    plan = templates.validate({"template": "mixing"}, 16, 4, project=readings())
    assert any("template is not a field" in problem for problem in plan["problems"])


def test_an_out_of_range_track_is_a_problem():
    spec = {"tracks": [{"track": 99, "name": "Kick"}]}
    plan = templates.validate(spec, 16, 4, project=readings())
    assert "tracks[0].track" in plan["problems"][0]


def test_the_master_track_is_not_a_target():
    spec = {"tracks": [{"track": 0, "name": "Master"}]}
    plan = templates.validate(spec, 16, 4, project=readings())
    assert "tracks[0].track" in plan["problems"][0]
    assert "Master" in plan["problems"][0]


def test_a_wrong_type_is_a_problem_with_its_path():
    spec = {"tracks": [{"track": "1", "name": 7, "color": "red", "sends": 7}]}
    plan = templates.validate(spec, 16, 4, project=readings())
    paths = {problem.split()[0] for problem in plan["problems"]}
    assert {
        "tracks[0].track",
        "tracks[0].name",
        "tracks[0].color",
        "tracks[0].sends",
    } <= paths


def test_a_send_destination_out_of_range_is_a_problem():
    spec = {"tracks": [{"track": 1, "name": "Kick", "sends": [99]}]}
    plan = templates.validate(spec, 16, 4, project=readings())
    assert "tracks[0].sends[0]" in plan["problems"][0]


def test_a_track_cannot_send_to_itself():
    spec = {"tracks": [{"track": 1, "name": "Kick", "sends": [1]}]}
    plan = templates.validate(spec, 16, 4, project=readings())
    assert any("feedback" in problem for problem in plan["problems"])


def test_nothing_is_planned_when_any_entry_is_wrong():
    """A typo in the ninth track must not apply the first eight."""
    spec = {
        "tracks": [
            {"track": 1, "name": "Kick"},
            {"track": 2, "name": "Snare", "colour": 1},
        ]
    }
    plan = templates.validate(spec, 16, 4, project=readings())
    assert plan["problems"]
    assert plan["commands"] == []
    assert plan["skipped"] == []


# --- markers ------------------------------------------------------------------


def test_markers_become_ticks_in_the_project_meter():
    plan = templates.validate(SECTIONS, 16, 4, project=readings(beats_per_bar=4.0))
    times = [command["params"]["time"] for command in plan["commands"]]
    assert times[0] == 0, "bar 1 is tick 0"
    assert times[1] == 8 * 4 * PPQ, "bar 9 is eight 4/4 bars in"
    assert len(times) == 8


def test_markers_in_three_four_are_three_beats_to_the_bar():
    """Eight bars of 3/4 is twenty four beats, not thirty two."""
    plan = templates.validate(SECTIONS, 16, 4, project=readings(beats_per_bar=3.0))
    times = [command["params"]["time"] for command in plan["commands"]]
    assert times[1] == 8 * 3 * PPQ
    assert times[1] != 8 * 4 * PPQ


def test_a_marker_without_a_meter_is_refused_by_path():
    """A marker placed from an assumed meter lands in the wrong place."""
    plan = templates.validate(SECTIONS, 16, 4)
    assert plan["commands"] == []
    assert "markers[0].bar" in plan["problems"][0]


def test_a_bar_below_one_is_a_problem():
    plan = templates.validate(
        {"markers": [{"bar": 0, "name": "Nope"}]}, 16, 4, project=readings()
    )
    assert "markers[0].bar" in plan["problems"][0]


# --- the instrument helper ----------------------------------------------------


def test_the_helper_names_the_tracks_no_channel_is_routed_into():
    channels = [{"index": 0, "target_fx_track": 3}, {"index": 1, "target_fx_track": 3}]
    empty = templates.tracks_without_instruments(MIXING, channels)
    assert [entry["track"] for entry in empty] == [1, 2, 4, 5, 6, 7, 8]
    assert empty[0]["name"] == "Drums"


def test_a_spec_with_no_tracks_has_nothing_without_an_instrument():
    assert templates.tracks_without_instruments(SECTIONS, []) == []


# --- the tool -----------------------------------------------------------------


@pytest.fixture
def wired(fl_env, monkeypatch):
    """The template tool wired to the in-process controller and a 4/4 meter.

    A wider mixer than the shared harness starts with, because the built-in mixing
    template names eight inserts and the default project has seven.
    """
    from fl_studio_mcp.utils.midi_connection import MIDIConnection

    fl_env.project.tracks = FakeProject.with_tracks(16).tracks
    conn = MIDIConnection()
    conn._command_file = fl_env.command_file
    conn._response_file = fl_env.response_file
    conn._port = fl_env.midi_port
    conn._connected = True
    monkeypatch.setattr(template_tools, "get_connection", lambda: conn, raising=False)
    # run_batch holds its own reference, so it is patched on its own module.
    monkeypatch.setattr(template_tools.batch, "get_connection", lambda: conn, raising=False)
    # The meter read is imported by name into this module, so patching it anywhere
    # else would leave this module calling the real piano roll path.
    monkeypatch.setattr(
        template_tools,
        "project_context",
        lambda: {"beats_per_bar": 4.0, "time_signature": "4/4", "key": "A minor"},
    )
    fl_env.connection = conn
    return fl_env


def state(project) -> list[tuple]:
    return [
        (track.name, track.color, dict(track.routes)) for track in project.tracks
    ]


def test_no_template_returns_the_catalogue_and_sends_nothing(wired):
    before = wired.trigger_count
    result = template_tools.apply_template()
    assert result["success"] is True
    assert result["applied"] is False
    assert {entry["name"] for entry in result["templates"]} == {"mixing", "sections"}
    assert wired.trigger_count == before, "the catalogue must not touch FL"


def test_a_plan_is_one_round_trip(wired):
    before = wired.trigger_count
    template_tools.apply_template("mixing")
    assert wired.trigger_count - before == 1


def test_reporting_a_template_changes_nothing(wired):
    before = state(wired.project)
    result = template_tools.apply_template("mixing")
    assert result["success"] is True
    assert result["applied"] is False
    assert result["move_count"] == len(result["moves"]) == 21
    assert state(wired.project) == before
    assert "apply=True" in result["message"]


def test_applying_a_template_goes_through_one_named_batch(wired, monkeypatch):
    calls = []

    def fake_batch(commands, name):
        calls.append((commands, name))
        return {"success": True, "executed": len(commands), "undo_name": name}

    monkeypatch.setattr(template_tools.batch, "run_batch", fake_batch)
    result = template_tools.apply_template("mixing", apply=True)
    assert result["applied"] is True
    assert len(calls) == 1, "one undo entry for the whole template"
    commands, name = calls[0]
    assert commands
    assert name == "MCP: apply template"


def test_applying_the_mixing_template_names_colours_and_routes(wired):
    before = wired.trigger_count
    result = template_tools.apply_template("mixing", apply=True)
    assert result["applied"] is True, result
    assert wired.trigger_count - before == 2, "one read batch and one write batch"
    assert wired.project.track(1).name == "Drums"
    assert wired.project.track(1).color == 0xE15759
    assert 7 in wired.project.track(1).routes
    assert set(wired.project.track(3).routes) == {7, 8}
    assert wired.project.track(7).name == "Reverb"
    assert wired.project.track(8).name == "Delay"
    assert result["batch"]["undo_name"] == "MCP: apply template"


def test_a_track_the_producer_named_is_skipped_and_named_in_the_reply(wired):
    wired.project.track(3).name = "My Bass"
    result = template_tools.apply_template("mixing")
    assert [entry["index"] for entry in result["skipped"]] == [3]
    assert result["skipped"][0]["current_name"] == "My Bass"
    assert "My Bass" in result["message"]
    assert not any(
        command["action"] == "mixer.setTrackName" and command["params"]["track"] == 3
        for command in result["moves"]
    )


def test_overwrite_touches_the_named_track(wired):
    wired.project.track(3).name = "My Bass"
    result = template_tools.apply_template("mixing", overwrite=True, apply=True)
    assert result["applied"] is True, result
    assert result["skipped"] == []
    assert wired.project.track(3).name == "Keys"


def test_a_template_with_nothing_to_do_does_not_send_a_batch(wired, monkeypatch):
    for track in wired.project.tracks[1:9]:
        track.name = "taken"
    calls = []
    monkeypatch.setattr(
        template_tools.batch, "run_batch", lambda commands, name: calls.append(name)
    )
    result = template_tools.apply_template("mixing", apply=True)
    assert result["applied"] is False
    assert calls == []
    assert "Nothing to do" in result["message"]


def test_an_invalid_spec_is_refused_by_path_and_nothing_is_applied(wired, monkeypatch):
    calls = []
    monkeypatch.setattr(
        template_tools.batch, "run_batch", lambda commands, name: calls.append(name)
    )
    before = state(wired.project)
    result = template_tools.apply_template(
        spec={"tracks": [{"track": 1, "name": "Kick", "colour": 0xFF0000}]}, apply=True
    )
    assert result["success"] is False
    assert "tracks[0].colour" in result["problems"][0]
    assert calls == []
    assert state(wired.project) == before


def test_the_reply_says_an_instrument_cannot_be_loaded(wired):
    result = template_tools.apply_template("mixing")
    assert "cannot load an instrument" in result["instrument_note"]
    names = [entry["name"] for entry in result["without_instruments"]]
    assert "Drums" in names, "the fake project routes no channel into the inserts"


def test_the_sections_template_is_refused_without_the_meter(wired, monkeypatch):
    monkeypatch.setattr(template_tools, "project_context", dict)
    result = template_tools.apply_template("sections", apply=True)
    assert result["success"] is False
    assert "markers[0].bar" in result["problems"][0]
    assert wired.project.markers == []


def test_the_sections_template_places_eight_bar_markers(wired):
    result = template_tools.apply_template("sections", apply=True)
    assert result["applied"] is True, result
    assert [name for _, name in wired.project.markers] == [
        "Intro",
        "Verse 1",
        "Chorus 1",
        "Verse 2",
        "Chorus 2",
        "Bridge",
        "Chorus 3",
        "Outro",
    ]
    assert wired.project.markers[1] == (8 * 4 * PPQ, "Verse 1")


def test_a_spec_of_your_own_is_planned_without_a_template_name(wired):
    result = template_tools.apply_template(
        spec={
            "tracks": [{"track": 2, "name": "Bass", "color": 0x4E79A7}],
            "markers": [{"bar": 5, "name": "Drop"}],
        }
    )
    assert result["template"] == "custom"
    assert [command["action"] for command in result["moves"]] == [
        "mixer.setTrackName",
        "mixer.setTrackColor",
        "arrangement.addMarker",
    ]
    assert result["moves"][2]["params"] == {"time": 16 * PPQ, "name": "Drop"}


def test_an_unknown_template_name_is_refused(wired):
    before = wired.trigger_count
    result = template_tools.apply_template(template="nope")
    assert result["success"] is False
    assert "mixing" in result["error"]
    assert wired.trigger_count == before


def test_a_template_and_a_spec_together_are_refused(wired):
    before = wired.trigger_count
    result = template_tools.apply_template(template="mixing", spec={"tracks": []})
    assert result["success"] is False
    assert "not both" in result["error"]
    assert wired.trigger_count == before
