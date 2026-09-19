"""Saving, searching and recalling riffs against the fake FL and a temporary library."""

from __future__ import annotations

import pytest

from fl_studio_mcp.musical import riffs
from fl_studio_mcp.tools import riffs as riff_tools
from fl_studio_mcp.utils import store
from tests.fakes.project import Note

PPQ = 96


def phrase() -> list[Note]:
    """Two notes in A minor, one of them a slide, as the piano roll would hold them."""
    first = Note()
    first.number = 45
    first.time = 0
    first.length = PPQ // 2
    first.velocity = 0.9
    first.slide = True
    second = Note()
    second.number = 48
    second.time = PPQ // 2
    second.length = PPQ // 2
    second.velocity = 0.8
    return [first, second]


@pytest.fixture
def playing(fl_env, monkeypatch):
    """The riff tools wired to the in-process scripts and a fake project key."""
    from fl_studio_mcp.utils.midi_connection import MIDIConnection

    conn = MIDIConnection()
    conn._command_file = fl_env.command_file
    conn._response_file = fl_env.response_file
    conn._port = fl_env.midi_port
    conn._connected = True

    monkeypatch.setattr(riff_tools.piano_roll, "get_connection", lambda: conn, raising=False)
    monkeypatch.setattr(
        riff_tools.piano_roll, "piano_roll_scripts_dir", lambda: fl_env.piano_roll_dir
    )
    monkeypatch.setattr(riff_tools, "score", _FakeScore())

    def fake_trigger(delay: float = 0.0) -> bool:
        fl_env.pyscript.apply()
        return True

    monkeypatch.setattr(riff_tools.piano_roll, "trigger_fl_studio", fake_trigger)
    monkeypatch.setattr(riff_tools.piano_roll, "get_trigger", lambda: _Trigger())
    # The notes have to be in the piano roll for a save to find them. The score the
    # script reads is the project's flat note list, not the per pattern map.
    fl_env.project.notes = phrase()
    monkeypatch.setattr(riff_tools, "load_records", lambda: store.list_records("riffs"))
    return fl_env


class _Trigger:
    keystroke = "cmd+opt+y"
    last_error = None

    def __call__(self, delay: float = 0.0) -> bool:  # pragma: no cover - not used
        return True


class _FakeScore:
    """A project in A minor at 4/4, which is what the fake piano roll reports."""

    def get_project_context(self) -> dict:
        return {
            "root_note": 9,
            "scale_helper": "0,2,3,5,7,8,10",
            "scale_set": True,
            "key": "A minor",
            "tsnum": 4,
            "tsden": 4,
            "ppq": 96,
        }


def test_saving_captures_the_notes_the_piano_roll_holds(playing):
    result = riff_tools.save_riff("deep stab", tags=["dark"], channel=0)
    assert result["success"] is True, result
    record = store.read_record("riffs", result["id"])
    assert [note["midi"] for note in record["notes"]] == [45, 48]
    assert record["notes"][0]["slide"] is True, "expression must survive the save"


def test_a_saved_riff_carries_the_key_meter_and_instrument(playing):
    result = riff_tools.save_riff("deep stab", channel=0)
    record = store.read_record("riffs", result["id"])
    assert record["key"]["name"] == "A minor"
    assert record["meter"] == {"tsnum": 4, "tsden": 4}
    assert record["instrument"]
    assert record["note_count"] == 2


def test_an_empty_piano_roll_is_refused(playing):
    playing.project.notes = []
    result = riff_tools.save_riff("nothing", channel=0)
    assert result["success"] is False
    assert "no notes" in result["error"].lower()


def test_a_riff_without_a_name_is_refused(playing):
    result = riff_tools.save_riff("   ", channel=0)
    assert result["success"] is False
    assert "name" in result["error"].lower()


def test_saving_does_not_change_the_project(playing):
    before = {index: track.volume for index, track in enumerate(playing.project.tracks)}
    riff_tools.save_riff("deep stab", channel=0)
    after = {index: track.volume for index, track in enumerate(playing.project.tracks)}
    assert before == after


def test_a_saved_riff_can_be_found_by_tag_and_by_query(playing):
    riff_tools.save_riff("deep stab", tags=["dark", "stab"], mood="moody", channel=0)
    assert riff_tools.find_riffs(tags=["dark"])["total"] == 1
    assert riff_tools.find_riffs(query="stab")["total"] == 1
    assert riff_tools.find_riffs(query="moody")["total"] == 1
    assert riff_tools.find_riffs(query="polka")["total"] == 0


def test_search_results_omit_the_notes(playing):
    riff_tools.save_riff("deep stab", channel=0)
    found = riff_tools.find_riffs()["riffs"][0]
    assert "notes" not in found
    assert found["note_count"] == 2
    assert found["id"]


def test_an_empty_library_says_so(playing):
    result = riff_tools.find_riffs()
    assert result["total"] == 0
    assert "empty" in result["message"].lower()


def test_a_search_that_matches_nothing_names_the_filters(playing):
    riff_tools.save_riff("deep stab", channel=0)
    result = riff_tools.find_riffs(query="polka")
    assert "polka" in result["message"]
    assert "loosen" in result["message"].lower()


def test_search_reports_the_project_key_so_in_key_riffs_are_visible(playing):
    result = riff_tools.find_riffs()
    assert result["project_key"]["name"] == "A minor"


def test_recall_transposes_into_the_project_key(playing, monkeypatch):
    saved = riff_tools.save_riff("deep stab", channel=0)
    # A is three semitones below C, so a riff saved in A moves up three to sit in C.
    monkeypatch.setattr(riff_tools, "score", _FakeScoreIn("C major", 0))
    result = riff_tools.recall_riff(saved["id"], channel=0)
    assert result["success"] is True, result
    assert result["transposed_by"] == 3
    assert [note.number for note in playing.project.notes] == [48, 51]


def test_recall_without_transposition_writes_the_saved_notes(playing):
    saved = riff_tools.save_riff("deep stab", channel=0)
    playing.project.notes = []
    result = riff_tools.recall_riff(saved["id"], channel=0, transpose=False)
    assert result["transposed_by"] == 0
    assert [note.number for note in playing.project.notes] == [45, 48]


def test_recall_is_refused_when_the_project_has_no_key(playing, monkeypatch):
    saved = riff_tools.save_riff("deep stab", channel=0)
    monkeypatch.setattr(riff_tools, "score", _NoKeyScore())
    result = riff_tools.recall_riff(saved["id"], channel=0)
    assert result["success"] is False
    assert "transpose=False" in result["error"]


def test_recall_reports_clamped_notes(playing, monkeypatch):
    """A note pushed past 127 is clamped, and the caller is told rather than spared."""
    saved = riff_tools.save_riff("deep stab", channel=0)
    monkeypatch.setattr(riff_tools, "score", _FakeScoreIn("C major", 0))
    record = store.read_record("riffs", saved["id"])
    record["notes"] = [{"midi": 125, "time": 0.0, "duration": 1.0}]
    store.write_record("riffs", saved["id"], record, overwrite=True)

    result = riff_tools.recall_riff(saved["id"], channel=0)
    assert result["success"] is True
    assert result["clamped_notes"] == 1
    assert "clamped" in result["clamped_note"]


def test_recall_appends_when_asked(playing):
    saved = riff_tools.save_riff("deep stab", channel=0)
    result = riff_tools.recall_riff(saved["id"], channel=0, mode="append", transpose=False)
    assert result["success"] is True
    assert len(playing.project.notes) == 4, "the phrase was added, not replaced"


def test_recall_by_name_works_when_the_name_is_unique(playing):
    riff_tools.save_riff("deep stab", channel=0)
    result = riff_tools.recall_riff("deep stab", channel=0, transpose=False)
    assert result["success"] is True


def test_an_ambiguous_name_is_refused_with_both_ids(playing):
    riff_tools.save_riff("deep stab", channel=0)
    riff_tools.save_riff("deep stab", channel=0)
    result = riff_tools.recall_riff("deep stab", channel=0)
    assert result["success"] is False
    assert "ambiguous" in result["error"]
    assert result["error"].count("2026") == 2


def test_an_unknown_riff_names_the_tool_that_lists_them(playing):
    result = riff_tools.recall_riff("never saved", channel=0)
    assert result["success"] is False
    assert "fl_find_riffs" in result["error"]


def test_a_recall_reports_where_the_notes_landed(playing):
    saved = riff_tools.save_riff("deep stab", channel=0)
    result = riff_tools.recall_riff(saved["id"], channel=0)
    assert result["channel"] == 0
    assert result["verified"] is True
    assert result["verified_notes"] == 2


def test_a_saved_riff_is_in_the_library_not_in_fl(playing):
    """Nothing about the library depends on FL Studio still being open."""
    result = riff_tools.save_riff("deep stab", channel=0)
    assert store.read_record("riffs", result["id"])["name"] == "deep stab"


def test_the_summary_of_a_riff_matches_the_record_shape(playing):
    saved = riff_tools.save_riff("deep stab", channel=0)
    record = store.read_record("riffs", saved["id"])
    summary = riffs.summarise(record)
    assert summary["name"] == "deep stab"
    assert summary["created"] == record["created"]


class _FakeScoreIn(_FakeScore):
    def __init__(self, name: str, root: int) -> None:
        self._name = name
        self._root = root

    def get_project_context(self) -> dict:
        context = super().get_project_context()
        context.update({"key": self._name, "root_note": self._root, "scale_set": True})
        return context


class _NoKeyScore(_FakeScore):
    def get_project_context(self) -> dict:
        context = super().get_project_context()
        context.update({"scale_set": False, "root_note": None, "key": None})
        return context
