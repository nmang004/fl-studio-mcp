"""Sample matching: which files answer a search, and in what order.

These are the decisions a sample search makes, kept as arithmetic over header
dictionaries so they are testable without a filesystem. The walk, the library root and
the tool's reply shape live in `tools/samples.py`; this module never touches a disk.

A duration filter is the one place where the answer can be unknown rather than simply
wrong. A file whose header does not give a length is excluded rather than assumed to
fit, because including it on a guess would put a file in an answer where the caller
asked for files of a particular length.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def matches(
    info: dict[str, Any],
    query: str | None = None,
    formats: list[str] | tuple[str, ...] | str | None = None,
    min_seconds: float | None = None,
    max_seconds: float | None = None,
    path: str | Path | None = None,
) -> bool:
    """Whether one file, described by its header, answers a search.

    Args:
        info: What `utils.audio_meta.read_audio_info` measured.
        query: A case-insensitive substring of the file name or of its folder path.
        formats: Extensions or format names, with or without a leading dot. A file is
            matched on the format its bytes declare and on its extension, so a FLAC
            named .wav answers to both rather than disappearing from each.
        min_seconds: Keep only files at least this long.
        max_seconds: Keep only files at most this long.
        path: The file's path. The info dictionary may carry its own "path" key; this
            argument wins when both are given.

    Returns:
        True when every filter given passes. A filter that was not given narrows
        nothing. A duration filter excludes a file whose duration is unknown rather
        than guessing that it fits.
    """
    source = str(path or info.get("path") or "")
    name = source.replace("\\", "/").rsplit("/", 1)[-1] if source else str(info.get("name") or "")

    if query:
        needle = str(query).strip().lower()
        if needle and needle not in f"{name}\n{source}".lower():
            return False

    if formats:
        wanted = _wanted_formats(formats)
        if wanted:
            detected = str(info.get("format") or "").lower()
            suffix = name.rsplit(".", 1)[-1].lower() if "." in name else ""
            if detected not in wanted and suffix not in wanted:
                return False

    duration = info.get("duration")
    if min_seconds is not None:
        if duration is None or float(duration) < float(min_seconds):
            return False
    if max_seconds is not None:
        if duration is None or float(duration) > float(max_seconds):
            return False
    return True


def rank(entries: list[dict[str, Any]], query: str | None = None) -> list[dict[str, Any]]:
    """Best match first: a file whose name answers the query beats one whose folder did.

    A producer who types "kick" means the file called kick, not the folder called kicks,
    so a name match sorts above a folder match and the obvious answer survives a capped
    list. Ties fall back to the file name, so two runs over the same folder answer in
    the same order.
    """
    needle = str(query or "").strip().lower()

    def order(entry: dict[str, Any]) -> tuple[int, str]:
        name = str(entry.get("name") or _name_of(entry) or "").lower()
        if not needle or needle in name:
            return (0, name)
        if needle in str(entry.get("path") or "").lower():
            return (1, name)
        return (2, name)

    return sorted(entries, key=order)


def summarise(entry: dict[str, Any]) -> dict[str, Any]:
    """A result row: what a caller needs to choose a file, and why a number is missing.

    The reason is carried per row rather than once for the reply, because a factory .wav
    with no duration and a WavPack file with no duration need different explanations and
    a caller reads one row at a time.
    """
    row: dict[str, Any] = {
        "name": entry.get("name") or _name_of(entry),
        "path": entry.get("path"),
        "folder": entry.get("folder") or _folder_of(entry),
        "format": entry.get("format"),
        "codec": entry.get("codec"),
        "sample_rate": entry.get("sample_rate"),
        "channels": entry.get("channels"),
        "bits": entry.get("bits"),
        "duration": _seconds(entry.get("duration")),
        "readable": bool(entry.get("readable")),
    }
    if entry.get("reason"):
        row["reason"] = entry["reason"]
    return row


def _wanted_formats(formats: list[str] | tuple[str, ...] | str) -> set[str]:
    """The filter as a set of bare, lower case names: ".WAV" and "wav" are one thing."""
    if isinstance(formats, str):
        formats = [formats]
    return {str(item).strip().lower().lstrip(".") for item in formats if str(item).strip()}


def _seconds(value: Any) -> float | None:
    """A duration rounded for display, or None when it was not measured."""
    return None if value is None else round(float(value), 3)


def _name_of(entry: dict[str, Any]) -> str | None:
    path = entry.get("path")
    return Path(path).name if path else None


def _folder_of(entry: dict[str, Any]) -> str | None:
    path = entry.get("path")
    return str(Path(path).parent) if path else None
