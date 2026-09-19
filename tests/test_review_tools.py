"""The review is read-only, and the gain staging pass reports before it acts."""

from __future__ import annotations

import pytest

from fl_studio_mcp.tools import review


@pytest.fixture
def wired(fl_env, monkeypatch):
    """The review tools wired to the in-process controller."""
    from fl_studio_mcp.utils.midi_connection import MIDIConnection

    conn = MIDIConnection()
    conn._command_file = fl_env.command_file
    conn._response_file = fl_env.response_file
    conn._port = fl_env.midi_port
    conn._connected = True
    monkeypatch.setattr(review, "get_connection", lambda: conn, raising=False)
    # review calls metering.sample_peaks, and metering holds its own reference to
    # get_connection. Patching only review's left the sampler building a real
    # connection and reaching for actual MIDI, which showed up as the transport
    # reading "stopped" regardless of the project state.
    monkeypatch.setattr(review.metering, "get_connection", lambda: conn, raising=False)
    fl_env.connection = conn
    return fl_env


def test_a_review_works_with_the_transport_stopped(wired):
    """The setting findings need no playback, so stopping is not a dead end."""
    result = review.mix_review(sample_seconds=0.05)
    assert result["success"] is True
    assert result["summary"]["levels_sampled"] is False
    assert "levels_unavailable" in result, "it must say why the levels are missing"


def test_the_review_says_playback_is_why_levels_are_missing(wired):
    result = review.mix_review(sample_seconds=0.05)
    assert "transport" in result["levels_unavailable"].lower()


def test_the_review_reports_setting_findings_while_stopped(wired):
    """Every default insert earns the unity finding, and nothing else is needed."""
    result = review.mix_review(sample_seconds=0.05)
    kinds = {finding["kind"] for finding in result["findings"]}
    assert "all_at_unity" in kinds


def test_a_review_with_playback_finds_clipping(wired, monkeypatch):
    wired.project.is_playing = True
    wired.modules["mixer"].getTrackPeaks = lambda index, mode: 1.5
    result = review.mix_review(sample_seconds=0.05)
    assert result["summary"]["levels_sampled"] is True
    assert any(f["kind"] == "clipping" for f in result["findings"])


def test_a_review_whose_window_stopped_early_says_so(wired):
    """Non-zero levels beside a stopped transport read as a contradiction.

    The live run hit this: playback ended inside the sampling window, so the review
    reported real peaks and a transport that was no longer playing. A review has to
    say the window was cut short, or the levels look like they were measured under
    playback when only part of them were.
    """
    wired.project.is_playing = True
    wired.modules["mixer"].getTrackPeaks = lambda index, mode: 0.9
    conn = wired.connection
    original = conn.send_command

    def stop_after_the_first_read(command, params=None, **kwargs):
        result = original(command, params, **kwargs)
        if command == "mixer.getLevels":
            wired.project.is_playing = False
        return result

    conn.send_command = stop_after_the_first_read
    result = review.mix_review(sample_seconds=0.05)
    assert result["summary"]["levels_sampled"] is True
    assert "levels_partial" in result
    assert "stopped" in result["levels_partial"].lower()


def test_a_full_window_review_has_no_partial_caveat(wired):
    wired.project.is_playing = True
    result = review.mix_review(sample_seconds=0.05)
    assert "levels_partial" not in result


def test_a_review_changes_nothing(wired):
    """It is a diagnostic, so a mutating command in it would be a defect."""
    before = {
        index: track.volume for index, track in enumerate(wired.project.tracks)
    }
    review.mix_review(sample_seconds=0.05)
    after = {index: track.volume for index, track in enumerate(wired.project.tracks)}
    assert before == after


def test_gain_staging_requires_playback(wired):
    result = review.gain_staging(sample_seconds=0.05)
    assert result["success"] is False
    assert result["requires_playback"] is True


def test_gain_staging_reports_without_applying(wired):
    wired.project.is_playing = True
    wired.modules["mixer"].getTrackPeaks = lambda index, mode: 1.5
    before = {i: t.volume for i, t in enumerate(wired.project.tracks)}

    result = review.gain_staging(apply=False, sample_seconds=0.05)

    assert result["success"] is True
    assert result["applied"] is False
    assert result["moves"], "a track peaking at 1.5 needs trimming"
    after = {i: t.volume for i, t in enumerate(wired.project.tracks)}
    assert before == after, "reporting must not move anything"
    assert "apply=True" in result["message"]


def test_gain_staging_applies_when_asked(wired, monkeypatch):
    wired.project.is_playing = True
    wired.modules["mixer"].getTrackPeaks = lambda index, mode: 1.5
    applied = {}

    def fake_batch(commands, name):
        applied["commands"] = commands
        applied["name"] = name
        return {"success": True, "executed": len(commands), "undo_name": name}

    monkeypatch.setattr(review.batch, "run_batch", fake_batch)
    result = review.gain_staging(apply=True, sample_seconds=0.05)

    assert result["applied"] is True
    assert applied["commands"], "no fader moves were sent"
    assert "gain staging" in applied["name"], "the undo entry should say what it was"


def test_gain_staging_applies_as_one_batch(wired, monkeypatch):
    """One undo step for the whole pass, not one per fader."""
    wired.project.is_playing = True
    wired.modules["mixer"].getTrackPeaks = lambda index, mode: 1.5
    calls = []

    def fake_batch(commands, name):
        calls.append(name)
        return {"success": True, "executed": len(commands), "undo_name": name}

    monkeypatch.setattr(review.batch, "run_batch", fake_batch)
    review.gain_staging(apply=True, sample_seconds=0.05)
    assert len(calls) == 1


def test_gain_staging_says_so_when_nothing_needs_moving(wired):
    wired.project.is_playing = True
    wired.modules["mixer"].getTrackPeaks = lambda index, mode: 0.2
    result = review.gain_staging(apply=True, sample_seconds=0.05)
    assert result["applied"] is False
    assert result["moves"] == []
    assert "no fader" in result["message"].lower()


def test_a_failed_batch_is_reported(wired, monkeypatch):
    wired.project.is_playing = True
    wired.modules["mixer"].getTrackPeaks = lambda index, mode: 1.5
    monkeypatch.setattr(
        review.batch,
        "run_batch",
        lambda commands, name: {"success": False, "error": "FL said no"},
    )
    result = review.gain_staging(apply=True, sample_seconds=0.05)
    assert result["success"] is False
    assert "FL said no" in result["error"]
