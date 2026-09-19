"""Patterns are FL's unit of work, and the server ignored them entirely.

The upstream README claimed they cannot be created. findFirstNextEmptyPat exists
in the stubs, and selecting the next empty pattern and writing into it is creation
in practice, so the claim is wrong and this covers it.
"""

from __future__ import annotations


def test_get_all_patterns_lists_them_with_their_properties(fl_env):
    fl_env.controller.dispatch_command("patterns.setName", {"index": 0, "name": "Verse"})
    result = fl_env.controller.dispatch_command("patterns.getAll", {})
    assert len(result["patterns"]) == 1
    entry = result["patterns"][0]
    assert entry["index"] == 0
    assert entry["name"] == "Verse"
    assert entry["length"] > 0
    assert entry["is_current"] is True


def test_get_all_patterns_marks_the_current_one(fl_env):
    """Pattern 0 holds notes, so createEmpty makes and selects pattern 1."""
    fl_env.project.notes_by_pattern = {0: [object()]}
    fl_env.controller.dispatch_command("patterns.createEmpty", {})
    result = fl_env.controller.dispatch_command("patterns.getAll", {})
    assert result["current"] == 1, "getAll reports a 0-based index"
    assert [p["is_current"] for p in result["patterns"]] == [False, True]


def test_set_name_changes_the_name(fl_env):
    fl_env.controller.dispatch_command("patterns.setName", {"index": 0, "name": "Drop"})
    assert fl_env.project.pattern(0).name == "Drop"


def test_set_color_writes_the_value_through(fl_env):
    fl_env.controller.dispatch_command("patterns.setColor", {"index": 0, "color": 0x112233})
    assert fl_env.project.pattern(0).color == 0x112233


def test_select_moves_the_current_pattern(fl_env):
    fl_env.controller.dispatch_command("patterns.createEmpty", {})
    fl_env.controller.dispatch_command("patterns.select", {"index": 0})
    assert fl_env.project.current_pattern == 0


def test_clone_adds_a_pattern_named_after_its_source(fl_env):
    fl_env.controller.dispatch_command("patterns.setName", {"index": 0, "name": "Verse"})
    result = fl_env.controller.dispatch_command("patterns.clone", {"index": 0})
    assert result["cloned"] == 1
    assert "Verse" in fl_env.project.pattern(1).name


def test_create_empty_makes_one_when_the_current_pattern_holds_notes(fl_env):
    """Pattern 0 is in use, so a new one is needed."""
    fl_env.project.notes_by_pattern = {0: [object()]}
    result = fl_env.controller.dispatch_command("patterns.createEmpty", {})
    assert result["created"] == 1
    assert fl_env.project.pattern(1).name


def test_create_empty_twice_does_not_consume_two_slots(fl_env):
    """A new pattern holds no notes, so it is still the next empty one.

    Without this, calling the tool twice before writing anything would create two
    patterns and leave a stray empty slot in the user's project.
    """
    fl_env.project.notes_by_pattern = {0: [object()]}
    first = fl_env.controller.dispatch_command("patterns.createEmpty", {})
    second = fl_env.controller.dispatch_command("patterns.createEmpty", {})
    assert second["created"] == first["created"]
    assert second["was_existing"] is True
    assert fl_env.modules["patterns"].patternCount() == first["created"] + 1


def test_create_empty_names_a_new_pattern(fl_env):
    fl_env.project.notes_by_pattern = {0: [object()]}
    result = fl_env.controller.dispatch_command(
        "patterns.createEmpty", {"name": "Chorus"}
    )
    assert result["name"] == "Chorus"
    assert fl_env.project.pattern(1).name == "Chorus"


def test_a_reused_pattern_keeps_its_name(fl_env):
    """Naming an existing empty pattern would overwrite what the user called it."""
    fl_env.project.notes_by_pattern = {}
    fl_env.project.pattern(0).name = "My Idea"
    result = fl_env.controller.dispatch_command(
        "patterns.createEmpty", {"name": "Ignored"}
    )
    assert result["created"] == 0
    assert result["was_existing"] is True
    assert result["name"] == "My Idea"


def test_pattern_actions_need_an_index(fl_env):
    for action in ("patterns.setName", "patterns.setColor", "patterns.select",
                   "patterns.clone"):
        result = fl_env.controller.dispatch_command(action, {})
        assert "error" in result, f"{action} accepted no index"
        assert "index" in result["error"]


def test_pattern_actions_refuse_an_index_that_does_not_exist(fl_env):
    result = fl_env.controller.dispatch_command("patterns.select", {"index": 99})
    assert "error" in result
    assert "99" in result["error"]


def test_a_mutating_pattern_action_is_refused_when_not_safe_to_edit(fl_env):
    fl_env.project.safe_to_edit = False
    result = fl_env.controller.dispatch_command(
        "patterns.setName", {"index": 0, "name": "Nope"}
    )
    assert "error" in result
    assert "safe to edit" in result["error"].lower()


def test_reads_are_not_refused(fl_env):
    fl_env.project.safe_to_edit = False
    assert "error" not in fl_env.controller.dispatch_command("patterns.getAll", {})
