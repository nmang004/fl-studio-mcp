"""Creating a pattern must never ask FL to open its name prompt.

On 2026-09-19 a live session froze on this call. The controller passed flags 0 to
`patterns.findFirstNextEmptyPat`, and per `midi/__ffnep_flags.py` flags 0 means "find
first and prompt the user for a pattern name". That prompt is modal: it never
returned, FL stopped answering MIDI, and the window showed a spinning wait cursor.

The same stub documents the return as `None` (`patterns/__properties.py:189`), while
the handler compared it with `patternCount()`. The fake used to return an index, so
the suite agreed with both mistakes. These tests exist so that neither can come back.
"""

from __future__ import annotations

import pytest


def find_flags(fl_env) -> list[int]:
    return fl_env.project.pattern_find_flags


def test_creating_a_pattern_never_asks_fl_to_prompt_for_a_name(fl_env):
    """The flag is the whole fix. Without it FL opens a modal dialog and stops."""
    fl_env.controller.dispatch_command("patterns.createEmpty", {})
    flags = find_flags(fl_env)
    assert flags, "findFirstNextEmptyPat was not called at all"
    for word in flags:
        assert word & fl_env.modules["midi"].FFNEP_DontPromptName, (
            f"flags {word} would make FL prompt for a pattern name"
        )


def test_the_flags_word_is_find_first_without_the_prompt(fl_env):
    fl_env.controller.dispatch_command("patterns.createEmpty", {})
    assert find_flags(fl_env) == [
        fl_env.modules["midi"].FFNEP_FindFirst | fl_env.modules["midi"].FFNEP_DontPromptName
    ]


def test_the_return_value_is_not_used_as_an_index(fl_env):
    """The stub says None, so a handler that reads it would raise on the next line.

    The index has to come from the selection, read with patternNumber. The fake now
    returns None like the real API, so a regression here is a TypeError rather than
    a wrong answer.
    """
    fl_env.project.notes_by_pattern[0] = [object()]  # pattern 0 is occupied
    result = fl_env.controller.dispatch_command("patterns.createEmpty", {})
    assert result["created"] == 1
    assert result["was_existing"] is False


def test_a_created_pattern_is_named_like_fl_names_its_own(fl_env):
    result = fl_env.controller.dispatch_command("patterns.createEmpty", {})
    assert result["name"] == f"Pattern {result['created']}"


def test_an_existing_empty_pattern_is_reused_and_keeps_its_name(fl_env):
    fl_env.project.notes_by_pattern[0] = [object()]
    fl_env.controller.dispatch_command("patterns.createEmpty", {})
    fl_env.controller.dispatch_command("patterns.setName", {"index": 1, "name": "Chorus"})
    second = fl_env.controller.dispatch_command("patterns.createEmpty", {})
    assert second["was_existing"] is True
    assert second["name"] == "Chorus"


def test_a_selection_that_never_happened_is_reported_not_guessed(fl_env, monkeypatch):
    """Zero from patternNumber means nothing is selected, which is not index -1."""

    def select_nothing(flags: int, x: int = -1, y: int = -1) -> None:
        fl_env.project.pattern_find_flags.append(flags)
        fl_env.project.current_pattern = -1
        return None

    monkeypatch.setitem(
        fl_env.modules["patterns"].__dict__, "findFirstNextEmptyPat", select_nothing
    )
    result = fl_env.controller.dispatch_command("patterns.createEmpty", {})
    assert "error" in result
    assert "no pattern" in result["error"].lower()


def test_a_selection_past_the_end_is_reported_not_used(fl_env, monkeypatch):
    """A number outside the count would name a pattern that does not exist."""

    def select_too_far(flags: int, x: int = -1, y: int = -1) -> None:
        fl_env.project.pattern_find_flags.append(flags)
        fl_env.project.current_pattern = 40
        return None

    monkeypatch.setitem(
        fl_env.modules["patterns"].__dict__, "findFirstNextEmptyPat", select_too_far
    )
    result = fl_env.controller.dispatch_command("patterns.createEmpty", {})
    assert "error" in result
    assert "outside" in result["error"]


@pytest.mark.parametrize("action", ["patterns.createEmpty", "patterns.clone"])
def test_the_pattern_writes_stay_behind_the_edit_gate(fl_env, action):
    """Creating and cloning are edits, so they are refused while FL is busy."""
    fl_env.project.safe_to_edit = False
    result = fl_env.controller.dispatch_command(action, {})
    assert result.get("success") is False or "error" in result
