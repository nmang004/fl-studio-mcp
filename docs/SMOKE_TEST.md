# Smoke test: what CI cannot cover

CI has no FL Studio. Everything in this file has to be run by a human on a machine
with FL Studio installed, and the result recorded. Every item names the specific
failure it catches, so a skipped item is a known blind spot rather than a vague
worry.

Run the automated pre-flight first:

```bash
uv run pytest
uv run ruff check .
uv run python scripts/dev_verify_connection.py
```

`dev_verify_connection.py` is read-only and prints the port, a round trip, the
environment, latency, and checks the bugs that were reproduced live. Run it before
and after any transport change.

## Setup, once per machine

1. Copy the controller script:

   ```bash
   cp fl_controller/device_FLStudioMCP.py \
      ~/Documents/Image-Line/FL\ Studio/Settings/Hardware/FLStudioMCP/
   ```

2. Copy the piano roll script:

   ```bash
   cp scripts/ComposeWithLLM.pyscript \
      ~/Documents/Image-Line/FL\ Studio/Settings/Piano\ roll\ scripts/
   ```

3. FL Studio: Options > MIDI Settings. Enable the "FL Studio MCP" input and set
   its controller type to "FL Studio MCP Controller".

4. FL Studio: assign the ComposeWithLLM piano roll script a keystroke, Cmd+Opt+Y
   on macOS or Ctrl+Alt+Y on Windows.

5. Restart FL Studio. Hot reload covers later script edits; the first install does
   not.

## Every time an FL-side script changes

Recopy it first. This is the single easiest mistake to make here, and it presents
as the change having had no effect.

- [ ] Re-copy the changed script into the FL Studio settings folder.
- [ ] `uv run python scripts/dev_verify_connection.py`, and confirm the round trip
      is OK. Catches a script error that stops FL loading it at all, which looks
      exactly like FL Studio not running.
- [ ] Confirm the reported API version is 45 on FL Studio 2026. Catches talking to
      an older FL than the tests assume.
- [ ] Confirm median latency is near 1ms. Catches a regression in the adaptive
      poll interval.

## Controller path, read-only

- [ ] `fl_get_version` returns API version 45, `safeToEdit: true`, and a tempo of
      130.0 for a 130 BPM project. Catches the thousandths-of-a-BPM scaling being
      forgotten.
- [ ] `fl_get_channels` lists the real channel names. Catches the global versus
      pattern-local index flag being wrong, which returns plausible names from the
      wrong channels.
- [ ] Send `bogus.doesNotExist` and confirm the reply is a failure. Catches the
      merge bug that reported an unknown action as a success.
- [ ] `fl_get_piano_roll_info` reports the scripts directory that actually
      contains the installed scripts.

## Controller path, mutating

Ask before running these, and restore the project afterwards.

- [ ] `fl_set_channel_volume` on a named channel changes that channel and no
      other. Catches a handler defaulting to index 0, which silently edits
      whichever channel is first.
- [ ] `fl_set_step_sequence` lights the steps you named on the channel you named.
      Catches the global index flag being wrong on the step sequencer.
- [ ] With playback running, confirm a mutating tool refuses rather than
      corrupting the project. Catches `safeToEdit` gating being dropped.
- [ ] Undo once with Ctrl+Z and confirm the whole edit is undone. Catches per-note
      undo grouping, which is Phase 1 work.

## Piano roll path

This is the only path that nothing but a human can test: it needs the keystroke,
the Accessibility permission, and the real `flpianoroll`.

- [ ] Open a piano roll on a named channel by hand, so the target is not in doubt.
- [ ] `fl_send_notes` a short phrase and confirm the notes appear on that channel.
      Catches notes landing in whichever piano roll happened to be focused, which
      is Phase 2's targeting work.
- [ ] Confirm the tool's report matches what actually landed. Catches the reply
      being ignored, which is what the old code did.
- [ ] `fl_get_piano_roll_state` returns the notes you just wrote, with their
      velocity and pan. Catches a stale state file being returned.
- [ ] Send notes with `slide` and `porta` set, and confirm FL shows them as slide
      and portamento notes rather than ordinary ones. Catches the expression
      properties not being written, which is Phase 4's whole point.
- [ ] Send a request with a deliberately invalid note and confirm the tool reports
      a specific failure. Catches unconditional success reporting.
- [ ] Trigger the script twice in a row with nothing queued and confirm no notes
      are duplicated or deleted. Catches requests left in the queue replaying.
- [ ] Revoke Accessibility permission for the terminal or client, then confirm the
      tool reports that the trigger failed instead of timing out silently.
      Catches the trigger's exit code being ignored.

## Platforms

Both must be covered before a release. Windows needs the extra step.

- [ ] macOS: the whole list above.
- [ ] Windows: the whole list above, plus confirm the server uses a loopMIDI port
      rather than trying to create a virtual one. Catches a regression that breaks
      Windows, which has no virtual MIDI API.
- [ ] Windows with OneDrive-redirected Documents: confirm the settings directory
      is found. Catches upstream issue #2.

## Record

Note the date, the FL Studio version, the API version, and any item that failed,
in the commit message or the pull request description. A smoke test with no record
is a rumour.
