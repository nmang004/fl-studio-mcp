"""Fake FL Studio modules, injected into sys.modules for one test at a time.

The point of this package is that the *real* controller script and the *real*
piano roll script are exercised, with only FL itself replaced. Nothing here
reimplements the scripts.
"""

from __future__ import annotations

import sys
from types import ModuleType

from tests.fakes.modules import MODULE_NAMES, build_fake_modules
from tests.fakes.project import FakeProject

_INSTALLED: list[str] = []


def install(project: FakeProject) -> dict[str, ModuleType]:
    """Put the fake FL modules into sys.modules and return them.

    Any module already under one of these names is replaced, so the fakes always
    win over anything a test environment happened to provide.
    """
    modules = build_fake_modules(project)
    unexpected = set(modules) - set(MODULE_NAMES)
    assert not unexpected, f"fake module set drifted: {sorted(unexpected)}"
    for name, module in modules.items():
        sys.modules[name] = module
        if name not in _INSTALLED:
            _INSTALLED.append(name)
    return modules


def uninstall() -> None:
    """Remove every fake module this package installed."""
    while _INSTALLED:
        sys.modules.pop(_INSTALLED.pop(), None)
