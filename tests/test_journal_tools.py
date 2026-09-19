"""The journal tools read the host's files, and work with FL closed."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from fl_studio_mcp.tools import journal as journal_tool
from fl_studio_mcp.utils import journal


@pytest.fixture
def recorded(fl_env):
    """Six edits of four kinds, written the way the transport writes them."""
    from fl_studio_mcp.utils.midi_connection import MIDIConnection

    conn = MIDIConnection()
    conn._command_file = fl_env.command_file
    conn._response_file = fl_env.response_file
    conn._port = fl_env.midi_port
    conn._connected = True

    conn.send_command("mixer.setTrackVolume", {"track": 1, "volume": 0.5})
    conn.send_command("mixer.setTrackVolume", {"track": 2, "volume": 0.6})
    conn.send_command("channels.setName", {"index": 0, "name": "Kick"})
    conn.send_command("mixer.setTrackPan", {"pan": 0.1})  # refused: no track
    return fl_env


def test_the_journal_lists_entries_newest_first(recorded):
    result = journal_tool.read_journal()
    assert result["success"] is True
    assert result["total"] == 4
    assert result["entries"][0]["params"] == {"pan": 0.1}


def test_an_empty_journal_is_not_an_error(fl_env):
    """A fresh install has never edited anything, and that is a fine answer."""
    result = journal_tool.read_journal()
    assert result["success"] is True
    assert result["entries"] == []
    assert "message" in result


def test_entries_can_be_filtered_by_action(recorded):
    result = journal_tool.read_journal(action="mixer.setTrackVolume")
    assert result["total"] == 2
    assert {entry["action"] for entry in result["entries"]} == {"mixer.setTrackVolume"}


def test_a_namespace_filter_covers_the_whole_namespace(recorded):
    result = journal_tool.read_journal(action="mixer.")
    assert result["total"] == 3


def test_the_limit_is_reported_when_it_truncates(recorded):
    result = journal_tool.read_journal(limit=2)
    assert len(result["entries"]) == 2
    assert result["total"] == 4
    assert result["truncated"] is True


def test_an_absurd_limit_is_capped(recorded):
    result = journal_tool.read_journal(limit=10_000)
    assert result["limit"] == journal_tool.MAX_LIMIT


def test_a_window_of_time_can_be_asked_for(recorded):
    recent = journal_tool.read_journal(since="1h")
    assert recent["total"] == 4, "everything just happened"
    assert journal_tool.read_journal(since="1m")["total"] == 4


def test_a_time_in_the_future_returns_nothing(recorded):
    moment = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    assert journal_tool.read_journal(since=moment)["total"] == 0


def test_an_unreadable_window_is_refused_with_an_example(recorded):
    result = journal_tool.read_journal(since="last tuesday")
    assert result["success"] is False
    assert "30m" in result["error"], "the error shows the shape that works"


def test_an_iso_timestamp_is_accepted(recorded):
    moment = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    assert journal_tool.read_journal(since=moment)["total"] == 4


def test_a_summary_counts_actions_and_separates_failures(recorded):
    summary = journal_tool.summarise_journal()
    assert summary["success"] is True
    assert summary["count"] == 4
    assert summary["by_namespace"] == {"channels": 1, "mixer": 3}
    assert summary["failures"] == 1
    assert summary["failed_actions"] == ["mixer.setTrackPan"]


def test_the_tools_never_talk_to_fl_studio(recorded, monkeypatch):
    """The question is usually asked after something broke, so FL may be gone."""
    from fl_studio_mcp.utils import connection

    def refuse():
        raise AssertionError("the journal must not need FL Studio")

    monkeypatch.setattr(connection, "get_connection", refuse, raising=False)
    assert journal_tool.read_journal()["success"] is True
    assert journal_tool.summarise_journal()["success"] is True


def test_a_journal_write_failure_is_surfaced(recorded, monkeypatch):
    """An empty answer because logging broke must not read as nothing happened."""
    monkeypatch.setattr(
        journal, "journal_path", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full"))
    )
    journal.record("mixer.setTrackVolume", {}, {"success": True}, 1.0)
    result = journal_tool.read_journal()
    assert result["journal_write_failures"]["count"] >= 1
    assert "disk full" in result["journal_write_failures"]["last"]
