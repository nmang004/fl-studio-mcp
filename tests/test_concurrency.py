"""Two clients on one machine must not cross-talk.

The command file and the response file are each a single shared slot. Two writers
interleave there no matter how good the correlation is, so a whole request cycle
is serialised. This is the failure the audit described, and it needs no timeout,
only a second client.
"""

from __future__ import annotations

import threading

import pytest

from fl_studio_mcp.utils.midi_connection import MIDIConnection


@pytest.fixture
def connection(fl_env):
    """A MIDIConnection wired to the in-process controller."""
    conn = MIDIConnection()
    conn._command_file = fl_env.command_file
    conn._response_file = fl_env.response_file
    conn._port = fl_env.midi_port
    conn._port_name = fl_env.midi_port.name
    conn._connected = True
    return conn


def _run_all(targets):
    """Start every target at once and return the collected failures."""
    barrier = threading.Barrier(len(targets))
    failures = []
    lock = threading.Lock()

    def wrapped(index, fn):
        try:
            barrier.wait(timeout=10)
            fn()
        except Exception as error:  # noqa: BLE001 - collected and asserted on
            with lock:
                failures.append(f"{index}: {type(error).__name__}: {error}")

    threads = [
        threading.Thread(target=wrapped, args=(i, fn)) for i, fn in enumerate(targets)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
    return failures


def test_concurrent_commands_each_get_their_own_answer(connection):
    """Ten threads asking two different questions get ten correct answers."""
    results: dict[int, object] = {}
    lock = threading.Lock()

    def ask(index: int):
        def call():
            action = "mixer.getTrackCount" if index % 2 == 0 else "channels.getCount"
            reply = connection.send_command(action, timeout=10.0)
            with lock:
                results[index] = reply.get("count")

        return call

    failures = _run_all([ask(i) for i in range(10)])

    assert not failures, failures
    assert len(results) == 10, f"only {len(results)} of 10 calls returned"
    for index, value in results.items():
        expected = 8 if index % 2 == 0 else 4
        assert value == expected, f"thread {index} got {value}, expected {expected}"


def test_no_caller_receives_another_callers_reply(connection):
    """A mixer question must never come back with a channel count."""
    counts: dict[str, list] = {"mixer.getTrackCount": [], "channels.getCount": []}
    lock = threading.Lock()

    def ask(action: str):
        def call():
            reply = connection.send_command(action, timeout=10.0)
            with lock:
                counts[action].append(reply.get("count"))

        return call

    failures = _run_all([ask("mixer.getTrackCount"), ask("channels.getCount")])

    assert not failures, failures
    assert counts["mixer.getTrackCount"] == [8]
    assert counts["channels.getCount"] == [4]


def test_the_lock_is_reentrant(connection):
    """A caller holding the lock must be able to compose smaller calls."""
    with connection._lock:
        assert connection.send_command("mixer.getTrackCount", timeout=5.0)["count"] == 8
