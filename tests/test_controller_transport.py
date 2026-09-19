"""Transport handlers must match the API's actual signatures.

transport.setLoopMode takes no argument and toggles, and transport.setSongPos
defaults its mode to -1, the same units getSongPosHint returns. Both handlers
were passing made-up arguments, which fails silently inside FL.
"""

from __future__ import annotations

from tests.helpers import load_controller


class FakeTransport:
    """Records calls, so a test can assert on the arguments the handler used."""

    def __init__(self, loop_mode: int = 0) -> None:
        self.calls: list[tuple] = []
        self._loop_mode = loop_mode

    def setLoopMode(self) -> None:
        self.calls.append(("setLoopMode",))
        self._loop_mode = 1 - self._loop_mode

    def getLoopMode(self) -> int:
        return self._loop_mode

    def setSongPos(self, position, mode=-1) -> None:
        self.calls.append(("setSongPos", position, mode))

    def getSongPosHint(self) -> str:
        return "1:01:00"


def load(monkeypatch, tmp_path, transport):
    monkeypatch.setenv("FL_STUDIO_MCP_SETTINGS_DIR", str(tmp_path))
    return load_controller(monkeypatch, {"transport": transport})


def test_set_loop_mode_calls_the_toggle_exactly_once(monkeypatch, tmp_path):
    transport = FakeTransport(loop_mode=0)
    controller = load(monkeypatch, tmp_path, transport)
    result = controller.handle_transport_set_loop_mode({"mode": "song"})
    assert transport.calls == [("setLoopMode",)]
    assert result["mode"] == "song"


def test_set_loop_mode_does_not_toggle_when_already_there(monkeypatch, tmp_path):
    """Toggling unconditionally would flip away from the requested mode."""
    transport = FakeTransport(loop_mode=1)
    controller = load(monkeypatch, tmp_path, transport)
    result = controller.handle_transport_set_loop_mode({"mode": "song"})
    assert transport.calls == []
    assert result["mode"] == "song"


def test_set_position_defaults_to_hint_units(monkeypatch, tmp_path):
    transport = FakeTransport()
    controller = load(monkeypatch, tmp_path, transport)
    controller.handle_transport_set_position({"position": 0})
    assert transport.calls == [("setSongPos", 0, -1)]


def test_set_position_passes_an_explicit_mode_through(monkeypatch, tmp_path):
    transport = FakeTransport()
    controller = load(monkeypatch, tmp_path, transport)
    controller.handle_transport_set_position({"position": 8, "mode": 2})
    assert transport.calls == [("setSongPos", 8, 2)]


def test_set_position_reports_where_it_landed(monkeypatch, tmp_path):
    transport = FakeTransport()
    controller = load(monkeypatch, tmp_path, transport)
    assert controller.handle_transport_set_position({"position": 0})["position"] == "1:01:00"
