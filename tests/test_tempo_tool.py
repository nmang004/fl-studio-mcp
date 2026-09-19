"""fl_set_tempo, which the live measurement unblocked.

The write works: measured on FL Studio 2026 build 5406, processRECEvent with
midi.REC_Tempo and flags 17 set the tempo and an independent read agreed. The
spike finding is docs/spikes/2026-09-19-T1-tempo-write.md.

The tool still verifies rather than trusts. processRECEvent's own stub says that
part of the API is full of hidden bugs, and a tempo setter that silently does
nothing is worse than no tool, because the caller cannot tell the difference.
"""

from __future__ import annotations

import pytest

from fl_studio_mcp.tools import tempo


@pytest.fixture
def wired(fl_env, monkeypatch):
    """The tempo tool wired to the in-process controller."""
    from fl_studio_mcp.utils.midi_connection import MIDIConnection

    conn = MIDIConnection()
    conn._command_file = fl_env.command_file
    conn._response_file = fl_env.response_file
    conn._port = fl_env.midi_port
    conn._connected = True
    monkeypatch.setattr(tempo, "get_connection", lambda: conn, raising=False)
    return fl_env


def test_setting_the_tempo_reports_the_value_before_and_after(wired):
    wired.project.tempo = 130000
    result = tempo.set_tempo(128.0)
    assert result["success"] is True
    assert result["bpm_before"] == pytest.approx(130.0)
    assert result["bpm_after"] == pytest.approx(128.0)


def test_the_write_is_reported_as_verified(wired):
    """The fake models a working write; the tool must confirm it rather than assume."""
    wired.project.tempo = 130000
    result = tempo.set_tempo(128.0)
    assert result["write_verified"] is True


def test_a_write_that_did_not_take_is_a_failure(wired, monkeypatch):
    """The failure mode that matters: FL accepts the call and the tempo does not move.

    This is what the tool exists to catch, because the caller cannot tell the
    difference between a silent no-op and a success.
    """
    monkeypatch.setattr(wired.project, "tempo_write_works", False, raising=False)
    result = tempo.set_tempo(128.0)
    assert result["success"] is False
    assert "did not change" in result["error"] or "did not take" in result["error"]


def test_the_tempo_range_is_validated_before_writing(wired):
    """The stubs give the event no range and warn an invalid value can crash FL."""
    for bpm in (0.0, -5.0, 100000.0):
        result = tempo.set_tempo(bpm)
        assert result["success"] is False
        assert "range" in result["error"].lower()


def test_a_plausible_tempo_is_accepted(wired):
    for bpm in (20.0, 130.0, 999.0):
        assert tempo.set_tempo(bpm)["success"] is True


def test_the_tool_reports_the_tempo_it_read_back(wired):
    result = tempo.set_tempo(140.5)
    assert result["bpm_after"] == pytest.approx(140.5)
    assert result["message"]


def test_the_tool_uses_the_flag_word_the_live_run_measured(wired):
    """Flags 17 is what the probe measured on FL Studio 2026 build 5406.

    Changing it silently would replace a measured value with a guess, so it is one
    named constant and this test pins it.
    """
    assert tempo.TEMPO_WRITE_FLAGS == 17
    recorded = [call for call in wired.project.rec_events if call[0] == 1073741829]
    tempo.set_tempo(128.0)
    recorded = [call for call in wired.project.rec_events if call[0] == 1073741829]
    assert recorded, "no REC_Tempo event reached FL"
    assert recorded[-1][2] == tempo.TEMPO_WRITE_FLAGS


def test_setting_the_tempo_it_already_has_succeeds(wired):
    wired.project.tempo = 130000
    """Asking for the value a project already has is a no-op, not a failure.

    Found live: the first version reported "the tempo did not change" as an error
    when asked to set 130 on a 130 BPM project, which would fail a reasonable
    "make sure the tempo is 130".
    """
    result = tempo.set_tempo(130.0)
    assert result["success"] is True
    assert result["already_set"] is True
    assert result["bpm_after"] == pytest.approx(130.0)


def test_a_real_change_does_not_claim_it_was_already_set(wired):
    wired.project.tempo = 130000
    result = tempo.set_tempo(128.0)
    assert result["success"] is True
    assert "already_set" not in result
