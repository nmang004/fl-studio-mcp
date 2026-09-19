# Phase 3: API Breadth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cover the parts of FL the server currently ignores, that producers
actually use: patterns, EQ, routing, metering, channel properties, playlist,
arrangement and UI. Plus a written finding for the tempo write.

**Architecture:** Controller actions grouped by area, each doing one thing well.
Server tools deliberately fewer than the actions: a tool surface is a prompt, and
twenty thin wrappers make the model do the domain reasoning and burn a round trip
per question. So `fl_get_eq(track=3)` returns all seven bands at once rather than
one tool per band property, and `fl_get_patterns()` returns every pattern with its
name, colour and length rather than a tool per field.

**Tech Stack:** The Phase 0 harness, the Phase 1 transport, the Phase 2 targeting,
pytest 9, ruff 0.16.

**Spec:** `ROADMAP.md` Phase 3, plus the README corrections it asks for.

## Global Constraints

Copied from ROADMAP.md, and implicitly part of every task:

- Python `>=3.10`, ruff `target-version = "py310"`, `ruff check .` clean, line
  length 100, rules `E`, `F`, `I`, `W`.
- `pytest` green with no FL Studio running.
- macOS and Windows must both keep working.
- No em dashes, no en dashes, no emoji anywhere. No AI attribution.
- Commits scoped to one concern.
- The controller script imports only FL modules plus `json`, `os`, `sys` and
  `pathlib`, and may not call `mkdir`, `makedirs`, `replace`, `rename`, `remove`,
  `unlink`, `glob`, `rglob`, `walk` or the builtin `open()`.
- Every mutating action is listed in `MUTATING_ACTIONS` so the `safeToEdit` guard
  covers it, and every action that needs a target uses `_require`.

### The tool surface this phase builds

Nine tools, not forty. Each one answers a question a producer would ask.

| Tool | Answers |
| --- | --- |
| `fl_get_patterns()` | What patterns exist, what are they called, how long are they, which is current |
| `fl_set_pattern()` | Rename, recolour, select, clone, or create a pattern |
| `fl_get_eq(track)` | All seven bands of a mixer track's EQ |
| `fl_set_eq(track, bands)` | Set several bands in one call |
| `fl_get_routing(track=None)` | What a track sends to, and what sends to it |
| `fl_set_routing(track, sends)` | Route a track to several destinations with levels |
| `fl_get_levels(tracks=None, samples=1)` | Peak levels per track, sampled |
| `fl_get_channel_properties(index)` | Type, pitch, and the rest of what a channel exposes |
| `fl_set_channel_properties(index, ...)` | Pitch and quantize |
| `fl_get_playlist_tracks()` | Playlist track names, colours, mute and solo |
| `fl_set_playlist_track()` | Rename, recolour, mute or solo a playlist track |
| `fl_get_markers()` | Arrangement markers and the selection |
| `fl_add_marker(time, name)` | Place a marker |
| `fl_get_ui_state()` | Which windows are open, what has focus, the snap mode |

That is fourteen, which is still far fewer than the fifty-odd stub functions they
cover, and each one replaces several round trips.

---

### Task 1: Fake modules for patterns, playlist, arrangement and UI

**Files:**
- Modify: `tests/fakes/project.py`
- Modify: `tests/fakes/modules/patterns.py`, `playlist.py`, `arrangement.py`, `ui.py`
- Test: `tests/test_fakes_phase3.py`

**Interfaces:**
- Consumes: the Phase 0 `FakeProject`.
- Produces: fake modules covering every function this phase calls, so the control
  tests can run with no FL.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_fakes_phase3.py
"""The fakes have to cover what Phase 3 calls, or the tests prove nothing.

Each of these asserts on the project model rather than on the fake's own
bookkeeping, so a fake that records a call without changing state fails here.
"""

from __future__ import annotations

import pytest


def test_patterns_carry_name_colour_and_length(fl_env):
    patterns = fl_env.modules["patterns"]
    assert patterns.patternCount() == 1
    patterns.setPatternName(0, "Verse")
    assert patterns.getPatternName(0) == "Verse"
    patterns.setPatternColor(0, 0x123456)
    assert patterns.getPatternColor(0) == 0x123456
    assert patterns.getPatternLength(0) > 0


def test_cloning_a_pattern_adds_one_and_names_it(fl_env):
    patterns = fl_env.modules["patterns"]
    patterns.setPatternName(0, "Verse")
    new_index = patterns.clonePattern(0)
    assert patterns.patternCount() == 2
    assert new_index == 1
    assert "Verse" in patterns.getPatternName(1)


def test_selecting_a_pattern_moves_the_current_one(fl_env):
    patterns = fl_env.modules["patterns"]
    patterns.clonePattern(0)
    patterns.selectPattern(1)
    assert patterns.patternNumber() == 1
    assert patterns.isPatternSelected(1) is True


def test_playlist_tracks_report_their_properties(fl_env):
    playlist = fl_env.modules["playlist"]
    playlist.setTrackName(1, "Drums")
    playlist.setTrackColor(1, 0x00FF00)
    playlist.muteTrack(1, 1)
    playlist.soloTrack(2, 1)
    assert playlist.getTrackName(1) == "Drums"
    assert playlist.getTrackColor(1) == 0x00FF00
    assert playlist.isTrackMuted(1) is True
    assert playlist.isTrackSolo(2) is True


def test_markers_are_recorded_and_named(fl_env):
    arrangement = fl_env.modules["arrangement"]
    arrangement.addAutoTimeMarker(384, "Drop")
    arrangement.addAutoTimeMarker(768, "Break")
    assert arrangement.getMarkerName(0) == "Drop"
    assert arrangement.getMarkerName(1) == "Break"
    assert arrangement.selectionStart() == 0


def test_ui_reports_visibility_and_focus(fl_env):
    ui = fl_env.modules["ui"]
    ui.showWindow(3)
    assert ui.getVisible(3) is True
    ui.hideWindow(3)
    assert ui.getVisible(3) is False
    ui.setFocused(3)
    assert ui.getFocused(3) is True


def test_the_fakes_still_refuse_a_playlist_clip_function(fl_env):
    """This phase adds playlist tools, so the absence must stay pinned."""
    playlist = fl_env.modules["playlist"]
    for forbidden in ("add", "insert", "create", "addClip", "insertClip", "placeClip"):
        assert not hasattr(playlist, forbidden), f"the fake gained {forbidden}()"
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/test_fakes_phase3.py -v`
Expected: failures where the fakes are thin, for example `setPatternName` not
changing what `getPatternName` returns, or `playlist_tracks` being tuples that
cannot hold a name change.

- [ ] **Step 3: Make the fakes model the properties**

`tests/fakes/project.py`: replace the playlist tuple with a dataclass, because
four positional fields are already hard to read and this phase adds more:

```python
@dataclass
class PlaylistTrack:
    """A playlist track. Not a mixer track: FL keeps them separate."""

    name: str
    color: int = 0x808080
    muted: bool = False
    solo: bool = False
    selected: bool = False
```

Add to `FakeProject.__init__`:

```python
        self.playlist_tracks: list[PlaylistTrack] = []
        self.selected_pattern = 0
```

`tests/fakes/modules/playlist.py`: use the dataclass, and add `isTrackSelected`,
`selectTrack`, `getTrackActivityLevel`, `getSongStartTickPos` and
`getPerformanceModeState`.

`tests/fakes/modules/patterns.py`: make `selectPattern` set both
`current_pattern` and `selected_pattern`, make `clonePattern` copy the name and
length, and add `setPatternColor`, `getPatternLength`, `isPatternDefault`.

`tests/fakes/modules/arrangement.py`: cover `addAutoTimeMarker`, `getMarkerName`,
`currentTime`, `selectionStart`, `selectionEnd`, `jumpToMarker`.

`tests/fakes/modules/ui.py`: cover `showWindow`, `hideWindow`, `getVisible`,
`getFocused`, `setFocused`, `getFocusedFormCaption`, `getSnapMode`, `setSnapMode`,
`showNotification`.

`tests/conftest.py`: `make_project` builds `PlaylistTrack` objects.

- [ ] **Step 4: Run them and watch them pass**

Run: `uv run pytest tests/test_fakes_phase3.py -v`
Expected: 7 passed.

- [ ] **Step 5: Run the whole suite and lint**

Run: `uv run pytest && uv run ruff check .`

- [ ] **Step 6: Commit**

```bash
git add tests/fakes tests/conftest.py tests/test_fakes_phase3.py
git commit -m "Model playlist tracks, patterns, markers and UI state in the fakes"
```

---

### Task 2: Patterns

**Files:**
- Modify: `fl_controller/device_FLStudioMCP.py`
- Create: `src/fl_studio_mcp/tools/patterns.py`
- Modify: `src/fl_studio_mcp/tools/__init__.py`, `src/fl_studio_mcp/server.py`
- Test: `tests/test_patterns.py`

**Interfaces:**
- Consumes: Task 1's fakes, `_require`.
- Produces:
  - Controller actions `patterns.getAll`, `patterns.setName`,
    `patterns.setColor`, `patterns.select`, `patterns.clone`,
    `patterns.createEmpty`.
  - `patterns.getAll` replies
    `{"patterns": [{"index", "name", "color", "length", "is_current", "is_default"}], "current": int}`.
  - `patterns.createEmpty` uses `patterns.findFirstNextEmptyPat(0)` followed by
    `patterns.setPatternName`, and replies
    `{"created": int, "name": str, "was_existing": bool}`.
  - Tools `fl_get_patterns()` and `fl_set_pattern(...)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_patterns.py
"""Patterns are FL's unit of work, and the server ignored them entirely.

The upstream README claimed they cannot be created. findFirstNextEmptyPat exists
in the stubs, and selecting the next empty pattern and writing into it is creation
in practice, so the claim is wrong and this covers it.
"""

from __future__ import annotations

import pytest


def test_get_all_patterns_lists_them_with_their_properties(fl_env):
    fl_env.controller.dispatch_command("patterns.setName", {"index": 0, "name": "Verse"})
    result = fl_env.controller.dispatch_command("patterns.getAll", {})
    assert len(result["patterns"]) == 1
    entry = result["patterns"][0]
    assert entry["index"] == 0
    assert entry["name"] == "Verse"
    assert entry["length"] > 0
    assert entry["is_current"] is True


def test_set_name_changes_the_name(fl_env):
    fl_env.controller.dispatch_command("patterns.setName", {"index": 0, "name": "Drop"})
    assert fl_env.project.pattern(0).name == "Drop"


def test_set_color_writes_rrggbb(fl_env):
    fl_env.controller.dispatch_command(
        "patterns.setColor", {"index": 0, "color": 0x112233}
    )
    assert fl_env.project.pattern(0).color == 0x112233


def test_select_moves_the_current_pattern(fl_env):
    fl_env.controller.dispatch_command("patterns.clone", {"index": 0})
    fl_env.controller.dispatch_command("patterns.select", {"index": 1})
    assert fl_env.project.current_pattern == 1


def test_clone_adds_a_pattern_named_after_its_source(fl_env):
    fl_env.controller.dispatch_command("patterns.setName", {"index": 0, "name": "Verse"})
    result = fl_env.controller.dispatch_command("patterns.clone", {"index": 0})
    assert result["cloned"] == 1
    assert "Verse" in fl_env.project.pattern(1).name


def test_create_empty_makes_one_when_the_project_is_full(fl_env):
    result = fl_env.controller.dispatch_command("patterns.createEmpty", {})
    assert result["created"] == 1, "pattern 0 is in use, so a new one is needed"
    assert fl_env.project.pattern(1).name


def test_create_empty_reuses_a_pattern_that_already_exists(fl_env):
    """Creating an empty pattern twice must not consume two slots."""
    first = fl_env.controller.dispatch_command("patterns.createEmpty", {})
    second = fl_env.controller.dispatch_command("patterns.createEmpty", {})
    assert second["created"] == first["created"]
    assert second["was_existing"] is True


def test_pattern_actions_need_an_index(fl_env):
    for action in ("patterns.setName", "patterns.setColor", "patterns.select",
                   "patterns.clone"):
        result = fl_env.controller.dispatch_command(action, {})
        assert "error" in result, f"{action} accepted no index"
        assert "index" in result["error"]


def test_a_mutating_pattern_action_is_refused_when_not_safe_to_edit(fl_env):
    fl_env.project.safe_to_edit = False
    result = fl_env.controller.dispatch_command(
        "patterns.setName", {"index": 0, "name": "Nope"}
    )
    assert "error" in result
    assert "safe to edit" in result["error"].lower()


def test_reads_are_not_refused(fl_env):
    fl_env.project.safe_to_edit = False
    assert "error" not in fl_env.controller.dispatch_command("patterns.getAll", {})
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/test_patterns.py -v`
Expected: `Unknown action: patterns.getAll`.

- [ ] **Step 3: Add the controller actions**

Add `import patterns` to the controller's FL imports, add the dispatch branches,
and implement the handlers. `createEmpty` must report whether it reused a slot:

```python
def handle_patterns_create_empty(params: dict) -> dict:
    """Create a pattern, or select the next empty one.

    patterns.findFirstNextEmptyPat exists in the stubs, which is why "cannot
    create patterns" was overstated: selecting the next empty slot and writing
    into it is creation in practice. The name is set explicitly so a new pattern
    is identifiable rather than called "Pattern 5".
    """
    before = patterns.patternCount()
    index = patterns.findFirstNextEmptyPat(0)
    was_existing = index < before
    if was_existing:
        return {
            "created": index,
            "name": patterns.getPatternName(index),
            "was_existing": True,
        }
    name = params.get("name") or ("Pattern %d" % (index + 1))
    patterns.setPatternName(index, name)
    return {"created": index, "name": name, "was_existing": False}
```

- [ ] **Step 4: Run them and watch them pass**

Run: `uv run pytest tests/test_patterns.py -v`
Expected: 10 passed.

- [ ] **Step 5: Add the server tools**

`src/fl_studio_mcp/tools/patterns.py`, following the shape of
`tools/batch.py`: functions that do the work, and a `register_pattern_tools`
that wraps them as tools with docstrings written for the model.

`fl_get_patterns()` returns the whole list plus which is current, so one call
answers "what is in this project".

`fl_set_pattern(index, name=None, color=None, select=False, clone=False)` is one
tool rather than four, because they are all "change this pattern" and a model that
has the index does not need to pick a different tool per field. Document that
`clone=True` ignores the other arguments and returns the new index.

- [ ] **Step 6: Run the whole suite and lint**

Run: `uv run pytest && uv run ruff check .`

- [ ] **Step 7: Copy into FL and check the reads live**

```bash
cp fl_controller/device_FLStudioMCP.py \
   ~/Documents/Image-Line/FL\ Studio/Settings/Hardware/FLStudioMCP/device_FLStudioMCP.py
uv run python -c "
from fl_studio_mcp.utils.midi_connection import get_connection
conn = get_connection(); conn.connect()
import json
print(json.dumps(conn.send_command('patterns.getAll', {}, timeout=3.0), indent=2))
"
```

Expected: the real pattern list. Read-only. Do not run `createEmpty` or `clone`
against the user's project without asking.

- [ ] **Step 8: Commit**

```bash
git add fl_controller/device_FLStudioMCP.py src/fl_studio_mcp/tools/patterns.py \
        src/fl_studio_mcp/tools/__init__.py src/fl_studio_mcp/server.py tests/test_patterns.py
git commit -m "Add patterns, the unit of work the server ignored"
```

---

### Task 3: Mixer EQ

**Files:**
- Modify: `fl_controller/device_FLStudioMCP.py`
- Create: `src/fl_studio_mcp/tools/eq.py`
- Test: `tests/test_eq.py`

**Interfaces:**
- Consumes: `_require`.
- Produces:
  - Controller actions `mixer.getEq` and `mixer.setEqBands`.
  - `mixer.getEq` replies `{"track": int, "band_count": int,
    "bands": [{"band", "gain", "frequency", "bandwidth"}]}`, so one call returns
    the whole EQ rather than one round trip per property per band.
  - `mixer.setEqBands` takes
    `{"track": int, "bands": [{"band": int, "gain"?: float, "frequency"?: float, "bandwidth"?: float}]}`
    and replies with the EQ read back.
  - Tools `fl_get_eq(track)` and `fl_set_eq(track, bands)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_eq.py
"""EQ is seven bands per track, which is why it is one tool and not twenty one.

mixer.getEqBandCount reports the band count rather than it being assumed, because
a hardcoded seven would be wrong on a version that changed it.
"""

from __future__ import annotations

import pytest


def test_get_eq_returns_every_band(fl_env):
    result = fl_env.controller.dispatch_command("mixer.getEq", {"track": 1})
    assert result["track"] == 1
    assert result["band_count"] == 7
    assert len(result["bands"]) == 7
    assert [b["band"] for b in result["bands"]] == list(range(7))


def test_get_eq_reports_gain_frequency_and_bandwidth(fl_env):
    fl_env.project.track(1).eq_gains[2] = 0.75
    result = fl_env.controller.dispatch_command("mixer.getEq", {"track": 1})
    band = next(b for b in result["bands"] if b["band"] == 2)
    assert band["gain"] == pytest.approx(0.75)
    assert band["frequency"] is not None
    assert band["bandwidth"] is not None


def test_set_eq_bands_writes_only_what_was_named(fl_env):
    """A band the caller did not mention must not be reset."""
    fl_env.project.track(1).eq_gains[0] = 0.5
    fl_env.controller.dispatch_command("mixer.setEqBands", {
        "track": 1,
        "bands": [{"band": 3, "gain": 0.25}],
    })
    assert fl_env.project.track(1).eq_gains[3] == pytest.approx(0.25)
    assert fl_env.project.track(1).eq_gains[0] == pytest.approx(0.5), "band 0 was reset"


def test_set_eq_bands_reads_the_result_back(fl_env):
    result = fl_env.controller.dispatch_command("mixer.setEqBands", {
        "track": 1,
        "bands": [{"band": 1, "gain": 0.9, "frequency": 0.4, "bandwidth": 0.6}],
    })
    band = next(b for b in result["bands"] if b["band"] == 1)
    assert band["gain"] == pytest.approx(0.9)
    assert band["frequency"] == pytest.approx(0.4)
    assert band["bandwidth"] == pytest.approx(0.6)


def test_set_eq_sets_several_bands_in_one_call(fl_env):
    fl_env.controller.dispatch_command("mixer.setEqBands", {
        "track": 2,
        "bands": [{"band": 0, "gain": 0.1}, {"band": 6, "gain": 0.9}],
    })
    assert fl_env.project.track(2).eq_gains[0] == pytest.approx(0.1)
    assert fl_env.project.track(2).eq_gains[6] == pytest.approx(0.9)


def test_get_eq_needs_a_track(fl_env):
    result = fl_env.controller.dispatch_command("mixer.getEq", {})
    assert "error" in result
    assert "track" in result["error"]


def test_an_out_of_range_band_is_refused(fl_env):
    result = fl_env.controller.dispatch_command("mixer.setEqBands", {
        "track": 1, "bands": [{"band": 99, "gain": 0.5}],
    })
    assert "error" in result
    assert "99" in result["error"]


def test_eq_writes_are_refused_when_not_safe_to_edit(fl_env):
    fl_env.project.safe_to_edit = False
    result = fl_env.controller.dispatch_command("mixer.setEqBands", {
        "track": 1, "bands": [{"band": 0, "gain": 0.5}],
    })
    assert "error" in result
    assert "safe to edit" in result["error"].lower()


def test_eq_reads_are_not_refused(fl_env):
    fl_env.project.safe_to_edit = False
    assert "error" not in fl_env.controller.dispatch_command("mixer.getEq", {"track": 1})
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/test_eq.py -v`
Expected: `Unknown action: mixer.getEq`.

- [ ] **Step 3: Add the controller actions**

Read `mixer.getEqBandCount()` rather than assuming seven. Wrap each band read so
one bad band does not lose the other six, and report which ones failed.

- [ ] **Step 4: Run them and watch them pass, then add `fl_get_eq` and `fl_set_eq`**

Run: `uv run pytest tests/test_eq.py -v`

- [ ] **Step 5: Run the whole suite and lint, then verify the read live**

```bash
uv run pytest && uv run ruff check .
cp fl_controller/device_FLStudioMCP.py \
   ~/Documents/Image-Line/FL\ Studio/Settings/Hardware/FLStudioMCP/device_FLStudioMCP.py
uv run python -c "
from fl_studio_mcp.utils.midi_connection import get_connection
conn = get_connection(); conn.connect()
for track in (0, 1):
    r = conn.send_command('mixer.getEq', {'track': track}, timeout=3.0)
    print(track, r.get('band_count'), r.get('bands'))
"
```

Expected: a real band count from FL, which may not be seven. Record what it is.

- [ ] **Step 6: Commit**

```bash
git add fl_controller/device_FLStudioMCP.py src/fl_studio_mcp/tools/eq.py \
        src/fl_studio_mcp/tools/__init__.py src/fl_studio_mcp/server.py tests/test_eq.py
git commit -m "Add mixer EQ, read and written as a set of bands"
```

---

### Task 4: Routing and metering

**Files:**
- Modify: `fl_controller/device_FLStudioMCP.py`
- Create: `src/fl_studio_mcp/tools/routing.py`
- Test: `tests/test_routing.py`, `tests/test_metering.py`

**Interfaces:**
- Consumes: `_require`.
- Produces:
  - Controller actions `mixer.getRouting`, `mixer.setRouting`, `mixer.getLevels`.
  - `mixer.getRouting` replies
    `{"track", "name", "sends": [{"track", "name", "level", "active"}]}` for the
    tracks this one sends to.
  - `mixer.setRouting` takes `{"track", "sends": [{"track", "level"?: float, "remove"?: bool}]}`
    and replies with the routing read back.
  - `mixer.getLevels` takes `{"tracks"?: [int], "samples"?: int}` and replies
    `{"levels": [{"track", "name", "peak"}]}`, where peak is the maximum seen
    across the samples.
  - Tools `fl_get_routing`, `fl_set_routing`, `fl_get_levels`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_routing.py
"""Routing is how FL gets from channels to inserts, and the server ignored it."""

from __future__ import annotations

import pytest


def test_get_routing_lists_the_destinations(fl_env):
    fl_env.project.track(1).routes = {0: 1.0}
    result = fl_env.controller.dispatch_command("mixer.getRouting", {"track": 1})
    assert result["track"] == 1
    assert [s["track"] for s in result["sends"]] == [0]
    assert result["sends"][0]["active"] is True


def test_get_routing_reports_the_level(fl_env):
    fl_env.project.track(1).routes = {0: 0.5}
    result = fl_env.controller.dispatch_command("mixer.getRouting", {"track": 1})
    assert result["sends"][0]["level"] == pytest.approx(0.5)


def test_get_routing_can_report_every_track(fl_env):
    result = fl_env.controller.dispatch_command("mixer.getRouting", {})
    assert len(result["tracks"]) == 8
    assert "sends" in result["tracks"][0]


def test_set_routing_adds_a_send(fl_env):
    fl_env.controller.dispatch_command("mixer.setRouting", {
        "track": 1, "sends": [{"track": 3, "level": 0.4}],
    })
    assert fl_env.project.track(1).routes.get(3) == pytest.approx(0.4)


def test_set_routing_removes_a_send(fl_env):
    fl_env.project.track(1).routes = {3: 1.0}
    fl_env.controller.dispatch_command("mixer.setRouting", {
        "track": 1, "sends": [{"track": 3, "remove": True}],
    })
    assert 3 not in fl_env.project.track(1).routes


def test_set_routing_leaves_unmentioned_sends_alone(fl_env):
    fl_env.project.track(1).routes = {2: 1.0, 3: 1.0}
    fl_env.controller.dispatch_command("mixer.setRouting", {
        "track": 1, "sends": [{"track": 3, "remove": True}],
    })
    assert 2 in fl_env.project.track(1).routes


def test_set_routing_refuses_a_destination_that_does_not_exist(fl_env):
    result = fl_env.controller.dispatch_command("mixer.setRouting", {
        "track": 1, "sends": [{"track": 99, "level": 0.5}],
    })
    assert "error" in result
    assert "99" in result["error"]


def test_routing_writes_are_refused_when_not_safe_to_edit(fl_env):
    fl_env.project.safe_to_edit = False
    result = fl_env.controller.dispatch_command("mixer.setRouting", {
        "track": 1, "sends": [{"track": 3, "level": 0.5}],
    })
    assert "error" in result
    assert "safe to edit" in result["error"].lower()
```

```python
# tests/test_metering.py
"""Peaks are instantaneous, so sampling is the only way to learn anything.

mixer.getTrackPeaks returns the current value: 0.0 is silence, 1.0 is 0 dB, and
anything above 1.0 is clipping. One reading while stopped is always silence, which
is why the tool takes a sample count.
"""

from __future__ import annotations

import pytest


def test_levels_reports_a_peak_per_track(fl_env):
    result = fl_env.controller.dispatch_command(
        "mixer.getLevels", {"tracks": [0, 1]}
    )
    assert [entry["track"] for entry in result["levels"]] == [0, 1]
    assert all("peak" in entry for entry in result["levels"])


def test_levels_keeps_the_loudest_of_the_samples(fl_env):
    """A single reading would miss a peak between polls."""
    readings = iter([0.1, 0.9, 0.3])
    fl_env.modules["mixer"].getTrackPeaks = lambda index, mode: next(readings, 0.0)
    result = fl_env.controller.dispatch_command(
        "mixer.getLevels", {"tracks": [1], "samples": 3}
    )
    assert result["levels"][0]["peak"] == pytest.approx(0.9)


def test_levels_defaults_to_every_track(fl_env):
    result = fl_env.controller.dispatch_command("mixer.getLevels", {})
    assert len(result["levels"]) == 8


def test_levels_reports_clipping_distinctly(fl_env):
    fl_env.modules["mixer"].getTrackPeaks = lambda index, mode: 1.4
    result = fl_env.controller.dispatch_command("mixer.getLevels", {"tracks": [0]})
    assert result["levels"][0]["peak"] == pytest.approx(1.4)
    assert result["levels"][0]["clipping"] is True


def test_levels_reports_a_silent_track_as_not_clipping(fl_env):
    result = fl_env.controller.dispatch_command("mixer.getLevels", {"tracks": [0]})
    assert result["levels"][0]["clipping"] is False


def test_levels_refuses_a_track_that_does_not_exist(fl_env):
    result = fl_env.controller.dispatch_command("mixer.getLevels", {"tracks": [99]})
    assert "error" in result
    assert "99" in result["error"]


def test_levels_is_never_refused(fl_env):
    """Reading a meter changes nothing, and is exactly what a stuck user needs."""
    fl_env.project.safe_to_edit = False
    assert "error" not in fl_env.controller.dispatch_command("mixer.getLevels", {})
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/test_routing.py tests/test_metering.py -v`

- [ ] **Step 3: Implement, run to green, add the tools**

Note that metering needs the host to sample, not FL: the action returns one
reading per requested track, and `samples` makes the controller take several
readings back to back. It cannot wait between them, because the controller runs
inside FL's MIDI thread, so document that a caller wanting a longer window should
call it repeatedly during playback.

- [ ] **Step 4: Run the whole suite, lint, verify the reads live**

Reads only. Report the real routing and levels rather than changing anything.

- [ ] **Step 5: Commit**

```bash
git add fl_controller/device_FLStudioMCP.py src/fl_studio_mcp/tools/routing.py \
        src/fl_studio_mcp/tools/__init__.py src/fl_studio_mcp/server.py \
        tests/test_routing.py tests/test_metering.py
git commit -m "Add mixer routing and peak metering"
```

---

### Task 5: Channel properties, playlist, arrangement and UI

**Files:**
- Modify: `fl_controller/device_FLStudioMCP.py`
- Create: `src/fl_studio_mcp/tools/project.py`
- Test: `tests/test_project_tools.py`

**Interfaces:**
- Consumes: Tasks 1 to 4.
- Produces:
  - Controller actions `channels.getProperties`, `channels.setProperties`,
    `playlist.getAll`, `playlist.setTrack`, `arrangement.getMarkers`,
    `arrangement.addMarker`, `ui.getState`, `ui.showWindow`, `ui.hideWindow`.
  - Tools `fl_get_channel_properties`, `fl_set_channel_properties`,
    `fl_get_playlist_tracks`, `fl_set_playlist_track`, `fl_get_markers`,
    `fl_add_marker`, `fl_get_ui_state`, `fl_show_window`.

- [ ] **Step 1: Write the failing tests**

Cover, one test per behaviour:

- Channel properties report type, pitch, target FX track, mute, solo, selected.
- Setting pitch writes it, and reading it back matches.
- `quickQuantize` is callable and reported.
- Playlist tracks report name, colour, mute, solo, and are independent of mixer
  tracks, which is the distinction a generic DAW tool gets wrong.
- Setting a playlist track name does not rename the mixer track of the same index.
- Markers are added and read back with their names.
- UI state reports which windows are visible and what has focus.
- Every mutating action is refused when `safe_to_edit` is False.
- Every action that needs a target names the missing field.

- [ ] **Step 2: Run them and watch them fail**

- [ ] **Step 3: Implement, run to green, add the tools**

- [ ] **Step 4: Run the whole suite, lint, verify the reads live**

- [ ] **Step 5: Commit**

```bash
git add fl_controller/device_FLStudioMCP.py src/fl_studio_mcp/tools/project.py \
        src/fl_studio_mcp/tools/__init__.py src/fl_studio_mcp/server.py \
        tests/test_project_tools.py
git commit -m "Add channel properties, playlist, arrangement markers and UI state"
```

---

### Task 6: The tempo write, as a spike

**Files:**
- Create: `docs/spikes/2026-09-19-T1-tempo-write.md`
- Modify: `fl_controller/device_FLStudioMCP.py`
- Test: `tests/test_tempo.py`

**Interfaces:**
- Consumes: `midi.REC_Tempo`, `midi.REC_UpdateValue`, `midi.REC_UpdateControl`.
- Produces: a written finding. Whether a `fl_set_tempo` tool ships depends on it.

- [ ] **Step 1: Write the spike probe as a controller action**

`system.tempoProbe`, params `{"bpm": float, "restore"?: bool}`, which:

1. Reads the tempo with `mixer.getCurrentTempo()`.
2. Calls `general.processRECEvent(midi.REC_Tempo, int(bpm * 1000), flags)`.
3. Reads the tempo back.
4. Reports both readings and which flags were tried.

The action must be read-mostly: it changes tempo, so it is only ever called
deliberately with the user's agreement, and it restores the original when
`restore` is true.

- [ ] **Step 2: Write the test that pins the report shape**

The finding is the deliverable, so the test asserts the action reports the before
value, the after value and the flags, not that the write works. A test that
asserted the write works would encode a guess.

- [ ] **Step 3: Ask the user before running it live**

This changes project tempo. Ask, run it with `restore=True`, and confirm the tempo
is back where it started.

- [ ] **Step 4: Write the finding**

`docs/spikes/2026-09-19-T1-tempo-write.md`, in the shape of the T4 write-up:
what the stubs say, what was measured, and the conclusion including whether to
ship a tool. Record that `general.processRECEvent`'s own stub says to try other
functions first because that part of the API is incomplete and buggy, and that no
other tempo setter exists.

- [ ] **Step 5: Commit**

```bash
git add fl_controller/device_FLStudioMCP.py docs/spikes tests/test_tempo.py
git commit -m "Resolve spike T1, the tempo write"
```

---

### Task 7: README corrections and the tool tables

**Files:**
- Modify: `README.md`
- Test: `tests/test_docs.py`

**Interfaces:**
- Consumes: Tasks 2 to 5.
- Produces: a README that describes what the server does now.

- [ ] **Step 1: Write the failing tests**

```python
def test_the_readme_no_longer_claims_patterns_cannot_be_created():
    text = (REPO_ROOT / "README.md").read_text().lower()
    assert "cannot create patterns" not in text
    assert "findfirstnextemptypat" in text


def test_the_readme_says_tempo_is_readable():
    text = (REPO_ROOT / "README.md").read_text().lower()
    assert "tempo" in text


def test_the_readme_lists_the_new_tool_areas():
    text = (REPO_ROOT / "README.md").read_text().lower()
    for area in ("pattern", "eq", "routing", "meter", "playlist", "marker"):
        assert area in text, f"the README never mentions {area}"


def test_the_readme_keeps_the_real_limitations():
    text = (REPO_ROOT / "README.md").read_text().lower()
    assert "cannot load" in text, "the plugin limit is real and must stay"
    assert "playlist" in text
```

- [ ] **Step 2: Run them and watch them fail**

- [ ] **Step 3: Correct the README and fill in the tool tables**

Add a row for every new tool, with what it answers rather than what it wraps.

- [ ] **Step 4: Run them and watch them pass, then the whole suite**

- [ ] **Step 5: Commit**

```bash
git add README.md tests/test_docs.py
git commit -m "Correct the README and document the new tool areas"
```

---

## Phase 3 exit criteria

The roadmap's own bar, restated so it can be checked rather than believed:

- [ ] Every area in the roadmap's table has controller actions, tests against the
      fake harness, and a row in the README tool tables.
- [ ] The tool count stays well below the function count, and the plan says why
      for each grouping.
- [ ] A mutating action in every new area is refused when `safeToEdit` is false.
- [ ] An action in every new area names the missing field rather than defaulting.
- [ ] The tempo write has a written finding, whether or not a tool ships.
- [ ] `pytest` green and `ruff check .` clean with no FL Studio running.
- [ ] `docs/SMOKE_TEST.md` records the live reads, and says which writes were not
      attempted on the user's open project.

## What Phase 3 deliberately does not do

- It does not ship a tempo write tool on the strength of the stubs. The only
  function that could do it documents itself as incomplete and buggy, so the
  finding comes first.
- It does not attempt `mixer.automateEvent`, which is spike T3 and marked
  "HELP WANTED" upstream. Automation writing is a separate investigation.
- It does not build arrangement by placing clips, because `playlist` has no such
  function. Markers and live clips remain the ceiling.
