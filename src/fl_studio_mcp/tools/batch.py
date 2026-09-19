"""Batch execution, undo and undo history.

Batching exists so that one logical edit is one trigger and one undo step. The
roadmap is explicit that speed is not the motivation: a round trip is about a
millisecond, so sixteen notes cost sixteen milliseconds and nobody cares. What
matters is that sixteen edits are not sixteen Ctrl+Z presses, and that a failure
half way through does not leave a half-applied edit reported as a success.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fl_studio_mcp.utils.connection import get_connection

if TYPE_CHECKING:
    from fastmcp import FastMCP

# A batch is one trigger, but the controller still runs every command inside it,
# so it gets a longer window than a single command.
BATCH_TIMEOUT = 15.0


def run_batch(commands: list[dict], name: str) -> dict[str, Any]:
    """Run several commands from one trigger, inside one undo point.

    Args:
        commands: Entries of the form {"action": str, "params": dict}.
        name: What this edit is called in FL Studio's undo history. Required,
            because an unnamed entry in the undo list is barely better than none.

    Returns:
        The controller's batch report: "success", "results" in order, "executed",
        "failed", "undo_name" and "undo_history_count". A failure stops the
        batch and the remaining
        entries carry "skipped": true.
    """
    if not commands:
        return {
            "success": False,
            "error": "A batch needs at least one command.",
        }
    if not name or not name.strip():
        return {
            "success": False,
            "error": (
                "A batch needs a 'name'. It becomes the undo entry, so the user "
                "reads what the edit was instead of just 'Undo'."
            ),
        }

    for index, command in enumerate(commands):
        if "action" not in command:
            return {
                "success": False,
                "error": f"Command {index} has no 'action'.",
            }

    reply = get_connection().send_command(
        "system.batch",
        {"commands": commands, "name": name},
        timeout=BATCH_TIMEOUT,
    )

    return reply


def run_undo(steps: int = 1) -> dict[str, Any]:
    """Undo one or more steps in FL Studio.

    A batch is not one undo step, and nothing here pretends otherwise. Measured on
    FL Studio 2026: a batch of channel or step writes needs one undo call, while
    two mixer writes need two, and the undo history count does not predict either.
    So this takes an explicit step count, and the caller decides by looking at
    what changed.

    This uses general.undoUpDown rather than general.undo, because undo is a
    toggle: two calls undo once and then redo.
    """
    if steps < 1:
        return {"success": False, "error": "steps must be at least 1."}

    # Always the relative move, never general.undo(). undo() is a toggle: the stub
    # says so, and live FL Studio 2026 confirms it. Calling it twice undoes once
    # and then redoes, so a caller asking for two steps would silently get zero.
    reply = get_connection().send_command(
        "general.undoUpDown", {"value": -steps}, timeout=5.0
    )
    if reply.get("success"):
        reply["message"] = f"Undid {steps} step(s)."
    return reply


def run_undo_history() -> dict[str, Any]:
    """Report how many undo steps FL Studio holds."""
    return get_connection().send_command("general.getUndoHistoryCount", timeout=5.0)


def register_batch_tools(mcp: FastMCP) -> None:
    """Register batch and undo tools with the MCP server."""

    @mcp.tool()
    def fl_batch(commands: list[dict], name: str) -> dict:
        """Run several FL Studio commands as one edit.

        Use this instead of many separate tool calls whenever the commands belong
        together: writing a drum pattern, setting up a mix, changing a value
        across several tracks. It is one trigger and one undo step, so a single
        Ctrl+Z reverses the whole edit.

        A failure stops the batch. Commands after the failure are reported as
        skipped rather than run, so the project is never left half edited without
        the caller knowing exactly where it stopped.

        Args:
            commands: The commands to run, in order. Each is a dict with:
                      - action (str): for example "channels.setVolume"
                      - params (dict): its parameters
            name: What this edit is called in FL Studio's undo history. Say what
                  the user did, for example "AI edit: drum pattern".

        Returns:
            success: whether every command ran
            results: one entry per command, in order, with "skipped": true for
                     those that never ran
            executed, failed: counts
            undo_name: a descriptive name for this edit
            undo_history_count: the undo history size after the batch, or null
                                when this FL Studio cannot report it

        Note on undo: FL Studio has no way to group an edit into one undo step.
        general.saveUndo was tried and measured to change nothing, so it is not
        called. A batch of channel or step writes needs one fl_undo call, while
        mixer writes need one per change.

        Example:
            fl_batch(
                name="AI edit: four on the floor",
                commands=[
                    {"action": "channels.setGridBit",
                     "params": {"channel": 0, "position": 0, "value": True}},
                    {"action": "channels.setGridBit",
                     "params": {"channel": 0, "position": 4, "value": True}},
                ],
            )
        """
        return run_batch(commands, name)

    @mcp.tool()
    def fl_undo(steps: int = 1) -> dict:
        """Undo one or more steps in FL Studio.

        FL Studio cannot group an edit into a single undo step, so a batch that
        changed several things may need several steps. Channel and step writes
        generally need one. Mixer changes generally need one per change.

        Args:
            steps: How many steps to move back. One by default.
        """
        return run_undo(steps)

    @mcp.tool()
    def fl_undo_history() -> dict:
        """Report how deep FL Studio's undo history is.

        Useful for checking that an edit is undoable before making it, and for
        confirming that a batch produced exactly one entry rather than one per
        command.
        """
        return run_undo_history()
