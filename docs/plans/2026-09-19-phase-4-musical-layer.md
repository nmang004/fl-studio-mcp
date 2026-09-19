# Phase 4: The FL-Native Musical Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One call writes a slide-articulated bassline in the project's real key and
meter into a named channel, and reads it back.

**Architecture:** Three layers, and the split matters.

The piano roll script owns everything that touches notes, because it is the only
thing that can. It gains the twelve `flpianoroll.Note` properties the server has
never written, and it assigns note groups, because `score.getNextFreeGroupIndex`
lives in its sandbox and nowhere else.

The server owns musical reasoning: keys, scales, bars and beats, chord symbols,
groove. It has a real standard library and the key facts, where the script has
neither.

The controller owns context the script cannot see, which is only the PPQ, since
`flpianoroll.score` already exposes the key and the meter to the script directly.
That is worth stating because the roadmap assumes otherwise: it lists
`score.snap_root_note` and `score.tsnum` under the server's context sources, and
they are the piano roll script's sources, not the controller's.

**Tech Stack:** The Phase 0 harness, the Phase 1 transport, the Phase 2 targeting,
the Phase 3 breadth, pytest 9, ruff 0.16.

**Spec:** `ROADMAP.md` Phase 4, plus the Note property table in `CLAUDE.md`.

## Global Constraints

Copied from ROADMAP.md, and implicitly part of every task:

- Python `>=3.10`, ruff `target-version = "py310"`, `ruff check .` clean, line
  length 100, rules `E`, `F`, `I`, `W`.
- `pytest` green with no FL Studio running.
- macOS and Windows must both keep working.
- No em dashes, no en dashes, no emoji anywhere. No AI attribution.
- Commits scoped to one concern.
- The controller imports only FL modules plus `json`, `os`, `sys`, `pathlib`, and
  may not call `mkdir`, `makedirs`, `replace`, `rename`, `remove`, `unlink`,
  `glob`, `rglob`, `walk` or the builtin `open()`.
- The pyscript has the same rename and directory restrictions but may use `open()`.
- Every mutating action is in `MUTATING_ACTIONS` and every action needing a target
  uses `_require`.

### The contract types, read from the stubs

Read from `flpianoroll/__note.py` and `flpianoroll/__score.py`, because these are
easy to assume wrongly and the fakes had two of them wrong until this phase:

| Name | Type | Notes |
| --- | --- | --- |
| `number` | int | MIDI note number |
| `time`, `length` | int | ticks |
| `velocity` | float | 0.0 to 1.0 |
| `pan` | float | the piano roll's own range; an untouched note reads back 0.5 |
| `color` | int | |
| `fcut`, `fres` | float | per-note filter cutoff and resonance |
| `group` | int | note group index |
| `pitchofs` | **int** | not a float |
| `release` | **float** | not a flag |
| `repeats` | int | |
| `slide`, `porta`, `muted`, `selected` | bool | the only four flags |
| `score.snap_root_note` | int | root of snap to scale, C is 0 |
| `score.snap_scale_helper` | **str** | `"0,1,0,1,..."`, 0 is in scale, always C-aligned |
| `score.tsnum`, `score.tsden` | int | project time signature, ignores markers |

---

### Task 1: The pyscript owns every Note property

**Files:**
- Modify: `scripts/ComposeWithLLM.pyscript`
- Test: `tests/test_piano_roll_expression.py`

**Interfaces:**
- Consumes: the existing `_note_from` and `HANDLERS` in the pyscript.
- Produces: `_note_from` writes all sixteen properties, and the state export
  already reports all sixteen.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_piano_roll_expression.py
"""Every Note property the API exposes has to survive a round trip.

The server wrote four of sixteen. Slide and portamento are what make a 303 line
sound like a 303 line, and no generic MIDI tool writes them, so this is the part of
the fork that is not a wrapper.
"""

from __future__ import annotations

import json

import pytest

EXPRESSIVE = {
    "midi": 36,
    "time": 0.0,
    "duration": 0.5,
    "velocity": 0.9,
    "pan": 0.25,
    "color": 0x334455,
    "fcut": 0.6,
    "fres": 0.3,
    "group": 7,
    "muted": True,
    "pitchofs": 12,
    "porta": True,
    "release": 0.4,
    "repeats": 3,
    "selected": True,
    "slide": True,
}


def write(fl_env, notes, action="add_notes"):
    path = fl_env.request_file
    path.write_text(json.dumps([{"action": action, "id": "x", "notes": notes}]))
    fl_env.pyscript.apply()


def state(fl_env):
    return json.loads(fl_env.state_file.read_text())


def test_every_property_survives_the_round_trip(fl_env):
    write(fl_env, [EXPRESSIVE])
    note = fl_env.project.notes[0]
    for key, expected in EXPRESSIVE.items():
        if key in ("midi", "time", "duration"):
            continue
        assert getattr(note, key) == pytest.approx(expected), f"{key} did not survive"


def test_the_export_reports_every_property(fl_env):
    write(fl_env, [EXPRESSIVE])
    exported = state(fl_env)["notes"][0]
    for key in ("fcut", "fres", "group", "pitchofs", "release", "repeats",
                "slide", "porta", "pan", "color", "muted", "selected"):
        assert key in exported, f"the export omits {key}"
    assert exported["slide"] is True
    assert exported["pitchofs"] == 12
    assert exported["release"] == pytest.approx(0.4)
    assert exported["repeats"] == 3


def test_pitchofs_is_an_integer(fl_env):
    """The stubs give pitchofs as an int. Writing a float would be a silent change."""
    write(fl_env, [{"midi": 60, "time": 0.0, "duration": 1.0, "pitchofs": 7}])
    assert isinstance(fl_env.project.notes[0].pitchofs, int)


def test_release_is_numeric_not_a_flag(fl_env):
    """The stubs give release as a float, so it is a value, not a switch."""
    write(fl_env, [{"midi": 60, "time": 0.0, "duration": 1.0, "release": 0.75}])
    assert fl_env.project.notes[0].release == pytest.approx(0.75)


def test_an_unspecified_property_keeps_the_note_default(fl_env):
    write(fl_env, [{"midi": 60, "time": 0.0, "duration": 1.0}])
    note = fl_env.project.notes[0]
    assert note.slide is False
    assert note.pitchofs == 0
    assert note.release == 0.0
    assert note.velocity == pytest.approx(0.8), "the Note default, not zero"


def test_a_bad_value_is_reported_rather_than_crashing_the_script(fl_env):
    write(fl_env, [{"midi": 60, "time": 0.0, "duration": 1.0, "pitchofs": "not a number"}])
    response = json.loads(fl_env.piano_roll_response_file.read_text())
    assert response["success"] is False
    assert response["error"]
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/test_piano_roll_expression.py -v`
Expected: `fcut`, `fres`, `group`, `pitchofs`, `release`, `repeats` and the flags
outside the current list do not survive, because `_note_from` writes six numeric,
two integer and five flag properties and hardcodes nothing else.

- [ ] **Step 3: Write every property**

In `scripts/ComposeWithLLM.pyscript`, replace the three property tuples with one
table so the types cannot drift from the stubs:

```python
# Every flpianoroll.Note property a request may set, with the type to coerce to.
# The stubs give pitchofs and repeats as ints, release, velocity, pan, fcut and
# fres as floats, and slide, porta, muted and selected as flags. Getting one of
# these types wrong is silent, which is why the table is explicit rather than a
# list of names.
NOTE_PROPERTIES = (
    ("velocity", float),
    ("pan", float),
    ("fcut", float),
    ("fres", float),
    ("release", float),
    ("color", int),
    ("group", int),
    ("pitchofs", int),
    ("repeats", int),
    ("slide", bool),
    ("porta", bool),
    ("muted", bool),
    ("selected", bool),
)
```

and use it in `_note_from`:

```python
    for key, coerce in NOTE_PROPERTIES:
        if key in data:
            setattr(note, key, coerce(data[key]))
```

- [ ] **Step 4: Run them and watch them pass**

Run: `uv run pytest tests/test_piano_roll_expression.py -v`
Expected: 6 passed.

- [ ] **Step 5: Run the whole suite and lint, then verify live**

```bash
uv run pytest && uv run check .
cp scripts/ComposeWithLLM.pyscript \
   ~/Documents/Image-Line/FL\ Studio/Settings/Piano\ roll\ scripts/
```

Then ask the user to run the script once with a queued slide-articulated note, and
confirm `slide` and `porta` come back true in the export. This is the one check
that proves FL accepts the properties, as opposed to the fake.

- [ ] **Step 6: Commit**

```bash
git add scripts/ComposeWithLLM.pyscript tests/test_piano_roll_expression.py
git commit -m "Write every flpianoroll Note property, not four of sixteen"
```

---

### Task 2: Note groups

**Files:**
- Modify: `scripts/ComposeWithLLM.pyscript`
- Test: `tests/test_note_groups.py`

**Interfaces:**
- Consumes: Task 1's property table.
- Produces:
  - A request may carry `"group": true` instead of a group number, and the script
    assigns the next free index with `score.getNextFreeGroupIndex`, stamping the
    same index on every note in that request.
  - `"group_name"` in the request is recorded in the reply so a caller can refer to
    the phrase later.
  - The reply carries `"group": <index>`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_note_groups.py
"""A group makes "remove the arpeggio you added" exact.

Without one, removing a phrase means matching on pitch and time, which is wrong the
moment the user has written something similar by hand.
"""

from __future__ import annotations

import json


def write(fl_env, requests):
    fl_env.request_file.write_text(json.dumps(requests))
    fl_env.pyscript.apply()


def reply(fl_env):
    return json.loads(fl_env.piano_roll_response_file.read_text())


def test_a_request_asking_for_a_group_gets_one(fl_env):
    write(fl_env, [{"action": "add_notes", "id": "g", "group": True, "notes": [
        {"midi": 60, "time": 0.0, "duration": 1.0},
        {"midi": 64, "time": 1.0, "duration": 1.0},
    ]}])
    groups = {note.group for note in fl_env.project.notes}
    assert len(groups) == 1, "the notes are not one group"
    assert groups != {0}, "group 0 means ungrouped, so it is not an assignment"
    assert reply(fl_env)["group"] in groups


def test_two_grouped_requests_get_different_groups(fl_env):
    write(fl_env, [
        {"action": "add_notes", "id": "a", "group": True,
         "notes": [{"midi": 60, "time": 0.0, "duration": 1.0}]},
        {"action": "add_notes", "id": "b", "group": True,
         "notes": [{"midi": 67, "time": 0.0, "duration": 1.0}]},
    ])
    assert len({note.group for note in fl_env.project.notes}) == 2


def test_an_explicit_group_number_is_honoured(fl_env):
    write(fl_env, [{"action": "add_notes", "id": "e", "notes": [
        {"midi": 60, "time": 0.0, "duration": 1.0, "group": 5},
    ]}])
    assert fl_env.project.notes[0].group == 5
    assert reply(fl_env)["group"] is None, "nothing was assigned"


def test_notes_without_a_group_stay_ungrouped(fl_env):
    write(fl_env, [{"action": "add_notes", "id": "n", "notes": [
        {"midi": 60, "time": 0.0, "duration": 1.0},
    ]}])
    assert fl_env.project.notes[0].group == 0
```

- [ ] **Step 2: Run and watch them fail**

- [ ] **Step 3: Implement group assignment**

`getNextFreeGroupIndex` must be called once per group, and its own stub says the
notes have to be added before calling it again, so the assignment happens before
the notes are added and the index is reused within the request.

- [ ] **Step 4: Run to green, then commit**

```bash
git commit -m "Assign note groups so a phrase can be removed exactly"
```

---

### Task 3: Project context, read from where it actually lives

**Files:**
- Modify: `scripts/ComposeWithLLM.pyscript`
- Modify: `fl_controller/device_FLStudioMCP.py`
- Create: `src/fl_studio_mcp/tools/score.py`
- Test: `tests/test_score_context.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - Pyscript action `get_context`, replying
    `{"root_note": int, "scale_helper": str, "in_scale": [int, ...],
      "tsnum": int, "tsden": int, "ppq": int}`.
  - Controller action `system.getPpq`, replying `{"ppq": int}` from
    `general.getRecPPQ()`.
  - `fl_studio_mcp.tools.score.get_project_context() -> dict` with
    `key_name`, `root_note`, `scale`, `scale_degrees`, `time_signature`,
    `beats_per_bar`, `ppq`.
  - Tool `fl_get_project_context()`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_score_context.py
"""The project's key and meter, so the server stops assuming C major 4/4.

The stubs put the key and the meter in the piano roll script's sandbox, on
flpianoroll.score, not in the controller. The roadmap lists them as controller
sources; they are not, and this is the correction.
"""

from __future__ import annotations

import pytest

from fl_studio_mcp.tools import score

# C major: every note in scalemeans no black keys.
C_MAJOR = "0,1,0,1,0,0,1,0,1,0,1,0"
# A natural minor, the same shape rotated so that A is the root.
A_MINOR = "0,1,0,1,0,1,0,1,1,0,1,0"


def test_the_context_reports_the_root_note(fl_env):
    fl_env.project.snap_root_note = 9
    fl_env.project.snap_scale_helper = A_MINOR
    fl_env.pyscript.apply()
    context = score.read_context(fl_env.pyscript)
    assert context["root_note"] == 9


def test_the_context_translates_the_helper_into_scale_degrees(fl_env):
    fl_env.project.snap_root_note = 0
    fl_env.project.snap_scale_helper = C_MAJOR
    fl_env.pyscript.apply()
    context = score.read_context(fl_env.pyscript)
    assert context["in_scale"] == [0, 2, 4, 5, 7, 9, 11]


def test_the_context_reports_the_meter(fl_env):
    fl_env.project.tsnum = 3
    fl_env.project.tsden = 4
    fl_env.pyscript.apply()
    context = score.read_context(fl_env.pyscript)
    assert context["time_signature"] == "3/4"
    assert context["beats_per_bar"] == 3


def test_the_context_names_the_key(fl_env):
    fl_env.project.snap_root_note = 9
    fl_env.project.snap_scale_helper = A_MINOR
    fl_env.pyscript.apply()
    assert score.key_name(9, A_MINOR) == "A minor"


def test_the_context_names_a_major_key(fl_env):
    assert score.key_name(0, C_MAJOR) == "C major"


def test_a_helper_that_is_not_twelve_entries_is_refused(fl_env):
    """A malformed helper would silently produce a wrong scale."""
    with pytest.raises(ValueError):
        score.scale_degrees("0,1,0")
```

- [ ] **Step 2: Run and watch them fail**

- [ ] **Step 3: Implement, run to green, then verify live**

The live check matters here more than usual, because `snap_scale_helper` is a
string whose meaning is documented but whose real content on a project has never
been seen. Print it and record what FL actually returns for the open project.

- [ ] **Step 4: Commit**

```bash
git commit -m "Read the project's key and meter from the piano roll sandbox"
```

---

### Task 4: Bars and beats

**Files:**
- Create: `src/fl_studio_mcp/musical/time.py`
- Test: `tests/test_musical_time.py`

**Interfaces:**
- Consumes: Task 3's context for `beats_per_bar` and `ppq`.
- Produces:
  - `parse_position(text, beats_per_bar) -> float`: accepts `"3"` (bar 3),
    `"3.2"` (bar 3 beat 2), `"3.2.1"` and `"3.2.50%"`, `"2:3:120"` and a bare
    number of beats as `"b7"`.
  - `format_position(beats, beats_per_bar) -> str`: the inverse.
  - `beats_to_ticks(beats, ppq) -> int`, `ticks_to_beats(ticks, ppq) -> float`.

- [ ] **Step 1: Write the failing tests**

One test per accepted form and per rejection. The forms that matter:

- `"1"` is bar 1 beat 1, which is beat 0.
- `"2"` is beat `beats_per_bar`.
- `"3.2"` is bar 3 beat 2.
- `"3.2.1"` is the first sixteenth of bar 3 beat 2.
- `"3.2.50%"` is halfway through bar 3 beat 2.
- `"b7"` is 7 beats from the start, which is the escape hatch when the meter is
  not what the caller assumed.
- A negative or zero bar is refused, naming the input.
- `format_position(parse_position(x)) == x` round trips for the forms with a
  canonical spelling.

- [ ] **Step 2: Run and watch them fail, then implement**

The arithmetic is worth stating once: a bar is `beats_per_bar` beats, and a beat is
`ppq` ticks. Nothing else in this module should contain a bare number.

- [ ] **Step 3: Run to green and commit**

```bash
git commit -m "Add a bars and beats time model that honours the project meter"
```

---

### Task 5: Chords by symbol

**Files:**
- Create: `src/fl_studio_mcp/musical/chords.py`
- Test: `tests/test_chords.py`

**Interfaces:**
- Produces: `parse_chord(symbol) -> list[int]`, returning semitone offsets from the
  root, and `notes_for_chord(symbol, root_octave=4) -> list[int]` returning MIDI
  numbers.

- [ ] **Step 1: Write the failing tests**

Cover the vocabulary a producer actually types, and refuse the rest rather than
guessing:

- Major, minor, dominant and diminished triads: `C`, `Cm`, `Cdim`.
- Sevenths: `Cmaj7`, `Cm7`, `C7`, `Cm7b5`, `Cdim7`, `CmMaj7`.
- Suspended and added: `Csus2`, `Csus4`, `Cadd9`, `C6`, `Cm6`.
- Extensions: `C9`, `Cm9`, `Cmaj9`, `C11`, `C13`.
- Alterations: `C7b9`, `C7#9`, `C7#11`, `Cmaj7#5`.
- Accidentals: `F#`, `Gb`, `Bb`, `Eb`.
- Slash chords: `C/G`, `Am7/G`.
- Octave placement: `notes_for_chord("C", 4)` starts at MIDI 60.
- An unknown symbol raises `ValueError` naming it, rather than returning a guess.
- Every parsed chord's first interval is 0, and the intervals ascend.

- [ ] **Step 2: Run, watch them fail, implement, run to green**

- [ ] **Step 3: Commit**

```bash
git commit -m "Add chord symbols, because Cmaj7 is clearer than three MIDI numbers"
```

---

### Task 6: Groove transforms

**Files:**
- Create: `src/fl_studio_mcp/musical/groove.py`
- Test: `tests/test_groove.py`

**Interfaces:**
- Produces pure functions over note dicts, so they are testable without FL:
  - `swing(notes, amount=0.5, subdivision=2) -> list[dict]`
  - `humanize(notes, timing=0.02, velocity=0.1, seed=None) -> list[dict]`
  - `quantize(notes, grid=0.25, strength=1.0) -> list[dict]`
  - `accent(notes, pattern="x-x-", strength=0.2) -> list[dict]`
  - `crescendo(notes, start=0.5, end=1.0) -> list[dict]`

- [ ] **Step 1: Write the failing tests**

The properties worth asserting are the musical ones, not the implementation:

- Swing moves every second subdivision later and leaves the first alone.
- Swing with amount 0 changes nothing, which is the identity a caller expects.
- Humanize with a seed is reproducible, and without one is not.
- Humanize never pushes a note before zero, which would be invalid.
- Humanize respects the velocity range, clamping rather than exceeding it.
- Quantize with strength 1 lands exactly on the grid, and with strength 0 changes
  nothing.
- Quantize does not change note lengths.
- Accent raises the velocity of the accented positions and leaves the rest.
- Crescendo is monotonic across the notes in time order.
- Every function returns new dicts rather than mutating the input, because a caller
  that wants the original still has it.
- An empty list is returned unchanged by all five.

- [ ] **Step 2: Run, watch them fail, implement, run to green**

- [ ] **Step 3: Commit**

```bash
git commit -m "Add groove transforms: swing, humanize, quantize, accent, crescendo"
```

---

### Task 7: The bassline, and the exit criterion

**Files:**
- Create: `src/fl_studio_mcp/musical/bassline.py`
- Modify: `src/fl_studio_mcp/tools/score.py`
- Test: `tests/test_bassline.py`

**Interfaces:**
- Consumes: Tasks 3 to 6.
- Produces:
  - `bassline(root, pattern, bars=1, octave=2, slide=True, accent=None) -> list[dict]`
    where `pattern` is a rhythm string like `"x-x-xx--"` and the notes follow the
    root, with `slide` set on the notes that lead into the next.
  - Tool `fl_write_bassline(channel, notes, bars=1, octave=2, ...)`, which reads the
    context, snaps the notes into the project's key, targets the channel, writes,
    and reads back.

- [ ] **Step 1: Write the failing tests**

The exit criterion is the test:

- A single call writes a slide-articulated bassline into a named channel and the
  read-back confirms it, with `slide` true on the articulation notes.
- The written notes are in the project's key: with an A minor context, every note is
  in A minor.
- Time is metered: with a 3/4 context, one bar is three beats, not four.
- The reply names the channel and the key it used.
- A channel that does not exist is refused before anything is written.
- A rhythm string with no hits is refused rather than writing nothing.

- [ ] **Step 2: Run, watch the exit-criterion test fail, implement, run to green**

- [ ] **Step 3: Verify live, with the user running the script once**

This is the phase's done-condition and it needs a human, because the keystroke is
still blocked. Queue the request, ask the user to run the script from FL's menu,
then read the notes back and confirm the articulation.

To leave the project clean, write into a new pattern the user can delete rather
than over existing notes, and say so.

- [ ] **Step 4: Commit**

```bash
git commit -m "Write a slide-articulated bassline in the project's own key and meter"
```

---

### Task 8: Describe the project in one call

**Files:**
- Create: `src/fl_studio_mcp/tools/describe.py`
- Test: `tests/test_describe.py`

**Interfaces:**
- Consumes: everything above.
- Produces: tool `fl_describe_project()`, returning tempo, key, meter, patterns with
  their lengths, channels with their plugins and mixer targets, mixer tracks with
  volume and routing, and which pattern is current.

- [ ] **Step 1: Write the failing test**

The point is one call instead of twenty, so the test asserts the call count: one
`fl_describe_project` must not fan out into a round trip per channel. Count the
commands the tool sends and assert it is a small fixed number.

- [ ] **Step 2: Run, watch it fail, implement, run to green, commit**

```bash
git commit -m "Describe the whole project in one call"
```

---

### Task 9: MIDI import and export

**Files:**
- Create: `src/fl_studio_mcp/musical/midi.py`
- Test: `tests/test_midi_bridge.py`

**Interfaces:**
- Produces `to_midi_file(notes, ppq, tempo, path) -> Path` and
  `from_midi_file(path) -> list[dict]`, using `mido`, which is already a
  dependency.

- [ ] **Step 1: Write the failing tests**

- A round trip through a file returns the same pitches, times, lengths and
  velocities within a tolerance.
- Slide and portamento are exported as the FL conventions if any exist, and if none
  do, the export says so in its docstring rather than inventing one.
- A file with a tempo and a time signature exports them.
- Import maps ticks to beats using the file's own PPQ, not the project's.
- A malformed file raises rather than returning an empty list, because silently
  importing nothing looks like an empty pattern.

- [ ] **Step 2: Run, watch them fail, implement, run to green, commit**

```bash
git commit -m "Bridge to MIDI files so notes can leave and enter FL"
```

---

### Task 10: Documentation and the exit criteria

**Files:**
- Modify: `README.md`, `docs/SMOKE_TEST.md`
- Modify: `docs/plans/2026-09-19-phase-4-musical-layer.md`
- Test: `tests/test_docs.py`

- [ ] **Step 1: Add the README rows for every new tool, and a section on musical
      context explaining that the server reads the project's key and meter rather
      than assuming C major 4/4.**

- [ ] **Step 2: Add the smoke test items for the piano roll expression path, since
      those can only be checked by eye in FL:**

- [ ] Write a slide note and confirm FL draws it as a slide rather than a normal note.
- [ ] Write a portamento note and confirm the same.
- [ ] Write notes with `fcut` and confirm the per-note filter is set.
- [ ] Read the context back and confirm the key matches the piano roll's snap to
      scale setting.

- [ ] **Step 3: Record the live run in the smoke test, then commit.**

---

## Phase 4 exit criteria

Checked on 2026-09-19 against the committed tree and live FL Studio 2026.

- [x] One call writes a slide-articulated bassline in the project's real key and
      meter into a named channel, and reads it back. Verified live, and confirmed by
      eye in FL.
- [x] Every one of the sixteen `flpianoroll.Note` properties round trips. Verified
      live: slide, porta, fcut, fres, pitchofs, release and group all survived, and
      FL drew its own slide and portamento markers.
- [x] The server reads the key and meter instead of assuming C major 4/4, and says
      so when no key is set rather than inventing one.
- [x] Bars and beats work, honouring the project's time signature, so bar 2 in 3/4 is
      beat 3 and not beat 4.
- [x] Chord symbols parse, and an unknown symbol is refused rather than guessed.
- [x] Groove transforms are pure, tested against the fake, and leave the input alone.
- [x] A grouped phrase can be identified exactly.
- [x] `fl_describe_project` answers in one call, and a test counts the round trips to
      keep it that way.
- [x] `pytest` green and `ruff check .` clean with no FL Studio running. 592 tests
      from a clean clone.
- [x] `docs/SMOKE_TEST.md` records the live run and what could not be run.

### Seven assumptions the live environment corrected

This phase produced more of these than the previous three combined, and every one was
invisible to the test suite because the fake had been written from the same guess as
the code.

| Assumption | What FL actually does |
| --- | --- |
| `release` is a flag | It is a float. The property table had it in the flag list, so a release of 0.75 became True |
| `pitchofs` is a float | It is an int in units of 10 cents, so 25 is a quarter tone and a fractional value is not valid at all |
| `snap_scale_helper` is always twelve values | With snap to scale off it is an empty string |
| The scale root is at index 0 | The helper is C-aligned, so A minor starts at index 9 |
| Rotating the degree list gives offsets from the root | It gives absolute semitones in a different order, so the third entry read as 0 rather than as a minor third |
| `getNextFreeGroupIndex` is a module function | It is a method on the score object |
| A note with no `pan`, `fcut`, `fres` or `release` reads back as 0.0 | They read back as 0.5, because FL normalises them |

Two of these were mine getting a test expectation wrong while the code was right, and
five were the code and the fake being wrong together. The pattern is consistent
enough to state as a rule: the fake is a model written from the same understanding as
the code, so it cannot catch a misunderstanding. Only a live read can.

### What Phase 4 got right by accident

`fl_get_project_context` imported its script with a helper from the test suite, so
the shipped code raised ModuleNotFoundError the first time it was called for real. No
test caught it because every test provided the helper. It was found by running the
tool outside pytest, which is a check worth doing on every tool before claiming it
works.

## What Phase 4 deliberately does not do

- It does not write automation clips. That is spike T3, and `mixer.automateEvent` is
  marked HELP WANTED upstream.
- It does not place anything in the playlist. `playlist` has no such function, so
  markers and live clips remain the ceiling, and the bassline goes into a pattern.
- It does not attempt loopback audio capture, which is tabled.
