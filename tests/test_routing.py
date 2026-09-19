"""Routing is how FL gets from channels to inserts, and the server ignored it."""

from __future__ import annotations

import pytest


def test_get_routing_lists_the_destinations(fl_env):
    fl_env.project.track(1).routes = {0: 1.0}
    result = fl_env.controller.dispatch_command("mixer.getRouting", {"track": 1})
    assert result["track"] == 1
    assert [s["track"] for s in result["sends"]] == [0]
    assert result["sends"][0]["active"] is True


def test_get_routing_reports_the_level_and_the_name(fl_env):
    fl_env.project.track(1).routes = {0: 0.5}
    result = fl_env.controller.dispatch_command("mixer.getRouting", {"track": 1})
    assert result["sends"][0]["level"] == pytest.approx(0.5)
    assert result["sends"][0]["name"] == "Master"


def test_get_routing_names_the_source_track(fl_env):
    result = fl_env.controller.dispatch_command("mixer.getRouting", {"track": 1})
    assert result["name"] == "Insert 1"


def test_get_routing_can_report_every_track(fl_env):
    result = fl_env.controller.dispatch_command("mixer.getRouting", {})
    assert len(result["tracks"]) == 8
    assert "sends" in result["tracks"][0]


def test_set_routing_adds_a_send(fl_env):
    fl_env.controller.dispatch_command("mixer.setRouting", {
        "track": 1, "sends": [{"track": 3, "level": 0.4}],
    })
    assert fl_env.project.track(1).routes.get(3) == pytest.approx(0.4)


def test_set_routing_removes_a_send(fl_env):
    fl_env.project.track(1).routes = {3: 1.0}
    fl_env.controller.dispatch_command("mixer.setRouting", {
        "track": 1, "sends": [{"track": 3, "remove": True}],
    })
    assert 3 not in fl_env.project.track(1).routes


def test_set_routing_leaves_unmentioned_sends_alone(fl_env):
    fl_env.project.track(1).routes = {2: 1.0, 3: 1.0}
    fl_env.controller.dispatch_command("mixer.setRouting", {
        "track": 1, "sends": [{"track": 3, "remove": True}],
    })
    assert 2 in fl_env.project.track(1).routes


def test_set_routing_reads_the_result_back(fl_env):
    result = fl_env.controller.dispatch_command("mixer.setRouting", {
        "track": 1, "sends": [{"track": 3, "level": 0.4}],
    })
    assert [s["track"] for s in result["sends"]] == [3]


def test_set_routing_needs_a_track(fl_env):
    result = fl_env.controller.dispatch_command("mixer.setRouting", {"sends": []})
    assert "error" in result
    assert "track" in result["error"]


def test_set_routing_needs_sends(fl_env):
    result = fl_env.controller.dispatch_command("mixer.setRouting", {"track": 1})
    assert "error" in result
    assert "sends" in result["error"]


def test_set_routing_refuses_a_destination_that_does_not_exist(fl_env):
    result = fl_env.controller.dispatch_command("mixer.setRouting", {
        "track": 1, "sends": [{"track": 99, "level": 0.5}],
    })
    assert "error" in result
    assert "99" in result["error"]


def test_set_routing_refuses_a_send_to_itself(fl_env):
    """A track routing into itself is a feedback loop, not a routing decision."""
    result = fl_env.controller.dispatch_command("mixer.setRouting", {
        "track": 1, "sends": [{"track": 1, "level": 0.5}],
    })
    assert "error" in result
    assert "itself" in result["error"].lower()


def test_routing_writes_are_refused_when_not_safe_to_edit(fl_env):
    fl_env.project.safe_to_edit = False
    result = fl_env.controller.dispatch_command("mixer.setRouting", {
        "track": 1, "sends": [{"track": 3, "level": 0.5}],
    })
    assert "error" in result
    assert "safe to edit" in result["error"].lower()


def test_routing_reads_are_not_refused(fl_env):
    fl_env.project.safe_to_edit = False
    assert "error" not in fl_env.controller.dispatch_command("mixer.getRouting", {})
