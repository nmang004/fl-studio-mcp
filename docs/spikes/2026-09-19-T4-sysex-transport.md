# Spike T4: SysEx transport

**Date:** 2026-09-19
**Status:** Resolved, negative for the roadmap's stated use
**Environment:** FL Studio 2026 (Producer Edition v26.1.6, build 5406), API version
45, macOS 26, Apple silicon, mido 1.3.3, python-rtmidi 1.5.8 (rtmidi 5.0.0)

## The question

ROADMAP.md asked whether `device.midiOutSysex` plus an `OnSysEx` callback would
give a genuine bidirectional MIDI channel with no filesystem and no keystroke,
and noted: "If this works it supersedes much of Phase 1's file plumbing, so spike
it early."

## Summary

Both halves of the API exist and the host half is easier than expected, but FL
Studio's port assignment model makes the return path unusable as a default. The
roadmap's premise, that a working T4 supersedes Phase 1's file plumbing, is
**wrong on two counts**: T4 still needs the filesystem for the cases where it does
not apply, and the Phase 1 items it was supposed to replace are orthogonal to the
transport. Recommendation: keep files as the transport. Do not build on T4.

## Verified by reading the stubs

- `device.midiOutSysex(message: bytes) -> None` exists, "Included since API
  version 1" (`device/__device.py` line 161). Its docstring states the message
  must include the `0xF0` start and `0xF7` end bytes "or FL Studio will ignore
  the function call entirely".
- `OnSysEx(msg: FlMidiMsg) -> None` exists, "Included since API version 1"
  (`build_lib/midi_controller_scripting/callbacks/__init__.py` line 93).
- `device.isAssigned() -> bool` exists and is described as: "Returns `True` if an
  output interface is linked to the script, meaning that the script can send MIDI
  messages to that device" (line 30).
- `device.getPortNumber() -> int` exists, "port number of the input device that
  the script is attached to" (line 64). `device.isMidiOutAssigned()` also exists
  but carries an explicit crash warning and was not called.
- `device.midiOutSysex` sends to "the (linked) output device" for the controller,
  which means an FL-side configuration the scripting API cannot perform.

## Verified by observing live FL Studio

### Virtual MIDI input works on macOS

This was the main unknown on the host side, and the expected answer was that it
would not work. `python-rtmidi` does expose `open_virtual_port` on `MidiIn`, mido
does not restrict `virtual=True` by port direction, and CoreMIDI supports virtual
destinations. Confirmed by probe: a virtual input was created, a second process
saw it in `get_output_names()`, sent a SysEx and a note to it, and the first
process received both. No IAC Driver involved.

### FL reports no output interface by default

`system.sysExProbe` returned `device.isAssigned() == 0` and
`device.getPortNumber() == -1` on the working setup. FL was receiving commands
from the virtual port the whole time, so `getPortNumber()` returning `-1` does not
mean "no device attached"; it means "no port number configured for this row".

### The output port needs an output port number

The user enabled "FL Studio MCP Probe" in FL's output list on port 1, which was
also the input row's number. Then `device.isAssigned()` returned `1`,
`device.getPortNumber()` returned `1`, and both `device.midiOutSysex` and
`device.midiOutMsg` accepted their calls without raising.

### Matching port numbers produce an echo, not a return path

With input and output both on port 1, the listener received
`note_on note=127 velocity=127`, which is the server's own trigger note. FL was
echoing its input back out. It received neither the controller's SysEx nor the
`device.midiOutMsg` note that were sent in the same command.

### Separating the port numbers breaks `isAssigned`, and sends are dropped

The input row was moved to port 2 while the probe output stayed on port 1. Then
`device.getPortNumber()` returned `2`, but `device.isAssigned()` returned `0`
again and `device.midiOutMsg` raised. No message of any kind reached the listener.

## Conclusions

`device.isAssigned()` tracks whether an output port shares the port number
configured for the controller's input row. That creates a bind:

- Port numbers match: `isAssigned()` is true and the calls succeed, but FL routes
  the controller's output back to the endpoint it is also reading from, so the
  messages never leave the loop.
- Port numbers differ: nothing is linked and every send is dropped.

Making this work would need FL's output bound to a port that is not the one FL
reads from, which FL's port-number-keyed routing does not appear to offer for two
virtual endpoints. That is a limit of FL's MIDI device model, not of the API
functions, which both exist and are callable.

Because T4 cannot be made to work without the user editing FL's MIDI Settings by
hand, and because it cannot be verified from inside the project at all, it cannot
be a transport the server relies on. `loopMIDI` on Windows has the same manual
setup cost, so this was already true there; the finding is that it is true on
macOS too, for a different reason.

## What would be needed to revisit

- A named output device that FL can bind independently of its input, which
  means either a second physical or virtual endpoint presented under a different
  name with a working port number. The probe found the name is listed, so the
  blocker is the routing, not the listing.
- Confirmation that `device.isAssigned()` behaves this way by design rather than
  as a quirk of virtual CoreMIDI ports. Untested on Windows with loopMIDI.

## Consequence for Phase 1

Unchanged in substance, corrected in framing:

- Request correlation, atomic writes, error propagation, the `ping` handshake and
  `safeToEdit` gating are all transport-independent. They were never contingent on
  T4 and are not superseded by it.
- The keystroke trigger and its Accessibility permission requirement are for the
  piano roll path (Phase 2) and are untouched by T4, which only ever concerned the
  controller path.
- The file-based transport stays the default and the only path guaranteed to work
  on a stock install, which was already the position for Windows.

## Artefacts

- `scripts/dev_probe_sysex.py`: the probe. Read-only against the project; it sends
  one version query. Kept, because a future revisit needs exactly this tool.
- `fl_controller/device_FLStudioMCP.py`: a `system.sysExProbe` action. Kept for the
  same reason, and because it is the only way to read `device.isAssigned()` and
  `device.getPortNumber()` from a live FL.
- `FL_STUDIO_MCP_VIRTUAL_PORT_NAME` and `VIRTUAL_INPUT_PORT_NAME` in
  `utils/midi_connection.py`, so a diagnostic can create its own named port
  without disturbing the one the server owns.

## Incidental findings

- FL Studio **hot-reloads the controller script**, confirmed directly: the
  installed copy matched the repo copy byte for byte before the edit, the edit was
  copied over, and the next command answered an action the old code rejected with
  "Unknown action". Only the first install needs a restart.
- The unknown-action bug was reproduced again in its exact form:
  `{'success': True, 'error': 'Unknown action: ...'}`.
- A stray 4 byte SysEx (`06 01 ...`) appeared on the fresh probe input during
  silence. Something on this machine (most likely the Arturia KeyLab) emits it.
  Any future SysEx listener must filter by payload, not by "a SysEx arrived".
