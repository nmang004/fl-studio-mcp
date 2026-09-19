"""Where FL Studio keeps its settings on this machine.

Three things need to agree on this path: the server (which writes the command and
request files), the controller script (which reads them inside FL Studio), and the
piano roll script (inside a separate sandbox). Two of those live in FL's embedded
Python, which cannot import from this package, so the same resolution logic exists
in three places by necessity. `tests/test_paths.py` pins this copy and
`tests/test_controller_settings_dir.py` pins the copy inside FL.
"""

from __future__ import annotations

import os
from pathlib import Path

SETTINGS_DIR_ENV = "FL_STUDIO_MCP_SETTINGS_DIR"


def settings_dir() -> Path:
    """Return FL Studio's Settings directory, without creating it.

    FL_STUDIO_MCP_SETTINGS_DIR wins when set, which is what tests use and what a
    user with a relocated Documents folder needs. Otherwise the platform default
    is used, preferring a OneDrive-redirected Documents folder on Windows when it
    exists: a Microsoft account often keeps Documents there.
    """
    override = os.environ.get(SETTINGS_DIR_ENV)
    if override:
        return Path(override).expanduser()

    home = Path.home()
    candidates = [home / "Documents" / "Image-Line" / "FL Studio" / "Settings"]
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
