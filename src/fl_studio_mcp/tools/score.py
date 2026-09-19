"""Musical context: the project's key, scale and meter.

The facts live in the piano roll sandbox, on `flpianoroll.score`, and nowhere else.
The controller cannot see the key or the meter at all, which is worth knowing
because it is the opposite of what the roadmap assumed.

What this layer adds is meaning: the helper string becomes scale degrees, the root
turns those into a named key, and the meter becomes beats per bar.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fl_studio_mcp.musical import score
from fl_studio_mcp.utils.connection import get_connection

if TYPE_CHECKING:
    from fastmcp import FastMCP


def piano_roll_script() -> Any:
    """The piano roll script, loaded so its context can be read.

    Kept behind a function so a test can substitute one, and so the import cost is
    only paid when context is actually wanted.
    """
    from tests.helpers import load_pyscript

    class _NoPatch:
        def setitem(self, *args, **kwargs):
            pass

    return load_pyscript(_NoPatch())


def get_project_context() -> dict[str, Any]:
    """The key, scale, meter and timebase of the open project.

    Returns:
        key, root_note, in_scale: the scale as semitone offsets from the root
        time_signature, beats_per_bar: the project meter
        ppq: ticks per quarter note, from the controller
    """
    from fl_studio_mcp.utils.paths import piano_roll_scripts_dir

    scripts = piano_roll_scripts_dir()
    context = score.read_context(
        piano_roll_script(),
        scripts / "mcp_response.json",
        scripts / "mcp_request.json",
    )

    # The controller owns the PPQ, because a caller may want it without having run
    # a piano roll script at all.
    reply = get_connection().send_command("system.getPpq", timeout=5.0)
    if reply.get("ppq") is not None:
        context["ppq"] = reply["ppq"]
    return context


def register_score_tools(mcp: FastMCP) -> None:
    """Register the musical context tool."""

    @mcp.tool()
    def fl_get_project_context() -> dict:
        """Read the project's key, scale and meter.

        Call this before generating anything. The project's key is whatever the
        producer set in the piano roll's snap to scale, and assuming C major is the
        fastest way to write notes that sound wrong in their track.

        Returns:
            key: a name, for example "A minor"
            root_note: the root as a MIDI pitch class, where C is 0
            in_scale: semitone offsets from the root, so 0 is the root and 3 is a
                       minor third
            time_signature: for example "3/4"
            beats_per_bar: how many quarter notes a bar holds, so 6/8 gives 3.0
            ppq: ticks per quarter note
        """
        return get_project_context()
