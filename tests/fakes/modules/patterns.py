"""Fake patterns module.

patterns.findFirstNextEmptyPat exists in the stubs, which is why "cannot create
patterns" in the upstream README is overstated: selecting the next empty pattern
and writing into it is creation in practice. That is modelled here, so Phase 3 can
test it.
"""

from __future__ import annotations

from types import ModuleType

from tests.fakes.project import FakeProject, Pattern


def build(project: FakeProject) -> ModuleType:
    module = ModuleType("patterns")

    def patternCount() -> int:
        return len(project.patterns)

    def patternNumber() -> int:
        return project.current_pattern

    def patternMax() -> int:
        return 999

    def selectPattern(
        index: int, options: int = 0, preview: bool = False, force: bool = False
    ) -> None:
        if not 0 <= index < len(project.patterns):
            raise IndexError(f"pattern index {index} out of range")
        project.current_pattern = index

    def jumpToPattern(index: int) -> None:
        selectPattern(index)

    def findFirstNextEmptyPat(flags: int, x: int = -1, y: int = -1) -> int:
        """Select the first pattern that has no notes, creating one if needed.

        A pattern counts as empty when no note in the project points at it. The
        fake tracks that with `project.notes_by_pattern` rather than guessing.
        """
        used = set(project.notes_by_pattern)
        for i in range(len(project.patterns)):
            if i not in used:
                project.current_pattern = i
                return i
        project.patterns.append(Pattern(f"Pattern {len(project.patterns) + 1}"))
        project.notes_by_pattern.setdefault(len(project.patterns) - 1, [])
        project.current_pattern = len(project.patterns) - 1
        return project.current_pattern

    def clonePattern(index: int | None = None) -> int:
        source = project.current_pattern if index is None else index
        project.pattern(source)
        project.patterns.append(Pattern(project.pattern(source).name + " copy"))
        return len(project.patterns) - 1

    def getPatternName(index: int) -> str:
        return project.pattern(index).name

    def setPatternName(index: int, name: str) -> None:
        project.pattern(index).name = name

    def getPatternColor(index: int) -> int:
        return project.pattern(index).color

    def setPatternColor(index: int, color: int) -> None:
        project.pattern(index).color = int(color)

    def getPatternLength(index: int) -> int:
        return project.pattern(index).length

    def isPatternDefault(index: int) -> bool:
        pattern = project.pattern(index)
        return pattern.name == f"Pattern {index + 1}" and pattern.color == 0x808080

    def isPatternSelected(index: int) -> bool:
        return project.current_pattern == index

    def deselectAll() -> None:
        project.current_pattern = -1

    module.patternCount = patternCount
    module.patternNumber = patternNumber
    module.patternMax = patternMax
    module.selectPattern = selectPattern
    module.jumpToPattern = jumpToPattern
    module.findFirstNextEmptyPat = findFirstNextEmptyPat
    module.clonePattern = clonePattern
    module.getPatternName = getPatternName
    module.setPatternName = setPatternName
    module.getPatternColor = getPatternColor
    module.setPatternColor = setPatternColor
    module.getPatternLength = getPatternLength
    module.isPatternDefault = isPatternDefault
    module.isPatternSelected = isPatternSelected
    module.deselectAll = deselectAll
    return module
