"""The controller script must honour the same settings override as the server.

FL's embedded Python cannot import the server package, so the controller carries
its own copy of the resolution logic. If the two ever disagree, the server writes
a command file the controller never reads, and the only symptom is a timeout.
"""

from __future__ import annotations

from pathlib import Path

from tests.helpers import load_controller


def test_controller_honours_the_settings_override(fl_settings, monkeypatch):
    module = load_controller(monkeypatch)
    expected = fl_settings / "Hardware" / "FLStudioMCP"
    assert module.COMMAND_FILE == expected / "mcp_command.json"
    assert module.RESPONSE_FILE == expected / "mcp_response.json"


def test_controller_and_server_resolve_the_same_directory(fl_settings, monkeypatch):
    from fl_studio_mcp.utils.paths import hardware_dir

    module = load_controller(monkeypatch)
    assert module.COMMAND_FILE.parent == hardware_dir()


def test_the_controller_creates_nothing_on_import(fl_settings, monkeypatch):
    """FL's sandbox blocks mkdir, and a blocked call stops the module importing.

    The controller used to call SCRIPT_DIR.mkdir() at module scope, which broke
    the script inside FL: FL's loader cannot import a module whose body raised
    SystemError, and the symptom is exactly FL not running. The server owns
    directory creation, so the controller must leave a missing directory alone.
    """
    missing = fl_settings.parent / "does-not-exist"
    monkeypatch.setenv("FL_STUDIO_MCP_SETTINGS_DIR", str(missing))
    module = load_controller(monkeypatch)
    assert module.COMMAND_FILE.parent == missing / "Hardware" / "FLStudioMCP"
    assert not missing.exists(), "the controller created a directory; FL's sandbox blocks mkdir"


def test_default_settings_path_is_used_without_the_override(monkeypatch):
    monkeypatch.delenv("FL_STUDIO_MCP_SETTINGS_DIR", raising=False)
    module = load_controller(monkeypatch)
    expected = Path.home() / "Documents" / "Image-Line" / "FL Studio" / "Settings"
    assert module.COMMAND_FILE.parent == expected / "Hardware" / "FLStudioMCP"
