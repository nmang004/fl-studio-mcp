"""Fake midi module.

The constants matter more than the functions: REC_Tempo and the REC_Update flags
are what research spike T1 needs. Values are copied from the stubs rather than
guessed, and the composition is shown so it can be re-checked.

Note that the `general` stubs define no constants at all, so there is no UF_ flag
set to mirror; general.saveUndo takes a plain integer.
"""

from __future__ import annotations

from types import ModuleType

from tests.fakes.project import FakeProject

# From midi/__rec_events/ranges.py: REC_ItemRange = 0x10000, and
# REC_Global_First = 0x4000 * REC_ItemRange. REC_Tempo is the fifth global event.
REC_ItemRange = 0x10000
REC_Global_First = 0x4000 * REC_ItemRange
REC_Tempo = REC_Global_First + 5

# From the stubs, as written there.
REC_UpdateValue = 1 << 0
REC_UpdateControl = 1 << 4

# General transport flags, assembled as the stubs assemble them.
GT_Plugin = 1
GT_Form = 2
GT_Menu = 4
GT_Global = 8
GT_All = GT_Plugin | GT_Form | GT_Menu | GT_Global
GT_None = 0

# Window ids.
widMixer = 0
widChannelRack = 1
widPianoRoll = 3

# Song position modes. ST_Hint is not defined in the stubs, so only ST_Int is
# mirrored; the numeric mode -1 is what transport.setSongPos defaults to.
ST_Int = 0

# Pickup modes.
PIM_None = 0
PIM_AlwaysPickup = 1
PIM_FollowGlobal = 2

# Playlist live clip status mode.
LB_Status_Default = 0

# findFirstNextEmptyPat flags, from midi/__ffnep_flags.py. The whole point of the
# pair is the second one: flags 0 means "find first and prompt the user for a name",
# and that prompt is modal. Modelled rather than ignored, because a fake that cannot
# express "this call asked FL to open a dialog" cannot fail a test about it.
FFNEP_FindFirst = 0
FFNEP_DontPromptName = 1 << 1


def build(project: FakeProject) -> ModuleType:
    module = ModuleType("midi")

    def EncodeRemoteControlID(PortNum: int, ChanNum: int, CCNum: int) -> int:
        return (PortNum << 16) | (ChanNum << 8) | CCNum

    def pitch_bend_event_to_float(event) -> float:
        """Convert a pitch bend event to the range -1.0 to 1.0."""
        value = (getattr(event, "data2", 0) << 7) | getattr(event, "data1", 0)
        return (value - 8192) / 8192.0

    def OnMidiIn(msg) -> None:
        pass

    def OnRefresh(flags: int) -> None:
        pass

    module.EncodeRemoteControlID = EncodeRemoteControlID
    module.pitch_bend_event_to_float = pitch_bend_event_to_float
    module.OnMidiIn = OnMidiIn
    module.OnRefresh = OnRefresh

    for name, value in (
        ("REC_ItemRange", REC_ItemRange),
        ("REC_Global_First", REC_Global_First),
        ("REC_Tempo", REC_Tempo),
        ("REC_UpdateValue", REC_UpdateValue),
        ("REC_UpdateControl", REC_UpdateControl),
        ("GT_Plugin", GT_Plugin),
        ("GT_Form", GT_Form),
        ("GT_Menu", GT_Menu),
        ("GT_Global", GT_Global),
        ("GT_All", GT_All),
        ("GT_None", GT_None),
        ("widMixer", widMixer),
        ("widChannelRack", widChannelRack),
        ("widPianoRoll", widPianoRoll),
        ("ST_Int", ST_Int),
        ("PIM_None", PIM_None),
        ("PIM_AlwaysPickup", PIM_AlwaysPickup),
        ("PIM_FollowGlobal", PIM_FollowGlobal),
        ("LB_Status_Default", LB_Status_Default),
        ("FFNEP_FindFirst", FFNEP_FindFirst),
        ("FFNEP_DontPromptName", FFNEP_DontPromptName),
    ):
        setattr(module, name, value)
    return module
