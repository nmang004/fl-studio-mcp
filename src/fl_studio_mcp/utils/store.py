"""The library: plain JSON records under one root.

Where FL Studio keeps its settings is `utils.paths`. This is where this server keeps
what it has learned: riffs, plugin presets and project snapshots. The producer owns
these files. They are JSON with a schema number, readable in any editor, copyable to a
backup, and diffable by git, because a library in a format only this server can read is
a library that is lost the first time the server breaks.

Nothing in this module runs inside FL Studio. Both sandboxes block the filesystem
calls used here, which is why the two scripts keep their own tiny readers and writers
and this stays on the host. Tests point the root at a temporary directory and never
touch a real home directory.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

# The environment variable that moves the whole library, for a second drive, a synced
# folder, or a test suite.
LIBRARY_HOME_ENV = "FL_STUDIO_MCP_HOME"

# The kinds of record the library holds. A fixed set rather than free strings: these
# become directory names, so an unknown kind is a bug in this package, not input.
KINDS = ("riffs", "presets", "snapshots")

# What a record id may look like. An id reaches the filesystem as a file name, and ids
# are produced from a name a model chose, so this is the boundary between a tool call
# and a path. Letters, digits, dot, dash and underscore only, and it may not start with
# a dot: that alone refuses "..", ".hidden" and every separator on both platforms.
_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")

_SLUG_LENGTH = 40


def library_root() -> Path:
    """The library's root directory, without creating it.

    FL_STUDIO_MCP_HOME wins when set. The default is deliberately not inside FL's
    Settings tree: that directory is FL's, it is synced by some producers and not
    others, and a broken library file should never be something FL has to read.
    """
    override = os.environ.get(LIBRARY_HOME_ENV)
    if override:
        return Path(override).expanduser()
    return Path.home() / ".fl_studio_mcp"


def library_dir(kind: str) -> Path:
    """One kind's directory, created if missing."""
    if kind not in KINDS:
        raise ValueError(f"unknown library kind: {kind!r}, expected one of {KINDS}")
    path = library_root() / kind
    path.mkdir(parents=True, exist_ok=True)
    return path


def safe_record_id(record_id: str) -> str | None:
    """Return the id when it is safe to use as a file name, else None.

    A caller-supplied id is untrusted: it arrives from a model that may have built it
    from a producer's words, and "../../.ssh/authorized_keys" is a legal JSON string.
    Refusing by shape is stronger than sanitising, because there is then nothing to get
    wrong, and a refusal is visible to the caller.
    """
    if not isinstance(record_id, str):
        return None
    if not _ID_PATTERN.match(record_id):
        return None
    if set(record_id) <= {"."}:
        return None
    return record_id


def new_record_id(name: str, when: datetime | None = None) -> str:
    """A sortable id: when it was made, then what it is called."""
    moment = when or datetime.now()
    return f"{moment.strftime('%Y-%m-%d-%H%M%S')}-{_slug(name)}"


def unique_record_id(kind: str, name: str, when: datetime | None = None) -> str:
    """An id that is not taken yet, by appending a counter.

    Saving the same riff name twice in one second is ordinary, and silently replacing
    the first one would turn a save into a loss.
    """
    base = new_record_id(name, when)
    candidate = base
    counter = 2
    while (library_dir(kind) / f"{candidate}.json").exists():
        candidate = f"{base}-{counter}"
        counter += 1
    return candidate


def write_record(
    kind: str, record_id: str, payload: dict[str, Any], overwrite: bool = False
) -> Path:
    """Write one record, atomically, and return its path.

    The temporary file plus os.replace is a host-only luxury: both FL sandboxes raise
    SystemError on os.replace, measured live, which is why the controller writes its
    response in place instead. On the host a half written record would be a corrupted
    library entry, so it is worth the extra call.
    """
    safe = safe_record_id(record_id)
    if safe is None:
        raise ValueError(
            f"unsafe record id: {record_id!r}. Ids are used as file names, so they may "
            "contain only letters, digits, dot, dash and underscore, and may not start "
            "with a dot."
        )

    directory = library_dir(kind)
    path = directory / f"{safe}.json"
    if path.exists() and not overwrite:
        raise ValueError(
            f"a {kind} record with id {safe!r} already exists. Pick another id rather "
            "than replacing a record the producer saved."
        )

    text = json.dumps(payload, indent=2, sort_keys=False) + "\n"
    temporary = directory / f".{safe}.json.tmp"
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)
    return path


def read_record(kind: str, record_id: str) -> dict[str, Any] | None:
    """Read one record, or None when it is missing or unusable."""
    safe = safe_record_id(record_id)
    if safe is None:
        return None
    path = library_dir(kind) / f"{safe}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def list_records(kind: str, limit: int | None = None) -> dict[str, Any]:
    """Every record, newest first, with the unusable ones named rather than raised.

    One truncated file must not hide the rest of a producer's library, and it must not
    be invisible either: it comes back in `skipped` so a caller can say so.
    """
    directory = library_dir(kind)
    records = []
    skipped = []
    for path in sorted(directory.glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            skipped.append(path.stem)
            continue
        if not isinstance(record, dict):
            skipped.append(path.stem)
            continue
        record.setdefault("id", path.stem)
        records.append(record)

    # Newest first by the record's own timestamp, falling back to its id, which begins
    # with one. Sorting by id alone would order two records made in the same second by
    # name, which is not what "recent" means.
    records.sort(key=lambda record: str(record.get("created") or record["id"]), reverse=True)

    total = len(records)
    truncated = False
    if limit is not None and limit >= 0 and total > limit:
        records = records[:limit]
        truncated = True
    return {"records": records, "skipped": skipped, "total": total, "truncated": truncated}


def delete_record(kind: str, record_id: str) -> bool:
    """Delete one record. False when it was not there, or when the id was unsafe."""
    safe = safe_record_id(record_id)
    if safe is None:
        return False
    path = library_dir(kind) / f"{safe}.json"
    try:
        path.unlink()
    except OSError:
        return False
    return True


def _slug(name: str) -> str:
    """A file name fragment made from a producer's words.

    Not a security boundary, since safe_record_id checks the finished id. This only
    makes an id readable and predictable: "Deep Stab!" becomes "deep-stab".
    """
    lowered = (name or "").strip().lower()
    fragment = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    fragment = fragment[:_SLUG_LENGTH].strip("-")
    return fragment or "record"
