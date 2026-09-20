"""Index a folder of FL Studio projects without opening FL Studio.

An index is what answers "which sketch was the 130 BPM one" from the files themselves.
Every field comes from `utils.flp`, which reads the project's own uncompressed event
stream and refuses to report anything it could not verify, so a row here is either a
measured value or null with the reason beside it. That matters more here than anywhere
else in the server: a project folder holds autosaves, exports and half written
downloads, and a wrong tempo in an index is worse than a blank one.

The scan is recursive and bounded, the same shape as the sample walk. It is newest
first, because the sketch from last night is the one a producer is looking for, and the
cap that cuts the list short is reported rather than silent. A scan is cached under the
library root in `index/`, and `refresh=True` walks the folder again. The cache never
lives in a project folder: those belong to FL Studio and to the producer, and this
server writes nothing there.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fl_studio_mcp.utils import flp, paths, store

if TYPE_CHECKING:
    from fastmcp import FastMCP

DEFAULT_LIMIT = 50

# A caller asking for everything is usually a caller who has not thought about the
# size of the answer, so the cap is enforced rather than suggested.
MAX_LIMIT = 500

# The walk is bounded twice, and both bounds are reported when they are hit. A project
# folder is small by sample library standards, but it is often a synced folder with a
# Backup tree in it, and a folder that turns out to be a mounted drive is still
# answered in a moment.
MAX_FILES = 5000
MAX_DEPTH = 6

PROJECT_SUFFIX = ".flp"

# FL Studio keeps the projects folder beside the Settings folder it is using, so the
# default is derived from the one module that decides where Settings is rather than
# written down here. See default_projects_folder.
PROJECTS_FOLDER_NAME = "Projects"

# The cache's schema number, so a later change to the entry shape is refused and the
# folder walked again rather than misread.
_CACHE_SCHEMA = 1


def index_projects(
    folder: str | Path | None = None,
    refresh: bool = False,
    limit: int = DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Index the FL Studio projects in one folder, newest first.

    The scan is recursive: a project folder usually holds a Backup tree, and the
    autosave from an hour ago is exactly what someone is looking for. Every `.flp`
    file found is read with `utils.flp.read_flp`, and a file that is not a project, or
    is truncated or rewritten, becomes a row with its status and problems rather than
    failing the scan. Files with any other extension are counted and skipped.

    Args:
        folder: The folder to scan. When omitted, FL Studio's projects folder is used,
            derived from the Settings folder FL is using through
            `utils.paths.settings_dir` so a relocated or OneDrive Documents folder
            still resolves.
        refresh: Walk the folder again instead of answering from the cached scan.
        limit: How many projects to return, newest first, up to MAX_LIMIT.

    Returns:
        projects: one row per project, newest first, each with its name, path, status,
            size, modified time, tempo, time signature, title, version, build and
            plugin names, plus the problems that stopped a field being read.
        total, returned, truncated, limit: how many `.flp` files were found, how many
            came back, whether the cap cut the list short, and what the cap was.
        unreadable: how many of the files found could not be read as a project.
        cache: whether the answer came from the cached scan, where that cache is, when
            it was written, and any problem with reading or writing it.
        walk: how many files were examined, how many were not `.flp`, and whether the
            walk's file or depth bound stopped it early.
        A folder that is not there is reported as an error rather than raised.
    """
    target = Path(folder).expanduser() if folder else default_projects_folder()
    capped = max(1, min(int(limit), MAX_LIMIT))
    if not target.is_dir():
        return _missing_reply(target, capped)

    scan: dict[str, Any] | None = None
    problem: str | None = None
    from_cache = False
    cache_path: Path | None = None

    if not refresh:
        scan, problem = _read_cache(target)
        from_cache = scan is not None
        if from_cache:
            cache_path = _cache_path(target)

    if scan is None:
        scan = _scan(target)
        written, write_problem = _write_cache(target, scan)
        cache_path = written
        if write_problem is not None:
            # The read problem, if there was one, still explains why this walked.
            problem = f"{problem} {write_problem}" if problem else write_problem

    return _reply(target, scan, capped, from_cache, cache_path, problem)


def default_projects_folder() -> Path:
    """FL Studio's projects folder, discovered rather than written down.

    FL keeps the projects folder beside the Settings folder it is using, and
    `utils.paths.settings_dir` is the one place that decides where that is: the
    FL_STUDIO_MCP_SETTINGS_DIR override first, then Documents, preferring a OneDrive
    redirected Documents folder on Windows when it exists. Deriving the projects
    folder from it means a relocated Documents folder and a Microsoft account both
    land in the right place, and no path is hardcoded.
    """
    return paths.settings_dir().parent / PROJECTS_FOLDER_NAME


def _scan(folder: Path) -> dict[str, Any]:
    """Walk one folder and read every project file in it, newest first."""
    state = _new_state()
    entries = [_row(path, flp.read_flp(path)) for path in _iter_project_files(folder, state)]
    entries.sort(key=_order)
    return {
        "entries": entries,
        "walk": {
            "examined": state["examined"],
            "not_flp": state["not_flp"],
            "max_files": state["max_files"],
            "max_depth": state["max_depth"],
            "file_limit_reached": state["file_limit_reached"],
            "depth_limit_reached": state["depth_limit_reached"],
            "unreadable_folders": state["unreadable_folders"],
        },
        "scanned_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def _row(path: Path, result: dict[str, Any]) -> dict[str, Any]:
    """One project, as the index reports it: what was read, and what could not be.

    Every key is present on every row, with None where the reader refused a value, so
    a caller can read a row without guarding lookups. The reader's own status and
    problems are passed through unchanged rather than summarised: the problem text
    names the event or the check that failed, which is what makes a bad file
    diagnosable from the index alone.
    """
    plugins = result.get("plugins") or []
    modified = result.get("modified")
    return {
        "name": path.name,
        "path": str(path),
        "status": result.get("status"),
        "ok": bool(result.get("ok")),
        "problems": list(result.get("problems") or []),
        "size": result.get("size"),
        "modified": modified,
        "modified_iso": _iso(modified),
        "tempo": result.get("tempo"),
        "time_signature": result.get("time_signature"),
        "title": result.get("title"),
        "version": result.get("version"),
        "build": result.get("build"),
        "header": result.get("header"),
        "events": (result.get("walk") or {}).get("events"),
        "plugins": plugins,
        "plugin_names": [plugin.get("name") for plugin in plugins if plugin.get("name")],
    }


def _iter_project_files(folder: Path, state: dict[str, Any]):
    """Yield the project files under one folder, stopping at the walk's two bounds.

    Breadth first, with the entries of each folder sorted, so the same folder answers
    the same way twice. Every file seen counts against the file bound, including the
    ones skipped for their extension, because that is what makes the bound a bound. A
    folder that cannot be listed is recorded and stepped over: one unreadable folder
    must not end a scan that has other folders to try.
    """
    queue: deque[tuple[Path, int]] = deque([(folder, 0)])
    while queue:
        directory, depth = queue.popleft()
        try:
            entries = sorted(directory.iterdir(), key=lambda entry: entry.name.lower())
        except OSError as error:
            state["unreadable_folders"].append({"path": str(directory), "error": str(error)})
            continue

        for entry in entries:
            try:
                if entry.is_dir():
                    if depth + 1 > state["max_depth"]:
                        state["depth_limit_reached"] = True
                        continue
                    queue.append((entry, depth + 1))
                    continue
                if not entry.is_file():
                    continue
            except OSError as error:
                state["unreadable_folders"].append({"path": str(entry), "error": str(error)})
                continue

            if state["examined"] >= state["max_files"]:
                state["file_limit_reached"] = True
                return
            state["examined"] += 1
            if entry.suffix.lower() != PROJECT_SUFFIX:
                state["not_flp"] += 1
                continue
            yield entry


def _new_state() -> dict[str, Any]:
    """The walk's counters, read from the module so a test can lower the bounds."""
    return {
        "examined": 0,
        "not_flp": 0,
        "max_files": MAX_FILES,
        "max_depth": MAX_DEPTH,
        "file_limit_reached": False,
        "depth_limit_reached": False,
        "unreadable_folders": [],
    }


def _order(entry: dict[str, Any]) -> tuple[float, str]:
    """Newest first, with a file whose modified time could not be read last.

    A project the reader could not stat has no place in a "most recent" order, so it
    sorts after every file that has a time, and the name breaks ties so two runs over
    the same folder answer in the same order.
    """
    return (-(entry["modified"] or 0.0), entry["name"])


def _iso(timestamp: float | None) -> str | None:
    """A Unix timestamp as a readable UTC time, or None when it was not measured."""
    if timestamp is None:
        return None
    try:
        return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat(timespec="seconds")
    except (OSError, OverflowError, ValueError):
        return None


def _reply(
    folder: Path,
    scan: dict[str, Any],
    capped: int,
    from_cache: bool,
    cache_path: Path | None,
    problem: str | None,
) -> dict[str, Any]:
    """The reply, built from a scan every time so the message matches this call.

    The cache holds the scan, not the reply: a later call with a different limit must
    report its own cap, and a cached message would name the first caller's.
    """
    entries = scan["entries"]
    total = len(entries)
    page = entries[:capped]
    unreadable = sum(1 for entry in entries if not entry["ok"])
    returned = len(page)
    return {
        "success": True,
        "message": _message(
            folder=folder,
            total=total,
            returned=returned,
            capped=capped,
            unreadable=unreadable,
            scan=scan,
            from_cache=from_cache,
        ),
        "folder": str(folder),
        "projects": page,
        "total": total,
        "returned": returned,
        "truncated": total > returned,
        "limit": capped,
        "unreadable": unreadable,
        "walk": scan["walk"],
        "cache": {
            "used": from_cache,
            "path": str(cache_path) if cache_path else None,
            "scanned_at": scan.get("scanned_at"),
            "problem": problem,
        },
    }


def _message(
    *,
    folder: Path,
    total: int,
    returned: int,
    capped: int,
    unreadable: int,
    scan: dict[str, Any],
    from_cache: bool,
) -> str:
    """The sentence a caller reads first, including everything that limits it."""
    if total == 0:
        sentence = f"No project file was found in {folder}."
    else:
        sentence = (
            f"Indexed {total} project file(s) in {folder}, newest first, and returned "
            f"{returned}."
        )
    if returned < total:
        sentence += f" The limit of {capped} cut the list short."
    if unreadable:
        sentence += (
            f" {unreadable} of them could not be read as a project; each row carries "
            "its status and the reason."
        )
    if from_cache:
        sentence += (
            f" Answered from the cache written at {scan['scanned_at']}; pass "
            "refresh=True to walk the folder again."
        )
    else:
        sentence += " The folder was walked for this answer."
    walk = scan["walk"]
    if walk["file_limit_reached"]:
        sentence += (
            f" The walk stopped after {walk['max_files']} files, so this answer is "
            "incomplete: index a narrower folder to see the rest."
        )
    if walk["depth_limit_reached"]:
        sentence += (
            f" The walk stopped {walk['max_depth']} folder level(s) below the folder "
            "asked for, so deeper folders were not searched."
        )
    if walk["unreadable_folders"]:
        names = ", ".join(item["path"] for item in walk["unreadable_folders"])
        sentence += f" Could not list: {names}."
    return sentence.strip()


def _missing_reply(target: Path, capped: int) -> dict[str, Any]:
    """A folder that is not there, reported in the shape the scan would have used."""
    return {
        "success": False,
        "error": (
            f"{target} is not a folder, so there is nothing to index. Pass a folder "
            "that holds .flp files, or leave the folder out to use FL Studio's "
            "projects folder."
        ),
        "folder": str(target),
        "projects": [],
        "total": 0,
        "returned": 0,
        "truncated": False,
        "limit": capped,
        "unreadable": 0,
        "walk": _empty_walk(),
        "cache": {"used": False, "path": None, "scanned_at": None, "problem": None},
    }


def _empty_walk() -> dict[str, Any]:
    """The walk block for a reply that never walked anything."""
    return {
        "examined": 0,
        "not_flp": 0,
        "max_files": MAX_FILES,
        "max_depth": MAX_DEPTH,
        "file_limit_reached": False,
        "depth_limit_reached": False,
        "unreadable_folders": [],
    }


def _cache_path(folder: Path) -> Path:
    """The cache file for one folder, under the library root, never in the folder.

    The name is a hash of the folder path because a folder path is not a legal and
    stable file name on both platforms, and the payload carries the folder it belongs
    to so a collision or a moved library is detected rather than believed.
    """
    digest = hashlib.sha256(str(folder).encode("utf-8")).hexdigest()[:16]
    return store.library_root() / "index" / f"{digest}.json"


def _read_cache(folder: Path) -> tuple[dict[str, Any] | None, str | None]:
    """The cached scan for one folder, and any reason it could not be used.

    A cache is an optimisation, so every failure means "walk the folder again" and
    none of them is raised: a cache written by another version, one that belongs to a
    different folder, or a truncated file all come back as absent with a reason the
    caller can see.
    """
    path = _cache_path(folder)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, None
    except (OSError, ValueError) as error:
        return None, (
            f"the cache at {path} could not be read, so the folder was walked again: "
            f"{error}"
        )

    if not isinstance(payload, dict) or payload.get("schema") != _CACHE_SCHEMA:
        return None, (
            f"the cache at {path} was not written by this version, so the folder was "
            "walked again"
        )
    if payload.get("folder") != str(folder) or not isinstance(payload.get("entries"), list):
        return None, (
            f"the cache at {path} does not belong to {folder}, so the folder was walked "
            "again"
        )
    return payload, None


def _write_cache(folder: Path, scan: dict[str, Any]) -> tuple[Path | None, str | None]:
    """Store one scan under the library root, and report a failure rather than raise.

    The temporary file plus os.replace is the same host-side write the record store
    uses. A scan that cannot be cached is still a good scan: losing the cache costs a
    second walk, never the answer.
    """
    path = _cache_path(folder)
    payload = {"schema": _CACHE_SCHEMA, "folder": str(folder), **scan}
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    except OSError as error:
        return None, f"the scan could not be cached, so the next call will walk again: {error}"
    return path, None


def register_index_tools(mcp: FastMCP) -> None:
    """Register the project indexing tool."""

    @mcp.tool()
    def fl_index_projects(
        folder: str | None = None,
        refresh: bool = False,
        limit: int = DEFAULT_LIMIT,
    ) -> dict:
        """Index a folder of FL Studio projects without opening FL Studio.

        Each project is read from its own file: its tempo, time signature, title,
        version, build and the plugins it names, plus its size and modified time. The
        scan is recursive and newest first, so an autosave from last night is at the
        top. A file that is not a project, or that is truncated or rewritten, is a row
        with its status and the reason rather than a failed scan, which matters
        because a project folder collects exports and half written downloads too.

        The fields come from the reader in `utils.flp`, which refuses to report a
        value it could not verify. A project whose tempo cannot be read has null there
        and a problem saying why, rather than a guessed number: a wrong tempo in an
        index is worse than a blank one.

        Args:
            folder: The folder to scan, recursively. Omit it to use FL Studio's
                    projects folder, discovered from the Settings folder FL uses.
            refresh: Walk the folder again instead of answering from the cached scan
                     under the library root.
            limit: How many projects to return, newest first, up to 500. The reply
                   says when this cut the list short.

        Returns:
            projects: one row per project, newest first, with the fields above and any
                      problems that stopped one being read.
            total, returned, truncated, limit, unreadable: how many `.flp` files were
                      found, how many came back, and how many could not be read.
            cache, walk: where the answer came from, and what the walk skipped.
        """
        return index_projects(folder=folder, refresh=refresh, limit=limit)
