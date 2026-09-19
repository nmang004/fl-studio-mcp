"""Fake channels module.

Signatures mirror the official stubs exactly. Where a stub documents a range the
setter clamps to it, and where a stub returns a type the getter returns that type:
channels.getChannelPitch returns a float for mode 0 and an int for modes 1 and 2.

Nothing here is more capable than the real API. Per-step velocity and pan live in
the graph editor behind channels.getStepParam and setStepParameterByIndex, whose
arguments the stubs mark "???" and which are research spike T2, so they are
absent on purpose.
"""

from __future__ import annotations

from types import ModuleType

from tests.fakes.project import FakeProject, clamp

# From the stubs: channels.getChannelType values. Only the ones the controller
# and the roadmap care about are named.
CT_Sampler = 0
CT_Native = 1
CT_VST = 3

# From the stubs: channels.quickQuantize modes.
QT_Start = 0
QT_StartEnd = 1

# From the stubs: channels.getChannelPitch modes.
PITCH_SEMITONES = 0
PITCH_CENTS = 1
PITCH_FINE_CENTS = 2


def build(project: FakeProject) -> ModuleType:
    module = ModuleType("channels")

    def channelCount(globalCount: bool = False) -> int:
        return len(project.channels)

    def channelNumber(canBeNone: bool = False, offset: int = 0):
        if project.selected_channel is None:
            return None if canBeNone else -1
        return project.selected_channel + offset

    def selectedChannel(canBeNone: bool = False, indexGlobal: bool = False):
        if project.selected_channel is None:
            return None if canBeNone else -1
        return project.selected_channel

    def selectChannel(index: int, value: bool, useGlobalIndex: bool = False) -> None:
        project.channel(index).selected = bool(value)

    def selectOneChannel(index: int, useGlobalIndex: bool = False) -> None:
        project.channel(index)  # raises IndexError on a bad index
        project.selected_channel = index
        for i, channel in enumerate(project.channels):
            channel.selected = i == index

    def deselectAll() -> None:
        project.selected_channel = None
        for channel in project.channels:
            channel.selected = False

    def isChannelSelected(index: int, useGlobalIndex: bool = False) -> bool:
        return project.channel(index).selected

    def getChannelName(index: int, useGlobalIndex: bool = False) -> str:
        return project.channel(index).name

    def setChannelName(index: int, name: str, useGlobalIndex: bool = False) -> None:
        project.channel(index).name = name

    def getChannelColor(index: int, useGlobalIndex: bool = False) -> int:
        return project.channel(index).color

    def setChannelColor(index: int, color: int, useGlobalIndex: bool = False) -> None:
        project.channel(index).color = int(color)

    def getChannelVolume(index: int, useGlobalIndex: bool = False) -> float:
        return project.channel(index).volume

    def setChannelVolume(index: int, volume: float, useGlobalIndex: bool = False) -> None:
        project.channel(index).volume = clamp(volume, 0.0, 1.0)
        project.record_undo("set channel volume")

    def getChannelPan(index: int, useGlobalIndex: bool = False) -> float:
        return project.channel(index).pan

    def setChannelPan(index: int, pan: float, useGlobalIndex: bool = False) -> None:
        project.channel(index).pan = clamp(pan, -1.0, 1.0)
        project.record_undo("set channel pan")

    def getChannelPitch(index: int, mode: int = PITCH_SEMITONES, useGlobalIndex: bool = False):
        channel = project.channel(index)
        if mode == PITCH_SEMITONES:
            # The stub's overload returns float for mode 0.
            return float(channel.pitch)
        if mode == PITCH_CENTS:
            return int(round(channel.pitch * 100))
        return int(round(channel.pitch * 10000))

    def setChannelPitch(
        index: int,
        value: float,
        mode: int = PITCH_SEMITONES,
        pickupMode: int = 0,
        useGlobalIndex: bool = False,
    ) -> None:
        channel = project.channel(index)
        if mode == PITCH_SEMITONES:
            channel.pitch = int(round(clamp(value, -120.0, 120.0)))
        elif mode == PITCH_CENTS:
            channel.pitch = int(round(clamp(value, -12000.0, 12000.0) / 100))
        else:
            channel.pitch = int(round(clamp(value, -1200000.0, 1200000.0) / 10000))

    def getChannelType(index: int, useGlobalIndex: bool = False) -> int:
        return project.channel(index).channel_type

    def isChannelMuted(index: int, useGlobalIndex: bool = False) -> bool:
        return project.channel(index).muted

    def muteChannel(index: int, value: int = -1, useGlobalIndex: bool = False) -> None:
        channel = project.channel(index)
        if value == -1:
            channel.muted = not channel.muted
        else:
            channel.muted = bool(value)

    def isChannelSolo(index: int, useGlobalIndex: bool = False) -> bool:
        return project.channel(index).solo

    def soloChannel(index: int, value: int = -1, useGlobalIndex: bool = False) -> None:
        channel = project.channel(index)
        if value == -1:
            channel.solo = not channel.solo
        else:
            channel.solo = bool(value)

    def getTargetFxTrack(index: int, useGlobalIndex: bool = False) -> int:
        return project.channel(index).target_fx_track

    def setTargetFxTrack(index: int, value: int, useGlobalIndex: bool = False) -> None:
        project.channel(index).target_fx_track = value

    def getGridBit(index: int, position: int, useGlobalIndex: bool = False) -> bool:
        return project.channel(index).grid[position]

    def setGridBit(
        index: int, position: int, value: bool, useGlobalIndex: bool = False
    ) -> None:
        project.channel(index).grid[position] = bool(value)
        project.record_undo("set grid bit")

    def getGridBitWithLoop(
        index: int, position: int, useGlobalIndex: bool = False
    ) -> bool:
        """Loops are not modelled, so this matches getGridBit.

        The stub documents only "accounting for loops" and does not say how, so
        inventing loop semantics here would be a guess dressed as a fixture.
        """
        return project.channel(index).grid[position]

    def isGridBitAssigned(index: int, useGlobalIndex: bool = False) -> bool:
        return project.channel(index).grid_assigned

    def getActivityLevel(index: int, useGlobalIndex: bool = False) -> float:
        return 0.0

    def midiNoteOn(
        indexGlobal: int, note: int, velocity: int, channel: int = -1
    ) -> None:
        project.channel(indexGlobal)
        project.midi_notes.append((indexGlobal, note, velocity, channel))

    def quickQuantize(index: int, mode: int, useGlobalIndex: bool = False) -> None:
        project.channel(index)

    module.channelCount = channelCount
    module.channelNumber = channelNumber
    module.selectedChannel = selectedChannel
    module.selectChannel = selectChannel
    module.selectOneChannel = selectOneChannel
    module.deselectAll = deselectAll
    module.isChannelSelected = isChannelSelected
    module.getChannelName = getChannelName
    module.setChannelName = setChannelName
    module.getChannelColor = getChannelColor
    module.setChannelColor = setChannelColor
    module.getChannelVolume = getChannelVolume
    module.setChannelVolume = setChannelVolume
    module.getChannelPan = getChannelPan
    module.setChannelPan = setChannelPan
    module.getChannelPitch = getChannelPitch
    module.setChannelPitch = setChannelPitch
    module.getChannelType = getChannelType
    module.isChannelMuted = isChannelMuted
    module.muteChannel = muteChannel
    module.isChannelSolo = isChannelSolo
    module.soloChannel = soloChannel
    module.getTargetFxTrack = getTargetFxTrack
    module.setTargetFxTrack = setTargetFxTrack
    module.getGridBit = getGridBit
    module.setGridBit = setGridBit
    module.getGridBitWithLoop = getGridBitWithLoop
    module.isGridBitAssigned = isGridBitAssigned
    module.getActivityLevel = getActivityLevel
    module.midiNoteOn = midiNoteOn
    module.quickQuantize = quickQuantize

    module.CT_Sampler = CT_Sampler
    module.CT_Native = CT_Native
    module.CT_VST = CT_VST
    module.QT_Start = QT_Start
    module.QT_StartEnd = QT_StartEnd
    module.PITCH_SEMITONES = PITCH_SEMITONES
    module.PITCH_CENTS = PITCH_CENTS
    module.PITCH_FINE_CENTS = PITCH_FINE_CENTS
    return module
