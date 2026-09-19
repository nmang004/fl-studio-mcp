"""Riffs: a phrase, what makes it findable, and how to move it into another key.

The arithmetic is here and the disk is elsewhere, so keys, tags, transposition and
clamping are all tested with no FL Studio and no library directory.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from fl_studio_mcp.musical import riffs


# A fixed moment, so newest-first ordering is assertable rather than a race.
def moment(text: str):
    return datetime.fromisoformat(text)

CONTEXT = {
    "root_note": 9,
    "scale_helper": "0,2,3,5,7,8,10",
    "scale_set": True,
    "tsnum": 4,
    "tsden": 4,
    "ppq": 96,
    "key": "A minor",
    "time_signature": "4/4",
    "beats_per_bar": 4.0,
}


def note(midi: int, time: float = 0.0, duration: float = 1.0) -> dict:
    return {
        "midi": midi,
        "number": midi,
        "time": time,
        "duration": duration,
        "time_ticks": int(time * 96),
        "length_ticks": int(duration * 96),
        "velocity": 0.8,
        "slide": True,
    }


def riff(name: str = "deep stab", **overrides) -> dict:
    payload = {
        "name": name,
        "notes": [note(57, 0.0), note(60, 1.0)],
        "context": CONTEXT,
        "instrument": "808 Astronomic",
        "tags": ["dark", "stab"],
        "mood": "dark",
        "record_id": "2026-09-19-120000-deep-stab",
    }
    payload.update(overrides)
    return riffs.make_riff(**payload)


# --- making a record ---------------------------------------------------------


def test_a_record_carries_what_makes_it_findable():
    record = riff()
    assert record["schema"] == riffs.SCHEMA
    assert record["name"] == "deep stab"
    assert record["tags"] == ["dark", "stab"]
    assert record["mood"] == "dark"
    assert record["instrument"] == "808 Astronomic"
    assert record["key"]["name"] == "A minor"
    assert record["key"]["root"] == 9
    assert record["meter"] == {"tsnum": 4, "tsden": 4}
    assert record["note_count"] == 2
    assert record["id"] and record["created"]


def test_a_record_keeps_the_notes_exactly_as_they_were():
    """Expression is the point. A recall that flattens slides is a different riff."""
    record = riff()
    assert record["notes"][0]["slide"] is True
    assert record["notes"][0]["velocity"] == 0.8


def test_making_a_record_does_not_alter_the_notes_it_was_given():
    notes = [note(60)]
    riffs.make_riff("x", notes, context=CONTEXT)
    assert notes[0]["midi"] == 60


def test_the_length_is_measured_in_beats():
    record = riff(notes=[note(60, 0.0, 2.0), note(64, 2.0, 2.5)])
    assert record["length_beats"] == pytest.approx(4.5)


def test_a_record_without_a_key_says_so_rather_than_guessing_c_major():
    record = riff(context={"scale_set": False, "tsnum": 4, "tsden": 4, "ppq": 96})
    assert record["key"] is None


# --- transposition -----------------------------------------------------------


def test_no_movement_when_the_keys_are_the_same():
    assert riffs.transpose_semitones(9, 9) == 0


def test_the_nearest_direction_is_chosen():
    """An eleven semitone jump is a different part, not a transposition."""
    assert riffs.transpose_semitones(0, 11) == -1
    assert riffs.transpose_semitones(11, 0) == 1
    assert riffs.transpose_semitones(9, 2) == 5
    assert riffs.transpose_semitones(2, 9) == -5


def test_a_tritone_goes_up():
    """Six either way, so the direction has to be stated. Up is the convention."""
    assert riffs.transpose_semitones(0, 6) == 6


def test_up_and_down_can_be_forced():
    assert riffs.transpose_semitones(0, 2, direction="up") == 2
    assert riffs.transpose_semitones(0, 2, direction="down") == -10
    assert riffs.transpose_semitones(0, 0, direction="down") == 0


def test_an_unknown_direction_is_refused():
    with pytest.raises(ValueError, match="direction"):
        riffs.transpose_semitones(0, 2, direction="sideways")


def test_notes_move_by_the_interval():
    moved, clamped = riffs.transpose_notes([note(60), note(64)], 3)
    assert [entry["midi"] for entry in moved] == [63, 67]
    assert clamped == 0


def test_a_note_pushed_off_the_top_is_clamped_and_counted():
    """Clamped, not dropped, and the caller is told: a silent edit is the failure."""
    moved, clamped = riffs.transpose_notes([note(120)], 12)
    assert moved[0]["midi"] == 127
    assert clamped == 1


def test_a_note_pushed_off_the_bottom_is_clamped_and_counted():
    moved, clamped = riffs.transpose_notes([note(3)], -12)
    assert moved[0]["midi"] == 0
    assert clamped == 1


def test_clamping_keeps_the_number_alias_in_step():
    """The export carries `number` beside `midi`, and a stale alias would confuse."""
    moved, _ = riffs.transpose_notes([note(120)], 12)
    assert moved[0]["number"] == moved[0]["midi"]


def test_transposition_does_not_alter_the_input():
    notes = [note(60)]
    riffs.transpose_notes(notes, 5)
    assert notes[0]["midi"] == 60


# --- matching ----------------------------------------------------------------


def test_a_query_matches_the_name():
    assert riffs.match(riff(), query="stab") is True


def test_a_query_matches_a_tag_and_the_mood():
    assert riffs.match(riff(), query="dark") is True


def test_a_query_matches_the_instrument():
    assert riffs.match(riff(), query="astronomic") is True


def test_a_query_matches_the_key_name():
    assert riffs.match(riff(), query="a minor") is True


def test_matching_is_case_insensitive():
    assert riffs.match(riff(), query="STAB") is True


def test_a_query_that_matches_nothing_is_false():
    assert riffs.match(riff(), query="polka") is False


def test_every_named_tag_must_be_present():
    assert riffs.match(riff(), tags=["dark", "stab"]) is True
    assert riffs.match(riff(), tags=["dark", "polka"]) is False


def test_tags_are_matched_without_regard_to_case():
    assert riffs.match(riff(), tags=["DARK"]) is True


def test_an_empty_filter_matches_everything():
    assert riffs.match(riff()) is True
    assert riffs.match(riff(), tags=[], query=None, instrument=None) is True


def test_a_key_filter_takes_a_pitch_class_or_a_full_key_name():
    assert riffs.match(riff(), key="A") is True
    assert riffs.match(riff(), key="a minor") is True
    assert riffs.match(riff(), key="C") is False


def test_an_instrument_filter_is_a_substring():
    assert riffs.match(riff(), instrument="808") is True
    assert riffs.match(riff(), instrument="Serum") is False


def test_a_minimum_note_count_can_be_asked_for():
    assert riffs.match(riff(), min_notes=2) is True
    assert riffs.match(riff(), min_notes=3) is False


def test_a_record_without_a_key_does_not_match_a_key_filter():
    record = riff(context={"scale_set": False, "tsnum": 4, "tsden": 4})
    assert riffs.match(record, key="A") is False


# --- searching ---------------------------------------------------------------


def test_search_returns_newest_first():
    older = riff("first", when=moment("2026-09-19T10:00:00"))
    newer = riff("second", when=moment("2026-09-19T12:00:00"))
    found = riffs.search([older, newer])
    assert [record["name"] for record in found] == ["second", "first"]


def test_search_applies_the_limit_after_filtering():
    records = [riff(f"take {index}") for index in range(5)]
    assert len(riffs.search(records, limit=2)) == 2


def test_search_of_nothing_is_empty():
    assert riffs.search([], query="anything") == []


# --- summaries ---------------------------------------------------------------


def test_a_summary_holds_no_note_list():
    """Search results have to fit in a context window, so notes stay out of them."""
    summary = riffs.summarise(riff())
    assert "notes" not in summary
    assert summary["note_count"] == 2
    assert summary["name"] == "deep stab"
    assert summary["key"] == "A minor"
    assert summary["length_beats"] == pytest.approx(2.0)


def test_a_summary_names_what_a_recall_would_write():
    summary = riffs.summarise(riff())
    assert summary["instrument"] == "808 Astronomic"
    assert summary["id"]


def test_recall_notes_drops_the_tick_aliases_the_script_ignores():
    """The request carries beats, which is what the script converts back."""
    notes, clamped = riffs.recall_notes(riff(), semitones=0)
    assert clamped == 0
    assert "time_ticks" not in notes[0]
    assert "length_ticks" not in notes[0]
    assert notes[0]["time"] == 0.0
    assert notes[0]["duration"] == 1.0


def test_recall_notes_applies_the_transposition():
    notes, _ = riffs.recall_notes(riff(), semitones=-2)
    assert [entry["midi"] for entry in notes] == [55, 58]
