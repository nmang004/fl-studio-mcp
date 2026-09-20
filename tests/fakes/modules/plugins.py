"""Fake plugins module.

plugins can control loaded plugins but cannot load one, which is a real limit
confirmed against the stubs and stated in ROADMAP.md. There is no load, add or
insert function here, and adding one would be the harness inventing capability.
"""

from __future__ import annotations

from types import ModuleType

from tests.fakes.project import FakeProject, clamp

PARAM_COUNT = 8

# From midi/__pickup_modes.py and the colour flag the stub declares as the default of
# plugins.getColor. Named rather than written as bare numbers so a test can say which
# one it means.
PIM_None = 0
PIM_AlwaysPickup = 1
PIM_FollowGlobal = 2
GC_BackgroundColor = 0
GC_Semitone = 1


def _params(project: FakeProject, index: int, slot: int) -> dict[int, float]:
    return project.plugin_params.setdefault((index, slot), {})


def build(project: FakeProject) -> ModuleType:
    module = ModuleType("plugins")

    def isValid(index: int, slotIndex: int = -1, useGlobalIndex: bool = False) -> bool:
        """True only for a slot the fake project has been given.

        Nothing is loaded by default, so this is False until a test says
        otherwise. That keeps "cannot load plugins" visible rather than implied.

        A mixer slot is addressed by track index with slotIndex >= 0, and a track is
        not a channel, so the channel check belongs to the channel rack case only.
        Requiring one for every call made every mixer slot raise.
        """
        if slotIndex < 0:
            project.channel(index)
        return (index, slotIndex) in project.plugin_params or (
            slotIndex == -1 and (index, -1) in project.plugin_params
        )

    def getPluginName(
        index: int,
        slotIndex: int = -1,
        userName: bool = False,
        useGlobalIndex: bool = False,
    ) -> str:
        """The plugin's own name, or the name the user gave it when asked.

        The real signature is `(index, slotIndex, userName, useGlobalIndex)`, read from
        `plugins/__init__.py:89`. The controller used to pass `use_global` in the
        `userName` slot, so it always reported the user's name, and this fake had the
        same wrong signature and agreed with it.
        """
        if slotIndex < 0:
            project.channel(index)
        if not isValid(index, slotIndex):
            return ""
        if userName:
            return project.plugin_user_names.get(
                (index, slotIndex), project.plugin_names.get((index, slotIndex), "Fake Plugin")
            )
        return project.plugin_names.get((index, slotIndex), "Fake Plugin")

    def getParamCount(
        index: int, slotIndex: int = -1, useGlobalIndex: bool = False
    ) -> int:
        # A mixer slot is addressed by track index with slotIndex >= 0, and an empty
        # slot answers zero rather than raising: the real API asks about every slot.
        # Requiring a channel first made every mixer slot look like a broken channel.
        if slotIndex < 0:
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
        if slotIndex < 0:
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
        if slotIndex < 0:
            project.channel(index)
        if not 0 <= paramIndex < PARAM_COUNT:
            raise IndexError(f"parameter {paramIndex} out of range")
        return _params(project, index, slotIndex).get(paramIndex, 0.5)

    def getParamValueString(
        paramIndex: int,
        index: int,
        slotIndex: int = -1,
        pickupMode: int = PIM_None,
        useGlobalIndex: bool = False,
    ) -> str:
        """The display string. Its fourth argument is pickupMode, not the index flag."""
        project.plugin_calls.append(
            ("getParamValueString", {"pickupMode": pickupMode, "useGlobalIndex": useGlobalIndex})
        )
        return f"{getParamValue(paramIndex, index, slotIndex, useGlobalIndex):.3f}"

    def setParamValue(
        value: float,
        paramIndex: int,
        index: int,
        slotIndex: int = -1,
        pickupMode: int = 0,
        useGlobalIndex: bool = False,
    ) -> None:
        """The fifth argument is pickupMode, and a scripted write wants PIM_None."""
        project.plugin_calls.append(
            ("setParamValue", {"pickupMode": pickupMode, "useGlobalIndex": useGlobalIndex})
        )
        if slotIndex < 0:
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

    def getColor(
        index: int,
        slotIndex: int = -1,
        flag: int = GC_BackgroundColor,
        useGlobalIndex: bool = False,
    ) -> int:
        """The third argument is a colour flag: 0 background, 1 semitone."""
        project.plugin_calls.append(
            ("getColor", {"flag": flag, "useGlobalIndex": useGlobalIndex})
        )
        if slotIndex < 0:
            project.channel(index)
        return GC_BackgroundColor if flag == GC_BackgroundColor else 0x00FF00

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
