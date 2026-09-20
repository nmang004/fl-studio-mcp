"""The preset library: save a plugin's sound, find it, put it back, blend two.

There is no preset load or save in the API, so a preset here is every parameter read
and written back. Two consequences shape this module:

- Reading a plugin is paged and the pages are followed, because a VST reports 4240
  parameters and stopping at the first page would save a fraction of a sound while
  reporting success.
- Writing is compared against what the plugin holds now, so the reply says which
  parameters actually move, and parameters the plugin no longer has are named rather
  than written into the wrong slot. A plugin update renumbers parameters, and a preset
  applied blind is a preset applied to the wrong controls.

Nothing is written unless the caller passes apply=True, and then it goes through one
batch so a single undo reverses it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fl_studio_mcp.musical import presets
from fl_studio_mcp.tools import batch
from fl_studio_mcp.tools.plugins import get_plugin_params
from fl_studio_mcp.utils import store
from fl_studio_mcp.utils.connection import get_connection

if TYPE_CHECKING:
    from fastmcp import FastMCP

DEFAULT_LIMIT = 20
MAX_LIMIT = 200

# How many parameters are read in one go while following the pages.
PAGE = 200

# The most parameters a preset will store. A VST reports 4240, of which 4096 are real
# and the rest are MIDI CC and aftertouch. Storing all of them is possible; storing
# them without a stated limit is how a library file becomes unreadable.
MAX_PRESET_PARAMS = 4096


def read_plugin_params(index: int, slot_index: int = -1, use_global_index: bool = True) -> dict:
    """Every named parameter a plugin reports, following the pages.

    Returns:
        params: index to `{"name", "value"}`, as a preset stores them
        total: how many the plugin reports
        truncated: whether the cap stopped the read early
        error: a reason, when the plugin could not be read at all
    """
    collected: dict[str, Any] = {}
    offset = 0
    total = None
    truncated = False
    while True:
        page = get_plugin_params(
            index,
            slot_index=slot_index,
            use_global_index=use_global_index,
            max_params=PAGE,
            offset=offset,
            include_unnamed=False,
        )
        if not page.get("success"):
            return {
                "params": {},
                "total": 0,
                "truncated": False,
                "error": page.get("error") or "The plugin's parameters could not be read.",
            }
        for entry in page["params"]:
            collected[str(entry.get("index"))] = {
                "name": entry.get("name"),
                "value": entry.get("value"),
            }
            if len(collected) >= MAX_PRESET_PARAMS:
                truncated = True
                break
        total = page.get("total", len(collected))
        if truncated:
            break
        next_offset = page.get("next_offset")
        if next_offset is None or not page["params"]:
            break
        offset = next_offset
    return {"params": collected, "total": total or len(collected), "truncated": truncated}


def save_plugin_preset(
    name: str,
    index: int,
    slot_index: int = -1,
    tags: list[str] | None = None,
    use_global_index: bool = True,
) -> dict[str, Any]:
    """Read a plugin's parameters and store them as a named preset.

    Args:
        name: What the producer calls it.
        index: Channel index, or mixer track index for an effect.
        slot_index: Effect slot, or -1 for the channel rack.
        tags: Free labels for searching.
        use_global_index: Whether `index` is a global channel index.
    """
    if not name or not str(name).strip():
        return {"success": False, "error": "A preset needs a name to be found again."}

    identity = _identity(index, slot_index, use_global_index)
    if not identity["valid"]:
        return {
            "success": False,
            "error": (
                f"There is no plugin at index {index}, slot {slot_index}. A preset of "
                "nothing is a trap rather than a library entry, so it is refused."
            ),
        }

    read = read_plugin_params(index, slot_index=slot_index, use_global_index=use_global_index)
    if read.get("error"):
        return {"success": False, "error": read["error"]}
    if not read["params"]:
        return {
            "success": False,
            "error": (
                "The plugin reports no named parameters, so there is nothing to save. "
                "Some plugins expose only unnamed parameters, which are skipped."
            ),
        }

    record_id = store.unique_record_id("presets", str(name))
    record = presets.make_preset(
        str(name).strip(),
        identity["name"],
        read["params"],
        user_name=identity["user_name"],
        tags=tags or [],
        record_id=record_id,
        source={"index": index, "slot_index": slot_index, "use_global": use_global_index},
    )
    try:
        path = store.write_record("presets", record_id, record)
    except ValueError as error:
        return {"success": False, "error": str(error)}

    result: dict[str, Any] = {
        "success": True,
        "id": record_id,
        "file": str(path),
        "preset": presets.summarise(record),
        "message": (
            f"Saved {record['param_count']} parameter(s) of "
            f"{identity['name'] or 'the plugin'} as {record['name']!r}."
        ),
    }
    if read["truncated"]:
        result["truncated"] = True
        result["message"] += (
            f" The plugin reports {read['total']} parameter(s) and the cap is "
            f"{MAX_PRESET_PARAMS}, so the rest are not in the preset."
        )
    return result


def find_plugin_presets(
    query: str | None = None,
    plugin: str | None = None,
    tags: list[str] | None = None,
    limit: int = DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Search the preset library, newest first."""
    listing = store.list_records("presets")
    capped = max(1, min(int(limit), MAX_LIMIT))
    found = presets.search(
        listing["records"], query=query, plugin=plugin, tags=tags or [], limit=capped
    )
    result: dict[str, Any] = {
        "success": True,
        "presets": [presets.summarise(record) for record in found],
        "total": len(found),
        "library_size": len(listing["records"]),
    }
    if listing["skipped"]:
        result["skipped_files"] = listing["skipped"]
    if not found:
        result["message"] = (
            "No preset matched. The library holds "
            f"{len(listing['records'])} preset(s). Save one with "
            "fl_save_plugin_preset, which reads the plugin's current sound."
        )
    return result


def recall_plugin_preset(
    preset: str,
    index: int | None = None,
    slot_index: int | None = None,
    apply: bool = False,
) -> dict[str, Any]:
    """Compare a stored preset with the plugin, and put it back when asked."""
    found = _resolve(preset)
    if found.get("error"):
        return {"success": False, "error": found["error"]}
    record = found["record"]

    target = _target(record, index, slot_index)
    if target.get("error"):
        return {"success": False, "error": target["error"]}

    return _write(
        record,
        target["index"],
        target["slot_index"],
        target["use_global"],
        apply=apply,
        what=f"preset {record.get('name')!r}",
    )


def morph_plugin_preset(
    first: str,
    second: str,
    amount: float,
    index: int | None = None,
    slot_index: int | None = None,
    apply: bool = False,
) -> dict[str, Any]:
    """Blend two stored presets and write the result into a plugin.

    Amount 0 is the first preset and 1 is the second. Parameters that exist in only one
    of the two are kept as they are there rather than blended, and the reply names them,
    because there is no midpoint between a value and no value.
    """
    left = _resolve(first)
    if left.get("error"):
        return {"success": False, "error": left["error"]}
    right = _resolve(second)
    if right.get("error"):
        return {"success": False, "error": right["error"]}

    blended = presets.interpolate(left["record"], right["record"], amount)
    record = {
        "name": f"{left['record'].get('name')} to {right['record'].get('name')} at {amount}",
        "params": blended["values"],
        "param_count": blended["param_count"],
        "plugin": left["record"].get("plugin"),
    }
    target = _target(left["record"], index, slot_index)
    if target.get("error"):
        return {"success": False, "error": target["error"]}

    result = _write(
        record,
        target["index"],
        target["slot_index"],
        target["use_global"],
        apply=apply,
        what=f"a blend of {left['record'].get('name')!r} and {right['record'].get('name')!r}",
    )
    result["blend"] = {
        "amount": max(0.0, min(1.0, float(amount))),
        "only_in_first": blended["only_in_first"],
        "only_in_second": blended["only_in_second"],
        "renamed": blended["renamed"],
        "notes": blended["notes"],
    }
    return result


def _write(
    record: dict[str, Any],
    index: int,
    slot_index: int,
    use_global: bool,
    *,
    apply: bool,
    what: str,
) -> dict[str, Any]:
    """Compare a preset with the plugin, then report or apply the difference."""
    current = read_plugin_params(index, slot_index=slot_index, use_global_index=use_global)
    if current.get("error"):
        return {"success": False, "error": current["error"]}

    names = {
        position: str((entry or {}).get("name") or "")
        for position, entry in current["params"].items()
    }
    planned = presets.recall_commands(
        record,
        index,
        slot_index=slot_index,
        use_global_index=use_global,
        current_total=current["total"],
        current_names=names,
    )
    missing = planned["missing"]

    # The planner writes every parameter in the preset, because that is what a recall
    # is. What a caller wants to read, and what should go over the wire, is the
    # difference: writing eight values that are already right is eight chances to
    # change something nobody asked about.
    changes = presets.differences(record, current["params"])
    moved = {change["param_index"] for change in changes}
    commands = [
        command
        for command in planned["commands"]
        if command["params"]["param_index"] in moved
    ]
    result: dict[str, Any] = {
        "success": True,
        "preset": record.get("name"),
        "plugin_index": index,
        "slot_index": slot_index,
        "parameters": len(record.get("params") or {}),
        "would_change": len(changes),
        "changes": changes[:50],
        "applied": False,
        "note": (
            "Values are normalised 0.0 to 1.0, which is the only form the API exposes. "
            "A parameter the plugin no longer has is reported rather than written."
        ),
    }
    if len(changes) > 50:
        result["changes_truncated"] = len(changes) - 50
    if missing:
        result["missing"] = missing
        result["missing_note"] = (
            f"{len(missing)} parameter(s) in the preset are not on the plugin now, so "
            "they were not written. A plugin update renumbers parameters, and writing "
            "a value into the wrong control is worse than leaving it alone."
        )
    if not commands:
        result["message"] = (
            f"Nothing to do: the plugin already matches {what} in every parameter the "
            "preset holds."
        )
        return result
    if not apply:
        result["message"] = (
            f"{len(commands)} parameter(s) differ from {what}. Nothing has been "
            "changed: pass apply=True to write them, which goes through one batch so "
            "one undo reverses it."
        )
        return result

    batch_result = batch.run_batch(commands, f"MCP: recall {record.get('name')}")
    result["batch"] = batch_result
    result["applied"] = bool(batch_result.get("success"))
    if not result["applied"]:
        result["success"] = False
        result["error"] = batch_result.get("error") or "The preset batch did not complete."
        return result
    result["message"] = (
        f"Wrote {len(commands)} parameter(s) from {what}. One undo reverses it."
    )
    return result


def _identity(index: int, slot_index: int, use_global: bool) -> dict[str, Any]:
    reply = get_connection().send_command(
        "plugins.getName",
        {"index": index, "slot_index": slot_index, "use_global": use_global},
        timeout=5.0,
    )
    return {
        "name": reply.get("name"),
        "user_name": reply.get("user_name"),
        "valid": bool(reply.get("valid")),
    }


def _target(record: dict[str, Any], index: int | None, slot_index: int | None) -> dict[str, Any]:
    """Where to write, preferring the caller's choice over where it was saved."""
    source = record.get("source") or {}
    chosen = index if index is not None else source.get("index")
    if chosen is None:
        return {
            "error": (
                "This preset does not record where it came from, so the target plugin "
                "has to be named with index."
            )
        }
    return {
        "index": int(chosen),
        "slot_index": int(slot_index if slot_index is not None else source.get("slot_index", -1)),
        "use_global": bool(source.get("use_global", True)),
    }


def _resolve(preset: str) -> dict[str, Any]:
    """Find one preset by id, or by a name that matches exactly one."""
    wanted = str(preset or "").strip()
    if not wanted:
        return {"error": "A preset id or name is required."}

    by_id = store.read_record("presets", wanted)
    if by_id:
        return {"record": by_id}

    listing = store.list_records("presets")
    matches = [
        record
        for record in listing["records"]
        if str(record.get("name") or "").lower() == wanted.lower()
    ]
    if not matches:
        return {
            "error": (
                f"No preset called {wanted!r} and no record with that id. Use "
                "fl_find_plugin_presets to see what is in the library."
            )
        }
    if len(matches) > 1:
        ids = ", ".join(str(record.get("id")) for record in matches)
        return {
            "error": (
                f"{len(matches)} presets are called {wanted!r}, so the name is "
                f"ambiguous. Recall one by id: {ids}."
            )
        }
    return {"record": matches[0]}


def register_preset_tools(mcp: FastMCP) -> None:
    """Register the preset library tools."""

    @mcp.tool()
    def fl_save_plugin_preset(
        name: str,
        index: int,
        slot_index: int = -1,
        tags: list[str] | None = None,
    ) -> dict:
        """Save a plugin's current sound as a named preset.

        Reads every named parameter the plugin reports, following the pages, and stores
        them beside the plugin's own name and the label on the channel. There is no
        preset save in FL's API, so this is the whole sound rather than a reference to
        one.

        An empty slot is refused: a preset of nothing is a trap rather than a library
        entry.

        Args:
            name: What to call it.
            index: Channel index, or mixer track index for an effect.
            slot_index: Effect slot, or -1 for the channel rack.
            tags: Free labels, matched case-insensitively when searching.
        """
        return save_plugin_preset(name, index, slot_index=slot_index, tags=tags)

    @mcp.tool()
    def fl_find_plugin_presets(
        query: str | None = None,
        plugin: str | None = None,
        tags: list[str] | None = None,
        limit: int = DEFAULT_LIMIT,
    ) -> dict:
        """Search the preset library, newest first.

        Results are summaries without parameter lists, so the answer stays readable.
        Use the id it returns with fl_recall_plugin_preset.

        Args:
            query: Matched against the name, plugin, channel label and tags.
            plugin: A substring of the plugin name or the channel label.
            tags: Every tag named has to be present.
            limit: How many to return, up to 200.
        """
        return find_plugin_presets(query=query, plugin=plugin, tags=tags, limit=limit)

    @mcp.tool()
    def fl_recall_plugin_preset(
        preset: str,
        index: int | None = None,
        slot_index: int | None = None,
        apply: bool = False,
    ) -> dict:
        """Put a stored preset back into a plugin.

        Reports first and writes only when apply is true, and then through one batch so
        a single undo reverses it. Parameters the plugin no longer has are named rather
        than written into whatever now sits at that index.

        Args:
            preset: The preset id, or a name that matches exactly one.
            index: Channel or mixer track to write into. Defaults to where the preset
                   was saved from.
            slot_index: Effect slot, or -1 for the channel rack.
            apply: False reports the difference. True writes it.
        """
        return recall_plugin_preset(preset, index=index, slot_index=slot_index, apply=apply)

    @mcp.tool()
    def fl_morph_plugin_preset(
        first: str,
        second: str,
        amount: float,
        index: int | None = None,
        slot_index: int | None = None,
        apply: bool = False,
    ) -> dict:
        """Blend two stored presets and write the result into a plugin.

        Amount 0 is the first preset and 1 is the second. The blend is arithmetic in the
        normalised 0.0 to 1.0 range, which is the only form the API exposes: a switch
        snaps somewhere in the middle and a frequency control is not linear there, so
        the result is a starting point rather than a guaranteed halfway sound. The reply
        says what could not be blended and why.

        Args:
            first: The preset at amount 0.
            second: The preset at amount 1.
            amount: Where between them to land, 0.0 to 1.0.
            index: Channel or mixer track to write into. Defaults to where the first
                   preset was saved from.
            slot_index: Effect slot, or -1 for the channel rack.
            apply: False reports the blend. True writes it.
        """
        return morph_plugin_preset(
            first, second, amount, index=index, slot_index=slot_index, apply=apply
        )
