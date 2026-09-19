"""Fake ui module.

ui.getVersion takes a mode and returns different strings for each, which the
docs rely on, so the fake mirrors that rather than returning one fixed string.
"""

from __future__ import annotations

from types import ModuleType

from tests.fakes.project import FakeProject

# From the stubs: ui.getVersion modes.
VERSION_BUILD = 0
VERSION_SHORT = 4

PROGRAM_TITLE = "FL Studio 2026"
VERSION_STRING = "Producer Edition v26.1.6 [build 5406]"


def build(project: FakeProject) -> ModuleType:
    module = ModuleType("ui")

    def getVersion(mode: int = VERSION_SHORT) -> str:
        if mode == VERSION_BUILD:
            return "5406"
        return VERSION_STRING

    def getProgTitle() -> str:
        return PROGRAM_TITLE

    def showWindow(index: int) -> None:
        project.ui_state["visible_%d" % index] = True

    def hideWindow(index: int) -> None:
        project.ui_state["visible_%d" % index] = False

    def getVisible(index: int) -> bool:
        return bool(project.ui_state.get("visible_%d" % index, False))

    def getFocused(index: int) -> bool:
        return project.focused_window == index

    def setFocused(index: int) -> None:
        project.focused_window = index

    def getFocusedFormCaption() -> str:
        return ""

    def getFocusedNodeCaption() -> str:
        return project.focused_node_caption

    def getSnapMode() -> int:
        return project.snap_mode

    def setSnapMode(value: int) -> None:
        project.snap_mode = value

    def showNotification(notificationId: int) -> None:
        project.notifications.append(notificationId)

    def navigateBrowser(direction: int, shiftHeld: bool) -> None:
        project.browser_calls.append(("navigateBrowser", direction, shiftHeld))

    def previewBrowserMenuItem() -> None:
        project.browser_calls.append(("previewBrowserMenuItem",))

    def selectBrowserMenuItem() -> None:
        project.browser_calls.append(("selectBrowserMenuItem",))

    def getHintMsg() -> str:
        return str(project.ui_state.get("hint", ""))

    def setHintMsg(msg: str) -> None:
        project.ui_state["hint"] = msg

    def isMetronomeEnabled() -> bool:
        return project.metronome

    module.getVersion = getVersion
    module.getProgTitle = getProgTitle
    module.showWindow = showWindow
    module.hideWindow = hideWindow
    module.getVisible = getVisible
    module.getFocused = getFocused
    module.setFocused = setFocused
    module.getFocusedFormCaption = getFocusedFormCaption
    module.getFocusedNodeCaption = getFocusedNodeCaption
    module.getSnapMode = getSnapMode
    module.setSnapMode = setSnapMode
    module.showNotification = showNotification
    module.navigateBrowser = navigateBrowser
    module.previewBrowserMenuItem = previewBrowserMenuItem
    module.selectBrowserMenuItem = selectBrowserMenuItem
    module.getHintMsg = getHintMsg
    module.setHintMsg = setHintMsg
    module.isMetronomeEnabled = isMetronomeEnabled

    module.VERSION_BUILD = VERSION_BUILD
    module.VERSION_SHORT = VERSION_SHORT
    return module
