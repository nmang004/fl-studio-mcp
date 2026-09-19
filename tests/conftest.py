"""Shared fixtures.

Two things every FL-side test needs: a settings tree that already exists, because
the controller is not allowed to create one (FL's sandbox blocks mkdir), and a
`sys.modules` that is restored afterwards, because the scripts are loaded under
fixed names and would otherwise leak between tests.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from tests.helpers import CONTROLLER_PATH, PYSCRIPT_PATH, load_controller, load_pyscript


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


@pytest.fixture
def controller_path() -> Path:
    return CONTROLLER_PATH


@pytest.fixture
def pyscript_path() -> Path:
    return PYSCRIPT_PATH
