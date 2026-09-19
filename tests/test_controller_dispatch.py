"""Dispatch must report failure as failure, and must not call what is not there.

An unknown action used to be reported as `{"success": True, "error": ...}`, which
was reproduced against live FL Studio. A missing API function used to escape as a
generic exception, making an API gap look like a transport failure.
"""

from __future__ import annotations

import json

from tests.helpers import load_controller, module_with


def test_unknown_action_reports_an_error(monkeypatch, tmp_path):
    monkeypatch.setenv("FL_STUDIO_MCP_SETTINGS_DIR", str(tmp_path))
    controller = load_controller(monkeypatch)
    result = controller.dispatch_command("bogus.doesNotExist", {})
    assert "error" in result
    assert "bogus.doesNotExist" in result["error"]


def test_system_get_info_survives_a_missing_safe_to_edit(monkeypatch, tmp_path):
    """An older FL without API 29 must not make the whole info action fail."""
    monkeypatch.setenv("FL_STUDIO_MCP_SETTINGS_DIR", str(tmp_path))
    controller = load_controller(
        monkeypatch,
        {
            "general": module_with(getVersion=lambda: 21),  # no safeToEdit at all
            "mixer": module_with(getCurrentTempo=lambda: 130000),
            "ui": module_with(
                getVersion=lambda: "Producer Edition v21",
                getProgTitle=lambda: "FL Studio 21",
            ),
        },
    )
    info = controller.handle_system_get_info()
    assert info["api_version"] == 21
    assert info["capabilities"]["safeToEdit"] is None
    assert info["capabilities"]["getCurrentTempo"] == 130000


def test_system_get_info_reports_safe_to_edit_when_present(monkeypatch, tmp_path):
    monkeypatch.setenv("FL_STUDIO_MCP_SETTINGS_DIR", str(tmp_path))
    controller = load_controller(
        monkeypatch,
        {"general": module_with(getVersion=lambda: 45, safeToEdit=lambda: 1)},
    )
    assert controller.handle_system_get_info()["capabilities"]["safeToEdit"] is True


def _run_pending(controller, command: dict) -> dict:
    """Write a command file and let the controller execute it."""
    controller.COMMAND_FILE.write_text(json.dumps(command))
    controller.execute_pending_command()
    return json.loads(controller.RESPONSE_FILE.read_text())


def test_unknown_action_through_the_file_path_is_not_a_success(monkeypatch, tmp_path):
    """The exact live bug: success True sitting next to an error string."""
    monkeypatch.setenv("FL_STUDIO_MCP_SETTINGS_DIR", str(tmp_path))
    controller = load_controller(monkeypatch)
    response = _run_pending(controller, {"action": "bogus.doesNotExist", "params": {}})
    assert response["success"] is False
    assert response["error"]


def test_a_good_command_through_the_file_path_is_a_success(monkeypatch, tmp_path):
    monkeypatch.setenv("FL_STUDIO_MCP_SETTINGS_DIR", str(tmp_path))
    controller = load_controller(monkeypatch, {"mixer": module_with(trackCount=lambda: 7)})
    response = _run_pending(controller, {"action": "mixer.getTrackCount", "params": {}})
    assert response["success"] is True
    assert response["count"] == 7


def test_a_missing_command_file_reports_failure(monkeypatch, tmp_path):
    monkeypatch.setenv("FL_STUDIO_MCP_SETTINGS_DIR", str(tmp_path))
    controller = load_controller(monkeypatch)
    controller.execute_pending_command()
    response = json.loads(controller.RESPONSE_FILE.read_text())
    assert response["success"] is False
    assert "No command file" in response["error"]


def test_invalid_json_reports_failure(monkeypatch, tmp_path):
    monkeypatch.setenv("FL_STUDIO_MCP_SETTINGS_DIR", str(tmp_path))
    controller = load_controller(monkeypatch)
    controller.COMMAND_FILE.write_text("{not json")
    controller.execute_pending_command()
    response = json.loads(controller.RESPONSE_FILE.read_text())
    assert response["success"] is False


def test_a_handler_exception_reports_failure_not_a_crash(monkeypatch, tmp_path):
    def explode():
        raise RuntimeError("boom")

    monkeypatch.setenv("FL_STUDIO_MCP_SETTINGS_DIR", str(tmp_path))
    controller = load_controller(monkeypatch, {"mixer": module_with(trackCount=explode)})
    response = _run_pending(controller, {"action": "mixer.getTrackCount", "params": {}})
    assert response["success"] is False
    assert "boom" in response["error"]


def test_response_is_written_whole(monkeypatch, tmp_path):
    """The poller reads the file the instant it exists, so it must never be partial."""
    monkeypatch.setenv("FL_STUDIO_MCP_SETTINGS_DIR", str(tmp_path))
    controller = load_controller(monkeypatch, {"mixer": module_with(trackCount=lambda: 7)})
    _run_pending(controller, {"action": "mixer.getTrackCount", "params": {}})
    assert controller.RESPONSE_FILE.exists()
    assert not controller.RESPONSE_FILE.with_suffix(".json.tmp").exists()
