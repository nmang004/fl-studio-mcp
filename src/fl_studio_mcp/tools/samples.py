"""Find samples on disk, because FL's browser cannot be searched.

The API has no search, no filter setter and no way to ask a browser node for its path,
so the only honest answer to "where is my kick" is a walk over the folders a producer
actually has. That walk is bounded, and it reports what it looked at rather than only
what it found: a search that examined nothing and a search that examined nine thousand
files and matched nothing would otherwise read the same.

The numbers come from each file's own header, never from its extension. FL's factory
.wav files are Ogg Vorbis in a RIFF container, so they are listed with their codec and
no duration, and a duration filter drops them and says how many it dropped. That is the
whole point: a caller who sees a file with no duration will audition it, and a caller
handed a wrong number will not.
"""

from __future__ import annotations

import time
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fl_studio_mcp.musical import samples as matching
from fl_studio_mcp.utils import audio_meta, paths

if TYPE_CHECKING:
    from fastmcp import FastMCP

DEFAULT_LIMIT = 25

# A caller asking for everything is usually a caller who has not thought about the size
# of the answer, so the cap is enforced rather than suggested.
MAX_LIMIT = 500

# The walk is bounded twice, and both bounds are reported when they are hit. The whole
# sample corpus measured on the machine this was written for is about nine thousand
# files, so the default leaves room for a producer with more, while a folder that turns
# out to be a mounted drive with a million files in it is still answered in a moment.
MAX_FILES = 20000
MAX_DEPTH = 10

# The extensions worth opening. This is a filter on what to describe, not a claim about
# what a file contains: the header decides that, and a file whose bytes are not audio
# comes back unreadable rather than being trusted because of its name.
AUDIO_EXTENSIONS = frozenset(
    {
        ".wav",
        ".aif",
        ".aiff",
        ".aifc",
        ".flac",
        ".ogg",
        ".opus",
        ".wv",
        ".caf",
        ".mp3",
        ".m4a",
        ".aac",
        ".wma",
    }
)


def find_samples(
    query: str | None = None,
    folder: str | Path | None = None,
    formats: list[str] | None = None,
    min_seconds: float | None = None,
    max_seconds: float | None = None,
    limit: int = DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Search the sample folders for audio files.

    Args:
        query: Matched case-insensitively against the file name and its folder path.
        folder: One folder to search instead of the default roots.
        formats: Extensions or format names, such as ["wav", "flac"].
        min_seconds: Keep only files at least this long.
        max_seconds: Keep only files at most this long.
        limit: How many results to return, up to MAX_LIMIT.

    Returns:
        The results as summaries, the roots that were searched, the folders that were
        asked for and not there, how many files were examined, how many were skipped
        and why, whether either walk bound was hit, and how long it took. A folder that
        does not exist is reported in `missing` rather than raised, because a fresh
        machine has none of these.
    """
    started = time.perf_counter()
    roots, missing = _roots(folder)
    state = _new_state()
    matched: list[dict[str, Any]] = []
    duration_wanted = min_seconds is not None or max_seconds is not None

    for root in roots:
        for path in _iter_files(root, state):
            if path.suffix.lower() not in AUDIO_EXTENSIONS:
                state["not_audio"] += 1
                continue
            info = audio_meta.read_audio_info(path)
            if not info.get("format"):
                state["unreadable_header"] += 1
                continue
            # The name and format filters run first, so the count below is of files the
            # caller actually asked about: telling someone filtering for wav that six
            # thousand WavPack files were left out would be noise, not honesty.
            if not matching.matches(info, query=query, formats=formats, path=path):
                continue
            if not matching.matches(info, min_seconds=min_seconds, max_seconds=max_seconds):
                if duration_wanted and info.get("duration") is None:
                    # `matches` excludes an unmeasured file rather than guessing that it
                    # fits. It is counted here because "left out because nobody measured
                    # it" is a different answer from "not the length you asked for".
                    state["unknown_duration"] += 1
                continue
            entry = dict(info)
            entry["path"] = str(path)
            entry["name"] = path.name
            entry["folder"] = str(path.parent)
            matched.append(entry)

        if state["file_limit_reached"] or state["depth_limit_reached"]:
            break

    ranked = matching.rank(matched, query)
    capped = max(1, min(int(limit), MAX_LIMIT))
    page = ranked[:capped]
    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
    unmeasured = sum(1 for entry in page if entry.get("duration") is None)

    result: dict[str, Any] = {
        "success": True,
        "samples": [matching.summarise(entry) for entry in page],
        "total": len(ranked),
        "returned": len(page),
        "truncated": len(ranked) > len(page),
        "limit": capped,
        "roots": [str(root) for root in roots],
        "missing": [str(path) for path in missing],
        "examined": state["examined"],
        "skipped": {
            "not_audio": state["not_audio"],
            "unreadable_header": state["unreadable_header"],
            "unknown_duration": state["unknown_duration"],
        },
        "unmeasured": unmeasured,
        "walk": {
            "max_files": state["max_files"],
            "max_depth": state["max_depth"],
            "file_limit_reached": state["file_limit_reached"],
            "depth_limit_reached": state["depth_limit_reached"],
        },
        "elapsed_ms": elapsed_ms,
    }
    if state["unreadable_folders"]:
        result["unreadable_folders"] = state["unreadable_folders"]
    result["message"] = _message(
        roots=roots,
        missing=missing,
        state=state,
        matched=len(ranked),
        returned=len(page),
        capped=capped,
        unmeasured=unmeasured,
        duration_wanted=duration_wanted,
    )
    return result


def _roots(folder: str | Path | None) -> tuple[list[Path], list[Path]]:
    """The folders to walk, and the ones that were asked for but are not there."""
    asked = [Path(folder).expanduser()] if folder else paths.sample_roots()
    roots: list[Path] = []
    missing: list[Path] = []
    for path in asked:
        if path.is_dir():
            roots.append(path)
        else:
            missing.append(path)
    return roots, missing


def _new_state() -> dict[str, Any]:
    """The walk's counters, read from the module so a test can lower the bounds."""
    return {
        "examined": 0,
        "not_audio": 0,
        "unreadable_header": 0,
        "unknown_duration": 0,
        "file_limit_reached": False,
        "depth_limit_reached": False,
        "unreadable_folders": [],
        "max_files": MAX_FILES,
        "max_depth": MAX_DEPTH,
    }


def _iter_files(root: Path, state: dict[str, Any]):
    """Yield the files under one root, stopping at the walk's two bounds.

    Breadth first, with the entries of each folder sorted, so the same folder answers
    the same way twice and the files nearest a root are examined first. A directory that
    cannot be listed is recorded in the state and stepped over: one unreadable folder
    must not end a search that has other roots to try.
    """
    queue: deque[tuple[Path, int]] = deque([(root, 0)])
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
            yield entry


def _message(
    *,
    roots: list[Path],
    missing: list[Path],
    state: dict[str, Any],
    matched: int,
    returned: int,
    capped: int,
    unmeasured: int,
    duration_wanted: bool,
) -> str:
    """The sentence a caller reads first, including everything that limits it."""
    if not roots:
        sentence = "No sample folder was searched."
    else:
        sentence = (
            f"Examined {state['examined']} file(s) in {len(roots)} folder(s), matched "
            f"{matched} and returned {returned}."
        )

    if missing:
        sentence += " Not found: " + ", ".join(str(path) for path in missing) + "."
    if state["unreadable_folders"]:
        names = ", ".join(item["path"] for item in state["unreadable_folders"])
        sentence += f" Could not list: {names}."
    if not roots:
        sentence += (
            " Set FL_STUDIO_MCP_SAMPLE_DIRS to the folders to use, separated by the "
            "platform's path separator, or pass one folder, or install FL Studio, Logic "
            "or GarageBand content."
        )
    elif state["examined"] == 0:
        sentence += " Nothing was examined, so the folders are there but hold no files."
    if returned < matched:
        sentence += f" The limit of {capped} cut the list short; the total is {matched}."
    if state["unknown_duration"]:
        sentence += (
            f" {state['unknown_duration']} file(s) were left out because a duration filter "
            "was given and their duration could not be measured. They are not being "
            "guessed at: search again without min_seconds or max_seconds to see them."
        )
    if unmeasured and not duration_wanted:
        sentence += (
            f" {unmeasured} of the results have no measurable duration, so a duration "
            "filter would exclude them."
        )
    if state["file_limit_reached"]:
        sentence += (
            f" The walk stopped after {state['max_files']} files, so this answer is "
            "incomplete: search one folder, or a narrower query, to see the rest."
        )
    if state["depth_limit_reached"]:
        sentence += (
            f" The walk stopped {state['max_depth']} folder level(s) below a root, so "
            "deeper folders were not searched."
        )
    return sentence.strip()


def register_sample_tools(mcp: FastMCP) -> None:
    """Register the sample search tool."""

    @mcp.tool()
    def fl_find_samples(
        query: str | None = None,
        folder: str | None = None,
        formats: list[str] | None = None,
        min_seconds: float | None = None,
        max_seconds: float | None = None,
        limit: int = DEFAULT_LIMIT,
    ) -> dict:
        """Find audio files in FL's factory packs and the usual sample folders.

        FL's browser cannot be searched through its API, so this walks the folders on
        disk instead: the FL user folders, the factory packs inside an installed copy of
        FL Studio (discovered, because the folder name carries the release year), Apple
        Loops, Logic and GarageBand, each only when it exists. Set
        FL_STUDIO_MCP_SAMPLE_DIRS to a path-separated list to search somewhere else, or
        pass one folder to search only that.

        Every file is described from its own header, not from its extension: FL's factory
        .wav files are Ogg Vorbis inside a RIFF container, so they are listed with their
        codec and no duration rather than a duration that would be wrong. min_seconds and
        max_seconds therefore drop files whose duration is unknown, and the reply says
        how many were dropped for that reason.

        Args:
            query: Matched case-insensitively against the file name and its folder path.
            folder: One folder to search instead of the default roots.
            formats: Extensions or format names, such as ["wav", "flac"]. Case is
                     ignored, so "wav" matches a file called KICK.WAV.
            min_seconds: Keep only files at least this long.
            max_seconds: Keep only files at most this long.
            limit: How many results to return, up to 500.

        Returns:
            samples: one row per file, with its path, format, codec, rate, channels,
                     bits and duration, plus a reason when a number could not be
                     measured.
            total: how many matched, which may be more than were returned.
            roots, missing, examined, skipped, walk, elapsed_ms: what was searched, what
                     was not there, how much was looked at, and whether a walk bound cut
                     the search short.
        """
        return find_samples(
            query=query,
            folder=folder,
            formats=formats,
            min_seconds=min_seconds,
            max_seconds=max_seconds,
            limit=limit,
        )
