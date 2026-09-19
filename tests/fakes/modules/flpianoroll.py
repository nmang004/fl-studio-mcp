"""Fake flpianoroll module.

This is the piano roll sandbox's only FL module, which is why the two
communication paths exist and cannot be merged: `channels` does not exist here,
and `flpianoroll` does not exist in the controller sandbox.

flpianoroll.Note has sixteen properties. All of them are present, because Phase 4
writes expression through them and this fake is the only place that work can be
tested without a human at the keyboard.
"""

from __future__ import annotations

from types import ModuleType

from tests.fakes.project import FakeProject, Note


def build(project: FakeProject) -> ModuleType:
    module = ModuleType("flpianoroll")

    score = ModuleType("flpianoroll.score")

    class _Score:
        """The score object the piano roll script reads and writes."""

        def __init__(self, project: FakeProject) -> None:
            self._project = project

        @property
        def PPQ(self) -> int:
            return self._project.ppq

        @property
        def noteCount(self) -> int:
            return len(self._project.notes)

        @property
        def snap_root_note(self) -> int:
            return self._project.snap_root_note

        @snap_root_note.setter
        def snap_root_note(self, value: int) -> None:
            self._project.snap_root_note = value

        @property
        def snap_scale_helper(self) -> int:
            return self._project.snap_scale_helper

        @property
        def tsnum(self) -> int:
            return self._project.tsnum

        @property
        def tsden(self) -> int:
            return self._project.tsden

        def getNote(self, index: int) -> Note:
            if not 0 <= index < len(self._project.notes):
                raise IndexError(f"note index {index} out of range")
            return self._project.notes[index]

        def addNote(self, note: Note) -> None:
            self._project.notes.append(note)

        def deleteNote(self, index: int) -> None:
            if not 0 <= index < len(self._project.notes):
                raise IndexError(f"note index {index} out of range")
            del self._project.notes[index]

        def getTimelineSelection(self):
            """The region the user highlighted, as (start, end) in ticks."""
            return self._project.timeline_selection

    module.Note = Note
    module.score = _Score(project)
    module.getNextFreeGroupIndex = lambda: project.group_index
    module.setHasSeenWelcome = lambda: None

    del score
    return module
