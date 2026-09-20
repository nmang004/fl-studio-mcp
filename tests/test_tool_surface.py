"""Tests for the shape of the tool surface itself.

The tool descriptions are a prompt. They are the only thing a model reads before
deciding what to call, and a wrong choice here fails silently: the command
succeeds, it just acted on the wrong object.

The specific hazard is the Channel Rack versus the mixer. They are different
things in FL Studio, many channels can share one mixer track, and turning down a
channel is not the same as turning down the track it feeds. Measured on the real
server, the summary lines of the paired tools were up to 77 percent identical,
with nothing in either one saying which object it acted on.
"""

from __future__ import annotations

import asyncio

import pytest

from fl_studio_mcp.server import mcp

# Tools that do the same operation to the two different objects. Each one has to
# name its counterpart so a model choosing between them sees the distinction.
CHANNEL_AND_TRACK_PAIRS = [
    ("fl_get_mixer_track_info", "fl_get_channel_info"),
    ("fl_get_all_mixer_tracks", "fl_get_all_channels"),
    ("fl_set_track_volume", "fl_set_channel_volume"),
    ("fl_set_track_pan", "fl_set_channel_pan"),
    ("fl_mute_track", "fl_mute_channel"),
    ("fl_solo_track", "fl_solo_channel"),
    ("fl_set_track_name", "fl_set_channel_name"),
    ("fl_set_track_color", "fl_set_channel_color"),
]


@pytest.fixture(scope="module")
def descriptions() -> dict[str, str]:
    tools = asyncio.run(mcp.list_tools())
    return {tool.name: (tool.description or "") for tool in tools}


@pytest.mark.parametrize(("track_tool", "channel_tool"), CHANNEL_AND_TRACK_PAIRS)
def test_paired_tools_point_at_each_other(descriptions, track_tool, channel_tool):
    """Each half of a channel/track pair names the other."""
    for tool, counterpart in ((track_tool, channel_tool), (channel_tool, track_tool)):
        assert tool in descriptions, f"{tool} is not registered"
        assert counterpart in descriptions[tool], (
            f"{tool} does not mention {counterpart}, so a model choosing between "
            f"them has nothing telling it which object it is about to change"
        )


def test_every_tool_has_a_description(descriptions):
    """A tool with no description cannot be chosen correctly."""
    missing = sorted(name for name, text in descriptions.items() if not text.strip())
    assert not missing, f"tools with no description: {missing}"


def test_server_instructions_explain_channels_versus_tracks(descriptions):
    """The distinction is stated once centrally, not only per tool."""
    instructions = mcp.instructions or ""
    assert "Channel Rack" in instructions
    assert "mixer track" in instructions


def test_tool_count_is_deliberate(descriptions):
    """A canary, not a limit.

    The surface is currently 101 tools costing roughly 7,900 tokens on every
    request. That is lean per tool, but tool selection degrades as the count
    grows. If this trips, decide whether the new tools earn their place rather
    than editing the number by reflex.
    """
    assert len(descriptions) <= 115, (
        f"{len(descriptions)} tools registered. Consider whether the surface "
        f"should be filtered by tag instead of growing further."
    )
