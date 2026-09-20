"""The project index, over synthetic .flp files built in a temporary folder.

The byte helpers come from tests/test_flp_index.py rather than a second copy: the
container format has one implementation in this suite, and an index test that built its
own events could agree with a reader that is wrong. What is tested here is the layer
above the reader: which files are found, what each row reports, what happens to a file
the reader refuses, and where the answer came from.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

from fl_studio_mcp.tools import indexing
from tests.test_flp_index import _channel, _header_events, _project

# A fixed base time so "newest first" is a fact of the fixture rather than a race
# between files written in the same millisecond.
BASE_TIME = 1_700_000_000


def project_bytes(*, tempo: int = 130000, title: str = "Sketch") -> bytes:
    """One whole project file, with a channel so the plugins list is not empty."""
    events = _header_events(tempo=tempo, title=title) + _channel(
        2, "808 Astronomic", factory="FLEX"
    )
    return _project(events, channels=1)


def project_file(
    folder: Path,
    name: str,
    *,
    tempo: int = 130000,
    title: str = "Sketch",
    modified: float | None = None,
) -> Path:
    """Write one synthetic project into a folder, optionally with a set mtime."""
    path = folder / name
    path.write_bytes(project_bytes(tempo=tempo, title=title))
    if modified is not None:
        os.utime(path, (modified, modified))
    return path


def test_a_folder_of_projects_is_indexed_newest_first(tmp_path):
    project_file(tmp_path, "old.flp", tempo=120000, modified=BASE_TIME)
    project_file(tmp_path, "new.flp", tempo=140000, modified=BASE_TIME + 500)

    result = indexing.index_projects(tmp_path)

    assert result["success"] is True
    assert [row["name"] for row in result["projects"]] == ["new.flp", "old.flp"]
    newest = result["projects"][0]
    assert newest["tempo"] == 140.0
    assert newest["time_signature"] == {"tsnum": 4, "tsden": 4}
    assert newest["title"] == "Sketch"
    assert newest["version"] == "26.1.6.5406"
    assert newest["build"] == "5406"
    assert newest["size"] == len((tmp_path / "new.flp").read_bytes())
    assert newest["modified"] == BASE_TIME + 500
    assert newest["modified_iso"] == "2023-11-14T22:21:40+00:00"
    assert newest["plugin_names"] == ["808 Astronomic"]
    assert newest["status"] == "ok"
    assert newest["ok"] is True
    assert newest["problems"] == []


def test_the_scan_is_recursive_and_says_what_it_walked(tmp_path):
    """A project folder usually holds a Backup tree, and the autosave is the point."""
    (tmp_path / "Backup").mkdir()
    project_file(tmp_path, "current.flp", modified=BASE_TIME)
    project_file(tmp_path / "Backup", "autosave.flp", modified=BASE_TIME + 10)

    result = indexing.index_projects(tmp_path)

    assert [row["name"] for row in result["projects"]] == ["autosave.flp", "current.flp"]
    assert result["walk"]["examined"] == 2
    assert result["walk"]["file_limit_reached"] is False
    assert result["walk"]["depth_limit_reached"] is False


def test_a_file_that_is_not_a_project_is_a_row_with_its_status(tmp_path):
    """One bad file must not fail the scan, and must not disappear either."""
    project_file(tmp_path, "real.flp", modified=BASE_TIME)
    (tmp_path / "notes.flp").write_bytes(b"not a project, but it is named like one")
    (tmp_path / "half.flp").write_bytes(project_bytes()[:20])

    result = indexing.index_projects(tmp_path)

    assert result["success"] is True
    rows = {row["name"]: row for row in result["projects"]}
    assert rows["real.flp"]["ok"] is True
    assert rows["notes.flp"]["ok"] is False
    assert rows["notes.flp"]["status"] == "not_a_project"
    assert rows["notes.flp"]["problems"], "the reason has to come through"
    assert rows["notes.flp"]["tempo"] is None
    assert rows["half.flp"]["status"] == "truncated"
    assert result["total"] == 3
    assert result["unreadable"] == 2
    assert "2" in result["message"]


def test_a_file_that_is_not_a_project_file_is_skipped_and_counted(tmp_path):
    project_file(tmp_path, "real.flp")
    (tmp_path / "readme.txt").write_text("not a project")
    (tmp_path / "render.wav").write_bytes(b"RIFF")

    result = indexing.index_projects(tmp_path)

    assert result["total"] == 1
    assert result["unreadable"] == 0
    assert result["walk"]["examined"] == 3
    assert result["walk"]["not_flp"] == 2


def test_the_cap_is_reported(tmp_path):
    for index in range(4):
        project_file(tmp_path, f"sketch-{index}.flp", modified=BASE_TIME + index)

    result = indexing.index_projects(tmp_path, limit=2)

    assert result["success"] is True
    assert result["returned"] == 2
    assert result["total"] == 4
    assert result["truncated"] is True
    assert result["limit"] == 2
    assert [row["name"] for row in result["projects"]] == ["sketch-3.flp", "sketch-2.flp"]
    assert "limit of 2" in result["message"]


def test_a_limit_above_the_maximum_is_clamped(tmp_path):
    project_file(tmp_path, "one.flp")

    result = indexing.index_projects(tmp_path, limit=100000)

    assert result["limit"] == indexing.MAX_LIMIT


def test_a_missing_folder_is_reported_not_raised(tmp_path):
    result = indexing.index_projects(tmp_path / "not-there")

    assert result["success"] is False
    assert "not-there" in result["error"]
    assert result["projects"] == []
    assert result["total"] == 0
    assert result["cache"]["used"] is False


def test_the_folder_defaults_to_fl_studios_projects_folder(fl_settings):
    """The default is derived from the Settings folder, not written down."""
    projects = fl_settings.parent / "Projects"
    projects.mkdir(parents=True, exist_ok=True)
    project_file(projects, "last-night.flp")

    assert indexing.default_projects_folder() == projects
    result = indexing.index_projects()

    assert [row["name"] for row in result["projects"]] == ["last-night.flp"]


# --- the cache -----------------------------------------------------------------


def test_a_second_ask_is_served_from_the_cache(tmp_path):
    project_file(tmp_path, "one.flp")
    first = indexing.index_projects(tmp_path)
    assert first["cache"]["used"] is False
    assert first["cache"]["scanned_at"]
    assert Path(first["cache"]["path"]).is_file()

    project_file(tmp_path, "two.flp")
    second = indexing.index_projects(tmp_path)
    assert second["cache"]["used"] is True
    assert second["total"] == 1, "the cache is what was scanned, not a new walk"
    assert "cache" in second["message"].lower()

    refreshed = indexing.index_projects(tmp_path, refresh=True)
    assert refreshed["cache"]["used"] is False
    assert refreshed["total"] == 2


def test_the_cache_lives_under_the_library_root_not_the_project_folder(tmp_path, monkeypatch):
    """A producer's project folder belongs to FL Studio, so nothing is written there."""
    library = tmp_path / "library"
    monkeypatch.setenv("FL_STUDIO_MCP_HOME", str(library))
    projects = tmp_path / "projects"
    projects.mkdir()
    project_file(projects, "one.flp")

    result = indexing.index_projects(projects)

    cache_path = Path(result["cache"]["path"])
    assert cache_path.is_file()
    assert cache_path.is_relative_to(library)
    assert list(projects.iterdir()) == [projects / "one.flp"]


def test_an_unreadable_cache_is_reported_and_the_folder_is_walked_again(tmp_path):
    """A cache is an optimisation: a broken one costs a walk, never the answer."""
    project_file(tmp_path, "one.flp")
    first = indexing.index_projects(tmp_path)
    Path(first["cache"]["path"]).write_text("{ this is not json")

    second = indexing.index_projects(tmp_path)

    assert second["success"] is True
    assert second["total"] == 1
    assert second["cache"]["used"] is False
    assert second["cache"]["problem"]


def test_a_cached_scan_still_honours_a_new_limit(tmp_path):
    """The cache holds the scan, not the reply, so the cap is this call's cap."""
    for index in range(3):
        project_file(tmp_path, f"sketch-{index}.flp", modified=BASE_TIME + index)

    indexing.index_projects(tmp_path, limit=3)
    result = indexing.index_projects(tmp_path, limit=1)

    assert result["cache"]["used"] is True
    assert result["limit"] == 1
    assert result["returned"] == 1
    assert result["truncated"] is True


def test_the_index_tool_is_registered_by_name():
    mcp = FastMCP("test")
    indexing.register_index_tools(mcp)
    names = {tool.name for tool in asyncio.run(mcp._list_tools())}
    assert names == {"fl_index_projects"}


def test_the_tool_passes_its_arguments_through(tmp_path, monkeypatch):
    """The registered tool is the only way a client reaches this, so pin the wiring."""
    recorded: dict[str, Any] = {}

    def fake(folder=None, refresh=False, limit=indexing.DEFAULT_LIMIT):
        recorded.update(folder=folder, refresh=refresh, limit=limit)
        return {"success": True}

    monkeypatch.setattr(indexing, "index_projects", fake)
    mcp = FastMCP("test")
    indexing.register_index_tools(mcp)
    tool = asyncio.run(mcp.get_tool("fl_index_projects"))
    result = tool.fn(folder=str(tmp_path), refresh=True, limit=7)

    assert result == {"success": True}
    assert recorded == {"folder": str(tmp_path), "refresh": True, "limit": 7}
