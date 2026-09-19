"""Musical context: the project's key, scale and meter.

The facts live in the piano roll sandbox, on `flpianoroll.score`, and nowhere else.
The controller cannot see the key or the meter at all, which is worth knowing
because it is the opposite of what the roadmap assumed.

What this layer adds is meaning: the helper string becomes scale degrees, the root
turns those into a named key, and the meter becomes beats per bar.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fl_studio_mcp.musical import bassline as bassline_module
from fl_studio_mcp.musical import score
from fl_studio_mcp.tools import piano_roll
from fl_studio_mcp.utils.connection import get_connection

if TYPE_CHECKING:
    from fastmcp import FastMCP


def read_context(request_timeout: float = 5.0) -> dict[str, Any]:
    """Read the key and meter by asking the piano roll script.

    This goes through the real transport rather than loading the script directly.
    An earlier version imported the script with a helper from the test suite, which
    meant the shipped code could not run outside a test at all: `from tests.helpers`
    raised ModuleNotFoundError the first time it was called for real.
    """
    return piano_roll.send_request(
        {"action": "get_context", "id": CONTEXT_REQUEST_ID},
        timeout=request_timeout,
        wait_for_manual_trigger=request_timeout,
    )


def get_project_context() -> dict[str, Any]:
    """The key, scale, meter and timebase of the open project.

    Returns:
        key, root_note, in_scale: the scale as semitone offsets from the root
        time_signature, beats_per_bar: the project meter
        ppq: ticks per quarter note, from the controller
    """
    reply = read_context()
    context = score.context_from_reply(reply)

    # The controller owns the PPQ, because a caller may want it without having run
    # a piano roll script at all.
    reply = get_connection().send_command("system.getPpq", timeout=5.0)
    if reply.get("ppq") is not None:
        context["ppq"] = reply["ppq"]
    return context


def write_bassline(
    channel: int,
    pattern: str = "x-x-xx--",
    bars: int = 1,
    octave: int = 2,
    articulation: str = "slide",
    root: int | None = None,
    verify: bool = True,
) -> dict[str, Any]:
    """Write a bassline into a channel, in the project's key and meter.

    One call does the whole job: read the key and meter, work out the notes, target
    the channel, write them, and read them back. That is the point of this layer, and
    it is the difference between a wrapper and a musical tool.

    Args:
        channel: Channel Rack index to write into.
        pattern: One character per subdivision, `x` for a note.
        bars: How many bars to fill.
        octave: Which octave the root sits in. 2 is a normal bass register.
        articulation: "slide", "porta" or "none".
        root: Override the root as a pitch class. By default the project's own key is
            used, which is what a producer means by "write me a bassline".
        verify: Read the notes back and confirm they landed.

    Returns:
        The notes written, the key and meter they were written in, and the channel.
    """
    context = get_project_context()
    beats_per_bar = context.get("beats_per_bar") or 4.0
    degrees = context.get("in_scale")

    root_pitch = root if root is not None else (context.get("root_note") or 0)
    root_midi = (octave + 1) * 12 + (int(root_pitch) % 12)

    notes = bassline_module.bassline(
        root_midi,
        pattern=pattern,
        bars=bars,
        octave=octave,
        scale=degrees,
        articulation=articulation,
        beats_per_bar=beats_per_bar,
    )

    result = piano_roll.send_request(
        {"action": "add_notes", "notes": notes, "group": True, "group_name": "bassline"},
        channel=channel,
        verify=verify,
    )

    if not result.get("success"):
        return {
            "success": False,
            "error": result.get("error"),
            "key": context.get("key"),
            "time_signature": context.get("time_signature"),
        }

    return {
        "success": True,
        "channel": channel,
        "channel_name": result.get("target_channel_name"),
        "key": context.get("key"),
        "time_signature": context.get("time_signature"),
        "beats_per_bar": beats_per_bar,
        "pattern": pattern,
        "bars": bars,
        "articulation": articulation,
        "group": result.get("group"),
        "notes_written": len(notes),
        "notes_read_back": result.get("verified_notes"),
        "notes": notes,
    }


CONTEXT_REQUEST_ID = "project-context"


def register_score_tools(mcp: FastMCP) -> None:
    """Register the musical context and bassline tools."""

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


    @mcp.tool()
    def fl_write_bassline(
        channel: int,
        pattern: str = "x-x-xx--",
        bars: int = 1,
        octave: int = 2,
        articulation: str = "slide",
        root: int | None = None,
        verify: bool = True,
    ) -> dict:
        """Write a bassline into a channel, in the project's own key and meter.

        Use this instead of working out pitches and times yourself. It reads the
        project's key from the piano roll's snap to scale and the meter from the
        project settings, so the line fits the track rather than a generic C major
        4/4, and it writes the slide articulation that makes a bassline move instead
        of pulse.

        Args:
            channel: Channel Rack index to write into.
            pattern: One character per subdivision, `x` for a note and `-` for a
                     rest, for example "x-x-xx--" or "x--x--x-".
            bars: How many bars to fill. The pattern repeats.
            octave: Register. 2 is a normal bass octave, where C is MIDI 36.
            articulation: "slide" for FL slide notes, "porta" for portamento, or
                          "none". Slide is the default because it is what makes an
                          acid line sound alive.
            root: Override the root as a pitch class, where C is 0. By default the
                  project's own key is used.
            verify: Read the notes back and confirm they landed. On by default here,
                    unlike the lower level tools, because this is the call whose whole
                    purpose is to put a part in the project.

        Returns:
            key, time_signature: what the line was written in
            notes_written, notes_read_back: what was sent and what FL holds
            group: the note group, so the phrase can be removed exactly later
        """
        return write_bassline(
            channel,
            pattern=pattern,
            bars=bars,
            octave=octave,
            articulation=articulation,
            root=root,
            verify=verify,
        )
