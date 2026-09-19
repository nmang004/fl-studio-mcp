"""Assemble one fake module per FL module, all bound to the same project.

`MODULE_NAMES` is the contract: every FL module either script may import has a
fake here, and the installer asserts the set matches rather than merging quietly.
A missing entry would otherwise show up as an ImportError in one test and as a
silently different code path in another.
"""

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

_BUILDERS = {
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


def build_fake_modules(project: FakeProject) -> dict[str, ModuleType]:
    """Build every fake module, bound to one project."""
    missing = set(MODULE_NAMES) - set(_BUILDERS)
    if missing:
        raise AssertionError(f"no fake builder for {sorted(missing)}")
    extra = set(_BUILDERS) - set(MODULE_NAMES)
    if extra:
        raise AssertionError(f"fake builders not declared in MODULE_NAMES: {sorted(extra)}")
    return {name: _BUILDERS[name](project) for name in MODULE_NAMES}
