"""Hold a virtual MIDI output port open for manual testing.

macOS and Linux only. python-rtmidi can create a virtual MIDI port, which FL
Studio then sees as an ordinary MIDI input device. That removes the need for the
IAC Driver on macOS entirely. Windows has no native virtual MIDI API, so loopMIDI
is still required there.

The port only exists while this process runs. Leave it running in a terminal
while testing, or let the MCP server own the port once that lands in the server
itself.

Usage:
    uv run python scripts/dev_hold_midi_port.py [port_name]

Send a trigger note on demand by typing "t" then Enter. Quit with Ctrl+C.
"""

from __future__ import annotations

import platform
import sys
import time

import mido

DEFAULT_PORT_NAME = "FL Studio MCP"
TRIGGER_NOTE = 127


def main() -> int:
    if platform.system() == "Windows":
        print("Windows cannot create virtual MIDI ports. Use loopMIDI instead.")
        return 1

    name = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PORT_NAME

    try:
        port = mido.open_output(name, virtual=True)
    except Exception as e:
        print(f"Failed to create virtual port {name!r}: {type(e).__name__}: {e}")
        return 1

    print(f"Virtual MIDI port open: {name}", flush=True)
    print("In FL Studio: Options > MIDI Settings, select this port under Input,", flush=True)
    print("enable it, and set Controller type to FLStudioMCP.", flush=True)

    interactive = sys.stdin.isatty()
    if interactive:
        print('Type "t" then Enter to send a trigger note. Ctrl+C to quit.', flush=True)
    else:
        # Detached (background) run: nothing will ever arrive on stdin, so
        # reading it would hit EOF immediately and drop the port.
        print("Running detached. Ctrl+C or kill the process to release.", flush=True)

    try:
        if interactive:
            for line in sys.stdin:
                if line.strip().lower() == "t":
                    port.send(mido.Message("note_on", note=TRIGGER_NOTE, velocity=127))
                    print(f"sent note_on {TRIGGER_NOTE}", flush=True)
        else:
            while True:
                time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        port.close()
        print("\nPort closed.", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
