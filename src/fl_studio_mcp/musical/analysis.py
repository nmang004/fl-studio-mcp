"""Mix findings and a gain staging plan, as arithmetic.

Pure functions over a mixer snapshot and sampled peaks, so the decisions a review
makes are tested with no FL Studio running. That matters more here than anywhere else
in the project: a finding that is wrong sends a producer to change something that was
fine, and a finding that fires on everything is the same as no finding at all.

Every function says which measurement it is reasoning from. A peak hold is not
loudness, and the difference decides what a finding may claim.
"""

from __future__ import annotations

import math

# A peak above this is over 0 dB. Exactly 1.0 is the ceiling, not over it.
CLIP_THRESHOLD = 1.0

# A fader this close to FL's default 0.8 has probably never been touched. The value
# comes from FL itself: 0.8 reads back as 0.0 dB, measured live.
UNITY = 0.8
UNITY_TOLERANCE = 0.005

# Master is index 0 in FL. It is never a routing problem when it is silent, because a
# silent master means nothing is playing rather than a track wired to nowhere.
MASTER = 0

# How a finding is graded, so a caller can filter without reading the prose.
PROBLEM = "problem"
INFORMATIONAL = "informational"

_SEVERITY = {PROBLEM: 0, INFORMATIONAL: 1}


def find_peaks(levels: list[dict]) -> list[dict]:
    """What clips and what never sounds, from sampled peaks.

    Args:
        levels: Entries with `track`, `name` and `peak`, as the sampler returns.

    Returns:
        Findings, each with a kind, a severity, the track and a sentence.
    """
    findings = []
    for entry in levels:
        peak = entry.get("peak")
        if peak is None:
            continue
        track = entry.get("track")
        name = entry.get("name") or f"track {track}"

        if peak > CLIP_THRESHOLD:
            # Three decimals, and the overshoot in dB, because a clipping peak is
            # often barely over the ceiling: 1.004 rounded to two decimals reads as
            # 1.00, the exact value this function says is not clipping. A live review
            # hit that, and a message that contradicts its own threshold is worse than
            # no message.
            overshoot_db = 20.0 * math.log10(peak)
            findings.append({
                "kind": "clipping",
                "severity": PROBLEM,
                "track": track,
                "name": name,
                "detail": (
                    f"{name} peaked at {peak:.3f}, which is {overshoot_db:.2f} dB over "
                    "full scale, so it is clipping."
                ),
                "peak": peak,
            })
        elif peak <= 0.0 and track != MASTER:
            # An insert that never rose above silence is only interesting if something
            # is routed to it. An unused insert is not a finding, it is an empty slot,
            # and flagging those would bury the real ones under a hundred entries.
            findings.append({
                "kind": "silent",
                "severity": INFORMATIONAL,
                "track": track,
                "name": name,
                "detail": (
                    f"{name} never rose above silence while the project played."
                ),
                "peak": peak,
            })
    return findings


def review_mix(snapshot: dict, levels: list[dict] | None = None) -> dict:
    """Findings across the mixer's settings, and its levels when they were sampled.

    Args:
        snapshot: The mixer snapshot: every track's volume, pan, routing and state.
        levels: Sampled peaks, or None when the transport was not running. Without
            them the setting findings are still reported, because those need no
            playback.

    Returns:
        findings, ordered by severity and then by track
        summary: the counts, and whether levels were part of the review
    """
    tracks = snapshot.get("tracks") or []
    by_index = {track["index"]: track for track in tracks}
    findings: list[dict] = []

    if levels:
        # One check for a silent track with signal going into it, rather than two.
        # Reporting it from the sender's side and from the receiver's side produced
        # the same finding twice under different names.
        findings.extend(_routed_but_silent(levels, by_index))
        findings.extend(_clipping(levels))
    findings.extend(_settings(tracks))

    findings.sort(key=lambda finding: (_SEVERITY.get(finding["severity"], 9),
                                       finding.get("track") if finding.get("track")
                                       is not None else -1))
    problems = [f for f in findings if f["severity"] == PROBLEM]
    return {
        "findings": findings,
        "summary": {
            "problem_count": len(problems),
            "informational_count": len(findings) - len(problems),
            "tracks_reviewed": len(tracks),
            "levels_sampled": levels is not None,
            "note": (
                "Peak levels are a peak hold, not a loudness measurement. They find "
                "clipping and silence, not what a listener would call too loud."
            ),
        },
    }


def plan_gain_staging(
    snapshot: dict, levels: list[dict] | None, target_db: float = -3.0
) -> dict:
    """The fader moves that would bring hot tracks down to a target.

    Args:
        snapshot: The mixer snapshot.
        levels: Sampled peaks. Without them there is nothing to act on, because the
            current volume says nothing about how hot the signal arriving is.
        target_db: Where to aim. -3 dB leaves room without being timid, and the
            default is deliberately a trim rather than a loudness target.

    Returns:
        moves: one per track that needs one, each naming the track, the current
            volume, the proposed volume, and the reason
        requires_playback: whether the caller still needs to sample
    """
    if not levels:
        return {
            "moves": [],
            "requires_playback": True,
            "note": (
                "No levels were sampled, so there is nothing to judge the faders "
                "against. Playback has to be running to sample."
            ),
        }

    by_index = {track["index"]: track for track in snapshot.get("tracks") or []}
    moves = []

    for entry in levels:
        peak = entry.get("peak")
        track = entry.get("track")
        if peak is None or peak <= 0.0 or track not in by_index:
            continue

        # Only tracks that are actually over. Trimming a quiet track up is a different
        # decision, and doing it automatically would fight a producer's own balance.
        peak_db = _to_db(peak)
        if peak_db <= target_db:
            continue

        current = by_index[track].get("volume")
        if current is None:
            continue
        reduction_db = peak_db - target_db
        proposed = current * (10 ** (reduction_db / -20.0))
        proposed = round(max(0.0, min(1.0, proposed)), 4)
        if proposed == current:
            continue

        moves.append({
            "track": track,
            "name": by_index[track].get("name"),
            "current_volume": current,
            "proposed_volume": proposed,
            "peak_db": round(peak_db, 2),
            "reduction_db": round(reduction_db, 2),
            "reason": (
                f"peaked at {peak_db:.2f} dB, which is {reduction_db:.2f} dB over the "
                f"{target_db} dB target"
            ),
        })

    return {
        "moves": moves,
        "requires_playback": False,
        "target_db": target_db,
        "note": (
            "Reductions are computed from a peak hold, so they bring the loudest "
            "moment under the target. They do not make two tracks sound equally loud."
        ),
    }


def _to_db(peak: float) -> float:
    """A linear peak as decibels. 1.0 is 0 dB, above it is positive."""
    import math

    if peak <= 0:
        return float("-inf")
    return 20.0 * math.log10(peak)


def _clipping(levels: list[dict]) -> list[dict]:
    return [finding for finding in find_peaks(levels) if finding["kind"] == "clipping"]


def _routed_but_silent(levels: list[dict], by_index: dict) -> list[dict]:
    """Silent tracks that something is actually routed into.

    A silent insert with nothing feeding it is an empty slot, not a finding. Flagging
    every empty insert would put a hundred informational entries in front of the two
    that matter, and a producer reading that list learns nothing.

    This is one check rather than two. A send into a track that never sounded is the
    same fact whether it is reported from the sender's end or the receiver's, and
    reporting both produced duplicate findings under different names.
    """
    silent = {entry["track"] for entry in levels if (entry.get("peak") or 0.0) <= 0.0}
    findings = []
    for index in sorted(silent):
        if index == MASTER:
            continue
        target = by_index.get(index)
        if target is None or target.get("is_muted"):
            continue
        fed_by = [
            track["index"]
            for track in by_index.values()
            if index in (track.get("sends") or [])
        ]
        if not fed_by:
            continue
        name = target.get("name") or f"track {index}"
        findings.append({
            "kind": "silent",
            "severity": INFORMATIONAL,
            "track": index,
            "name": name,
            "fed_by": fed_by,
            "peak": 0.0,
            "detail": (
                f"{name} never rose above silence, and {len(fed_by)} track(s) send to "
                "it, so that signal is going nowhere audible."
            ),
        })
    return findings


def _settings(tracks: list[dict]) -> list[dict]:
    """Findings that need no playback, because they are about the settings alone."""
    findings = []

    inserts = [track for track in tracks if track["index"] != MASTER and not track.get("is_muted")]
    if inserts and all(abs((track.get("volume") or 0.0) - UNITY) < UNITY_TOLERANCE
                       for track in inserts):
        findings.append({
            "kind": "all_at_unity",
            "severity": INFORMATIONAL,
            "track": None,
            "name": None,
            "detail": (
                f"Every insert is at FL's default fader of {UNITY}, so no track has "
                "been balanced against any other yet."
            ),
        })

    panned = [track for track in inserts if abs(track.get("pan") or 0.0) > 1e-6]
    if inserts and not panned:
        findings.append({
            "kind": "nothing_panned",
            "severity": INFORMATIONAL,
            "track": None,
            "name": None,
            "detail": (
                "Every insert is panned centre. That is a choice, not a mistake, so "
                "this is only worth saying once."
            ),
        })

    for track in tracks:
        if track["index"] == MASTER:
            continue
        if track.get("sends"):
            continue
        if track.get("is_muted"):
            continue
        findings.append({
            "kind": "no_output",
            "severity": PROBLEM,
            "track": track["index"],
            "name": track.get("name"),
            "detail": (
                f"{track.get('name')} has no sends at all, so nothing routed to it "
                "reaches the master."
            ),
        })

    return findings
