"""Fake transport module.

Signatures mirror the official stubs exactly. transport.start, stop and record
take no arguments and toggle, which is the detail the controller got wrong.
"""

from __future__ import annotations

from types import ModuleType

from tests.fakes.project import FakeProject

# From the stubs: getSongPos and setSongPos modes.
MODE_TICKS = 0
MODE_MILLISECONDS = 1
MODE_SECONDS = 2
MODE_HINT = -1

# From the stubs: units accepted by transport.getSongLength.
LENGTH_MILLISECONDS = 1
LENGTH_SECONDS = 2
LENGTH_TICKS = 3


def build(project: FakeProject) -> ModuleType:
    module = ModuleType("transport")

    def start() -> None:
        project.is_playing = not project.is_playing

    def stop() -> None:
        project.is_playing = False

    def record() -> None:
        project.is_recording = not project.is_recording

    def isPlaying() -> int:
        return 1 if project.is_playing else 0

    def isRecording() -> int:
        return 1 if project.is_recording else 0

    def getLoopMode() -> int:
        return project.loop_mode

    def setLoopMode() -> None:
        """No arguments in the API: this toggles between the two modes."""
        project.loop_mode = 1 - project.loop_mode

    def getSongPosHint() -> str:
        return project.song_pos_hint

    def getSongPos(mode: int = MODE_HINT):
        if mode == MODE_HINT:
            return project.song_pos_hint
        return 0

    def setSongPos(position, mode: int = MODE_HINT) -> None:
        project.song_pos_hint = str(position)

    def getSongLength(mode: int) -> int:
        return project.song_length_ticks

    def setPlaybackSpeed(speedMultiplier: float) -> None:
        project.playback_speed = speedMultiplier

    module.start = start
    module.stop = stop
    module.record = record
    module.isPlaying = isPlaying
    module.isRecording = isRecording
    module.getLoopMode = getLoopMode
    module.setLoopMode = setLoopMode
    module.getSongPosHint = getSongPosHint
    module.getSongPos = getSongPos
    module.setSongPos = setSongPos
    module.getSongLength = getSongLength
    module.setPlaybackSpeed = setPlaybackSpeed

    module.MODE_TICKS = MODE_TICKS
    module.MODE_MILLISECONDS = MODE_MILLISECONDS
    module.MODE_SECONDS = MODE_SECONDS
    module.MODE_HINT = MODE_HINT
    module.LENGTH_MILLISECONDS = LENGTH_MILLISECONDS
    module.LENGTH_SECONDS = LENGTH_SECONDS
    module.LENGTH_TICKS = LENGTH_TICKS
    return module
