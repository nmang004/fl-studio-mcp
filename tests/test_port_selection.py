"""Tests for MIDI output port selection.

The important property is negative: the server must never pick a port it has no
reason to believe is wired to FL Studio. The upstream code fell back to the first
available port, which on a typical machine is real hardware, so the trigger note
went to the user's keyboard or audio interface.
"""

from __future__ import annotations

from fl_studio_mcp.utils.midi_connection import select_existing_port

REAL_HARDWARE = [
    "Scarlett 2i2 USB",
    "Arturia KeyLab Essential 49",
    "Bluetooth MIDI",
]


def test_returns_none_when_only_real_hardware_present():
    assert select_existing_port(REAL_HARDWARE, None) is None


def test_returns_none_when_no_ports_at_all():
    assert select_existing_port([], None) is None


def test_picks_iac_driver_on_macos():
    ports = [*REAL_HARDWARE, "IAC Driver Bus 1"]
    assert select_existing_port(ports, None) == "IAC Driver Bus 1"


def test_picks_loopmidi_on_windows():
    ports = [*REAL_HARDWARE, "loopMIDI Port"]
    assert select_existing_port(ports, None) == "loopMIDI Port"


def test_picks_our_own_virtual_port_if_already_open():
    ports = [*REAL_HARDWARE, "FL Studio MCP"]
    assert select_existing_port(ports, None) == "FL Studio MCP"


def test_preferred_port_matches_by_substring_case_insensitively():
    ports = [*REAL_HARDWARE, "IAC Driver Bus 2"]
    assert select_existing_port(ports, "bus 2") == "IAC Driver Bus 2"


def test_preferred_port_can_select_hardware_when_user_insists():
    # An explicit request is honoured. The safety rule is about defaults.
    assert select_existing_port(REAL_HARDWARE, "Scarlett") == "Scarlett 2i2 USB"


def test_preferred_port_that_does_not_exist_returns_none():
    # Must not silently fall through to some other port.
    assert select_existing_port(REAL_HARDWARE, "loopMIDI") is None
