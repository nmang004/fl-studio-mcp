"""Which commands change the project.

The session journal has to know whether a command mutated before it is sent, because
asking FL afterwards would cost a round trip per command and the answer would arrive
too late to label the entry. The controller already needs the same knowledge for
`safeToEdit` gating, and it cannot import this package: the two FL sandboxes have no
path back to it.

So the list exists twice by necessity, exactly like the settings directory in
`utils/paths.py`, and `tests/test_actions.py` parses the controller's copy and asserts
the two sets are equal. Two copies plus a test that pins them is a different thing from
two copies: this one cannot drift without turning the suite red.

Commands that are read-only are absent on purpose. The journal records edits, not
questions, and a log full of "what is the tempo" would bury the fader moves.
"""

from __future__ import annotations

# Kept in step with `MUTATING_ACTIONS` in `fl_controller/device_FLStudioMCP.py`.
# Several entries are older aliases that the controller still accepts, and they stay
# here for the same reason they stay there: a client may still send them.
MUTATING_ACTIONS = frozenset([
    "arrangement.addMarker",
    "channels.mute",
    "channels.muteChannel",
    "channels.routeToMixer",
    "channels.select",
    "channels.selectOne",
    "channels.selectPianoRoll",
    "channels.setChannelColor",
    "channels.setChannelName",
    "channels.setChannelPan",
    "channels.setChannelPitch",
    "channels.setChannelVolume",
    "channels.setColor",
    "channels.setGridBit",
    "channels.setName",
    "channels.setPan",
    "channels.setProperties",
    "channels.setStepSequence",
    "channels.setTargetFxTrack",
    "channels.setVolume",
    "channels.solo",
    "channels.soloChannel",
    "channels.triggerNote",
    "general.restoreUndo",
    "general.restoreUndoLevel",
    "general.undo",
    "general.undoUpDown",
    "mixer.armTrack",
    "mixer.muteTrack",
    "mixer.setEqBands",
    "mixer.setRouting",
    "mixer.setStereoSep",
    "mixer.setTrackColor",
    "mixer.setTrackName",
    "mixer.setTrackPan",
    "mixer.setTrackVolume",
    "mixer.soloTrack",
    "patterns.clone",
    "patterns.createEmpty",
    "patterns.select",
    "patterns.setColor",
    "patterns.setName",
    "playlist.setTrack",
    "plugins.nextPreset",
    "plugins.prevPreset",
    "plugins.setParamValue",
    "system.tempoProbe",
    "transport.record",
    "transport.setLoopMode",
    "transport.setPlaybackSpeed",
    "transport.setPosition",
    "transport.start",
    "transport.stop",
    "ui.hideWindow",
    "ui.showWindow",
])


def is_mutating(action: str) -> bool:
    """Whether an action changes the project, the transport or a window's visibility."""
    return action in MUTATING_ACTIONS


# The piano roll script's own actions, which travel by request file rather than by
# MIDI and so are not in the list above. Four of the six write notes, and the other two
# read. Kept here so the journal has one place to ask, and pinned against the script's
# handler table by `tests/test_actions.py`.
PIANO_ROLL_MUTATING_ACTIONS = frozenset([
    "add_chord",
    "add_notes",
    "clear",
    "delete_notes",
])


def is_mutating_piano_roll(action: str) -> bool:
    """Whether a piano roll request writes notes."""
    return action in PIANO_ROLL_MUTATING_ACTIONS
