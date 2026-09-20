"""The browser reads and the audition, against a fake FL.

The browser is the part of the API that cannot be searched, cannot be made to select a
file, and cannot be stopped once a preview starts. FL previews whatever the producer
has highlighted, so these tests pin what the tools claim about that. A tool that
implied it chose a file would be lying about the only thing the API actually does.

The two new browser readers are installed onto the fake ui module by the `browser`
fixture. The controller reads them through getattr, which is why a fake that does not
carry them is reported as an unknown field rather than breaking the state read.
"""

from __future__ import annotations

import asyncio

import pytest
from fastmcp import FastMCP

from fl_studio_mcp.tools import project as project_tools
from fl_studio_mcp.utils import actions


@pytest.fixture
def wired(fl_env, monkeypatch):
    """The browser tools wired to the in-process controller.

    project holds its own get_connection reference, so it is patched on that module
    rather than on utils.connection. Patching the shared helper would leave the tool
    building a real MIDI connection and reaching for actual hardware.
    """
    from fl_studio_mcp.utils.midi_connection import MIDIConnection

    conn = MIDIConnection()
    conn._command_file = fl_env.command_file
    conn._response_file = fl_env.response_file
    conn._port = fl_env.midi_port
    conn._connected = True
    monkeypatch.setattr(project_tools, "get_connection", lambda: conn, raising=False)
    fl_env.connection = conn
    return fl_env


@pytest.fixture
def browser(fl_env, monkeypatch):
    """The browser readers the fake ui module does not carry yet.

    getFocusedNodeCaption is on the fake already. getFocusedNodeFileType and
    isBrowserAutoHide are not, so they are installed here, reading the values a test
    sets on the project, which is how the fake's own readers work.
    """
    fl_env.project.focused_node_file_type = 0
    fl_env.project.browser_auto_hide = False
    ui = fl_env.modules["ui"]
    monkeypatch.setattr(
        ui,
        "getFocusedNodeFileType",
        lambda: fl_env.project.focused_node_file_type,
        raising=False,
    )
    monkeypatch.setattr(
        ui, "isBrowserAutoHide", lambda: fl_env.project.browser_auto_hide, raising=False
    )
    return fl_env


# --- what the browser has highlighted ------------------------------------------


def test_the_browser_block_reports_the_focused_node(wired, browser):
    wired.project.focused_node_caption = "Kick 01.wav"
    wired.project.focused_node_file_type = 2049
    wired.project.browser_auto_hide = True

    result = project_tools.get_ui_state()

    assert result["success"] is True
    block = result["browser"]
    assert block["caption"] == "Kick 01.wav"
    assert block["file_type"] == 2049
    assert block["auto_hide"] is True
    assert block["problems"] == []


def test_nothing_focused_is_null_not_an_empty_string(wired, browser):
    """FL answers an empty caption when nothing is selected, and that is an absence.

    A file with an empty name and no selection at all would both be an empty string,
    so the empty answer becomes null and the caller can tell them apart.
    """
    wired.project.focused_node_caption = ""

    result = project_tools.get_ui_state()

    assert result["browser"]["caption"] is None


def test_a_read_that_raises_does_not_lose_the_other_fields(wired, browser, monkeypatch):
    """One failing browser call costs its own field, not the whole block."""
    wired.project.focused_node_caption = "Bass Loop.wav"
    wired.project.browser_auto_hide = True

    def explode() -> int:
        raise RuntimeError("no file type on this build")

    monkeypatch.setattr(wired.modules["ui"], "getFocusedNodeFileType", explode)

    result = project_tools.get_ui_state()

    block = result["browser"]
    assert block["caption"] == "Bass Loop.wav"
    assert block["auto_hide"] is True
    assert block["file_type"] is None
    assert any(
        "getFocusedNodeFileType" in problem and "no file type on this build" in problem
        for problem in block["problems"]
    )


def test_a_reader_this_fl_does_not_carry_is_reported(wired, browser, monkeypatch):
    """An older ui module without the function leaves a reason, not an AttributeError."""
    monkeypatch.delattr(wired.modules["ui"], "isBrowserAutoHide")

    result = project_tools.get_ui_state()

    block = result["browser"]
    assert block["caption"] is None
    assert block["file_type"] == 0
    assert block["auto_hide"] is None
    assert any("isBrowserAutoHide" in problem for problem in block["problems"])


# --- audition ------------------------------------------------------------------


def test_audition_reports_the_caption_it_was_pointed_at(wired, browser):
    wired.project.focused_node_caption = "Kick 01.wav"

    result = project_tools.audition_sample()

    assert result["success"] is True
    assert result["previewed"] is True
    assert result["caption"] == "Kick 01.wav"
    assert "Kick 01.wav" in result["message"]
    assert ("previewBrowserMenuItem",) in wired.project.browser_calls


def test_audition_says_it_cannot_choose_the_file(wired, browser):
    """The reply must not imply the tool picked what played."""
    wired.project.focused_node_caption = "Snare 03.wav"

    result = project_tools.audition_sample()

    message = result["message"].lower()
    assert "highlighted" in message
    assert "cannot choose" in message
    assert "stop" in message


def test_audition_refuses_when_nothing_is_highlighted(wired, browser):
    wired.project.focused_node_caption = ""

    result = project_tools.audition_sample()

    assert result["success"] is False
    assert result["previewed"] is False
    assert result["caption"] is None
    assert "highlight" in result["error"].lower()
    assert wired.project.browser_calls == [], "nothing must be played on a refusal"


def test_audition_refuses_when_the_caption_cannot_be_read(wired, browser, monkeypatch):
    """Without the caption there is no honest answer to what was played, so nothing plays."""

    def explode() -> str:
        raise RuntimeError("the browser is not answering")

    monkeypatch.setattr(wired.modules["ui"], "getFocusedNodeCaption", explode)

    result = project_tools.audition_sample()

    assert result["success"] is False
    assert result["previewed"] is False
    assert "the browser is not answering" in result["error"]
    assert wired.project.browser_calls == []


def test_a_preview_that_raises_is_a_reported_failure(wired, browser, monkeypatch):
    wired.project.focused_node_caption = "Kick 01.wav"

    def explode() -> None:
        raise RuntimeError("the browser is not there")

    monkeypatch.setattr(wired.modules["ui"], "previewBrowserMenuItem", explode)

    result = project_tools.audition_sample()

    assert result["success"] is False
    assert result["previewed"] is False
    assert result["caption"] == "Kick 01.wav"
    assert "the browser is not there" in result["error"]


def test_audition_sends_no_mutating_action(wired, browser, monkeypatch):
    """It plays audio and changes no project state, so it must not be gated as a write."""
    wired.project.focused_node_caption = "Kick 01.wav"
    sent: list[str] = []
    original = wired.connection.send_command

    def record(command, params=None, **kwargs):
        sent.append(command)
        return original(command, params, **kwargs)

    monkeypatch.setattr(wired.connection, "send_command", record)

    def project_state():
        return (
            len(wired.project.undo_stack),
            [track.volume for track in wired.project.tracks],
            [track.name for track in wired.project.channels],
            list(wired.project.notes),
        )

    before = project_state()
    result = project_tools.audition_sample()

    assert result["success"] is True
    assert sent == ["ui.previewBrowser"]
    assert "ui.previewBrowser" not in actions.MUTATING_ACTIONS
    assert not any(actions.is_mutating(action) for action in sent)
    assert project_state() == before


def test_the_audition_tool_is_registered_by_name():
    """Registration is what makes the tool reachable; the name is what clients call."""
    mcp = FastMCP("test")
    project_tools.register_browser_tools(mcp)
    names = {tool.name for tool in asyncio.run(mcp._list_tools())}
    assert names == {"fl_audition_sample"}
