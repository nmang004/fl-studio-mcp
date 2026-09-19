"""Verify the live FL Studio connection and reproduce the known transport bugs.

Run this with FL Studio open and the FLStudioMCP controller enabled. It exercises
the real code path in `fl_studio_mcp.utils.midi_connection`, so what it reports is
what the MCP server would experience.

Every check here is read-only. Nothing modifies the open project.

Usage:
    uv run python scripts/dev_verify_connection.py
"""

from __future__ import annotations

import statistics
import time

from fl_studio_mcp.utils.midi_connection import get_connection


def _hr(title: str) -> None:
    print(f"\n{title}\n{'-' * len(title)}")


def check_port() -> bool:
    _hr("1. MIDI port")
    conn = get_connection()
    if not conn.connect():
        print(f"FAIL: {conn.connection_error}")
        return False
    status = conn.get_status()
    print(f"opened port : {status['port_name']}")
    print(f"all outputs : {status['available_ports']}")
    print(f"command file: {status['command_file']}")
    return True


def check_roundtrip() -> bool:
    _hr("2. Round trip")
    conn = get_connection()
    result = conn.send_command("transport.getStatus", timeout=3.0)
    if not result.get("success"):
        print(f"FAIL: {result.get('error')}")
        print("\nFL Studio is not answering. Check that:")
        print("  - FL Studio was restarted after the controller script was installed")
        print("  - Options > MIDI Settings has the port enabled")
        print("  - Controller type is set to 'FL Studio MCP Controller'")
        return False
    print(f"OK: {result}")
    return True


def check_environment() -> None:
    """Report which FL Studio and API version we are actually targeting."""
    _hr("3. Environment")
    conn = get_connection()
    result = conn.send_command("system.getInfo", timeout=3.0)
    if not result.get("success"):
        print(f"unavailable: {result.get('error')}")
        print("if this says unknown action, reinstall the controller script")
        return
    caps = result.get("capabilities", {})
    tempo = caps.get("getCurrentTempo")
    print(f"FL Studio   : {result.get('fl_version')}")
    print(f"title       : {result.get('program_title')}")
    print(f"API version : {result.get('api_version')}")
    print(f"safeToEdit  : {caps.get('safeToEdit')}")
    if isinstance(tempo, (int, float)):
        print(f"tempo       : {tempo} raw, so {tempo / 1000:g} BPM (thousandths of a BPM)")


def check_latency(n: int = 10) -> None:
    _hr(f"4. Latency over {n} round trips")
    conn = get_connection()
    times = []
    for _ in range(n):
        start = time.perf_counter()
        result = conn.send_command("transport.getStatus", timeout=3.0)
        elapsed = (time.perf_counter() - start) * 1000
        if result.get("success"):
            times.append(elapsed)
    if not times:
        print("FAIL: no successful round trips")
        return
    median = statistics.median(times)
    print(f"min {min(times):.1f}ms  median {median:.1f}ms  max {max(times):.1f}ms")
    print(f"a 16 note pattern at this rate costs ~{median * 16:.0f}ms")
    if median > 10:
        print("SLOW: expect ~1ms. A flat 20ms poll interval was the original cause.")


def check_unknown_action_bug() -> None:
    """Audit bug 2: unknown actions were reported as successes.

    Fixed in the controller on 2026-09-19. Kept as a regression check, because
    the fix is three lines and the failure is invisible: a caller reading only
    `success` acts on a command that never ran.
    """
    _hr("5. Check: unknown action reported as success (was a bug)")
    conn = get_connection()
    result = conn.send_command("bogus.doesNotExist", timeout=3.0)
    if result.get("success") is True and "error" in result:
        print(f"REGRESSED: success=True alongside error={result['error']!r}")
        print("cause: dispatch_command returns {'error': ...} and the caller")
        print("merges it into {'success': True, **result}")
    elif result.get("success") is False and "error" in result:
        print(f"OK: reported as failure, error={result['error']!r}")
    else:
        print(f"UNEXPECTED: {result}")


def check_double_execution_bug() -> None:
    """Audit bug 1: an abandoned command makes the NEXT command execute twice.

    There are no request IDs, so a trigger note is just "run whatever is in the
    command file now". Timing out does not cancel the trigger already in flight.

    Sequence, with FL taking roughly 23ms to service a trigger:
        t=0     write command A, send trigger A, give up after 1ms
        t=1ms   write command B, send trigger B
        t=23ms  FL services trigger A, reads the file, finds B, runs B
        t=46ms  FL services trigger B, reads the file, finds B, runs B again

    Command B therefore runs twice. For a read this is invisible. For a toggle
    (play, record, arm, mute without an explicit value) the second run cancels
    the first, which is why playback appears not to respond.

    Detected here by counting how many times FL writes a response, which is
    read-only: the probe command is a track count.
    """
    _hr("6. Bug: an abandoned command makes the next one run twice")
    conn = get_connection()
    response_file = conn._response_file  # noqa: SLF001 - diagnostic script
    command_file = conn._command_file  # noqa: SLF001 - diagnostic script

    # Settle, so nothing from earlier checks is still in flight.
    conn.send_command("transport.getStatus", timeout=3.0)
    time.sleep(0.5)
    if response_file.exists():
        response_file.unlink()

    # Command A, abandoned after 1ms. Its trigger is still in flight.
    abandoned = conn.send_command("mixer.getTrackCount", timeout=0.001)
    print(f"abandoned call (1ms timeout) -> {str(abandoned)[:60]}")

    # Command B, written and triggered while A's trigger is unserviced.
    command_file.write_text(
        '{"action": "mixer.getTrackCount", "params": {}}'
    )
    if response_file.exists():
        response_file.unlink()

    import mido

    conn._port.send(mido.Message("note_on", note=127, velocity=127))  # noqa: SLF001

    # Count distinct response writes over a window longer than two round trips.
    executions = 0
    deadline = time.time() + 2.0
    while time.time() < deadline:
        if response_file.exists():
            executions += 1
            response_file.unlink()
        time.sleep(0.005)

    print(f"responses written for a single follow-up command: {executions}")
    if executions >= 2:
        print("\nREPRODUCED: FL executed the follow-up command twice.")
        print("On a toggle such as fl_play or fl_record the second run cancels")
        print("the first, so the tool reports success and nothing happens.")
        print("Fix: request IDs, so a stale trigger finds no matching work.")
    elif executions == 1:
        print("\nnot reproduced on this run; the race depends on FL's servicing")
        print("time relative to the timeout. The missing correlation is")
        print("structural regardless, and two MCP clients hit it with no timeout.")
    else:
        print("\ninconclusive: no response observed at all.")


def main() -> int:
    print("FL Studio MCP live connection check")
    print("All checks are read-only.")

    if not check_port():
        return 1
    if not check_roundtrip():
        return 1

    check_environment()
    check_latency()
    check_unknown_action_bug()
    check_double_execution_bug()

    _hr("Done")
    print("Findings above are evidence for the Phase 1 work in ROADMAP.md.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
