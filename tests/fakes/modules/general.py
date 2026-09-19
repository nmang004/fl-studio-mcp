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
        """Append one history entry, or as many as the project models.

        Real FL decides this itself: a batch of channel writes costs one entry
        while mixer writes cost more, which was measured live. The project carries
        the number so a test can exercise both cases.
        """
        for _ in range(max(1, project.undo_entries_per_write)):
            project.undo_stack.append(undoName)

    def getUndoHistoryLast() -> int:
        """Position in the history.

        The stub says the most recent position is 0 and earlier points have higher
        indexes, which would make this 0 always. Live FL Studio 2026 also returned
        0 after every edit, so the fake matches that rather than inventing a
        position the real API does not report.
        """
        return 0

    def undoUpDown(value: int) -> None:
        """Move by a count. Negative undoes, positive redoes."""
        if value < 0:
            for _ in range(min(-value, len(project.undo_stack))):
                project.undo_stack.pop()

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
    module.getUndoHistoryLast = getUndoHistoryLast
    module.undoUpDown = undoUpDown
    module.getUndoHistoryPos = getUndoHistoryPos
    module.getUndoLevelHint = getUndoLevelHint
    module.getUseMetronome = getUseMetronome
    module.processRECEvent = processRECEvent

    module.UF_None = UF_None
    module.UF_UndoLevel = UF_UndoLevel
    return module
