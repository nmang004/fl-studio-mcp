# CLAUDE.md

Context for Claude Code sessions in this repo. For the full working brief, see
`docs/MASTER_PROMPT.md`. For what we are building and why, see `ROADMAP.md`.

## What this is

An MCP server that lets an AI assistant drive FL Studio. This is a fork of
`karl-andres/fl-studio-mcp`, configured as the `upstream` remote. The fork exists
to fix the transport, make the piano roll path verifiable, and build a genuinely
FL-native musical layer on top. `ROADMAP.md` is the spec.

## Architecture: two paths, and why

FL Studio exposes Python through two sandboxes that cannot see each other.

**Path 1, the MIDI controller script.** `fl_controller/device_FLStudioMCP.py` runs
inside FL and can import `channels`, `mixer`, `transport`, `plugins`, `general`,
`patterns`, `playlist`, `arrangement`, `ui`, `device`, `midi`. The server writes a
command to `mcp_command.json`, sends MIDI note 127 as a trigger, the script
executes and writes `mcp_response.json`, the server polls for it. Files live in
`~/Documents/Image-Line/FL Studio/Settings/Hardware/FLStudioMCP/`.

**Path 2, the piano roll script.** `scripts/ComposeWithLLM.pyscript` runs in a
different sandbox whose only FL module is `flpianoroll`. It is the only way to
write persistent notes. It is triggered by a keystroke (Cmd+Opt+Y on macOS,
Ctrl+Alt+Y on Windows) rather than MIDI. Files live in
`.../Settings/Piano roll scripts/`.

The split is forced by FL, not a design choice. `flpianoroll` does not exist in
path 1, and `channels` does not exist in path 2.

Neither sandbox has `__file__`, a full stdlib, package installation, or a
debugger. FL's View > Script output window is the only FL-side logging surface.

## Layout

```
fl_controller/device_FLStudioMCP.py   runs inside FL, path 1
scripts/ComposeWithLLM.pyscript       runs inside FL, path 2
scripts/dev_verify_connection.py      read-only live check, run it first
src/fl_studio_mcp/server.py           FastMCP entry point, 101 tools
src/fl_studio_mcp/tools/              24 tool families
src/fl_studio_mcp/musical/            theory, groove, chords, riffs, snapshots
src/fl_studio_mcp/utils/              connection, midi_connection, fl_trigger, paths
tests/fakes/                          in-memory FL that the real scripts load against
ROADMAP.md                            the spec, with the verified-live table
docs/MASTER_PROMPT.md                 session-bootstrapping brief
docs/SMOKE_TEST.md                    the manual checks CI cannot do
docs/plans/                           per-phase implementation plans
```

The fakes load the real controller and piano roll scripts, so tests exercise the
shipped code rather than a copy. The standing caution, stated in every phase plan:
a fake agreeing with the code proves nothing. Live checks are the real evidence.

## Commands

```bash
uv sync --dev              # install, including the FL API stubs
uv run fl-studio-mcp       # run the server
uv run pytest              # tests (must pass with no FL Studio running)
uv run ruff check .        # lint, must be clean before commit
uv run ruff check --fix .
```

## The FL Studio API is the hard part

It is poorly documented and inconsistently versioned, and its own official stubs
contain entries marked "HELP WANTED" and parameters documented as "???". Failures
are silent: code imports fine and does nothing.

Never claim an FL API behaves a certain way without either reading it in the stubs
or observing it in a running FL Studio, and say which one. The stubs are the dev
dependency `fl-studio-api-stubs`; unpack the wheel and grep it.

`ROADMAP.md` has the full verified table. These are the ones that cost real time
to rediscover, so read them before touching the relevant area.

**The sandbox blocks whole syscalls, not just writes.** In the controller script,
`Path.mkdir`, `os.makedirs`, `os.replace`, `os.rename`, `os.remove`, `Path.unlink`,
`Path.glob` and the builtin `open()` all raise `SystemError`. `Path.write_text`,
`Path.read_text`, `Path.exists`, `Path.is_dir`, `Path.stat`, `Path.iterdir` and
`Path.home` work. A blocked call at module scope stops the script importing at
all, so FL never loads it and every command times out, which looks exactly like FL
not being open. Atomic writes are impossible here; the reader tolerates catching a
file mid write instead.

The piano roll sandbox differs: `os.replace` is still blocked, but the builtin
`open()` does work there. An error surfaces as a dialog with a traceback.

**`patterns.findFirstNextEmptyPat` freezes FL Studio.** Measured twice on build
5406, with and without the prompt flag. The window stops responding and the call
never returns. Pattern creation and cloning refuse rather than call it. Do not try
it again.

**The plugin stubs disagree with the runtime.** `getParamValueString` takes four
parameters, not five, and `setParamValue` needs five positional arguments with its
first named `paramValue`. A probe action asks the running build rather than
trusting the stubs.

**The piano roll's marker accessors are a silent no-op.** `score.markerCount` and
`getMarker` exist, raise nothing, and report zero markers in an arrangement holding
three. The plumbing was deleted rather than shipped.

**Undo cannot be grouped.** `general.undo()` is a toggle, so two calls undo then
redo. `general.undoUpDown(-n)` is the real relative move. `saveUndo` adds no
history entry and does not reduce the undo count, so it is not called.

**A piano roll script must be bound to its keystroke by hand** inside FL. Nothing
in this repo can do it, and until it is done every piano roll tool times out.

**A virtual MIDI port exists only while a process holds it**, which is why FL
cannot list the controller after a restart if nothing is running.

Verified working: tempo write via `general.processRECEvent(midi.REC_Tempo, value,
17)` where value is thousandths of a BPM; all sixteen `flpianoroll.Note`
properties; `score.snap_root_note` and `snap_scale_helper` for the user's key,
`tsnum` and `tsden` for the time signature. Note `pan` defaults to 0.5, not 0.0,
and is not the same scale as `channels.getChannelPan`.

Genuinely impossible: loading VST or AU plugins, placing clips in the playlist,
rendering audio.

## Style rules

- No em dashes and no en dashes anywhere: code, comments, docs, UI strings, commit
  messages. Use commas, colons, full stops, or rewrite.
- No emoji.
- No AI or assistant attribution in commits, PRs, READMEs, or anything shipped.
- `ruff check .` clean and `pytest` green before committing.
- Keep commits scoped to one concern so fixes stay cherry-pickable to upstream.
