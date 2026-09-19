# FL Studio MCP Roadmap

This fork rebuilds the upstream server into a reliable, FL-native music production
tool. It is the spec that per-phase implementation plans argue from.

**Status:** Phase 0 not started. Three Phase 1 items landed early, out of order,
because they blocked the test environment: see "Verified against live FL Studio".

**Source of truth for the FL Studio API:** the official stubs package
(`fl-studio-api-stubs>=37.0`, already a dev dependency). Every API claim in this
document was checked against stubs v37.0.1. Items whose stub entries are marked
"HELP WANTED" upstream are flagged as research spikes, not committed work.

---

## Verified against live FL Studio

Measured 2026-09-19 on FL Studio 2026 (26.1.6.5406), macOS 26, Apple silicon.
Anything here is observation, not inference.

| Finding | Detail |
| --- | --- |
| Virtual MIDI port works | `mido.open_output("FL Studio MCP", virtual=True)` creates a port FL sees as an ordinary MIDI input. The IAC Driver is not needed on macOS at all. Same call works on Linux via ALSA. Windows has no virtual MIDI API, so loopMIDI stays required |
| The creating process must send | a virtual port does not appear in `mido.get_output_names()` for any other process, so the server has to own the port. The old discovery-only code could never use one |
| FL binds lazily | FL takes 2.0 to 2.3 seconds to bind a newly created virtual port. Commands sent before that are silently dropped and look exactly like "FL Studio is not running" |
| FL is fast | FL services a trigger in a median of **0.8ms**. The 23ms round trip the old code reported was almost entirely its own flat 20ms poll interval |
| Controller type name | FL lists the script by its `# name=` header, so the dropdown reads "FL Studio MCP Controller", not "FLStudioMCP" as the upstream README says |
| API version is 45 | `general.getVersion()` returns **45**, against `ui.getVersion()` of "Producer Edition v26.1.6 [build 5406]". Everything in stubs v37 is available, including `safeToEdit` (API 29). The upstream 20.7+ floor is far below what is actually installed here, so do not assume a feature is missing without checking |
| Tempo scaling confirmed | `mixer.getCurrentTempo()` returned `130000` on a 130 BPM project, confirming thousandths of a BPM. This resolves the read half of spike T1; the `processRECEvent` write flags are still unverified |
| Controller script hot-reloads | editing and recopying `device_FLStudioMCP.py` took effect without restarting FL. Only the initial install needs a restart, which makes the dev loop much faster than the README implies |
| Unknown actions report success | reproduced live: `bogus.doesNotExist` returns `success: True` alongside an error string |
| Double execution | not reproduced live. The race window is roughly 1ms wide given FL's speed, so it is much narrower than the audit assumed. The missing correlation is still structural, and two concurrent MCP clients hit it without needing a timeout |

### Landed early

- Server creates and owns its virtual MIDI port, with `FL_STUDIO_MCP_MIDI_PORT` to
  override. The "fall back to the first available port" hazard is gone, so trigger
  notes can no longer reach the user's real hardware. Covered by
  `tests/test_port_selection.py`.
- Adaptive poll interval: 0.5ms for the first 100ms, then 20ms. Round trip went
  from 23ms to 1.0ms measured, a 23x improvement.
- Settle delay after creating a virtual port, so the first command is not lost.
- A `system.getInfo` action and an `fl_get_version` tool reporting FL version, API
  version, tempo, and whether version-gated functions actually work.

## Why this fork exists

The upstream server works in demo conditions and breaks in real ones. The audit
that produced this roadmap found three structural problems:

1. **The transport has no correlation.** No request IDs, so a timed-out command
   makes the next command execute twice. Toggles (play, record, arm, mute) cancel
   themselves. Two MCP clients on one machine cross-talk.
2. **The piano roll path cannot be verified.** It writes a file, sends a
   keystroke, sleeps two seconds, and reports success unconditionally. It never
   reads the response the FL-side script already writes, and it has no idea which
   channel's piano roll is open.
3. **The API surface is a thin wrapper over roughly a quarter of what FL exposes,**
   and skips the parts producers care about: patterns, undo, tempo, EQ, routing,
   metering, note expression, key and meter awareness.

Fixing 1 and 2 is prerequisite to everything else. Building features on an
unreliable transport just produces unreliable features.

---

## Global constraints

Every phase inherits these.

| Constraint | Value |
| --- | --- |
| Python | `>=3.10`, ruff `target-version = "py310"` |
| Lint | `ruff check .` clean, line length 100, rules `E`, `F`, `I`, `W` |
| Tests | `pytest` green with no FL Studio running (see Phase 0) |
| FL Studio | 20.7+ for MIDI controller scripting; `general.safeToEdit` needs API v29+ |
| Intel Mac | keep `constraint-dependencies = ["cryptography<49"]` in `pyproject.toml` |
| Platforms | macOS and Windows must both keep working; do not regress either path |
| Prose style | no em dashes, no en dashes, no emoji, anywhere in code, comments, docs or commit messages |
| Attribution | no AI or assistant attribution in commits, PRs, READMEs or any deliverable |
| Upstream | keep commits scoped so individual fixes stay cherry-pickable back to upstream |

### Sandbox rules that constrain the design

These are properties of FL Studio's embedded Python, not preferences. Violating
them produces code that imports fine locally and fails silently inside FL.

- The controller script (`fl_controller/device_FLStudioMCP.py`) runs inside FL with
  no `__file__`, a restricted stdlib, and no ability to install packages. It can
  import `channels`, `mixer`, `transport`, `plugins`, `general`, `patterns`,
  `playlist`, `arrangement`, `ui`, `device`, `midi`.
- The piano roll script (`scripts/ComposeWithLLM.pyscript`) runs in a *separate*
  sandbox whose only FL module is `flpianoroll`. It cannot see `channels` or
  `mixer`. This is why the two paths exist and cannot be merged.
- Script output goes to FL's View > Script output window. There is no debugger.

---

## Phase 0: Test harness and CI

Nothing else is safe to build without this. The goal is that the FL-side scripts
are importable and testable on a machine with no FL Studio installed.

- Fake FL modules (`channels`, `mixer`, `transport`, `plugins`, `general`,
  `patterns`, `playlist`, `arrangement`, `ui`, `device`, `midi`, `flpianoroll`)
  backed by an in-memory project model: channels, mixer tracks, patterns, a score.
- A test fixture that injects those into `sys.modules`, imports the controller
  script and the pyscript, and drives them through the real JSON files in a
  `tmp_path`.
- `pytest` suite covering dispatch, every handler, and the full command round trip.
- GitHub Actions running `ruff check .` and `pytest` on macOS and Windows.
- A manual smoke test checklist (`docs/SMOKE_TEST.md`) for verifying against real
  FL Studio, since CI can never cover the FL side.

**Done when:** `pytest` passes on a machine with no FL Studio, and CI is green.

---

## Phase 1: Transport correctness

Fixes the audit's structural bug 1 and the error handling that hides everything.

| Item | Change |
| --- | --- |
| Request correlation | every command carries an `id`; the response echoes it; mismatched responses are ignored, not consumed |
| Atomic writes | responses written to a temp file then `os.replace`, so the poller never reads a half-written file |
| Error propagation | `dispatch_command` returns `success: False` on unknown actions and exceptions; tools raise `ToolError` instead of returning `"Error: ..."` strings |
| Real liveness check | a `ping` action; `fl_connect` reports success only when FL answers, not when a port opens |
| Own the MIDI port | the server creates its own virtual port named "FL Studio MCP" via `mido.open_output(name, virtual=True)`, verified working on macOS 2026-09-19. This removes the IAC Driver setup step entirely on macOS, and the same call works on Linux via ALSA. Windows has no virtual MIDI API, so loopMIDI stays required there |
| Safe port selection | never fall back to "first available port"; match the server's own virtual port, or a configured one, so trigger notes cannot hit real hardware |
| Required parameters | handlers reject missing `track` / `index` instead of silently defaulting to 0 and editing the Master track |
| Settings path override | `FL_STUDIO_MCP_SETTINGS_DIR` env var, plus OneDrive-redirected Documents detection on Windows (upstream issue #2) |
| Batching | `fl_batch([...])` executes many commands from one trigger. Note the motivation is atomicity and undo grouping, not speed: once the poll interval is fixed a round trip is about 1ms, so a 16 note pattern already costs roughly 16ms |
| Undo grouping | batches wrap in `general.saveUndo()` so one AI edit is one Ctrl+Z |
| Edit safety | check `general.safeToEdit()` before mutating; refuse rather than corrupt |

**Done when:** a forced timeout followed by a second command executes that second
command exactly once, proven by a test.

---

## Phase 2: Piano roll targeting and verification

Fixes structural bug 2. Uses machinery already in the repo.

- Add a `channel` argument to every piano roll tool. Before triggering, route
  through the controller script to `channels.selectOneChannel(channel)` and
  `ui.showWindow(midi.widPianoRoll)`, so notes land in a known place.
- Correlate by request ID and actually read the pyscript's `mcp_response.json`,
  which it already writes and the server currently ignores.
- Replace the fixed 2 second sleep with polling against a timeout.
- Report trigger failure honestly: check the `osascript` exit code instead of
  always returning `True`.
- Do not let failed requests accumulate in the queue file, where they all replay
  on the next success and duplicate notes.
- `fl_get_piano_roll_state` refreshes the state before reading rather than
  returning a stale file.

**Done when:** `fl_send_notes(channel=3, ...)` either reports the notes landed on
channel 3, verified by read-back, or reports a specific failure. No silent success.

---

## Phase 3: API breadth

Straight coverage work. All verified present in stubs v37.

| Area | Functions |
| --- | --- |
| Patterns | `patternCount`, `patternNumber`, `selectPattern`, `jumpToPattern`, `clonePattern`, `findFirstNextEmptyPat`, `setPatternName`, `setPatternColor`, `getPatternLength`, `getPatternName`, `getPatternColor` |
| Undo | `saveUndo`, `undo`, `restoreUndo`, `restoreUndoLevel`, `getUndoHistoryCount`, `getUndoHistoryPos`, `getUndoLevelHint` |
| Tempo | read via `mixer.getCurrentTempo()`; write via `general.processRECEvent` with `midi.REC_Tempo` (see spike T1) |
| Mixer EQ | `getEqBandCount`, `getEqGain`, `setEqGain`, `getEqFrequency`, `setEqFrequency`, `getEqBandwidth`, `setEqBandwidth` |
| Routing | `setRouteTo`, `getRouteSendActive`, `setRouteToLevel`, `getRouteToLevel`, `linkChannelToTrack`, `linkTrackToChannel` |
| Metering | `mixer.getTrackPeaks(index, mode)`, `mixer.getLastPeakVol`, `channels.getActivityLevel` |
| Channels | `getChannelType`, `getChannelPitch`, `setChannelPitch`, `quickQuantize`, `getGridBitWithLoop`, `isGridBitAssigned` |
| Playlist | `trackCount`, `getTrackName`, `setTrackName`, `getTrackColor`, `setTrackColor`, `muteTrack`, `soloTrack`, `isTrackMuted`, `isTrackSolo` |
| Arrangement | `addAutoTimeMarker(time, name)`, `getMarkerName`, `jumpToMarker`, `currentTime`, `selectionStart`, `selectionEnd` |
| UI | `showWindow`, `hideWindow`, `getFocused`, `setFocused`, `getSnapMode`, `setSnapMode`, `showNotification` |

Also correct the two wrong claims in the README while doing this:

- "Cannot create patterns" is overstated. `patterns.findFirstNextEmptyPat()`
  selects the next empty pattern, and writing into it is creation in practice.
- Tempo is readable today via `mixer.getCurrentTempo()`.

"Cannot load VST/AU plugins" is genuinely true and stays.

**Done when:** each area has tools, tests against the fake harness, and a line in
the README tool tables.

---

## Phase 4: The FL-native musical layer

This is what makes the fork worth having. The upstream tools are a 1:1 API
wrapper, so the model has to do all note math itself and burns a round trip per
question.

### Expression: write notes FL can actually articulate

`flpianoroll.Note` exposes `number`, `time`, `length`, `velocity`, `pan`, `color`,
`fcut`, `fres`, `group`, `muted`, `pitchofs`, `porta`, `release`, `repeats`,
`selected`, `slide`. The current server writes four of sixteen. Slides, portamento
and per-note filter movement are what make an acid line sound like an acid line,
and no generic MIDI tool writes them. This is the differentiator.

### Context: stop assuming C major 4/4

- `score.snap_root_note` and `score.snap_scale_helper` give the key the producer
  actually set in the piano roll. Generate in that key; offer a "fix out-of-key
  notes" pass.
- `score.tsnum` and `score.tsden` give the real time signature.
- `score.getTimelineSelection()` gives the region the user highlighted, which turns
  every generative tool into "do this to what I selected."

### Ergonomics

- A bars-and-beats time model instead of raw quarter notes, honouring the actual
  time signature.
- Chord entry by symbol (`Cmaj7`, `F#m7b5`) rather than MIDI integers.
- Groove transforms on existing notes: swing, humanize (timing and velocity),
  quantize, accent patterns, crescendo.
- Note groups via `score.getNextFreeGroupIndex()`, so "remove the arpeggio you
  added" is exact instead of matching on pitch and time.
- `fl_describe_project()`: tempo, time signature, key, patterns, channels with
  their plugins, mixer routing, all in one call instead of twenty.
- MIDI file import and export, bridging FL to everything else.

**Done when:** a single call can write a slide-articulated bassline in the
project's real key and meter into a named channel, and read it back.

---

## Phase 5: Gain staging and mix review

The cheap, in-API half of "give it ears." Two functions, real value.

- Sample `mixer.getTrackPeaks` across all tracks during playback to find what
  clips and what never sounds.
- An automated gain staging pass: play, sample, trim the hot tracks.
- A mix review that reads volume, pan, EQ, routing and peaks across the project
  and flags the usual suspects: tracks clipping, everything panned centre, unused
  sends, duplicate routing, channels at unity that were never touched.

**Done when:** `fl_mix_review()` returns actionable findings on a real project.

---

## Phase 6: Curation

The most under-served half. Producers accumulate thousands of ideas and have no
way to find them.

| Feature | Notes |
| --- | --- |
| Riff library | capture the current piano roll as a tagged snippet (key, tempo, instrument, mood), search it later, recall transposed into the current project's key |
| Project snapshots | serialise full project state to JSON, diff two snapshots, answer "what changed since yesterday" and roll back further than FL's undo |
| Plugin state library | all params are readable and writable, so snapshot any plugin as a named preset, recall it, and interpolate between two snapshots |
| Session journal | log every edit the server makes, with timestamps, for review and summary |
| Sample search | `ui.navigateBrowser`, `getFocusedNodeCaption`, `previewBrowserMenuItem`, `selectBrowserMenuItem` make browser-driven search and audition possible; pair with a filesystem scan |
| Project indexing | scan a folder of `.flp` files for tempo, key, plugins used, last modified. PyFLP is read-only and lags FL versions, so best effort with graceful failure |
| Structure critique | pattern lengths plus arrangement markers let the server read and annotate song structure |
| Template scaffolding | cannot load plugins, but can name, colour and route everything, so "set up my mixing template" is instant |

---

## Tabled

Deliberately deferred, not rejected. Recorded here so the decision is recoverable.

- **Loopback audio capture and analysis.** Routing FL's master out through
  BlackHole or VB-Cable, capturing it, and analysing with numpy or librosa for
  LUFS, spectral balance, detected key and tempo. This is the single highest-value
  feature available and the one that would most separate this project from every
  other DAW MCP. Tabled for scope, and because Phase 5 delivers a usable fraction
  of it from inside the API.
- **Reference track matching.** Comparing the user's spectral balance against a
  reference and translating the difference into moves on the mixer EQ. Depends
  entirely on the item above.

## Not possible

Confirmed against the stubs. Do not plan around these.

- **Loading VST/AU plugins.** No API exists.
- **Placing clips in the playlist.** The `playlist` module has no add, insert or
  create function. Only `triggerLiveClip` and performance mode. Full arrangement
  building is therefore out; markers and live clips are the ceiling.
- **Rendering or exporting audio** through the scripting API.

## Research spikes

Timeboxed investigations. Each needs a live FL Studio to resolve. Do not commit
roadmap work that depends on one until the spike lands.

- **T1: Tempo write.** Half resolved. Reading works and the scaling is confirmed
  as thousandths of a BPM (`getCurrentTempo` returned 130000 at 130 BPM). What
  remains is the write path: `general.processRECEvent` with `midi.REC_Tempo` and
  the right flag combination, likely `REC_UpdateValue | REC_UpdateControl`.
- **T2: Step parameters.** `channels.getStepParam` and `setStepParameterByIndex`
  reach the graph editor for per-step velocity, pan, pitch and shift. Several
  arguments are marked "???" in the stubs and need experimentation.
- **T3: Automation clips.** `mixer.automateEvent` is marked "HELP WANTED" upstream
  with the docstring question "What does this do?". If it works, automation
  writing (filter sweeps, risers, volume rides) becomes possible, which would be a
  significant capability. Treat as high risk.
- **T4: SysEx transport.** `device.midiOutSysex` plus an `OnSysEx` callback would
  give a genuine bidirectional channel with no filesystem and no keystroke, which
  removes the focus-stealing and the Accessibility permission requirement. Cost is
  asking the user to also enable the virtual port as a MIDI *output* in FL. If this
  works it supersedes much of Phase 1's file plumbing, so spike it early.

---

## Suggested order

Phase 0, then 1, then 2, are sequential and non-negotiable: the harness enables
TDD, the transport must be correct before features stack on it, and the piano roll
is the headline feature that is currently unverifiable.

After that, Phase 3 is broad and parallelisable, Phase 4 is where the project
becomes distinctive, and Phases 5 and 6 are independent of each other.

Run spike T4 during Phase 0, because a positive result changes Phase 1's design.
