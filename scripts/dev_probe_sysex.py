"""Research spike T4: can FL Studio send SysEx back to this process?

The roadmap's T4 asks whether `device.midiOutSysex` plus an `OnSysEx` callback
give a genuine bidirectional MIDI channel with no filesystem and no keystroke.
The stubs answer the "does the function exist" half: `device.midiOutSysex` is
documented in `device/__device.py` and `OnSysEx` in the callbacks stubs, both
since API version 1. What they cannot answer is whether a message sent that way
actually leaves FL Studio, and through which port.

This script answers that half. It:

1. Creates a virtual MIDI output (how commands reach FL, name from
   FL_STUDIO_MCP_VIRTUAL_PORT_NAME, default "FL Studio MCP").
2. Creates a virtual MIDI input (how FL talks back, name from
   FL_STUDIO_MCP_PROBE_INPUT_PORT, default "FL Studio MCP Probe").
3. Sends a `system.sysExProbe` command and prints whatever SysEx comes back.

Step 2 needs a human. FL Studio only sends to a MIDI port that the user has
enabled as an *output* in Options > MIDI Settings, and no scripting API can
toggle that. The script therefore re-sends the probe on a timer, so the settings
change can be made while it is running.

This modifies nothing in the project: the command it sends is a read-only
version probe.

Usage:
    uv run python scripts/dev_probe_sysex.py --headless --seconds 180
    uv run python scripts/dev_probe_sysex.py            # interactive
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from fl_studio_mcp.utils.midi_connection import (  # noqa: E402
    VIRTUAL_INPUT_PORT_NAME,
    VIRTUAL_PORT_NAME,
)

PROBE_PORT_NAME = os.environ.get("FL_STUDIO_MCP_PROBE_INPUT_PORT", VIRTUAL_INPUT_PORT_NAME)
COMMAND_PORT_NAME = os.environ.get("FL_STUDIO_MCP_VIRTUAL_PORT_NAME", VIRTUAL_PORT_NAME)

# The controller shifts each JSON byte up by 0x38 before sending, so no byte in
# the body can collide with the SysEx boundary bytes or the realtime range.
BYTE_SHIFT = 0x38

COMMAND_FILE = (
    Path.home()
    / "Documents"
    / "Image-Line"
    / "FL Studio"
    / "Settings"
    / "Hardware"
    / "FLStudioMCP"
    / "mcp_command.json"
)


def decode_sysex(data: bytes) -> str | None:
    """Turn the probe's SysEx body back into the JSON text FL sent.

    Returns None if any byte falls below the shift, which means the message did
    not come from the probe and is not ours to interpret.
    """
    try:
        return "".join(chr(b - BYTE_SHIFT) for b in data)
    except (ValueError, TypeError):
        return None


def describe(message) -> str:
    """Render an incoming mido message compactly."""
    if getattr(message, "type", None) == "sysex":
        body = bytes(message.data)
        text = decode_sysex(body)
        missing = [b for b in body if b < BYTE_SHIFT]
        return (
            f"sysex, {len(body)} bytes, decoded: {text!r}"
            f" (bytes below the shift: {missing})"
        )
    return str(message)


def fire_probe(command_port, tag: str) -> None:
    """Write the probe command and trigger FL with the usual note."""
    import mido

    COMMAND_FILE.parent.mkdir(parents=True, exist_ok=True)
    COMMAND_FILE.write_text(
        '{"action": "system.sysExProbe", "params": {"echo": "%s"}}' % tag
    )
    command_port.send(mido.Message("note_on", note=127, velocity=127))


def instructions() -> None:
    print("In FL Studio: Options > MIDI Settings.")
    print("  - The command port must be enabled as an input with controller type")
    print("    'FL Studio MCP Controller' (the existing setup, unchanged).")
    print(f"  - NEW: find '{PROBE_PORT_NAME}' in the output list, select it, and")
    print("    send it on a port number. FL's controller here reports its input")
    print("    port number; matching the two is the point of the exercise.")
    print("  - If the probe port is not listed, click 'Refresh device list'.")


def run(seconds: float, interval: float, interactive: bool) -> int:
    import mido

    print("FL Studio MCP: SysEx return-path probe (research spike T4)")
    print("Read-only. Sends a version probe and listens for a reply.\n")

    try:
        command_port = mido.open_output(COMMAND_PORT_NAME, virtual=True)
    except Exception as e:
        print(f"FAIL: could not create the command output port: {e}")
        return 1

    try:
        listen_port = mido.open_input(PROBE_PORT_NAME, virtual=True)
    except Exception as e:
        print(f"FAIL: could not create the probe input port: {e}")
        command_port.close()
        return 1

    print(f"command port (FL input)  : {COMMAND_PORT_NAME}")
    print(f"probe port   (FL output) : {PROBE_PORT_NAME}\n")
    instructions()

    hits: list[str] = []

    def on_message(message) -> None:
        line = describe(message)
        hits.append(line)
        print(f"  <- {line}", flush=True)

    listen_port.callback = on_message

    try:
        if interactive:
            tag = 0
            while True:
                fire_probe(command_port, str(tag))
                tag += 1
                reply = input("\nEnter to probe again, 'q' to quit: ")
                if reply.strip().lower() == "q":
                    break
        else:
            deadline = time.time() + seconds
            tag = 0
            while time.time() < deadline:
                fire_probe(command_port, str(tag))
                tag += 1
                print(f"probe {tag} sent", flush=True)
                time.sleep(interval)
    except (EOFError, KeyboardInterrupt):
        pass

    print("\n--- result ---")
    if hits:
        print(f"PASS: FL Studio sent {len(hits)} SysEx message(s) back.")
        print("device.midiOutSysex reaches the host, so a SysEx return path is")
        print("possible. It still needs the user to enable an output port in FL's")
        print("MIDI Settings, so files remain the zero-config default.")
    else:
        print("INCONCLUSIVE: no SysEx arrived.")
        print("Check, in order: the probe port is enabled as an output in FL's")
        print("MIDI Settings; the controller script was recopied after the last")
        print("edit; FL's controller reports a non-negative device port number.")

    listen_port.close()
    command_port.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--headless",
        action="store_true",
        help="no prompts; fire the probe on a timer (for use while changing FL settings)",
    )
    parser.add_argument(
        "--seconds",
        type=float,
        default=180.0,
        help="headless mode: how long to keep probing (default 180)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=5.0,
        help="headless mode: seconds between probes (default 5)",
    )
    args = parser.parse_args()
    return run(args.seconds, args.interval, interactive=not args.headless)


if __name__ == "__main__":
    raise SystemExit(main())
