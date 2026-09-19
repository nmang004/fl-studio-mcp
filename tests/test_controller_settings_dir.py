"""The controller script must honour the same settings override as the server.

FL's embedded Python cannot import the server package, so the controller carries
its own copy of the resolution logic. If the two ever disagree, the server writes
a command file the controller never reads, and the only symptom is a timeout.
"""

from __future__ import annotations

from pathlib import Path

from tests.helpers import load_controller


def test_controller_honours_the_settings_override(monkeypatch, tmp_path):
    settings = tmp_path / "settings"
    monkeypatch.setenv("FL_STUDIO_MCP_SETTINGS_DIR", str(settings))
    module = load_controller(monkeypatch)
    assert module.COMMAND_FILE == settings / "Hardware" / "FLStudioMCP" / "mcp_command.json"
    assert module.RESPONSE_FILE == settings / "Hardware" / "FLStudioMCP" / "mcp_response.json"


def test_controller_matches_the_server_resolver(monkeypatch, tmp_path):
    from fl_studio_mcp.utils.paths import hardware_dir

    settings = tmp_path / "settings"
    monkeypatch.setenv("FL_STUDIO_MCP_SETTINGS_DIR", str(settings))
    module = load_controller(monkeypatch)
    assert module.COMMAND_FILE.parent == hardware_dir()


def test_controller_creates_its_own_directory(monkeypatch, tmp_path):
    """It has to, because nothing else may have run on a fresh machine."""
    settings = tmp_path / "fresh"
    monkeypatch.setenv("FL_STUDIO_MCP_SETTINGS_DIR", str(settings))
    module = load_controller(monkeypatch)
    assert module.COMMAND_FILE.parent.is_dir()


def test_default_settings_path_is_used_without_the_override(monkeypatch):
    monkeypatch.delenv("FL_STUDIO_MCP_SETTINGS_DIR", raising=False)
    module = load_controller(monkeypatch)
    expected = Path.home() / "Documents" / "Image-Line" / "FL Studio" / "Settings"
    assert module.COMMAND_FILE.parent == expected / "Hardware" / "FLStudioMCP"
