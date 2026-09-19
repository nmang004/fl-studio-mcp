"""Fake plugins module.

plugins can control loaded plugins but cannot load one, which is a real limit
confirmed against the stubs and stated in ROADMAP.md. There is no load, add or
insert function here, and adding one would be the harness inventing capability.
"""

from __future__ import annotations

from types import ModuleType

from tests.fakes.project import FakeProject, clamp

PARAM_COUNT = 8


def _params(project: FakeProject, index: int, slot: int) -> dict[int, float]:
    return project.plugin_params.setdefault((index, slot), {})


def build(project: FakeProject) -> ModuleType:
    module = ModuleType("plugins")

    def isValid(index: int, slotIndex: int = -1, useGlobalIndex: bool = False) -> bool:
        """True only for a slot the fake project has been given.

        Nothing is loaded by default, so this is False until a test says
        otherwise. That keeps "cannot load plugins" visible rather than implied.
        """
        project.channel(index)
        return (index, slotIndex) in project.plugin_params or (
            slotIndex == -1 and (index, -1) in project.plugin_params
        )

    def getPluginName(
        index: int, slotIndex: int = -1, useGlobalIndex: bool = False
    ) -> str:
        project.channel(index)
        if not isValid(index, slotIndex):
            return ""
        return project.plugin_names.get((index, slotIndex), "Fake Plugin")

    def getParamCount(
        index: int, slotIndex: int = -1, useGlobalIndex: bool = False
    ) -> int:
        project.channel(index)
        if not isValid(index, slotIndex):
            return 0
        return PARAM_COUNT

    def getParamName(
        paramIndex: int,
        index: int,
        slotIndex: int = -1,
        useGlobalIndex: bool = False,
    ) -> str:
        project.channel(index)
        if not 0 <= paramIndex < PARAM_COUNT:
            raise IndexError(f"parameter {paramIndex} out of range")
        return f"Param {paramIndex}"

    def getParamValue(
        paramIndex: int,
        index: int,
        slotIndex: int = -1,
        useGlobalIndex: bool = False,
    ) -> float:
        project.channel(index)
        if not 0 <= paramIndex < PARAM_COUNT:
            raise IndexError(f"parameter {paramIndex} out of range")
        return _params(project, index, slotIndex).get(paramIndex, 0.5)

    def getParamValueString(
        paramIndex: int,
        index: int,
        slotIndex: int = -1,
        useGlobalIndex: bool = False,
    ) -> str:
        return f"{getParamValue(paramIndex, index, slotIndex, useGlobalIndex):.3f}"

    def setParamValue(
        value: float,
        paramIndex: int,
        index: int,
        slotIndex: int = -1,
        useGlobalIndex: bool = False,
    ) -> None:
        project.channel(index)
        if not 0 <= paramIndex < PARAM_COUNT:
            raise IndexError(f"parameter {paramIndex} out of range")
        _params(project, index, slotIndex)[paramIndex] = clamp(value, 0.0, 1.0)

    def getPresetCount(
        index: int, slotIndex: int = -1, useGlobalIndex: bool = False
    ) -> int:
        project.channel(index)
        return 0

    def nextPreset(index: int, slotIndex: int = -1, useGlobalIndex: bool = False) -> None:
        project.channel(index)

    def prevPreset(index: int, slotIndex: int = -1, useGlobalIndex: bool = False) -> None:
        project.channel(index)

    def getColor(index: int, slotIndex: int = -1, useGlobalIndex: bool = False) -> int:
        project.channel(index)
        return 0x808080

    module.isValid = isValid
    module.getPluginName = getPluginName
    module.getParamCount = getParamCount
    module.getParamName = getParamName
    module.getParamValue = getParamValue
    module.getParamValueString = getParamValueString
    module.setParamValue = setParamValue
    module.getPresetCount = getPresetCount
    module.nextPreset = nextPreset
    module.prevPreset = prevPreset
    module.getColor = getColor
    return module
