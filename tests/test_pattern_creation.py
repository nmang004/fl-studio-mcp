"""Pattern slot creation is disarmed, because it froze FL Studio twice.

On 2026-09-19 `patterns.findFirstNextEmptyPat` hung FL Studio 2026 build 5406 on two
separate live sessions. The first time it was called with flags 0, which the stubs say
also asks FL to prompt for a pattern name. The second time it was called with
`FFNEP_FindFirst | FFNEP_DontPromptName` and its documented `None` return was no longer
used, and it froze exactly the same way. So the prompt was not the cause: the function
itself hangs this build, and it is marked HELP WANTED upstream with two arguments
documented as "???".

Two things follow, and both are tested here. The shipping behaviour is a refusal that
never touches FL and tells the caller to make the pattern by hand. Behind that refusal
the corrected call is kept, and these tests exercise it by lifting the block, so the
day somebody verifies it against a fresh FL Studio with the project saved first,
re-enabling it is one line rather than a rewrite.
"""

from __future__ import annotations

import pytest


def find_flags(fl_env) -> list[int]:
    return fl_env.project.pattern_find_flags


@pytest.fixture
def unblocked(fl_env, monkeypatch):
    """The block lifted, as it would be after a live verification."""
    monkeypatch.setattr(fl_env.controller, "PATTERN_SLOT_CREATION_BLOCKED", False)
    return fl_env


# --- what ships ---------------------------------------------------------------


def test_the_block_is_on(fl_env):
    assert fl_env.controller.PATTERN_SLOT_CREATION_BLOCKED is True


def test_creating_a_pattern_is_refused_without_touching_fl(fl_env):
    """The function that freezes FL must not be reached at all, not merely reported."""
    result = fl_env.controller.dispatch_command("patterns.createEmpty", {})
    assert "error" in result
    assert "froze FL Studio" in result["error"]
    assert find_flags(fl_env) == [], "findFirstNextEmptyPat was called"


def test_the_refusal_says_how_to_get_a_pattern_anyway(fl_env):
    """A refusal that leaves the caller stuck is only half a refusal."""
    error = fl_env.controller.dispatch_command("patterns.createEmpty", {})["error"]
    assert "by hand" in error
    assert "patterns.select" in error, "the safe alternative is named"


def test_the_refusal_says_what_would_re_enable_it(fl_env):
    error = fl_env.controller.dispatch_command("patterns.createEmpty", {})["error"]
    assert "PATTERN_SLOT_CREATION_BLOCKED" in error


def test_cloning_a_pattern_is_refused_without_touching_fl(fl_env):
    """clonePattern allocates a pattern slot and has never been run live.

    This is a precaution rather than an observation: the sibling allocator hung twice,
    and one freeze already cost a session.
    """
    before = list(fl_env.project.patterns)
    result = fl_env.controller.dispatch_command("patterns.clone", {"index": 0})
    assert "error" in result
    assert fl_env.project.patterns == before, "a slot was allocated"


def test_the_refusal_applies_even_when_a_name_was_given(fl_env):
    result = fl_env.controller.dispatch_command("patterns.createEmpty", {"name": "Chorus"})
    assert "error" in result
    assert fl_env.project.patterns[0].name != "Chorus"


@pytest.mark.parametrize("action", ["patterns.createEmpty", "patterns.clone"])
def test_the_pattern_writes_stay_behind_the_edit_gate(fl_env, action):
    """Both are edits, so neither may run while FL is busy, block or no block."""
    fl_env.project.safe_to_edit = False
    result = fl_env.controller.dispatch_command(action, {})
    assert result.get("success") is False or "error" in result


# --- the corrected call, kept tested behind the block -------------------------


def test_the_corrected_call_never_asks_fl_to_prompt_for_a_name(unblocked):
    """The flag is right even though it turned out not to be the cause."""
    unblocked.controller.dispatch_command("patterns.createEmpty", {})
    flags = find_flags(unblocked)
    assert flags, "findFirstNextEmptyPat was not called"
    for word in flags:
        assert word & unblocked.modules["midi"].FFNEP_DontPromptName, (
            f"flags {word} would make FL prompt for a pattern name"
        )


def test_the_corrected_flags_word_is_find_first_without_the_prompt(unblocked):
    unblocked.controller.dispatch_command("patterns.createEmpty", {})
    assert find_flags(unblocked) == [
        unblocked.modules["midi"].FFNEP_FindFirst
        | unblocked.modules["midi"].FFNEP_DontPromptName
    ]


def test_the_index_comes_from_the_selection_not_from_a_return_value(unblocked):
    """The stub declares the return as None, so reading it raises TypeError.

    That was a real defect in its own right, found while investigating the freeze:
    the handler compared None with patternCount. The fake now returns None like the
    real API, so a regression is a TypeError rather than a wrong answer.
    """
    unblocked.project.notes_by_pattern[0] = [object()]  # pattern 0 is occupied
    result = unblocked.controller.dispatch_command("patterns.createEmpty", {})
    assert result["created"] == 1
    assert result["was_existing"] is False


def test_an_existing_empty_pattern_is_reused_and_keeps_its_name(unblocked):
    unblocked.project.notes_by_pattern[0] = [object()]
    unblocked.controller.dispatch_command("patterns.createEmpty", {})
    unblocked.controller.dispatch_command("patterns.setName", {"index": 1, "name": "Chorus"})
    second = unblocked.controller.dispatch_command("patterns.createEmpty", {})
    assert second["was_existing"] is True
    assert second["name"] == "Chorus"


def test_a_selection_that_never_happened_is_reported_not_guessed(unblocked, monkeypatch):
    """Zero from patternNumber means nothing is selected, which is not index -1."""

    def select_nothing(flags: int, x: int = -1, y: int = -1) -> None:
        unblocked.project.pattern_find_flags.append(flags)
        unblocked.project.current_pattern = -1
        return None

    monkeypatch.setitem(
        unblocked.modules["patterns"].__dict__, "findFirstNextEmptyPat", select_nothing
    )
    result = unblocked.controller.dispatch_command("patterns.createEmpty", {})
    assert "error" in result
    assert "no pattern" in result["error"].lower()


def test_a_selection_past_the_end_is_reported_not_used(unblocked, monkeypatch):
    """A number outside the count would name a pattern that does not exist."""

    def select_too_far(flags: int, x: int = -1, y: int = -1) -> None:
        unblocked.project.pattern_find_flags.append(flags)
        unblocked.project.current_pattern = 40
        return None

    monkeypatch.setitem(
        unblocked.modules["patterns"].__dict__, "findFirstNextEmptyPat", select_too_far
    )
    result = unblocked.controller.dispatch_command("patterns.createEmpty", {})
    assert "error" in result
    assert "outside" in result["error"]
