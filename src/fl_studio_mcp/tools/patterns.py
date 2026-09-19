"""Patterns: FL's unit of work.

A pattern is not a track and not a clip. It is the thing a producer writes into,
and it is what the Channel Rack's step sequencer and the piano roll both edit. A
generic DAW tool has no equivalent, which is why it tends to ignore them.

The upstream README claimed patterns cannot be created. That is wrong:
patterns.findFirstNextEmptyPat exists in the stubs, and selecting the next empty
slot and writing into it is creation in practice.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fl_studio_mcp.utils.connection import get_connection

if TYPE_CHECKING:
    from fastmcp import FastMCP


def get_patterns() -> dict[str, Any]:
    """Every pattern in the project, with its properties."""
    return get_connection().send_command("patterns.getAll", timeout=5.0)


def set_pattern(
    index: int,
    name: str | None = None,
    color: int | None = None,
    select: bool = False,
    clone: bool = False,
) -> dict[str, Any]:
    """Change a pattern. One action per call."""
    actions = [
        label
        for label, chosen in (
            ("name", name is not None),
            ("color", color is not None),
            ("select", select),
            ("clone", clone),
        )
        if chosen
    ]
    if not actions:
        return {
            "success": False,
            "error": (
                "Nothing to do: give at least one of name, color, select or clone."
            ),
        }
    if len(actions) > 1:
        return {
            "success": False,
            "error": (
                f"One action per call, but got {', '.join(actions)}. Do them in "
                "separate calls so each result describes one change."
            ),
        }

    connection = get_connection()
    if clone:
        reply = connection.send_command("patterns.clone", {"index": index}, timeout=5.0)
        if reply.get("success"):
            reply["message"] = f"Cloned pattern {index} to {reply.get('cloned')}."
        return reply
    if select:
        reply = connection.send_command("patterns.select", {"index": index}, timeout=5.0)
        if reply.get("success"):
            reply["message"] = f"Pattern {index} is now current."
        return reply
    if name is not None:
        reply = connection.send_command(
            "patterns.setName", {"index": index, "name": name}, timeout=5.0
        )
        if reply.get("success"):
            reply["message"] = f"Renamed pattern {index} to {reply.get('name')!r}."
        return reply
    reply = connection.send_command(
        "patterns.setColor", {"index": index, "color": color}, timeout=5.0
    )
    if reply.get("success"):
        reply["message"] = f"Recoloured pattern {index}."
    return reply


def create_pattern(name: str = "") -> dict[str, Any]:
    """Select the next empty pattern, creating a slot if every one is used."""
    params: dict[str, Any] = {}
    if name:
        params["name"] = name
    reply = get_connection().send_command("patterns.createEmpty", params, timeout=5.0)
    if reply.get("success"):
        if reply.get("was_existing"):
            reply["message"] = (
                f"Pattern {reply.get('created')} ({reply.get('name')!r}) is empty "
                "and is now current. Write into it, or pass a name to a new one."
            )
        else:
            reply["message"] = (
                f"Created pattern {reply.get('created')} ({reply.get('name')!r}) "
                "and made it current."
            )
    return reply


def register_pattern_tools(mcp: FastMCP) -> None:
    """Register pattern tools with the MCP server."""

    @mcp.tool()
    def fl_get_patterns() -> dict:
        """List every pattern in the FL Studio project.

        A pattern is FL's unit of work: it holds the notes and the step sequence
        that the Channel Rack and the piano roll edit. There is no equivalent in
        other DAWs, so this is the call that tells you what the project actually
        contains rather than what the mixer looks like.

        Returns:
            patterns: one entry per pattern, each with its index, name, colour,
                      length in steps, whether it is an untouched default, and
                      whether it is the current one
            current: the index of the current pattern, which is what the piano
                     roll and the step sequencer are editing
        """
        return get_patterns()

    @mcp.tool()
    def fl_set_pattern(
        index: int,
        name: str | None = None,
        color: int | None = None,
        select: bool = False,
        clone: bool = False,
    ) -> dict:
        """Rename, recolour, select or clone a pattern.

        One action per call, so the result describes exactly one change.

        Args:
            index: Pattern index, as reported by fl_get_patterns.
            name: New name for the pattern. Worth setting, because a project full
                  of "Pattern 3" tells the user nothing.
            color: Colour as 0xRRGGBB.
            select: Make this the current pattern, which is what the piano roll
                    and the step sequencer will then edit.
            clone: Copy this pattern and make the copy current. Ignores name,
                   color and select.
        """
        return set_pattern(index, name=name, color=color, select=select, clone=clone)

    @mcp.tool()
    def fl_create_pattern(name: str = "") -> dict:
        """Make a new, empty pattern current.

        Selects the next empty pattern, creating a slot if every one is already
        used. Call this before writing a new part so the notes go somewhere
        intentional rather than on top of an existing idea.

        Calling it twice returns the same pattern, because a pattern with no notes
        is still empty. It will not rename an existing pattern.

        Args:
            name: What to call a newly created pattern. Ignored when an existing
                  empty pattern is reused, so a name the user already chose is
                  never overwritten.
        """
        return create_pattern(name)
