"""Fake flpianoroll module.

This is the piano roll sandbox's only FL module, which is why the two
communication paths exist and cannot be merged: `channels` does not exist here,
and `flpianoroll` does not exist in the controller sandbox.

flpianoroll.Note has sixteen properties. All of them are present, because Phase 4
writes expression through them and this fake is the only place that work can be
tested without a human at the keyboard.

Markers are here too. `arrangement.getMarkers` in the controller sandbox can read a
marker's name and not its time, and flpianoroll is the only sandbox where a time can
be read, so this is where the structure critique gets one. The fake models the stubs
(markerCount, getMarker, Marker.name, Marker.time); the stubs are not the runtime, so
the script probes for the accessors before using them.
"""

from __future__ import annotations

from types import ModuleType

from tests.fakes.project import FakeProject, Marker, Note


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

        @property
        def markerCount(self) -> int:
            """How many markers this sandbox sees.

            The stubs define markerCount and getMarker on Score, and Marker carries a
            name and a time in ticks. Whether the running piano roll sandbox has them
            is a different question that only a live FL Studio can answer, which is
            why the script probes for them and reports their absence rather than
            assuming them. This fake models the stubs, so a live disagreement shows up
            as a mismatch against the arrangement rather than as a silent zero.
            """
            return len(self._project.piano_roll_markers)

        def getMarker(self, index: int) -> Marker:
            if not 0 <= index < len(self._project.piano_roll_markers):
                raise IndexError(f"marker index {index} out of range")
            return self._project.piano_roll_markers[index]

        def getNextFreeGroupIndex(self):
            """The next free group index, advancing so two groups are not one.

            A method on the score object, which is where the stubs define it. Group
            0 is the ungrouped state, so the first assignable index is 1.
            """
            self._project.group_index += 1
            return self._project.group_index

    module.Note = Note
    module.Marker = Marker
    module.score = _Score(project)
    module.setHasSeenWelcome = lambda: None

    del score
    return module
