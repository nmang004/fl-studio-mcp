"""Playlist tracks, arrangement markers, UI state and channel properties.

The playlist is the arrangement grid. A playlist track is a lane in it, which is
not a mixer track and not a Channel Rack channel, and FL keeps the three
completely separate. A generic DAW tool tends to assume they are the same thing,
and renaming one then renames something the user did not mean.

Markers are how far arrangement building goes. The playlist module has no function
that places a clip, so structure can be annotated but not constructed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fl_studio_mcp.utils.connection import get_connection

if TYPE_CHECKING:
    from fastmcp import FastMCP


def get_playlist_tracks(include_unnamed: bool = False) -> dict[str, Any]:
    """Playlist tracks with their properties."""
    return get_connection().send_command(
        "playlist.getAll", {"include_unnamed": include_unnamed}, timeout=10.0
    )


def set_playlist_track(
    index: int,
    name: str | None = None,
    color: int | None = None,
    muted: bool | None = None,
    solo: bool | None = None,
) -> dict[str, Any]:
    """Change a playlist track, then report it read back."""
    params: dict[str, Any] = {"index": index}
    for key, value in (("name", name), ("color", color), ("muted", muted), ("solo", solo)):
        if value is not None:
            params[key] = value
    if len(params) == 1:
        return {
            "success": False,
            "error": "Nothing to do: give at least one of name, color, muted or solo.",
        }
    reply = get_connection().send_command("playlist.setTrack", params, timeout=10.0)
    if reply.get("success"):
        reply["message"] = f"Playlist track {index} is now called {reply.get('name')!r}."
    return reply


def get_markers() -> dict[str, Any]:
    """The arrangement's markers and the current selection."""
    return get_connection().send_command("arrangement.getMarkers", timeout=10.0)


def add_marker(time: int, name: str) -> dict[str, Any]:
    """Place a time marker in the arrangement."""
    reply = get_connection().send_command(
        "arrangement.addMarker", {"time": time, "name": name}, timeout=10.0
    )
    if reply.get("success"):
        reply["message"] = f"Placed marker {name!r} at tick {time}."
    return reply


def get_ui_state() -> dict[str, Any]:
    """Which windows are open, and what has focus."""
    return get_connection().send_command("ui.getState", timeout=10.0)


def show_window(index: int) -> dict[str, Any]:
    """Show an FL window."""
    return get_connection().send_command("ui.showWindow", {"index": index}, timeout=10.0)


def hide_window(index: int) -> dict[str, Any]:
    """Hide an FL window."""
    return get_connection().send_command("ui.hideWindow", {"index": index}, timeout=10.0)


def get_channel_properties(index: int) -> dict[str, Any]:
    """A channel's type, pitch and routing."""
    return get_connection().send_command(
        "channels.getProperties", {"index": index}, timeout=5.0
    )


def set_channel_properties(
    index: int, pitch: float | None = None, quantize: bool = False
) -> dict[str, Any]:
    """Set a channel's pitch, or quantize it."""
    params: dict[str, Any] = {"index": index}
    if pitch is not None:
        params["pitch"] = pitch
    if quantize:
        params["quantize"] = True
    if len(params) == 1:
        return {
            "success": False,
            "error": "Nothing to do: give 'pitch', 'quantize', or both.",
        }
    return get_connection().send_command("channels.setProperties", params, timeout=10.0)


def register_project_tools(mcp: FastMCP) -> None:
    """Register playlist, arrangement, UI and channel property tools."""

    @mcp.tool()
    def fl_get_playlist_tracks(include_unnamed: bool = False) -> dict:
        """List the playlist tracks, which are the arrangement lanes.

        A playlist track is not a mixer track and not a Channel Rack channel. FL
        keeps the three separate, so a playlist track called "Drums" and a mixer
        insert called "Drums" are two unrelated things that happen to share a name.

        A project reports five hundred playlist tracks whether or not they are used,
        and only the named ones mean anything, so unnamed lanes are left out by
        default.

        Args:
            include_unnamed: Also report lanes with no name, which is 499 of the
                             500 on a typical project.

        Returns:
            tracks: each with its index, name, colour, and mute and solo state
            total_tracks: how many lanes FL reports in total
        """
        return get_playlist_tracks(include_unnamed)

    @mcp.tool()
    def fl_set_playlist_track(
        index: int,
        name: str | None = None,
        color: int | None = None,
        muted: bool | None = None,
        solo: bool | None = None,
    ) -> dict:
        """Rename, recolour, mute or solo a playlist track.

        Args:
            index: Playlist track index, from fl_get_playlist_tracks.
            name: New name for the lane.
            color: Colour as 0xRRGGBB.
            muted: Mute or unmute the lane.
            solo: Solo or unsolo the lane.
        """
        return set_playlist_track(index, name=name, color=color, muted=muted, solo=solo)

    @mcp.tool()
    def fl_get_markers() -> dict:
        """List the arrangement's markers and the current timeline selection.

        Markers are the ceiling for arrangement work: the playlist module has no
        function that places a clip, so a song's structure can be labelled but not
        built.

        The API can read a marker's name but not its time, so times are reported
        as null rather than guessed. Record the time yourself when you place one.

        Returns:
            markers: each with its index and name
            selection: the timeline selection start and end in ticks
        """
        return get_markers()

    @mcp.tool()
    def fl_add_marker(time: int, name: str) -> dict:
        """Place a named marker in the arrangement.

        Use this to label structure: Intro, Drop, Break. It is how this server
        records a song's shape, since clips cannot be placed.

        Args:
            time: Position in ticks. A bar is 4 * PPQ ticks, and general.getRecPPQ
                  reports PPQ, which is 96 on a default project.
            name: What the marker says, for example "Drop".
        """
        return add_marker(time, name)

    @mcp.tool()
    def fl_get_ui_state() -> dict:
        """Find out which FL windows are open and what has focus.

        Worth checking before any piano roll work, because the piano roll tools
        write into whichever piano roll is open.

        Returns:
            windows: whether the mixer, channel rack, playlist, piano roll and
                     browser are visible
            piano_roll_visible: the one that matters most
            focused: the window index that has focus, or null
            snap_mode, form_caption: the current snap setting and the focused
                                     window's caption
            selected_channel: which Channel Rack channel is selected
        """
        return get_ui_state()

    @mcp.tool()
    def fl_show_window(index: int) -> dict:
        """Show an FL window.

        Args:
            index: 0 mixer, 1 channel rack, 2 playlist, 3 piano roll, 4 browser.
        """
        return show_window(index)

    @mcp.tool()
    def fl_hide_window(index: int) -> dict:
        """Hide an FL window.

        Args:
            index: 0 mixer, 1 channel rack, 2 playlist, 3 piano roll, 4 browser.
        """
        return hide_window(index)

    @mcp.tool()
    def fl_get_channel_properties(index: int) -> dict:
        """Read a channel's type, pitch and routing.

        Complements fl_get_channel_info, which covers the common properties. This
        adds the ones a producer reaches for less often: what kind of channel it
        is, its fine pitch, and which mixer track it feeds.

        Args:
            index: Channel Rack index.
        """
        return get_channel_properties(index)

    @mcp.tool()
    def fl_set_channel_properties(
        index: int, pitch: float | None = None, quantize: bool = False
    ) -> dict:
        """Set a channel's pitch, or quantize its notes.

        Args:
            index: Channel Rack index.
            pitch: Semitones, -120 to 120. For fine tuning, use the piano roll's
                   per-note pitch offset instead, which is exact.
            quantize: Quantize note starts and lengths to the project grid.
        """
        return set_channel_properties(index, pitch=pitch, quantize=quantize)
