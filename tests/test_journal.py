"""The journal records edits, and never breaks the command it records.

Two paths can edit a project: commands to the controller script, and requests to the
piano roll script. Both are covered here, because a journal that only saw one of them
would answer "what did the server do" with half the truth.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from fl_studio_mcp.utils import journal


@pytest.fixture
def wired(fl_env):
    """A real MIDIConnection against the in-process controller, so the hook is live."""
    from fl_studio_mcp.utils.midi_connection import MIDIConnection

    conn = MIDIConnection()
    conn._command_file = fl_env.command_file
    conn._response_file = fl_env.response_file
    conn._port = fl_env.midi_port
    conn._connected = True
    return conn


def entries() -> list[dict]:
    return journal.read_entries()["entries"]


def test_a_mutating_command_is_recorded(wired):
    wired.send_command("mixer.setTrackVolume", {"track": 1, "volume": 0.5})
    recorded = entries()
    assert len(recorded) == 1
    entry = recorded[0]
    assert entry["action"] == "mixer.setTrackVolume"
    assert entry["params"] == {"track": 1, "volume": 0.5}
    assert entry["ok"] is True
    assert entry["error"] is None
    assert entry["duration_ms"] >= 0
    assert datetime.fromisoformat(entry["ts"]), "the timestamp must be readable"


def test_a_read_is_not_recorded(wired):
    """A log of questions would bury the edits, which are the point."""
    wired.send_command("mixer.getSnapshot", {})
    wired.send_command("transport.getStatus", {})
    assert entries() == []


def test_an_edit_that_failed_is_recorded_with_its_error(wired):
    """What the server tried matters as much as what it managed."""
    wired.send_command("mixer.setTrackVolume", {"volume": 0.5})
    entry = entries()[0]
    assert entry["ok"] is False
    assert "track" in entry["error"]


def test_a_batch_names_every_command_it_carried(wired):
    """A batched edit must not be invisible behind its wrapper."""
    commands = [
        {"action": "mixer.setTrackVolume", "params": {"track": 1, "volume": 0.7}},
        {"action": "mixer.setTrackPan", "params": {"track": 1, "pan": 0.1}},
    ]
    wired.send_command("system.batch", {"commands": commands, "name": "MCP: test"})
    entry = entries()[0]
    assert entry["action"] == "system.batch"
    assert entry["commands"] == ["mixer.setTrackVolume", "mixer.setTrackPan"]
    assert entry["name"] == "MCP: test"


def test_a_journal_that_cannot_be_written_does_not_break_the_command(wired, monkeypatch):
    """The most important behaviour here.

    Losing a log line is acceptable. Losing a fader move because the log failed is
    not, and a read-only disk is the ordinary way this happens.
    """

    def refuse(*args, **kwargs):
        raise OSError("read-only file system")

    monkeypatch.setattr(journal, "journal_path", refuse)
    result = wired.send_command("mixer.setTrackVolume", {"track": 1, "volume": 0.5})
    assert result.get("success") is True, "the command must still have run"
    assert journal.last_error() and "read-only" in journal.last_error()


def test_recording_never_raises_on_unserialisable_parameters():
    """Parameters come from tool calls, and a defensive writer beats a traceback."""
    before = journal.error_summary()["count"]
    journal.record("mixer.setTrackVolume", {"odd": {1, 2, 3}}, {"success": True}, 1.0)
    assert journal.error_summary()["count"] == before, "nothing failed to be written"
    assert len(entries()) == 1, "the entry was still written"


def test_journaling_can_be_switched_off(wired, monkeypatch):
    monkeypatch.setenv(journal.JOURNAL_ENV, "0")
    assert journal.is_enabled() is False
    wired.send_command("mixer.setTrackVolume", {"track": 1, "volume": 0.5})
    assert entries() == []


def test_one_session_id_covers_one_process(wired):
    """So a caller can ask what this session did, not what every session did."""
    wired.send_command("mixer.setTrackVolume", {"track": 1, "volume": 0.5})
    wired.send_command("mixer.setTrackVolume", {"track": 2, "volume": 0.5})
    sessions = {entry["session"] for entry in entries()}
    assert len(sessions) == 1
    assert sessions == {journal.session_id()}


def test_a_piano_roll_write_is_recorded(piano_roll_wired):
    """The other edit path. Notes are edits, and the journal has to say so."""
    from fl_studio_mcp.tools import piano_roll

    piano_roll.send_request(
        {"action": "add_notes", "notes": [{"midi": 60, "time": 0, "duration": 96}]},
        channel=0,
    )
    recorded = entries()
    assert recorded, "a note write is an edit"
    assert recorded[0]["action"] == "piano_roll.add_notes"
    assert recorded[0]["ok"] is True


def test_a_piano_roll_read_is_not_recorded(piano_roll_wired):
    """Reading the notes is not an edit, though targeting the channel is one.

    Asking for a channel's piano roll to be read selects that channel first, and
    selecting a channel is in the controller's own mutating list, so it is recorded.
    What must not appear is a request that changed notes.
    """
    from fl_studio_mcp.tools import piano_roll

    piano_roll.send_request({"action": "get_state"}, channel=0)
    assert [entry for entry in entries() if entry["action"].startswith("piano_roll.")] == []


def test_huge_parameters_are_truncated_rather_than_dropped():
    """A snapshot command carries a whole project, and a log line is not a database."""
    giant = {"data": "x" * 5000, "track": 3}
    journal.record("mixer.setTrackVolume", giant, {"success": True}, 1.0)
    entry = entries()[0]
    assert entry["params"]["_truncated"] is True
    assert entry["params"]["_keys"] == ["data", "track"]
    assert entry["params"]["_chars"] > journal.MAX_PARAM_CHARS


def test_entries_can_be_filtered_by_action(wired):
    wired.send_command("mixer.setTrackVolume", {"track": 1, "volume": 0.5})
    wired.send_command("channels.setChannelName", {"index": 0, "name": "Kick"})
    only_mixer = journal.read_entries(action="mixer.setTrackVolume")["entries"]
    assert [entry["action"] for entry in only_mixer] == ["mixer.setTrackVolume"]


def test_an_action_filter_can_name_a_whole_namespace(wired):
    """'mixer.' asks what the mixer was asked to do, which is the useful question."""
    wired.send_command("mixer.setTrackVolume", {"track": 1, "volume": 0.5})
    wired.send_command("channels.setChannelName", {"index": 0, "name": "Kick"})
    filtered = journal.read_entries(action="mixer.")["entries"]
    assert [entry["action"] for entry in filtered] == ["mixer.setTrackVolume"]


def test_entries_can_be_filtered_by_time(wired):
    wired.send_command("mixer.setTrackVolume", {"track": 1, "volume": 0.5})
    future = datetime.now(timezone.utc) + timedelta(minutes=1)
    assert journal.read_entries(since=future)["entries"] == []
    past = datetime.now(timezone.utc) - timedelta(minutes=1)
    assert len(journal.read_entries(since=past)["entries"]) == 1


def test_the_reading_is_capped_and_says_so(wired):
    for index in range(5):
        wired.send_command("mixer.setTrackVolume", {"track": index, "volume": 0.5})
    listing = journal.read_entries(limit=2)
    assert len(listing["entries"]) == 2
    assert listing["total"] == 5
    assert listing["truncated"] is True


def test_entries_read_newest_first(wired):
    wired.send_command("mixer.setTrackVolume", {"track": 1, "volume": 0.1})
    wired.send_command("mixer.setTrackVolume", {"track": 2, "volume": 0.2})
    assert [entry["params"]["track"] for entry in entries()] == [2, 1]


def test_a_corrupt_line_is_skipped_and_counted(wired):
    wired.send_command("mixer.setTrackVolume", {"track": 1, "volume": 0.5})
    path = journal.journal_path()
    path.write_text(path.read_text() + "{not json\n")
    listing = journal.read_entries()
    assert len(listing["entries"]) == 1
    assert listing["skipped_lines"] == 1


def test_a_summary_counts_actions_and_separates_failures(wired):
    wired.send_command("mixer.setTrackVolume", {"track": 1, "volume": 0.5})
    wired.send_command("mixer.setTrackVolume", {"track": 2, "volume": 0.5})
    wired.send_command("mixer.setTrackPan", {"pan": 0.1})
    summary = journal.summarise(entries())
    assert summary["count"] == 3
    assert summary["by_action"]["mixer.setTrackVolume"] == 2
    assert summary["by_namespace"]["mixer"] == 3
    assert summary["failures"] == 1
    assert summary["failed_actions"] == ["mixer.setTrackPan"]
    assert summary["first"] <= summary["last"]


def test_the_journal_lives_under_the_library(tmp_path, monkeypatch):
    monkeypatch.setenv("FL_STUDIO_MCP_HOME", str(tmp_path / "lib"))
    journal.record("mixer.setTrackVolume", {}, {"success": True}, 1.0)
    assert journal.journal_path().parent.parent == tmp_path / "lib"
    assert journal.journal_path().name.endswith(".jsonl")


def test_no_journal_file_is_created_for_a_read(wired):
    """A library directory that appears just because someone asked a question is rude."""
    wired.send_command("mixer.getSnapshot", {})
    assert not journal.journal_path().exists()


def test_a_line_is_valid_json_on_its_own(wired):
    """JSONL, so a tail of the file is readable without parsing the whole thing."""
    wired.send_command("mixer.setTrackVolume", {"track": 1, "volume": 0.5})
    lines = journal.journal_path().read_text().strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["action"] == "mixer.setTrackVolume"


def test_the_journal_is_never_written_to_a_real_home(wired):
    """The suite records edits, and none of them may land in the user's journal.

    An autouse fixture moves the library root, so this is not a polite request that
    a future test could forget to make: it is what the suite does for every test.
    """
    wired.send_command("mixer.setTrackVolume", {"track": 1, "volume": 0.5})
    assert journal.journal_path().is_file()
    assert Path.home() not in journal.journal_path().parents
