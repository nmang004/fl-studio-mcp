"""Plugin presets: a named snapshot of a plugin's parameters, and blending two.

There is no preset load or save in the API. `plugins` has `getPresetCount`,
`nextPreset` and `prevPreset`, and the only way to capture a sound is to read every
parameter and write it back later. That is what a preset is here, and the limits follow
from it:

- A parameter's value is normalised 0.0 to 1.0. The API exposes no other form, so that
  is what a preset stores and what interpolation works in.
- Interpolation in that space is arithmetic, not a musical morph. A switch snaps
  somewhere between the two values, a filter cutoff is not linear in frequency, and a
  parameter that exists in only one of the two presets has no midpoint at all. The
  function returns what it could not blend by name, so nobody is surprised by it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

SCHEMA = 1

_INTERPOLATION_NOTES = (
    "Values are blended in the normalised 0.0 to 1.0 range, which is the only form the "
    "API exposes. A switch will snap to one side somewhere in the middle, and a "
    "frequency control is not linear in this range, so treat the result as a starting "
    "point rather than as a guaranteed halfway sound."
)


def make_preset(
    name: str,
    plugin: str | None,
    params: dict[str, Any],
    *,
    user_name: str | None = None,
    tags: list[str] | tuple[str, ...] = (),
    when: datetime | None = None,
    record_id: str | None = None,
    source: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a preset record from a plugin's parameters.

    Args:
        name: What the producer calls it.
        plugin: The plugin's own name, which identifies the instrument.
        params: Parameter index to `{"name", "value"}`, as the reader returns them.
        user_name: The label on the channel, which identifies where it came from.
        tags: Free labels for searching.
        when: When it was captured.
        record_id: The library id, chosen by the store because it must be unique.
        source: Where it came from, for provenance.
    """
    moment = when or datetime.now()
    return {
        "schema": SCHEMA,
        "id": record_id,
        "created": moment.astimezone().isoformat() if moment.tzinfo else moment.isoformat(),
        "name": name,
        "plugin": plugin,
        "user_name": user_name,
        "tags": [str(tag) for tag in tags],
        "params": {str(index): dict(entry) for index, entry in (params or {}).items()},
        "param_count": len(params or {}),
        "source": source or {},
    }


def match(
    record: dict[str, Any],
    query: str | None = None,
    plugin: str | None = None,
    tags: list[str] | tuple[str, ...] = (),
) -> bool:
    """Whether a preset answers a search. Every filter given has to pass."""
    if query:
        needle = query.strip().lower()
        fields = [
            str(record.get("name") or ""),
            str(record.get("plugin") or ""),
            str(record.get("user_name") or ""),
            *[str(tag) for tag in record.get("tags") or []],
        ]
        if not any(needle in field.lower() for field in fields):
            return False

    if plugin:
        needle = plugin.strip().lower()
        fields = [str(record.get("plugin") or ""), str(record.get("user_name") or "")]
        if not any(needle in field.lower() for field in fields):
            return False

    if tags:
        present = {str(tag).lower() for tag in record.get("tags") or []}
        for tag in tags:
            if str(tag).lower() not in present:
                return False

    return True


def search(
    records: list[dict[str, Any]],
    *,
    query: str | None = None,
    plugin: str | None = None,
    tags: list[str] | tuple[str, ...] = (),
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """The presets that match, newest first."""
    found = [
        record
        for record in records
        if match(record, query=query, plugin=plugin, tags=tags)
    ]
    found.sort(
        key=lambda record: str(record.get("created") or record.get("id") or ""),
        reverse=True,
    )
    if limit is not None and limit >= 0:
        found = found[:limit]
    return found


def interpolate(first: dict[str, Any], second: dict[str, Any], amount: float) -> dict[str, Any]:
    """Blend two presets in the normalised range.

    Args:
        first: The preset at amount 0.
        second: The preset at amount 1.
        amount: Where between them to land. Clamped to 0.0 to 1.0.

    Returns:
        values: index to `{"name", "value"}`, ready to write back
        only_in_first, only_in_second: parameter names with no counterpart
        renamed: indices where the two presets name different parameters
        notes: what this blend is and is not
    """
    amount = max(0.0, min(1.0, float(amount)))
    first_params = first.get("params") or {}
    second_params = second.get("params") or {}

    values: dict[str, Any] = {}
    only_in_first: list[str] = []
    only_in_second: list[str] = []
    renamed: list[dict[str, str]] = []

    for index, entry in first_params.items():
        name = str((entry or {}).get("name") or "")
        if index not in second_params:
            values[str(index)] = dict(entry or {})
            only_in_first.append(name or str(index))
            continue
        other = second_params[index] or {}
        other_name = str(other.get("name") or "")
        if name and other_name and name != other_name:
            # Same index, different parameter: the plugin changed under the preset, so
            # blending the two numbers would produce a value that means nothing.
            renamed.append({"index": str(index), "first": name, "second": other_name})
            values[str(index)] = dict(entry or {})
            continue
        low = _as_float((entry or {}).get("value"))
        high = _as_float(other.get("value"))
        values[str(index)] = {
            "name": name or other_name,
            "value": round(low + (high - low) * amount, 6),
        }

    for index, entry in second_params.items():
        if index not in first_params:
            values[str(index)] = dict(entry or {})
            only_in_second.append(str((entry or {}).get("name") or index))

    notes = [_INTERPOLATION_NOTES]
    if only_in_first or only_in_second:
        notes.append(
            "Some parameters exist in only one of the two presets, so they are kept at "
            "the value they have there rather than blended: there is no midpoint "
            "between a value and no value."
        )
    if renamed:
        notes.append(
            "Some parameter indices name different parameters in the two presets, so "
            "they were left alone. The plugin's parameters changed between them."
        )

    return {
        "values": values,
        "only_in_first": sorted(only_in_first),
        "only_in_second": sorted(only_in_second),
        "renamed": renamed,
        "param_count": len(values),
        "notes": notes,
    }


def recall_commands(
    preset: dict[str, Any],
    index: int,
    slot_index: int = -1,
    use_global_index: bool = True,
    current_total: int | None = None,
    current_names: dict[str, str] | None = None,
) -> Any:
    """The commands that write a preset back, plus what the plugin no longer has.

    Args:
        preset: The stored preset.
        index: Channel or mixer track index.
        slot_index: Mixer slot, or -1 for the channel rack.
        use_global_index: Whether `index` is a global channel index.
        current_total: How many parameters the plugin reports now, when known.
        current_names: Parameter names the plugin reports now, by index.

    Returns:
        A list of commands, or a dict with `commands` and `missing` when a plugin
        parameter list was supplied to check against.
    """
    commands = []
    missing = []
    for param_index, entry in sorted(
        (preset.get("params") or {}).items(), key=lambda item: int(item[0])
    ):
        position = int(param_index)
        name = str((entry or {}).get("name") or "")
        if current_total is not None and position >= int(current_total):
            missing.append(name or str(position))
            continue
        if current_names is not None:
            now = str(current_names.get(str(position)) or "")
            if now and name and now != name:
                missing.append(name)
                continue
        commands.append({
            "action": "plugins.setParamValue",
            "params": {
                "value": _as_float((entry or {}).get("value")),
                "param_index": position,
                "plugin_index": int(index),
                "slot_index": int(slot_index),
                "use_global": bool(use_global_index),
            },
            "reason": f"{name or 'parameter ' + str(position)} goes back to "
                      f"{(entry or {}).get('value')}",
        })
    if current_total is None and current_names is None:
        return commands
    return {"commands": commands, "missing": missing}


def summarise(record: dict[str, Any]) -> dict[str, Any]:
    """A preset without its parameter list, so a search result stays readable."""
    source = record.get("source") or {}
    return {
        "id": record.get("id"),
        "name": record.get("name"),
        "plugin": record.get("plugin"),
        "user_name": record.get("user_name"),
        "tags": record.get("tags") or [],
        "param_count": record.get("param_count"),
        "channel": source.get("index"),
        "slot_index": source.get("slot_index"),
        "created": record.get("created"),
    }


def differences(preset: dict[str, Any], current: dict[str, Any]) -> list[dict[str, Any]]:
    """Which of a preset's parameters differ from what the plugin reports now."""
    changes = []
    for param_index, entry in sorted(
        (preset.get("params") or {}).items(), key=lambda item: int(item[0])
    ):
        now = (current or {}).get(str(param_index)) or {}
        before = _as_float((entry or {}).get("value"))
        after = _as_float(now.get("value"))
        if abs(before - after) > 1e-6:
            changes.append({
                "param_index": int(param_index),
                "name": (entry or {}).get("name") or now.get("name"),
                "from": after,
                "to": before,
            })
    return changes


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
