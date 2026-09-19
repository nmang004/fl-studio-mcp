"""The project's key, scale and meter.

Read from the piano roll sandbox, because that is where FL puts them. The roadmap
lists `score.snap_root_note` and `score.tsnum` as controller sources; they are
properties of `flpianoroll.score`, which exists only in the piano roll script's
sandbox. The controller cannot see them at all.

`snap_scale_helper` is the awkward one. It is a string of twelve 0 and 1 values
separated by commas, always aligned to C, where 0 means the note is in the scale and
1 means it is out. It is not an index, not an enum, and not a bitmask.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

NOTE_NAMES = (
    "C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B",
)

SCALE_LENGTH = 12


def scale_degrees(helper: str) -> list[int]:
    """The semitones in the scale, from the C-aligned helper string.

    Args:
        helper: The value of `score.snap_scale_helper`, for example
            "0,1,0,1,0,0,1,0,1,0,1,0" for C major.

    Returns:
        Semitone offsets from C, ascending.

    Raises:
        ValueError: If the helper is not twelve values of 0 or 1, or if it marks
            every note as out of scale, which cannot describe a scale.
    """
    parts = [part.strip() for part in str(helper).split(",")]
    if len(parts) != SCALE_LENGTH:
        raise ValueError(
            f"snap_scale_helper must hold {SCALE_LENGTH} values, got {len(parts)}: "
            f"{helper!r}"
        )
    for part in parts:
        if part not in ("0", "1"):
            raise ValueError(
                f"snap_scale_helper values must be 0 or 1, got {part!r} in {helper!r}"
            )

    degrees = [index for index, part in enumerate(parts) if part == "0"]
    if not degrees:
        raise ValueError(
            f"snap_scale_helper marks every note out of scale, which is not a scale: "
            f"{helper!r}"
        )
    return degrees


def is_minor(degrees: list[int], root_note: int = 0) -> bool:
    """Whether a scale is minor, from the interval pattern.

    A minor scale has a minor third above its root, which is three semitones, and a
    major scale has four.

    Note that the helper string is always C-aligned, so the root is not necessarily
    the first entry: A minor as C, D, E, F, G, A, B starts at index 9, and its third
    is the note two positions along, not two semitones along. Reading the third from
    `degrees[2]` would call A minor a major key, which is exactly the mistake this
    docstring exists to prevent.
    """
    if len(degrees) < 3:
        return False
    root = int(root_note) % SCALE_LENGTH
    if root not in degrees:
        return False
    start = degrees.index(root)
    third = degrees[(start + 2) % len(degrees)]
    return (third - root) % SCALE_LENGTH == 3


def rooted_degrees(degrees: list[int], root_note: int) -> list[int]:
    """The scale as semitone offsets from the root, ascending from 0.

    The API reports absolute semitones from C, so A minor arrives as 9, 11, 0, 2, 4,
    5, 7. A caller reasoning about A minor wants 0, 2, 3, 5, 7, 8, 10, where 0 is the
    root and 3 is its minor third.

    Rotating the list is not enough: rotating gives 9, 11, 0, 2, 4, 5, 7, whose
    numbers are still absolute, so the third entry reads as 0 rather than as a minor
    third. The offsets have to be recomputed, which is what this does. An earlier
    version returned the rotation and would have made every chord and bassline
    computed from it wrong.
    """
    root = int(root_note) % SCALE_LENGTH
    if root not in degrees:
        return list(degrees)
    start = degrees.index(root)
    rotated = degrees[start:] + degrees[:start]
    return [(degree - root) % SCALE_LENGTH for degree in rotated]


def key_name(root_note: int, helper: str) -> str:
    """A name for the project's key, for a caller to read and reason about."""
    root = int(root_note) % SCALE_LENGTH
    degrees = scale_degrees(helper)
    quality = "minor" if is_minor(degrees, root) else "major"
    return f"{NOTE_NAMES[root]} {quality}"


def context_from_reply(reply: dict[str, Any]) -> dict[str, Any]:
    """The key, scale and meter from a get_context reply.

    The script echoes every response keyed by id, so the context is looked up by the
    id it was asked for rather than taken from whichever response came first. A
    context read queued alongside a write otherwise returns the write's answer, which
    carries no key at all.
    """
    entry = reply
    for candidate in reply.get("responses") or []:
        if candidate.get("root_note") is not None or candidate.get("scale_helper"):
            entry = candidate
            break
    return _context_from_fields(entry)


def read_context(
    piano_roll_script: Any, response_file: Any = None, request_file: Any = None
) -> dict[str, Any]:
    """The key, scale and meter, read from the piano roll script.

    Args:
        piano_roll_script: The loaded ComposeWithLLM module, or a fake of it, whose
            `apply()` runs one request and writes a reply.
        response_file: Where the script writes its reply. Defaults to the real
            settings directory, and tests pass their own.
        request_file: Where to queue the context request. Defaults to the real
            settings directory, and tests pass their own.

    Returns:
        root_note, scale_helper, in_scale, tsnum, tsden, ppq and the derived
        time_signature, beats_per_bar and key.
    """
    import json as _json
    from pathlib import Path as _Path

    if request_file is None:
        from fl_studio_mcp.utils.paths import piano_roll_scripts_dir

        request_file = piano_roll_scripts_dir() / "mcp_request.json"
    _Path(request_file).write_text(
        _json.dumps([{"action": "get_context", "id": "context"}])
    )

    piano_roll_script.apply()
    reply = _last_reply(response_file)
    return context_from_reply(reply)


def _context_from_fields(reply: dict[str, Any]) -> dict[str, Any]:
    """Build the context from a reply that carries the raw fields."""
    helper = reply.get("scale_helper")
    root = reply.get("root_note")
    tsnum = reply.get("tsnum") or 4
    tsden = reply.get("tsden") or 4

    context: dict[str, Any] = {
        "root_note": root,
        "scale_helper": helper,
        "tsnum": tsnum,
        "tsden": tsden,
        # The two reply shapes name this differently: the top level field carries
        # the context prefix to avoid colliding with the transport's own fields,
        # while a per response entry is just ppq. Reading only one of them left the
        # value None depending on which shape arrived.
        "ppq": reply.get("context_ppq") if reply.get("context_ppq") is not None
        else reply.get("ppq"),
        "time_signature": f"{tsnum}/{tsden}",
        "beats_per_bar": _beats_per_bar(tsnum, tsden),
    }
    if helper is not None:
        degrees = scale_degrees(helper)
        # C-aligned, exactly as the API reports it, so a caller can check the
        # translation.
        context["c_aligned_degrees"] = degrees
        if root is not None:
            # Rotated so the first entry is the root, which is the form musical
            # code wants and the form the chord and bassline work reads.
            context["in_scale"] = rooted_degrees(degrees, root)
            context["key"] = key_name(root, helper)
    return context


def _beats_per_bar(tsnum: int, tsden: int) -> float:
    """How many quarter notes a bar holds.

    A 4/4 bar is four quarter notes. A 6/8 bar is six eighth notes, which is three
    quarter notes, and getting that wrong would put every bar line in the wrong
    place for anything not in a x/4 meter.
    """
    if not tsden:
        return float(tsnum)
    return tsnum * (4.0 / tsden)


def _last_reply(response_file: Any = None) -> dict[str, Any]:
    """Read the reply the script just wrote."""
    import json

    if response_file is None:
        from fl_studio_mcp.utils.paths import piano_roll_scripts_dir

        response_file = piano_roll_scripts_dir() / "mcp_response.json"
    try:
        return json.loads(Path(response_file).read_text())
    except Exception:
        return {}
