"""Peaks are instantaneous, so sampling is the only way to learn anything.

mixer.getTrackPeaks returns the current value: 0.0 is silence, 1.0 is 0 dB, and
anything above 1.0 is clipping. One reading is a snapshot, which is why the tool
takes a sample count.
"""

from __future__ import annotations

import pytest


def test_levels_reports_a_peak_per_track(fl_env):
    result = fl_env.controller.dispatch_command("mixer.getLevels", {"tracks": [0, 1]})
    assert [entry["track"] for entry in result["levels"]] == [0, 1]
    assert all("peak" in entry for entry in result["levels"])


def test_levels_keeps_the_loudest_of_the_samples(fl_env):
    """A single reading would miss a peak between polls."""
    readings = iter([0.1, 0.9, 0.3])
    fl_env.modules["mixer"].getTrackPeaks = lambda index, mode: next(readings, 0.0)
    result = fl_env.controller.dispatch_command(
        "mixer.getLevels", {"tracks": [1], "samples": 3}
    )
    assert result["levels"][0]["peak"] == pytest.approx(0.9)


def test_levels_defaults_to_every_track(fl_env):
    result = fl_env.controller.dispatch_command("mixer.getLevels", {})
    assert len(result["levels"]) == 8


def test_levels_reports_clipping_distinctly(fl_env):
    fl_env.modules["mixer"].getTrackPeaks = lambda index, mode: 1.4
    result = fl_env.controller.dispatch_command("mixer.getLevels", {"tracks": [0]})
    assert result["levels"][0]["peak"] == pytest.approx(1.4)
    assert result["levels"][0]["clipping"] is True


def test_levels_reports_a_silent_track_as_not_clipping(fl_env):
    result = fl_env.controller.dispatch_command("mixer.getLevels", {"tracks": [0]})
    assert result["levels"][0]["clipping"] is False


def test_levels_names_each_track(fl_env):
    result = fl_env.controller.dispatch_command("mixer.getLevels", {"tracks": [0]})
    assert result["levels"][0]["name"] == "Master"


def test_levels_reports_the_sample_count_used(fl_env):
    result = fl_env.controller.dispatch_command(
        "mixer.getLevels", {"tracks": [0], "samples": 5}
    )
    assert result["samples"] == 5


def test_levels_refuses_a_track_that_does_not_exist(fl_env):
    result = fl_env.controller.dispatch_command("mixer.getLevels", {"tracks": [99]})
    assert "error" in result
    assert "99" in result["error"]


def test_levels_refuses_a_sample_count_below_one(fl_env):
    result = fl_env.controller.dispatch_command(
        "mixer.getLevels", {"tracks": [0], "samples": 0}
    )
    assert "error" in result
    assert "samples" in result["error"]


def test_levels_is_never_refused(fl_env):
    """Reading a meter changes nothing, and is what a stuck user needs."""
    fl_env.project.safe_to_edit = False
    assert "error" not in fl_env.controller.dispatch_command("mixer.getLevels", {})
