"""The tempo write probe: what it reports, and what it refuses.

Reading tempo is settled. `mixer.getCurrentTempo()` returned 130000 on a 130 BPM
project in the Phase 0 run, which fixes the unit as thousandths of a BPM. Writing
it is not settled: no module in the API has a tempo setter, and the only candidate,
`general.processRECEvent` with `midi.REC_Tempo`, carries a stub docstring that
advises against using it at all because the REC event layer is incomplete, poorly
documented and full of hidden bugs.

So these tests deliberately do not assert that a tempo write works. They assert
the shape of the probe's report, that a refusal names the field it refused, and
that every failure arrives as an "error" field instead of an exception.

The fake's `processRECEvent` can be configured to store the value, and two tests
below use that to exercise the probe's before and after arithmetic. That fake is a
model of one possible FL Studio and is not evidence about the real one. The
measurement needs a live run, which `docs/spikes/2026-09-19-T1-tempo-write.md`
describes.
"""

from __future__ import annotations

import pytest

from tests.fakes.modules.midi import REC_Tempo, REC_UpdateControl, REC_UpdateValue

# The flag word the probe uses unless a caller overrides it.
DEFAULT_FLAGS = REC_UpdateValue | REC_UpdateControl

# Every key a report carries, pinned so a caller can rely on the shape rather
# than discovering a missing field at the far end of a live run.
REPORT_KEYS = {
    "event_id",
    "requested_bpm",
    "requested_value",
    "tempo_before",
    "bpm_before",
    "flags",
    "flag_names",
    "process_rec_result",
    "tempo_after",
    "bpm_after",
    "changed",
    "write_verified",
    "restore",
    "tempo_restored",
    "bpm_restored",
    "restore_verified",
}


def test_the_probe_reports_the_value_before_the_value_after_and_the_flags(fl_env):
    """A run against an FL that ignores the write.

    The write was measured to work on build 5406, so the fake models that by
    default. This test turns it off, because a live negative result is the other
    thing the probe exists to be able to state, and the report has to be readable
    either way.

    See docs/spikes/2026-09-19-T1-tempo-write.md.
    """
    fl_env.project.tempo_write_works = False
    result = fl_env.controller.dispatch_command(
        "system.tempoProbe", {"bpm": 140.0, "restore": False}
    )

    assert "error" not in result
    assert set(result) == REPORT_KEYS
    # The id is REC_Global_First + 5, computed in the stubs as 0x4000 * 0x10000 + 5.
    assert result["event_id"] == REC_Tempo == 0x40000005
    assert result["requested_bpm"] == pytest.approx(140.0)
    assert result["requested_value"] == 140000
    assert result["tempo_before"] == 130000
    assert result["bpm_before"] == pytest.approx(130.0)
    assert result["flags"] == DEFAULT_FLAGS == 0x11
    assert result["flag_names"] == ["REC_UpdateValue", "REC_UpdateControl"]
    assert result["process_rec_result"] is None
    assert result["tempo_after"] == 130000
    assert result["bpm_after"] == pytest.approx(130.0)
    assert result["changed"] is False
    assert result["write_verified"] is False
    assert result["restore"] is False
    assert result["restore_verified"] is None

    # The call reached the API with the raw value, not the BPM.
    assert fl_env.project.rec_events == [(REC_Tempo, 140000, DEFAULT_FLAGS)]
    assert fl_env.project.tempo == 130000


def test_the_probe_reports_a_read_back_when_the_write_lands(fl_env):
    """With the fake modelling a write that stores the value.

    This is the case the live run has to look for. Configured here so the probe's
    before and after arithmetic is exercised at all. The fake doing what it is
    told says nothing about FL Studio; only a live run can.
    """
    fl_env.project.tempo_write_works = True

    result = fl_env.controller.dispatch_command("system.tempoProbe", {"bpm": 140.5})

    assert "error" not in result
    assert result["requested_value"] == 140500
    assert result["tempo_before"] == 130000
    assert result["tempo_after"] == 140500
    assert result["bpm_after"] == pytest.approx(140.5)
    assert result["changed"] is True
    assert result["write_verified"] is True
    assert fl_env.project.tempo == 140500


def test_restore_puts_the_original_tempo_back(fl_env):
    """The property that makes the probe safe to run on someone's project.

    A probe that moves the tempo and cannot put it back is not a probe, it is an
    edit. The restore goes through the same mechanism and the reply reports the
    read-back, so a restore that silently failed would be visible.
    """
    fl_env.project.tempo_write_works = True

    result = fl_env.controller.dispatch_command(
        "system.tempoProbe", {"bpm": 90.0, "restore": True}
    )

    assert "error" not in result
    assert result["write_verified"] is True
    assert result["restore"] is True
    assert result["tempo_restored"] == 130000
    assert result["bpm_restored"] == pytest.approx(130.0)
    assert result["restore_verified"] is True
    assert fl_env.project.tempo == 130000
    assert fl_env.project.rec_events == [
        (REC_Tempo, 90000, DEFAULT_FLAGS),
        (REC_Tempo, 130000, DEFAULT_FLAGS),
    ]


def test_restore_is_reported_as_verified_when_the_tempo_never_moved(fl_env):
    """Restore means "the project holds the original tempo", not "a second write
    happened". On an FL that ignores the write the project is already correct, and
    the report says so rather than claiming a failure."""
    fl_env.project.tempo_write_works = False
    result = fl_env.controller.dispatch_command(
        "system.tempoProbe", {"bpm": 90.0, "restore": True}
    )

    assert "error" not in result
    assert result["changed"] is False
    assert result["restore_verified"] is True
    assert fl_env.project.tempo == 130000


def test_the_flag_word_can_be_overridden_and_is_reported(fl_env):
    """Which flag combination FL honours is the open half of the spike.

    Being able to vary the flag word from the caller means one live session can
    compare candidates rather than one session per script edit. The model stores
    the value only when REC_UpdateValue is among the flags, which is why the
    flags have to reach the API rather than being decorative.
    """
    fl_env.project.tempo_write_works = True

    result = fl_env.controller.dispatch_command(
        "system.tempoProbe", {"bpm": 140.0, "flags": REC_UpdateControl}
    )

    assert "error" not in result
    assert result["flags"] == REC_UpdateControl
    assert result["flag_names"] == ["REC_UpdateControl"]
    assert result["write_verified"] is False
    assert fl_env.project.tempo == 130000
    assert fl_env.project.rec_events == [(REC_Tempo, 140000, REC_UpdateControl)]


@pytest.mark.parametrize("params", [{}, {"restore": False}, {"bpm": None}])
def test_a_missing_bpm_is_refused_naming_the_field(fl_env, params):
    assert fl_env.controller.dispatch_command("system.tempoProbe", params) == {
        "error": "system.tempoProbe requires a 'bpm'"
    }
    assert fl_env.project.rec_events == []
    assert fl_env.project.tempo == 130000


@pytest.mark.parametrize("bpm", [0, -120, "fast", float("nan"), float("inf")])
def test_a_bpm_that_is_not_a_tempo_is_refused(fl_env, bpm):
    """The stub warns that an invalid processRECEvent value can crash FL, so the
    probe refuses one instead of finding out on a real project."""
    result = fl_env.controller.dispatch_command("system.tempoProbe", {"bpm": bpm})

    assert "error" in result
    assert fl_env.project.rec_events == []
    assert fl_env.project.tempo == 130000


def test_a_non_integer_flag_word_is_refused(fl_env):
    result = fl_env.controller.dispatch_command(
        "system.tempoProbe", {"bpm": 140.0, "flags": "all of them"}
    )

    assert "error" in result
    assert "flags" in result["error"]
    assert fl_env.project.rec_events == []


def test_the_probe_refuses_to_write_when_fl_is_not_safe_to_edit(fl_env):
    """It is a write, so it is gated like every other write."""
    fl_env.project.safe_to_edit = False

    result = fl_env.controller.dispatch_command("system.tempoProbe", {"bpm": 140.0})

    assert "error" in result
    assert "safe to edit" in result["error"].lower()
    assert fl_env.project.rec_events == []
    assert fl_env.project.tempo == 130000


def test_a_raising_write_is_reported_and_the_read_back_still_runs(fl_env, monkeypatch):
    """A call that raised may still have landed, which is one of the hidden
    behaviours the probe exists to find, so both observations are reported."""

    def explode(eventId, value, flags):
        fl_env.project.tempo = value
        raise RuntimeError("boom")

    monkeypatch.setattr(fl_env.modules["general"], "processRECEvent", explode)

    result = fl_env.controller.dispatch_command("system.tempoProbe", {"bpm": 140.0})

    assert "error" in result
    assert "boom" in result["error"]
    assert result["tempo_after"] == 140000
    assert result["write_verified"] is True


def test_a_raising_restore_is_reported(fl_env, monkeypatch):
    """The restore runs through the same call, so it can fail the same way."""
    calls = {"n": 0}
    original = fl_env.modules["general"].processRECEvent

    def explode_on_restore(eventId, value, flags):
        calls["n"] += 1
        if calls["n"] > 1:
            raise RuntimeError("restore refused")
        original(eventId, value, flags)

    monkeypatch.setattr(fl_env.modules["general"], "processRECEvent", explode_on_restore)

    result = fl_env.controller.dispatch_command(
        "system.tempoProbe", {"bpm": 140.0, "restore": True}
    )

    assert "error" in result
    assert "restore refused" in result["error"]
    # The write landed, so the project is holding the requested tempo and the
    # restore is what failed. That is the state a caller most needs told about,
    # because their project is not where they left it.
    assert result["write_verified"] is True
    assert result["tempo_restored"] == 140000
    assert result["restore_verified"] is False


def test_an_unreadable_tempo_refuses_the_write(fl_env, monkeypatch):
    """Without the value before the write there is nothing to restore."""

    def explode():
        raise RuntimeError("no tempo for you")

    monkeypatch.setattr(fl_env.modules["mixer"], "getCurrentTempo", explode)

    result = fl_env.controller.dispatch_command("system.tempoProbe", {"bpm": 140.0})

    assert "error" in result
    assert "getCurrentTempo" in result["error"]
    assert fl_env.project.rec_events == []
    assert fl_env.project.tempo == 130000


def _connection(fl_env):
    """A real MIDIConnection wired to the in-process controller."""
    from fl_studio_mcp.utils.midi_connection import MIDIConnection

    conn = MIDIConnection()
    conn._command_file = fl_env.command_file
    conn._response_file = fl_env.response_file
    conn._port = fl_env.midi_port
    conn._connected = True
    return conn


def test_a_successful_probe_arrives_through_the_round_trip(fl_env):
    result = _connection(fl_env).send_command(
        "system.tempoProbe", {"bpm": 128.0}, timeout=2.0
    )

    assert result["success"] is True
    assert result["requested_value"] == 128000
    assert result["tempo_before"] == 130000


def test_a_refusal_arrives_as_a_failure_through_the_round_trip(fl_env):
    """The server must see the refusal as a failure, not as a success."""
    result = _connection(fl_env).send_command("system.tempoProbe", {}, timeout=2.0)

    assert result["success"] is False
    assert "bpm" in result["error"]
    assert fl_env.project.rec_events == []
