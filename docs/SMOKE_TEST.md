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

## Mix review and gain staging

The findings are arithmetic over a peak hold, so a test can check the arithmetic. No
test can check that the arithmetic agrees with the record. That is this list, and it
is the only place the two are compared.

- [ ] Start playback, run `fl_mix_review()`, and confirm `levels_sampled` is true and
      the Master peak is not zero. Catches a review reporting on a mix it never
      measured.
- [ ] Compare the reported Master peak against FL's own master meter at that moment.
      They should agree within a few percent. Catches a peak read from the wrong
      track, which the fake cannot see because it answers for any index it is given.
- [ ] Decide by ear which element is loudest before reading the findings, then check
      the review's loudest track is that one. This is the item the phase exists for: a
      peak hold is a real measurement, but it only helps if it matches what is heard.
- [ ] Mute a track you can hear is sounding, re-run, and confirm it drops out of the
      loudest few. Then confirm no track you can plainly hear is reported as never
      sounding.
- [ ] Confirm a track that is muted and silent is not reported as never sounding.
      The reason is known already, so reporting it is noise.
- [ ] Confirm every clipping finding names a peak above 1.000 and a dB overshoot that
      matches it. A message reading "peaked at 1.00, which is over 0 dB" contradicts
      the rule that 1.0 is the ceiling, and the message is the thing a producer acts
      on.
- [ ] Confirm a fader left at FL's default earns an informational note rather than a
      problem, so the clipping finding stays at the top of the list.
- [ ] Note a fader's value, run `fl_mix_review()`, then confirm the fader did not
      move. Catches a diagnostic that is not read-only.
- [ ] With playback running, run `fl_gain_staging()` without `apply` and confirm the
      moves are reported and no fader moved in FL's mixer.
- [ ] Only on a scratch project, run `fl_gain_staging(apply=True)` and confirm the
      named faders moved down by the reported amounts, that nothing else moved, and
      that one Ctrl+Z reverses the whole pass. Do not run this on a project whose
      balance you care about. It has deliberately not been run against a real project
      in this repo.

## Curation, Phase 6

Most of Phase 6 is files on disk, so tests cover it. These items are the parts only a
human can judge: whether a recalled riff is the riff, whether a restored mix is the
mix, and whether the library is where you can find it.

- [ ] `fl_save_riff` on a phrase you know, then `fl_find_riffs` by tag and by key, then
      `fl_recall_riff` into a new pattern and listen. Catches a round trip that keeps
      the notes but loses the groove, which no test can hear.
- [ ] Recall the same riff into a project in another key and confirm it lands in that
      key and still sounds like the phrase rather than a transposed mistake.
- [ ] `fl_snapshot_project`, move two faders and rename a track, then
      `fl_project_changes` and confirm the report names exactly those three things.
      Catches a diff that reports float noise as changes, which would make it useless.
- [ ] `fl_restore_snapshot(apply=True)` and confirm the faders and the name come back,
      then press Ctrl+Z once and confirm the whole restore reverses. Catches a restore
      that is not one undo step.
- [ ] `fl_save_plugin_preset` on a synth you know, move three controls, recall it, and
      listen. Catches a preset that restores numbers but not the sound, which is the
      only thing that matters about it.
- [ ] `fl_morph_plugin_preset` between two presets at 0.5, and confirm the result is a
      usable in-between sound rather than silence or a stuck switch.
- [ ] `fl_find_samples` for a word you know is in your library and confirm the paths
      are ones you recognise, then highlight one of them in FL's browser and run
      `fl_audition_sample`. Catches a search that only finds factory content, and an
      audition that plays something other than what is highlighted.
- [ ] Confirm a `.wav` in the results that FL's own pack ships is reported with no
      duration and a reason, because it is Ogg Vorbis in a RIFF container. A duration
      there would be a number somebody made up.
- [ ] `fl_index_projects` on your projects folder and confirm the tempos and plugin
      names match what FL shows when you open one. Catches a reader that walks the file
      wrongly and still returns plausible numbers, which is how the published rule for
      this format fails.
- [ ] `fl_structure_critique` on a project with markers and confirm the sections match
      what you drew, including one marker deliberately off the bar line.
- [ ] `fl_apply_template` with `apply=False`, read the plan, then `apply=True`, look at
      FL, and undo once. Confirm a track you had already named was left alone.
- [ ] `fl_journal` after a session of edits and confirm it lists what you watched the
      server do, in order, with nothing that was only a question.
- [ ] Confirm `fl_create_pattern` refuses and explains, and that creating a pattern by
      hand and selecting it with `fl_set_pattern(select=True)` works. This call froze FL
      Studio twice in testing, so it must never run.

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
- [ ] Write a note with `slide` set and confirm FL draws it as a slide note rather
      than an ordinary one. Catches the property not reaching FL, which no test can
      see because the fake accepts anything.
- [ ] Write a note with `porta` set and confirm FL draws the portamento marker.
      Catches the same for the other articulation flag.
- [ ] Write a note with `pitchofs` set to 25 and confirm the pitch is a quarter tone
      up. Catches the units being read as semitones, which the API documents as 10
      cents and nothing enforces.
- [ ] `fl_get_project_context` with snap to scale switched on, and confirm the key
      matches what the piano roll shows. Then switch it off and confirm the tool says
      the scale is not set rather than naming C major.
- [ ] `fl_write_bassline` into a channel and confirm the notes are on that channel,
      are in the project's key, carry slide marks, and that one Ctrl+Z removes the
      whole phrase. Catches a group that did not get assigned.
- [ ] `fl_describe_project` and confirm the summary matches what is on screen, and
      that it took one round trip rather than one per channel.
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

### 2026-09-19, Phase 6

FL Studio 2026, Producer Edition v26.1.6 build 5406, API version 45, macOS 26,
Apple silicon. The project used for these runs was a fresh one; nothing of the
producer's was changed except one fader, which was restored in the same run.

Passed, live:

- Riff capture: four notes read out of channel 0's piano roll with their expression
  intact (`slide` survived), the key recorded as absent because snap to scale is off,
  tempo 130.0, and the instrument taken from the channel. Recall then refused to
  transpose, naming the reason and the way round it, which is the behaviour that keeps
  it from guessing a key.
- Plugin identity: channel 4 reports `name: FLEX` and `user_name: 808 Astronomic`,
  which is the distinction the old argument order could not express. A sampler channel
  answers that it is not a plugin rather than failing the command.
- Plugin parameter paging: `total: 45, returned: 3, skipped_unnamed: 0` with real
  names and display strings, after the call forms were corrected.
- `plugins.probeCalls`, added for this: `getParamValueString` accepts at most four
  keyword arguments, so the stub's `pickupMode` does not exist at runtime, and
  `setParamValue` needs five positional arguments with its first named `paramValue`.
  Passing `pickupMode` had emptied a parameter page while the handler reported success.
- Snapshot round trip: snapshot taken, Insert 1 nudged from 0.8 to 0.62, the diff
  reported exactly one change and named it, the restore planned one
  `mixer.setTrackVolume` move and applied it as one batch named `MCP: restore snapshot`,
  the fader came back to 0.8, and the diff then read "Nothing changed".
- Sample search: 12,966 files examined across the six discovered roots in 1.3 seconds,
  5,190 of them the FL factory packs in 0.54 seconds, and every sampled factory `.wav`
  reported as vorbis in a RIFF container with no duration and a reason.
- `.flp` reader: five autosaved projects read as 130.0 BPM, 4/4, PPQ 96, five channels,
  build 5406, matching what the running project reports.

Caused during this phase, and since fixed:

- `patterns.findFirstNextEmptyPat` **froze FL Studio twice**, costing two sessions. The
  first time it was called with flags 0, which the stubs say also prompts for a pattern
  name; the second time with the prompt flag set and the documented `None` return no
  longer used. It froze identically, so the prompt was not the cause and the function is
  unusable on this build. Pattern creation and pattern cloning now refuse, with the
  corrected call kept behind one constant and tested, and the roadmap and README record
  the finding.

Passed later in the same phase, the four checks that were test-only until then:

- `fl_index_projects` on the real projects folder: five autosaved projects found,
  every one read as 130.0 BPM and 4/4 with its channel names, status `ok`.
- The browser block of `fl_get_ui_state`: nothing focused reported as `None` rather than
  an empty string, file type `-1`, auto hide `False`, and no problems from the guarded
  reads.
- A preset round trip on channel 4: 42 parameters saved, one moved to 0.9, the recall
  reported exactly one change, applied it through one batch, and the parameter came back
  to 0.5 with its display string intact.
- The mixing template: 21 moves planned, applied as one batch, and the inserts came back
  named Drums, Bass, Keys and so on.

Found during that run, and worth knowing:

- **One undo did not reverse the 21 command template batch.** `fl_undo(steps=1)`
  reported success and the names were still changed afterwards, so the "one undo
  reverses the whole pass" wording in the batch tools is optimistic for a large batch.
  The reliable way back is `fl_restore_snapshot`, which put all 21 settings back,
  names and routing included, and is what was used here. The wording was left alone
  rather than rewritten in a hurry, so treat any claim about a single undo as unverified
  above a handful of commands.
- `fl_audition_sample` is still unrun: nothing was highlighted in FL's browser, and the
  tool correctly refused to claim it had played something.

Structure critique, after it learned to read marker times from the piano roll sandbox:

- The tool ran live and reported `marker_times_source: not_needed`, no sections, and two
  informational findings: the arrangement has no markers, so there is no structure to
  read, and the meter could not be read so bars would be counted in 4/4 as an assumption
  rather than a measurement. Both are the honest answers for this project.
- The marker time path itself is therefore **not exercised live**. The piano roll request
  did not answer during that run, which is why the meter came back unavailable: that path
  needs a focused piano roll window and the script to run. What is verified is that its
  absence produces a stated assumption and no invented bar positions.
- Confirming the two sandboxes share a timeline was attempted with two markers drawn in
  the arrangement, `test1` and `test2`. The result is a negative one, and it is recorded
  rather than smoothed over:

  * The controller reports both markers with `time: None`, as expected, since no
    `getMarkerTime` exists in that sandbox.
  * The automatic trigger did not reach the piano roll script twice, waiting 8 seconds
    and then 120 seconds with the request already queued. Running **ComposeWithLLM by
    hand** from the piano roll scripts menu answered immediately, so the script and the
    request format are fine and the server's keystroke delivery is what fails, which is
    the focus and Accessibility limitation Phase 0 recorded.
  * That reply was `success: true` with `ppq: 96` and `meter: 4/4`, so the new request
    path executes live and the meter can now be measured instead of assumed.
  * It also reported **zero markers**, while the arrangement holds two. The critique
    therefore answered `marker_times_source: mismatch`, left both sections without a
    start or a length, and invented no bar numbers. That is the designed behaviour and
    it is now verified live.

  So the honest conclusion is that the piano roll sandbox's marker list is **not** the
  arrangement's marker list on this build: the accessors exist and report an empty list,
  which suggests they expose piano roll or pattern markers rather than arrangement
  timeline markers. Marker times are read from the stubs and the plumbing works, but the
  feature does not currently produce arrangement section bars, and nothing should claim
  otherwise.

  The reply carried `markers_error: null` and `markers: []`, so the accessors were found
  and reported nothing rather than being missing. Two explanations remain, and one
  experiment separates them. The stub's `Marker` documents `mode` values of 8 and 12
  with `tsnum`, `tsden`, `scale_root` and `scale_helper`, which are the playlist's time
  signature and key markers, so this API looks like it is meant for those. Placing a
  **time signature marker** in the playlist and running the request again tells us which
  explanation is true:

  * a non-zero count means the accessors work and report a narrower set of markers than
    the arrangement's, and the feature can be rebuilt around that set;
  * a count that stays at zero with a marker that certainly exists means the accessors
    are a silent no-op on this build, which is the failure mode this API is known for,
    and the feature should be deleted rather than carried.

  Until that runs, treat marker times as plumbing that executes and reports honestly,
  not as a feature that reads the arrangement.

Could not be run:

- Riff recall into a pattern, because the only pattern's piano roll holds the
  producer's four notes and the tool correctly refuses to clear a piano roll that is not
  empty. The write path is covered by tests against the fake and by the note tools that
  share it, but the riff round trip itself has not been played.
- Preset recall and morph, a template applied to real tracks, the browser reads and an
  audition, and the project index tool. All are covered by tests; none has been run
  against FL.
- The journal read after a session of edits, for the same reason: no session of edits
  has happened since it was built.
- Windows, and Windows with a OneDrive-redirected Documents folder. No machine.

### 2026-09-19, Phase 5

FL Studio 2026, Producer Edition v26.1.6 build 5406, API version 45, macOS 26,
Apple silicon. The project was left as found: nothing was moved, muted or renamed.

Passed, read-only, with the user's playback running:

- The refusal: with the transport stopped, `fl_mix_review` reported
  `levels_sampled: false` and said the transport was stopped, rather than reporting a
  silent mix. That is the behaviour the whole phase is built on.
- The done condition, one problem finding from a real project. Master was clipping.
  The other two findings were informational and correct for this project: every insert
  at FL's default fader, and nothing panned.
- A second pass printed the raw peaks unrounded: Master 0.892, Insert 2 0.860,
  Insert 1 0.819, Insert 3 0.485, from 60 readings over three seconds. The Master is
  therefore near the ceiling but not over it in general, which is exactly why the
  clipping in the first pass was intermittent and worth catching.
- 18 tracks reviewed in one round trip, which is the Phase 5 reason for the batched
  snapshot: the same review with a call per track would be 18 triggers.

Found during this run, and since fixed:

- The clipping message contradicted its own threshold. A peak of 1.004 printed with
  two decimals as "peaked at 1.00, which is over 0 dB, so it is clipping", and 1.00 is
  the exact value the tool says is not clipping. The peak is now printed to three
  decimals with the dB overshoot. The real value from this run is lost to the
  rounding, so it is recorded here as above 1.0 rather than as a number.
- 60 readings of real audio were reported beside `is_playing: false`, because the
  transport is read after the sampling window and playback had finished inside it.
  The sampler now reports `played_throughout`, and the review surfaces a window that
  was cut short as `levels_partial`, so a partial pass cannot read as a full one.
- The sampler carried its own copy of the clipping threshold. It now imports
  `CLIP_THRESHOLD` from the analysis module, because two copies of that boundary
  drift and the sampler's flag has to agree with the review's rule.

Not run, on purpose:

- `fl_gain_staging(apply=True)` against this project. It moves faders, and the phase
  says not to do that to someone's work unasked. The reporting form was exercised,
  and the applying form is covered by tests against the fake only, so the applying
  path has never touched a real project.
- Windows, and Windows with a OneDrive-redirected Documents folder. No machine.
- The automatic piano roll keystroke, still blocked by macOS Accessibility error 1002.

### 2026-09-19, Phase 4

FL Studio 2026, Producer Edition v26.1.6 build 5406, API version 45, macOS 26,
Apple silicon.

Passed, against live FL Studio:

- Note expression: two notes written with `slide`, `porta`, `fcut` 0.7, `fres` 0.3,
  `pitchofs` 25, `release` 0.4 and `group` 3 all came back with those values intact,
  and FL drew the slide marker and the portamento marker on screen. This is the
  check the fake cannot make, because a fake accepts whatever it is given.
- The Phase 4 done-condition: one `fl_write_bassline` call wrote a slide-articulated
  bassline into a named channel in the project's own key and meter, and the read-back
  confirmed it. Six notes, C2 and G2, every one carrying a slide, grouped as group 1
  so one Ctrl+Z removes the phrase.
- Project context: FL reported `root_note` 0, an empty `scale_helper`, 4/4 and PPQ
  96 for the open project.

Could not be run:

- Windows, and Windows with a OneDrive-redirected Documents folder. No machine.
- The MIDI file bridge against FL, because there is no tool that reads or writes a
  MIDI file through FL; the bridge is tested against the filesystem only.
- The automatic keystroke, still blocked by macOS Accessibility error 1002, so every
  live piano roll run went through FL's menu.

Found during this run, and since fixed:

- With snap to scale switched off, `score.snap_scale_helper` returns an empty string
  rather than twelve values. The first version treated that as malformed, which would
  have made every project without snap to scale unusable.
- An untouched note's `pan`, `fcut`, `fres` and `release` all read back as 0.5, not
  0.0, so those are normalised with 0.5 as neutral.
- `pitchofs` is an int in units of 10 cents, so the quarter tone used in an early
  test was never a valid value.
- A reply that carried two responses, a context read and a write, echoed the context
  fields as null, so the caller was told the project's key was unknown when the
  script had just answered it.
- `get_project_context` imported a helper from the test suite, so the shipped code
  raised ModuleNotFoundError the first time it was called for real. No test caught it
  because every test supplied the helper.

### 2026-09-19, Phase 3

FL Studio 2026, Producer Edition v26.1.6 build 5406, API version 45, macOS 26,
Apple silicon.

Passed, against live FL Studio, all read-only except where noted:

- Patterns: the real project reported one pattern, name "Pattern 0", length 16,
  colour 0x485156. This corrected three wrong assumptions, recorded below.
- Mixer EQ: an insert reports three bands, not seven, with gain, frequency and
  bandwidth each.
- Routing: Insert 1 sends to Master at 0.8, and the project reported 18 mixer
  tracks.
- Levels: read 0.0 with the transport stopped, which is correct rather than a bug.
- Playlist: FL reported 500 lanes and the tool correctly reported that all 500 are
  empty generated lanes rather than listing them.
- Markers: none on this project, and the tool said so instead of returning 513
  empty entries.
- Channel properties and UI state: channel 0 is "808 Kick", type 0, feeding mixer
  track 1, and the piano roll window was visible.

Run with the owner's explicit agreement, and restored afterwards:

- Tempo write: set to 128 BPM and read back, then restored to 130 and confirmed by
  an independent read. Later verified through the shipped tool across a real change
  from 130 to 126, a repeat of the same value, and a restore to 130. The project
  ended at 130, where it started.

Not run:

- Windows, and Windows with a OneDrive-redirected Documents folder. No machine.
- Any write to the playlist, arrangement or UI on this project. Those paths are
  fake-tested only, because a smoke test has no business renaming someone's
  arrangement lanes or moving their windows.

Found during this run, and since fixed:

- The pattern accessors do not share an index base: `patternCount` is a 0-based
  count, `patternNumber` is 1-based, `getPatternName` and `getPatternLength` are
  0-based, and `isPatternSelected` and `isPatternDefault` are 1-based, where index
  0 raises "Index out of range".
- FL names its patterns "Pattern 0", not "Pattern 1".
- `getPatternColor` returns a signed int, so a colour with the high bit set arrives
  negative.
- An insert EQ has three bands, not seven.
- Reading past the last arrangement marker returns an empty name rather than
  failing.
- Reading a playlist lane's properties for index 0 returns nulls.
- The tempo no-op case: setting a project to the tempo it already has is a
  legitimate request, and the first version of the tool reported it as an error.

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
