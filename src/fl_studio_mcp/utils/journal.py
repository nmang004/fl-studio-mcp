"""What the server did, in the order it did it.

The journal answers one question a producer asks after letting an assistant near their
project: what did you change. It is an append-only file of one JSON object per line,
one file per day, under the library root. JSONL rather than JSON so that a tail of the
file is readable on its own, and so that a process that dies mid-write loses at most
one line.

Two properties are worth more than completeness:

- A journal write never breaks the command it was recording. Losing a log line is
  acceptable; losing a fader move because the log failed is not, and a read-only disk
  is the ordinary way that happens. Every failure here is swallowed and reported
  through `last_error` instead.
- Nothing large is ever written. A snapshot command carries a whole project in its
  parameters, so oversized parameters are replaced by their key names and a length
  rather than being copied into the log.

The hook lives in `MIDIConnection.send_command` for controller commands and in the
piano roll tools for note writes, because those are the two ways a project can change.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any

from fl_studio_mcp.utils.actions import is_mutating, is_mutating_piano_roll
from fl_studio_mcp.utils.store import library_root

# Set to "0" to turn the journal off entirely. A producer who does not want a log
# should not have to delete one.
JOURNAL_ENV = "FL_STUDIO_MCP_JOURNAL"
_OFF = "0"

# Parameters larger than this are replaced by a summary. Chosen to keep a line well
# under a kilobyte in the ordinary case while still recording every fader move.
MAX_PARAM_CHARS = 2000

# How many journal failures to remember for reporting. One is enough to act on; a list
# is kept so a tool can say "seven times".
_MAX_ERRORS = 10

# One id per process, so "what did this session do" is answerable even when the
# journal holds weeks of entries.
_SESSION = uuid.uuid4().hex[:12]

_errors: list[str] = []
_error_count = 0


def is_enabled() -> bool:
    """Whether to record. On unless FL_STUDIO_MCP_JOURNAL is exactly "0"."""
    return os.environ.get(JOURNAL_ENV, "").strip() != _OFF


def session_id() -> str:
    """This process's id, stable for as long as the process lives."""
    return _SESSION


def journal_dir() -> Path:
    """The journal's directory, created if missing."""
    path = library_root() / "journal"
    path.mkdir(parents=True, exist_ok=True)
    return path


def journal_path(when: datetime | date | None = None) -> Path:
    """Today's journal file, or the one for the given day."""
    moment = when or datetime.now()
    return journal_dir() / f"{moment.strftime('%Y-%m-%d')}.jsonl"


def record(
    action: str,
    params: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
    duration_ms: float | None = None,
    *,
    extra: dict[str, Any] | None = None,
) -> None:
    """Append one entry, and never raise.

    Args:
        action: The action name, namespaced the way the tools use it, so controller
            commands look like "mixer.setTrackVolume" and note writes look like
            "piano_roll.add_notes".
        params: What was asked for. Summarised when oversized.
        result: The reply, used for its success flag and its error.
        duration_ms: How long the command took.
        extra: Anything else worth recording, such as the commands a batch carried.
    """
    if not is_enabled():
        return
    try:
        entry: dict[str, Any] = {
            "ts": datetime.now().astimezone().isoformat(),
            "session": _SESSION,
            "action": action,
            "params": _summarise_params(params),
            "ok": bool((result or {}).get("success")),
            "error": (result or {}).get("error"),
        }
        if duration_ms is not None:
            entry["duration_ms"] = round(duration_ms, 3)
        if extra:
            entry.update(extra)
        line = json.dumps(entry, default=str, sort_keys=False)
        with journal_path().open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except Exception as error:  # noqa: BLE001 - a log failure must never propagate
        _remember_error(f"{type(error).__name__}: {error}")


def record_command(
    action: str,
    params: dict[str, Any] | None,
    result: dict[str, Any] | None,
    duration_ms: float,
) -> None:
    """Record a controller command, if it is one that changes anything.

    A batch is expanded rather than labelled: "a batch ran" is not an answer to what
    changed, and the commands it carried are. `system.batch` is deliberately absent
    from the mutating list, because the controller judges the commands inside it
    instead, so the batch case is decided here by looking at what it carries. A batch
    of pure reads, which is how the project description is fetched, records nothing.
    """
    if action == "system.batch" and isinstance(params, dict):
        commands = [
            entry for entry in (params.get("commands") or []) if isinstance(entry, dict)
        ]
        names = [str(entry.get("action")) for entry in commands]
        changes = [name for name in names if is_mutating(name)]
        if not changes:
            return
        record(
            action,
            params,
            result,
            duration_ms,
            extra={
                "commands": names,
                "mutating": changes,
                "count": len(names),
                "name": params.get("name"),
            },
        )
        return

    if not is_mutating(action):
        return
    record(action, params, result, duration_ms)


def record_piano_roll(
    action: str,
    request: dict[str, Any] | None,
    reply: dict[str, Any] | None,
    duration_ms: float,
) -> None:
    """Record a piano roll request, if it is one of the ones that writes notes."""
    if not is_mutating_piano_roll(action):
        return
    record(f"piano_roll.{action}", request, reply, duration_ms)


def read_entries(
    since: datetime | str | None = None,
    action: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Entries newest first, with everything that could not be read counted.

    Args:
        since: Only entries at or after this time. A datetime or an ISO string.
        action: An exact action name, or a namespace ending in a dot, so "mixer."
            asks what the mixer was told to do.
        limit: How many entries to return.

    Returns:
        entries, total, truncated, skipped_lines, and journal_errors, which reports
        failures to write the journal itself.
    """
    if isinstance(since, str):
        since = datetime.fromisoformat(since)
    if since is not None and since.tzinfo is None:
        since = since.astimezone()

    entries: list[dict[str, Any]] = []
    skipped = 0
    for path in sorted(journal_dir().glob("*.jsonl")):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            skipped += 1
            continue
        for line in lines:
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                skipped += 1
                continue
            if not isinstance(entry, dict):
                skipped += 1
                continue
            if not _matches(entry, since, action):
                continue
            entries.append(entry)

    entries.sort(key=lambda entry: str(entry.get("ts") or ""), reverse=True)
    total = len(entries)
    truncated = False
    if limit is not None and limit >= 0 and total > limit:
        entries = entries[:limit]
        truncated = True
    return {
        "entries": entries,
        "total": total,
        "truncated": truncated,
        "skipped_lines": skipped,
        "journal_errors": error_summary(),
    }


def summarise(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Counts a producer can read at a glance: what, how often, what failed."""
    by_action: dict[str, int] = {}
    by_namespace: dict[str, int] = {}
    failed_actions: list[str] = []
    for entry in entries:
        action = str(entry.get("action") or "unknown")
        by_action[action] = by_action.get(action, 0) + 1
        namespace = action.split(".", 1)[0]
        by_namespace[namespace] = by_namespace.get(namespace, 0) + 1
        if entry.get("ok") is False and action not in failed_actions:
            failed_actions.append(action)

    timestamps = [str(entry.get("ts")) for entry in entries if entry.get("ts")]
    return {
        "count": len(entries),
        "by_action": by_action,
        "by_namespace": by_namespace,
        "failures": sum(1 for entry in entries if entry.get("ok") is False),
        "failed_actions": failed_actions,
        "sessions": sorted(
            {str(entry.get("session")) for entry in entries if entry.get("session")}
        ),
        "first": min(timestamps) if timestamps else None,
        "last": max(timestamps) if timestamps else None,
    }


def last_error() -> str | None:
    """The most recent failure to write the journal, if there has been one."""
    return _errors[-1] if _errors else None


def error_summary() -> dict[str, Any]:
    """How many journal failures there have been, and the most recent."""
    return {"count": _error_count, "last": last_error()}


def reset_errors() -> None:
    """Forget recorded failures. Used by tests and by a caller that has fixed the disk."""
    global _error_count
    _errors.clear()
    _error_count = 0


def _matches(entry: dict[str, Any], since: datetime | None, action: str | None) -> bool:
    if since is not None:
        try:
            moment = datetime.fromisoformat(str(entry.get("ts")))
        except ValueError:
            return False
        if moment < since:
            return False
    if action is not None:
        recorded = str(entry.get("action") or "")
        if action.endswith("."):
            if not recorded.startswith(action):
                return False
        elif recorded != action:
            return False
    return True


def _summarise_params(params: dict[str, Any] | None) -> Any:
    """Parameters as they were, or as much of them as is worth writing."""
    if not params:
        return {}
    try:
        text = json.dumps(params, default=str)
    except (TypeError, ValueError):
        return {"_unserialisable": True, "_keys": sorted(map(str, params))}
    if len(text) <= MAX_PARAM_CHARS:
        return params
    return {
        "_truncated": True,
        "_chars": len(text),
        "_keys": sorted(map(str, params)),
    }


def _remember_error(message: str) -> None:
    global _error_count
    _error_count += 1
    _errors.append(message)
    del _errors[:-_MAX_ERRORS]
