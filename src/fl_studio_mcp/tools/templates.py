"""Apply a template: name, colour and route, or place a song's markers.

With neither a name nor a spec this returns the catalogue and sends nothing, which is
what makes the tool discoverable without reading the code. With apply=False it reports
every move and changes nothing, because naming eight inserts and rerouting them is
disruptive enough that the first call should be free. With apply=True the moves go
through one batch, so one undo reverses the template.

The readings a plan needs arrive in one batch: the timebase, the mixer tracks, the
channels and the playlist lanes. The meter is the exception, because it lives in the
piano roll's sandbox and cannot ride in a controller batch. It is read only for a spec
that places markers, and a spec that places markers is refused when it cannot be read,
because a marker placed from an assumed meter lands in the wrong place.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fl_studio_mcp.musical import templates as templates_module
from fl_studio_mcp.tools import batch
from fl_studio_mcp.tools.structure import project_context
from fl_studio_mcp.utils.connection import get_connection

if TYPE_CHECKING:
    from fastmcp import FastMCP

READINGS: tuple[tuple[str, str, dict[str, Any]], ...] = (
    ("ppq", "system.getPpq", {}),
    ("tracks", "mixer.getAllTracks", {"include_empty": True}),
    ("channels", "channels.getAll", {}),
    ("lanes", "playlist.getAll", {"include_all": True}),
)

TEMPLATE_TIMEOUT = 30.0

# One batch, one named undo entry. The name is what the producer reads in FL's undo
# history, so it says what happened rather than which tool ran.
BATCH_NAME = "MCP: apply template"

CANNOT_LOAD = (
    "A template cannot load an instrument. FL's scripting API has no function that "
    "loads a plugin or adds a channel, so an insert a template names is a name, a "
    "colour and a routing and nothing more. Every track listed in "
    "without_instruments has no channel routed into it, and will stay silent until "
    "an instrument is loaded by hand."
)


def apply_template(
    template: str | None = None,
    spec: dict | None = None,
    apply: bool = False,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Plan a template, and with apply=True make its moves as one batch.

    Args:
        template: A built-in name, such as "mixing" or "sections".
        spec: A spec of the caller's own, in the same shape as the built-ins.
        apply: Whether to make the moves. False reports and changes nothing.
        overwrite: Touch a target even when the producer named it themselves.

    Returns:
        The moves, what was skipped and why, the tracks no channel is routed into,
        and the batch report when the moves were applied.
    """
    if template is None and spec is None:
        return {
            "success": True,
            "applied": False,
            "templates": templates_module.catalogue(),
            "note": CANNOT_LOAD,
            "message": (
                "Name a template or pass a spec to plan one. Nothing was sent to FL "
                "Studio."
            ),
        }

    chosen = _choose(template, spec)
    if "error" in chosen:
        return {"success": False, "applied": False, "error": chosen["error"]}

    readings = _read_project(needs_meter=bool(chosen["spec"].get("markers")))
    if not readings.get("success"):
        return readings

    plan = templates_module.validate(
        chosen["spec"],
        readings["track_count"],
        readings["channel_count"],
        overwrite=overwrite,
        project={
            "ppq": readings["ppq"],
            "beats_per_bar": readings.get("beats_per_bar"),
            "track_names": readings["track_names"],
            "lane_names": readings["lane_names"],
            "lane_count": readings["lane_count"],
        },
    )
    if plan["problems"]:
        return {
            "success": False,
            "applied": False,
            "template": chosen["name"],
            "problems": plan["problems"],
            "message": (
                f"The spec has {len(plan['problems'])} problem(s), starting with: "
                f"{plan['problems'][0]} Nothing was sent to FL Studio."
            ),
        }

    result: dict[str, Any] = {
        "success": True,
        "template": chosen["name"],
        "applied": False,
        "overwrite": overwrite,
        "moves": plan["commands"],
        "move_count": len(plan["commands"]),
        "skipped": plan["skipped"],
        "without_instruments": templates_module.tracks_without_instruments(
            chosen["spec"], readings["channels"]
        ),
        "instrument_note": CANNOT_LOAD,
    }

    if not plan["commands"]:
        result["message"] = (
            "Nothing to do: every target the spec names is already named by the "
            "producer. Pass overwrite=True to name the skipped ones anyway."
        )
        if not plan["skipped"]:
            result["message"] = (
                "Nothing to do: the spec names no tracks, lanes or markers that this "
                "project can take."
            )
        return result

    if not apply:
        result["message"] = (
            f"{len(plan['commands'])} move(s) would be made. Nothing has been "
            "changed: pass apply=True to make them, which goes through one batch so "
            "one undo reverses the template."
        )
        result["message"] += _left_alone_sentence(plan["skipped"])
        return result

    batch_result = batch.run_batch(plan["commands"], BATCH_NAME)
    result["batch"] = batch_result
    result["applied"] = bool(batch_result.get("success"))
    if not result["applied"]:
        result["success"] = False
        result["error"] = batch_result.get("error") or "The template batch did not complete."
        return result

    result["message"] = (
        f"Applied {len(plan['commands'])} move(s) as {BATCH_NAME!r}, in one batch. "
        "Undo may need several steps."
    )
    result["message"] += _left_alone_sentence(plan["skipped"])
    return result


def _choose(template: Any, spec: Any) -> dict[str, Any]:
    """Which spec to run, or the reason neither can be."""
    if spec is not None:
        if template is not None:
            return {
                "error": (
                    "Give either a template name or a spec, not both, so there is no "
                    "doubt which one ran."
                )
            }
        if not isinstance(spec, dict):
            return {
                "error": f"A spec must be an object, got {type(spec).__name__}."
            }
        return {"name": "custom", "spec": spec}

    if not isinstance(template, str) or template not in templates_module.TEMPLATES:
        names = ", ".join(sorted(templates_module.TEMPLATES))
        return {
            "error": (
                f"There is no built-in template called {template!r}. The built-in "
                f"ones are {names}."
            )
        }
    return {"name": template, "spec": templates_module.TEMPLATES[template]}


def _read_project(needs_meter: bool) -> dict[str, Any]:
    """What a plan needs, in one batch, plus the meter when a spec places markers."""
    connection = get_connection()
    commands = [{"action": action, "params": params} for _, action, params in READINGS]
    reply = connection.send_command(
        "system.batch",
        {"commands": commands, "name": "MCP: read project for a template"},
        timeout=TEMPLATE_TIMEOUT,
    )
    if not reply.get("success"):
        return {
            "success": False,
            "error": reply.get("error") or "The template's read batch did not complete.",
            "results": reply.get("results"),
        }

    results = reply.get("results") or []
    if len(results) < len(READINGS):
        return {
            "success": False,
            "error": (
                f"The read batch returned {len(results)} result(s) for "
                f"{len(READINGS)} command(s), so the project was only partly read."
            ),
        }

    ppq_reply, tracks_reply, channels_reply, lanes_reply = (
        results[0] or {}, results[1] or {}, results[2] or {}, results[3] or {}
    )
    tracks = tracks_reply.get("tracks") or []
    channels = channels_reply.get("channels") or []
    lanes = lanes_reply.get("tracks") or []
    readings: dict[str, Any] = {
        "success": True,
        "ppq": ppq_reply.get("ppq"),
        "channels": channels,
        "track_count": len(tracks),
        "channel_count": len(channels),
        "lane_count": lanes_reply.get("total_tracks", len(lanes)),
        "track_names": {entry.get("index"): entry.get("name") for entry in tracks},
        "lane_names": {entry.get("index"): entry.get("name") for entry in lanes},
    }
    if needs_meter:
        # Only a spec that places markers pays for this, and it is the one reading
        # that cannot be batched: the meter is in the piano roll's sandbox.
        readings["beats_per_bar"] = project_context().get("beats_per_bar")
    return readings


def _left_alone_sentence(skipped: list[dict]) -> str:
    """The skipped targets, named in the sentence a caller reads first."""
    if not skipped:
        return ""
    parts = []
    for entry in skipped:
        label = f"{entry.get('kind')} {entry.get('index')}"
        current = entry.get("current_name")
        parts.append(f"{label} is named {current!r}" if current else f"{label} was not read")
    return " Left alone: " + "; ".join(parts) + "."


def register_template_tools(mcp: FastMCP) -> None:
    """Register the template tool."""

    @mcp.tool()
    def fl_apply_template(
        template: str | None = None,
        spec: dict | None = None,
        apply: bool = False,
        overwrite: bool = False,
    ) -> dict:
        """Set up a mixing template, or place a song's section markers.

        Call it with no arguments to see the built-in templates and how many objects
        each one touches. Name one, or pass a spec of your own, to see every move it
        would make. Nothing changes until apply is true, and then every move goes
        through one batch, so one undo reverses the whole template.

        A template cannot load an instrument: FL's scripting API has no function that
        loads a plugin or adds a channel. The reply lists the inserts no channel is
        routed into, so you can load them by hand.

        An insert is only renamed when it still carries FL's own name for it, so
        applying a template to a project with work in it does not rename that work.
        The reply names what it left alone. Pass overwrite to touch those anyway.

        Args:
            template: A built-in name: "mixing" names and colours eight inserts and
                      routes them into two returns, and "sections" places eight bar
                      markers for a conventional song.
            spec: A spec in the built-ins' shape: a list of tracks with track, name,
                  color and sends, and a list of markers with bar and name.
            apply: False reports the moves. True makes them, as one batch.
            overwrite: Also touch targets the producer already named.

        Returns:
            moves: the commands that would run or did run
            skipped: what was left alone, each entry naming the reason
            without_instruments: the named tracks no channel is routed into
            batch: when applied, the batch report and its undo name
        """
        return apply_template(
            template=template, spec=spec, apply=apply, overwrite=overwrite
        )
