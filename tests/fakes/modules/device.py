"""Fake device module.

Only the parts the controller and the SysEx probe touch. `isAssigned` and
`getPortNumber` earned their place here: measuring them on live FL Studio showed
that isAssigned tracks whether an output port shares the port number configured
for the controller's input row, which is the whole of the spike T4 finding.
"""

from __future__ import annotations

from types import ModuleType

from tests.fakes.project import FakeProject


def build(project: FakeProject) -> ModuleType:
    module = ModuleType("device")

    def isAssigned() -> bool:
        return project.device_assigned

    def getPortNumber() -> int:
        return project.device_port_number

    def getName() -> str:
        return "FL Studio MCP"

    def midiOutMsg(message: int, channel: int = -1, data1: int = -1, data2: int = -1) -> None:
        if not project.device_assigned:
            raise RuntimeError("no output interface is linked to this script")
        project.midi_out.append((message, channel, data1, data2))

    def midiOutSysex(message: bytes) -> None:
        """The real one silently ignores a message without F0 and F7 framing."""
        if not message.startswith(b"\xf0") or not message.endswith(b"\xf7"):
            return
        if not project.device_assigned:
            raise RuntimeError("no output interface is linked to this script")
        project.sysex_sent.append(message)

    def getMasterSync() -> bool:
        return False

    def setMasterSync(value: bool) -> None:
        project.ui_state["master_sync"] = value

    def getDeviceID() -> bytes:
        return b""

    module.isAssigned = isAssigned
    module.getPortNumber = getPortNumber
    module.getName = getName
    module.midiOutMsg = midiOutMsg
    module.midiOutSysex = midiOutSysex
    module.getMasterSync = getMasterSync
    module.setMasterSync = setMasterSync
    module.getDeviceID = getDeviceID
    return module
