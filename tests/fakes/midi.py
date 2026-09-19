"""A mido stand-in that delivers the trigger note to the in-process controller.

The real transport is: write a command file, send note 127, FL reads the file.
The fake keeps every part of that except the MIDI cable, so the round trip test
covers both scripts and both file formats while staying deterministic.

mido.Message is the real class. It is pure Python and needs no port layer, so
faking it would only add a way for the tests to be wrong.
"""

from __future__ import annotations

from types import ModuleType
from typing import Callable

import mido

TRIGGER_NOTE = 127


class FakeMidiPort:
    """Accepts messages and hands each one to a callback."""

    def __init__(self, name: str, on_send: Callable[[object], None] | None = None) -> None:
        self.name = name
        self._on_send = on_send
        self.sent: list[object] = []
        self.closed = False

    def send(self, message) -> None:
        self.sent.append(message)
        if self._on_send is not None:
            self._on_send(message)

    def close(self) -> None:
        self.closed = True


class FakeMidiModule(ModuleType):
    """Just enough of mido for MIDIConnection.connect and send_command."""

    def __init__(self, port: FakeMidiPort, output_names: list[str] | None = None) -> None:
        super().__init__("mido")
        self.Message = mido.Message
        self._port = port
        self._output_names = output_names

    def get_output_names(self) -> list[str]:
        if self._output_names is not None:
            return list(self._output_names)
        return [self._port.name]

    def get_input_names(self) -> list[str]:
        return []

    def open_output(self, name: str | None = None, virtual: bool = False) -> FakeMidiPort:
        return self._port

    def open_input(self, name: str | None = None, virtual: bool = False) -> FakeMidiPort:
        return self._port
