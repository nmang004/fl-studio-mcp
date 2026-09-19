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
src/fl_studio_mcp/server.py           FastMCP entry point
src/fl_studio_mcp/tools/              channels, mixer, transport, plugins, piano_roll
src/fl_studio_mcp/utils/              connection, midi_connection, fl_trigger
install.sh / install.ps1              one-command installers
ROADMAP.md                            the spec
docs/MASTER_PROMPT.md                 session-bootstrapping brief
docs/plans/                           per-phase implementation plans
```

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

Known-good facts, verified against stubs v37.0.1:

- `mixer.getCurrentTempo()` reads tempo. Writing tempo goes through
  `general.processRECEvent` with `midi.REC_Tempo`, flags and scaling unverified.
- `patterns.findFirstNextEmptyPat()` exists, so pattern creation is possible in
  practice despite the upstream README saying otherwise.
- `playlist` has no clip placement function. Arrangement building is out.
- `plugins` cannot load plugins, only control loaded ones. This limit is real.
- `flpianoroll.Note` has sixteen properties including `slide`, `porta`, `pitchofs`,
  `fcut`, `fres`. The server currently writes four.
- `score.snap_root_note` and `score.snap_scale_helper` expose the user's key;
  `score.tsnum` and `score.tsden` the time signature.

## Style rules

- No em dashes and no en dashes anywhere: code, comments, docs, UI strings, commit
  messages. Use commas, colons, full stops, or rewrite.
- No emoji.
- No AI or assistant attribution in commits, PRs, READMEs, or anything shipped.
- `ruff check .` clean and `pytest` green before committing.
- Keep commits scoped to one concern so fixes stay cherry-pickable to upstream.
