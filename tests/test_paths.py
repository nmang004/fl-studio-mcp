"""Settings directory resolution.

The override exists so tests, and users with a redirected Documents folder, can
point the server somewhere other than the hardcoded default. FL Studio's own
scripts must agree with this resolver or the two sides write to different files.
"""

from __future__ import annotations

from pathlib import Path

from fl_studio_mcp.utils import paths


def test_env_override_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("FL_STUDIO_MCP_SETTINGS_DIR", str(tmp_path / "settings"))
    assert paths.settings_dir() == tmp_path / "settings"


def test_hardware_dir_is_under_settings(monkeypatch, tmp_path):
    monkeypatch.setenv("FL_STUDIO_MCP_SETTINGS_DIR", str(tmp_path / "settings"))
    assert paths.hardware_dir() == tmp_path / "settings" / "Hardware" / "FLStudioMCP"


def test_piano_roll_scripts_dir_is_under_settings(monkeypatch, tmp_path):
    monkeypatch.setenv("FL_STUDIO_MCP_SETTINGS_DIR", str(tmp_path / "settings"))
    assert paths.piano_roll_scripts_dir() == tmp_path / "settings" / "Piano roll scripts"


def test_directories_are_created(monkeypatch, tmp_path):
    monkeypatch.setenv("FL_STUDIO_MCP_SETTINGS_DIR", str(tmp_path / "settings"))
    assert paths.hardware_dir().is_dir()
    assert paths.piano_roll_scripts_dir().is_dir()


def test_override_is_read_per_call_not_cached(monkeypatch, tmp_path):
    monkeypatch.setenv("FL_STUDIO_MCP_SETTINGS_DIR", str(tmp_path / "a"))
    assert paths.settings_dir() == tmp_path / "a"
    monkeypatch.setenv("FL_STUDIO_MCP_SETTINGS_DIR", str(tmp_path / "b"))
    assert paths.settings_dir() == tmp_path / "b"


def test_default_is_the_fl_studio_settings_folder(monkeypatch):
    monkeypatch.delenv("FL_STUDIO_MCP_SETTINGS_DIR", raising=False)
    expected = Path.home() / "Documents" / "Image-Line" / "FL Studio" / "Settings"
    onedrive = (
        Path.home() / "OneDrive" / "Documents" / "Image-Line" / "FL Studio" / "Settings"
    )
    if onedrive.is_dir():
        assert paths.settings_dir() in (expected, onedrive)
    else:
        assert paths.settings_dir() == expected
