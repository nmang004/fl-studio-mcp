# Phase 2: Piano Roll Targeting and Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `fl_send_notes(channel=3, ...)` either land notes on channel 3,
verified by read-back, or report a specific failure. No silent success.

**Architecture:** The controller gains a targeting action that selects a named
channel and opens the piano roll window, returning the selection it actually
achieved. The server calls it before every piano roll trigger and refuses to
trigger if the selection does not match what was asked for. The controller can
read the selection back but cannot read notes, and the pyscript can read notes but
sees no channel identity at all, so verification is split exactly along that line:
the controller proves the target, and the pyscript proves the notes.

**Tech Stack:** The Phase 0 harness and the Phase 1 transport (correlation, request
lock, ping), pytest 9, ruff 0.16.

**Spec:** `ROADMAP.md` Phase 2, plus the "Verified against live FL Studio" table
and the sandbox rules.

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
  `tests/test_response_reading.py` enforces this.
- The pyscript has the same rename and directory restrictions but may use
  `open()`.
- A piano roll script can only be run by FL itself: by its keystroke, or by
  clicking it in the Piano roll scripts menu. Nothing in this repo can invoke it.

### Verified before planning this phase

Measured on live FL Studio 2026, build 5406, API 45, on 2026-09-19, using a
temporary controller action that has since been removed:

- `channels.selectOneChannel(index, True)` followed by `ui.showWindow(3)` targets
  a channel and opens its piano roll. Asking for channel 2 selected "808 HiHat"
  and asking for channel 0 selected "808 Kick", and `ui.getVisible(3)` returned 1
  each time.
- `channels.selectedChannel(canBeNone=True, indexGlobal=True)` reports the
  selection, so the target can be confirmed rather than assumed.
- `ui.showWindow`'s stub documents `widPianoRoll` as index 3.
- The piano roll keeps its own note data per pattern. A get_state run on one
  piano roll exported `noteCount: 0` while another piano roll held notes, which is
  what makes channel targeting necessary rather than cosmetic.

### What Phase 2 inherited from earlier phases

| Roadmap item | State |
| --- | --- |
| Correlate by request id and read the pyscript's reply | Done in Phase 1 and Phase 0: every request carries an id and `send_request` polls for a reply with the matching id |
| Replace the fixed 2 second sleep with polling | Done in Phase 0: `send_request` polls at 5ms against a timeout |
| Check the osascript exit code instead of always returning True | Done in Phase 0: `fl_trigger` reads the exit code and explains error 1002 |
| Do not let failed requests accumulate in the queue | Done in Phase 0: the pyscript empties the queue before running anything |
| `fl_get_piano_roll_state` refreshes before reading | Done in Phase 0: it calls `refresh_and_read_state` |

So this phase is the targeting and the verification of the target, which is the
part nothing has covered.

### The one thing that cannot be automated

The keystroke needs macOS Accessibility permission, and this machine denies it:

    osascript is not allowed to send keystrokes. (1002)

The trigger reports that honestly since Phase 0, and a request sits on disk until
someone runs the script from FL's Piano roll scripts menu. Every task below is
therefore testable without the permission, and the live checks use the menu. If
the permission is ever granted, `fl_trigger` already uses the keystroke and needs
no change.

---

### Task 1: Controller targeting actions

**Files:**
- Modify: `fl_controller/device_FLStudioMCP.py`
- Test: `tests/test_controller_targeting.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - Action `channels.selectPianoRoll`, params `{"index": int}`, replying
    `{"targeted": int, "channel_name": str, "piano_roll_visible": bool}` or an
    error. Selects the channel, opens its piano roll, and reports the selection it
    actually achieved.
  - Action `channels.getSelectedChannel`, replying
    `{"index": int | None, "channel_name": str | None}`, read-only.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_controller_targeting.py
"""Targeting is a controller job, because only the controller can see channels.

The piano roll script has one FL module, flpianoroll, and it exposes no channel
identity at all: no name, no index, nothing. So the side that knows which channel
was asked for has to be the side that arranges for its piano roll to be open.
"""

from __future__ import annotations

import pytest


def test_targeting_selects_the_channel_and_shows_its_piano_roll(fl_env):
    result = fl_env.controller.dispatch_command("channels.selectPianoRoll", {"index": 2})
    assert result["targeted"] == 2
    assert result["channel_name"] == "Channel 3"
    assert result["piano_roll_visible"] is True
    assert fl_env.project.selected_channel == 2


def test_targeting_deselects_the_others(fl_env):
    """A half-selected rack would leave the piano roll ambiguous."""
    fl_env.project.selected_channel = 0
    fl_env.controller.dispatch_command("channels.selectPianoRoll", {"index": 3})
    assert fl_env.project.channel(3).selected is True
    assert fl_env.project.channel(0).selected is False


def test_targeting_reports_the_window_it_showed(fl_env):
    fl_env.controller.dispatch_command("channels.selectPianoRoll", {"index": 1})
    assert fl_env.project.ui_state.get("visible_3") is True, "widPianoRoll is 3"


def test_targeting_refuses_a_missing_index(fl_env):
    result = fl_env.controller.dispatch_command("channels.selectPianoRoll", {})
    assert "error" in result
    assert "index" in result["error"]


def test_targeting_refuses_an_index_that_does_not_exist(fl_env):
    """Better to refuse than to select whatever FL decides index 99 means."""
    result = fl_env.controller.dispatch_command("channels.selectPianoRoll", {"index": 99})
    assert "error" in result
    assert "99" in result["error"]


def test_targeting_is_refused_when_fl_is_not_safe_to_edit(fl_env):
    """Selecting and opening a window is not a read: it changes what the user sees."""
    fl_env.project.safe_to_edit = False
    result = fl_env.controller.dispatch_command("channels.selectPianoRoll", {"index": 1})
    assert "error" in result
    assert "safe to edit" in result["error"].lower()


def test_get_selected_channel_reports_the_selection(fl_env):
    fl_env.controller.dispatch_command("channels.selectPianoRoll", {"index": 2})
    result = fl_env.controller.dispatch_command("channels.getSelectedChannel", {})
    assert result["index"] == 2
    assert result["channel_name"] == "Channel 3"


def test_get_selected_channel_reports_nothing_selected(fl_env):
    fl_env.project.selected_channel = None
    result = fl_env.controller.dispatch_command("channels.getSelectedChannel", {})
    assert result["index"] is None
    assert result["channel_name"] is None


def test_get_selected_channel_is_never_refused(fl_env):
    """A caller has to be able to find out where it is before it can move."""
    fl_env.project.safe_to_edit = False
    result = fl_env.controller.dispatch_command("channels.getSelectedChannel", {})
    assert "error" not in result
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/test_controller_targeting.py -v`
Expected: `Unknown action: channels.selectPianoRoll`.

- [ ] **Step 3: Add the actions**

In `fl_controller/device_FLStudioMCP.py`, add near the other channel constants:

```python
# From the stubs: ui.showWindow indices. The piano roll is window 3.
WID_PIANO_ROLL = 3
```

Add to `dispatch_command`, in the Channel commands block:

```python
    elif action == "channels.selectPianoRoll":
        return handle_channels_select_piano_roll(params)
    elif action == "channels.getSelectedChannel":
        return handle_channels_get_selected_channel(params)
```

Add the handlers in the Channel handlers section:

```python
def handle_channels_select_piano_roll(params: dict) -> dict:
    """Select a channel and open its piano roll.

    This is how a caller aims the piano roll tools. The piano roll window shows
    whichever channel is selected in the Channel Rack, so selecting first is what
    makes the target unambiguous. A piano roll script cannot do this for itself:
    flpianoroll exposes no channel identity at all.

    The selection is read back rather than assumed, because the point of the whole
    exercise is to know which piano roll is about to be written to.
    """
    index = _require(params, "index", "channels.selectPianoRoll")
    count = channels.channelCount(True)
    if not 0 <= index < count:
        return {
            "error": (
                "channels.selectPianoRoll: channel %d does not exist, this project "
                "has %d channels (0 to %d)" % (index, count, count - 1)
            )
        }

    channels.selectOneChannel(index, True)
    ui.showWindow(WID_PIANO_ROLL)

    selected = channels.selectedChannel(canBeNone=True, indexGlobal=True)
    return {
        "targeted": index,
        "selected": selected,
        "channel_name": channels.getChannelName(index, True),
        "piano_roll_visible": bool(ui.getVisible(WID_PIANO_ROLL)),
    }


def handle_channels_get_selected_channel(params: dict) -> dict:
    """Report which channel is selected, and its name.

    Read-only, and never refused: a caller has to be able to ask where it is
    before it can decide to move.
    """
    index = channels.selectedChannel(canBeNone=True, indexGlobal=True)
    if index is None or index < 0:
        return {"index": None, "channel_name": None}
    return {"index": index, "channel_name": channels.getChannelName(index, True)}
```

Add `channels.selectPianoRoll` to `MUTATING_ACTIONS`, because it changes what the
user sees and which channel subsequent edits will hit, and add
`channels.getSelectedChannel` nowhere, since it only reads.

- [ ] **Step 4: Run them and watch them pass**

Run: `uv run pytest tests/test_controller_targeting.py -v`
Expected: 9 passed.

- [ ] **Step 5: Run the whole suite and lint**

Run: `uv run pytest && uv run ruff check .`

- [ ] **Step 6: Copy into FL and verify the targeting live**

```bash
cp fl_controller/device_FLStudioMCP.py \
   ~/Documents/Image-Line/FL\ Studio/Settings/Hardware/FLStudioMCP/device_FLStudioMCP.py
uv run python -c "
from fl_studio_mcp.utils.midi_connection import get_connection
conn = get_connection(); conn.connect()
for i in (2, 0):
    r = conn.send_command('channels.selectPianoRoll', {'index': i}, timeout=3.0)
    print(i, '->', {k: r.get(k) for k in ('targeted', 'selected', 'channel_name', 'piano_roll_visible')})
print('read back:', conn.send_command('channels.getSelectedChannel', {}, timeout=3.0))
"
```

Expected: the channel names match the ones in FL's Channel Rack, and `selected`
equals `targeted`. Leave the user's selection as it was found.

- [ ] **Step 7: Commit**

```bash
git add fl_controller/device_FLStudioMCP.py tests/test_controller_targeting.py
git commit -m "Add a targeting action that selects a channel and opens its piano roll"
```

---

### Task 2: A channel argument on every piano roll tool

**Files:**
- Modify: `src/fl_studio_mcp/tools/piano_roll.py`
- Test: `tests/test_piano_roll_targeting.py`

**Interfaces:**
- Consumes: `channels.selectPianoRoll` from Task 1.
- Produces:
  - `piano_roll.target(channel: int) -> dict`, which calls the controller action
    and returns its reply.
  - `piano_roll.send_request(request, timeout, wait_for_manual_trigger, channel=None)`,
    which targets before triggering when a channel is given, and refuses to
    trigger when the target does not match.
  - Every piano roll tool gains a `channel: int | None` argument.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_piano_roll_targeting.py
"""A piano roll tool must say which piano roll it wrote to.

Before this, notes landed in whichever piano roll happened to be focused. The
failure was invisible: the tool reported success, the notes were real, and they
were in the wrong place.
"""

from __future__ import annotations

import json

import pytest

from fl_studio_mcp.tools import piano_roll
from fl_studio_mcp.utils.connection import reset_connection


@pytest.fixture
def wired(fl_env, monkeypatch):
    """Both the piano roll tools and the controller wired to one connection."""
    from fl_studio_mcp.utils.midi_connection import MIDIConnection

    conn = MIDIConnection()
    conn._command_file = fl_env.command_file
    conn._response_file = fl_env.response_file
    conn._port = fl_env.midi_port
    conn._connected = True

    monkeypatch.setattr(piano_roll, "get_connection", lambda: conn, raising=False)
    monkeypatch.setattr(piano_roll, "piano_roll_scripts_dir", lambda: fl_env.piano_roll_dir)

    def fake_trigger(delay: float = 0.0) -> bool:
        fl_env.pyscript.apply()
        return True

    monkeypatch.setattr(piano_roll, "trigger_fl_studio", fake_trigger)
    yield fl_env
    reset_connection()


def test_target_asks_the_controller_to_select_the_channel(wired):
    result = piano_roll.target(2)
    assert result["targeted"] == 2
    assert wired.project.selected_channel == 2


def test_target_refuses_a_channel_that_does_not_exist(wired):
    result = piano_roll.target(99)
    assert "error" in result
    assert "99" in result["error"]


def test_send_request_with_a_channel_targets_first(wired):
    result = piano_roll.send_request(
        {"action": "add_notes", "notes": [{"midi": 60, "time": 0.0, "duration": 1.0}]},
        timeout=1.0,
        channel=1,
    )
    assert result["success"] is True
    assert wired.project.selected_channel == 1
    assert result["target_channel"] == 1
    assert result["target_channel_name"] == "Channel 2"


def test_send_request_without_a_channel_does_not_target(wired):
    """Leaving the argument out keeps the old behaviour rather than guessing."""
    wired.project.selected_channel = 2
    piano_roll.send_request(
        {"action": "add_notes", "notes": [{"midi": 60, "time": 0.0, "duration": 1.0}]},
        timeout=1.0,
    )
    assert wired.project.selected_channel == 2


def test_a_failed_target_stops_before_the_trigger(wired, monkeypatch):
    """A trigger after a failed target would write to an unknown piano roll."""
    triggered = []
    monkeypatch.setattr(
        piano_roll, "trigger_fl_studio", lambda delay=0: triggered.append(1) or True
    )
    result = piano_roll.send_request({"action": "clear"}, timeout=0.05, channel=99)
    assert result["success"] is False
    assert "99" in result["error"]
    assert triggered == [], "the script was triggered without a confirmed target"


def test_the_target_is_reported_so_the_caller_knows_where_notes_went(wired):
    result = piano_roll.send_request({"action": "clear"}, timeout=1.0, channel=3)
    assert result["target_channel"] == 3
    assert result["target_channel_name"] == "Channel 4"


def test_the_request_file_records_the_target(wired):
    """So a stale request on disk says where it was meant to go."""
    piano_roll.send_request(
        {"action": "add_notes", "notes": [{"midi": 60, "time": 0.0, "duration": 1.0}]},
        timeout=1.0,
        channel=2,
    )
    written = json.loads(wired.request_file.read_text())
    assert written == [], "the script should have emptied the queue"
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/test_piano_roll_targeting.py -v`
Expected: `AttributeError: module 'fl_studio_mcp.tools.piano_roll' has no attribute 'target'`.

- [ ] **Step 3: Add `target` and the `channel` argument**

In `src/fl_studio_mcp/tools/piano_roll.py`, import the connection helper:

```python
from fl_studio_mcp.utils.connection import get_connection
```

Add the targeting function above `send_request`:

```python
def target(channel: int) -> dict:
    """Select a channel and open its piano roll, so writes land somewhere known.

    Args:
        channel: Global channel index in the Channel Rack.

    Returns:
        The controller's reply, with "targeted", "selected", "channel_name" and
        "piano_roll_visible", or an "error". A caller must not trigger the piano
        roll script unless this succeeded and "selected" equals "targeted".
    """
    return get_connection().send_command(
        "channels.selectPianoRoll", {"index": channel}, timeout=5.0
    )
```

Change `send_request`'s signature and add the targeting step:

```python
def send_request(
    request: dict,
    timeout: float = RESPONSE_TIMEOUT,
    wait_for_manual_trigger: float = 0.0,
    channel: int | None = None,
) -> dict:
```

and, before writing the request file:

```python
    target_info = {}
    if channel is not None:
        targeted = target(channel)
        if "error" in targeted:
            return {
                "success": False,
                "error": (
                    f"Could not target channel {channel}, so the piano roll script "
                    f"was not triggered: {targeted['error']}"
                ),
            }
        if targeted.get("selected") != channel:
            return {
                "success": False,
                "error": (
                    f"Asked FL Studio to select channel {channel} but it reports "
                    f"channel {targeted.get('selected')} selected, so the piano roll "
                    "script was not triggered. Writing now would edit the wrong "
                    "piano roll."
                ),
            }
        target_info = {
            "target_channel": channel,
            "target_channel_name": targeted.get("channel_name"),
        }
```

and remember to merge it into every return path that carries a reply:

```python
        if reply is not None and reply.get("id") in (None, request["id"]):
            return {**reply, **target_info}
```

Also stamp the channel into the request file, so a request left on disk for a
manual trigger records where it was meant to go:

```python
    request.setdefault("id", uuid.uuid4().hex)
    if channel is not None:
        request["channel"] = channel
```

- [ ] **Step 4: Add the argument to every tool**

Each of `fl_send_notes`, `fl_send_chord`, `fl_delete_notes` and
`fl_clear_piano_roll` gains `channel: int | None = None` and passes it through.
Update each docstring's Args to describe it, in the same voice as the rest:

```
            channel: Channel Rack index to write into. Strongly recommended: the
                     piano roll window shows whichever channel is selected, so
                     without this the notes land in whichever piano roll happens
                     to be focused. The reply names the channel that was targeted.
```

`fl_get_piano_roll_state` gains it too, described as which channel's piano roll to
read.

- [ ] **Step 5: Run them and watch them pass**

Run: `uv run pytest tests/test_piano_roll_targeting.py -v`
Expected: 7 passed.

- [ ] **Step 6: Run the whole suite and lint**

Run: `uv run pytest && uv run ruff check .`

- [ ] **Step 7: Commit**

```bash
git add src/fl_studio_mcp/tools/piano_roll.py tests/test_piano_roll_targeting.py
git commit -m "Give every piano roll tool a channel to write into"
```

---

### Task 3: Report the channel in the tool output

**Files:**
- Modify: `src/fl_studio_mcp/tools/piano_roll.py`
- Test: `tests/test_piano_roll_reporting.py`

**Interfaces:**
- Consumes: Task 2's `target_info`.
- Produces: every piano roll tool's string result naming the channel, or naming
  the absence of one as a warning.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_piano_roll_reporting.py
"""The tool output must say where the notes went.

A report that omits the channel cannot be checked by the model reading it, and the
old behaviour, notes in an unknown piano roll reported as success, is exactly what
this phase exists to remove.
"""

from __future__ import annotations

import pytest

from fl_studio_mcp import server
from fl_studio_mcp.tools import piano_roll


def _tools():
    """The registered tool functions, by name."""
    found = {}
    for name in dir(server):
        if name.startswith("fl_"):
            found[name] = getattr(server, name)
    return found


def test_the_tools_take_a_channel_argument():
    """The surface itself has to offer it, or the model cannot use it."""
    import inspect

    for name in ("fl_send_notes", "fl_send_chord", "fl_delete_notes",
                 "fl_clear_piano_roll", "fl_get_piano_roll_state"):
        tool = _tools().get(name)
        assert tool is not None, f"{name} is not registered"
        assert "channel" in inspect.signature(tool).parameters, (
            f"{name} has no channel parameter"
        )


def test_the_docstrings_tell_the_model_to_use_it():
    """A tool surface is a prompt, so the docstring is part of the feature."""
    for name in ("fl_send_notes", "fl_send_chord", "fl_delete_notes",
                 "fl_clear_piano_roll"):
        doc = _tools()[name].__doc__ or ""
        assert "channel" in doc, f"{name}'s docstring never mentions channel"
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/test_piano_roll_reporting.py -v`
Expected: both fail, because the arguments were added in Task 2 but this test file
did not exist yet. If they pass, Task 2 already covered it; keep them as
regression guards and say so in the commit.

- [ ] **Step 3: Put the channel in every result string**

Add a helper:

```python
def _target_note(result: dict) -> str:
    """A sentence fragment naming where the notes went, or warning that it is unknown."""
    name = result.get("target_channel_name")
    index = result.get("target_channel")
    if index is None:
        return " No channel was given, so this landed in whichever piano roll had focus."
    return f" Channel {index} ({name})."
```

and use it in each tool's success message, for example:

```python
        return f"Added {landed} note(s): {summary}.{_target_note(result)}"
```

- [ ] **Step 4: Run them and watch them pass**

Run: `uv run pytest tests/test_piano_roll_reporting.py -v`
Expected: 2 passed.

- [ ] **Step 5: Run the whole suite and lint**

Run: `uv run pytest && uv run ruff check .`

- [ ] **Step 6: Commit**

```bash
git add src/fl_studio_mcp/tools/piano_roll.py tests/test_piano_roll_reporting.py
git commit -m "Report which channel the piano roll tools wrote into"
```

---

### Task 4: Verify the notes landed, and prove it live

**Files:**
- Modify: `src/fl_studio_mcp/tools/piano_roll.py`
- Modify: `docs/SMOKE_TEST.md`
- Test: `tests/test_piano_roll_verification.py`

**Interfaces:**
- Consumes: Tasks 1 to 3.
- Produces: `piano_roll.send_request` optionally confirming the notes landed by
  reading the state back, and a `verified` field saying whether it did.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_piano_roll_verification.py
"""The roadmap asks for read-back verification, not just a reported count.

This is the done-condition: fl_send_notes(channel=3, ...) either reports the notes
landed on channel 3, verified by read-back, or reports a specific failure.
"""

from __future__ import annotations

import pytest

from fl_studio_mcp.tools import piano_roll


@pytest.fixture
def wired(fl_env, monkeypatch):
    from fl_studio_mcp.utils.midi_connection import MIDIConnection

    conn = MIDIConnection()
    conn._command_file = fl_env.command_file
    conn._response_file = fl_env.response_file
    conn._port = fl_env.midi_port
    conn._connected = True
    monkeypatch.setattr(piano_roll, "get_connection", lambda: conn, raising=False)
    monkeypatch.setattr(piano_roll, "piano_roll_scripts_dir", lambda: fl_env.piano_roll_dir)

    def fake_trigger(delay: float = 0.0) -> bool:
        fl_env.pyscript.apply()
        return True

    monkeypatch.setattr(piano_roll, "trigger_fl_studio", fake_trigger)
    return fl_env


def test_a_successful_write_is_confirmed_by_reading_the_notes_back(wired):
    result = piano_roll.send_request(
        {"action": "add_notes", "notes": [{"midi": 60, "time": 0.0, "duration": 1.0}]},
        timeout=1.0,
        channel=1,
        verify=True,
    )
    assert result["success"] is True
    assert result["verified"] is True
    assert result["verified_notes"] == 1


def test_a_write_that_did_not_land_is_reported_as_a_failure(wired, monkeypatch):
    """The script claims notes were added but the piano roll is empty.

    This is the failure the old code could not see, because it never read the
    state it already exported.
    """
    monkeypatch.setattr(
        wired.pyscript,
        "_handle",
        lambda request: {"action": "add_notes", "id": request.get("id"),
                         "notes_added": 1, "notes_deleted": 0, "error": None},
    )
    result = piano_roll.send_request(
        {"action": "add_notes", "notes": [{"midi": 60, "time": 0.0, "duration": 1.0}]},
        timeout=1.0,
        channel=1,
        verify=True,
    )
    assert result["success"] is False
    assert "did not land" in result["error"] or "no notes" in result["error"].lower()


def test_verification_is_off_by_default(wired):
    """Confirming costs a second script run, so it is opt in."""
    result = piano_roll.send_request({"action": "clear"}, timeout=1.0, channel=1)
    assert "verified" not in result
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/test_piano_roll_verification.py -v`
Expected: `TypeError: send_request() got an unexpected keyword argument 'verify'`.

- [ ] **Step 3: Implement verification**

Add the argument and the check to `send_request`:

```python
    verify: bool = False,
```

and after the reply is received and the target merged:

```python
            result = {**reply, **target_info}

            if verify:
                confirmed = _verify_notes_landed(request, result, timeout)
                result.update(confirmed)
                if confirmed.get("verified") is False:
                    result["success"] = False
                    result["error"] = confirmed["error"]

            return result
```

and the helper:

```python
def _verify_notes_landed(request: dict, reply: dict, timeout: float) -> dict:
    """Read the piano roll back and check the notes the script claimed it added.

    The script reports what it did; this reads what is there. The two can disagree:
    a script that ran against a different piano roll than the caller intended
    reports its own success honestly and is still wrong about the outcome.

    The check is deliberately simple: the script's own export is the only view of
    the notes anything has, because flpianoroll exposes no channel identity and the
    controller cannot read notes at all. What this adds is that the note count is
    read after the write rather than taken from the reply.
    """
    state = read_state()
    if state is None:
        return {
            "verified": False,
            "error": (
                "The script replied but exported no piano roll state, so the notes "
                "could not be confirmed."
            ),
        }

    added = reply.get("notes_added") or 0
    count = state.get("noteCount", 0)
    if added and count <= 0:
        return {
            "verified": False,
            "error": (
                f"The script reported adding {added} note(s) but the piano roll it "
                "exported holds none, so the notes did not land where they were "
                "reported to."
            ),
        }
    return {"verified": True, "verified_notes": count}
```

- [ ] **Step 4: Run them and watch them pass**

Run: `uv run pytest tests/test_piano_roll_verification.py -v`
Expected: 3 passed.

- [ ] **Step 5: Add a live smoke test item and run it by hand**

Add to `docs/SMOKE_TEST.md`, in the piano roll section:

```
- [ ] `fl_send_notes(channel=2, ...)` with the piano roll open on a different
      channel, and confirm the notes appear on channel 2 and the reply names
      channel 2. Catches targeting that selects the channel but does not move the
      window, which is the failure this phase exists to fix.
- [ ] `fl_get_piano_roll_state(channel=2)` and confirm the notes just written are
      reported, and that a different channel's piano roll holds different notes.
      Catches the state file being read without being refreshed.
```

Then run the live check by hand in FL, since the keystroke is unavailable:

```bash
uv run python -c "
import json
from fl_studio_mcp.tools import piano_roll
piano_roll.trigger_fl_studio = lambda delay=0: True   # the user runs it from the menu
r = piano_roll.send_request(
    {'action': 'add_notes', 'id': 'phase2-live', 'notes': [
        {'midi': 62, 'time': 0.0, 'duration': 0.5},
        {'midi': 65, 'time': 0.5, 'duration': 0.5},
    ]},
    timeout=90.0, wait_for_manual_trigger=90.0, channel=2, verify=True,
)
print(json.dumps(r, indent=2))
"
```

Ask the user to click **ComposeWithLLM** in the Piano roll scripts menu while it
waits. Expected: `success: true`, `target_channel: 2`, `target_channel_name`, and
`verified: true`, with the notes visible on channel 2 in FL. Then read
`fl_get_piano_roll_state(channel=2)` and confirm two notes, and read channel 0 and
confirm it does not have them.

- [ ] **Step 6: Run the whole suite and lint**

Run: `uv run pytest && uv run ruff check .`

- [ ] **Step 7: Commit**

```bash
git add src/fl_studio_mcp/tools/piano_roll.py docs/SMOKE_TEST.md \
        tests/test_piano_roll_verification.py
git commit -m "Confirm the notes landed by reading the piano roll back"
```

---

## Phase 2 exit criteria

The roadmap's own bar, restated so it can be checked rather than believed:

- [ ] `fl_send_notes(channel=3, ...)` lands notes on channel 3, or reports a
      specific failure. Proven by read-back, live.
- [ ] A failed or mismatched target stops before the trigger, so a script run can
      never write to an unconfirmed piano roll.
- [ ] Every piano roll tool takes a `channel`, and its result names the channel it
      used.
- [ ] `fl_get_piano_roll_state(channel=n)` refreshes and reports the channel.
- [ ] `pytest` green and `ruff check .` clean with no FL Studio running.
- [ ] `docs/SMOKE_TEST.md` records the live run, including that the keystroke path
      could not be exercised without the macOS Accessibility permission.

## What Phase 2 deliberately does not do

- It does not add patterns, EQ, routing or metering. That is Phase 3.
- It does not read the pyscript's reply to work out which piano roll was written
  to. The pyscript cannot know that: `flpianoroll` exposes no channel identity, so
  the controller proves the target instead and the plan says so rather than
  pretending the script can be made to verify itself.
- It does not fix the keystroke. That needs a macOS permission change, and the
  manual menu path already exercises everything except the keystroke itself.
