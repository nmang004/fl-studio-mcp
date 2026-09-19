"""Sampling peaks over time, from the host.

The controller cannot do this. It runs on FL's MIDI thread, so waiting between
readings would stall the audio engine, which is why the existing levels action reads
back to back and cannot see a peak that happens between two polls. The host has a
real clock and sleeps for free.
"""

from __future__ import annotations

import pytest

from fl_studio_mcp.tools import metering


@pytest.fixture
def wired(fl_env, monkeypatch):
    """The metering tools wired to the in-process controller."""
    from fl_studio_mcp.utils.midi_connection import MIDIConnection

    conn = MIDIConnection()
    conn._command_file = fl_env.command_file
    conn._response_file = fl_env.response_file
    conn._port = fl_env.midi_port
    conn._connected = True
    monkeypatch.setattr(metering, "get_connection", lambda: conn, raising=False)
    fl_env.connection = conn
    return fl_env


@pytest.fixture
def playing(wired):
    wired.project.is_playing = True
    return wired


def test_sampling_while_stopped_is_refused(wired):
    """The most important behaviour in the phase.

    Every reading while stopped is zero, and zero reads as "this track never
    sounds". A review run on a stopped transport would confidently report that the
    whole mix is silent and routed nowhere.
    """
    result = metering.sample_peaks(duration=0.05, interval=0.01)
    assert result["success"] is False
    assert "transport" in result["error"].lower() or "playing" in result["error"].lower()


def test_sampling_during_playback_returns_levels(playing):
    result = metering.sample_peaks(duration=0.05, interval=0.01)
    assert result["success"] is True
    assert len(result["levels"]) == 8
    assert result["transport"]["is_playing"] is True


def test_the_peak_is_the_loudest_reading_not_the_last(playing, monkeypatch):
    readings = iter([0.1, 0.9, 0.2])
    playing.modules["mixer"].getTrackPeaks = lambda index, mode: next(readings, 0.0)
    result = metering.sample_peaks(duration=0.05, interval=0.01, tracks=[1])
    assert result["levels"][0]["peak"] == pytest.approx(0.9)


def test_a_single_loud_sample_marks_the_track_as_clipping(playing, monkeypatch):
    """One clip in twenty samples is still a clip."""
    state = {"n": 0}

    def mostly_quiet(index, mode):
        state["n"] += 1
        return 1.4 if state["n"] == 5 else 0.5

    playing.modules["mixer"].getTrackPeaks = mostly_quiet
    result = metering.sample_peaks(duration=0.05, interval=0.01, tracks=[1])
    assert result["levels"][0]["clipping"] is True


class FakeClock:
    """A clock that only moves when something sleeps.

    Patching sleep alone is not enough: the loop would then read as fast as it could
    and take hundreds of samples instead of the ten a 0.5s window at 0.05s intervals
    calls for. The clock has to move with the sleeps, or the test measures the
    absence of a real clock rather than the sampling logic.
    """

    def __init__(self):
        self.now = 0.0
        self.slept = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


def test_the_sample_count_is_reported(playing, monkeypatch):
    """A caller has to be able to tell a four second window from a fluke."""
    clock = FakeClock()
    monkeypatch.setattr(metering.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(metering.time, "sleep", clock.sleep)
    result = metering.sample_peaks(duration=0.5, interval=0.05)
    assert result["samples"] == 10
    assert clock.slept, "the loop never waited, so it cannot sample over time"


def test_the_interval_is_respected(playing, monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(metering.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(metering.time, "sleep", clock.sleep)
    metering.sample_peaks(duration=0.2, interval=0.02)
    assert clock.slept, "no sleep happened"
    assert all(abs(seconds - 0.02) < 1e-9 for seconds in clock.slept), clock.slept


def test_sampling_only_the_tracks_asked_for(playing):
    result = metering.sample_peaks(duration=0.05, interval=0.01, tracks=[0, 1])
    assert [entry["track"] for entry in result["levels"]] == [0, 1]


def test_a_track_that_does_not_exist_is_refused(playing):
    result = metering.sample_peaks(duration=0.05, interval=0.01, tracks=[99])
    assert result["success"] is False
    assert "99" in result["error"]


def test_a_duration_with_no_samples_is_refused(playing):
    result = metering.sample_peaks(duration=0.0, interval=0.01)
    assert result["success"] is False
    assert "duration" in result["error"].lower()


def test_a_non_positive_interval_is_refused(playing):
    result = metering.sample_peaks(duration=0.05, interval=0)
    assert result["success"] is False


def test_the_duration_is_reported(playing):
    result = metering.sample_peaks(duration=0.05, interval=0.01)
    assert result["duration"] == pytest.approx(0.05)


def test_the_recording_state_is_reported(playing):
    """A caller reading levels during a take should know it is a take."""
    playing.project.is_recording = True
    result = metering.sample_peaks(duration=0.05, interval=0.01)
    assert result["transport"]["is_recording"] is True
