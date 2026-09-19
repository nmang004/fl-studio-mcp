"""Every command carries an id and every reply must match it.

Without correlation a reply is just "something FL finished", so an abandoned
command's answer can be consumed as the next command's answer. The original audit
could not reproduce the dramatic version of that story live, because FL answers in
about a millisecond, but the structural defect is real and two concurrent clients
reach it with no timeout at all.
"""

from __future__ import annotations

import json

import pytest

from fl_studio_mcp.utils.midi_connection import (
    NOT_READY,
    MIDIConnection,
    MIDIResponseReader,
)


@pytest.fixture
def connection(fl_env):
    """A MIDIConnection wired to the in-process controller."""
    conn = MIDIConnection()
    conn._command_file = fl_env.command_file
    conn._response_file = fl_env.response_file
    conn._port = fl_env.midi_port
    conn._port_name = fl_env.midi_port.name
    conn._connected = True
    return conn


def test_the_command_file_carries_an_id(connection, fl_env):
    connection.send_command("mixer.getTrackCount", timeout=2.0)
    written = json.loads(fl_env.command_file.read_text())
    assert written["id"], "the server sent a command with no id"


def test_the_reply_carries_the_same_id_back(connection):
    result = connection.send_command("mixer.getTrackCount", timeout=2.0)
    assert result["id"] == connection.last_request_id


def test_each_command_gets_a_distinct_id(connection):
    connection.send_command("mixer.getTrackCount", timeout=2.0)
    first = connection.last_request_id
    connection.send_command("mixer.getTrackCount", timeout=2.0)
    assert connection.last_request_id != first


def test_a_reply_for_another_request_is_not_consumed(connection, fl_env):
    """A reply that belongs to something else must not answer this command."""
    fl_env.response_file.write_text(
        json.dumps({"success": True, "id": "not-mine", "count": 999}) + "\n"
    )
    # The reader itself parses it, so this is not a "not ready" case.
    assert MIDIResponseReader(fl_env.response_file).read() is not NOT_READY

    result = connection.send_command("mixer.getTrackCount", timeout=1.0)

    assert result["id"] == connection.last_request_id, "a foreign reply was consumed"
    assert result["count"] == 8, "the foreign reply's payload leaked into this answer"


def test_a_reply_with_no_id_is_still_accepted(connection, fl_env, monkeypatch):
    """A controller older than this change does not echo an id."""
    original = fl_env.controller.execute_pending_command

    def drop_the_id():
        original()
        payload = json.loads(fl_env.response_file.read_text())
        payload.pop("id", None)
        fl_env.response_file.write_text(json.dumps(payload) + "\n")

    monkeypatch.setattr(fl_env.controller, "execute_pending_command", drop_the_id)

    result = connection.send_command("mixer.getTrackCount", timeout=2.0)

    assert result["success"] is True
    assert result["count"] == 8


def test_the_connection_reports_the_id_it_used(connection):
    assert connection.last_request_id is None, "no command has been sent yet"
    connection.send_command("mixer.getTrackCount", timeout=2.0)
    assert isinstance(connection.last_request_id, str)
    assert connection.last_request_id
