# Phase 6: Curation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** the producer's material becomes findable. Riffs, presets and project states
are captured, searched, compared and recalled, and every edit the server makes is
recorded.

**Architecture:** four layers, split so the decisions are testable with no FL Studio.

The library lives on the host, under one root, as plain JSON records and a JSONL
journal. Producers already have file managers, backups and diff tools, and a format
that those cannot read is a format that gets lost. Records carry a schema number so a
later change can migrate rather than guess.

The logic is pure. Matching a riff against a query, transposing its notes, diffing two
project states, deciding which fader moves a restore needs, interpolating two preset
snapshots, reading sections out of markers: all arithmetic over dictionaries, so all of
it is tested against fixtures with no FL Studio running.

The controller gains only what cannot be done from the host: the plugin calls whose
arguments are currently wrong, paged parameter reads, the browser's focused node, and
audition. Everything a snapshot needs already exists and is reached through
`system.batch`, which was measured live: 25 commands in one trigger, 12 ms, 10.7 KB of
reply.

The journal hooks the host's single choke point, `FLConnection.send_command`, so no
edit can bypass it, and it is gated on one canonical list of mutating actions that a
test pins against the controller's own copy.

**Tech Stack:** the Phase 0 harness, the Phase 1 transport, the Phase 3 readers, the
Phase 4 musical helpers, the Phase 5 session shape, pytest 9, ruff 0.16.

**Spec:** `ROADMAP.md` Phase 6, read against the "Tabled" and "Not possible" sections.

## Global Constraints

Copied from ROADMAP.md, and implicitly part of every task:

- Python `>=3.10`, ruff `target-version = "py310"`, `ruff check .` clean, line length
  100, rules `E`, `F`, `I`, `W`.
- `pytest` green with no FL Studio running.
- macOS and Windows must both keep working. No POSIX-only path handling: `pathlib`
  throughout, no `os.fork`, no shelling out.
- No em dashes, no en dashes, no emoji anywhere. No AI attribution.
- Commits scoped to one concern.
- Do not disrupt the open project. Reading is free. Every new write path reports
  before it applies, and applying requires the caller to ask.
- No new runtime dependency. The library is JSON and the audio metadata reader is
  ours; see the indexing task for why a third party `.flp` parser was weighed and
  rejected.
- Nothing under the user's home is written except inside the library root, and tests
  never write there at all.

### What this phase is, and what it refuses to fake

Every line below is read from the stubs (v37.0.1), not assumed. Paths are relative to
`.venv/lib/python3.13/site-packages/`.

| The wish | What the API actually has |
| --- | --- |
| Search FL's browser | Nothing. No search, filter or search-field setter exists. Searched every stub package for `*Search*`, `*Find*`, `*Query*`, `*Filter*` |
| Know what a browser node is | `ui.getFocusedNodeCaption()` returns a caption, `ui.getFocusedNodeFileType()` an int whose constants are not in the stubs. No path, no folder flag, no child count (`ui/__browser.py:116-141`) |
| Load a browser item into a channel | Not present. No load, add, or insert function in `channels`, `mixer` or `playlist` |
| Select a browser item | `ui.selectBrowserMenuItem()` exists, and its own stub warns it "appears to open the File menu, rather than navigating the browser" (`ui/__browser.py:108-110`). Not shipped |
| Walk the browser | `ui.navigateBrowser(40, False)` steps previous, `(41, False)` next, `ui.navigateBrowserTabs(midi.FPT_Left or FPT_Right)`, and `ui.toggleBrowserNode(1/0/-1)` expands. The stub warns navigateBrowser "doesn't seem to work very reliably, at least on my machine" (`ui/__browser.py:26`) |
| Audition | `ui.previewBrowserMenuItem()` plays whatever is highlighted (`ui/__browser.py:93-97`). There is no stop |
| Load or save a plugin preset | Nothing. `plugins` has `getPresetCount`, `nextPreset`, `prevPreset` and no by-name or by-index load (`plugins/__init__.py:480-554`) |
| Name a plugin | `plugins.getPluginName(index, slotIndex, userName, useGlobalIndex)`. No vendor, format, version or path exists anywhere in the stubs |
| Plugin parameters | Normalised 0.0 to 1.0 only (`plugins/__init__.py:222`, `:247`). A VST reports 4240 of them, 4096 real plus 128 CC and 16 aftertouch, and the unused ones are readable with an empty name (`:44-46`, `:138-141`) |
| Plugin state | Reading and writing every parameter is the only route. There is no chunk, blob, FXP or FST function |
| Playlist clips | `playlist` exposes tracks and live performance state only. Nothing reads or writes a clip |
| Piano roll notes | The other sandbox. Reachable only through the request file and the keystroke path |

Two consequences run through the whole phase. Sample search is a filesystem feature
with a thin audition step, because that is what the API allows, and a snapshot cannot
contain notes or clips, because those are not reachable from the path that reads it.
Both are stated in the tools' own descriptions rather than discovered by the caller.

### Four defects this phase starts by fixing

The plugin path has been calling FL functions with the wrong argument order since it
was written. The stubs give the real signatures, and Python's positional arguments
silently landed on the wrong names:

| Call | Real signature | What the controller passes | Effect |
| --- | --- | --- | --- |
| `plugins.getPluginName` | `(index, slotIndex=-1, userName=False, useGlobalIndex=False)` (`plugins/__init__.py:89`) | `(index, slot, use_global)` (`device_FLStudioMCP.py:2097`) | `userName` is set instead, so the tool reports the user's name for the plugin, never the plugin's own name |
| `plugins.getParamValueString` | `(paramIndex, index, slotIndex=-1, pickupMode=midi.PIM_None, useGlobalIndex=False)` (`:272`) | `(i, index, slot, use_global)` (`:2136`) | `pickupMode` is set and `useGlobalIndex` never is |
| `plugins.setParamValue` | `(value, paramIndex, index, slotIndex=-1, pickupMode=0, useGlobalIndex=False)` (`:233`) | `(value, i, index, slot, use_global)` (`:2189`) | every parameter write carries a pickup mode the caller never chose |
| `plugins.getColor` | `(index, slotIndex=-1, flag=midi.GC_BackgroundColor, useGlobalIndex=False)` (`:312`) | `(index, slot, use_global)` (`:2258`) | the flag becomes 1, which is `GC_Semitone`, so the default call asks for the wrong colour |

The fakes mirror the wrong signatures, so the suite agrees with the bug. This is the
Phase 4 lesson at its sharpest: a fake written from the same understanding as the code
cannot correct that understanding. The fix is earned by changing the fakes first,
watching the controller fail, then fixing the controller.

## Commit map

| Sub-phase | What it delivers | Commits |
| --- | --- | --- |
| A | Library root, canonical action list, session journal | 4 |
| B | Riff library: capture, search, recall transposed | 4 |
| C | Project snapshots: capture, diff, restore | 4 |
| D | Plugin calls fixed, presets, interpolation | 5 |
| E | Sample search and browser audition | 3 |
| F | Project indexing, structure critique, templates | 4 |
| G | Documentation and exit criteria | 1 |

---

## Sub-phase A: the library root and the session journal

### Task A1: One root, plain JSON, safe ids

**Files:**
- Create: `src/fl_studio_mcp/utils/store.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Produces:
  - `library_root() -> Path`, `FL_STUDIO_MCP_HOME` wins, default `~/.fl_studio_mcp`.
  - `library_dir(kind: str) -> Path`, creating it. Kinds are `riffs`, `presets`,
    `snapshots`.
  - `new_record_id(name: str, when: datetime | None = None) -> str`, a sortable id.
  - `safe_record_id(record_id: str) -> str | None`, `None` when the id could escape
    the library directory.
  - `write_record(kind, record_id, payload) -> Path`, `read_record(kind, record_id)`,
    `list_records(kind, limit=None) -> dict`, `delete_record(kind, record_id) -> bool`.

Record ids come from a model, so they are untrusted input: `../../.ssh/authorized_keys`
must not be writable through a riff name. This is the one security-relevant decision in
the phase and it gets its own tests.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_store.py
"""The library is plain JSON under one root, and record ids are untrusted input."""

def test_the_root_can_be_moved(monkeypatch, tmp_path):
    monkeypatch.setenv("FL_STUDIO_MCP_HOME", str(tmp_path / "lib"))
    assert store.library_root() == tmp_path / "lib"


def test_a_record_round_trips(tmp_path, monkeypatch):
    ...
    path = store.write_record("riffs", "2026-09-19-120000-thing", {"schema": 1, "name": "thing"})
    assert path.is_file()
    assert store.read_record("riffs", "2026-09-19-120000-thing")["name"] == "thing"


def test_an_id_that_escapes_the_library_is_refused(tmp_path, monkeypatch):
    for bad in ("../evil", "a/b", "..", ".hidden", "", "a\\b"):
        assert store.safe_record_id(bad) is None


def test_a_refused_id_is_not_written_anywhere(tmp_path, monkeypatch):
    """The point of the check: no file appears outside the library directory."""
    ...


def test_an_unreadable_record_is_reported_not_raised(tmp_path, monkeypatch):
    """One bad file must not hide the rest of the library."""
    ...


def test_records_list_newest_first(tmp_path, monkeypatch):
    ...
```

- [ ] **Step 2: Run and watch them fail**

Run: `uv run pytest tests/test_store.py -v`
Expected: `ModuleNotFoundError: fl_studio_mcp.utils.store`.

- [ ] **Step 3: Implement**

Write in place with a temporary file plus `os.replace`, which the host may use. The
sandboxes may not, which is why the controller writes differently, and the docstring
says so. `list_records` returns `{"records": [...], "skipped": [...]}` so a corrupted
file is visible rather than fatal.

- [ ] **Step 4: Green, whole suite, lint**

- [ ] **Step 5: Commit**

```bash
git commit -m "Add a JSON library root with safe record ids"
```

### Task A2: One canonical list of what mutates

**Files:**
- Create: `src/fl_studio_mcp/utils/actions.py`
- Modify: `fl_controller/device_FLStudioMCP.py` (only if the lists disagree)
- Test: `tests/test_actions.py`

**Interfaces:**
- Produces: `MUTATING_ACTIONS: frozenset[str]` on the host, and a test that parses the
  controller's own `MUTATING_ACTIONS` and asserts the two sets are equal.

The journal cannot ask FL whether an action mutates without paying a round trip per
command. The host needs the answer before the command is sent, so the list exists in
two places by necessity, exactly like the settings path in `utils/paths.py`. The test
that pins them together is what makes two copies safe.

- [ ] **Step 1: Write the failing test**

```python
def test_the_host_and_the_controller_agree_on_what_mutates():
    """Two copies of a list drift. This is the test that stops them."""
    controller = Path("fl_controller/device_FLStudioMCP.py").read_text()
    block = controller.split("MUTATING_ACTIONS = frozenset([", 1)[1].split("])", 1)[0]
    names = set(re.findall(r'"([^"]+)"', block))
    assert names == set(actions.MUTATING_ACTIONS)
```

- [ ] **Step 2: Run and watch it fail, then implement, then green**

- [ ] **Step 3: Commit**

```bash
git commit -m "Keep one canonical list of mutating actions"
```

### Task A3: The journal, on the single path every command takes

**Files:**
- Create: `src/fl_studio_mcp/utils/journal.py`
- Modify: `src/fl_studio_mcp/utils/connection.py`
- Test: `tests/test_journal.py`

**Interfaces:**
- Produces:
  - `is_enabled() -> bool`, false when `FL_STUDIO_MCP_JOURNAL` is `0`.
  - `record(action, params, result, duration_ms, session=None) -> None`, never raises.
  - `journal_path(when=None) -> Path`, one file per day under `journal/`.
  - `read_entries(since=None, action=None, limit=100) -> dict` with `entries`, `errors`,
    `total`, `truncated`.
  - `summarise(entries) -> dict`: counts by action, failures, first and last timestamp.
  - `last_error() -> str | None`, so a broken journal is visible instead of silent.
- Consumes: Task A2's list.

Properties that matter, each with a test:

- A mutating command is journaled with its action, params, timestamp and outcome.
- A read-only command is not journaled, or the journal becomes a log of questions.
- A failed command is journaled with its error, because "what did the server try" is
  as important as what it did.
- A journal that cannot be written does not break the command it was recording. This
  is the most important behaviour in the task: losing a log line is acceptable, losing
  a fader move because the log failed is not.
- `system.batch` is one entry naming every command it carried, so a batched edit is
  not invisible.
- `FL_STUDIO_MCP_JOURNAL=0` turns it off entirely and nothing is written.
- The session id is stable within one process, so "this session" is answerable.

- [ ] **Step 1: Write the failing tests** (the seven behaviours above, against a tmp
      library root)
- [ ] **Step 2: Run and watch them fail**
- [ ] **Step 3: Implement, hooking `FLConnection.send_command`**

The hook wraps the MIDI call, times it, and journals after the reply arrives. It must
not journal before the result is known, and it must not hold the lock longer than the
command itself needs.

- [ ] **Step 4: Green, whole suite, lint**

The whole suite must also be checked for the opposite failure: an autouse conftest
fixture points `FL_STUDIO_MCP_HOME` at a temporary directory, so no test can write to
the real `~/.fl_studio_mcp`. A test asserts that a mutating command inside the suite
writes its journal line under the temporary root.

- [ ] **Step 5: Commit**

```bash
git commit -m "Record every edit the server makes, and never fail a command over it"
```

### Task A4: The journal tools

**Files:**
- Create: `src/fl_studio_mcp/tools/journal.py`
- Test: `tests/test_journal_tools.py`

**Interfaces:**
- Produces: `fl_journal(since=None, action=None, limit=50)` and
  `fl_journal_summary(since=None)`.

- [ ] **Step 1: Write the failing tests**

- `fl_journal` returns entries newest first and says when it truncated.
- `fl_journal` with an action filter returns only that action.
- `fl_journal` with no journal at all returns an empty list and a note, not an error:
  a fresh install has never edited anything.
- `fl_journal_summary` counts by action and reports failures separately.
- Neither tool sends a command to FL, so both work with FL closed.
- A broken journal file is reported through `last_error` rather than raising.

- [ ] **Step 2: Run, watch them fail, implement, green**

- [ ] **Step 3: Commit**

```bash
git commit -m "Add the journal tools"
```

---

## Sub-phase B: the riff library

### Task B1: Riff records, matching and transposition, as pure functions

**Files:**
- Create: `src/fl_studio_mcp/musical/riffs.py`
- Test: `tests/test_riffs.py`

**Interfaces:**
- Produces:
  - `make_riff(name, notes, context, instrument=None, tags=(), mood=None, when=None) -> dict`
  - `match(record, query=None, tags=(), key=None, instrument=None, min_notes=None) -> bool`
  - `search(records, **filters) -> list[dict]`, newest first
  - `transpose_semitones(from_root, to_root, direction="nearest") -> int`
  - `transpose_notes(notes, semitones, low=0, high=127) -> tuple[list[dict], int]`
    returning the moved notes and how many were clamped
  - `summarise(record) -> dict`, the shape search results are returned in

A riff record holds the notes exactly as the piano roll reported them, all sixteen
properties, so a recall preserves expression rather than flattening it. It also holds
what makes it findable: key, meter, tempo, the channel and plugin it came from, and the
tags the producer chose.

Tests: a note outside 0 to 127 after transposition is clamped **and counted**, never
silently dropped; `direction="nearest"` never moves more than six semitones; a query
matches on name, tag, key or instrument; a query that matches nothing returns nothing
rather than everything; tags match case-insensitively; an empty tag list does not
filter anything out.

- [ ] **Step 1: Write the failing tests**

```python
def test_transposing_down_is_never_more_than_six_semitones():
    """Nearest, not upwards: an eleven semitone jump is a different part."""
    assert riffs.transpose_semitones(0, 11) == -1
    assert riffs.transpose_semitones(11, 0) == 1


def test_a_clamped_note_is_counted_not_dropped():
    notes = [{"midi": 120, "time": 0, "duration": 96}]
    moved, clamped = riffs.transpose_notes(notes, 12)
    assert moved[0]["midi"] == 127
    assert clamped == 1
```

- [ ] **Step 2: Run and watch them fail**
- [ ] **Step 3: Implement, green**
- [ ] **Step 4: Commit**

```bash
git commit -m "Add riff records, matching and transposition as pure functions"
```

### Task B2: Save what is in the piano roll

**Files:**
- Create: `src/fl_studio_mcp/tools/riffs.py` (registered from `server.py`)
- Test: `tests/test_riff_tools.py`

**Interfaces:**
- Produces: `fl_save_riff(name, tags=None, mood=None, channel=None)`.
- Consumes: Task A1's store, Task B1's `make_riff`, `piano_roll.refresh_and_read_state`,
  `score.read_context`, the controller's channel and tempo readers.

- [ ] **Step 1: Write the failing tests**

- Saving captures the notes the piano roll actually holds, not a cached copy.
- The record carries the project's key, meter and tempo, and the channel's name and
  plugin name when a channel is given.
- A save with an empty piano roll is refused with a reason, because an empty riff in a
  library is noise.
- A save whose name produces an unsafe id is refused rather than written outside the
  library.
- Saving does not mutate the project: no write action reaches FL.
- Tags and mood are stored as given and searchable afterwards.

- [ ] **Step 2: Run, watch them fail, implement, green**
- [ ] **Step 3: Commit**

```bash
git commit -m "Save the current piano roll as a tagged riff"
```

### Task B3: Find a riff again

**Files:**
- Modify: `src/fl_studio_mcp/tools/riffs.py`
- Test: `tests/test_riff_tools.py`

**Interfaces:**
- Produces: `fl_find_riffs(query=None, tags=None, key=None, instrument=None, limit=20)`.

- [ ] **Step 1: Write the failing tests**

- A search returns the summary shape, not whole note lists: a search result has to fit
  in a context window.
- An empty library returns an empty list and a note saying so.
- A search that matches nothing says what was searched for, so the caller can loosen it.
- The current project's key is included in the reply when it is known, so a caller can
  see which riffs are already in key.

- [ ] **Step 2: Run, watch them fail, implement, green**
- [ ] **Step 3: Commit**

```bash
git commit -m "Search the riff library"
```

### Task B4: Recall, transposed into this project

**Files:**
- Modify: `src/fl_studio_mcp/tools/riffs.py`
- Test: `tests/test_riff_tools.py`

**Interfaces:**
- Produces:
  `fl_recall_riff(riff, channel=None, transpose=True, direction="nearest", mode="replace", verify=True)`.

- [ ] **Step 1: Write the failing tests**

- Recall writes the riff's notes into the named channel through the piano roll path,
  and the notes kept their velocity, pan and articulation flags.
- With `transpose=True` the notes come back in the project's key, and the reply says
  how far they moved.
- With the project's key unknown and `transpose=True`, the recall is refused rather
  than guessing a key.
- Clamped notes are reported by count in the reply.
- `mode="replace"` clears first, `mode="append"` does not.
- The reply names the channel the notes landed on.
- Nothing is written when the target channel cannot be selected.

- [ ] **Step 2: Run, watch them fail, implement, green**
- [ ] **Step 3: Verify live, with the user's permission**: save a riff from the open
      project, search for it, then recall it into a scratch pattern. Record what came
      back, including the transposition and any clamping. A riff recall writes notes,
      so this needs the user's agreement, and it is done in a new pattern so their
      existing material is untouched.
- [ ] **Step 4: Commit**

```bash
git commit -m "Recall a riff into the current project's key"
```

---

## Sub-phase C: project snapshots

### Task C1: Flatten, diff and plan a restore, as pure functions

**Files:**
- Create: `src/fl_studio_mcp/musical/snapshots.py`
- Test: `tests/test_snapshots.py`

**Interfaces:**
- Produces:
  - `flatten(snapshot, prefix="") -> dict[str, Any]`, dotted paths to scalars.
  - `diff(before, after, limit=200) -> dict` with `added`, `removed`, `changed`,
    `counts` and `truncated`.
  - `summarise_diff(diff) -> dict`, the sentence a producer reads first.
  - `restore_commands(snapshot, current, limit=500) -> dict` with `commands`,
    `unrestorable`, `counts`. Commands are `{"action", "params"}` dicts ready for
    `fl_batch`.

The diff is over dotted paths so a change reads as
`mixer.tracks.3.volume: 0.8 -> 0.65` rather than as two blobs a caller has to compare
itself. The restore planner is the inverse and knows what cannot be put back: notes,
playlist clips and the plugin list are not in a snapshot, and markers can be added but
never removed, so a marker that appeared since the snapshot is listed as unrestorable
rather than silently left.

Tests: an added, removed and changed path each appear in the right bucket; a diff of a
snapshot against itself is empty; a restore of a snapshot against itself produces no
commands; a value with no writer is reported as unrestorable instead of being planned;
the command cap is reported when it truncates.

- [ ] **Step 1: Write the failing tests**
- [ ] **Step 2: Run and watch them fail**
- [ ] **Step 3: Implement, green**
- [ ] **Step 4: Commit**

```bash
git commit -m "Add snapshot flattening, diffing and restore planning as pure functions"
```

### Task C2: Capture the project

**Files:**
- Create: `src/fl_studio_mcp/tools/snapshots.py`
- Test: `tests/test_snapshot_tools.py`

**Interfaces:**
- Produces: `fl_snapshot_project(label=None, include_plugins=False, include_eq=True)`.
- Consumes: `system.batch`, Task A1's store, Task C1's `flatten`.

Readings, all in one batch: `system.getInfo`, `patterns.getAll`, `channels.getAll`,
`mixer.getSnapshot`, `playlist.getAll`, `arrangement.getMarkers`, one `mixer.getEq` per
track, and when `include_plugins` is set, one paged `plugins.getParams` per loaded
plugin. Measured live: the batch without plugins is 25 commands, 12 ms, 10.7 KB.

- [ ] **Step 1: Write the failing tests**

- The snapshot is one round trip regardless of track count, asserted by counting
  triggers.
- The snapshot records the tempo, the key and meter, every mixer track's volume, pan,
  mute, solo, name, colour, stereo separation and sends, and every channel's name,
  colour, volume, pan and target.
- `include_plugins=False` sends no plugin command, because a full parameter read of a
  VST is 4240 values.
- A snapshot with no label is still storable and its id says when it was taken.
- The reply says what a snapshot cannot contain, so nobody expects notes back.

- [ ] **Step 2: Run, watch them fail, implement, green**
- [ ] **Step 3: Commit**

```bash
git commit -m "Snapshot the project's settings in one round trip"
```

### Task C3: What changed since yesterday

**Files:**
- Modify: `src/fl_studio_mcp/tools/snapshots.py`
- Test: `tests/test_snapshot_tools.py`

**Interfaces:**
- Produces: `fl_project_changes(since=None, against=None, include_plugins=False)`.

Three shapes, one question: compare the live project against a stored snapshot (by id,
or the newest before `since`), or compare two stored snapshots against each other.

- [ ] **Step 1: Write the failing tests**

- Comparing live against a stored snapshot reports the changes and names the snapshot.
- `since` picks the newest snapshot at or before that time, which is what "since
  yesterday" means.
- With no snapshots at all the reply says so and names the tool that makes one.
- Two stored snapshots can be compared without touching FL at all, asserted by
  counting triggers.
- The reply distinguishes settings changes from things that cannot be compared, such
  as notes.

- [ ] **Step 2: Run, watch them fail, implement, green**
- [ ] **Step 3: Commit**

```bash
git commit -m "Report what changed since a stored snapshot"
```

### Task C4: Roll back further than undo

**Files:**
- Modify: `src/fl_studio_mcp/tools/snapshots.py`
- Test: `tests/test_snapshot_tools.py`

**Interfaces:**
- Produces: `fl_restore_snapshot(snapshot=None, apply=False, include_plugins=False)`.

- [ ] **Step 1: Write the failing tests**

- With `apply=False` the reply lists the moves and the project is untouched, asserted
  on the fake project state.
- With `apply=True` the moves go through `fl_batch` under one name, so one undo
  reverses them, and the project ends up matching the snapshot.
- A restore with nothing to do says so and does not send a batch.
- Unrestorable differences are reported separately and do not silently vanish from the
  plan.
- A restore never clears the piano roll, even though the snapshot has no notes in it.

- [ ] **Step 2: Run, watch them fail, implement, green**
- [ ] **Step 3: Verify live, with the user's permission**: snapshot the open project,
      make one small, named change, then diff and restore, and confirm the project is
      back where it started. The change is made and reversed in the same run, and the
      user is told exactly which fader will move before it moves.
- [ ] **Step 4: Commit**

```bash
git commit -m "Restore a stored snapshot through one batch"
```

---

## Sub-phase D: plugin presets

### Task D1: Call FL with the arguments FL actually declares

**Files:**
- Modify: `tests/fakes/modules/plugins.py` first, then
  `fl_controller/device_FLStudioMCP.py`
- Test: `tests/test_plugin_signatures.py`

**Interfaces:**
- Produces: corrected calls in the controller, corrected fakes, and a test that pins
  the argument order for the four broken functions.

- [ ] **Step 1: Write the failing tests against corrected fakes**

The fakes are changed to the real stub signatures first. That is what makes the
existing controller fail, and the failure is the evidence that the bug is real. The
test file asserts the four behaviours a producer would notice:

```python
def test_the_plugin_name_is_the_plugin_name_not_the_user_name(fl_env):
    """plugins.getPluginName's third argument is userName, not useGlobalIndex.

    The controller passed use_global there, so the tool reported a name the user
    chose rather than the plugin's own. Reading the stub is what settled it:
    plugins/__init__.py:89.
    """
    fl_env.project.plugin_user_name[4] = "My Bass"
    result = fl_env.controller.dispatch_command("plugins.getName", {"index": 4, "slot_index": -1})
    assert result["name"] == "808 Astronomic"


def test_a_parameter_write_carries_no_pickup_mode(fl_env):
    """setParamValue's fifth argument is pickupMode, not useGlobalIndex."""
    ...


def test_the_display_string_is_read_with_the_global_index_flag(fl_env):
    ...


def test_the_colour_flag_is_the_background_colour(fl_env):
    ...
```

- [ ] **Step 2: Run and watch them fail**
- [ ] **Step 3: Pass every argument by keyword**

Every `plugins.*` call in the controller moves to keyword arguments, so the next stub
signature that grows a parameter cannot silently capture one of ours. This is the real
fix: not four corrected positions, but one habit.

- [ ] **Step 4: Green, whole suite, lint**
- [ ] **Step 5: Commit**

```bash
git commit -m "Pass plugin arguments by name, and fix four that landed on the wrong ones"
```

### Task D2: Read every parameter, in pages

**Files:**
- Modify: `fl_controller/device_FLStudioMCP.py`, `src/fl_studio_mcp/tools/plugins.py`
- Test: `tests/test_plugin_params_paging.py`

**Interfaces:**
- Produces: `plugins.getParams` gains `offset`, `skip_unnamed` and a `total`, and the
  tool `fl_get_plugin_params` gains `offset` and `include_unnamed=False`.

A VST reports 4240 parameters and the current action silently stops at 50, so most of a
plugin is invisible. Paging needs an offset; the stub has none because the loop is
ours. Unnamed parameters are the unused ones a VST reserves, and skipping them by
default turns a 4240 entry wall into the 200 a producer recognises.

- [ ] **Step 1: Write the failing tests**

- `offset` returns the next page without repeating the first.
- `total` is reported, so a caller knows how many pages exist.
- `include_unnamed=False` drops the empty-named entries and says how many it dropped.
- Paging past the end returns an empty page, not an error.
- A page is still one round trip.

- [ ] **Step 2: Run, watch them fail, implement, green**
- [ ] **Step 3: Commit**

```bash
git commit -m "Page plugin parameters, and skip the unnamed ones"
```

### Task D3: Preset records and interpolation, as pure functions

**Files:**
- Create: `src/fl_studio_mcp/musical/presets.py`
- Test: `tests/test_presets.py`

**Interfaces:**
- Produces:
  - `make_preset(name, plugin, params, tags=(), when=None) -> dict`
  - `match(record, query=None, plugin=None, tags=()) -> bool`
  - `interpolate(a, b, amount) -> dict` with `values`, `kept`, `only_in_a`, `only_in_b`,
    `notes`
  - `recall_commands(preset, index, slot_index=-1) -> list[dict]`
  - `summarise(record) -> dict`

Interpolation is linear in the normalised value, which is the only value the API
exposes. That is honest arithmetic and it is not a musical morph: a switch snaps, a
filter cutoff interpolates in the wrong space, and a parameter that exists in only one
of the two presets has no midpoint at all. The function returns the differences it
could not blend by name, so the caller is told rather than surprised. Tests assert
exactly that, including `amount=0` returning the first preset, `amount=1` the second,
and a parameter present in only one preset being reported rather than invented.

- [ ] **Step 1: Write the failing tests**
- [ ] **Step 2: Run and watch them fail**
- [ ] **Step 3: Implement, green**
- [ ] **Step 4: Commit**

```bash
git commit -m "Add preset records and normalised interpolation as pure functions"
```

### Task D4: The preset tools

**Files:**
- Create: `src/fl_studio_mcp/tools/presets.py`
- Test: `tests/test_preset_tools.py`

**Interfaces:**
- Produces: `fl_save_plugin_preset(name, index, slot_index=-1, tags=None, include_unnamed=False)`,
  `fl_find_plugin_presets(query=None, plugin=None, tags=None, limit=20)`,
  `fl_recall_plugin_preset(preset, index, slot_index=-1, apply=False)`,
  `fl_morph_plugin_preset(first, second, amount, index, slot_index=-1, apply=False)`.

- [ ] **Step 1: Write the failing tests**

- Saving reads the plugin's parameters through the paged reader and stores the plugin's
  real name, not the user's.
- Saving an empty slot is refused by name, because a preset of nothing is a trap.
- Recall with `apply=False` reports the values it would write and changes nothing,
  asserted on the fake plugin's parameter array.
- Recall with `apply=True` writes through `fl_batch` so one undo reverses it, and the
  reply says the undo name.
- Recall reports parameters that no longer exist on the plugin.
- A morph of a preset with itself is that preset, and its reply says nothing was
  blended.
- A morph reports the switches it could not blend rather than claiming a smooth result.

- [ ] **Step 2: Run, watch them fail, implement, green**
- [ ] **Step 3: Verify live, with the user's permission**: on the open project, read
      the parameters of the loaded plugin on channel 4 (`808 Astronomic`, 45
      parameters, read live), save them as a preset, move one parameter, then recall
      the preset and confirm the value came back. This changes the sound of a loaded
      instrument, so it is done only with the user's agreement, the original is saved
      first, and the parameter is restored at the end.
- [ ] **Step 4: Commit**

```bash
git commit -m "Add the plugin preset and morph tools"
```

---

## Sub-phase E: sample search and the browser

The API cannot search a browser, so the search happens on disk and the browser is used
for the one thing it can do: audition whatever the producer has highlighted. A
read-only reconnaissance of this Mac, run before this plan was written, decided the
details below.

Findings that shape the code, all observed:

- There is no user sample library on this machine. The real content is factory content
  inside the application bundle, 5190 files in
  `/Applications/FL Studio 2026.app/Contents/Resources/FL/Data/Patches/Packs`, plus
  Apple Loops (1745 `.caf`), Logic (557 `.wav`, 490 `.aif`) and GarageBand.
- The application path carries the release year, so the factory root must be
  discovered or configured, never hardcoded.
- **FL's own factory `.wav` files are Ogg Vorbis inside a RIFF container.** Three of
  three sampled have `fmt` chunk size 26 and format tag `0x674F`, and their `data`
  chunks begin with `OggS`. Python's `wave.open` refuses them: `Error unknown format:
  26447`. 389 files are even named `*OGG.WAV`. A scanner that trusts the extension
  reports a duration it does not have.
- The second most common format is `.wv` (WavPack, 1675 files), then `.flac`. Neither
  is readable by the standard library.
- Spotlight does not index inside application bundles: `mdfind` reports zero `.wv`
  files disk-wide while 1675 exist, so a Spotlight-based scanner would silently miss
  the entire factory library. FL's own browser cache holds three virtual tokens, not
  absolute paths, and no user folders.
- Extensions are mixed case (88 `.WAV` against 3062 `.wav` in one tree) and 88 percent
  of names contain spaces.
- The whole corpus is about 9000 files and 2.6 GB, so a real walk is cheap.

### Task E1: Read audio headers honestly

**Files:**
- Create: `src/fl_studio_mcp/utils/audio_meta.py`
- Test: `tests/test_audio_meta.py`

**Interfaces:**
- Produces: `read_audio_info(path) -> dict` with `format`, `container`, `codec`,
  `sample_rate`, `channels`, `bits`, `duration`, `readable` and, when a number cannot
  be given, `reason`.

Every field is either measured from the file's own header or `None` with a reason. No
field is ever guessed, because a wrong duration is worse than no duration: a caller who
sees `None` and a reason will go and listen.

Formats read: RIFF/WAVE, including PCM, IEEE float, extensible, and the compressed case
that must be recognised rather than mis-decoded; AIFF and AIFC, whose `COMM` chunk
gives frames and rate directly; FLAC, whose `STREAMINFO` gives total samples and rate;
and Ogg, whose last page carries the granule position. Formats listed but not measured:
WavPack, CAF, MP3 and anything else, which come back with `readable: False` and a
reason naming the format. This split is deliberate: the four measured formats cover
most of what producers have, and the rest are listed by name rather than described by
invention.

- [ ] **Step 1: Write the failing tests**, using tiny hand-built headers in `tmp_path`,
      which is the point of reading headers rather than decoding audio:

```python
def test_a_vorbis_wav_is_not_reported_as_pcm(tmp_path):
    """FL's factory wavs are Ogg Vorbis in a RIFF container, tag 0x674F.

    Python's wave module refuses them, so the extension is not evidence of
    anything. A duration computed as if this were PCM would be a lie.
    """
    path = write_wav(tmp_path / "kick.wav", fmt_tag=0x674F, data=b"OggS" + b"\x00" * 100)
    info = audio_meta.read_audio_info(path)
    assert info["codec"] == "vorbis"
    assert info["duration"] is None
    assert "compressed" in info["reason"]


def test_a_pcm_wav_reports_its_duration_exactly(tmp_path):
    """Two seconds of 44.1k stereo 16 bit is two seconds."""
    ...


def test_an_extension_that_lies_is_still_read_by_header(tmp_path):
    """A FLAC named .wav is described as FLAC, because the bytes say so."""
```

- [ ] **Step 2: Run and watch them fail**
- [ ] **Step 3: Implement, green**

Every reader is bounded: a header read is a few hundred bytes, never a whole file, and
an unreadable or truncated file returns `readable: False` with the exception's message
rather than raising.

- [ ] **Step 4: Commit**

```bash
git commit -m "Read audio headers without trusting the extension"
```

### Task E2: Find samples on disk

**Files:**
- Create: `src/fl_studio_mcp/musical/samples.py`, `src/fl_studio_mcp/tools/samples.py`
- Modify: `src/fl_studio_mcp/utils/paths.py` (the root list), `src/fl_studio_mcp/server.py`
- Test: `tests/test_sample_search.py`

**Interfaces:**
- Produces:
  - `sample_roots() -> list[Path]`: `FL_STUDIO_MCP_SAMPLE_DIRS` (path-separator
    separated) wins; otherwise the user data folder, the discovered factory packs
    folder, Apple Loops, Logic and GarageBand, each included only when it exists.
  - `matches(info, query=None, formats=None, min_seconds=None, max_seconds=None) -> bool`
    and `rank(entries, query) -> list[dict]` in `musical/samples.py`, pure.
  - Tool `fl_find_samples(query=None, folder=None, formats=None, min_seconds=None,
    max_seconds=None, limit=25)`.

- [ ] **Step 1: Write the failing tests**

- A query matches the file name and the folder path, case-insensitively.
- `formats=["wav"]` matches `.WAV` as well, because one tree has both.
- A duration filter excludes a file whose duration is unknown rather than including it
  on a guess, and the reply says how many were excluded for that reason.
- The walk is bounded, and hitting the bound is reported rather than hidden.
- A folder that does not exist is reported, not raised, because a fresh Mac has none of
  these.
- Results are capped and the reply says the count that was found.
- The reply names the roots that were searched, so a surprising answer is explainable.

- [ ] **Step 2: Run, watch them fail, implement, green**
- [ ] **Step 3: Verify live**: search the real corpus, read-only, and record what came
      back. The factory packs are the interesting case: 5046 audio files, mostly
      `.wav` that are not PCM, so the scan exercises the honest-metadata path.
- [ ] **Step 4: Commit**

```bash
git commit -m "Search the sample folders that exist on this machine"
```

### Task E3: Audition, and say what audition means here

**Files:**
- Modify: `fl_controller/device_FLStudioMCP.py`, `src/fl_studio_mcp/tools/project.py`,
  `src/fl_studio_mcp/tools/samples.py`
- Test: `tests/test_browser_audition.py`

**Interfaces:**
- Produces: a `browser` block in `fl_get_ui_state`'s reply, from
  `ui.getFocusedNodeCaption()`, `ui.getFocusedNodeFileType()` and
  `ui.isBrowserAutoHide()`; and the tool `fl_audition_sample()` calling
  `ui.previewBrowserMenuItem()`.
- Produces only if the live check passes: `fl_browser_step(direction="next", steps=1,
  expand=False)` calling `ui.navigateBrowser(41 or 40, shiftHeld)`.

- [ ] **Step 1: Write the failing tests**

- `fl_get_ui_state` reports the focused browser caption and file type, and reports
  `None` rather than an empty string when nothing is focused, so "nothing selected" is
  distinguishable from "a file with no name".
- `fl_audition_sample` refuses to claim it chose a file: its reply names the caption it
  was pointed at and says the caption is whatever FL had highlighted.
- `fl_audition_sample` is not a mutating action, asserted against the canonical list:
  it plays audio, and it changes no project state.
- A browser call that raises inside FL is reported as a failure with the exception text,
  not as a silent success.

- [ ] **Step 2: Run, watch them fail, implement, green**
- [ ] **Step 3: Verify live, with the user's permission**: read the focused node, then
      audition with something highlighted. Separately, test whether
      `ui.navigateBrowser(41, False)` actually moves the selection on this build, since
      the stub itself says it is unreliable. Record the result. If it does not move,
      `fl_browser_step` is not shipped, and the plan says why: a tool that silently
      does nothing is worse than no tool.
- [ ] **Step 4: Commit**

```bash
git commit -m "Read and audition the browser's focused item"
```

---

## Sub-phase F: indexing, structure and templates

### Task F1: Index a folder of projects

**Files:**
- Create: `src/fl_studio_mcp/utils/flp.py`, `src/fl_studio_mcp/tools/indexing.py`
- Test: `tests/test_flp_index.py`

**Interfaces:** decided by the `.flp` feasibility study that runs alongside this plan.
The task lands as either a minimal header reader for a handful of fields, or a recorded
decision not to ship the feature. It never ships a parser that reports a number it
cannot stand behind, and it never adds a runtime dependency: the study weighed PyFLP
against a hand-written reader and the maintainability answer is recorded with the
decision.

- [ ] **Step 1: Write the decision and the failing tests together**, so the code and
      the reasoning arrive in the same commit.
- [ ] **Step 2: Run, watch them fail, implement, green**
- [ ] **Step 3: Commit**

```bash
git commit -m "Index project files, and say what could not be read"
```

### Task F2: Read the song's structure

**Files:**
- Create: `src/fl_studio_mcp/musical/structure.py`, `src/fl_studio_mcp/tools/structure.py`
- Test: `tests/test_structure.py`

**Interfaces:**
- Produces:
  - `sections(markers, ppq, beats_per_bar) -> list[dict]`, each with a name, a start
    bar, a length in bars and the next marker's name.
  - `pattern_report(patterns, ppq, beats_per_bar) -> list[dict]`, each with a length in
    bars and whether it divides into four bar blocks.
  - `critique(context, patterns, markers) -> dict` with `sections`, `patterns`,
    `observations` and `summary`.
  - Tool `fl_structure_critique()`.

Every observation is arithmetic, and the docstring says so. "The last section is four
bars and the others are sixteen" is a fact. "The chorus is too short" is taste, and
this tool does not have any. Marker positions come from `arrangement.getMarkers`, and
pattern lengths come from `patterns.getPatternLength`, which the stub documents as
**beats**, not ticks (`patterns/__properties.py:152-165`), so the conversion is beats
to bars and it is tested in both meters.

- [ ] **Step 1: Write the failing tests**

- Markers become sections with the right start and length, and the section lengths are
  measured to the next marker.
- A project with no markers says there is no structure to read, as an informational
  finding rather than an error.
- A marker that does not fall on a bar line is reported as a problem.
- A pattern whose length does not divide into four bar blocks is reported, and one that
  does is not.
- 3/4 is honoured: four bars of 3/4 is twelve beats, which is the kind of arithmetic
  that was wrong before in this project.
- The whole report is read in one round trip.

- [ ] **Step 2: Run, watch them fail, implement, green**
- [ ] **Step 3: Verify live, read-only**: run it against the open project, which has no
      markers and one sixteen beat pattern, and record the honest, boring answer.
- [ ] **Step 4: Commit**

```bash
git commit -m "Read the song's structure, as arithmetic over markers and lengths"
```

### Task F3: Templates that name, colour and route

**Files:**
- Create: `src/fl_studio_mcp/musical/templates.py`, `src/fl_studio_mcp/tools/templates.py`
- Test: `tests/test_templates.py`

**Interfaces:**
- Produces:
  - `TEMPLATES: dict[str, dict]` of built-in specs, and `catalogue() -> list[dict]`.
  - `validate(spec, track_count, channel_count, overwrite=False) -> dict` with
    `commands`, `skipped`, `problems`.
  - Tool `fl_apply_template(template=None, spec=None, apply=False, overwrite=False)`,
    which with neither a name nor a spec returns the catalogue.

The built-in `mixing` template names and colours eight inserts and routes them into two
returns, and the built-in `sections` template places eight bar markers. Neither loads
an instrument, because the API cannot, so the reply says which tracks are still empty.
A track is only touched when it is named in the spec and either still carries FL's
generated name or `overwrite=True`, so applying a template to a live project does not
rename work that is already there.

- [ ] **Step 1: Write the failing tests**

- Applying the mixing template with `apply=False` reports every move and changes
  nothing.
- Applying it with `apply=True` goes through one batch, so one undo reverses it.
- A track with a name the producer chose is skipped, and the reply names it.
- `overwrite=True` touches it.
- A spec with an unknown field, an out of range index or a wrong type is refused with
  the offending path named, and nothing is applied.
- With neither a name nor a spec, the reply is the catalogue and nothing is sent to FL.
- The template never claims to load an instrument, and the reply lists the tracks
  without one.

- [ ] **Step 2: Run, watch them fail, implement, green**
- [ ] **Step 3: Verify live, with the user's permission**, on empty high numbered mixer
      tracks only, then undo and confirm the names came back.
- [ ] **Step 4: Commit**

```bash
git commit -m "Name, colour and route from a validated template"
```

---

## Sub-phase G: documentation and the exit criteria

### Task G1: Documentation

**Files:**
- Modify: `README.md`, `docs/SMOKE_TEST.md`, `ROADMAP.md`,
  `docs/plans/2026-09-19-phase-6-curation.md`
- Test: `tests/test_docs.py`

- [ ] **Step 1: README rows for every new tool**, plus a "Library And Journal" section
      that says where the library lives, that it is plain JSON, how to move it, how to
      turn the journal off, and what a snapshot cannot contain. The peak-hold honesty
      of Phase 5 is the model: state the limit in the same breath as the feature.
- [ ] **Step 2: Smoke test items for what only a human can check**: that a recalled
      riff sounds like the riff, that a restored snapshot put the mix back, that the
      audition preview played the highlighted file, and that the journal describes what
      the session did in the order it did it.
- [ ] **Step 3: Record the live runs**, including everything that could not be run and
      the browser navigation result.
- [ ] **Step 4: Tick the exit criteria, and record what this plan got wrong.** Every
      previous phase's plan has that section, and it is the most useful part of them.
- [ ] **Step 5: Commit**

```bash
git commit -m "Document the curation tools and record the live runs"
```

---

## Phase 6 exit criteria

- [ ] All eight roadmap features ship, each with at least one tool, tests, and a README
      row.
- [ ] Nothing in the phase writes outside the library root, and a test proves an unsafe
      record id cannot escape it.
- [ ] The journal records every mutating command with its outcome and never breaks the
      command it records, and `FL_STUDIO_MCP_JOURNAL=0` disables it.
- [ ] The four plugin argument-order defects are fixed, with tests that fail against
      the old ordering, and every `plugins.*` call passes its arguments by name.
- [ ] Plugin parameter reads are paged and report the total, so a 4240 parameter VST is
      no longer truncated at 50 in silence.
- [ ] A riff can be saved, found and recalled transposed into the project's key, with
      clamped notes counted and reported.
- [ ] A snapshot can be taken, diffed against the live project, and restored through
      one batch, and the restore reports what it cannot put back.
- [ ] A plugin preset can be saved, found, recalled and interpolated, and the
      interpolation names what it could not blend.
- [ ] Sample search walks the folders that exist, never trusts a file extension, and
      reports a reason instead of a guessed duration.
- [ ] The browser integration reports what is highlighted and auditions it, and claims
      nothing more than the API allows.
- [ ] Structure critique is arithmetic over markers and pattern lengths, in the
      project's own meter, and says so.
- [ ] Templates validate before they apply, skip work they do not own, and never claim
      to load an instrument.
- [ ] `pytest` green and `ruff check .` clean with no FL Studio running, and a clean
      clone installs with `uv sync --dev --locked` and passes.
- [ ] `docs/SMOKE_TEST.md` records the live runs and what could not be run.

## What Phase 6 deliberately does not do

- It does not search FL's browser, because the API has no search of any kind. The
  filesystem is searched instead, and the browser is used only for auditioning what the
  producer has highlighted.
- It does not load anything into the project from the browser. No such function exists
  in any module, which is the same wall as Phase 3's plugin loading limit.
- It does not capture audio, so it adds no loudness measurement. Loopback capture and
  reference matching stay tabled.
- It does not write `.flp` files, and it will not parse one further than it can
  justify: the indexing task ships only what it can verify, and says so where it stops.
- It does not store notes in a snapshot, because the notes live in the other sandbox,
  and a snapshot that silently omits something is worse than one that lists it as
  unrestorable.
- It does not add a runtime dependency for audio metadata or project parsing. The
  headers it reads, it reads itself, and the formats it cannot read are named rather
  than approximated.
