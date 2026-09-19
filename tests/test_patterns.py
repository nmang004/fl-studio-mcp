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
    """The selection is what getAll reports, read back as a 0-based index."""
    fl_env.controller.dispatch_command("patterns.select", {"index": 0})
    result = fl_env.controller.dispatch_command("patterns.getAll", {})
    assert result["current"] == 0, "getAll reports a 0-based index"
    assert [p["is_current"] for p in result["patterns"]] == [True]


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


def test_pattern_actions_need_an_index(fl_env):
    for action in ("patterns.setName", "patterns.setColor", "patterns.select"):
        result = fl_env.controller.dispatch_command(action, {})
        assert "error" in result, f"{action} accepted no index"
        assert "index" in result["error"]


def test_clone_is_refused_before_its_arguments_are_even_checked(fl_env):
    """The refusal must not be reachable-around by omitting an argument."""
    result = fl_env.controller.dispatch_command("patterns.clone", {})
    assert "error" in result
    assert "froze FL Studio" in result["error"]


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
