"""Shared fixtures.

Three things every FL-side test needs: a settings tree that already exists,
because the controller is not allowed to create one (FL's sandbox blocks mkdir),
a `sys.modules` that is restored afterwards, because the scripts are loaded under
fixed names and would otherwise leak between tests, and a fake FL to load them
against.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from tests import fakes
from tests.fakes.midi import FakeMidiModule, FakeMidiPort
from tests.fakes.project import FakeProject
from tests.helpers import load_controller, load_pyscript

# The controller's own trigger note. Kept here rather than imported from the
# script under test, so the fake cable cannot agree with a broken constant.
TRIGGER_NOTE = 127


class Harness:
    """Everything a test needs to drive the real scripts against a fake FL."""

    def __init__(self, project, modules, settings, controller, pyscript):
        self.project = project
        self.modules = modules
        self.settings = settings
        self.controller = controller
        self.pyscript = pyscript
        self.trigger_count = 0

    @property
    def hardware_dir(self) -> Path:
        return self.settings / "Hardware" / "FLStudioMCP"

    @property
    def piano_roll_dir(self) -> Path:
        return self.settings / "Piano roll scripts"

    @property
    def command_file(self) -> Path:
        return self.hardware_dir / "mcp_command.json"

    @property
    def response_file(self) -> Path:
        return self.hardware_dir / "mcp_response.json"

    @property
    def request_file(self) -> Path:
        return self.piano_roll_dir / "mcp_request.json"

    @property
    def piano_roll_response_file(self) -> Path:
        return self.piano_roll_dir / "mcp_response.json"

    @property
    def state_file(self) -> Path:
        return self.piano_roll_dir / "piano_roll_state.json"


@pytest.fixture(autouse=True)
def _restore_sys_modules():
    """Undo every sys.modules change a test makes.

    monkeypatch restores the keys it touched, but the scripts are also written
    under their fixed names directly, and a fake left behind would silently be
    used by the next test.
    """
    before = dict(sys.modules)
    try:
        yield
    finally:
        for name in list(sys.modules):
            if name not in before:
                del sys.modules[name]
        sys.modules.update(before)


@pytest.fixture
def fl_settings(tmp_path, monkeypatch):
    """A settings tree that exists, with the override pointing at it.

    The directories are created here rather than by the code under test, because
    the controller cannot create them inside FL. The server owns that job, via
    fl_studio_mcp.utils.paths.
    """
    settings = tmp_path / "settings"
    (settings / "Hardware" / "FLStudioMCP").mkdir(parents=True, exist_ok=True)
    (settings / "Piano roll scripts").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("FL_STUDIO_MCP_SETTINGS_DIR", str(settings))
    return settings


@pytest.fixture
def controller(fl_settings, monkeypatch):
    """The real controller script, loaded against whatever fakes are installed."""
    return load_controller(monkeypatch)


@pytest.fixture
def pyscript(fl_settings, monkeypatch):
    """The real piano roll script, loaded against whatever fakes are installed."""
    return load_pyscript(monkeypatch)


def make_project() -> FakeProject:
    """A small but complete project: channels, mixer tracks and playlist tracks.

    Built in one place so every test starts from the same shape and a test that
    wants something different says so explicitly.
    """
    project = FakeProject.with_channels(4)
    project.tracks = FakeProject.with_tracks(8).tracks
    project.playlist_tracks = [(f"Track {i + 1}", 0x808080, False, False) for i in range(4)]
    project.patterns = [FakeProject().patterns[0]]
    project.notes_by_pattern = {0: []}
    return project


@pytest.fixture
def fl_env(fl_settings, monkeypatch):
    """A fake FL, the two real scripts, a fake MIDI cable, and a temp settings tree."""
    project = make_project()
    modules = fakes.install(project)
    # The fakes are passed explicitly: load_controller installs empty stand-ins
    # for any module the caller does not supply, and those would shadow the fakes
    # that were just installed, leaving the script talking to blank modules.
    controller = load_controller(monkeypatch, modules)
    pyscript = load_pyscript(monkeypatch, modules)
    harness = Harness(
        project=project,
        modules=modules,
        settings=fl_settings,
        controller=controller,
        pyscript=pyscript,
    )

    def on_send(message) -> None:
        """Deliver a trigger note to the controller, the way FL would.

        This is the whole of the fake transport. Everything else in the round
        trip is the real code reading and writing the real files.
        """
        if getattr(message, "type", None) == "note_on" and message.note == TRIGGER_NOTE:
            harness.trigger_count += 1
            harness.controller.execute_pending_command()

    harness.midi_port = FakeMidiPort("FL Studio MCP", on_send)
    monkeypatch.setitem(sys.modules, "mido", FakeMidiModule(harness.midi_port))
    try:
        yield harness
    finally:
        fakes.uninstall()


@pytest.fixture
def piano_roll_wired(fl_env, monkeypatch):
    """The piano roll tools driving the in-process controller.

    Every tool that writes notes needs the same four things wired: a connection
    bound to the harness files, the scripts directory pointed at the harness, a
    trigger that runs the script in process, and the musical context going through
    the same path. Doing that per test file was four lines of setup repeated, and
    one test file had it subtly wrong.
    """
    from fl_studio_mcp.tools import piano_roll
    from fl_studio_mcp.tools import score as score_tool
    from fl_studio_mcp.utils.midi_connection import MIDIConnection

    conn = MIDIConnection()
    conn._command_file = fl_env.command_file
    conn._response_file = fl_env.response_file
    conn._port = fl_env.midi_port
    conn._port_name = fl_env.midi_port.name
    conn._connected = True

    monkeypatch.setattr(piano_roll, "get_connection", lambda: conn, raising=False)
    monkeypatch.setattr(piano_roll, "piano_roll_scripts_dir", lambda: fl_env.piano_roll_dir)
    monkeypatch.setattr(score_tool, "get_connection", lambda: conn, raising=False)

    def fake_trigger(delay: float = 0.0) -> bool:
        fl_env.pyscript.apply()
        return True

    monkeypatch.setattr(piano_roll, "trigger_fl_studio", fake_trigger)
    fl_env.connection = conn
    return fl_env
