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

4. FL Studio: open a piano roll, then in the piano roll's own menu find
   **Piano roll scripts** and confirm **ComposeWithLLM** is listed. Assign it a
   keystroke, Cmd+Opt+Y on macOS or Ctrl+Alt+Y on Windows. This step cannot be
   automated from outside FL and nothing in this repo performs it, but without it
   the keystroke the server sends is delivered to nothing and every piano roll
   tool times out.

   To confirm the script itself works, click it from that menu directly. It needs
   no keystroke and no permission, so it separates "the script is broken" from
   "the trigger never arrived". An error inside the script appears as a dialog
   with a traceback and the script's path, which is the only debugging surface on
   that side.

5. Restart FL Studio. Hot reload covers later controller edits; the first install
   does not.

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
- [ ] `fl_batch` two commands and confirm both ran. Catches the batch runner
      stopping early or running a command twice.
- [ ] `fl_batch` where the second command is deliberately invalid, and confirm
      `executed: 1`, `failed: 1`, and the third command reported as skipped rather
      than run. Catches a half-applied edit reported as a whole one.
- [ ] `fl_batch` a mixer change and a channel change, then `fl_undo(steps=1)` and
      confirm the channel change is reversed. Then `fl_undo()` again and confirm
      the mixer change goes too. Catches `general.undo` being used as a toggle
      rather than `undoUpDown` as a relative move, which makes the second call
      redo instead of undo.
- [ ] `fl_connect` reports that FL is answering, and does so only when it is.
      Stop FL Studio and confirm it reports that no ping was answered rather than
      claiming success because a port opened.
- [ ] Two clients at once: run two MCP clients, or two shells calling
      `send_command` in parallel, and confirm each gets its own answer. Catches a
      regression in the request lock, which turns cross-talk into either wrong
      answers or empty ones.

## Piano roll path

This is the only path that nothing but a human can test: it needs the keystroke,
the Accessibility permission, and the real `flpianoroll`.

- [ ] Open a piano roll on a named channel by hand, so the target is not in doubt.
- [ ] `fl_send_notes(channel=N, ...)` where N is not the channel whose piano roll is
      open, and confirm the notes appear on N and the reply names N. Catches
      targeting that selects the channel but does not move the window, which is
      the failure this item exists for.
- [ ] `fl_send_notes(channel=N, verify=True, ...)` and confirm the reply says the
      notes were read back. Catches a script that reports notes it did not add.
- [ ] `fl_get_piano_roll_state(channel=N)` and confirm it holds the notes just
      written, and that a different channel holds different notes. Catches reading
      one piano roll and reporting another.
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

### 2026-09-19, Phase 2

FL Studio 2026, Producer Edition v26.1.6 build 5406, API version 45, macOS 26,
Apple silicon.

Passed, against live FL Studio:

- Targeting: `channels.selectPianoRoll` selected the right channel every time
  (index 2 gave 808 HiHat, index 1 gave 808 Clap, index 0 gave 808 Kick) and
  reported the selection it achieved. An index outside the project was refused
  with the real range: "this project has 5 channels, indexed 0 to 4".
- The roadmap's done-condition: `fl_send_notes(channel=2, verify=True)` returned
  `success: true`, `target_channel: 2`, `target_channel_name: "808 HiHat"`,
  `verified: true`, `verified_notes: 2`, and the user confirmed D4 and F4 appeared
  on the 808 HiHat piano roll rather than wherever focus happened to be.
- The read-back was genuinely independent: the state export reported 2 notes at
  that moment, and reported 0 afterwards once the user undid the write with
  Ctrl+Z. One Ctrl+Z removed both notes.

Not run:

- Auto-trigger keystroke, still blocked by macOS Accessibility error 1002, so the
  trigger was the Piano roll scripts menu throughout.
- Windows, and Windows with a OneDrive-redirected Documents folder. No machine.

### 2026-09-19, Phase 1

FL Studio 2026, Producer Edition v26.1.6 build 5406, API version 45, macOS 26,
Apple silicon.

Passed, against live FL Studio:

- Ping handshake: `fl_connect` reached FL with a ping answered in 3ms once the
  port was bound.
- Correlation: every reply carries the id of the command it answers.
- The abandoned-command check now genuinely exercises the race, because the 1ms
  call timed out with its trigger in flight, and the follow-up command ran
  **exactly once**. This is the roadmap's Phase 1 done-condition, and it holds.
- Missing target: `mixer.setTrackVolume` with no `track` is refused with
  "mixer.setTrackVolume requires a 'track'", and the Master track stayed at 0.8
  where the old code would have set it to 0.5.
- Batch atomicity: a batch whose second command was refused reported
  `executed: 1, failed: 1` and left the third command unrun.
- Undo: two mixer changes needed two `fl_undo` calls, reproducibly across three
  trials, and the track was back at its original volume and pan afterwards.

Not run:

- Auto-trigger keystroke, still blocked by macOS Accessibility error 1002.
- Windows, and Windows with a OneDrive-redirected Documents folder. No machine.
- The edit-safety refusal. The live project reports `safeToEdit: true`, and
  forcing it false on someone's open project is not something a smoke test should
  do. The refusal path is covered by tests against the fake only, and that gap is
  deliberate.

Found during this run, and since fixed:

- `general.undo()` is a toggle, as its stub says, so the server's single-step undo
  undone once and then redid. It now always uses `general.undoUpDown`.
- The roadmap's undo-grouping premise is wrong: `general.saveUndo` adds no history
  entry and does not reduce how many undos an edit needs. Batching delivers
  atomicity, not one-Ctrl+Z grouping, and the roadmap now says so.

### 2026-09-19, Phase 0

FL Studio 2026, Producer Edition v26.1.6 build 5406, API version 45, macOS 26,
Apple silicon.

Passed:

- Controller round trip, 1.1ms median over 10 calls.
- `fl_get_version`: API 45, `safeToEdit: true`, tempo 130000 raw for a 130 BPM
  project.
- The unknown-action bug is fixed: `bogus.doesNotExist` now returns
  `success: false`.
- Piano roll end to end, with the trigger clicked by hand from FL's Piano roll
  scripts menu: four notes added, the reply carried the matching request id and
  `notes_added: 4`, the exported state showed all four, the queue emptied, and the
  `slide` flag survived the round trip.
- Error propagation on the piano roll path is real: an `os.replace` the sandbox
  blocks produced FL's error dialog rather than a silent success.

Could not be run:

- The automatic keystroke. macOS refused it with error 1002,
  `osascript is not allowed to send keystrokes`, because the process running this
  does not hold the Accessibility permission. The code reports this honestly
  instead of claiming success. The manual menu path above covers the same script
  execution, but not the keystroke itself, so **the automated trigger remains
  unverified on this machine**.
- Windows, and Windows with a OneDrive-redirected Documents folder. No machine.

Found during this run, and since fixed:

- The piano roll script died on `os.replace`, which FL's sandbox blocks. Every
  automated test passed, because a local interpreter allows it.
- The controller died on `Path.mkdir` for the same reason.
- No piano roll keystroke was bound in FL, so the path had never worked. Setup
  step 4 above now covers it.
