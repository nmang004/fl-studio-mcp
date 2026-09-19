"""The journal tools: what did the server do, and how much of it.

Both tools read the host's own files and never talk to FL Studio, so they work with
FL closed. That matters more than it sounds: the question "what did you change" is
usually asked after something went wrong, and the answer should not depend on FL still
being open.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from fl_studio_mcp.utils import journal

if TYPE_CHECKING:
    from fastmcp import FastMCP

# A caller asking for everything is usually a caller who has not thought about the
# size of the answer, so the cap is enforced rather than suggested.
MAX_LIMIT = 500

# "30m", "2h", "7d": the shorthand a producer actually uses when asking what happened.
_WINDOW = re.compile(r"^(\d+)\s*([mhd])$", re.IGNORECASE)


def read_journal(
    since: str | None = None,
    action: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """The recorded edits, newest first.

    Args:
        since: An ISO timestamp, or a window such as "30m", "2h" or "7d".
        action: An exact action, or a namespace ending in a dot, so "mixer." asks
            what the mixer was told to do.
        limit: How many entries to return, capped at MAX_LIMIT.

    Returns:
        entries, how many there were in total, whether the answer was truncated, and
        a note when the journal itself could not be written at some point.
    """
    moment, problem = parse_since(since)
    if problem:
        return {"success": False, "error": problem}

    capped = max(1, min(int(limit), MAX_LIMIT))
    listing = journal.read_entries(since=moment, action=action, limit=capped)
    result: dict[str, Any] = {
        "success": True,
        "entries": listing["entries"],
        "total": listing["total"],
        "truncated": listing["truncated"],
        "limit": capped,
    }
    if not listing["entries"]:
        result["message"] = (
            "No edits have been recorded for that window. A fresh install has never "
            "changed anything, and reads are not recorded."
        )
    if listing["skipped_lines"]:
        result["skipped_lines"] = listing["skipped_lines"]
    if listing["journal_errors"]["count"]:
        # A journal that silently stopped recording would be worse than no journal,
        # because the caller would read an empty answer as "nothing happened".
        result["journal_write_failures"] = listing["journal_errors"]
    return result


def summarise_journal(since: str | None = None) -> dict[str, Any]:
    """Counts by action and namespace, with failures counted separately."""
    moment, problem = parse_since(since)
    if problem:
        return {"success": False, "error": problem}

    listing = journal.read_entries(since=moment, action=None, limit=MAX_LIMIT)
    summary = journal.summarise(listing["entries"])
    summary["success"] = True
    summary["truncated"] = listing["truncated"]
    if listing["truncated"]:
        summary["message"] = (
            f"Only the most recent {MAX_LIMIT} entries were counted, so these numbers "
            "are a floor rather than a total."
        )
    if listing["journal_errors"]["count"]:
        summary["journal_write_failures"] = listing["journal_errors"]
    return summary


def parse_since(since: str | None) -> tuple[datetime | None, str | None]:
    """Turn an ISO timestamp or a window like "2h" into a moment.

    Returns:
        The moment and None, or None and a message naming what was wrong. A caller
        who typed an unparseable window should be told, not handed everything.
    """
    if since is None or since == "":
        return None, None
    text = str(since).strip()

    window = _WINDOW.match(text)
    if window:
        amount = int(window.group(1))
        unit = window.group(2).lower()
        seconds = {"m": 60, "h": 3600, "d": 86400}[unit]
        return datetime.now().astimezone() - timedelta(seconds=amount * seconds), None

    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None, (
            f"Could not read since={since!r}. Use an ISO timestamp such as "
            '"2026-09-19T10:00:00", or a window such as "30m", "2h" or "7d".'
        )
    if moment.tzinfo is None:
        moment = moment.astimezone()
    return moment, None


def register_journal_tools(mcp: FastMCP) -> None:
    """Register the journal tools."""

    @mcp.tool()
    def fl_journal(since: str | None = None, action: str | None = None, limit: int = 50) -> dict:
        """List the edits this server has made, newest first.

        Every command that changed the project, the transport or a window is recorded
        with its parameters, its outcome and how long it took, and so is every note
        write. Reads are not recorded, so an empty answer means nothing was changed
        rather than nothing was asked.

        This reads the host's journal file and never talks to FL Studio, so it works
        with FL closed.

        Args:
            since: An ISO timestamp, or a window such as "30m", "2h" or "7d".
            action: An exact action such as "mixer.setTrackVolume", or a namespace
                    ending in a dot such as "mixer." for everything the mixer was
                    told to do.
            limit: How many entries to return, up to 500.

        Returns:
            entries: newest first, each with ts, action, params, ok, error and
                     duration_ms. A batch entry also names the commands it carried.
            total: how many matched, which may be more than were returned
            truncated: whether the limit cut the answer short
        """
        return read_journal(since=since, action=action, limit=limit)

    @mcp.tool()
    def fl_journal_summary(since: str | None = None) -> dict:
        """Summarise what this server has changed: counts by action and namespace.

        Use this before fl_journal when the question is "how much did you touch"
        rather than "what exactly did you do". Failures are counted separately,
        because a command FL refused is worth knowing about even though nothing
        changed.

        Args:
            since: An ISO timestamp, or a window such as "30m", "2h" or "7d".
        """
        return summarise_journal(since=since)
