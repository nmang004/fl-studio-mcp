"""Fake arrangement module.

arrangement is where markers and the timeline selection live. Placing clips is
not here and not anywhere else: it does not exist in the API, which is why
markers are the ceiling for arrangement building.
"""

from __future__ import annotations

from types import ModuleType

from tests.fakes.project import FakeProject

# From the stubs: arrangement.currentTime snap modes.
SNAP_NONE = 0


def build(project: FakeProject) -> ModuleType:
    module = ModuleType("arrangement")

    def currentTime(snap: int) -> int:
        return project.arrangement_time

    def currentTimeHint(
        mode: int, delta: int, snap: int, song: bool = True, fill: bool = False
    ) -> str:
        return project.song_pos_hint

    def selectionStart() -> int:
        return project.arrangement_selection[0]

    def selectionEnd() -> int:
        return project.arrangement_selection[1]

    def addAutoTimeMarker(time: int, name: str) -> None:
        project.markers.append((time, name))

    def getMarkerName(index: int) -> str:
        if not 0 <= index < len(project.markers):
            raise IndexError(f"marker index {index} out of range")
        return project.markers[index][1]

    def jumpToMarker(delta: int, select: bool) -> None:
        pass

    def liveSelection(time: int, stop: bool) -> None:
        pass

    def liveSelectionStart() -> int:
        return 0

    module.currentTime = currentTime
    module.currentTimeHint = currentTimeHint
    module.selectionStart = selectionStart
    module.selectionEnd = selectionEnd
    module.addAutoTimeMarker = addAutoTimeMarker
    module.getMarkerName = getMarkerName
    module.jumpToMarker = jumpToMarker
    module.liveSelection = liveSelection
    module.liveSelectionStart = liveSelectionStart

    module.SNAP_NONE = SNAP_NONE
    return module
