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

SAMPLE_DIRS_ENV = "FL_STUDIO_MCP_SAMPLE_DIRS"

# Where a copy of FL Studio keeps its factory content. The application folder carries
# the release year, so the bundle is globbed rather than written down: a hardcoded year
# means the sample search silently finds nothing the first time FL is upgraded.
MACOS_APPLICATIONS = Path("/Applications")
MACOS_FACTORY_GLOB = "FL Studio*.app/Contents/Resources/FL/Data/Patches/Packs"
WINDOWS_FACTORY_GLOBS = (
    "Image-Line/FL Studio*/Data/Patches/Packs",
    "Image-Line/FL Studio*/Resources/FL/Data/Patches/Packs",
)


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


def sample_roots() -> list[Path]:
    """The folders worth searching for samples, each one that exists.

    FL_STUDIO_MCP_SAMPLE_DIRS wins when set, separated by os.pathsep, which is what a
    producer with samples on another drive, or a test, needs. Its entries are kept even
    when they are missing, so the caller can be told which one was not found. Otherwise
    the known locations are used, each only when it exists, because a fresh machine has
    none of them: the FL user folders, the factory packs of an installed copy of FL
    Studio, Apple Loops, Logic and GarageBand.

    The factory packs are discovered rather than hardcoded. FL's application folder
    carries the release year, so on macOS the bundle is matched with
    `/Applications/FL Studio*.app/Contents/Resources/FL/Data/Patches/Packs`, and on
    Windows an Image-Line install is matched under the usual program directories. Both
    layouts are tried on both platforms, since only one of them can exist on a machine
    and a platform check would be one more thing to get wrong.
    """
    override = os.environ.get(SAMPLE_DIRS_ENV)
    if override:
        parts = [Path(part).expanduser() for part in override.split(os.pathsep) if part.strip()]
        return _without_duplicates(parts)

    home = Path.home()
    candidates = [
        home / "Documents" / "Image-Line" / "FL Studio",
        home / "Documents" / "Image-Line" / "Downloads",
        home / "OneDrive" / "Documents" / "Image-Line" / "FL Studio",
    ]
    candidates.extend(_factory_packs())
    candidates.extend(
        [
            Path("/Library/Audio/Apple Loops/Apple"),
            Path("/Library/Application Support/Logic"),
            Path("/Library/Application Support/GarageBand"),
        ]
    )
    return _without_duplicates([path for path in candidates if path.is_dir()])


def _factory_packs() -> list[Path]:
    """The factory packs folder of an installed copy of FL Studio, if there is one."""
    found: list[Path] = []
    if MACOS_APPLICATIONS.is_dir():
        found.extend(sorted(MACOS_APPLICATIONS.glob(MACOS_FACTORY_GLOB)))
    for base in _program_dirs():
        if not base.is_dir():
            continue
        for pattern in WINDOWS_FACTORY_GLOBS:
            found.extend(sorted(base.glob(pattern)))
    return found


def _program_dirs() -> list[Path]:
    """The directories a Windows install lives in, whether or not they exist here."""
    bases = [os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")]
    return [Path(base) for base in bases if base]


def _without_duplicates(paths: list[Path]) -> list[Path]:
    """The list without repeats, keeping the first place each path appeared."""
    unique: list[Path] = []
    for path in paths:
        if path not in unique:
            unique.append(path)
    return unique
