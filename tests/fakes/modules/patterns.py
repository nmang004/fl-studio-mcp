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
        """The 1-based number of the current pattern.

        Measured on live FL Studio 2026: this returns 1 while no pattern is
        selected at all, and 1 for the first pattern, so it is a number rather
        than an index. The controller subtracts one to report an index.
        """
        return project.current_pattern + 1

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
        """Select the first pattern that holds no notes.

        A pattern counts as empty when it is not in `notes_by_pattern`, which is
        the fake's record of which patterns have notes and which do not. A pattern
        that exists but has never been written into is therefore empty, not
        occupied: that is the actual meaning of the function's name, and it is
        what makes calling it twice in a row safe.
        """
        used = {index for index, notes in project.notes_by_pattern.items() if notes}
        for i in range(len(project.patterns)):
            if i not in used:
                project.current_pattern = i
                return i
        project.patterns.append(Pattern(f"Pattern {len(project.patterns)}"))
        project.current_pattern = len(project.patterns) - 1
        return project.current_pattern

    def clonePattern(index: int | None = None) -> int:
        """Copy a pattern. The length comes too, because a copy that is a
        different length is not a copy."""
        source = project.current_pattern if index is None else index
        original = project.pattern(source)
        project.patterns.append(
            Pattern(original.name + " copy", original.color, original.length)
        )
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

    def isPatternDefault(number: int) -> bool:
        """Whether pattern `number` is an untouched default.

        1-based, matching live FL Studio 2026, where isPatternDefault(0) raises
        "Index out of range" and the first pattern is number 1. FL's own default
        names are "Pattern 0", "Pattern 1", and so on, so the name for number n is
        "Pattern {n - 1}".
        """
        pattern = project.pattern(number - 1)
        return pattern.name == f"Pattern {number - 1}" and pattern.color == 0x808080

    def isPatternSelected(number: int) -> bool:
        """Whether pattern `number` is current. 1-based, as on live FL."""
        return project.current_pattern == number - 1

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
