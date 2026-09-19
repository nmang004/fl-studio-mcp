"""The library is plain JSON under one root, and record ids are untrusted input.

Every id in here can come from a model's tool call, so the interesting tests are the
ones that try to escape the library directory rather than the ones that round trip.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from fl_studio_mcp.utils import store

# A fixed moment, so an id is assertable rather than merely well shaped.
WHEN = datetime(2026, 9, 19, 12, 0, 0)


def test_the_root_can_be_moved(tmp_path, monkeypatch):
    """A producer with a second drive, or a test suite, has to be able to move it."""
    monkeypatch.setenv(store.LIBRARY_HOME_ENV, str(tmp_path / "elsewhere"))
    assert store.library_root() == tmp_path / "elsewhere"


def test_the_root_defaults_under_the_home_directory(monkeypatch):
    monkeypatch.delenv(store.LIBRARY_HOME_ENV, raising=False)
    monkeypatch.setenv("HOME", "/home/someone")
    assert store.library_root() == Path("/home/someone") / ".fl_studio_mcp"


def test_a_kind_directory_is_created_on_demand(tmp_path, monkeypatch):
    monkeypatch.setenv(store.LIBRARY_HOME_ENV, str(tmp_path / "lib"))
    path = store.library_dir("riffs")
    assert path.is_dir()
    assert path.name == "riffs"


def test_an_unknown_kind_is_refused(tmp_path, monkeypatch):
    """Kinds are our own strings, so a surprise is a bug rather than user input."""
    monkeypatch.setenv(store.LIBRARY_HOME_ENV, str(tmp_path / "lib"))
    with pytest.raises(ValueError, match="unknown library kind"):
        store.library_dir("passwords")


def test_a_record_round_trips(tmp_path, monkeypatch):
    monkeypatch.setenv(store.LIBRARY_HOME_ENV, str(tmp_path / "lib"))
    payload = {"schema": 1, "name": "deep stab", "notes": [{"midi": 60}]}
    path = store.write_record("riffs", "2026-09-19-120000-deep-stab", payload)
    assert path.is_file()
    assert store.read_record("riffs", "2026-09-19-120000-deep-stab") == payload


def test_a_record_is_written_as_json_a_human_can_read(tmp_path, monkeypatch):
    """The producer owns these files, so they stay readable without this server."""
    monkeypatch.setenv(store.LIBRARY_HOME_ENV, str(tmp_path / "lib"))
    path = store.write_record("riffs", "r1", {"schema": 1, "name": "x"})
    text = path.read_text()
    assert json.loads(text) == {"schema": 1, "name": "x"}
    assert "\n" in text, "a trailing newline keeps diff tools happy"


def test_a_missing_record_reads_as_none(tmp_path, monkeypatch):
    monkeypatch.setenv(store.LIBRARY_HOME_ENV, str(tmp_path / "lib"))
    assert store.read_record("riffs", "never-written") is None


@pytest.mark.parametrize(
    "bad",
    ["../evil", "a/b", "..", ".hidden", "", "a\\b", "with space", "x" * 200, "./x"],
)
def test_an_id_that_could_escape_the_library_is_refused(bad):
    assert store.safe_record_id(bad) is None


def test_an_ordinary_id_is_allowed():
    assert store.safe_record_id("2026-09-19-120000-deep-stab") == "2026-09-19-120000-deep-stab"


def test_a_refused_id_is_not_written_anywhere(tmp_path, monkeypatch):
    """The point of the check. A traversal write is the failure this prevents."""
    root = tmp_path / "lib"
    monkeypatch.setenv(store.LIBRARY_HOME_ENV, str(root))
    with pytest.raises(ValueError, match="unsafe"):
        store.write_record("riffs", "../escaped", {"schema": 1})
    assert not (tmp_path / "escaped").exists()


def test_a_refused_id_is_not_deleted(tmp_path, monkeypatch):
    root = tmp_path / "lib"
    monkeypatch.setenv(store.LIBRARY_HOME_ENV, str(root))
    outsider = tmp_path / "keep-me.json"
    outsider.write_text("{}")
    assert store.delete_record("riffs", "../keep-me") is False
    assert outsider.exists()


def test_writing_over_a_record_is_refused(tmp_path, monkeypatch):
    """Silently replacing a riff the producer saved is not a save, it is a loss."""
    monkeypatch.setenv(store.LIBRARY_HOME_ENV, str(tmp_path / "lib"))
    store.write_record("riffs", "r1", {"schema": 1, "name": "first"})
    with pytest.raises(ValueError, match="already exists"):
        store.write_record("riffs", "r1", {"schema": 1, "name": "second"})
    assert store.read_record("riffs", "r1")["name"] == "first"


def test_a_unique_id_is_chosen_when_the_name_is_taken(tmp_path, monkeypatch):
    monkeypatch.setenv(store.LIBRARY_HOME_ENV, str(tmp_path / "lib"))
    first = store.unique_record_id("riffs", "deep stab", when=WHEN)
    store.write_record("riffs", first, {"schema": 1})
    second = store.unique_record_id("riffs", "deep stab", when=WHEN)
    assert second != first
    assert second.endswith("-2")


def test_an_id_says_when_it_was_made_and_what_it_is(tmp_path, monkeypatch):
    monkeypatch.setenv(store.LIBRARY_HOME_ENV, str(tmp_path / "lib"))
    made = store.new_record_id("Deep Stab!", when=WHEN)
    assert made == "2026-09-19-120000-deep-stab"


def test_a_name_with_nothing_usable_still_gets_an_id():
    made = store.new_record_id("***", when=WHEN)
    assert made == "2026-09-19-120000-record"


def test_records_list_newest_first(tmp_path, monkeypatch):
    monkeypatch.setenv(store.LIBRARY_HOME_ENV, str(tmp_path / "lib"))
    store.write_record("riffs", "2026-09-19-100000-old", {"created": "2026-09-19T10:00:00"})
    store.write_record("riffs", "2026-09-19-120000-new", {"created": "2026-09-19T12:00:00"})
    listed = store.list_records("riffs")
    assert [record["id"] for record in listed["records"]] == [
        "2026-09-19-120000-new",
        "2026-09-19-100000-old",
    ]
    assert listed["skipped"] == []


def test_an_unreadable_record_is_reported_not_raised(tmp_path, monkeypatch):
    """One truncated file must not hide the rest of a producer's library."""
    monkeypatch.setenv(store.LIBRARY_HOME_ENV, str(tmp_path / "lib"))
    store.write_record("riffs", "good", {"created": "2026-09-19T10:00:00"})
    (store.library_dir("riffs") / "broken.json").write_text("{not json")
    listed = store.list_records("riffs")
    assert [record["id"] for record in listed["records"]] == ["good"]
    assert listed["skipped"] == ["broken"]


def test_a_listing_can_be_capped(tmp_path, monkeypatch):
    monkeypatch.setenv(store.LIBRARY_HOME_ENV, str(tmp_path / "lib"))
    for index in range(5):
        store.write_record("riffs", f"r{index}", {"created": f"2026-09-19T1{index}:00:00"})
    listed = store.list_records("riffs", limit=2)
    assert len(listed["records"]) == 2
    assert listed["total"] == 5
    assert listed["truncated"] is True


def test_deleting_a_record_reports_whether_it_was_there(tmp_path, monkeypatch):
    monkeypatch.setenv(store.LIBRARY_HOME_ENV, str(tmp_path / "lib"))
    store.write_record("riffs", "r1", {"schema": 1})
    assert store.delete_record("riffs", "r1") is True
    assert store.delete_record("riffs", "r1") is False


def test_the_three_kinds_do_not_collide(tmp_path, monkeypatch):
    """A riff and a preset may share a name; they are different objects."""
    monkeypatch.setenv(store.LIBRARY_HOME_ENV, str(tmp_path / "lib"))
    store.write_record("riffs", "same-id", {"kind": "riff"})
    store.write_record("presets", "same-id", {"kind": "preset"})
    assert store.read_record("riffs", "same-id")["kind"] == "riff"
    assert store.read_record("presets", "same-id")["kind"] == "preset"
