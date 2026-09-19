# Phase 5: Gain Staging and Mix Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `fl_mix_review()` returns actionable findings on a real project, and a
gain staging pass can act on them.

**Architecture:** Three layers, split so the decisions are testable with no FL.

The controller gains one batched reader that returns every mixer track's settings
in a single round trip, because a review needs all of them and one call per track
would be the twenty round trips Phase 4 deleted.

The server owns the sampling, because sampling is about time and the controller
runs on FL's MIDI thread where waiting would stall the audio engine. The host reads
peaks, sleeps, and reads again, which is the only way to catch a peak that happens
between two polls.

The analysis is pure functions over the sampled data and the settings. Clipping,
silence, an unused send, a fader that was never touched: all of it is arithmetic,
so all of it is tested against the fake with no FL Studio running.

**Tech Stack:** The Phase 0 harness, the Phase 1 transport, the Phase 3 mixer
readers, pytest 9, ruff 0.16.

**Spec:** `ROADMAP.md` Phase 5, plus the "Tabled" section for what this deliberately
does not measure.

## Global Constraints

Copied from ROADMAP.md, and implicitly part of every task:

- Python `>=3.10`, ruff `target-version = "py310"`, `ruff check .` clean, line
  length 100, rules `E`, `F`, `I`, `W`.
- `pytest` green with no FL Studio running.
- macOS and Windows must both keep working.
- No em dashes, no en dashes, no emoji anywhere. No AI attribution.
- Commits scoped to one concern.
- Do not disrupt the open project. The review is read-only. The gain staging pass
  changes faders, so it requires the caller to ask for it explicitly, and it must be
  able to report what it would do without doing it.

### What this phase measures, and what it does not

`mixer.getTrackPeaks` returns the peak right now: 0.0 is silence, 1.0 is 0 dB, above
1.0 is clipping. Sampling it during playback gives a peak hold per track. That is
enough to find what clips and what never sounds.

It is not loudness. There is no LUFS, no RMS, no spectral balance and no frequency
content, because all of those need the audio itself, and the tabled loopback capture
is still tabled. Every tool in this phase says so in its docstring, so nobody reads a
peak hold as a loudness measurement. Peak and loudness disagree in both directions: a
spiky drum bus peaks high and sounds quiet, a compressed pad peaks low and sounds
loud.

---

### Task 1: One batched read of every mixer track

**Files:**
- Modify: `fl_controller/device_FLStudioMCP.py`
- Test: `tests/test_mixer_snapshot.py`

**Interfaces:**
- Consumes: the existing mixer handlers.
- Produces: controller action `mixer.getSnapshot`, params `{"include_empty": bool}`,
  replying `{"tracks": [{"index", "name", "volume", "pan", "is_muted", "is_solo",
  "is_armed", "stereo_separation", "color", "sends": [int], "volume_db"}],
  "track_count": int}`. One round trip for the whole mixer, because a review needs
  all of it.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_mixer_snapshot.py
"""A review needs every track's settings, so it must not be one call per track.

Phase 4 deleted twenty round trips from the project description for exactly this
reason, and a mix review with one call per track would put them back.
"""

from __future__ import annotations

import pytest


def test_the_snapshot_reports_every_track(fl_env):
    result = fl_env.controller.dispatch_command("mixer.getSnapshot", {})
    assert result["track_count"] == 8
    assert len(result["tracks"]) == 8


def test_the_snapshot_reports_volume_pan_and_state(fl_env):
    fl_env.project.track(1).volume = 0.5
    fl_env.project.track(1).pan = -0.3
    fl_env.project.track(1).muted = True
    entry = next(
        t for t in fl_env.controller.dispatch_command("mixer.getSnapshot", {})["tracks"]
        if t["index"] == 1
    )
    assert entry["volume"] == pytest.approx(0.5)
    assert entry["pan"] == pytest.approx(-0.3)
    assert entry["is_muted"] is True


def test_the_snapshot_reports_loudness_units(fl_env):
    """A fader value means nothing without knowing how hot the signal is."""
    result = fl_env.controller.dispatch_command("mixer.getSnapshot", {})
    assert all("volume_db" in track for track in result["tracks"])


def test_the_snapshot_reports_where_a_track_sends(fl_env):
    fl_env.project.track(1).routes = {0: 0.8}
    entry = next(
        t for t in fl_env.controller.dispatch_command("mixer.getSnapshot", {})["tracks"]
        if t["index"] == 1
    )
    assert entry["sends"] == [0]


def test_the_snapshot_names_every_track(fl_env):
    result = fl_env.controller.dispatch_command("mixer.getSnapshot", {})
    assert result["tracks"][0]["name"] == "Master"


def test_a_snapshot_is_a_single_round_trip(fl_env):
    """The whole point. More than one command and it is not a snapshot."""
    before = fl_env.trigger_count
    fl_env.controller.dispatch_command("mixer.getSnapshot", {})
    assert fl_env.trigger_count == before, "the controller was called directly"
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/test_mixer_snapshot.py -v`
Expected: `Unknown action: mixer.getSnapshot`.

- [ ] **Step 3: Implement**

Read each track's properties guarded, so one unreadable property does not lose the
whole mixer. Include `volume_db` from `mixer.getTrackVolume(index, 1)`, and the sends
by asking each candidate whether it is an active send, which is what the routing
snapshot already does.

- [ ] **Step 4: Run to green, then the whole suite and lint**

- [ ] **Step 5: Commit**

```bash
git commit -m "Read the whole mixer in one round trip"
```

---

### Task 2: The sampling loop, on the host

**Files:**
- Create: `src/fl_studio_mcp/tools/metering.py`
- Test: `tests/test_sampling.py`

**Interfaces:**
- Consumes: Task 1's snapshot, the Phase 3 levels action.
- Produces:
  - `sample_peaks(duration=4.0, interval=0.05, tracks=None) -> dict` returning
    `{"success", "samples", "levels": [{"track", "name", "peak", "clipping"}],
      "transport": {"is_playing", "is_recording"}, "duration"}`.
  - Tool `fl_sample_levels(duration=4.0, tracks=None)`.

- [ ] **Step 1: Write the failing tests**

The properties that matter:

- Sampling while the transport is stopped is refused, because every reading would be
  zero and that reads as "everything is silent" rather than "nothing is playing".
  This is the single most important behaviour in the phase: a review run on a stopped
  transport would confidently report that the whole mix never sounds.
- The peak per track is the loudest reading across all samples, not the last.
- The number of samples actually taken is reported, so a caller can tell a four
  second window from a one sample fluke.
- A track that clips in one sample out of twenty is reported as clipping.
- The transport state is reported as it was, so a caller knows whether the reading
  was during playback.
- The interval is respected: a test with a fake clock asserts the sleeps happened,
  because a loop that reads as fast as it can is the Phase 3 behaviour that cannot
  sample over time at all.

- [ ] **Step 2: Run and watch them fail**

- [ ] **Step 3: Implement, run to green**

Use `time.sleep` between reads. Document that the sleep is on the host and not in the
controller, because sleeping in the controller would stall FL's MIDI thread, which is
why the Phase 3 action reads back to back.

- [ ] **Step 4: Verify live, with the user playing the project**

Ask the user to start playback, then sample. Expect non-zero peaks on tracks that are
sounding. Record what the Master peaks at, because that is the number the whole phase
is built on.

- [ ] **Step 5: Commit**

```bash
git commit -m "Sample peak levels over time from the host"
```

---

### Task 3: The findings, as pure functions

**Files:**
- Create: `src/fl_studio_mcp/musical/analysis.py`
- Test: `tests/test_analysis.py`

**Interfaces:**
- Consumes: Task 1's snapshot shape and Task 2's level shape.
- Produces:
  - `find_peaks(levels) -> list[dict]` for what clips and what never sounds.
  - `review_mix(snapshot, levels=None) -> dict` with `findings` and a `summary`.
  - `plan_gain_staging(snapshot, levels, target=-3.0) -> dict` with the moves it
    would make and the reason for each.

- [ ] **Step 1: Write the failing tests**

Each finding gets a test for the case that should produce it and the case that should
not, because a review that flags everything is as useless as one that flags nothing:

- A track above 1.0 is reported as clipping, naming the peak.
- A track at exactly 1.0 is not clipping, because 1.0 is 0 dB and that is the
  ceiling rather than over it.
- A track that never rose above silence is reported as never sounding, but only when
  something is routed to it, because an unused insert is not a finding.
- The Master is never reported as never sounding, because a silent master means
  nothing is playing rather than a routing problem.
- A muted track at silence is not reported as never sounding, because the reason is
  known already.
- A send to a track that never sounds is reported, because that is a dead end.
- Findings are ordered by severity, so the caller reads the clipping first.
- Every finding names the track, so a caller can act without a second lookup.
- Silences are reported as informational and clipping as a problem, so a caller can
  filter.
- `plan_gain_staging` proposes no move for a track already under the target.
- `plan_gain_staging` proposes a trim for a track above the target, and the trim
  direction is down.
- `plan_gain_staging` never proposes a move that would exceed the fader's range.
- `plan_gain_staging` with no levels returns nothing to do rather than guessing.
- A review with no levels still reports the setting findings, because those do not
  need playback.

- [ ] **Step 2: Run, watch them fail, implement, run to green**

- [ ] **Step 3: Commit**

```bash
git commit -m "Add mix findings and a gain staging plan, as pure functions"
```

---

### Task 4: The tools

**Files:**
- Create: `src/fl_studio_mcp/tools/review.py`
- Test: `tests/test_review_tools.py`

**Interfaces:**
- Consumes: Tasks 1 to 3.
- Produces:
  - Tool `fl_mix_review(sample_seconds=4.0)`.
  - Tool `fl_gain_staging(target_db=-3.0, apply=False, sample_seconds=4.0)`.

- [ ] **Step 1: Write the failing tests**

- `fl_mix_review` is read-only: it sends no mutating command, asserted by counting
  the commands and checking them against `MUTATING_ACTIONS`.
- `fl_mix_review` works with the transport stopped, reporting the setting findings
  and saying that the level findings need playback, rather than failing.
- `fl_gain_staging` with `apply=False` reports the moves and changes nothing,
  asserted on the project state.
- `fl_gain_staging` with `apply=True` applies them through `fl_batch`, so the whole
  pass is one undo step.
- `fl_gain_staging` refuses to apply when nothing needs moving.
- `fl_gain_staging` names the moves it made in the reply.

- [ ] **Step 2: Run, watch them fail, implement, run to green**

- [ ] **Step 3: Run the whole suite and lint**

- [ ] **Step 4: Verify live, read-only only**

Run `fl_mix_review` against the open project with the user's playback. Do not run the
applying form on their project: it moves their faders. Report what the review found,
and say plainly that the applying path was not run on their work.

- [ ] **Step 5: Commit**

```bash
git commit -m "Add the mix review and gain staging tools"
```

---

### Task 5: Documentation and the exit criteria

**Files:**
- Modify: `README.md`, `docs/SMOKE_TEST.md`
- Modify: `docs/plans/2026-09-19-phase-5-gain-staging.md`
- Test: `tests/test_docs.py`

- [ ] **Step 1: Add the README rows and a section stating what a peak measurement is
      and is not, because the tabled loopback work is what would give loudness.**

- [ ] **Step 2: Add smoke test items for the parts only a human can check, which is
      whether the findings match what the producer hears.**

- [ ] **Step 3: Record the live run, then commit.**

---

## Phase 5 exit criteria

- [x] `fl_mix_review()` returns actionable findings on a real project, verified live.
      One problem finding, a clipping Master, plus two informational findings that are
      both correct for that project.
- [x] Sampling is refused while the transport is stopped, so a review can never
      report a silent mix as a routing problem. Verified live, and it is the first
      thing the live run did.
- [x] The findings are ordered by severity and name the track.
- [x] `fl_gain_staging(apply=False)` reports moves without making them, and a test
      asserts the project is untouched.
- [x] `pytest` green and `ruff check .` clean with no FL Studio running. 653 tests.
- [x] The README says what a peak hold is not, so nobody reads it as loudness.
- [x] `docs/SMOKE_TEST.md` records the live run and says the applying path was not
      run against the user's project.

### What the live run corrected

| Assumption | What the live run showed |
| --- | --- |
| Two decimals are enough to show a peak over the ceiling | A peak of 1.004 prints as 1.00, which is the exact value this code calls not clipping, so the finding argued with its own threshold |
| The transport state read after the window describes the window | 60 readings of real audio came back beside `is_playing: false`, because playback ended inside the window |
| The sampler's clipping flag and the review's threshold are separate decisions | They are one boundary. Two copies drift, so the sampler now imports `CLIP_THRESHOLD` |

One of these was catchable without FL. The rounding is arithmetic, and a unit test
with a peak of 1.004 would have caught it, which is worth stating because the other
two needed the live run: nothing about a fake project tells you when a real transport
stops, or what a real peak holds at. The phase's own lesson stands, that a fake is
written from the same understanding as the code and cannot correct that
understanding. What this run adds is that a message is part of the measurement. Both
live defects were cases where the numbers were right and the sentence describing them
was wrong, and the sentence is what a producer reads.

## What Phase 5 deliberately does not do

- It does not measure loudness, frequency content or stereo width. Those need the
  audio, which means the tabled loopback capture, and the roadmap tabled it on
  purpose. Peak level is a real measurement and it is not a substitute.
- It does not read EQ. The roadmap's Phase 5 bullet lists EQ among what the review
  reads, and this plan narrowed that away: a boost or a cut is a mixing decision, and
  nothing about a band's settings says whether it is the wrong one. Reading EQ would
  produce findings that fire on every real mix, which is the same as no findings.
- It does not report duplicate routing. Two tracks sending to the same bus is
  ordinary practice rather than a defect, so the finding would need a definition of
  duplication that does not flag every drum bus in existence. The dead end that can be
  identified is already reported: a send into a track that never sounds.
- It does not run a gain staging pass on the user's open project without them asking.
- It does not chase automation. `mixer.automateEvent` is spike T3 and marked HELP
  WANTED upstream.
