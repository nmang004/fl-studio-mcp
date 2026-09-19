"""Fake general module.

Undo is modelled as a stack because Phase 1's batching wraps edits in
general.saveUndo so that one AI edit becomes one Ctrl+Z.
"""

from __future__ import annotations

from types import ModuleType

from tests.fakes.project import FakeProject

# From the stubs: the flags general.saveUndo accepts.
UF_None = 0
UF_UndoLevel = 1


def build(project: FakeProject) -> ModuleType:
    module = ModuleType("general")

    def getVersion() -> int:
        return project.api_version

    def safeToEdit() -> bool:
        return project.safe_to_edit

    def getRecPPQ() -> int:
        return project.ppq

    def getRecPPB() -> int:
        return project.ppq // 4

    def getChangedFlag() -> int:
        return 1 if project.tempo else 1

    def saveUndo(undoName: str, flags: int, update: bool = True) -> None:
        project.undo_stack.append(undoName)

    def undo() -> None:
        if len(project.undo_stack) > 1:
            project.undo_stack.pop()

    def restoreUndo() -> None:
        pass

    def restoreUndoLevel(level: int) -> None:
        pass

    def getUndoHistoryCount() -> int:
        return len(project.undo_stack)

    def getUndoHistoryPos() -> int:
        return max(0, len(project.undo_stack) - 1)

    def getUndoLevelHint() -> str:
        return project.undo_stack[-1] if project.undo_stack else ""

    def getUseMetronome() -> bool:
        return project.metronome

    def processRECEvent(eventId: int, value: int, flags: int) -> None:
        """Recording events. Modelled only far enough to be observable.

        Writing tempo is research spike T1 and its flags are unverified, so this
        records the call rather than pretending to change the tempo.
        """
        project.rec_events.append((eventId, value, flags))

    module.getVersion = getVersion
    module.safeToEdit = safeToEdit
    module.getRecPPQ = getRecPPQ
    module.getRecPPB = getRecPPB
    module.getChangedFlag = getChangedFlag
    module.saveUndo = saveUndo
    module.undo = undo
    module.restoreUndo = restoreUndo
    module.restoreUndoLevel = restoreUndoLevel
    module.getUndoHistoryCount = getUndoHistoryCount
    module.getUndoHistoryPos = getUndoHistoryPos
    module.getUndoLevelHint = getUndoLevelHint
    module.getUseMetronome = getUseMetronome
    module.processRECEvent = processRECEvent

    module.UF_None = UF_None
    module.UF_UndoLevel = UF_UndoLevel
    return module
