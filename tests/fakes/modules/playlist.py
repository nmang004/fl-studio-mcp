"""Fake playlist module.

There is no add, insert or create function here, and there never will be: the
real `playlist` module has none, which is why full arrangement building is out of
scope and why ROADMAP.md lists clip placement under "not possible". A test in the
harness contract suite asserts the absence, so this stays honest.

What does exist is modelled: track naming, colouring, mute and solo, and the live
clip performance path.
"""

from __future__ import annotations

from types import ModuleType

from tests.fakes.project import FakeProject


def _track(project: FakeProject, index: int):
    if not 0 <= index < len(project.playlist_tracks):
        raise IndexError(f"playlist track index {index} out of range")
    return project.playlist_tracks[index]


def _set_track(project: FakeProject, index: int, track) -> None:
    project.playlist_tracks[index] = track


def build(project: FakeProject) -> ModuleType:
    module = ModuleType("playlist")

    def trackCount() -> int:
        return len(project.playlist_tracks)

    def getTrackName(index: int) -> str:
        return _track(project, index)[0]

    def setTrackName(index: int, name: str) -> None:
        current = _track(project, index)
        _set_track(project, index, (name, current[1], current[2], current[3]))

    def getTrackColor(index: int) -> int:
        return _track(project, index)[1]

    def setTrackColor(index: int, color: int) -> None:
        current = _track(project, index)
        _set_track(project, index, (current[0], int(color), current[2], current[3]))

    def isTrackMuted(index: int) -> bool:
        return _track(project, index)[2]

    def muteTrack(index: int, value: int = -1) -> None:
        current = _track(project, index)
        muted = (not current[2]) if value == -1 else bool(value)
        _set_track(project, index, (current[0], current[1], muted, current[3]))

    def isTrackSolo(index: int) -> bool:
        return _track(project, index)[3]

    def soloTrack(index: int, value: int = -1, inGroup: bool = False) -> None:
        current = _track(project, index)
        solo = (not current[3]) if value == -1 else bool(value)
        _set_track(project, index, (current[0], current[1], current[2], solo))

    def getPerformanceModeState() -> bool:
        return project.performance_mode

    def triggerLiveClip(
        index: int,
        clipIndex: int = -1,
        value: int = -1,
        flags: int = 0,
        velocity: float = -1.0,
    ) -> None:
        _track(project, index)
        project.live_clips.append((index, clipIndex, value, flags, velocity))

    def getLiveStatus(index: int, mode: int = 0) -> int:
        _track(project, index)
        return 0

    def getSongStartTickPos() -> int:
        return 0

    def getTrackActivityLevel(index: int) -> float:
        _track(project, index)
        return 0.0

    module.trackCount = trackCount
    module.getTrackName = getTrackName
    module.setTrackName = setTrackName
    module.getTrackColor = getTrackColor
    module.setTrackColor = setTrackColor
    module.isTrackMuted = isTrackMuted
    module.muteTrack = muteTrack
    module.isTrackSolo = isTrackSolo
    module.soloTrack = soloTrack
    module.getPerformanceModeState = getPerformanceModeState
    module.triggerLiveClip = triggerLiveClip
    module.getLiveStatus = getLiveStatus
    module.getSongStartTickPos = getSongStartTickPos
    module.getTrackActivityLevel = getTrackActivityLevel
    return module
