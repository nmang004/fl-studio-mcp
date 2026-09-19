"""EQ is seven bands per track, which is why it is one tool and not twenty one.

The band count comes from mixer.getEqBandCount rather than being assumed, because
a hardcoded seven would be wrong on a version that changed it.
"""

from __future__ import annotations

import pytest


def test_get_eq_returns_every_band(fl_env):
    """Three bands, which is what live FL Studio 2026 reports for an insert."""
    result = fl_env.controller.dispatch_command("mixer.getEq", {"track": 1})
    assert result["track"] == 1
    assert result["band_count"] == 3
    assert len(result["bands"]) == 3
    assert [b["band"] for b in result["bands"]] == list(range(3))


def test_get_eq_reports_gain_frequency_and_bandwidth(fl_env):
    fl_env.project.track(1).eq_gains[2] = 0.75
    fl_env.project.track(1).eq_freqs[2] = 0.4
    fl_env.project.track(1).eq_bandwidths[2] = 0.6
    band = next(
        b for b in fl_env.controller.dispatch_command("mixer.getEq", {"track": 1})["bands"]
        if b["band"] == 2
    )
    assert band["gain"] == pytest.approx(0.75)
    assert band["frequency"] == pytest.approx(0.4)
    assert band["bandwidth"] == pytest.approx(0.6)


def test_get_eq_names_the_track(fl_env):
    result = fl_env.controller.dispatch_command("mixer.getEq", {"track": 1})
    assert result["name"] == "Insert 1"


def test_set_eq_bands_writes_only_what_was_named(fl_env):
    """A band the caller did not mention must not be reset."""
    fl_env.project.track(1).eq_gains[0] = 0.9
    fl_env.controller.dispatch_command("mixer.setEqBands", {
        "track": 1,
        "bands": [{"band": 1, "gain": 0.25}],
    })
    assert fl_env.project.track(1).eq_gains[1] == pytest.approx(0.25)
    assert fl_env.project.track(1).eq_gains[0] == pytest.approx(0.9), "band 0 was reset"


def test_set_eq_bands_reads_the_result_back(fl_env):
    result = fl_env.controller.dispatch_command("mixer.setEqBands", {
        "track": 1,
        "bands": [{"band": 1, "gain": 0.9, "frequency": 0.4, "bandwidth": 0.6}],
    })
    band = next(b for b in result["bands"] if b["band"] == 1)
    assert band["gain"] == pytest.approx(0.9)
    assert band["frequency"] == pytest.approx(0.4)
    assert band["bandwidth"] == pytest.approx(0.6)


def test_set_eq_sets_several_bands_in_one_call(fl_env):
    fl_env.controller.dispatch_command("mixer.setEqBands", {
        "track": 2,
        "bands": [{"band": 0, "gain": 0.1}, {"band": 2, "gain": 0.9}],
    })
    assert fl_env.project.track(2).eq_gains[0] == pytest.approx(0.1)
    assert fl_env.project.track(2).eq_gains[2] == pytest.approx(0.9)


def test_eq_values_are_clamped_to_the_documented_range(fl_env):
    fl_env.controller.dispatch_command("mixer.setEqBands", {
        "track": 1, "bands": [{"band": 0, "frequency": 4.0}],
    })
    assert fl_env.project.track(1).eq_freqs[0] == pytest.approx(1.0)


def test_get_eq_needs_a_track(fl_env):
    result = fl_env.controller.dispatch_command("mixer.getEq", {})
    assert "error" in result
    assert "track" in result["error"]


def test_set_eq_needs_a_track(fl_env):
    result = fl_env.controller.dispatch_command("mixer.setEqBands", {"bands": []})
    assert "error" in result
    assert "track" in result["error"]


def test_set_eq_needs_bands(fl_env):
    result = fl_env.controller.dispatch_command("mixer.setEqBands", {"track": 1})
    assert "error" in result
    assert "bands" in result["error"]


def test_an_out_of_range_band_is_refused(fl_env):
    result = fl_env.controller.dispatch_command("mixer.setEqBands", {
        "track": 1, "bands": [{"band": 99, "gain": 0.5}],
    })
    assert "error" in result
    assert "99" in result["error"]


def test_a_band_with_no_settings_is_refused(fl_env):
    result = fl_env.controller.dispatch_command("mixer.setEqBands", {
        "track": 1, "bands": [{"band": 0}],
    })
    assert "error" in result


def test_a_track_that_does_not_exist_is_refused(fl_env):
    result = fl_env.controller.dispatch_command("mixer.getEq", {"track": 99})
    assert "error" in result
    assert "99" in result["error"]


def test_eq_writes_are_refused_when_not_safe_to_edit(fl_env):
    fl_env.project.safe_to_edit = False
    result = fl_env.controller.dispatch_command("mixer.setEqBands", {
        "track": 1, "bands": [{"band": 0, "gain": 0.5}],
    })
    assert "error" in result
    assert "safe to edit" in result["error"].lower()


def test_eq_reads_are_not_refused(fl_env):
    fl_env.project.safe_to_edit = False
    assert "error" not in fl_env.controller.dispatch_command("mixer.getEq", {"track": 1})
