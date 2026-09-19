"""The tool output must say where the notes went.

A report that omits the channel cannot be checked by the model reading it, and the
old behaviour, notes in an unknown piano roll reported as success, is exactly what
this phase exists to remove. The tool surface is a prompt, so this is part of the
feature rather than decoration.
"""

from __future__ import annotations

import asyncio
import inspect

import pytest

from fl_studio_mcp.server import mcp
from fl_studio_mcp.tools import piano_roll

TOOLS = (
    "fl_send_notes",
    "fl_send_chord",
    "fl_delete_notes",
    "fl_clear_piano_roll",
    "fl_get_piano_roll_state",
)


def _tool(name: str):
    """The registered tool function, fetched from the MCP server itself.

    The piano roll tools are closures defined inside register_piano_roll_tools, so
    they are not module attributes. Asking the server for its own registry is the
    only way to inspect what a client would actually be offered.
    """
    tools = asyncio.run(mcp._list_tools())
    for tool in tools:
        if tool.name == name:
            fn = getattr(tool, "fn", None)
            assert fn is not None, f"{name} has no underlying function to inspect"
            return fn
    raise AssertionError(f"{name} is not registered on the server")


@pytest.mark.parametrize("name", TOOLS)
def test_every_tool_takes_a_channel(name):
    """The surface itself has to offer it, or the model cannot use it."""
    assert "channel" in inspect.signature(_tool(name)).parameters, (
        f"{name} has no channel parameter"
    )


@pytest.mark.parametrize("name", TOOLS)
def test_every_docstring_mentions_the_channel(name):
    """A docstring the model reads is how the argument gets used at all."""
    assert "channel" in (_tool(name).__doc__ or ""), f"{name}'s docstring omits it"


def test_the_unknown_target_warning_is_specific():
    """A result with no channel has to say so, not stay silent about it."""
    note = piano_roll._target_note({})
    assert "no channel" in note.lower()
    assert "focus" in note.lower()


def test_the_target_note_names_the_channel_and_its_name():
    note = piano_roll._target_note({"target_channel": 2, "target_channel_name": "808 HiHat"})
    assert "2" in note
    assert "808 HiHat" in note


def test_the_tools_mention_the_channel_in_their_result(fl_env, monkeypatch):
    """End to end: the string a caller reads says where the notes went."""
    conn_modules = __import__(
        "fl_studio_mcp.utils.midi_connection", fromlist=["MIDIConnection"]
    )
    conn = conn_modules.MIDIConnection()
    conn._command_file = fl_env.command_file
    conn._response_file = fl_env.response_file
    conn._port = fl_env.midi_port
    conn._connected = True

    monkeypatch.setattr(piano_roll, "get_connection", lambda: conn, raising=False)
    monkeypatch.setattr(piano_roll, "piano_roll_scripts_dir", lambda: fl_env.piano_roll_dir)
    monkeypatch.setattr(
        piano_roll, "trigger_fl_studio", lambda delay=0: (fl_env.pyscript.apply(), True)[1]
    )

    result = piano_roll.send_request({"action": "clear"}, timeout=1.0, channel=2)
    assert piano_roll._target_note(result) == " Channel 2 (Channel 3)."
