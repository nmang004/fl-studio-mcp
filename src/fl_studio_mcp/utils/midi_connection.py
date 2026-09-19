"""MIDI-based connection to FL Studio.

This module provides communication with FL Studio via MIDI messages and JSON files.
The approach is:
1. Write command data to a JSON file
2. Send a MIDI trigger note to FL Studio
3. FL Studio's MIDI controller script executes the command
4. Read the response from a JSON file

This is similar to how the piano_roll module works, but uses MIDI for triggering
instead of keystrokes.
"""

from __future__ import annotations

import json
import os
import platform
import time
from pathlib import Path
from typing import Any

from fl_studio_mcp.utils.paths import hardware_dir

# Name of the virtual MIDI port the server creates for itself on platforms that
# support one. FL Studio sees this as an ordinary MIDI input device, so no IAC
# Driver (macOS) setup is needed.
VIRTUAL_PORT_NAME = "FL Studio MCP"

# Name of the virtual MIDI *input* port, used only by diagnostics that need to
# hear FL Studio talk back (research spike T4, SysEx transport). It is a separate
# port on purpose: FL Studio's MIDI Settings lists one entry per device name, so
# reusing the output name would make the two ports indistinguishable in the GUI.
VIRTUAL_INPUT_PORT_NAME = "FL Studio MCP Probe"

# Substrings identifying a virtual MIDI port that is plausibly wired to FL Studio.
# A port must match one of these to be used automatically. Never fall back to
# "first available port": on a typical machine that is real hardware, and the
# trigger note would be sent to the user's keyboard or audio interface.
KNOWN_PORT_HINTS = ("IAC", "LOOPMIDI", "FL STUDIO MCP")

# FL Studio does not bind to a virtual MIDI port the instant it appears. Measured
# on FL Studio 2026 / macOS 26: binding completed between 2.0 and 2.3 seconds
# after the port was created. Commands sent before that are silently dropped,
# which looks exactly like "FL Studio is not running".
#
# This is a one-time cost at server start. Phase 1 of ROADMAP.md replaces it with
# a ping handshake that polls until FL actually answers.
VIRTUAL_PORT_SETTLE_SECONDS = 3.0


def _supports_virtual_ports() -> bool:
    """Whether this platform can create a virtual MIDI port.

    CoreMIDI (macOS) and ALSA (Linux) both allow it. Windows has no native
    virtual MIDI API, so loopMIDI or similar is required there.
    """
    return platform.system() in ("Darwin", "Linux")


def select_existing_port(output_ports: list[str], preferred: str | None) -> str | None:
    """Pick an existing MIDI output port to use, or None if none is suitable.

    Args:
        output_ports: Port names as reported by mido.
        preferred: An exact or substring match requested by the user via the
            FL_STUDIO_MCP_MIDI_PORT environment variable.

    Returns:
        The chosen port name, or None if nothing suitable was found.
    """
    if preferred:
        for name in output_ports:
            if preferred.lower() in name.lower():
                return name
        return None

    for name in output_ports:
        upper = name.upper()
        if any(hint in upper for hint in KNOWN_PORT_HINTS):
            return name
    return None


def _get_fl_hardware_dir() -> Path:
    """Get the FL Studio Hardware scripts directory."""
    return hardware_dir()


class _NotReady:
    """Sentinel for "the response file is not finished yet"."""

    def __repr__(self) -> str:
        return "NOT_READY"


# Returned by MIDIResponseReader.read() while a response is still being written.
NOT_READY = _NotReady()


class MIDIResponseReader:
    """Reads a response file that may be caught mid write.

    FL Studio's embedded Python sandbox disables the rename syscalls: `os.replace`
    and `os.rename` both raise `SystemError: <built-in function replace> returned
    NULL without setting an exception` on FL Studio 2026, build 5406, which
    bundles CPython 3.12.1. The controller therefore cannot write a response
    atomically, and truncates and rewrites the file in place.

    The response format is one JSON object followed by a newline, so a complete
    response always ends with "}". A file that does not is either empty or still
    being written, which is a reason to keep waiting rather than an error. A
    response that is complete but wrong is a real error and is reported as one.
    """

    def __init__(self, path: Path) -> None:
        self._path = path

    def read(self) -> dict[str, Any] | _NotReady:
        """Read the response, or return NOT_READY if it is not complete yet.

        Returns:
            The parsed response, which always carries a "success" key, or
            NOT_READY when the file is missing, empty, or still being written.
        """
        try:
            text = self._path.read_text()
        except OSError:
            # Missing, or not readable yet.
            return NOT_READY

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            # Valid JSON always closes, and this does not parse, so if the text
            # ends with a brace it is malformed rather than unfinished. Anything
            # else, including an empty file, is a write still in flight.
            if text.strip().endswith("}"):
                return {"success": False, "error": f"Invalid JSON in response: {text.strip()}"}
            return NOT_READY

        if not isinstance(parsed, dict):
            return {
                "success": False,
                "error": f"Response was {type(parsed).__name__}, not an object",
            }
        if "success" not in parsed:
            return {
                "success": False,
                "error": f"Response had no success field: {parsed}",
            }
        return parsed


class MIDIConnection:
    """MIDI-based connection to FL Studio.

    Communicates with FL Studio via:
    - JSON files for command/response data
    - MIDI trigger note to execute commands
    """

    # MIDI trigger note (same as in FL Studio controller script)
    TRIGGER_NOTE = 127

    def __init__(self) -> None:
        self._port = None
        self._port_name: str | None = None
        self._is_virtual = False
        self._connected = False
        self._error: str | None = None

        # File paths for JSON communication
        self._hardware_dir = _get_fl_hardware_dir()
        self._command_file = self._hardware_dir / "mcp_command.json"
        self._response_file = self._hardware_dir / "mcp_response.json"

    @property
    def is_connected(self) -> bool:
        """Check if connected to FL Studio."""
        return self._connected and self._port is not None

    @property
    def connection_error(self) -> str | None:
        """Get the last connection error, if any."""
        return self._error

    def connect(self) -> bool:
        """Attempt to connect to FL Studio via MIDI.

        Returns True if connection successful, False otherwise.
        """
        if self._connected and self._port is not None:
            return True

        try:
            import mido
        except ImportError:
            self._error = (
                "mido library not installed. Install with: pip install mido python-rtmidi"
            )
            return False

        preferred = os.environ.get("FL_STUDIO_MCP_MIDI_PORT")

        try:
            output_ports = mido.get_output_names()
        except Exception as e:
            self._error = f"Failed to get MIDI ports: {e}"
            return False

        # Prefer an existing port the user has already wired up (IAC, loopMIDI,
        # or one named explicitly), so we do not duplicate a working setup.
        target_port = select_existing_port(output_ports, preferred)

        if target_port is not None:
            try:
                self._port = mido.open_output(target_port)
            except Exception as e:
                self._error = f"Failed to open MIDI port '{target_port}': {e}"
                return False
            self._port_name = target_port
            self._is_virtual = False
            self._connected = True
            self._error = None
            return True

        if preferred:
            self._error = (
                f"No MIDI output port matching '{preferred}' "
                f"(FL_STUDIO_MCP_MIDI_PORT). Available: {output_ports or 'none'}"
            )
            return False

        # Nothing suitable exists. On macOS and Linux we can create our own port,
        # which FL Studio then sees as a normal MIDI input device.
        if _supports_virtual_ports():
            # The port name is overridable so diagnostics can create a port with
            # a distinct name without disturbing the one the server owns.
            port_name = os.environ.get("FL_STUDIO_MCP_VIRTUAL_PORT_NAME", VIRTUAL_PORT_NAME)
            try:
                self._port = mido.open_output(port_name, virtual=True)
            except Exception as e:
                self._error = f"Failed to create virtual MIDI port: {e}"
                return False
            self._port_name = port_name
            self._is_virtual = True
            self._connected = True
            self._error = None

            settle = float(
                os.environ.get(
                    "FL_STUDIO_MCP_PORT_SETTLE_SECONDS", VIRTUAL_PORT_SETTLE_SECONDS
                )
            )
            if settle > 0:
                time.sleep(settle)
            return True

        self._error = (
            "No suitable MIDI output port found and this platform cannot create "
            "one. On Windows, install and run loopMIDI, create a port, then set "
            "it as the FL Studio MCP input in FL Studio's MIDI Settings. "
            f"Available ports: {output_ports or 'none'}"
        )
        return False

    def disconnect(self) -> None:
        """Close the MIDI connection."""
        if self._port is not None:
            try:
                self._port.close()
            except Exception:
                pass
            self._port = None
        self._connected = False
        self._port_name = None
        self._is_virtual = False

    def ensure_connected(self) -> None:
        """Ensure connection to FL Studio is active. Raises RuntimeError if not."""
        if not self.is_connected:
            if not self.connect():
                raise RuntimeError(
                    self._error or "Failed to connect to FL Studio via MIDI"
                )

    def send_command(
        self,
        action: str,
        params: dict[str, Any] | None = None,
        timeout: float = 2.0,
    ) -> dict[str, Any]:
        """Send a command to FL Studio and wait for response.

        Args:
            action: The command action (e.g., "transport.start", "mixer.setTrackVolume")
            params: Optional parameters for the command
            timeout: Maximum time to wait for response in seconds

        Returns:
            Response dictionary from FL Studio

        Raises:
            RuntimeError: If not connected or command fails
        """
        self.ensure_connected()

        # Prepare command
        command = {
            "action": action,
            "params": params or {},
        }

        # Write command to file
        try:
            self._command_file.write_text(json.dumps(command, indent=2))
        except Exception as e:
            return {"success": False, "error": f"Failed to write command file: {e}"}

        # Clear old response file
        if self._response_file.exists():
            try:
                self._response_file.unlink()
            except Exception:
                pass

        # Send MIDI trigger
        try:
            import mido
            trigger_msg = mido.Message("note_on", note=self.TRIGGER_NOTE, velocity=127)
            self._port.send(trigger_msg)
        except Exception as e:
            return {"success": False, "error": f"Failed to send MIDI trigger: {e}"}

        # Wait for response
        return self._wait_for_response(timeout)

    def _wait_for_response(self, timeout: float) -> dict[str, Any]:
        """Wait for response file to appear and read it.

        Args:
            timeout: Maximum time to wait in seconds

        Returns:
            Response dictionary or error dict if timeout
        """
        start_time = time.time()

        # FL Studio services a trigger in well under a millisecond: measured at a
        # median of 0.8ms on FL Studio 2026 / macOS 26 with an M-series CPU.
        # A flat 20ms poll therefore spent about 96 percent of every round trip
        # asleep. Poll tightly at first, then back off so a genuinely slow or
        # absent FL does not spin a core for the whole timeout.
        fast_poll_until = start_time + 0.1
        reader = MIDIResponseReader(self._response_file)

        while time.time() - start_time < timeout:
            poll_interval = 0.0005 if time.time() < fast_poll_until else 0.02
            response = reader.read()
            if response is not NOT_READY:
                # Clean up response file
                try:
                    self._response_file.unlink()
                except Exception:
                    pass

                return response

            time.sleep(poll_interval)

        return {
            "success": False,
            "error": (
                f"Timeout waiting for FL Studio response after {timeout}s. "
                "Make sure FL Studio is running and the MCP controller is enabled "
                "in MIDI Settings."
            ),
        }

    def get_status(self) -> dict[str, Any]:
        """Get connection status information."""
        try:
            import mido
            output_ports = mido.get_output_names()
        except Exception:
            output_ports = []

        return {
            "connected": self.is_connected,
            "port_name": self._port_name,
            "port_is_virtual": self._is_virtual,
            "available_ports": output_ports,
            "command_file": str(self._command_file),
            "response_file": str(self._response_file),
            "error": self._error,
        }


# Global connection instance
_connection: MIDIConnection | None = None


def get_connection() -> MIDIConnection:
    """Get the global MIDI connection instance."""
    global _connection
    if _connection is None:
        _connection = MIDIConnection()
    return _connection


def reset_connection() -> None:
    """Reset the connection state to allow reconnection attempts."""
    global _connection
    if _connection is not None:
        _connection.disconnect()
        _connection = None
