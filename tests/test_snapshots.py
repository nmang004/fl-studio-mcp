"""Snapshot arithmetic: flattening, diffing, and planning a restore.

The shapes here are the ones the live reads produce, including the float32 noise FL
returns for a fader it was asked to set to 0.8, because that noise is exactly what a
naive diff would report as a change on every project, forever.
"""

from __future__ import annotations

from fl_studio_mcp.musical import snapshots


def document() -> dict:
    """A small project in the shape the capture produces."""
    return {
        "schema": 1,
        "project": {"tempo": 130.0, "ppq": 96, "tsnum": 4, "tsden": 4},
        "mixer": {
            "tracks": {
                "0": {
                    "name": "Master",
                    "volume": 0.8,
                    "pan": 0.0,
                    "is_muted": False,
                    "is_solo": False,
                    "is_armed": False,
                    "stereo_separation": 0.0,
                    "color": 0,
                    "sends": [],
                },
                "1": {
                    "name": "Insert 1",
                    "volume": 0.8,
                    "pan": 0.0,
                    "is_muted": False,
                    "is_solo": False,
                    "is_armed": False,
                    "stereo_separation": 0.0,
                    "color": 0,
                    "sends": [0],
                    "eq": {
                        "bands": [
                            {"band": 0, "gain": 0.5, "frequency": 0.5, "bandwidth": 0.5},
                            {"band": 1, "gain": 0.5, "frequency": 0.5, "bandwidth": 0.5},
                        ]
                    },
                },
            }
        },
        "channels": {
            "0": {"name": "808 Kick", "is_muted": False, "volume": 0.8, "pan": 0.0, "color": 0}
        },
        "patterns": {"0": {"name": "Pattern 0", "color": 0, "length": 16}},
        "playlist": {
            "tracks": {
                "0": {"name": "Track 1", "color": 0, "is_muted": False, "is_solo": False}
            }
        },
        "markers": {},
    }


def changed(path: str, before, after) -> dict:
    """A document pair differing at exactly one path."""
    first = document()
    second = document()
    _set(second, path, after)
    _set(first, path, before)
    return {"before": first, "after": second}


def _set(document: dict, path: str, value) -> None:
    parts = path.split(".")
    node = document
    for part in parts[:-1]:
        node = node[part]
    node[parts[-1]] = value


# --- flattening --------------------------------------------------------------


def test_a_nested_document_flattens_to_dotted_paths():
    flat = snapshots.flatten(document())
    assert flat["mixer.tracks.1.volume"] == 0.8
    assert flat["channels.0.name"] == "808 Kick"
    assert flat["project.tempo"] == 130.0


def test_lists_are_flattened_by_index():
    """EQ bands arrive as a list, so their paths have to be addressable."""
    flat = snapshots.flatten({"bands": [{"gain": 0.5}, {"gain": 0.6}]})
    assert flat["bands.0.gain"] == 0.5
    assert flat["bands.1.gain"] == 0.6


def test_a_list_of_scalars_stays_one_value():
    """A track's sends are a set of destinations, so they diff as a set.

    Flattening them index by index turned one routing change into a list of added
    and removed positions, which no writer could turn back into a routing call.
    """
    flat = snapshots.flatten({"sends": [0, 2]})
    assert flat == {"sends": [0, 2]}


def test_an_empty_container_is_a_value_not_a_missing_branch():
    """`sends: []` means no sends, which is different from no sends key at all."""
    flat = snapshots.flatten({"a": [], "b": {}, "c": [1]})
    assert flat["a"] == []
    assert flat["b"] == {}
    assert flat["c"] == [1]


def test_float_noise_from_fl_is_rounded_away():
    """FL returns 0.7999999998137355 for a fader set to 0.8.

    Comparing those raw makes every snapshot differ from the next one by float32
    noise, which would report a change on every project on every run.
    """
    flat = snapshots.flatten({"volume": 0.7999999998137355})
    assert flat["volume"] == 0.8


def test_a_prefix_is_honoured():
    flat = snapshots.flatten({"a": 1}, prefix="root")
    assert flat == {"root.a": 1}


# --- diffing -----------------------------------------------------------------


def test_a_document_does_not_differ_from_itself():
    result = snapshots.diff(document(), document())
    assert result["counts"] == {"added": 0, "removed": 0, "changed": 0, "total": 0}


def test_a_changed_value_is_reported_with_both_sides():
    result = snapshots.diff(**changed("mixer.tracks.1.volume", 0.8, 0.65))
    assert result["changed"] == {"mixer.tracks.1.volume": {"before": 0.8, "after": 0.65}}
    assert result["counts"]["changed"] == 1


def test_a_new_path_is_added_and_a_lost_path_is_removed():
    before = document()
    after = document()
    del after["channels"]["0"]
    after["markers"] = {"0": {"name": "Intro", "time": 0}}
    result = snapshots.diff(before, after)
    assert "channels.0.name" in result["removed"]
    assert "markers.0.name" in result["added"]


def test_a_boolean_change_is_not_confused_with_a_number():
    """True equals 1 in Python, and a mute flag is not a fader value."""
    result = snapshots.diff(**changed("mixer.tracks.1.is_muted", False, 1))
    assert result["counts"]["changed"] == 1


def test_a_long_list_of_changes_is_capped_and_says_so():
    before = document()
    after = document()
    for index in range(2, 22):
        after["mixer"]["tracks"][str(index)] = {"volume": index / 100.0}
    result = snapshots.diff(before, after, limit=5)
    assert result["truncated"] is True
    assert len(result["added"]) == 5
    assert result["counts"]["added"] == 20


def test_a_diff_summary_counts_by_namespace():
    before = document()
    after = document()
    after["mixer"]["tracks"]["1"]["volume"] = 0.65
    after["mixer"]["tracks"]["1"]["pan"] = 0.2
    after["channels"]["0"]["name"] = "Kick"
    summary = snapshots.summarise_diff(snapshots.diff(before, after))
    assert summary["counts"]["changed"] == 3
    assert summary["by_namespace"] == {"channels": 1, "mixer": 2}
    assert "3" in summary["headline"]


# --- restore planning --------------------------------------------------------


def plan(before: dict, after: dict) -> dict:
    """The moves that turn `after` back into `before`."""
    return snapshots.restore_commands(before, after)


def test_a_restore_of_an_identical_project_does_nothing():
    result = plan(document(), document())
    assert result["commands"] == []
    assert result["unrestorable"] == []


def test_a_fader_change_becomes_one_command_with_the_snapshot_value():
    result = plan(*_pair("mixer.tracks.1.volume", 0.8, 0.65))
    assert len(result["commands"]) == 1
    command = result["commands"][0]
    assert command["action"] == "mixer.setTrackVolume"
    assert command["params"] == {"track": 1, "volume": 0.8}


def test_every_mixer_scalar_has_a_writer():
    wanted = {
        "volume": "mixer.setTrackVolume",
        "pan": "mixer.setTrackPan",
        "is_muted": "mixer.muteTrack",
        "is_solo": "mixer.soloTrack",
        "name": "mixer.setTrackName",
        "color": "mixer.setTrackColor",
        "stereo_separation": "mixer.setStereoSep",
    }
    for field, action in wanted.items():
        result = plan(*_pair(f"mixer.tracks.1.{field}", 0.5, 0.25))
        actions = [command["action"] for command in result["commands"]]
        assert action in actions, f"{field} has no writer"


def test_a_channel_change_becomes_a_channel_command():
    result = plan(*_pair("channels.0.volume", 0.8, 0.5))
    assert result["commands"][0]["action"] == "channels.setVolume"
    assert result["commands"][0]["params"] == {"index": 0, "volume": 0.8}


def test_an_arm_change_is_reported_as_a_toggle():
    """mixer.armTrack takes no value: it flips the state.

    Both sides are known, so a flip is the right move, but the caller deserves to
    know that it is a toggle rather than a value that was written.
    """
    result = plan(*_pair("mixer.tracks.1.is_armed", False, True))
    command = result["commands"][0]
    assert command["action"] == "mixer.armTrack"
    assert command["params"] == {"track": 1}
    assert command["toggle"] is True


def test_a_send_change_is_one_command_that_both_adds_and_removes():
    result = plan(*_pair("mixer.tracks.1.sends", [0], [0, 2]))
    commands = [
        command for command in result["commands"] if command["action"] == "mixer.setRouting"
    ]
    assert len(commands) == 1
    sends = commands[0]["params"]["sends"]
    assert sends == [{"track": 2, "remove": True}], (
        "only the difference is written: track 0 was already routed"
    )


def test_an_eq_change_is_one_command_for_the_whole_track():
    """Seven bands of three properties would be twenty one commands otherwise."""
    before = document()
    after = document()
    after["mixer"]["tracks"]["1"]["eq"]["bands"][0]["gain"] = 0.9
    result = plan(before, after)
    eq_commands = [
        command for command in result["commands"] if command["action"] == "mixer.setEqBands"
    ]
    assert len(eq_commands) == 1
    assert eq_commands[0]["params"]["track"] == 1
    assert eq_commands[0]["params"]["bands"][0] == {
        "band": 0,
        "gain": 0.5,
        "frequency": 0.5,
        "bandwidth": 0.5,
    }


def test_a_tempo_change_is_restored_with_the_measured_flag_word():
    result = plan(*_pair("project.tempo", 130.0, 140.0))
    command = result["commands"][0]
    assert command["action"] == "system.tempoProbe"
    assert command["params"]["bpm"] == 130.0
    assert command["params"]["flags"] == snapshots.TEMPO_WRITE_FLAGS


def test_the_tempo_flag_word_agrees_with_the_tempo_tool():
    """Two copies of a measured constant, pinned so they cannot drift."""
    from fl_studio_mcp.tools import tempo

    assert snapshots.TEMPO_WRITE_FLAGS == tempo.TEMPO_WRITE_FLAGS


def test_something_that_appeared_since_the_snapshot_is_not_deleted():
    """This version moves values back. It does not remove what you added."""
    before = document()
    after = document()
    after["markers"] = {"0": {"name": "Chorus", "time": 384}}
    result = plan(before, after)
    assert result["commands"] == []
    assert any("marker" in entry["path"] for entry in result["unrestorable"])
    assert any("appeared" in entry["reason"] for entry in result["unrestorable"])


def test_something_that_disappeared_is_reported_not_recreated():
    before = document()
    after = document()
    del after["channels"]["0"]
    result = plan(before, after)
    assert result["commands"] == []
    entry = next(e for e in result["unrestorable"] if e["path"].startswith("channels.0"))
    assert "gone" in entry["reason"] or "cannot" in entry["reason"]


def test_a_pattern_length_change_is_unrestorable_because_nothing_writes_it():
    result = plan(*_pair("patterns.0.length", 16, 32))
    assert result["commands"] == []
    assert result["unrestorable"][0]["path"] == "patterns.0.length"
    assert "no writer" in result["unrestorable"][0]["reason"]


def test_the_command_list_is_capped_and_says_so():
    before = document()
    after = document()
    for index in range(10):
        after["mixer"]["tracks"][str(index)] = {"volume": 0.1}
        before["mixer"]["tracks"][str(index)] = {"volume": 0.2}
    result = snapshots.restore_commands(before, after, limit=3)
    assert len(result["commands"]) == 3
    assert result["truncated"] is True
    assert result["counts"]["commands"] == 3
    assert result["counts"]["needed"] == 10


def test_plugin_parameters_are_captured_but_not_restored():
    """The preset library owns plugin values, and the plan says so."""
    before = document()
    after = document()
    before["plugins"] = {"channels.4": {"params": {"0": {"name": "Attack", "value": 0.5}}}}
    after["plugins"] = {"channels.4": {"params": {"0": {"name": "Attack", "value": 0.9}}}}
    result = plan(before, after)
    assert result["commands"] == []
    assert any("plugin" in entry["path"] for entry in result["unrestorable"])


def _pair(path: str, snapshot_value, current_value, **kwargs) -> tuple[dict, dict]:
    """A snapshot and a current document differing at one path."""
    snapshot = document()
    current = document()
    _set(snapshot, path, snapshot_value)
    _set(current, path, current_value)
    return snapshot, current
