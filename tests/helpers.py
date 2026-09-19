"""Test helpers for loading the real FL-side scripts against fake FL modules.

The scripts are loaded from their real paths rather than copied, so the tests
exercise exactly what ships. They are reloaded per test because they resolve
their file paths at import time.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from importlib.machinery import SourceFileLoader
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONTROLLER_PATH = REPO_ROOT / "fl_controller" / "device_FLStudioMCP.py"
PYSCRIPT_PATH = REPO_ROOT / "scripts" / "ComposeWithLLM.pyscript"
CONTROLLER_MODULE_NAME = "fl_controller_under_test"
PYSCRIPT_MODULE_NAME = "fl_pyscript_under_test"

# Modules the controller script imports, per ROADMAP.md's sandbox rules.
CONTROLLER_IMPORTS = (
    "channels",
    "device",
    "general",
    "mixer",
    "plugins",
    "transport",
    "ui",
)

# Every FL module a script may reach for, including the ones later phases add.
FL_MODULE_NAMES = (
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


def blank_modules(names=CONTROLLER_IMPORTS) -> dict[str, types.ModuleType]:
    """Empty stand-ins, for tests that only care about one module."""
    return {name: types.ModuleType(name) for name in names}


def module_with(**attributes) -> types.ModuleType:
    """A stand-in carrying specific attributes, for feature-detection tests."""
    module = types.ModuleType("fake")
    for key, value in attributes.items():
        setattr(module, key, value)
    return module


def load_controller(monkeypatch, fl_modules: dict | None = None) -> types.ModuleType:
    """Load the real controller script against the given fake FL modules.

    Every FL module the controller imports is installed, so a caller can override
    just the one it cares about and leave the rest empty. monkeypatch handles
    removal afterwards.
    """
    installed = blank_modules()
    installed.update(fl_modules or {})
    for name, module in installed.items():
        monkeypatch.setitem(sys.modules, name, module)
    return _load_from_path(CONTROLLER_PATH, CONTROLLER_MODULE_NAME, monkeypatch)


def load_pyscript(monkeypatch, fl_modules: dict | None = None) -> types.ModuleType:
    """Load the real piano roll script against the given fake flpianoroll.

    The pyscript's only FL module is flpianoroll, which is exactly why the two
    paths cannot be merged.
    """
    installed = {"flpianoroll": (fl_modules or {}).get("flpianoroll")}
    if installed["flpianoroll"] is None:
        installed["flpianoroll"] = types.ModuleType("flpianoroll")
    for name, module in installed.items():
        monkeypatch.setitem(sys.modules, name, module)
    return _load_from_path(PYSCRIPT_PATH, PYSCRIPT_MODULE_NAME, monkeypatch)


def _load_from_path(path: Path, name: str, monkeypatch) -> types.ModuleType:
    """Import a module from an arbitrary path, replacing any earlier copy.

    The loader is chosen explicitly rather than by extension, because the piano
    roll script is a `.pyscript` and importlib only knows the extensions in
    importlib.machinery.SOURCE_SUFFIXES.
    """
    sys.modules.pop(name, None)
    loader = SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    monkeypatch.setitem(sys.modules, name, module)
    loader.exec_module(module)
    return module
