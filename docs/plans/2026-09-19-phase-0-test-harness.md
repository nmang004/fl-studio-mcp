# Phase 0: Test Harness and CI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the FL-side scripts importable and testable on a machine with no
FL Studio installed, so every later phase can be developed test-first.

**Architecture:** A package of fake FL API modules, backed by a single in-memory
`FakeProject`, is injected into `sys.modules`. The real controller script and the
real piano roll script are then loaded from their real paths through
`importlib.util.spec_from_file_location`, so the code under test is exactly the
code that ships, not a copy. A fake MIDI port closes the loop: sending the
trigger note from the server-side `MIDIConnection` synchronously invokes the
controller's own trigger handler, and the two sides exchange the real JSON files
in a `tmp_path`.

**Tech Stack:** pytest 9, ruff 0.16, mido 1.3, GitHub Actions, `uv`.

**Spec:** `ROADMAP.md` (Phase 0, Global constraints, sandbox rules);
`docs/spikes/2026-09-19-T4-sysex-transport.md` (why Phase 1 is unaffected).

## Global Constraints

Copied verbatim from ROADMAP.md, and implicitly part of every task:

- Python `>=3.10`, ruff `target-version = "py310"`.
- `ruff check .` clean, line length 100, rules `E`, `F`, `I`, `W`.
- `pytest` green with no FL Studio running.
- Keep `constraint-dependencies = ["cryptography<49"]` in `pyproject.toml`.
- macOS and Windows must both keep working.
- No em dashes and no en dashes anywhere, in code, comments, docs, UI strings or
  commit messages. No emoji. No AI or assistant attribution.
- Commits scoped to one concern, so individual fixes stay cherry-pickable to
  upstream.
- FL Studio's embedded Python has no `__file__`, a restricted stdlib, and no
  package installation. The controller script must import only FL modules plus
  `json`, `os`, `sys` and `pathlib`. It must not import anything from
  `fl_studio_mcp`.
- The piano roll script's only FL module is `flpianoroll`. It cannot see
  `channels` or `mixer`.

### Fidelity rule for the fakes

A fake must never be more capable than the real API. Every fake function mirrors
the stub signature exactly, in parameter names, defaults and positional-only
markers, and returns the documented type. Where the stub documents a range
(volume `0.0` to `1.0`, pan `-1.0` to `1.0`), the fake clamps to it. Where a
function does not exist in the stubs, the fake does not define it, so a test that
calls it fails loudly: this is how the harness proves `playlist` has no clip
placement. Functions that belong to a later phase are defined but raise
`NotImplementedError("<name> is not modelled yet")`, so that `parity` in Task 3
passes on presence while unfinished behaviour is impossible to mistake for
working behaviour.

### File structure

```
src/fl_studio_mcp/utils/paths.py     new. Settings directory resolution, shared by the whole server
fl_controller/device_FLStudioMCP.py  modify. Settings dir override; undo grouping; edit safety
scripts/ComposeWithLLM.pyscript      modify. Settings dir override; write mcp_response.json reply
tests/fakes/__init__.py              new. install(), uninstall(), FakeFL
tests/fakes/project.py               new. FakeProject and the data records
tests/fakes/modules/__init__.py      new. build_fake_modules(project) -> dict[str, ModuleType]
tests/fakes/modules/*.py             new. One file per FL module
tests/fakes/midi.py                  new. FakeMidiPort, FakeMidiModule
tests/conftest.py                    new. fl_env fixture
tests/test_paths.py                  new
tests/test_fake_project.py           new
tests/test_controller_settings_dir.py new
tests/test_controller_dispatch.py    new
tests/test_controller_transport.py   new
tests/test_controller_handlers.py    new
tests/test_harness_contract.py       new
tests/test_piano_roll_script.py      new
tests/test_piano_roll_tools.py       new
tests/test_command_roundtrip.py      new
tests/test_docs.py                   new
docs/SMOKE_TEST.md                   new
docs/spikes/2026-09-19-T4-sysex-transport.md  already written
.github/workflows/ci.yml             new
pyproject.toml                       modify. pytest config, dev deps
uv.lock                              new to git. Removed from .gitignore
README.md, install.sh, install.ps1   modify. Em dashes must go, see Task 2 Step 0
```

---

### Task 1: Fix what live FL Studio already broke (3 small commits)

**Files:**
- Modify: `fl_controller/device_FLStudioMCP.py:36-52` (`_get_script_dir`)
- Modify: `fl_controller/device_FLStudioMCP.py:126-241` (`dispatch_command`)
- Modify: `fl_controller/device_FLStudioMCP.py:292-355` (transport handlers)
- Create: `src/fl_studio_mcp/utils/paths.py`
- Modify: `src/fl_studio_mcp/utils/midi_connection.py` (use `paths`)
- Modify: `src/fl_studio_mcp/tools/piano_roll.py` (use `paths`)
- Test: `tests/test_paths.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `fl_studio_mcp.utils.paths.settings_dir() -> Path`
  - `fl_studio_mcp.utils.paths.hardware_dir() -> Path`
  - `fl_studio_mcp.utils.paths.piano_roll_scripts_dir() -> Path`
  - All three create the directory they return, as the current `_get_fl_hardware_dir`
    and `_get_fl_scripts_dir` do, and all three re-read the environment on every
    call so tests can redirect them per test.
  - Environment variable `FL_STUDIO_MCP_SETTINGS_DIR` overrides the FL Settings
    directory in both the server and the FL-side scripts.

This task lands first because the harness needs a redirectable path, and because
these are real defects that a live FL Studio exposed. Each step is its own commit.

- [ ] **Step 1: Write the failing test for the settings directory override**

```python
# tests/test_paths.py
"""Settings directory resolution.

The override exists so tests, and users with a redirected Documents folder, can
point the server somewhere other than the hardcoded default. FL Studio's own
scripts must agree with this resolver or the two sides write to different files.
"""

from __future__ import annotations

from pathlib import Path

from fl_studio_mcp.utils import paths


def test_env_override_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("FL_STUDIO_MCP_SETTINGS_DIR", str(tmp_path / "settings"))
    assert paths.settings_dir() == tmp_path / "settings"


def test_hardware_dir_is_under_settings(monkeypatch, tmp_path):
    monkeypatch.setenv("FL_STUDIO_MCP_SETTINGS_DIR", str(tmp_path / "settings"))
    assert paths.hardware_dir() == tmp_path / "settings" / "Hardware" / "FLStudioMCP"


def test_piano_roll_scripts_dir_is_under_settings(monkeypatch, tmp_path):
    monkeypatch.setenv("FL_STUDIO_MCP_SETTINGS_DIR", str(tmp_path / "settings"))
    assert paths.piano_roll_scripts_dir() == tmp_path / "settings" / "Piano roll scripts"


def test_directories_are_created(monkeypatch, tmp_path):
    monkeypatch.setenv("FL_STUDIO_MCP_SETTINGS_DIR", str(tmp_path / "settings"))
    assert paths.hardware_dir().is_dir()
    assert paths.piano_roll_scripts_dir().is_dir()


def test_override_is_read_per_call_not_cached(monkeypatch, tmp_path):
    monkeypatch.setenv("FL_STUDIO_MCP_SETTINGS_DIR", str(tmp_path / "a"))
    assert paths.settings_dir() == tmp_path / "a"
    monkeypatch.setenv("FL_STUDIO_MCP_SETTINGS_DIR", str(tmp_path / "b"))
    assert paths.settings_dir() == tmp_path / "b"


def test_default_is_the_fl_studio_settings_folder(monkeypatch):
    monkeypatch.delenv("FL_STUDIO_MCP_SETTINGS_DIR", raising=False)
    expected = Path.home() / "Documents" / "Image-Line" / "FL Studio" / "Settings"
    if (Path.home() / "OneDrive").exists():
        onedrive = Path.home() / "OneDrive" / "Documents" / "Image-Line" / "FL Studio" / "Settings"
        assert paths.settings_dir() in (expected, onedrive)
    else:
        assert paths.settings_dir() == expected
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest tests/test_paths.py -v`
Expected: `ModuleNotFoundError: No module named 'fl_studio_mcp.utils.paths'`.

- [ ] **Step 3: Write the resolver**

```python
# src/fl_studio_mcp/utils/paths.py
"""Where FL Studio keeps its settings on this machine.

Three things need to agree on this path: the server (which writes the command and
request files), the controller script (which reads them inside FL Studio), and the
piano roll script (inside a separate sandbox). Two of those live in FL's embedded
Python, which cannot import from this package, so the same resolution logic exists
in three places by necessity. `tests/test_paths.py` pins this copy and
`tests/test_controller_import.py` pins the copies inside FL.
"""

from __future__ import annotations

import os
from pathlib import Path

SETTINGS_DIR_ENV = "FL_STUDIO_MCP_SETTINGS_DIR"


def settings_dir() -> Path:
    """Return FL Studio's Settings directory, creating it if needed.

    FL_STUDIO_MCP_SETTINGS_DIR wins when set, which is what tests use and what a
    user with a relocated Documents folder needs.
    """
    override = os.environ.get(SETTINGS_DIR_ENV)
    if override:
        return Path(override).expanduser()

    home = Path.home()
    candidates = [home / "Documents" / "Image-Line" / "FL Studio" / "Settings"]
    # Windows machines with a Microsoft account often keep Documents inside
    # OneDrive, where the Image-Line folder follows it.
    candidates.append(
        home / "OneDrive" / "Documents" / "Image-Line" / "FL Studio" / "Settings"
    )
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return candidates[0]


def hardware_dir() -> Path:
    """The controller script's data directory. Created if missing."""
    path = settings_dir() / "Hardware" / "FLStudioMCP"
    path.mkdir(parents=True, exist_ok=True)
    return path


def piano_roll_scripts_dir() -> Path:
    """The piano roll script directory. Created if missing."""
    path = settings_dir() / "Piano roll scripts"
    path.mkdir(parents=True, exist_ok=True)
    return path
```

- [ ] **Step 4: Run the tests and watch them pass**

Run: `uv run pytest tests/test_paths.py -v`
Expected: 6 passed.

- [ ] **Step 5: Point the server at the resolver and delete the duplicates**

In `src/fl_studio_mcp/utils/midi_connection.py`, delete `_get_fl_hardware_dir` and
replace its use in `__init__`:

```python
from fl_studio_mcp.utils.paths import hardware_dir
...
        self._hardware_dir = hardware_dir()
        self._command_file = self._hardware_dir / "mcp_command.json"
        self._response_file = self._hardware_dir / "mcp_response.json"
```

In `src/fl_studio_mcp/tools/piano_roll.py`, delete `_get_fl_scripts_dir` and its
three callers' local logic:

```python
from fl_studio_mcp.utils.paths import piano_roll_scripts_dir
...
def _get_request_file() -> Path:
    """Get the path to the MCP request JSON file."""
    return piano_roll_scripts_dir() / "mcp_request.json"


def _get_response_file() -> Path:
    """Get the path to the MCP response JSON file."""
    return piano_roll_scripts_dir() / "mcp_response.json"


def _get_state_file() -> Path:
    """Get the path to the piano roll state JSON file."""
    return piano_roll_scripts_dir() / "piano_roll_state.json"
```

Remove the now-unused `platform` import from `piano_roll.py` if nothing else uses
it, and run `uv run ruff check .`.

- [ ] **Step 6: Run the full suite and lint**

Run: `uv run pytest && uv run ruff check .`
Expected: all pass, lint clean.

- [ ] **Step 7: Commit**

```bash
git add src/fl_studio_mcp/utils/paths.py src/fl_studio_mcp/utils/midi_connection.py \
        src/fl_studio_mcp/tools/piano_roll.py tests/test_paths.py
git commit -m "Resolve the FL Studio settings directory in one place"
```

- [ ] **Step 8: Write the failing test for the override inside the controller script**

```python
# tests/test_controller_settings_dir.py
"""The controller script must honour the same settings override as the server.

FL's embedded Python cannot import the server package, so the controller carries
its own copy of the resolution logic. If the two ever disagree, the server writes
a command file the controller never reads, and the only symptom is a timeout.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONTROLLER = REPO_ROOT / "fl_controller" / "device_FLStudioMCP.py"


def _load_controller_without_fl_modules(monkeypatch, settings: Path):
    """Import the controller with stub FL modules.

    The controller imports channels, device, general, mixer, plugins, transport
    and ui at module scope. Task 3 supplies the real fakes; here only the
    settings path is under test, so empty modules are enough.
    """
    import sys
    import types

    for name in ("channels", "device", "general", "mixer", "plugins", "transport", "ui"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    monkeypatch.setenv("FL_STUDIO_MCP_SETTINGS_DIR", str(settings))
    spec = importlib.util.spec_from_file_location("controller_under_test", CONTROLLER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_controller_honours_the_settings_override(monkeypatch, tmp_path):
    settings = tmp_path / "settings"
    module = _load_controller_without_fl_modules(monkeypatch, settings)
    assert module.COMMAND_FILE == settings / "Hardware" / "FLStudioMCP" / "mcp_command.json"
    assert module.RESPONSE_FILE == settings / "Hardware" / "FLStudioMCP" / "mcp_response.json"


def test_controller_matches_the_server_resolver(monkeypatch, tmp_path):
    from fl_studio_mcp.utils.paths import hardware_dir

    settings = tmp_path / "settings"
    monkeypatch.setenv("FL_STUDIO_MCP_SETTINGS_DIR", str(settings))
    module = _load_controller_without_fl_modules(monkeypatch, settings)
    assert module.COMMAND_FILE.parent == hardware_dir()
```

- [ ] **Step 9: Run it and watch it fail**

Run: `uv run pytest tests/test_controller_settings_dir.py -v`
Expected: FAIL. `module.COMMAND_FILE` is under the real `~/Documents`, because the
controller hardcodes it.

- [ ] **Step 10: Add the override to the controller script**

Replace `_get_script_dir` and the two path constants in
`fl_controller/device_FLStudioMCP.py`:

```python
SETTINGS_DIR_ENV = "FL_STUDIO_MCP_SETTINGS_DIR"


def _get_settings_dir() -> Path:
    """Get the FL Studio Settings directory.

    FL Studio's Python environment doesn't support __file__, so the path is
    constructed from the platform's standard location. FL_STUDIO_MCP_SETTINGS_DIR
    overrides it, which the test harness uses to keep every file inside a
    temporary directory.

    This duplicates fl_studio_mcp.utils.paths on purpose: the controller runs
    inside FL and cannot import the server package.
    """
    override = os.environ.get(SETTINGS_DIR_ENV)
    if override:
        return Path(override).expanduser()

    home = Path.home()
    if sys.platform == "win32":
        candidates = [
            home / "Documents" / "Image-Line" / "FL Studio" / "Settings",
            home / "OneDrive" / "Documents" / "Image-Line" / "FL Studio" / "Settings",
        ]
    else:
        candidates = [home / "Documents" / "Image-Line" / "FL Studio" / "Settings"]

    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return candidates[0]


# File paths for JSON communication
SCRIPT_DIR = _get_settings_dir() / "Hardware" / "FLStudioMCP"
SCRIPT_DIR.mkdir(parents=True, exist_ok=True)
COMMAND_FILE = SCRIPT_DIR / "mcp_command.json"
RESPONSE_FILE = SCRIPT_DIR / "mcp_response.json"
```

- [ ] **Step 11: Run the tests and watch them pass**

Run: `uv run pytest tests/test_controller_settings_dir.py -v`
Expected: 2 passed.

- [ ] **Step 12: Feature-detect safeToEdit, then report honestly that it is missing**

`general.safeToEdit` needs API 29 and the current script calls it without a guard,
which turns a missing function into an exception that the generic handler reports
as `Error executing command: ...`. Test first:

```python
# tests/test_controller_dispatch.py  (create this file here; Task 4 extends it)
"""Dispatch must report failure as failure, and must not call what is not there."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONTROLLER = REPO_ROOT / "fl_controller" / "device_FLStudioMCP.py"


def load_controller(monkeypatch, fl_modules: dict) -> types.ModuleType:
    """Load the real controller script against the given fake FL modules."""
    for name, module in fl_modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    spec = importlib.util.spec_from_file_location("controller_under_test", CONTROLLER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _module_with(**attrs) -> types.ModuleType:
    module = types.ModuleType("fake")
    for key, value in attrs.items():
        setattr(module, key, value)
    return module


def test_unknown_action_reports_failure(monkeypatch, tmp_path):
    monkeypatch.setenv("FL_STUDIO_MCP_SETTINGS_DIR", str(tmp_path))
    modules = {
        name: types.ModuleType(name)
        for name in ("channels", "device", "general", "mixer", "plugins", "transport", "ui")
    }
    controller = load_controller(monkeypatch, modules)
    result = controller.dispatch_command("bogus.doesNotExist", {})
    assert "error" in result


def test_system_get_info_survives_a_missing_safe_to_edit(monkeypatch, tmp_path):
    """An older FL without API 29 must not make the whole info action fail."""
    monkeypatch.setenv("FL_STUDIO_MCP_SETTINGS_DIR", str(tmp_path))
    general = _module_with(getVersion=lambda: 21)  # no safeToEdit at all
    modules = {
        "channels": types.ModuleType("channels"),
        "device": types.ModuleType("device"),
        "general": general,
        "mixer": _module_with(getCurrentTempo=lambda: 130000),
        "plugins": types.ModuleType("plugins"),
        "transport": types.ModuleType("transport"),
        "ui": _module_with(getVersion=lambda: "old", getProgTitle=lambda: "FL Studio 21"),
    }
    controller = load_controller(monkeypatch, modules)
    info = controller.handle_system_get_info()
    assert info["api_version"] == 21
    assert info["capabilities"]["safeToEdit"] is None
```

- [ ] **Step 13: Run and watch the second test fail**

Run: `uv run pytest tests/test_controller_dispatch.py -v`
Expected: `test_unknown_action_reports_failure` passes. The safeToEdit test fails
with `AttributeError: module 'fake' has no attribute 'safeToEdit'`, which is the
bug: `handle_system_get_info` catches it, but `dispatch_command` does not, so a
genuine API gap is indistinguishable from a transport failure.

- [ ] **Step 14: Make dispatch report failure, and gate the risky calls**

In `fl_controller/device_FLStudioMCP.py`, replace the tail of `execute_pending_command`
and `dispatch_command`:

```python
def execute_pending_command():
    """Read command from JSON file, execute it, and write response."""
    response = {"success": False, "error": None}

    try:
        if not COMMAND_FILE.exists():
            response["error"] = "No command file found"
            write_response(response)
            return

        command_text = COMMAND_FILE.read_text()
        command = json.loads(command_text)

        action = command.get("action", "")
        params = command.get("params", {})
        request_id = command.get("id")

        result = dispatch_command(action, params)

        if "error" in result:
            response = {"success": False, "id": request_id, **result}
        else:
            response = {"success": True, "id": request_id, **result}

    except json.JSONDecodeError as e:
        response["error"] = f"Invalid JSON in command file: {e}"
    except Exception as e:
        response["error"] = f"Error executing command: {e}"

    write_response(response)
```

and add at the top of the System handlers section:

```python
def _safe_to_edit() -> bool | None:
    """Whether FL is in a state where the project may be mutated.

    general.safeToEdit was added in API 29. On anything older the function does
    not exist, and the honest answer is "unknown", not "no" and not an exception.
    """
    try:
        return bool(general.safeToEdit())
    except Exception:
        return None
```

`write_response` becomes atomic, because the poller on the other side reads the
file the instant it appears:

```python
def write_response(response: dict):
    """Write response to JSON file, atomically.

    The server polls for this file and reads it as soon as it exists, so a plain
    write can be observed half-finished and fail to parse. Writing beside the
    target and then os.replace makes the swap atomic on both platforms.
    """
    try:
        temporary = RESPONSE_FILE.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(response, indent=2))
        os.replace(temporary, RESPONSE_FILE)
    except Exception as e:
        print(f"Error writing response: {e}")
```

- [ ] **Step 15: Run the tests and watch them pass**

Run: `uv run pytest tests/test_controller_dispatch.py -v`
Expected: both pass.

- [ ] **Step 16: Commit**

```bash
git add fl_controller/device_FLStudioMCP.py tests/test_controller_settings_dir.py \
        tests/test_controller_dispatch.py
git commit -m "Let the controller script honour the settings override and report failures"
```

- [ ] **Step 17: Write the failing tests for the two live-FL defects**

`transport.setLoopMode` takes no arguments and toggles, but
`handle_transport_set_loop_mode` calls `transport.setLoopMode()` whenever the
current mode differs from the requested one. That is correct only for two modes.
`setSongPos(position, mode)` defaults mode to `-1`; the handler's default of `2`
means seconds, which is not what a caller passing no mode expects.

```python
# tests/test_controller_transport.py
"""Transport handlers must match the API's actual signatures.

setLoopMode takes no argument and toggles, and setSongPos defaults its mode to
-1 ("hint" units, the same units getSongPosHint returns). Both were being called
with made-up arguments, which is silent on the FL side.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONTROLLER = REPO_ROOT / "fl_controller" / "device_FLStudioMCP.py"


class FakeTransport:
    """Records calls, so the test can assert on the arguments the handler used."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self._loop_mode = 0

    def setLoopMode(self):
        self.calls.append(("setLoopMode",))
        self._loop_mode = 1 - self._loop_mode

    def getLoopMode(self):
        return self._loop_mode

    def setSongPos(self, position, mode=-1):
        self.calls.append(("setSongPos", position, mode))

    def getSongPosHint(self):
        return "1:01:00"


def load_controller(monkeypatch, tmp_path, transport) -> types.ModuleType:
    monkeypatch.setenv("FL_STUDIO_MCP_SETTINGS_DIR", str(tmp_path))
    modules = {
        name: types.ModuleType(name)
        for name in ("channels", "device", "general", "mixer", "plugins", "ui")
    }
    modules["transport"] = transport
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    spec = importlib.util.spec_from_file_location("controller_under_test", CONTROLLER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_set_loop_mode_calls_the_toggle_exactly_once(monkeypatch, tmp_path):
    transport = FakeTransport()
    controller = load_controller(monkeypatch, tmp_path, transport)
    controller.handle_transport_set_loop_mode({"mode": "song"})
    assert transport.calls == [("setLoopMode",)]


def test_set_position_defaults_to_hint_units(monkeypatch, tmp_path):
    transport = FakeTransport()
    controller = load_controller(monkeypatch, tmp_path, transport)
    controller.handle_transport_set_position({"position": 0})
    assert transport.calls == [("setSongPos", 0, -1)]
```

- [ ] **Step 18: Run and watch them fail**

Run: `uv run pytest tests/test_controller_transport.py -v`
Expected: `test_set_position_defaults_to_hint_units` fails with
`('setSongPos', 0, 2)`. The loop mode test passes; keep it as a regression guard
rather than deleting it, since the toggle semantics are easy to break.

- [ ] **Step 19: Fix the two handlers**

```python
def handle_transport_set_position(params: dict) -> dict:
    """Set playback position.

    mode -1 means the same units getSongPosHint returns, which is what a caller
    passing a bare position almost always wants. Modes 0 to 5 are ticks,
    milliseconds, seconds, and so on, per transport.setSongPos.
    """
    position = params.get("position", 0)
    mode = params.get("mode", -1)
    transport.setSongPos(position, mode)
    return {"position": transport.getSongPosHint()}


def handle_transport_set_loop_mode(params: dict) -> dict:
    """Set loop mode.

    transport.setLoopMode() takes no arguments and toggles between the two
    modes, so this has to compare and toggle rather than pass a value through.
    """
    mode = str(params.get("mode", "pattern")).lower()
    target = 1 if mode == "song" else 0
    if transport.getLoopMode() != target:
        transport.setLoopMode()
    return {"mode": "song" if transport.getLoopMode() == 1 else "pattern"}
```

- [ ] **Step 20: Run the tests, lint, and commit**

Run: `uv run pytest tests/test_controller_transport.py -v && uv run ruff check .`

```bash
git add fl_controller/device_FLStudioMCP.py tests/test_controller_transport.py
git commit -m "Call setSongPos and setLoopMode with the arguments the API takes"
```

- [ ] **Step 21: Copy the controller into FL and re-verify against live FL Studio**

This is the one step in Phase 0 that needs a human and a running FL Studio. It is
also the step that catches everything the fakes cannot model.

```bash
cp fl_controller/device_FLStudioMCP.py \
   ~/Documents/Image-Line/FL\ Studio/Settings/Hardware/FLStudioMCP/device_FLStudioMCP.py
uv run python scripts/dev_verify_connection.py
```

Expected: round trip OK, API version 45, tempo 130000, median latency near 1ms,
and the unknown-action bug section now reporting that the error is *not* implied
to be a success, because fixing the merge is Task 4.

---

### Task 2: The in-memory project model

**Files:**
- Create: `tests/fakes/__init__.py`
- Create: `tests/fakes/project.py`
- Create: `tests/fakes/modules/__init__.py`
- Create: `tests/fakes/modules/channels.py`, `mixer.py`, `transport.py`,
  `general.py`, `plugins.py`, `patterns.py`, `playlist.py`, `arrangement.py`,
  `ui.py`, `device.py`, `midi.py`, `flpianoroll.py`
- Test: `tests/test_fake_project.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `tests.fakes.project.Channel`, `.MixerTrack`, `.Pattern`, `.Note`
  - `tests.fakes.project.FakeProject`, with fields `channels: list[Channel]`,
    `tracks: list[MixerTrack]`, `patterns: list[Pattern]`, `notes: list[Note]`,
    `tempo: int` (thousandths of a BPM), `ppq: int`, `is_playing: bool`,
    `is_recording: bool`, `song_pos_hint: str`, `loop_mode: int`,
    `selected_channel: int | None`, `api_version: int`, `safe_to_edit: bool`
  - `FakeProject.with_channels(n)` and `FakeProject.with_tracks(n)` classmethods,
    so a test states its own fixture instead of inheriting a mystery default
  - `tests.fakes.build_fake_modules(project) -> dict[str, ModuleType]`
  - `tests.fakes.install(project) -> dict[str, ModuleType]` and
    `tests.fakes.uninstall()`

- [ ] **Step 0: Remove the em dashes that are already in shipped files**

The harness contract test in Task 3 enforces the no-dash rule over the whole
repo. A scan today finds three files that predate the rule:

```
install.sh: 1 em dash
README.md: 8 em dashes
install.ps1: 1 em dash
```

Rewrite each one with a comma, a colon, a full stop, or parentheses. Do not
touch `ROADMAP.md` or `CLAUDE.md`: they are already clean.

```bash
uv run --quiet python - <<'PY'
from pathlib import Path
for name in ("README.md", "install.sh", "install.ps1"):
    text = Path(name).read_text()
    for ch, label in (("\u2014", "em"), ("\u2013", "en")):
        if ch in text:
            print(f"{name}: contains {text.count(ch)} {label} dash(es), fix by hand")
PY
```

Then commit on its own, so the style sweep is not tangled with the harness:

```bash
git add README.md install.sh install.ps1
git commit -m "Replace em dashes with punctuation"
```

- [ ] **Step 1: Write the failing tests for the data model**

```python
# tests/test_fake_project.py
"""The fake project is the substrate every later phase asserts against.

Its job is to be a faithful, boring model of FL's documented surface: correct
signatures, documented value ranges, and honest errors for indices that do not
exist. It is not a DAW.
"""

from __future__ import annotations

import pytest

from tests.fakes.project import FakeProject


def test_channels_carry_the_properties_the_api_exposes():
    project = FakeProject.with_channels(3)
    assert [c.name for c in project.channels] == ["Channel 1", "Channel 2", "Channel 3"]
    assert project.channels[0].volume == pytest.approx(0.8)  # FL's documented default
    assert project.channels[0].pan == pytest.approx(0.0)
    assert project.channels[0].pitch == 0
    assert project.channels[0].target_fx_track == 0


def test_step_grid_is_per_channel():
    project = FakeProject.with_channels(2)
    project.channels[0].grid[0] = True
    assert project.channels[0].grid[0] is True
    assert project.channels[1].grid[0] is False


def test_mixer_has_a_master_track_at_index_zero():
    project = FakeProject.with_tracks(4)
    assert project.tracks[0].name == "Master"
    assert len(project.tracks) == 4


def test_tempo_is_stored_in_thousandths():
    assert FakeProject().tempo == 130000  # 130 BPM, as observed on live FL Studio


def test_unknown_channel_index_raises():
    project = FakeProject.with_channels(1)
    with pytest.raises(IndexError):
        project.channel(5)


def test_index_zero_is_the_first_channel_not_a_default():
    """The upstream bug was reading index 0 when the caller omitted the index.

    The fake cannot reproduce that bug, but it must make the bug impossible to
    hide: index 0 has to be a perfectly ordinary channel, so a handler that
    defaults to it edits the wrong thing loudly rather than the right thing by
    luck.
    """
    project = FakeProject.with_channels(3)
    assert project.channel(0).name == "Channel 1"
    assert project.channel(2).name == "Channel 3"
```

- [ ] **Step 2: Run and watch them fail**

Run: `uv run pytest tests/test_fake_project.py -v`
Expected: `ModuleNotFoundError: No module named 'tests.fakes'`.

- [ ] **Step 3: Write the project model**

```python
# tests/fakes/project.py
"""An in-memory stand-in for the FL Studio project.

Values and defaults come from the official stubs, not from guesswork. Where a
stub documents a range, the accessors here clamp to it, so a handler that passes
1.5 for a volume fails in tests rather than silently working on FL (which clamps
for you) and hiding the bug.
"""

from __future__ import annotations

from dataclasses import dataclass, field


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


@dataclass
class Channel:
    """A Channel Rack channel.

    `grid` is the step sequencer's on/off lane, which is what channels.getGridBit
    and setGridBit read and write. Per-step velocity and pan live in the graph
    editor and are research spike T2, so they are deliberately absent: calling
    them must fail until the spike lands.
    """

    name: str
    color: int = 0x808080
    volume: float = 0.8
    pan: float = 0.0
    pitch: int = 0
    muted: bool = False
    solo: bool = False
    selected: bool = False
    target_fx_track: int = 0
    grid: list[bool] = field(default_factory=lambda: [False] * 16)


@dataclass
class MixerTrack:
    """A mixer insert. Index 0 is the Master, as it is in FL."""

    name: str
    color: int = 0x808080
    volume: float = 0.8
    pan: float = 0.0
    stereo_sep: float = 0.0
    muted: bool = False
    solo: bool = False
    armed: bool = False
    routes: dict[int, float] = field(default_factory=dict)
    eq_gains: list[float] = field(default_factory=lambda: [0.0] * 7)
    eq_freqs: list[float] = field(default_factory=lambda: [0.5] * 7)
    eq_bandwidths: list[float] = field(default_factory=lambda: [0.5] * 7)


@dataclass
class Pattern:
    name: str
    color: int = 0x808080
    length: int = 16  # steps


@dataclass
class Note:
    """A piano roll note.

    All sixteen flpianoroll.Note properties are present, because the fake is the
    only place Phase 4's expression work can be tested. `number` is the MIDI note
    number and `time` and `length` are in ticks, matching the API.
    """

    number: int
    time: int = 0
    length: int = 0
    velocity: float = 0.8
    pan: float = 0.0
    color: int = 0
    fcut: float = 0.0
    fres: float = 0.0
    group: int = 0
    muted: bool = False
    pitchofs: float = 0.0
    porta: bool = False
    release: bool = False
    repeats: int = 0
    selected: bool = False
    slide: bool = False


class FakeProject:
    """The whole fake project, one instance per test."""

    def __init__(self, *, channels: list[Channel] | None = None,
                 tracks: list[MixerTrack] | None = None,
                 patterns: list[Pattern] | None = None) -> None:
        self.channels = channels if channels is not None else []
        self.tracks = tracks if tracks is not None else [MixerTrack("Master")]
        self.patterns = patterns if patterns is not None else [Pattern("Pattern 1")]
        self.notes: list[Note] = []

        # Thousandths of a BPM. Live FL Studio returned 130000 at 130 BPM.
        self.tempo = 130000
        # From live FL: general.getRecPPQ. Pulses per quarter note.
        self.ppq = 96
        self.is_playing = False
        self.is_recording = False
        self.song_pos_hint = "1:01:00"
        self.loop_mode = 0  # 0 is pattern mode, 1 is song mode
        self.selected_channel: int | None = None
        self.api_version = 45  # observed on FL Studio 2026, build 5406
        self.safe_to_edit = True
        self.undo_stack: list[str] = []
        self.current_pattern = 0

    @classmethod
    def with_channels(cls, count: int) -> FakeProject:
        return cls(channels=[Channel(f"Channel {i + 1}") for i in range(count)])

    @classmethod
    def with_tracks(cls, count: int) -> FakeProject:
        tracks = [MixerTrack("Master")]
        tracks += [MixerTrack(f"Insert {i}") for i in range(1, count)]
        return cls(tracks=tracks)

    def channel(self, index: int) -> Channel:
        if not 0 <= index < len(self.channels):
            raise IndexError(f"channel index {index} out of range")
        return self.channels[index]

    def track(self, index: int) -> MixerTrack:
        if not 0 <= index < len(self.tracks):
            raise IndexError(f"mixer track index {index} out of range")
        return self.tracks[index]

    def pattern(self, index: int) -> Pattern:
        if not 0 <= index < len(self.patterns):
            raise IndexError(f"pattern index {index} out of range")
        return self.patterns[index]
```

- [ ] **Step 4: Run the tests and watch them pass**

Run: `uv run pytest tests/test_fake_project.py -v`
Expected: 6 passed.

- [ ] **Step 5: Write the fake module builder, one file per module**

Every fake function mirrors its stub signature exactly. The complete inventory,
taken from the stubs, is:

| Module | Functions the fakes define |
| --- | --- |
| `channels` | `channelCount(globalCount=False)`, `channelNumber(canBeNone=False, offset=0)`, `selectedChannel(canBeNone=False, indexGlobal=False)`, `selectChannel(index, value, useGlobalIndex=False)`, `selectOneChannel(index, useGlobalIndex=False)`, `deselectAll()`, `isChannelSelected`, `getChannelName`, `setChannelName`, `getChannelColor`, `setChannelColor`, `getChannelVolume`, `setChannelVolume`, `getChannelPan`, `setChannelPan`, `getChannelPitch(index, mode=0, useGlobalIndex=False)`, `setChannelPitch(index, value, mode=0, pickupMode=<PIM_None>, useGlobalIndex=False)`, `getChannelType`, `isChannelMuted`, `muteChannel`, `isChannelSolo`, `soloChannel`, `getTargetFxTrack`, `setTargetFxTrack`, `getGridBit`, `setGridBit`, `getGridBitWithLoop`, `isGridBitAssigned`, `getActivityLevel`, `midiNoteOn(indexGlobal, note, velocity, channel=-1)`, `quickQuantize` |
| `mixer` | `trackCount()`, `trackNumber()`, `getTrackName`, `setTrackName`, `getTrackColor`, `setTrackColor`, `getTrackVolume(index, mode=0)`, `setTrackVolume`, `getTrackPan`, `setTrackPan`, `getTrackStereoSep`, `setTrackStereoSep`, `isTrackMuted`, `muteTrack`, `isTrackSolo`, `soloTrack`, `isTrackArmed`, `armTrack`, `getCurrentTempo`, `getTrackPeaks(index, mode)`, `getLastPeakVol(section)`, `getEqBandCount()`, `getEqGain`, `setEqGain`, `getEqFrequency`, `setEqFrequency`, `getEqBandwidth`, `setEqBandwidth`, `setRouteTo`, `getRouteSendActive`, `setRouteToLevel`, `getRouteToLevel`, `linkChannelToTrack`, `linkTrackToChannel`, `getSongStepPos`, `getRecPPS` |
| `transport` | `start()`, `stop()`, `record()`, `isPlaying()`, `isRecording()`, `getLoopMode()`, `setLoopMode()`, `getSongPosHint()`, `getSongPos(mode=-1)`, `setSongPos(position, mode=-1)`, `getSongLength(mode)`, `setPlaybackSpeed(multiplier)` |
| `general` | `getVersion()`, `safeToEdit()`, `getRecPPQ()`, `getRecPPB()`, `saveUndo(name, flags, update=True)`, `undo()`, `restoreUndo()`, `restoreUndoLevel(level)`, `getUndoHistoryCount()`, `getUndoHistoryPos()`, `getUndoLevelHint()`, `getChangedFlag()`, `getUseMetronome()` |
| `plugins` | `isValid`, `getPluginName`, `getParamCount`, `getParamName`, `getParamValue`, `getParamValueString`, `setParamValue`, `getPresetCount`, `nextPreset`, `prevPreset`, `getColor`, `getNumParams` |
| `patterns` | `patternCount()`, `patternNumber()`, `patternMax()`, `selectPattern(index, ..., force=False)`, `jumpToPattern(index)`, `clonePattern(index=None)`, `findFirstNextEmptyPat(flags, x=-1, y=-1)`, `setPatternName`, `getPatternName`, `setPatternColor`, `getPatternColor`, `getPatternLength`, `isPatternDefault`, `isPatternSelected`, `deselectAll()` |
| `playlist` | `trackCount()`, `getTrackName`, `setTrackName`, `getTrackColor`, `setTrackColor`, `muteTrack`, `soloTrack`, `isTrackMuted`, `isTrackSolo`, `getLiveBlockTrackId`, `triggerLiveClip`, `getPerformanceModeState` |
| `arrangement` | `currentTime(snap)`, `currentTimeHint(mode, ...)`, `selectionStart()`, `selectionEnd()`, `addAutoTimeMarker(time, name)`, `getMarkerName(index)`, `jumpToMarker(delta, select)`, `liveSelection(time, stop)`, `liveSelectionStart()` |
| `ui` | `getVersion(mode=4)`, `getProgTitle()`, `showWindow(index)`, `hideWindow(index)`, `getVisible(index)`, `getFocused(index)`, `setFocused(index)`, `getFocusedFormCaption()`, `getFocusedNodeCaption()`, `getSnapMode()`, `setSnapMode(value)`, `showNotification(id)`, `navigateBrowser(direction, shiftHeld)`, `previewBrowserMenuItem()`, `selectBrowserMenuItem()`, `getHintMsg()`, `setHintMsg(msg)`, `isMetronomeEnabled()` |
| `device` | `isAssigned()`, `getPortNumber()`, `getName()`, `midiOutMsg(...)`, `midiOutSysex(message)`, `getMasterSync()`, `setMasterSync(value)`, `getDeviceID()` |
| `midi` | `EncodeRemoteControlID(PortNum, ChanNum, CCNum)`, `pitch_bend_event_to_float(event)`, plus the constants `REC_Tempo`, `REC_UpdateValue`, `REC_UpdateControl`, `GT_All`, `widPianoRoll`, `ST_Int`, `PIM_None` |
| `flpianoroll` | `Note` with all sixteen properties, `score` with `PPQ`, `noteCount`, `getNote`, `addNote`, `deleteNote`, and the read-only key and meter attributes `snap_root_note`, `snap_scale_helper`, `tsnum`, `tsden`, `getTimelineSelection()` |

Each module file follows exactly this shape (shown for `channels`; the rest are
the same pattern with the inventory above):

```python
# tests/fakes/modules/channels.py
"""Fake channels module. Signatures mirror the official stubs exactly.

Where a stub documents a range, the setter clamps to it. Where a stub documents a
return type, the getter returns that type. Nothing here is more capable than the
real API: no function exists that the stubs do not define.
"""

from __future__ import annotations

from types import ModuleType

from tests.fakes.project import FakeProject, clamp


def build(project: FakeProject) -> ModuleType:
    """Build the fake channels module bound to one project."""
    module = ModuleType("channels")

    def channelCount(globalCount: bool = False) -> int:
        return len(project.channels)

    def channelNumber(canBeNone: bool = False, offset: int = 0) -> int:
        return project.selected_channel if project.selected_channel is not None else -1

    def selectedChannel(canBeNone: bool = False, indexGlobal: bool = False):
        return project.selected_channel

    def selectOneChannel(index: int, useGlobalIndex: bool = False) -> None:
        project.channel(index)  # raises IndexError on a bad index
        project.selected_channel = index
        for i, channel in enumerate(project.channels):
            channel.selected = i == index

    def getGridBit(index: int, position: int, useGlobalIndex: bool = False) -> bool:
        return project.channel(index).grid[position]

    def setGridBit(index: int, position: int, value: bool, useGlobalIndex: bool = False) -> None:
        project.channel(index).grid[position] = bool(value)

    def getChannelVolume(index: int, useGlobalIndex: bool = False) -> float:
        return project.channel(index).volume

    def setChannelVolume(index: int, volume: float, useGlobalIndex: bool = False) -> None:
        project.channel(index).volume = clamp(volume, 0.0, 1.0)

    # ... and so on for the rest of the inventory in the table above

    for name, value in list(locals().items()):
        if callable(value) and not name.startswith("_"):
            setattr(module, name, value)
    return module
```

`tests/fakes/modules/__init__.py`:

```python
"""Assemble one fake module per FL module, all bound to the same project."""

from __future__ import annotations

from types import ModuleType

from tests.fakes.modules import (
    arrangement,
    channels,
    device,
    flpianoroll,
    general,
    midi,
    mixer,
    patterns,
    playlist,
    plugins,
    transport,
    ui,
)
from tests.fakes.project import FakeProject

# Every module the controller script or the piano roll script may import. A
# second module must never be added to the scripts without a fake here, so
# install() asserts the set matches rather than merging quietly.
MODULE_NAMES = (
    "arrangement",
    "channels",
    "device",
    "flpianoroll",
    "general",
    "midi",
    "mixer",
    "patterns",
    "playlist",
    "plugins",
    "transport",
    "ui",
)


def build_fake_modules(project: FakeProject) -> dict[str, ModuleType]:
    builders = {
        "arrangement": arrangement.build,
        "channels": channels.build,
        "device": device.build,
        "flpianoroll": flpianoroll.build,
        "general": general.build,
        "midi": midi.build,
        "mixer": mixer.build,
        "patterns": patterns.build,
        "playlist": playlist.build,
        "plugins": plugins.build,
        "transport": transport.build,
        "ui": ui.build,
    }
    missing = set(MODULE_NAMES) - set(builders)
    if missing:
        raise AssertionError(f"no fake builder for {sorted(missing)}")
    return {name: builder(project) for name, builder in builders.items()}
```

- [ ] **Step 6: Write the installer and the fixture**

```python
# tests/fakes/__init__.py
"""Fake FL Studio modules, injected into sys.modules for one test at a time.

The point of this package is that the *real* controller script and the *real*
piano roll script are exercised, with only FL itself replaced. Nothing here is a
reimplementation of the scripts.
"""

from __future__ import annotations

import sys
from types import ModuleType

from tests.fakes.modules import MODULE_NAMES, build_fake_modules
from tests.fakes.project import FakeProject

_INSTALLED: list[str] = []


def install(project: FakeProject) -> dict[str, ModuleType]:
    """Put the fake FL modules into sys.modules and return them."""
    modules = build_fake_modules(project)
    unexpected = set(modules) - set(MODULE_NAMES)
    assert not unexpected, f"fake module set drifted: {sorted(unexpected)}"
    for name, module in modules.items():
        sys.modules[name] = module
        _INSTALLED.append(name)
    return modules


def uninstall() -> None:
    """Remove every fake module this package installed."""
    while _INSTALLED:
        sys.modules.pop(_INSTALLED.pop(), None)
```

```python
# tests/conftest.py
"""Shared fixtures. The harness is per-test so no state leaks between tests."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from tests import fakes
from tests.fakes.project import FakeProject

REPO_ROOT = Path(__file__).resolve().parent.parent
CONTROLLER_PATH = REPO_ROOT / "fl_controller" / "device_FLStudioMCP.py"
PYSCRIPT_PATH = REPO_ROOT / "scripts" / "ComposeWithLLM.pyscript"


class Harness:
    """Everything a test needs to drive both sides of the transport."""

    def __init__(self, project, modules, settings_dir, controller, pyscript):
        self.project = project
        self.modules = modules
        self.settings_dir = settings_dir
        self.controller = controller
        self.pyscript = pyscript

    @property
    def hardware_dir(self) -> Path:
        return self.settings_dir / "Hardware" / "FLStudioMCP"

    @property
    def piano_roll_dir(self) -> Path:
        return self.settings_dir / "Piano roll scripts"

    @property
    def command_file(self) -> Path:
        return self.hardware_dir / "mcp_command.json"

    @property
    def response_file(self) -> Path:
        return self.hardware_dir / "mcp_response.json"

    def load(self, path: Path, name: str):
        """Load a module from an arbitrary path, replacing any earlier copy.

        The scripts are reloaded per test because their file paths are resolved at
        import time from the environment.
        """
        sys.modules.pop(name, None)
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module


@pytest.fixture
def fl_env(tmp_path, monkeypatch):
    """A fake FL, two real scripts, and a temporary settings tree."""
    settings = tmp_path / "settings"
    monkeypatch.setenv("FL_STUDIO_MCP_SETTINGS_DIR", str(settings))
    project = FakeProject.with_channels(4)
    project.tracks = FakeProject.with_tracks(8).tracks
    modules = fakes.install(project)
    harness = Harness(project, modules, settings, None, None)
    harness.controller = harness.load(CONTROLLER_PATH, "fl_controller_under_test")
    harness.pyscript = harness.load(PYSCRIPT_PATH, "fl_pyscript_under_test")
    try:
        yield harness
    finally:
        fakes.uninstall()
        sys.modules.pop("fl_controller_under_test", None)
        sys.modules.pop("fl_pyscript_under_test", None)
```

- [ ] **Step 7: Run the whole suite**

Run: `uv run pytest -v`
Expected: all pass. The `fl_env` fixture is not used yet, so the harness is
exercised only by the tests added in Task 3.

- [ ] **Step 8: Commit**

```bash
git add tests/fakes tests/conftest.py tests/test_fake_project.py
git commit -m "Add fake FL Studio modules backed by an in-memory project"
```

---

### Task 3: The round trip, and the guarantee that the fakes stay honest

**Files:**
- Create: `tests/fakes/midi.py`
- Test: `tests/test_harness_contract.py`
- Test: `tests/test_controller_handlers.py`
- Test: `tests/test_command_roundtrip.py`

**Interfaces:**
- Consumes: `tests.fakes.FakeProject`, the `fl_env` fixture.
- Produces:
  - `tests.fakes.midi.FakeMidiPort`: an object with `send(message)` and `close()`.
    Constructed with a callable that receives any message sent to it.
  - `tests.fakes.midi.FakeMidiModule`: a stand-in for `mido` exposing
    `Message` (the real one, which needs no port layer), `get_output_names()`,
    `get_input_names()` and `open_output(name, virtual=False)`.
  - `fl_env.midi`: the `FakeMidiModule`, and `fl_env.trigger_count`: how many
    trigger notes the server has sent.

- [ ] **Step 1: Write the failing contract tests**

These are the tests that keep the harness from rotting. If the controller starts
calling an API the fakes do not model, these fail, which is the only thing
standing between a passing suite and a false sense of safety.

```python
# tests/test_harness_contract.py
"""Guarantees about the harness itself.

A fake that is missing a function the scripts call produces a green suite and a
broken FL. These tests derive the required surface from the scripts' own source,
so they cannot drift.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CONTROLLER = REPO_ROOT / "fl_controller" / "device_FLStudioMCP.py"
PYSCRIPT = REPO_ROOT / "scripts" / "ComposeWithLLM.pyscript"

# Modules the controller may use, from ROADMAP.md's sandbox rules.
CONTROLLER_MODULES = (
    "arrangement",
    "channels",
    "device",
    "general",
    "midi",
    "mixer",
    "patterns",
    "playlist",
    "plugins",
    "transport",
    "ui",
)


def _attribute_calls(source: str, module_names) -> set[tuple[str, str]]:
    """Find every `module.function(...)` call in a source file."""
    tree = ast.parse(source)
    found = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id in module_names
        ):
            found.add((func.value.id, func.attr))
    return found


def _defined_functions(module) -> set[str]:
    return {name for name in dir(module) if not name.startswith("_")}


def test_every_fl_call_in_the_controller_exists_in_the_fakes(fl_env):
    calls = _attribute_calls(CONTROLLER.read_text(), CONTROLLER_MODULES)
    assert calls, "found no FL API calls in the controller; the parser is broken"
    missing = [
        f"{mod}.{func}"
        for mod, func in sorted(calls)
        if not hasattr(fl_env.modules[mod], func)
    ]
    assert not missing, f"controller calls FL APIs the fakes do not define: {missing}"


def test_every_fl_call_in_the_pyscript_exists_in_the_fake_flpianoroll(fl_env):
    calls = _attribute_calls(PYSCRIPT.read_text(), ("flp", "flpianoroll"))
    assert calls, "found no flpianoroll calls in the pyscript; the parser is broken"
    fake = fl_env.modules["flpianoroll"]
    missing = []
    for _, func in sorted(calls):
        target = fake
        for part in func.split("."):
            if not hasattr(target, part):
                missing.append(f"flp.{func}")
                break
            target = getattr(target, part)
    assert not missing, f"pyscript calls flpianoroll APIs the fake lacks: {missing}"


def test_the_controller_imports_nothing_outside_the_sandbox():
    """FL's embedded Python has no __file__ and a restricted stdlib."""
    allowed = {
        "json",
        "os",
        "sys",
        "pathlib",
        *CONTROLLER_MODULES,
    }
    tree = ast.parse(CONTROLLER.read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported <= allowed, f"controller imports outside the sandbox: {imported - allowed}"


def test_no_fake_is_more_capable_than_the_real_playlist():
    """playlist has no clip placement function, and the fake must not add one.

    This is the mechanism that keeps "not possible" in ROADMAP.md honest: the
    fake could implement anything, so it deliberately implements only what the
    stubs define.
    """
    from tests.fakes.modules import playlist

    fake = playlist.build(__import__("tests.fakes.project", fromlist=["FakeProject"]).FakeProject())
    for forbidden in ("add", "insert", "create", "addClip", "insertClip", "placeClip"):
        assert not hasattr(fake, forbidden), f"fake playlist gained a {forbidden}() it must not have"


def test_no_em_dash_or_en_dash_in_shipped_text():
    """Style rule from ROADMAP.md, enforced rather than remembered."""
    offenders = []
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file() or ".git" in path.parts or ".venv" in path.parts:
            continue
        if path.suffix not in {".py", ".md", ".pyscript", ".toml", ".yml", ".yaml", ".sh", ".ps1"}:
            continue
        text = path.read_text(errors="ignore")
        if "\u2014" in text or "\u2013" in text:
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert not offenders, f"em dash or en dash found in: {offenders}"
```

- [ ] **Step 2: Run and watch them fail**

Run: `uv run pytest tests/test_harness_contract.py -v`
Expected: FAIL, because `tests/fakes/modules/playlist.py` does not exist yet in
full and several controller calls are not modelled. Fix each failure by adding
the missing fake function, never by relaxing the assertion.

- [ ] **Step 3: Complete the fake modules until the contract tests pass**

Work through the missing list the tests print. Every addition mirrors the stub
signature. When the list is empty:

Run: `uv run pytest tests/test_harness_contract.py -v`
Expected: 5 passed.

- [ ] **Step 4: Write the fake MIDI layer**

```python
# tests/fakes/midi.py
"""A mido stand-in that delivers the trigger note to the in-process controller.

The real transport is: write a command file, send note 127, FL reads the file.
The fake keeps every part of that except the MIDI cable, so the round trip test
covers both scripts and both file formats while staying deterministic.
"""

from __future__ import annotations

from types import ModuleType
from typing import Callable

import mido

TRIGGER_NOTE = 127


class FakeMidiPort:
    """Accepts messages and hands each one to a callback."""

    def __init__(self, name: str, on_send: Callable[[object], None] | None = None) -> None:
        self.name = name
        self._on_send = on_send
        self.sent: list[object] = []
        self.closed = False

    def send(self, message) -> None:
        self.sent.append(message)
        if self._on_send is not None:
            self._on_send(message)

    def close(self) -> None:
        self.closed = True


class FakeMidiModule(ModuleType):
    """Just enough of mido for MIDIConnection.connect() and send_command()."""

    def __init__(self, port: FakeMidiPort) -> None:
        super().__init__("mido")
        self.Message = mido.Message  # real; it needs no port layer
        self._port = port

    def get_output_names(self) -> list[str]:
        return [self._port.name]

    def get_input_names(self) -> list[str]:
        return []

    def open_output(self, name: str | None = None, virtual: bool = False) -> FakeMidiPort:
        return self._port
```

Add to `tests/conftest.py`: the harness creates the fake mido module, wiring
`on_send` so that a trigger note invokes
`harness.controller.execute_pending_command()`, and counts triggers. The
`fl_env` fixture must set it up *after* loading the controller, because the
callback closes over the loaded module:

```python
@pytest.fixture
def fl_env(tmp_path, monkeypatch):
    """A fake FL, two real scripts, a fake MIDI cable, a temporary settings tree."""
    settings = tmp_path / "settings"
    monkeypatch.setenv("FL_STUDIO_MCP_SETTINGS_DIR", str(settings))
    project = FakeProject.with_channels(4)
    project.tracks = FakeProject.with_tracks(8).tracks
    modules = fakes.install(project)
    harness = Harness(project, modules, settings, None, None)
    harness.controller = harness.load(CONTROLLER_PATH, "fl_controller_under_test")
    harness.pyscript = harness.load(PYSCRIPT_PATH, "fl_pyscript_under_test")

    harness.trigger_count = 0

    def on_send(message) -> None:
        if getattr(message, "type", None) == "note_on" and message.note == TRIGGER_NOTE:
            harness.trigger_count += 1
            harness.controller.execute_pending_command()

    harness.midi = FakeMidiModule(FakeMidiPort("FL Studio MCP", on_send))
    monkeypatch.setitem(sys.modules, "mido", harness.midi)
    try:
        yield harness
    finally:
        fakes.uninstall()
        sys.modules.pop("fl_controller_under_test", None)
        sys.modules.pop("fl_pyscript_under_test", None)
```

- [ ] **Step 5: Write the failing handler tests, one per handler group**

```python
# tests/test_controller_handlers.py
"""Handler behaviour, asserted against the in-memory project.

Each test names the specific wrong behaviour it would catch. A test that only
asserts "no exception" is not worth having.
"""

from __future__ import annotations

import pytest


def test_get_all_channels_reports_every_channel(fl_env):
    result = fl_env.controller.handle_channels_get_all()
    assert [c["name"] for c in result["channels"]] == [
        "Channel 1", "Channel 2", "Channel 3", "Channel 4",
    ]


def test_set_channel_volume_writes_through(fl_env):
    fl_env.controller.handle_channels_set_volume({"index": 2, "volume": 0.25})
    assert fl_env.project.channel(2).volume == pytest.approx(0.25)
    assert fl_env.project.channel(0).volume == pytest.approx(0.8)  # untouched


def test_set_channel_volume_is_clamped_by_the_fake(fl_env):
    """FL clamps silently; the fake clamps too, so the test sees the real value."""
    fl_env.controller.handle_channels_set_volume({"index": 1, "volume": 4.0})
    assert fl_env.project.channel(1).volume == pytest.approx(1.0)


def test_mute_without_a_value_toggles(fl_env):
    first = fl_env.controller.handle_channels_mute({"index": 0})
    assert first["is_muted"] is True
    second = fl_env.controller.handle_channels_mute({"index": 0})
    assert second["is_muted"] is False


def test_step_sequence_round_trips(fl_env):
    pattern = [True, False] * 8
    fl_env.controller.handle_channels_set_step_sequence({"channel": 3, "pattern": pattern})
    result = fl_env.controller.handle_channels_get_step_sequence({"channel": 3, "steps": 16})
    assert result["sequence"] == pattern


def test_set_track_color_writes_rrggbb(fl_env):
    """The byte order was wrong upstream; 0xRRGGBB is what the API takes."""
    fl_env.controller.handle_mixer_set_track_color({"track": 2, "r": 0x11, "g": 0x22, "b": 0x33})
    assert fl_env.project.track(2).color == 0x112233


def test_transport_status_reports_position_and_mode(fl_env):
    fl_env.project.is_playing = True
    result = fl_env.controller.handle_transport_get_status()
    assert result["is_playing"] is True
    assert result["loop_mode"] == "pattern"


def test_get_track_info_reports_volume_in_both_units(fl_env):
    fl_env.project.track(1).volume = 0.5
    result = fl_env.controller.handle_mixer_get_track_info({"track": 1})
    assert result["volume"] == pytest.approx(0.5)
    assert result["volume_db"] < 0  # half amplitude is negative dB


def test_out_of_range_channel_index_raises_rather_than_editing_channel_zero(fl_env):
    """The upstream default was index 0, which silently edited the wrong channel."""
    with pytest.raises(IndexError):
        fl_env.controller.handle_channels_set_volume({"index": 99, "volume": 0.5})
```

- [ ] **Step 6: Run and watch them fail**

Run: `uv run pytest tests/test_controller_handlers.py -v`
Expected: failures wherever a handler does not yet match. Add the fake support
each failure needs; do not weaken the assertion.

- [ ] **Step 7: Write the failing round-trip test**

```python
# tests/test_command_roundtrip.py
"""The full path: server writes a command, sends a trigger, reads a response.

This is the test that would have caught the audit's bug 1 had it existed, and the
one Phase 1's correlation work will extend. It runs with no FL Studio installed
and no MIDI hardware.
"""

from __future__ import annotations

import json

import pytest

from fl_studio_mcp.utils.midi_connection import MIDIConnection


@pytest.fixture
def connection(fl_env):
    """A MIDIConnection wired to the in-process fake controller."""
    conn = MIDIConnection()
    conn._command_file = fl_env.command_file
    conn._response_file = fl_env.response_file
    return conn


def test_round_trip_returns_the_controllers_answer(connection, fl_env):
    result = connection.send_command("mixer.getTrackCount", timeout=2.0)
    assert result["success"] is True
    assert result["count"] == 8


def test_exactly_one_trigger_per_command(connection, fl_env):
    connection.send_command("mixer.getTrackCount", timeout=2.0)
    assert fl_env.trigger_count == 1


def test_the_command_file_records_what_was_sent(connection, fl_env):
    connection.send_command("channels.getCount", {"global_count": True}, timeout=2.0)
    written = json.loads(fl_env.command_file.read_text())
    assert written["action"] == "channels.getCount"
    assert written["params"] == {"global_count": True}


def test_a_timeout_reports_failure_not_success(connection, fl_env, monkeypatch):
    """FL not answering must never look like success."""
    monkeypatch.setattr(fl_env.controller, "execute_pending_command", lambda: None)
    result = connection.send_command("mixer.getTrackCount", timeout=0.05)
    assert result["success"] is False
    assert "Timeout" in result["error"]


def test_an_unknown_action_is_not_reported_as_success(connection, fl_env):
    """The reproduced live bug: success True alongside an error string."""
    result = connection.send_command("bogus.doesNotExist", timeout=2.0)
    assert result.get("success") is not True, (
        "an unknown action must not be reported as a success; see the "
        "unknown-action finding in ROADMAP.md"
    )
```

- [ ] **Step 8: Run and watch the last test fail**

Run: `uv run pytest tests/test_command_roundtrip.py -v`
Expected: four pass, `test_an_unknown_action_is_not_reported_as_success` fails with
`success` present and `True`. This is the live bug, reproduced offline.

- [ ] **Step 9: Fix the merge in the server**

In `src/fl_studio_mcp/utils/midi_connection.py`, the response is returned as
written by the controller, and the controller already reports `success: False`
after Task 1's change. Delete any `{"success": True, **result}` style merge
remaining in the server, and add a guard so a malformed response cannot be
mistaken for a good one:

```python
    def _read_response(self, response_file: Path) -> dict[str, Any]:
        """Parse a response file. A response without `success` is a failure.

        The controller always writes `success`, so its absence means the file is
        not one of ours, or is truncated. Treating that as success was the bug
        that made an unknown action look fine.
        """
        try:
            parsed = json.loads(response_file.read_text())
        except json.JSONDecodeError as e:
            return {"success": False, "error": f"Invalid JSON in response: {e}"}
        if not isinstance(parsed, dict):
            return {"success": False, "error": f"Response was {type(parsed).__name__}, not an object"}
        if "success" not in parsed:
            return {"success": False, "error": f"Response had no success field: {parsed}"}
        return parsed
```

- [ ] **Step 10: Run the whole suite and lint**

Run: `uv run pytest -v && uv run ruff check .`
Expected: everything passes, lint clean.

- [ ] **Step 11: Commit**

```bash
git add tests/fakes/midi.py tests/conftest.py tests/test_harness_contract.py \
        tests/test_controller_handlers.py tests/test_command_roundtrip.py \
        src/fl_studio_mcp/utils/midi_connection.py
git commit -m "Cover the full command round trip without FL Studio"
```

---

### Task 4: The piano roll path, verified

**Files:**
- Create: `tests/test_piano_roll_script.py`
- Modify: `scripts/ComposeWithLLM.pyscript`
- Modify: `src/fl_studio_mcp/tools/piano_roll.py`
- Modify: `tests/test_controller_dispatch.py` (the pyscript can now report errors)
- Update: `docs/SMOKE_TEST.md` (Task 5)

**Interfaces:**
- Consumes: `fl_env`, `tests.fakes.midi.FakeMidiPort`.
- Produces:
  - The pyscript writes `mcp_response.json` containing
    `{"success": bool, "id": <request id or null>, "action": <action>, "notes_added": int, "notes_deleted": int, "error": str | null}`.
  - `fl_studio_mcp.tools.piano_roll.send_request(request, timeout=...) -> dict`
    is the single place that writes a request, triggers, and reads the reply.
  - `fl_env.piano_roll_trigger(stub)` is how tests drive the pyscript instead of
    a real keystroke: it calls `harness.pyscript.apply()`.

- [ ] **Step 1: Write the failing tests for the pyscript**

```python
# tests/test_piano_roll_script.py
"""The piano roll script, whose reply the server never used to read.

The script already wrote mcp_response.json. No test existed, so no one noticed
that the server ignored it, that a failed request stayed in the queue to replay
on the next success, or that the reply had no way to say which request it
answered.
"""

from __future__ import annotations

import json

import pytest


def write_request(fl_env, requests) -> None:
    path = fl_env.piano_roll_dir / "mcp_request.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(requests))


def read_response(fl_env) -> dict:
    return json.loads((fl_env.piano_roll_dir / "mcp_response.json").read_text())


def test_add_notes_writes_notes_into_the_score(fl_env):
    write_request(fl_env, [{"action": "add_notes", "notes": [
        {"midi": 60, "time": 0.0, "duration": 1.0, "velocity": 0.8},
        {"midi": 64, "time": 0.0, "duration": 1.0, "velocity": 0.8},
    ]}])
    fl_env.pyscript.apply()
    assert sorted(n.number for n in fl_env.project.notes) == [60, 64]
    assert fl_env.project.notes[0].length == fl_env.project.ppq


def test_the_response_says_which_request_it_answered(fl_env):
    write_request(fl_env, [{"action": "add_notes", "id": "abc-123", "notes": [
        {"midi": 60, "time": 0.0, "duration": 1.0},
    ]}])
    fl_env.pyscript.apply()
    assert read_response(fl_env)["id"] == "abc-123"


def test_a_failed_request_reports_failure(fl_env):
    write_request(fl_env, [{"action": "add_notes", "id": "bad", "notes": [
        {"no_midi_key": True},
    ]}])
    fl_env.pyscript.apply()
    response = read_response(fl_env)
    assert response["success"] is False
    assert response["error"]


def test_a_failed_request_does_not_stay_in_the_queue(fl_env):
    """Leaving it queued replays it on the next trigger and duplicates notes."""
    write_request(fl_env, [{"action": "add_notes", "id": "bad", "notes": [{"x": 1}]}])
    fl_env.pyscript.apply()
    assert json.loads((fl_env.piano_roll_dir / "mcp_request.json").read_text()) == []


def test_clear_removes_every_note(fl_env):
    fl_env.project.notes.extend(fl_env.modules["flpianoroll"].Note() for _ in range(2))
    fl_env.project.notes[0].number = 60
    fl_env.project.notes[1].number = 62
    write_request(fl_env, [{"action": "clear", "id": "c1"}])
    fl_env.pyscript.apply()
    assert fl_env.project.notes == []
    assert read_response(fl_env)["notes_deleted"] == 2


def test_state_export_reports_the_documented_ppq_and_note_count(fl_env):
    fl_env.project.notes.append(fl_env.modules["flpianoroll"].Note())
    fl_env.project.notes[0].number = 60
    fl_env.pyscript.apply()
    state = json.loads((fl_env.piano_roll_dir / "piano_roll_state.json").read_text())
    assert state["ppq"] == fl_env.project.ppq
    assert state["noteCount"] == 1


def test_slide_porta_and_filter_survive_a_round_trip(fl_env):
    """Phase 4 depends on the fake carrying all sixteen Note properties."""
    write_request(fl_env, [{"action": "add_notes", "id": "expr", "notes": [
        {"midi": 36, "time": 0.0, "duration": 0.5, "slide": True, "porta": True,
         "pitchofs": 0.25, "fcut": 0.6, "fres": 0.3},
    ]}])
    fl_env.pyscript.apply()
    state = json.loads((fl_env.piano_roll_dir / "piano_roll_state.json").read_text())
    note = state["notes"][0]
    assert note["slide"] is True
    assert note["porta"] is True
    assert note["pitchofs"] == pytest.approx(0.25)
    assert note["fcut"] == pytest.approx(0.6)
```

- [ ] **Step 2: Run and watch them fail**

Run: `uv run pytest tests/test_piano_roll_script.py -v`
Expected: `test_the_response_says_which_request_it_answered` fails with `KeyError:
'id'`, `test_a_failed_request_reports_failure` fails because `apply()` writes
nothing when `process_mcp_request` returns None, and the expression test fails
because the notes are constructed with only four properties.

- [ ] **Step 3: Rewrite the pyscript's request handling**

Replace `process_mcp_request`, `add_notes_to_piano_roll`,
`add_chord_to_piano_roll`, `delete_notes_from_piano_roll` and `apply` in
`scripts/ComposeWithLLM.pyscript` with a version that: builds one response per
request, carries the request's `id` through, never leaves a processed request in
the queue, and writes the response atomically.

```python
def _script_dir():
    """Get the piano roll scripts directory.

    FL_STUDIO_MCP_SETTINGS_DIR overrides it, the same way the controller script
    honours it, so the test harness can keep every file in a temp directory.
    This sandbox has no __file__ and cannot import the server package.
    """
    override = os.environ.get("FL_STUDIO_MCP_SETTINGS_DIR")
    if override:
        return os.path.join(os.path.expanduser(override), "Piano roll scripts")
    return os.path.expanduser("~/Documents/Image-Line/FL Studio/Settings/Piano roll scripts")


def _note_from(data):
    """Build a flpianoroll.Note from a request dict.

    All sixteen Note properties are accepted. Missing keys fall back to the
    Note's own defaults rather than being written as zero, so the caller cannot
    silently flatten expression it did not mention.
    """
    note = flp.Note()
    note.number = int(data["midi"])
    note.time = int(flp.score.PPQ * data.get("time", 0))
    note.length = int(flp.score.PPQ * data["duration"])
    for key in ("velocity", "pan", "color", "fcut", "fres", "pitchofs"):
        if key in data:
            setattr(note, key, data[key])
    for key in ("slide", "porta", "release", "muted", "selected"):
        if key in data:
            setattr(note, key, bool(data[key]))
    for key in ("group", "repeats"):
        if key in data:
            setattr(note, key, int(data[key]))
    return note


def _handle(request):
    """Run one request and return its response body."""
    action = request.get("action")
    response = {
        "action": action,
        "id": request.get("id"),
        "notes_added": 0,
        "notes_deleted": 0,
        "error": None,
    }

    if action == "clear":
        count = flp.score.noteCount
        for i in range(count - 1, -1, -1):
            flp.score.deleteNote(i)
        response["notes_deleted"] = count
    elif action == "add_notes":
        for data in request.get("notes", []):
            flp.score.addNote(_note_from(data))
            response["notes_added"] += 1
    elif action == "add_chord":
        chord_time = int(flp.score.PPQ * request.get("time", 0))
        for data in request.get("notes", []):
            data = dict(data)
            data.setdefault("duration", request.get("duration", 1.0))
            note = _note_from(data)
            note.time = chord_time + int(flp.score.PPQ * data.get("offset", 0))
            flp.score.addNote(note)
            response["notes_added"] += 1
    elif action == "delete_notes":
        ppq = flp.score.PPQ
        criteria = [
            (int(n["midi"]), int(ppq * n["time"])) for n in request.get("notes", [])
        ]
        for i in range(flp.score.noteCount - 1, -1, -1):
            note = flp.score.getNote(i)
            for midi, time in criteria:
                if note.number == midi and note.time == time:
                    flp.score.deleteNote(i)
                    response["notes_deleted"] += 1
                    break
    else:
        response["error"] = "Unknown action: %s" % action

    return response


def apply(form=None):
    """Process pending requests, export state, and report the outcome.

    The reply is written for every trigger, even when there was nothing to do,
    because the server waits for it and a missing reply is indistinguishable
    from FL not running.
    """
    responses = []
    try:
        requests = _read_requests()
    except Exception as e:
        responses.append({"action": None, "id": None, "notes_added": 0,
                          "notes_deleted": 0, "error": "Invalid request file: %s" % e})
        requests = []

    for request in requests:
        try:
            responses.append(_handle(request))
        except Exception as e:
            responses.append({"action": request.get("action"),
                              "id": request.get("id"), "notes_added": 0,
                              "notes_deleted": 0, "error": str(e)})

    # The queue is emptied before anything else can fail, so a request that has
    # already run cannot replay on the next trigger and duplicate its notes.
    _write_requests([])

    added = sum(r["notes_added"] for r in responses)
    deleted = sum(r["notes_deleted"] for r in responses)
    errors = [r["error"] for r in responses if r["error"]]

    try:
        _write_json(STATE_FILE, _export_state())
    except Exception:
        pass

    _write_json(RESPONSE_FILE, {
        "success": not errors,
        "id": responses[0]["id"] if len(responses) == 1 else None,
        "requests_processed": len(responses),
        "notes_added": added,
        "notes_deleted": deleted,
        "error": "; ".join(errors) if errors else None,
    })


def _write_json(path, data):
    """Write JSON atomically. The server polls for these files."""
    temporary = path + ".tmp"
    with open(temporary, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(temporary, path)
```

- [ ] **Step 4: Run the tests and watch them pass**

Run: `uv run pytest tests/test_piano_roll_script.py -v`
Expected: 7 passed.

- [ ] **Step 5: Write the failing server-side test for reading the reply**

```python
# tests/test_piano_roll_tools.py
"""The server must read the reply the piano roll script writes.

Before this, fl_send_notes wrote a file, sent a keystroke, slept two seconds and
reported success unconditionally. Every failure mode looked identical.
"""

from __future__ import annotations

import pytest

from fl_studio_mcp import tools
from fl_studio_mcp.tools import piano_roll


def _wire(fl_env, monkeypatch, trigger_result=True):
    """Point the tool at the harness and stub the keystroke."""
    monkeypatch.setattr(piano_roll, "piano_roll_scripts_dir", lambda: fl_env.piano_roll_dir)
    monkeypatch.setattr(piano_roll, "trigger_fl_studio", lambda delay=0: (
        fl_env.pyscript.apply() or trigger_result
    ))


def test_send_notes_reports_what_landed(fl_env, monkeypatch):
    _wire(fl_env, monkeypatch)
    result = piano_roll.send_request(
        {"action": "add_notes", "notes": [{"midi": 60, "time": 0.0, "duration": 1.0}]},
        timeout=1.0,
    )
    assert result["success"] is True
    assert result["notes_added"] == 1


def test_send_notes_reports_a_specific_failure(fl_env, monkeypatch):
    _wire(fl_env, monkeypatch)
    result = piano_roll.send_request(
        {"action": "add_notes", "notes": [{"x": 1}]}, timeout=1.0
    )
    assert result["success"] is False
    assert result["error"]


def test_a_failed_keystroke_is_reported(fl_env, monkeypatch):
    """The old code returned True from the trigger even when osascript failed."""
    monkeypatch.setattr(piano_roll, "piano_roll_scripts_dir", lambda: fl_env.piano_roll_dir)
    monkeypatch.setattr(piano_roll, "trigger_fl_studio", lambda delay=0: False)
    result = piano_roll.send_request({"action": "clear"}, timeout=0.05)
    assert result["success"] is False
    assert "trigger" in result["error"].lower()
```

- [ ] **Step 6: Run and watch them fail**

Run: `uv run pytest tests/test_piano_roll_tools.py -v`
Expected: `AttributeError: module 'fl_studio_mcp.tools.piano_roll' has no attribute 'send_request'`.

- [ ] **Step 7: Add `send_request` and route the tools through it**

Refactor `src/fl_studio_mcp/tools/piano_roll.py` so that the request-write,
trigger and response-read sequence lives in one function that every tool uses,
returns the parsed reply, and reports a failed trigger as a failure. The tools
that currently return strings keep returning strings, but now built from the
reply:

```python
def send_request(request: dict, timeout: float = RESPONSE_TIMEOUT) -> dict:
    """Send one request to the piano roll script and return its reply.

    Sequence: clear any stale reply, write the request, trigger the script, poll
    for the reply until the timeout. Every step can fail, and every failure is
    reported rather than assumed away.

    Args:
        request: The request dict, with an "action" key. An "id" is added if the
            caller did not supply one, so the reply can be matched to it.
        timeout: Seconds to wait for the reply.

    Returns:
        The reply dict from the script, or a failure dict with "success": False
        and a specific "error".
    """
    scripts_dir = piano_roll_scripts_dir()
    request_file = scripts_dir / "mcp_request.json"
    response_file = scripts_dir / "mcp_response.json"
    request.setdefault("id", uuid.uuid4().hex)

    if response_file.exists():
        response_file.unlink()
    request_file.write_text(json.dumps([request], indent=2))

    if not trigger_fl_studio(delay=0):
        return {
            "success": False,
            "error": (
                "Could not send the trigger keystroke to FL Studio. Grant "
                "Accessibility permission to this process, or press "
                f"{get_trigger().keystroke} in FL Studio manually."
            ),
        }

    deadline = time.time() + timeout
    while time.time() < deadline:
        if response_file.exists():
            try:
                reply = json.loads(response_file.read_text())
            except json.JSONDecodeError:
                time.sleep(0.02)
                continue
            if reply.get("id") not in (None, request["id"]):
                # A reply to an earlier request. Leave it for that caller.
                time.sleep(0.02)
                continue
            return reply
        time.sleep(0.005)

    return {
        "success": False,
        "error": (
            f"No reply from the piano roll script within {timeout}s. Check that "
            "ComposeWithLLM is installed in FL Studio and that the piano roll "
            "window has focus."
        ),
    }
```

- [ ] **Step 8: Run the whole suite and lint**

Run: `uv run pytest -v && uv run ruff check .`
Expected: everything passes.

- [ ] **Step 9: Commit**

```bash
git add scripts/ComposeWithLLM.pyscript src/fl_studio_mcp/tools/piano_roll.py \
        tests/test_piano_roll_script.py tests/test_piano_roll_tools.py
git commit -m "Read the piano roll script's reply instead of assuming success"
```

- [ ] **Step 10: Copy the pyscript into FL and run the manual smoke test**

`docs/SMOKE_TEST.md` is written in Task 5; the piano roll section is the relevant
one here.

```bash
cp scripts/ComposeWithLLM.pyscript \
   ~/Documents/Image-Line/FL\ Studio/Settings/Piano\ roll\ scripts/ComposeWithLLM.pyscript
```

Then, in FL with a piano roll open, run the smoke test's piano roll section and
record the result. This is the only way to test the keystroke and the real
`flpianoroll`, and it must be done before Phase 2 starts.

---

### Task 5: Smoke test checklist, CI, and the lockfile

**Files:**
- Create: `docs/SMOKE_TEST.md`
- Create: `.github/workflows/ci.yml`
- Modify: `.gitignore` (unignore `uv.lock`)
- Modify: `pyproject.toml` (pytest config)
- Test: `tests/test_docs.py`

**Interfaces:**
- Consumes: everything above.
- Produces: a green CI run on macOS and Windows, and a written procedure for the
  things CI can never cover.

- [ ] **Step 1: Write the smoke test checklist**

```markdown
# Smoke test: what CI cannot cover

CI has no FL Studio. Everything in this file has to be run by a human on a
machine with FL Studio installed, and the result recorded. Every item names the
specific failure it catches, so a skipped item is a known blind spot rather than
a vague worry.

Run the automated pre-flight first:

    uv run pytest
    uv run ruff check .
    uv run python scripts/dev_verify_connection.py

`dev_verify_connection.py` is read-only and prints the port, a round trip, the
environment, latency, and reproduces the known bugs. Run it before and after any
transport change.

## Setup, once per machine

1. `cp fl_controller/device_FLStudioMCP.py ~/Documents/Image-Line/FL\ Studio/Settings/Hardware/FLStudioMCP/`
2. `cp scripts/ComposeWithLLM.pyscript ~/Documents/Image-Line/FL\ Studio/Settings/Piano\ roll\ scripts/`
3. FL Studio: Options > MIDI Settings. Enable the "FL Studio MCP" input, set its
   controller type to "FL Studio MCP Controller".
4. FL Studio: add the ComposeWithLLM piano roll script keystroke (Cmd+Opt+Y on
   macOS, Ctrl+Alt+Y on Windows) if it is not already set.
5. Restart FL Studio. Hot reload covers later script edits; the first install
   does not.

## Every time the controller script changes

Recopy it first. This is the single easiest mistake to make here, and it presents
as the change having had no effect.

- [ ] `cp fl_controller/device_FLStudioMCP.py .../Hardware/FLStudioMCP/`
- [ ] `uv run python scripts/dev_verify_connection.py` and confirm the round trip
      is OK. Catches: a syntax error in the script, which otherwise looks exactly
      like FL not running.
- [ ] Confirm the reported API version is 45 on FL Studio 2026. Catches: talking
      to an older FL than the tests assume.
- [ ] Confirm median latency is near 1ms. Catches: a regression in the adaptive
      poll interval.

## Controller path

- [ ] Read: `fl_get_version` returns version 45 and tempo 130.0 for a 130 BPM
      project. Catches: the thousandths-of-a-BPM scaling being forgotten.
- [ ] Read: `fl_get_channels` lists the real channel names. Catches: the global
      versus pattern-local index flag being wrong, which returns plausible names
      from the wrong channels.
- [ ] Unknown action: send `bogus.doesNotExist` and confirm the reply is a
      failure, not a success. Catches: the merge bug, if it ever returns.
- [ ] Safe edit: with playback running, confirm a mutating tool refuses rather
      than corrupting the project. Catches: `safeToEdit` gating being dropped.
      Ask before running this one; it touches the open project.

## Piano roll path

This is the only path that can be tested by nothing but a human: it needs the
keystroke, the Accessibility permission, and the real `flpianoroll`.

- [ ] Open a piano roll on a known channel by hand, so the target is not in doubt.
- [ ] `fl_send_notes` a short phrase and press the keystroke when prompted if
      auto-trigger is unavailable. Confirm the notes appear on the expected
      channel. Catches: notes landing in whichever piano roll happened to be
      focused, which is Phase 2's targeting work.
- [ ] Confirm the tool's report matches what actually landed. Catches: the reply
      being ignored, which is what the old code did.
- [ ] Send a request with a deliberately invalid note and confirm the tool reports
      a specific failure. Catches: unconditional success reporting.
- [ ] Trigger twice in a row with no new requests and confirm no notes are
      duplicated or deleted. Catches: requests left in the queue replaying.
- [ ] Grant nothing: with Accessibility permission revoked, confirm the tool
      reports that the trigger failed instead of timing out silently. Catches:
      the trigger's exit code being ignored.

## Platforms

Both must be covered before a release, and Windows needs the extra step.

- [ ] macOS: the whole list above.
- [ ] Windows: the whole list above, plus confirm the server uses a loopMIDI port
      rather than trying to create a virtual one. Catches: a regression that
      breaks Windows, which has no virtual MIDI API.
- [ ] Windows with OneDrive Documents redirection: confirm the settings directory
      is found. Catches: upstream issue #2.

## Record

Note the date, FL Studio version, API version, and any item that failed, in the
commit message or the PR description. A smoke test with no record is a rumour.
```

- [ ] **Step 2: Write the test that keeps the checklist honest**

```python
# tests/test_docs.py
"""Documentation that has to stay true to the code."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_smoke_test_names_both_scripts_that_must_be_copied():
    text = (REPO_ROOT / "docs" / "SMOKE_TEST.md").read_text()
    assert "device_FLStudioMCP.py" in text
    assert "ComposeWithLLM.pyscript" in text


def test_smoke_test_covers_both_platforms():
    text = (REPO_ROOT / "docs" / "SMOKE_TEST.md").read_text()
    assert "macOS" in text
    assert "Windows" in text
    assert "loopMIDI" in text


def test_readme_does_not_claim_macos_needs_the_iac_driver():
    """The virtual port removed that step; the README still described it."""
    text = (REPO_ROOT / "README.md").read_text()
    assert "IAC Driver enabled" not in text or "no longer" in text.lower()
```

- [ ] **Step 3: Run and fix the README**

Run: `uv run pytest tests/test_docs.py -v`
Expected: the third test fails against the current README. Fix the README's macOS
setup section to describe the virtual port, note that no IAC Driver is needed on
macOS, and keep the loopMIDI instructions for Windows.

- [ ] **Step 4: Add the CI workflow**

```yaml
# .github/workflows/ci.yml
name: CI

on:
  push:
    branches: [main]
  pull_request:

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true
      - run: uv sync --dev --locked
      - run: uv run ruff check --output-format=github .

  test:
    strategy:
      fail-fast: false
      matrix:
        os: [macos-latest, windows-latest]
        python: ["3.10", "3.13"]
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true
      - run: uv sync --dev --locked --python ${{ matrix.python }}
      - run: uv run pytest -v
```

- [ ] **Step 5: Verify the workflow locally as far as possible**

Run: `uv run pytest -v && uv run ruff check .`
Then confirm the workflow's exact commands work from a clean environment:

```bash
rm -rf /tmp/flmcp-ci && git clone . /tmp/flmcp-ci && cd /tmp/flmcp-ci
uv sync --dev --locked && uv run ruff check . && uv run pytest
```

Expected: green. If `--locked` fails, the lockfile is stale; run `uv lock` and
commit `uv.lock`.

- [ ] **Step 6: Track the lockfile and add pytest config**

`.gitignore`: remove the `uv.lock` line. Then:

```bash
git add uv.lock .gitignore
```

`pyproject.toml`, append:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
# The fakes live in tests/fakes and are imported as `tests.fakes`, so the repo
# root has to be importable.
addopts = "-q"
```

- [ ] **Step 7: Push and confirm CI is green on both platforms**

Run: `git push` and watch the Actions run.

Expected: lint green, four test jobs green. Windows is the one that matters: it
has no virtual MIDI API, so any test that reaches for one fails there and not
locally.

- [ ] **Step 8: Commit**

```bash
git add docs/SMOKE_TEST.md .github/workflows/ci.yml .gitignore pyproject.toml \
        uv.lock tests/test_docs.py README.md
git commit -m "Add CI, the smoke test checklist, and a committed lockfile"
```

---

## Phase 0 exit criteria

The roadmap's own bar, restated so it can be checked rather than believed:

- [ ] `uv run pytest` passes on a machine with no FL Studio installed, from a
      clean clone, on macOS and Windows.
- [ ] `uv run ruff check .` is clean.
- [ ] CI is green on both platforms and both Python versions.
- [ ] `docs/SMOKE_TEST.md` exists and its items have been run once by hand against
      live FL Studio, with the result recorded.
- [ ] The controller script, the pyscript and the server all agree on the settings
      directory, proven by test.
- [ ] No fake defines a function the stubs do not, proven by test.
- [ ] `uv run python scripts/dev_verify_connection.py` still reports a round trip
      near 1ms, after the Task 1 controller changes are copied into FL.

## What Phase 0 deliberately does not do

- It does not add request correlation, batch undo grouping, or the `ping`
  handshake. Those are Phase 1, and the harness built here is what makes them
  testable.
- It does not add a `channel` argument to the piano roll tools. That is Phase 2.
- It does not make the SysEx transport work. See
  `docs/spikes/2026-09-19-T4-sysex-transport.md` for why that is a negative result
  rather than unfinished work.
