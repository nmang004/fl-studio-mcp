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
from tests.fakes.project import FakeProject
from tests.helpers import load_controller, load_pyscript


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
    """A fake FL, the two real scripts, and a temporary settings tree."""
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
    try:
        yield harness
    finally:
        fakes.uninstall()
