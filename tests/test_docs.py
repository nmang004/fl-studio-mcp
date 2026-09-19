"""Documentation that has to stay true to the code."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SMOKE_TEST = REPO_ROOT / "docs" / "SMOKE_TEST.md"


def test_smoke_test_exists():
    assert SMOKE_TEST.is_file(), "CI cannot cover the FL side, so this file is required"


def test_smoke_test_names_both_scripts_that_must_be_copied():
    text = SMOKE_TEST.read_text()
    assert "device_FLStudioMCP.py" in text
    assert "ComposeWithLLM.pyscript" in text


def test_smoke_test_covers_both_platforms():
    text = SMOKE_TEST.read_text()
    assert "macOS" in text
    assert "Windows" in text
    assert "loopMIDI" in text, "the Windows virtual MIDI limit must stay recorded"


def test_smoke_test_points_at_the_live_check():
    assert "dev_verify_connection.py" in SMOKE_TEST.read_text()


def test_smoke_test_is_a_checklist_not_prose():
    """Checkboxes are what make an item skippable-on-purpose rather than forgotten."""
    assert SMOKE_TEST.read_text().count("- [ ]") >= 15


def test_smoke_test_covers_the_piano_roll_path():
    text = SMOKE_TEST.read_text()
    assert "fl_send_notes" in text
    assert "Accessibility" in text, "the permission requirement is the usual failure"


def test_readme_no_longer_tells_macos_users_to_enable_the_iac_driver():
    """The server creates its own virtual port, so that step is gone on macOS."""
    text = (REPO_ROOT / "README.md").read_text()
    assert "IAC Driver enabled in Audio MIDI Setup" not in text


def test_readme_keeps_the_loopmidi_instructions_for_windows():
    """Windows has no virtual MIDI API, so that path must stay documented."""
    text = (REPO_ROOT / "README.md").read_text().lower()
    assert "loopmidi" in text


def test_the_server_does_not_tell_clients_to_enable_the_iac_driver():
    """These strings reach every MCP client, so they must not contradict the README."""
    text = (REPO_ROOT / "src" / "fl_studio_mcp" / "server.py").read_text()
    assert "IAC Driver enabled in Audio MIDI Setup" not in text


def test_the_server_does_not_claim_patterns_cannot_be_created():
    text = (REPO_ROOT / "src" / "fl_studio_mcp" / "server.py").read_text()
    assert "Cannot create new patterns programmatically" not in text


def test_the_server_does_not_advertise_a_tempo_write():
    """Reading tempo works; writing it is an open spike with no tool."""
    text = (REPO_ROOT / "src" / "fl_studio_mcp" / "server.py").read_text()
    assert "record, tempo, position control" not in text
    assert "no tempo write tool exists yet" in text


def test_the_server_keeps_the_real_limits_in_front_of_the_model():
    text = (REPO_ROOT / "src" / "fl_studio_mcp" / "server.py").read_text()
    assert "Cannot load new VST or AU plugins" in text
    assert "Cannot place clips in the playlist" in text
    assert "Cannot render or export audio" in text
