"""Mix findings and a gain staging plan, as pure arithmetic.

Each finding is tested for the case that should produce it and the case that should
not. A review that flags everything is as useless as one that flags nothing, and the
second is harder to notice: it looks like a clean mix.
"""

from __future__ import annotations

from fl_studio_mcp.musical import analysis


def track(index, name=None, volume=0.8, pan=0.0, muted=False, sends=None):
    return {
        "index": index,
        "name": name or (f"Insert {index}" if index else "Master"),
        "volume": volume,
        "pan": pan,
        "is_muted": muted,
        "sends": [0] if sends is None and index else (sends or []),
        "volume_db": 0.0,
    }


def snapshot(*tracks):
    return {"tracks": list(tracks), "track_count": len(tracks)}


def level(index, peak, name=None):
    return {"track": index, "name": name or f"Insert {index}", "peak": peak}


# --- find_peaks -------------------------------------------------------------


def test_a_track_over_zero_db_is_clipping():
    findings = analysis.find_peaks([level(1, 1.2)])
    assert [f["kind"] for f in findings] == ["clipping"]
    assert findings[0]["severity"] == analysis.PROBLEM
    assert "1.20" in findings[0]["detail"]


def test_exactly_one_is_not_clipping():
    """1.0 is 0 dB, the ceiling, not over it."""
    assert analysis.find_peaks([level(1, 1.0)]) == []


def test_a_silent_track_is_reported():
    findings = analysis.find_peaks([level(2, 0.0)])
    assert [f["kind"] for f in findings] == ["silent"]


def test_the_master_is_never_reported_as_silent():
    """A silent master means nothing is playing, not that it is routed nowhere."""
    assert analysis.find_peaks([level(0, 0.0)]) == []


def test_a_track_with_signal_is_not_a_finding():
    assert analysis.find_peaks([level(1, 0.7)]) == []


# --- review_mix -------------------------------------------------------------


def test_a_review_without_levels_still_reports_the_settings():
    """Those need no playback, so a stopped transport is not a dead end.

    This snapshot is two default inserts, so it also earns the two about every fader
    being at unity and nothing being panned. Those are correct rather than noise.
    """
    reviewed = analysis.review_mix(snapshot(track(0), track(1, sends=[])))
    kinds = {f["kind"] for f in reviewed["findings"]}
    assert "no_output" in kinds
    assert "all_at_unity" in kinds, "two default inserts earn this"
    assert reviewed["summary"]["levels_sampled"] is False


def test_a_track_with_no_sends_is_a_problem():
    reviewed = analysis.review_mix(snapshot(track(0), track(3, sends=[])))
    finding = reviewed["findings"][0]
    assert finding["kind"] == "no_output"
    assert finding["track"] == 3
    assert finding["severity"] == analysis.PROBLEM


def test_a_muted_track_with_no_sends_is_left_alone():
    """The reason is already known, so it is not a finding."""
    reviewed = analysis.review_mix(snapshot(track(0), track(3, muted=True, sends=[])))
    assert [f["kind"] for f in reviewed["findings"]] == []


def test_a_silent_track_nothing_feeds_is_not_reported():
    """An empty insert is an empty slot, not a routing problem.

    Flagging every one would put a hundred entries in front of the two that matter.
    """
    reviewed = analysis.review_mix(snapshot(track(0), track(1)), [level(1, 0.0)])
    assert [f["kind"] for f in reviewed["findings"]] != ["silent"]
    assert all(f["kind"] != "silent" for f in reviewed["findings"])


def test_a_silent_track_something_feeds_is_reported():
    reviewed = analysis.review_mix(
        snapshot(track(0), track(1, sends=[2]), track(2, sends=[0])),
        [level(1, 0.5), level(2, 0.0)],
    )
    silent = [f for f in reviewed["findings"] if f["kind"] == "silent"]
    assert len(silent) == 1
    assert silent[0]["track"] == 2
    assert silent[0]["fed_by"] == [1]


def test_clipping_comes_before_silence():
    """A caller reads the top of the list, so the worst belongs there."""
    reviewed = analysis.review_mix(
        snapshot(track(0), track(1), track(2, sends=[0])),
        [level(1, 1.3), level(2, 0.0)],
    )
    kinds = [f["kind"] for f in reviewed["findings"]]
    assert kinds.index("clipping") < kinds.index("silent")


def test_every_finding_names_its_track_unless_it_is_about_all_of_them():
    reviewed = analysis.review_mix(snapshot(track(0), track(1, sends=[])))
    for finding in reviewed["findings"]:
        if finding["kind"] in ("all_at_unity", "nothing_panned"):
            assert finding["track"] is None
        else:
            assert finding["track"] is not None
            assert finding["name"]


def test_everything_at_unity_is_reported_once():
    reviewed = analysis.review_mix(snapshot(track(0), track(1), track(2)))
    at_unity = [f for f in reviewed["findings"] if f["kind"] == "all_at_unity"]
    assert len(at_unity) == 1
    assert at_unity[0]["severity"] == analysis.INFORMATIONAL


def test_a_balanced_mix_is_not_reported_as_unity():
    reviewed = analysis.review_mix(snapshot(track(0), track(1, volume=0.5), track(2)))
    assert all(f["kind"] != "all_at_unity" for f in reviewed["findings"])


def test_a_panned_mix_is_not_reported_as_unpanned():
    reviewed = analysis.review_mix(snapshot(track(0), track(1, pan=-0.4), track(2)))
    assert all(f["kind"] != "nothing_panned" for f in reviewed["findings"])


def test_the_summary_counts_problems_and_information_separately():
    reviewed = analysis.review_mix(
        snapshot(track(0), track(1, sends=[]), track(2)),
        [level(2, 1.4)],
    )
    summary = reviewed["summary"]
    assert summary["problem_count"] >= 2, "one no output and one clipping"
    assert summary["informational_count"] >= 0
    assert "peak hold" in summary["note"]


# --- plan_gain_staging ------------------------------------------------------


def test_no_moves_without_levels():
    plan = analysis.plan_gain_staging(snapshot(track(0), track(1)), None)
    assert plan["moves"] == []
    assert plan["requires_playback"] is True


def test_a_hot_track_is_trimmed_down():
    plan = analysis.plan_gain_staging(
        snapshot(track(0), track(1, volume=0.8)), [level(1, 1.4)], target_db=-3.0
    )
    assert len(plan["moves"]) == 1
    move = plan["moves"][0]
    assert move["proposed_volume"] < move["current_volume"]
    assert move["reduction_db"] > 0
    assert "target" in move["reason"]


def test_a_track_under_the_target_is_left_alone():
    """Trimming a quiet track up would fight the producer's own balance."""
    plan = analysis.plan_gain_staging(
        snapshot(track(0), track(1)), [level(1, 0.5)], target_db=-3.0
    )
    assert plan["moves"] == []


def test_a_trim_never_leaves_the_faders_range():
    plan = analysis.plan_gain_staging(
        snapshot(track(0), track(1, volume=0.01)), [level(1, 40.0)], target_db=-60.0
    )
    for move in plan["moves"]:
        assert 0.0 <= move["proposed_volume"] <= 1.0


def test_a_silent_track_is_not_moved():
    plan = analysis.plan_gain_staging(
        snapshot(track(0), track(1)), [level(1, 0.0)], target_db=-3.0
    )
    assert plan["moves"] == []


def test_a_move_names_the_track_and_the_reason():
    plan = analysis.plan_gain_staging(
        snapshot(track(0), track(2)), [level(2, 1.2)], target_db=-3.0
    )
    move = plan["moves"][0]
    assert move["track"] == 2
    assert move["name"]
    assert "dB" in move["reason"]


def test_the_plan_says_it_is_not_a_loudness_match():
    plan = analysis.plan_gain_staging(
        snapshot(track(0), track(1)), [level(1, 1.2)], target_db=-3.0
    )
    assert "peak hold" in plan["note"]
