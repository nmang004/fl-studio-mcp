"""One call, not twenty.

The value of this tool is the round trips it saves, so the test counts them. A
version that asked the controller once per channel would be a worse prompt than
asking the model to make twenty calls, because it would look like one call.
"""

from __future__ import annotations

import pytest

from fl_studio_mcp.tools import describe


class CountingConnection:
    """Records every command and answers from the fake controller."""

    def __init__(self, fl_env):
        self.env = fl_env
        self.commands = []

    def send_command(self, action, params=None, timeout=2.0):
        self.commands.append(action)
        if action == "system.batch":
            results = [
                self.env.controller.dispatch_command(entry["action"], entry.get("params", {}))
                for entry in params["commands"]
            ]
            return {"success": True, "results": results, "executed": len(results),
                    "failed": 0, "undo_name": params.get("name")}
        return self.env.controller.dispatch_command(action, params or {})


@pytest.fixture
def wired(fl_env, monkeypatch):
    connection = CountingConnection(fl_env)
    monkeypatch.setattr(describe, "get_connection", lambda: connection)
    return fl_env, connection


def test_describing_a_project_takes_one_round_trip(wired):
    """The whole point. More than a handful and it is not one call."""
    fl_env, connection = wired
    describe.describe_project()
    assert len(connection.commands) == 1, connection.commands


def test_the_description_reports_the_tempo(wired):
    fl_env, _ = wired
    described = describe.describe_project()
    assert described["summary"]["tempo_bpm"] == pytest.approx(130.0)


def test_the_description_reports_the_patterns(wired):
    fl_env, _ = wired
    fl_env.project.pattern(0).name = "Verse"
    described = describe.describe_project()
    assert described["summary"]["pattern_count"] == 1
    assert described["summary"]["pattern_names"] == ["Verse"]


def test_the_description_reports_the_channels(wired):
    fl_env, _ = wired
    described = describe.describe_project()
    assert described["summary"]["channel_count"] == 4
    assert "Channel 1" in described["summary"]["channel_names"]


def test_the_description_reports_the_mixer(wired):
    fl_env, _ = wired
    described = describe.describe_project()
    assert described["summary"]["mixer_track_count"] >= 1


def test_the_description_reports_the_versions(wired):
    """fl_version is ui.getVersion, which on live FL reads "Producer Edition
    v26.1.6 [build 5406]". The program title is a different string."""
    fl_env, _ = wired
    summary = describe.describe_project()["summary"]
    assert summary["fl_version"] == "Producer Edition v26.1.6 [build 5406]"
    assert summary["api_version"] == 45


def test_a_failed_batch_is_reported_rather_than_summarised(wired, monkeypatch):
    fl_env, connection = wired

    def failing(action, params=None, timeout=2.0):
        return {"success": False, "error": "FL said no", "results": []}

    monkeypatch.setattr(connection, "send_command", failing)
    described = describe.describe_project()
    assert described["success"] is False
    assert "FL said no" in described["error"]


def test_the_raw_replies_are_included(wired):
    """A summary that hides the detail forces the second call this tool exists to save."""
    fl_env, _ = wired
    described = describe.describe_project()
    for key in ("patterns", "channels", "tracks", "tempo"):
        assert key in described
