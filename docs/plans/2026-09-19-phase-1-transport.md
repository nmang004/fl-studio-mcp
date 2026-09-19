# Phase 1: Transport Correctness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the transport correct under timeout and concurrency, give FL a real
liveness check, refuse commands that do not say what to act on, and make one AI
edit one undo step.

**Architecture:** Correlation ids travel in the command and are echoed in the
response, and the server validates the id before consuming anything. A re-entrant
lock serialises whole request cycles, because the command file and the response
file are each a single shared slot that two clients cannot share. A `ping` action
gives a real liveness check, replacing both the fixed settle delay and the
assumption that an open port means a live FL. Handlers that could silently act on
the wrong target refuse instead. Batches run many commands from one trigger inside
one `general.saveUndo`, so one AI edit is one Ctrl+Z.

**Tech Stack:** The Phase 0 harness (fake FL modules, fake MIDI cable, `fl_env`
fixture), pytest 9, ruff 0.16.

**Spec:** `ROADMAP.md` Phase 1, plus the "Verified against live FL Studio" table
and the sandbox rules.

## Global Constraints

Copied from ROADMAP.md, and implicitly part of every task:

- Python `>=3.10`, ruff `target-version = "py310"`, `ruff check .` clean, line
  length 100, rules `E`, `F`, `I`, `W`.
- `pytest` green with no FL Studio running.
- Keep `constraint-dependencies = ["cryptography<49"]`.
- macOS and Windows must both keep working.
- No em dashes, no en dashes, no emoji anywhere. No AI attribution.
- Commits scoped to one concern.
- The controller script imports only FL modules plus `json`, `os`, `sys` and
  `pathlib`. It may not call `mkdir`, `makedirs`, `replace`, `rename`, `remove`,
  `unlink`, `glob`, `rglob`, `walk` or the builtin `open()`. `Path.write_text`,
  `Path.read_text`, `Path.exists`, `Path.is_dir`, `Path.stat` and `Path.iterdir`
  work. `tests/test_response_reading.py` enforces all of this.
- The pyscript has the same rename and directory restrictions but may use
  `open()`. The same test file enforces it.

### What Phase 1 inherited from Phase 0

Five roadmap items already landed, four of them early and one in a different form
than the table describes. This plan does not redo them.

| Roadmap item | State |
| --- | --- |
| Own the MIDI port | Done, with `FL_STUDIO_MCP_MIDI_PORT` to override |
| Safe port selection | Done, covered by `tests/test_port_selection.py` |
| Settings path override | Done, including OneDrive detection, shared by all three scripts |
| Error propagation | Done: the controller reports `success: False`, and the piano roll tools return specific failures |
| Atomic writes | Impossible inside FL: both sandboxes block `os.replace`. What landed is `MIDIResponseReader`, which treats a reply it cannot parse as unfinished, on both the controller and piano roll paths |

### Design decisions this plan makes

**The lock is the fix for concurrency, not belt and braces.** Two clients writing
the same command slot interleave no matter how good the correlation is, so whole
request cycles are serialised with an `RLock`. Correlation then covers what the
lock cannot: a leftover reply from an earlier process, and any reply whose id does
not match the work in flight.

**Correlation validates, it does not queue.** A reply whose id belongs to an
unknown request is ignored rather than consumed, which is the roadmap's wording. A
reply carrying no id at all is accepted, because a controller older than this
change does not echo one, and refusing those would break every working install to
guard a case the lock already covers.

**`send_command` keeps its signature.** It does not gain an `id` parameter, because
every tool calls it and none of them care. The id is generated inside
`send_command`, stored as `last_request_id`, and validated in `_wait_for_response`.

**`wait_until_responsive` replaces the fixed settle delay at the call sites that
need it.** `connect()` keeps its settle behaviour for now, because changing it
would alter every existing test's timing. `fl_connect` and the live check use the
handshake instead, so the honest answer is available where it matters.

---

### Task 1: Request correlation

**Files:**
- Modify: `src/fl_studio_mcp/utils/midi_connection.py`
- Test: `tests/test_correlation.py`

**Interfaces:**
- Consumes: `MIDIResponseReader` and `NOT_READY` from Phase 0.
- Produces:
  - `send_command` writes `{"action": ..., "params": ..., "id": <hex>}` and
    returns the reply, which carries the same `id`.
  - `MIDIConnection.last_request_id: str | None`, the id most recently sent.
  - `MIDIConnection._is_our_reply(response) -> bool`, which accepts a reply whose
    id matches or is absent, and rejects one that names a different request.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_correlation.py
"""Every command carries an id and every reply must match it.

Without correlation a reply is just "something FL finished", so an abandoned
command's answer can be consumed as the next command's answer. The original audit
could not reproduce the dramatic version of that story live, because FL answers in
about a millisecond, but the structural defect is real and two concurrent clients
reach it with no timeout at all.
"""

from __future__ import annotations

import json

import pytest

from fl_studio_mcp.utils.midi_connection import MIDIConnection, MIDIResponseReader, NOT_READY


@pytest.fixture
def connection(fl_env):
    """A MIDIConnection wired to the in-process controller."""
    conn = MIDIConnection()
    conn._command_file = fl_env.command_file
    conn._response_file = fl_env.response_file
    conn._port = fl_env.midi_port
    conn._port_name = fl_env.midi_port.name
    conn._connected = True
    return conn


def test_the_command_file_carries_an_id(connection, fl_env):
    connection.send_command("mixer.getTrackCount", timeout=2.0)
    written = json.loads(fl_env.command_file.read_text())
    assert written["id"], "the server sent a command with no id"


def test_the_reply_carries_the_same_id_back(connection):
    result = connection.send_command("mixer.getTrackCount", timeout=2.0)
    assert result["id"] == connection.last_request_id


def test_each_command_gets_a_distinct_id(connection):
    connection.send_command("mixer.getTrackCount", timeout=2.0)
    first = connection.last_request_id
    connection.send_command("mixer.getTrackCount", timeout=2.0)
    assert connection.last_request_id != first


def test_a_reply_for_another_request_is_not_consumed(connection, fl_env):
    """A reply that belongs to something else must not answer this command."""
    fl_env.response_file.write_text(
        json.dumps({"success": True, "id": "not-mine", "count": 999}) + "\n"
    )
    # The reader itself parses it, so this is not a "not ready" case.
    assert MIDIResponseReader(fl_env.response_file).read() is not NOT_READY

    result = connection.send_command("mixer.getTrackCount", timeout=1.0)

    assert result["id"] == connection.last_request_id, "a foreign reply was consumed"
    assert result["count"] == 8, "the foreign reply's payload leaked into this answer"


def test_a_reply_with_no_id_is_still_accepted(connection, fl_env, monkeypatch):
    """A controller older than this change does not echo an id."""
    original = fl_env.controller.execute_pending_command

    def drop_the_id():
        original()
        payload = json.loads(fl_env.response_file.read_text())
        payload.pop("id", None)
        fl_env.response_file.write_text(json.dumps(payload) + "\n")

    monkeypatch.setattr(fl_env.controller, "execute_pending_command", drop_the_id)

    result = connection.send_command("mixer.getTrackCount", timeout=2.0)

    assert result["success"] is True
    assert result["count"] == 8


def test_the_connection_reports_the_id_it_used(connection):
    assert connection.last_request_id is None, "no command has been sent yet"
    connection.send_command("mixer.getTrackCount", timeout=2.0)
    assert isinstance(connection.last_request_id, str)
    assert connection.last_request_id
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/test_correlation.py -v`
Expected: `test_the_command_file_carries_an_id` fails with `KeyError: 'id'`. The
id assertions fail with `AttributeError: ... has no attribute 'last_request_id'`.
`test_a_reply_for_another_request_is_not_consumed` fails because the foreign reply
is consumed and its count of 999 is returned.

- [ ] **Step 3: Generate the id in `send_command`**

In `src/fl_studio_mcp/utils/midi_connection.py`, add the import:

```python
import uuid
```

Add to `MIDIConnection.__init__`, beside the other state:

```python
        # The id of the command currently in flight. Its reply must carry it.
        self.last_request_id: str | None = None
```

Replace the command construction in `send_command`:

```python
        # Every command carries an id and the controller echoes it. A reply is
        # only accepted when its id matches, so an abandoned command's answer
        # cannot be mistaken for the next command's answer.
        self.last_request_id = uuid.uuid4().hex
        command = {
            "action": action,
            "params": params or {},
            "id": self.last_request_id,
        }
```

- [ ] **Step 4: Validate the id in `_wait_for_response`**

Replace the loop body:

```python
        while time.time() - start_time < timeout:
            poll_interval = 0.0005 if time.time() < fast_poll_until else 0.02
            response = reader.read()
            if response is not NOT_READY:
                if not self._is_our_reply(response):
                    # A reply to something else. Leave it alone and keep waiting
                    # rather than consuming it as this command's answer.
                    time.sleep(poll_interval)
                    continue

                # Clean up response file
                try:
                    self._response_file.unlink()
                except Exception:
                    pass

                return response

            time.sleep(poll_interval)
```

Add the helper after `_wait_for_response`:

```python
    def _is_our_reply(self, response: dict[str, Any]) -> bool:
        """Whether a reply belongs to the command in flight.

        A reply with no id at all is accepted. A controller older than this change
        does not echo one, and refusing those would break every working install in
        order to guard a case the request lock already covers.
        """
        reply_id = response.get("id")
        if reply_id is None:
            return True
        return reply_id == self.last_request_id
```

- [ ] **Step 5: Run them and watch them pass**

Run: `uv run pytest tests/test_correlation.py -v`
Expected: 6 passed.

- [ ] **Step 6: Run the whole suite and lint**

Run: `uv run pytest && uv run ruff check .`
Expected: green. If `tests/test_command_roundtrip.py::test_the_command_file_records_what_was_sent`
fails, it is asserting an exact command dict; update it to check `action` and
`params` separately and to assert an `id` is present.

- [ ] **Step 7: Commit**

```bash
git add src/fl_studio_mcp/utils/midi_connection.py tests/test_correlation.py \
        tests/test_command_roundtrip.py
git commit -m "Correlate every command with its reply by request id"
```

---

### Task 2: Serialise concurrent request cycles

**Files:**
- Modify: `src/fl_studio_mcp/utils/midi_connection.py`
- Test: `tests/test_concurrency.py`

**Interfaces:**
- Consumes: Task 1's `last_request_id` and `_is_our_reply`.
- Produces: `send_command` is safe from several threads at once. Each caller gets
  its own reply.
- Produces: `MIDIConnection._send_command_locked(action, params, timeout)`, which
  callers must hold `self._lock` to use.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_concurrency.py
"""Two clients on one machine must not cross-talk.

The command file and the response file are each a single shared slot. Two writers
interleave there no matter how good the correlation is, so a whole request cycle
is serialised. This is the failure the audit described, and it needs no timeout,
only a second client.
"""

from __future__ import annotations

import threading

import pytest

from fl_studio_mcp.utils.midi_connection import MIDIConnection


@pytest.fixture
def connection(fl_env):
    conn = MIDIConnection()
    conn._command_file = fl_env.command_file
    conn._response_file = fl_env.response_file
    conn._port = fl_env.midi_port
    conn._port_name = fl_env.midi_port.name
    conn._connected = True
    return conn


def _run_all(targets):
    """Start every target at once and return the collected failures."""
    barrier = threading.Barrier(len(targets))
    failures = []
    lock = threading.Lock()

    def wrapped(index, fn):
        try:
            barrier.wait(timeout=10)
            fn()
        except Exception as error:  # noqa: BLE001 - collected and asserted on
            with lock:
                failures.append(f"{index}: {type(error).__name__}: {error}")

    threads = [
        threading.Thread(target=wrapped, args=(i, fn)) for i, fn in enumerate(targets)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
    return failures


def test_concurrent_commands_each_get_their_own_answer(connection):
    """Ten threads asking two different questions get ten correct answers."""
    results: dict[int, object] = {}
    lock = threading.Lock()

    def ask(index: int):
        def call():
            action = "mixer.getTrackCount" if index % 2 == 0 else "channels.getCount"
            reply = connection.send_command(action, timeout=10.0)
            with lock:
                results[index] = reply.get("count")

        return call

    failures = _run_all([ask(i) for i in range(10)])

    assert not failures, failures
    assert len(results) == 10, f"only {len(results)} of 10 calls returned"
    for index, value in results.items():
        expected = 8 if index % 2 == 0 else 4
        assert value == expected, f"thread {index} got {value}, expected {expected}"


def test_no_caller_receives_another_callers_reply(connection):
    """A mixer question must never come back with a channel count."""
    counts: dict[str, list] = {"mixer.getTrackCount": [], "channels.getCount": []}
    lock = threading.Lock()

    def ask(action: str):
        def call():
            reply = connection.send_command(action, timeout=10.0)
            with lock:
                counts[action].append(reply.get("count"))

        return call

    failures = _run_all([ask("mixer.getTrackCount"), ask("channels.getCount")])

    assert not failures, failures
    assert counts["mixer.getTrackCount"] == [8]
    assert counts["channels.getCount"] == [4]


def test_the_lock_is_reentrant(connection):
    """A caller holding the lock must be able to compose smaller calls."""
    with connection._lock:
        assert connection.send_command("mixer.getTrackCount", timeout=5.0)["count"] == 8
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest tests/test_concurrency.py -v`
Expected: failures in `test_concurrent_commands_each_get_their_own_answer` and
`test_no_caller_receives_another_callers_reply`, with counts attributed to the
wrong question or calls timing out. `test_the_lock_is_reentrant` fails with
`AttributeError: ... has no attribute '_lock'`.

- [ ] **Step 3: Add the lock**

Add the import:

```python
import threading
```

Add to `__init__`:

```python
        # The command file and the response file are each one shared slot, so a
        # whole request cycle is serialised. Re-entrant, so a caller already
        # holding it can still send.
        self._lock = threading.RLock()
```

Turn `send_command` into a wrapper and move its body into a private method:

```python
    def send_command(
        self,
        action: str,
        params: dict[str, Any] | None = None,
        timeout: float = 2.0,
    ) -> dict[str, Any]:
        """Send a command to FL Studio and wait for its reply.

        Safe to call from several threads. Whole request cycles are serialised,
        because the command file and the response file are each a single shared
        slot: correlation alone cannot stop two writers interleaving there.

        Args:
            action: The command action, for example "transport.getStatus".
            params: Optional parameters for the command.
            timeout: Maximum time to wait for the reply, in seconds.

        Returns:
            The reply from FL Studio, which carries the id of the command it
            answers, or a dict with "success": False and a specific "error".
        """
        self.ensure_connected()
        with self._lock:
            return self._send_command_locked(action, params, timeout)

    def _send_command_locked(
        self,
        action: str,
        params: dict[str, Any] | None,
        timeout: float,
    ) -> dict[str, Any]:
        """Write the command, trigger FL, and wait for the matching reply.

        The caller must hold self._lock.
        """
        # ...the body that used to be in send_command, unchanged...
```

- [ ] **Step 4: Run it and watch it pass**

Run: `uv run pytest tests/test_concurrency.py -v`
Expected: 3 passed.

- [ ] **Step 5: Run the whole suite and lint**

Run: `uv run pytest && uv run ruff check .`

- [ ] **Step 6: Commit**

```bash
git add src/fl_studio_mcp/utils/midi_connection.py tests/test_concurrency.py
git commit -m "Serialise request cycles so concurrent clients cannot cross-talk"
```

---

### Task 3: A real liveness check

**Files:**
- Modify: `fl_controller/device_FLStudioMCP.py`
- Modify: `src/fl_studio_mcp/utils/midi_connection.py`
- Modify: `src/fl_studio_mcp/server.py`
- Modify: `scripts/dev_verify_connection.py`
- Test: `tests/test_liveness.py`

**Interfaces:**
- Consumes: Task 2's serialisation.
- Produces:
  - Controller action `system.ping`, replying with
    `{"pong": True, "api_version": int | None, "fl_version": str | None, "safe_to_edit": bool | None}`.
  - `MIDIConnection.ping(timeout=1.0) -> dict[str, Any]`
  - `MIDIConnection.wait_until_responsive(timeout=8.0, interval=0.25) -> bool`
  - `fl_connect` reports success only when FL answered.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_liveness.py
"""A port that opened is not a connection.

FL Studio takes 2.0 to 2.3 seconds to bind a newly created virtual port, and
commands sent before that are dropped silently, which is indistinguishable from
FL not being started at all. Opening a port proves only that CoreMIDI accepted the
name.
"""

from __future__ import annotations

import pytest

from fl_studio_mcp.utils.midi_connection import MIDIConnection


@pytest.fixture
def connection(fl_env):
    conn = MIDIConnection()
    conn._command_file = fl_env.command_file
    conn._response_file = fl_env.response_file
    conn._port = fl_env.midi_port
    conn._port_name = fl_env.midi_port.name
    conn._connected = True
    return conn


def test_ping_answers_with_the_environment(connection):
    """One round trip, and the version facts come with it.

    45 and "FL Studio 2026" are what the fake reports, and both match what live
    FL Studio 2026 build 5406 reported in the Phase 0 run.
    """
    result = connection.ping()
    assert result["success"] is True
    assert result["pong"] is True
    assert result["api_version"] == 45
    assert result["fl_version"] == "FL Studio 2026"
    assert result["safe_to_edit"] is True


def test_wait_until_responsive_succeeds_immediately_when_fl_answers(connection):
    assert connection.wait_until_responsive(timeout=1.0) is True


def test_wait_until_responsive_fails_when_nothing_answers(connection, fl_env, monkeypatch):
    """It must give up, and say so, rather than hang for the whole timeout."""
    monkeypatch.setattr(fl_env.controller, "execute_pending_command", lambda: None)
    assert connection.wait_until_responsive(timeout=0.3, interval=0.05) is False


def test_wait_until_responsive_retries_through_the_bind_window(
    connection, fl_env, monkeypatch
):
    """What FL does while it is still binding a new port: drop, drop, answer."""
    original = fl_env.controller.execute_pending_command
    attempts = {"n": 0}

    def drop_the_first_two():
        attempts["n"] += 1
        if attempts["n"] <= 2:
            return
        original()

    monkeypatch.setattr(fl_env.controller, "execute_pending_command", drop_the_first_two)

    assert connection.wait_until_responsive(timeout=2.0, interval=0.05) is True
    assert attempts["n"] >= 3, "the retry loop did not retry"


def test_ping_reports_failure_when_nothing_answers(connection, fl_env, monkeypatch):
    monkeypatch.setattr(fl_env.controller, "execute_pending_command", lambda: None)
    result = connection.ping(timeout=0.05)
    assert result["success"] is False
    assert "Timeout" in result["error"]


def test_ping_survives_a_controller_without_the_action(connection, fl_env, monkeypatch):
    """An older controller answers the ping with an unknown action error."""
    monkeypatch.setattr(
        fl_env.controller,
        "dispatch_command",
        lambda action, params: {"error": f"Unknown action: {action}"},
    )
    result = connection.ping(timeout=1.0)
    assert result["success"] is False
    assert "unknown action" in result["error"].lower()
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/test_liveness.py -v`
Expected: `AttributeError: 'MIDIConnection' object has no attribute 'ping'`.

- [ ] **Step 3: Add the controller action**

In `fl_controller/device_FLStudioMCP.py`, add to `dispatch_command` directly after
the `system.getInfo` branch:

```python
    elif action == "system.ping":
        return handle_system_ping()
```

Add the handler in the System handlers section, after `_safe_to_edit`:

```python
def handle_system_ping() -> dict:
    """Answer a liveness check.

    This is the only action whose purpose is to prove FL answered. It reports the
    environment alongside, so a caller that pings gets the version facts for free
    rather than paying a second round trip for them.
    """
    try:
        api_version = general.getVersion()
    except Exception:
        api_version = None
    try:
        fl_version = ui.getProgTitle()
    except Exception:
        fl_version = None

    return {
        "pong": True,
        "api_version": api_version,
        "fl_version": fl_version,
        "safe_to_edit": _safe_to_edit(),
    }
```

- [ ] **Step 4: Add the server side**

In `src/fl_studio_mcp/utils/midi_connection.py`, add to `MIDIConnection` after
`send_command`:

```python
    def ping(self, timeout: float = 1.0) -> dict[str, Any]:
        """Ask FL Studio whether it is there, and wait for the answer.

        A successful ping is the only evidence that FL is running, listening, and
        executing the controller. An open port is evidence of none of those.
        """
        return self.send_command("system.ping", timeout=timeout)

    def wait_until_responsive(self, timeout: float = 8.0, interval: float = 0.25) -> bool:
        """Ping until FL Studio answers, or the timeout expires.

        Used after creating a virtual port, because FL takes 2.0 to 2.3 seconds to
        bind one and silently drops everything sent before that. Retrying a cheap
        idempotent command is more honest than sleeping for a fixed guess: it
        returns as soon as FL is ready, and reports failure when it never is.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            reply = self.ping(timeout=min(interval * 4, 1.0))
            if reply.get("success") and reply.get("pong"):
                return True
            time.sleep(interval)
        return False
```

In `src/fl_studio_mcp/server.py`, replace `fl_connect`:

```python
@mcp.tool()
def fl_connect() -> str:
    """Connect to FL Studio and confirm it answers.

    Opening a MIDI port only proves the port opened. FL Studio takes two to three
    seconds to bind a new virtual port and commands sent before that vanish, so
    this sends a ping and reports success only when FL replies to it.
    """
    reset_connection()
    conn = get_connection()
    try:
        conn.ensure_connected()
    except RuntimeError as e:
        return f"Connection failed: {e}"

    if not conn.wait_until_responsive():
        return (
            "Opened the MIDI port, but FL Studio did not answer a ping. Check "
            "that FL Studio is running and that the FL Studio MCP Controller is "
            "enabled in Options > MIDI Settings."
        )

    status = conn.get_status()
    return f"Connected to FL Studio, and it is answering, on port {status['port_name']}."
```

- [ ] **Step 5: Run them and watch them pass**

Run: `uv run pytest tests/test_liveness.py -v`
Expected: 6 passed.

- [ ] **Step 6: Measure the handshake live**

In `scripts/dev_verify_connection.py`, in `check_port`, after the status block:

```python
    start = time.perf_counter()
    answered = conn.wait_until_responsive(timeout=8.0)
    elapsed = (time.perf_counter() - start) * 1000
    print(f"ping       : {'answered' if answered else 'NO ANSWER'} after {elapsed:.0f}ms")
```

Then copy the controller into FL and run it:

```bash
cp fl_controller/device_FLStudioMCP.py \
   ~/Documents/Image-Line/FL\ Studio/Settings/Hardware/FLStudioMCP/device_FLStudioMCP.py
uv run python scripts/dev_verify_connection.py
```

Expected: `ping: answered`, round trip OK, API 45, latency near 1ms. Record the
measured ping time in the commit message.

- [ ] **Step 7: Run the whole suite and lint**

Run: `uv run pytest && uv run ruff check .`

- [ ] **Step 8: Commit**

```bash
git add fl_controller/device_FLStudioMCP.py src/fl_studio_mcp/utils/midi_connection.py \
        src/fl_studio_mcp/server.py scripts/dev_verify_connection.py tests/test_liveness.py
git commit -m "Add a ping handshake so liveness is proven rather than assumed"
```

---

### Task 4: Refuse commands that do not say what to act on

**Files:**
- Modify: `fl_controller/device_FLStudioMCP.py`
- Test: `tests/test_required_params.py`

**Interfaces:**
- Consumes: the Phase 0 `fl_env` fixture.
- Produces: handler responses of the form
  `{"error": "<action> requires a '<field>'"}` when a target is absent, so the
  server's existing error propagation turns it into a failure the caller sees.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_required_params.py
"""A missing target must be an error, not a guess.

Every handler that takes an index defaulted to 0, and index 0 is the Master mixer
track or the first channel. A caller that forgot the parameter got a confident
report about the wrong object, and for a write that means editing the master track
of someone's project.
"""

from __future__ import annotations

import pytest

# action, params that omit the target, the field the caller forgot
REQUIRED = [
    ("mixer.getTrackInfo", {}, "track"),
    ("mixer.setTrackVolume", {"volume": 0.5}, "track"),
    ("mixer.setTrackPan", {"pan": 0.0}, "track"),
    ("mixer.setTrackName", {"name": "x"}, "track"),
    ("mixer.setTrackColor", {"r": 1, "g": 2, "b": 3}, "track"),
    ("mixer.muteTrack", {"muted": True}, "track"),
    ("mixer.soloTrack", {"solo": True}, "track"),
    ("mixer.setStereoSep", {"separation": 0.0}, "track"),
    ("channels.getInfo", {}, "index"),
    ("channels.setVolume", {"volume": 0.5}, "index"),
    ("channels.setPan", {"pan": 0.0}, "index"),
    ("channels.setName", {"name": "x"}, "index"),
    ("channels.setColor", {"r": 1, "g": 2, "b": 3}, "index"),
    ("channels.mute", {"muted": True}, "index"),
    ("channels.solo", {"solo": True}, "index"),
    ("channels.select", {"select": True}, "index"),
    ("channels.selectOne", {}, "index"),
    ("channels.routeToMixer", {"mixer_track": 1}, "channel_index"),
    ("channels.getGridBit", {"position": 0}, "channel"),
    ("channels.setGridBit", {"position": 0, "value": True}, "channel"),
    ("channels.getStepSequence", {}, "channel"),
    ("channels.setStepSequence", {"pattern": [True]}, "channel"),
    ("plugins.getParamValue", {"param_index": 0}, "plugin_index"),
    ("plugins.setParamValue", {"param_index": 0, "value": 0.5}, "plugin_index"),
]


@pytest.mark.parametrize("action,params,field", REQUIRED)
def test_a_missing_target_is_refused(fl_env, action, params, field):
    result = fl_env.controller.dispatch_command(action, params)
    assert "error" in result, f"{action} accepted params with no {field}"
    assert field in result["error"], f"{action} did not name the missing {field}"


@pytest.mark.parametrize("action,params,field", REQUIRED)
def test_a_supplied_target_is_accepted(fl_env, action, params, field):
    """The guard must not reject a caller that did supply the target."""
    supplied = dict(params)
    supplied[field] = 1
    result = fl_env.controller.dispatch_command(action, supplied)
    assert "requires" not in str(result.get("error", "")), (
        f"{action} refused a call that supplied {field}: {result.get('error')}"
    )


def test_an_index_of_zero_is_still_accepted(fl_env):
    """Zero is a real index. Only its absence is an error."""
    result = fl_env.controller.dispatch_command("mixer.getTrackInfo", {"track": 0})
    assert "error" not in result


def test_the_error_names_the_action_and_the_field(fl_env):
    result = fl_env.controller.dispatch_command("mixer.setTrackVolume", {"volume": 0.5})
    assert result["error"] == "mixer.setTrackVolume requires a 'track'"


def test_a_missing_target_through_the_round_trip_is_a_failure(fl_env):
    """The server must turn the controller's error into a reported failure."""
    from fl_studio_mcp.utils.midi_connection import MIDIConnection

    conn = MIDIConnection()
    conn._command_file = fl_env.command_file
    conn._response_file = fl_env.response_file
    conn._port = fl_env.midi_port
    conn._connected = True

    result = conn.send_command("mixer.setTrackVolume", {"volume": 0.5}, timeout=2.0)

    assert result["success"] is False
    assert "track" in result["error"]
    assert fl_env.project.track(0).volume == pytest.approx(0.8), "the master was edited"
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/test_required_params.py -v`
Expected: every case in `test_a_missing_target_is_refused` fails, because the
handler silently used index 0. `test_the_error_names_the_action_and_the_field`
fails with a missing `error` key. The round trip test fails because the volume was
set on the master track.

- [ ] **Step 3: Add the guard helper to the controller**

In `fl_controller/device_FLStudioMCP.py`, add near the top of the handlers, after
`_safe_to_edit`:

```python
def _require(params: dict, name: str, action: str):
    """Return a required parameter, or raise a ValueError naming it.

    Every handler used to default its index to 0, and index 0 is the Master mixer
    track or the first channel. A caller that forgot the parameter got a confident
    answer about the wrong object, and a write edited the master track of someone's
    project. Refusing is the only safe default.

    Zero is a real index, so only absence is an error, never falsiness.
    """
    if name not in params or params[name] is None:
        raise ValueError(f"{action} requires a '{name}'")
    return params[name]
```

- [ ] **Step 4: Make dispatch turn that into a proper error**

`dispatch_command` currently lets a handler's exception escape to
`execute_pending_command`, which reports `Error executing command: ...`. That works,
but the message then contains a Python traceback prefix. Catch `ValueError`
specifically so the caller gets the sentence and nothing else.

In `execute_pending_command`, add a branch before the generic `except Exception`:

```python
    except ValueError as e:
        # A handler refusing bad input. The message is already written for the
        # caller, so pass it through unwrapped.
        response["error"] = str(e)
    except Exception as e:
        response["error"] = f"Error executing command: {e}"
```

- [ ] **Step 5: Apply the guard to every handler in the table**

For each entry in `REQUIRED`, replace the defaulting read with a guarded one. The
pattern, shown for two handlers:

```python
def handle_mixer_set_track_volume(params: dict) -> dict:
    """Set mixer track volume."""
    track = _require(params, "track", "mixer.setTrackVolume")
    volume = params.get("volume", 0.8)
    ...


def handle_channels_set_volume(params: dict) -> dict:
    """Set channel volume."""
    index = _require(params, "index", "channels.setVolume")
    volume = params.get("volume", 0.8)
    ...
```

Note that `channels.routeToMixer` guards `channel_index`, not `mixer_track`: the
channel is what identifies the target, and `mixer_track` is the value being
written.

Leave handlers whose target genuinely is optional, or which have no target at all,
alone: the `getAll`, `getCount`, `getAllTracks`, transport, system, and
`plugins.isValid` handlers.

- [ ] **Step 6: Run them and watch them pass**

Run: `uv run pytest tests/test_required_params.py -v`
Expected: 51 passed (24 refused, 24 accepted, 3 singles).

- [ ] **Step 7: Run the whole suite and lint**

Run: `uv run pytest && uv run ruff check .`
Expected: green. `tests/test_controller_handlers.py` calls several of these
handlers with an explicit index already, so it should be unaffected. If a Phase 0
handler test passes no index, it is now wrong: add the index it meant.

- [ ] **Step 8: Copy the controller into FL and check nothing regressed**

```bash
cp fl_controller/device_FLStudioMCP.py \
   ~/Documents/Image-Line/FL\ Studio/Settings/Hardware/FLStudioMCP/device_FLStudioMCP.py
uv run python scripts/dev_verify_connection.py
```

Then exercise one refusal by hand, which is read-only in effect because the
command is refused:

```bash
uv run python -c "
from fl_studio_mcp.utils.midi_connection import get_connection
conn = get_connection(); conn.connect()
print(conn.send_command('mixer.setTrackVolume', {'volume': 0.5}, timeout=3.0))
"
```

Expected: `success: False` and an error naming `track`. Confirm the Master track
volume is unchanged by reading it back with `mixer.getTrackInfo`.

- [ ] **Step 9: Commit**

```bash
git add fl_controller/device_FLStudioMCP.py tests/test_required_params.py \
        tests/test_controller_handlers.py
git commit -m "Refuse commands that do not say which track or channel to act on"
```

---

### Task 5: Batch execution with undo grouping

**Files:**
- Modify: `fl_controller/device_FLStudioMCP.py`
- Create: `src/fl_studio_mcp/tools/batch.py`
- Modify: `src/fl_studio_mcp/tools/__init__.py`
- Modify: `src/fl_studio_mcp/server.py`
- Test: `tests/test_batch.py`
- Test: `tests/test_undo.py`

**Interfaces:**
- Consumes: Task 4's guards, Task 3's ping.
- Produces:
  - Controller action `system.batch`, params
    `{"commands": [{"action": str, "params": dict}, ...], "name": str}`, replying
    `{"success": bool, "results": [dict, ...], "executed": int, "failed": int,
    "undo_name": str}`. A failed command mid-batch stops the batch and marks the
    remaining entries `{"skipped": True}`.
  - Controller actions `general.saveUndo`, `general.undo`,
    `general.getUndoHistoryCount`.
  - `fl_studio_mcp.tools.batch.register_batch_tools(mcp)` registering
    `fl_batch`, `fl_undo`, and `fl_undo_history`.

- [ ] **Step 1: Write the failing controller tests**

```python
# tests/test_batch.py
"""Many commands, one trigger, one undo step.

The motivation is atomicity and undo grouping, not speed: once the poll interval
is right a round trip is about a millisecond, so sixteen separate notes cost about
sixteen milliseconds and speed is not the problem. What is a problem is that
sixteen separate edits are sixteen Ctrl+Z presses, and that a failure half way
through leaves the project in a state nobody asked for.
"""

from __future__ import annotations

import pytest


def test_a_batch_executes_every_command_in_order(fl_env):
    result = fl_env.controller.dispatch_command("system.batch", {
        "commands": [
            {"action": "channels.setVolume", "params": {"index": 1, "volume": 0.1}},
            {"action": "channels.setVolume", "params": {"index": 2, "volume": 0.2}},
            {"action": "channels.setVolume", "params": {"index": 3, "volume": 0.3}},
        ],
    })
    assert result["success"] is True
    assert result["executed"] == 3
    assert fl_env.project.channel(1).volume == pytest.approx(0.1)
    assert fl_env.project.channel(2).volume == pytest.approx(0.2)
    assert fl_env.project.channel(3).volume == pytest.approx(0.3)


def test_a_batch_is_one_undo_step(fl_env):
    """One AI edit has to be one Ctrl+Z, not one per command."""
    before = fl_env.controller.dispatch_command("general.getUndoHistoryCount", {})["count"]
    fl_env.controller.dispatch_command("system.batch", {
        "commands": [
            {"action": "channels.setVolume", "params": {"index": 1, "volume": 0.1}},
            {"action": "channels.setVolume", "params": {"index": 2, "volume": 0.2}},
        ],
        "name": "AI edit: two volumes",
    })
    after = fl_env.controller.dispatch_command("general.getUndoHistoryCount", {})["count"]
    assert after == before + 1, "the batch produced more than one undo entry"


def test_a_batch_reports_the_undo_name(fl_env):
    result = fl_env.controller.dispatch_command("system.batch", {
        "commands": [{"action": "channels.setVolume", "params": {"index": 1, "volume": 0.1}}],
        "name": "AI edit: one volume",
    })
    assert result["undo_name"] == "AI edit: one volume"


def test_a_batch_stops_at_the_first_failure(fl_env):
    """Continuing past a failure would leave a half-applied edit."""
    result = fl_env.controller.dispatch_command("system.batch", {
        "commands": [
            {"action": "channels.setVolume", "params": {"index": 1, "volume": 0.1}},
            {"action": "channels.setVolume", "params": {"volume": 0.2}},  # no index
            {"action": "channels.setVolume", "params": {"index": 3, "volume": 0.3}},
        ],
    })
    assert result["success"] is False
    assert result["executed"] == 1
    assert result["failed"] == 1
    assert result["results"][1]["error"]
    assert result["results"][2].get("skipped") is True
    assert fl_env.project.channel(1).volume == pytest.approx(0.1)
    assert fl_env.project.channel(3).volume == pytest.approx(0.8), "a skipped command ran"


def test_a_batch_reports_every_result(fl_env):
    result = fl_env.controller.dispatch_command("system.batch", {
        "commands": [
            {"action": "mixer.getTrackCount", "params": {}},
            {"action": "channels.getCount", "params": {}},
        ],
    })
    assert [entry.get("count") for entry in result["results"]] == [8, 4]


def test_an_empty_batch_is_refused(fl_env):
    result = fl_env.controller.dispatch_command("system.batch", {"commands": []})
    assert "error" in result
    assert "commands" in result["error"]


def test_a_batch_refuses_to_nest(fl_env):
    """A batch inside a batch would produce a second undo entry."""
    result = fl_env.controller.dispatch_command("system.batch", {
        "commands": [{"action": "system.batch", "params": {"commands": []}}],
    })
    assert result["success"] is False
    assert "batch" in result["results"][0]["error"].lower()


def test_a_batch_refuses_an_unknown_action(fl_env):
    result = fl_env.controller.dispatch_command("system.batch", {
        "commands": [{"action": "bogus.doesNotExist", "params": {}}],
    })
    assert result["success"] is False
    assert result["results"][0]["error"]


def test_a_batch_through_the_round_trip_is_one_command(fl_env):
    """One trigger, not one per entry, which is what makes it atomic."""
    from fl_studio_mcp.utils.midi_connection import MIDIConnection

    conn = MIDIConnection()
    conn._command_file = fl_env.command_file
    conn._response_file = fl_env.response_file
    conn._port = fl_env.midi_port
    conn._connected = True

    result = conn.send_command("system.batch", {
        "commands": [
            {"action": "channels.setVolume", "params": {"index": 1, "volume": 0.1}},
            {"action": "channels.setVolume", "params": {"index": 2, "volume": 0.2}},
        ],
    }, timeout=2.0)

    assert result["success"] is True
    assert fl_env.trigger_count == 1, "the batch triggered more than once"
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/test_batch.py -v`
Expected: every test fails with `Unknown action: system.batch`.

- [ ] **Step 3: Add the batch and undo actions to the controller**

In `fl_controller/device_FLStudioMCP.py`, add to `dispatch_command` after the
`system.ping` branch:

```python
    elif action == "system.batch":
        return handle_system_batch(params)
```

and the undo actions in a new section before the Mixer handlers:

```python
# =============================================================================
# Undo Handlers
# =============================================================================


def handle_general_save_undo(params: dict) -> dict:
    """Save an undo point.

    General.saveUndo was added in API 29 along with safeToEdit, so an older FL
    cannot do this. Reporting that honestly is better than pretending the edit is
    undoable.
    """
    name = params.get("name", "MCP edit")
    try:
        general.saveUndo(name, 0)
    except Exception as e:
        return {"error": f"general.saveUndo is unavailable: {e}"}
    return {"saved": True, "name": name, "count": _undo_count()}


def handle_general_undo(params: dict) -> dict:
    """Undo one step."""
    general.undo()
    return {"count": _undo_count()}


def handle_general_get_undo_history_count(params: dict) -> dict:
    """Report how many undo steps exist, so a caller can see its own edit."""
    return {"count": _undo_count()}


def _undo_count() -> int | None:
    """Undo history depth, or None where the API does not provide it."""
    try:
        return general.getUndoHistoryCount()
    except Exception:
        return None
```

Add the batch handler in the System handlers section:

```python
def handle_system_batch(params: dict) -> dict:
    """Run several commands from one trigger, inside one undo point.

    The motivation is atomicity and undo grouping rather than speed: a round trip
    is about a millisecond, so batching sixteen notes saves fifteen of them, which
    does not matter, while turning sixteen Ctrl+Z presses into one does.

    A failure stops the batch. The commands after it are reported as skipped
    rather than run, because a half-applied edit that claims success is worse than
    one that reports where it stopped.
    """
    commands = params.get("commands")
    if not isinstance(commands, list) or not commands:
        return {"error": "system.batch requires a non-empty 'commands' list"}

    for index, command in enumerate(commands):
        if not isinstance(command, dict) or not command.get("action"):
            return {"error": f"system.batch command {index} has no 'action'"}

    name = params.get("name") or "MCP edit"

    try:
        general.saveUndo(name, 0)
        undo_name = name
    except Exception:
        # An FL older than API 29. The batch still runs; it just cannot be one
        # undo step, and the reply says so rather than implying otherwise.
        undo_name = None

    results = []
    failed = 0
    executed = 0

    for command in commands:
        action = command["action"]
        if action == "system.batch":
            results.append({"error": "a batch may not contain a batch"})
            failed += 1
            break
        try:
            result = dispatch_command(action, command.get("params", {}))
        except ValueError as e:
            result = {"error": str(e)}
        except Exception as e:
            result = {"error": f"Error executing command: {e}"}
        results.append(result)
        if "error" in result:
            failed += 1
            break
        executed += 1

    remaining = len(commands) - len(results)
    results.extend({"skipped": True} for _ in range(remaining))

    return {
        "success": failed == 0,
        "results": results,
        "executed": executed,
        "failed": failed,
        "undo_name": undo_name,
    }
```

Wire the undo actions into `dispatch_command`:

```python
    # Undo commands
    elif action == "general.saveUndo":
        return handle_general_save_undo(params)
    elif action == "general.undo":
        return handle_general_undo(params)
    elif action == "general.getUndoHistoryCount":
        return handle_general_get_undo_history_count(params)
```

- [ ] **Step 4: Run the controller tests and watch them pass**

Run: `uv run pytest tests/test_batch.py -v`
Expected: 10 passed.

- [ ] **Step 5: Write the failing server-side tests**

```python
# tests/test_undo.py
"""fl_batch, fl_undo and fl_undo_history, through the round trip."""

from __future__ import annotations

import pytest

from fl_studio_mcp.tools import batch


@pytest.fixture
def connection(fl_env, monkeypatch):
    """The batch tools wired to the in-process controller."""
    from fl_studio_mcp.utils.midi_connection import MIDIConnection

    conn = MIDIConnection()
    conn._command_file = fl_env.command_file
    conn._response_file = fl_env.response_file
    conn._port = fl_env.midi_port
    conn._connected = True
    monkeypatch.setattr(batch, "get_connection", lambda: conn)
    return conn


def test_batch_runs_commands_and_reports_success(connection, fl_env):
    result = batch.run_batch([
        {"action": "channels.setVolume", "params": {"index": 1, "volume": 0.1}},
        {"action": "channels.setVolume", "params": {"index": 2, "volume": 0.2}},
    ], name="two volumes")
    assert result["success"] is True
    assert result["executed"] == 2
    assert fl_env.project.channel(1).volume == pytest.approx(0.1)


def test_batch_needs_commands(connection):
    result = batch.run_batch([], name="nothing")
    assert result["success"] is False
    assert "command" in result["error"].lower()


def test_batch_reports_where_it_stopped(connection):
    result = batch.run_batch([
        {"action": "channels.setVolume", "params": {"index": 1, "volume": 0.1}},
        {"action": "channels.setVolume", "params": {"volume": 0.2}},
    ], name="half bad")
    assert result["success"] is False
    assert result["executed"] == 1
    assert result["results"][1]["error"]


def test_batch_requires_a_name(connection):
    """The name is what the user sees in FL's undo history."""
    result = batch.run_batch(
        [{"action": "mixer.getTrackCount", "params": {}}], name=""
    )
    assert result["success"] is False
    assert "name" in result["error"].lower()


def test_undo_reports_the_remaining_depth(connection, fl_env):
    fl_env.project.undo_stack = ["a", "b", "c"]
    result = batch.run_undo()
    assert result["success"] is True
    assert result["count"] == 2


def test_undo_history_reports_the_depth(connection, fl_env):
    fl_env.project.undo_stack = ["a", "b"]
    result = batch.run_undo_history()
    assert result["count"] == 2
```

- [ ] **Step 6: Run them and watch them fail**

Run: `uv run pytest tests/test_undo.py -v`
Expected: `ModuleNotFoundError: No module named 'fl_studio_mcp.tools.batch'`.

- [ ] **Step 7: Write the batch tools**

```python
# src/fl_studio_mcp/tools/batch.py
"""Batch execution, undo and undo history.

Batching exists so one logical edit is one trigger and one undo step. The
roadmap is explicit that speed is not the motivation: a round trip is about a
millisecond, so sixteen notes cost sixteen milliseconds and nobody cares. What
matters is that sixteen edits are not sixteen Ctrl+Z presses, and that a failure
half way through does not leave a half-applied edit reported as a success.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fl_studio_mcp.utils.connection import get_connection

if TYPE_CHECKING:
    from fastmcp import FastMCP

# A batch is one trigger, but the controller still has to run every command in it,
# so it gets a longer window than a single command.
BATCH_TIMEOUT = 15.0


def run_batch(commands: list[dict], name: str) -> dict[str, Any]:
    """Run several commands from one trigger, inside one undo point.

    Args:
        commands: Entries of the form {"action": str, "params": dict}.
        name: What this edit is called in FL Studio's undo history. Required,
            because an unnamed edit in the undo list is not much better than no
            undo entry at all.

    Returns:
        The controller's batch report: "success", "results" in order,
        "executed", "failed" and "undo_name". A failure stops the batch and the
        remaining entries are marked "skipped".
    """
    if not commands:
        return {
            "success": False,
            "error": "A batch needs at least one command.",
        }
    if not name or not name.strip():
        return {
            "success": False,
            "error": (
                "A batch needs a 'name'. It becomes the undo entry, so the user "
                "sees what the edit was rather than 'Undo'."
            ),
        }

    for index, command in enumerate(commands):
        if "action" not in command:
            return {
                "success": False,
                "error": f"Command {index} has no 'action'.",
            }

    reply = get_connection().send_command(
        "system.batch",
        {"commands": commands, "name": name},
        timeout=BATCH_TIMEOUT,
    )

    if not reply.get("undo_name") and reply.get("success"):
        reply["warning"] = (
            "This FL Studio does not support general.saveUndo, so the batch is "
            "not a single undo step."
        )
    return reply


def run_undo() -> dict[str, Any]:
    """Undo one step in FL Studio."""
    reply = get_connection().send_command("general.undo", timeout=5.0)
    if reply.get("success"):
        reply["message"] = "Undid one step."
    return reply


def run_undo_history() -> dict[str, Any]:
    """Report how many undo steps FL Studio holds."""
    return get_connection().send_command("general.getUndoHistoryCount", timeout=5.0)


def register_batch_tools(mcp: FastMCP) -> None:
    """Register batch and undo tools with the MCP server."""

    @mcp.tool()
    def fl_batch(commands: list[dict], name: str) -> dict:
        """Run several FL Studio commands as one edit.

        Use this instead of many separate tool calls whenever the commands
        belong together: writing a drum pattern, setting up a mix, applying a
        gain change across tracks. One trigger, and one undo step, so a single
        Ctrl+Z reverses the whole edit.

        A failure stops the batch. Commands after the failure are reported as
        skipped rather than run, so the project is never left half edited
        without the caller knowing exactly where it stopped.

        Args:
            commands: Commands to run, in order. Each is a dict with:
                      - action (str): the command, e.g. "channels.setVolume"
                      - params (dict): its parameters
            name: What this edit is called in FL Studio's undo history. Say what
                  the user did, for example "AI edit: drum pattern".

        Returns:
            success: whether every command ran
            results: one entry per command, in order, with "skipped": true for
                     those that never ran
            executed / failed: counts
            undo_name: the undo entry name, or null if this FL cannot group

        Example:
            fl_batch(
                name="AI edit: four on the floor",
                commands=[
                    {"action": "channels.setGridBit",
                     "params": {"channel": 0, "position": 0, "value": True}},
                    {"action": "channels.setGridBit",
                     "params": {"channel": 0, "position": 4, "value": True}},
                ],
            )
        """
        return run_batch(commands, name)

    @mcp.tool()
    def fl_undo() -> dict:
        """Undo one step in FL Studio.

        Undoes one logical edit, which is one fl_batch call or one tool call,
        not one underlying API change.
        """
        return run_undo()

    @mcp.tool()
    def fl_undo_history() -> dict:
        """Report how deep FL Studio's undo history is.

        Useful for confirming that an edit is undoable before making it, and for
        checking that a batch produced exactly one entry.
        """
        return run_undo_history()
```

- [ ] **Step 8: Register the tools and run the tests**

In `src/fl_studio_mcp/tools/__init__.py`, export `register_batch_tools` the same
way the others are exported. In `src/fl_studio_mcp/server.py`, import it and add
`register_batch_tools(mcp)` to the registration block.

Run: `uv run pytest tests/test_undo.py tests/test_batch.py -v`
Expected: all pass.

- [ ] **Step 9: Run the whole suite and lint**

Run: `uv run pytest && uv run ruff check .`

- [ ] **Step 10: Verify the batch live, restoring afterwards**

```bash
cp fl_controller/device_FLStudioMCP.py \
   ~/Documents/Image-Line/FL\ Studio/Settings/Hardware/FLStudioMCP/device_FLStudioMCP.py
```

Then, having told the user first, run a batch that sets and restores a value so
the project is unchanged at the end:

```bash
uv run python -c "
from fl_studio_mcp.utils.midi_connection import get_connection
conn = get_connection(); conn.connect()
before = conn.send_command('mixer.getTrackInfo', {'track': 1}, timeout=3.0)
print('before:', before.get('volume'))
batch = conn.send_command('system.batch', {'name': 'MCP phase 1 check', 'commands': [
    {'action': 'mixer.setTrackVolume', 'params': {'track': 1, 'volume': 0.5}},
    {'action': 'mixer.setTrackVolume', 'params': {'track': 1, 'volume': before.get('volume')}},
]}, timeout=15.0)
print('batch:', {k: batch.get(k) for k in ('success', 'executed', 'failed', 'undo_name')})
after = conn.send_command('mixer.getTrackInfo', {'track': 1}, timeout=3.0)
print('after :', after.get('volume'))
"
```

Expected: `success: True`, `executed: 2`, `undo_name: "MCP phase 1 check"`, and
`after` equal to `before`. Then call `fl_undo_history` and confirm the depth grew
by exactly one.

- [ ] **Step 11: Commit**

```bash
git add fl_controller/device_FLStudioMCP.py src/fl_studio_mcp/tools/batch.py \
        src/fl_studio_mcp/tools/__init__.py src/fl_studio_mcp/server.py \
        tests/test_batch.py tests/test_undo.py
git commit -m "Add batch execution so one edit is one trigger and one undo step"
```

---

### Task 6: Edit safety

**Files:**
- Modify: `fl_controller/device_FLStudioMCP.py`
- Test: `tests/test_edit_safety.py`

**Interfaces:**
- Consumes: `_safe_to_edit` from Phase 0, Task 4's guards.
- Produces: a mutating action returns
  `{"error": "Refusing to edit: FL Studio reports it is not safe to edit ..."}`
  when `general.safeToEdit()` is false, and the handlers are unchanged when it is
  true or unknown.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_edit_safety.py
"""Refuse to mutate a project FL says is not safe to edit.

general.safeToEdit was added in API 29 and returns whether FL is in a state where
the project may be changed: during some operations it is not. Editing anyway can
corrupt the project, so the honest response is to refuse.

An older FL cannot answer the question at all. That is "unknown", and refusing on
unknown would break every install below API 29, so unknown proceeds.
"""

from __future__ import annotations

import pytest

MUTATING = [
    ("channels.setVolume", {"index": 1, "volume": 0.5}),
    ("channels.mute", {"index": 1, "muted": True}),
    ("channels.setGridBit", {"channel": 1, "position": 0, "value": True}),
    ("mixer.setTrackVolume", {"track": 1, "volume": 0.5}),
    ("mixer.setTrackName", {"track": 1, "name": "x"}),
    ("mixer.muteTrack", {"track": 1, "muted": True}),
    ("transport.start", {}),
]

READ_ONLY = [
    ("channels.getInfo", {"index": 1}),
    ("mixer.getTrackInfo", {"track": 1}),
    ("mixer.getTrackCount", {}),
    ("transport.getStatus", {}),
    ("system.getInfo", {}),
]


@pytest.mark.parametrize("action,params", MUTATING)
def test_a_mutation_is_refused_when_fl_is_not_safe_to_edit(fl_env, action, params):
    fl_env.project.safe_to_edit = False
    result = fl_env.controller.dispatch_command(action, params)
    assert "error" in result, f"{action} edited a project FL said not to touch"
    assert "safe to edit" in result["error"].lower()


@pytest.mark.parametrize("action,params", READ_ONLY)
def test_reads_are_never_refused(fl_env, action, params):
    """Reading cannot corrupt anything, and a diagnostic must work when stuck."""
    fl_env.project.safe_to_edit = False
    result = fl_env.controller.dispatch_command(action, params)
    assert "error" not in result, f"{action} was refused but only reads"


@pytest.mark.parametrize("action,params", MUTATING)
def test_a_mutation_proceeds_when_it_is_safe(fl_env, action, params):
    fl_env.project.safe_to_edit = True
    result = fl_env.controller.dispatch_command(action, params)
    assert "error" not in result


def test_an_unknown_answer_proceeds(fl_env):
    """API 29 is a floor, and below it the question cannot be asked.

    Deleting the function is exactly what an FL older than API 29 looks like from
    the controller's side.
    """
    del fl_env.modules["general"].safeToEdit
    result = fl_env.controller.dispatch_command(
        "channels.setVolume", {"index": 1, "volume": 0.5}
    )
    assert "error" not in result, "an older FL was refused for an unanswerable question"


def test_the_refusal_does_not_change_anything(fl_env):
    fl_env.project.safe_to_edit = False
    fl_env.controller.dispatch_command("channels.setVolume", {"index": 1, "volume": 0.1})
    assert fl_env.project.channel(1).volume == pytest.approx(0.8)


def test_a_batch_is_refused_whole(fl_env):
    """A batch must not run half its commands before hitting the guard."""
    fl_env.project.safe_to_edit = False
    result = fl_env.controller.dispatch_command("system.batch", {
        "commands": [{"action": "channels.setVolume", "params": {"index": 1, "volume": 0.1}}],
    })
    assert result["success"] is False
    assert fl_env.project.channel(1).volume == pytest.approx(0.8)
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/test_edit_safety.py -v`
Expected: every mutating case fails, because the guard does not exist yet.
`test_a_batch_is_refused_whole` fails because the batch runs its command.

- [ ] **Step 3: Add the guard and a registry of mutating actions**

In `fl_controller/device_FLStudioMCP.py`, add after `_require`:

```python
# Actions that change the project. Anything not listed here is treated as a read,
# which is the safe default in the only direction that matters: refusing a read
# would break diagnostics exactly when a user needs them, while allowing a write
# silently corrupts the project.
MUTATING_ACTIONS = frozenset([
    "channels.setChannelColor",
    "channels.setChannelName",
    "channels.setChannelPan",
    "channels.setChannelPitch",
    "channels.setChannelVolume",
    "channels.setColor",
    "channels.setGridBit",
    "channels.setName",
    "channels.setPan",
    "channels.setStepSequence",
    "channels.setVolume",
    "channels.mute",
    "channels.muteChannel",
    "channels.solo",
    "channels.soloChannel",
    "channels.routeToMixer",
    "channels.select",
    "channels.selectOne",
    "channels.triggerNote",
    "channels.setTargetFxTrack",
    "general.restoreUndo",
    "general.restoreUndoLevel",
    "general.undo",
    "mixer.armTrack",
    "mixer.muteTrack",
    "mixer.setStereoSep",
    "mixer.setTrackColor",
    "mixer.setTrackName",
    "mixer.setTrackPan",
    "mixer.setTrackVolume",
    "mixer.soloTrack",
    "plugins.nextPreset",
    "plugins.prevPreset",
    "plugins.setParamValue",
    "system.batch",
    "transport.record",
    "transport.setLoopMode",
    "transport.setPlaybackSpeed",
    "transport.setPosition",
    "transport.start",
    "transport.stop",
])


def _check_editable(action: str):
    """Refuse a mutation when FL reports the project is not safe to edit.

    None means the question could not be asked, which is what API versions below
    29 give. Unknown is not the same as no: refusing on unknown would break every
    install older than API 29, so unknown proceeds.
    """
    if action not in MUTATING_ACTIONS:
        return None
    if _safe_to_edit() is False:
        return {
            "error": (
                f"Refusing to edit: FL Studio reports it is not safe to edit the "
                f"project right now, so {action} was not run. Try again once the "
                "current operation has finished."
            )
        }
    return None
```

- [ ] **Step 4: Call the guard from `execute_pending_command` and from batches**

In `execute_pending_command`, before dispatching:

```python
        refusal = _check_editable(action)
        if refusal is not None:
            response = {"success": False, "id": request_id, **refusal}
            write_response(response)
            return
```

In the batch loop, check the batch as a whole before it starts, and each entry
inside it:

```python
    refusal = _check_editable("system.batch")
    if refusal is not None:
        return refusal
```

and inside the loop, before `dispatch_command`:

```python
        refusal = _check_editable(action)
        if refusal is not None:
            results.append(refusal)
            failed += 1
            break
```

The whole-batch check is what makes the refusal all-or-nothing: without it, a
batch would apply its first command and then stop.

- [ ] **Step 5: Run them and watch them pass**

Run: `uv run pytest tests/test_edit_safety.py -v`
Expected: 21 passed.

- [ ] **Step 6: Add the controller tests for the ping and batch guards**

Run the whole suite:

Run: `uv run pytest && uv run ruff check .`

- [ ] **Step 7: Verify live, without changing the project**

```bash
cp fl_controller/device_FLStudioMCP.py \
   ~/Documents/Image-Line/FL\ Studio/Settings/Hardware/FLStudioMCP/device_FLStudioMCP.py
uv run python scripts/dev_verify_connection.py
```

Expected: `safeToEdit` reads true on the live project, so the guard does not fire
and behaviour is unchanged. Confirm that with the refusal message absent from the
run, and note in the commit that the refusal path itself could only be exercised
against the fake, because forcing `safeToEdit` false on a live project is not
something this session should do to a user's open work.

- [ ] **Step 8: Commit**

```bash
git add fl_controller/device_FLStudioMCP.py tests/test_edit_safety.py
git commit -m "Refuse to mutate a project FL Studio says is not safe to edit"
```

---

## Phase 1 exit criteria

Checked on 2026-09-19 against the committed tree and live FL Studio 2026.

- [x] A forced timeout followed by a second command executes that second command
      exactly once. Verified live: the 1ms call timed out with its trigger in
      flight and the follow-up wrote exactly one response. The original audit
      could not reproduce this race, which is why the check now says whether the
      race was actually exercised rather than reporting a flat pass.
- [x] Two concurrent clients each receive their own answers. Ten threads asking
      two different questions get ten correctly attributed answers. Without the
      lock all ten get nothing, measured by disabling it.
- [x] A reply that belongs to another request is never consumed.
- [x] `fl_connect` reports success only when FL answers a ping, measured at 3ms.
- [x] A mutating handler with no target refuses and names the missing field.
      Verified live, with the Master track volume unchanged.
- [x] A batch runs from one trigger and stops at its first failure, reporting the
      rest as skipped. Verified live.
- [x] A mutation is refused when `general.safeToEdit()` is false, and proceeds
      when it is true or unknown. Fake-tested only, deliberately: the live project
      reports true and forcing it false would be editing someone's work to test a
      refusal.
- [x] `pytest` green and `ruff check .` clean with no FL Studio running. 278 tests
      from a clean clone with `uv sync --dev --locked`.
- [x] `dev_verify_connection.py` reports a round trip near 1ms, a successful ping,
      and the unknown-action and double-execution checks passing.
- [x] `docs/SMOKE_TEST.md` has a Phase 1 section recording the live run and what
      could not be run.

### Where this plan was wrong

Recorded so the plan does not read as if it went the way it was written.

- It asked for a batch to be one undo step through `general.saveUndo`. That is
  not achievable, and the plan inherited the claim from the roadmap. Measured: a
  bare `saveUndo` adds no history entry and does not reduce how many undos an edit
  needs, and the API has no grouping flag. The batch still calls nothing for
  grouping, and reports the undo history size as an observation rather than
  deriving a step count that would sometimes be the wrong sign.
- It did not anticipate that `general.undo()` is a toggle. That is documented in
  the stubs and confirmed live, and it meant the single-step undo undone once and
  then redid.
- It planned to measure a batch's undo cost from `getUndoHistoryCount`. That
  number does not predict the step count, so the plan was adjusted to measure the
  step count directly, by undoing until the state was restored, across three
  trials.

## What Phase 1 deliberately does not do

- It does not add the `channel` argument to the piano roll tools, or read the
  pyscript's reply for targeting purposes. That is Phase 2, and the reply plumbing
  it needs already landed in Phase 0.
- It does not add API breadth: patterns, EQ, routing, metering, playlist and
  arrangement are Phase 3.
- It does not retry a dropped command at the transport level. `wait_until_responsive`
  handles the one window where commands are known to be dropped, which is startup.
  A general retry policy needs evidence that drops happen elsewhere, and there is
  none.
