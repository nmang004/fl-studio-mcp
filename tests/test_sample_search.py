"""Sample search: the walk, the filters, and what the reply admits to.

Every folder here is built in tmp_path, because the real corpus on this machine is the
producer's and a test that walked it would answer differently on every machine. The
headers are assembled by hand for the same reason the reader exists: two of them need a
compressed RIFF payload, and no real file may be checked into the repository.
"""

from __future__ import annotations

import os
import struct
from pathlib import Path

import pytest

from fl_studio_mcp.musical import samples as matching
from fl_studio_mcp.tools import samples as sample_tool
from fl_studio_mcp.utils import paths


def write_pcm_wav(
    path: Path,
    seconds: float = 1.0,
    *,
    rate: int = 8000,
    channels: int = 1,
    bits: int = 16,
) -> Path:
    """A real PCM wav, short enough to write in full and long enough to measure."""
    block_align = channels * bits // 8
    data = b"\x00" * (int(seconds * rate) * block_align)
    payload = struct.pack("<HHIIHH", 1, channels, rate, rate * block_align, block_align, bits)
    body = b"WAVE" + _chunk(b"fmt ", payload) + _chunk(b"data", data)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)
    return path


def write_vorbis_wav(path: Path) -> Path:
    """A FL factory style wav: Ogg Vorbis in a RIFF container, tag 0x674F.

    There is no duration to be had from this without decoding it, which is the whole
    reason the search tool reports one instead of inventing one.
    """
    payload = struct.pack("<HHIIHH", 0x674F, 2, 44100, 176400, 4, 16)
    body = (
        b"WAVE"
        + _chunk(b"fmt ", payload)
        + _chunk(b"data", b"OggS" + b"\x00" * 200)
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)
    return path


def write_flac(path: Path, seconds: float = 1.0, *, rate: int = 44100) -> Path:
    """A FLAC header whose STREAMINFO declares its rate and total sample count."""
    packed = (rate << 44) | (1 << 41) | (15 << 36) | int(seconds * rate)
    streaminfo = b"\x00" * 10 + packed.to_bytes(8, "big") + b"\x00" * 16
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"fLaC" + b"\x80" + len(streaminfo).to_bytes(3, "big") + streaminfo)
    return path


def _chunk(chunk_id: bytes, payload: bytes) -> bytes:
    padding = b"\x00" if len(payload) % 2 else b""
    return chunk_id + struct.pack("<I", len(payload)) + payload + padding


@pytest.fixture
def library(tmp_path) -> Path:
    """A small folder tree with one of every case the search has to tell apart."""
    root = tmp_path / "samples"
    write_pcm_wav(root / "Drums" / "Kick 01.wav", 1.0)
    write_pcm_wav(root / "Drums" / "Snare 01.wav", 0.5)
    write_pcm_wav(root / "Deep House" / "bass stab.wav", 1.0)
    write_pcm_wav(root / "deep chord.wav", 1.0)
    write_vorbis_wav(root / "Packs" / "Kick OGG.WAV")
    write_flac(root / "Packs" / "Pad.flac", 1.0)
    return root


def names(reply: dict) -> set[str]:
    return {row["name"] for row in reply["samples"]}


def test_a_query_matches_the_file_name_case_insensitively(library):
    reply = sample_tool.find_samples(query="kick", folder=str(library))
    assert names(reply) == {"Kick 01.wav", "Kick OGG.WAV"}


def test_a_query_matches_the_folder_path_too(library):
    """A producer searching "deep" means the folder as much as a file name."""
    reply = sample_tool.find_samples(query="deep", folder=str(library))
    assert names(reply) == {"bass stab.wav", "deep chord.wav"}


def test_a_name_match_sorts_above_a_folder_match():
    """Type "deep" and the file called deep is the answer, not the folder called Deep."""
    entries = [
        {"name": "bass stab.wav", "path": "/x/Deep House/bass stab.wav"},
        {"name": "deep chord.wav", "path": "/x/deep chord.wav"},
    ]
    ranked = matching.rank(entries, "deep")
    assert [entry["name"] for entry in ranked] == ["deep chord.wav", "bass stab.wav"]


def test_a_name_match_sorts_above_a_folder_match_end_to_end(library):
    reply = sample_tool.find_samples(query="deep", folder=str(library))
    assert reply["samples"][0]["name"] == "deep chord.wav"


def test_a_lowercase_format_filter_matches_an_uppercase_extension(library):
    """One FL tree holds both .wav and .WAV, so the filter cannot be case sensitive."""
    reply = sample_tool.find_samples(formats=["wav"], folder=str(library))
    assert "Pad.flac" not in names(reply)
    assert "Kick OGG.WAV" in names(reply)
    assert reply["total"] == 5


def test_a_format_filter_accepts_a_leading_dot_and_any_case():
    info = {"format": "flac", "duration": 1.0}
    assert matching.matches(info, formats=[".FLAC"], path="/x/pad.flac")
    assert not matching.matches(info, formats=["wav"], path="/x/pad.flac")


def test_a_duration_filter_excludes_a_file_whose_duration_is_unknown(library):
    """The FL factory wav has no measurable duration, so it cannot be claimed to fit."""
    reply = sample_tool.find_samples(min_seconds=0.75, folder=str(library))
    assert "Kick OGG.WAV" not in names(reply)
    assert reply["skipped"]["unknown_duration"] == 1
    assert "could not be measured" in reply["message"]


def test_a_duration_filter_is_an_upper_bound_too(library):
    reply = sample_tool.find_samples(max_seconds=0.75, folder=str(library))
    assert names(reply) == {"Snare 01.wav"}


def test_the_unknown_duration_count_respects_the_other_filters(tmp_path):
    """A caller filtering for wav is not told about the WavPack files they excluded."""
    root = tmp_path / "counted"
    write_pcm_wav(root / "Kick.wav", 1.0)
    write_vorbis_wav(root / "Pad.wav")
    (root / "Pad.wv").write_bytes(b"wvpk" + b"\x00" * 64)
    every = sample_tool.find_samples(min_seconds=0.5, folder=str(root))
    assert every["skipped"]["unknown_duration"] == 2
    only_wav = sample_tool.find_samples(min_seconds=0.5, formats=["wav"], folder=str(root))
    assert only_wav["skipped"]["unknown_duration"] == 1


def test_a_file_with_no_measurable_duration_is_still_listed(library):
    """It is a sample FL can play, so it belongs in the answer, without a number."""
    reply = sample_tool.find_samples(query="kick", folder=str(library))
    rows = {row["name"]: row for row in reply["samples"]}
    assert rows["Kick OGG.WAV"]["duration"] is None
    assert rows["Kick OGG.WAV"]["codec"] == "vorbis"
    assert "reason" in rows["Kick OGG.WAV"]
    assert rows["Kick 01.wav"]["duration"] == 1.0
    assert reply["unmeasured"] == 1


def test_a_missing_folder_is_reported_not_raised(tmp_path):
    missing = tmp_path / "never-installed"
    reply = sample_tool.find_samples(folder=str(missing))
    assert reply["success"] is True
    assert reply["samples"] == []
    assert reply["roots"] == []
    assert reply["missing"] == [str(missing)]
    assert str(missing) in reply["message"]


def test_a_folder_with_no_audio_in_it_says_so(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    reply = sample_tool.find_samples(folder=str(empty))
    assert reply["roots"] == [str(empty)]
    assert reply["examined"] == 0
    assert reply["samples"] == []


def test_the_walk_stops_at_the_file_bound_and_says_so(library, monkeypatch):
    monkeypatch.setattr(sample_tool, "MAX_FILES", 2)
    reply = sample_tool.find_samples(folder=str(library))
    assert reply["walk"]["file_limit_reached"] is True
    assert reply["examined"] == 2
    assert "stopped after 2 files" in reply["message"]


def test_the_walk_stops_at_the_depth_bound_and_says_so(library, monkeypatch):
    monkeypatch.setattr(sample_tool, "MAX_DEPTH", 0)
    reply = sample_tool.find_samples(folder=str(library))
    assert reply["walk"]["depth_limit_reached"] is True
    assert names(reply) == {"deep chord.wav"}
    assert "folder level" in reply["message"]


def test_results_are_capped_and_the_total_is_reported(library):
    reply = sample_tool.find_samples(folder=str(library), limit=2)
    assert reply["returned"] == 2
    assert reply["total"] == 6
    assert reply["truncated"] is True
    assert "The limit of 2" in reply["message"]


def test_the_reply_names_the_roots_that_were_searched(library):
    """A surprising answer has to be explainable, and where it looked is the start."""
    reply = sample_tool.find_samples(folder=str(library))
    assert reply["roots"] == [str(library)]
    assert reply["missing"] == []


def test_one_folder_can_replace_the_default_roots(library, monkeypatch):
    monkeypatch.setenv(paths.SAMPLE_DIRS_ENV, str(library / "Packs"))
    reply = sample_tool.find_samples(folder=str(library / "Drums"))
    assert reply["roots"] == [str(library / "Drums")]
    assert names(reply) == {"Kick 01.wav", "Snare 01.wav"}


def test_the_default_roots_come_from_the_paths_module(library, monkeypatch):
    monkeypatch.setattr(paths, "sample_roots", lambda: [library])
    reply = sample_tool.find_samples()
    assert reply["roots"] == [str(library)]
    assert reply["total"] == 6


def test_a_non_audio_file_is_skipped_and_counted(tmp_path):
    root = tmp_path / "mixed"
    root.mkdir()
    (root / "readme.txt").write_text("not a sample")
    write_pcm_wav(root / "Kick.wav")
    reply = sample_tool.find_samples(folder=str(root))
    assert reply["examined"] == 2
    assert reply["skipped"]["not_audio"] == 1
    assert names(reply) == {"Kick.wav"}


def test_an_unreadable_audio_file_is_skipped_and_counted(tmp_path):
    root = tmp_path / "broken"
    root.mkdir()
    (root / "Kick.wav").write_bytes(b"not a wav at all, whatever the name says")
    reply = sample_tool.find_samples(folder=str(root))
    assert reply["skipped"]["unreadable_header"] == 1
    assert reply["samples"] == []


def test_the_elapsed_time_is_reported(library):
    reply = sample_tool.find_samples(folder=str(library))
    assert isinstance(reply["elapsed_ms"], float)
    assert reply["elapsed_ms"] >= 0


def test_a_result_row_carries_the_numbers_and_the_reason():
    row = matching.summarise(
        {
            "name": "Kick OGG.WAV",
            "path": "/x/Packs/Kick OGG.WAV",
            "format": "wav",
            "codec": "vorbis",
            "duration": None,
            "readable": False,
            "reason": "compressed",
        }
    )
    assert row["name"] == "Kick OGG.WAV"
    assert row["folder"] == "/x/Packs"
    assert row["codec"] == "vorbis"
    assert row["duration"] is None
    assert row["readable"] is False
    assert row["reason"] == "compressed"
    assert "sample_rate" in row


def test_matching_reads_the_path_from_the_info_dictionary_when_none_is_given():
    info = {"format": "wav", "duration": 1.0, "path": "/x/Drums/Kick 01.wav"}
    assert matching.matches(info, query="drums")
    assert not matching.matches(info, query="snare")


def test_a_filter_that_was_not_given_narrows_nothing():
    info = {"format": "wav", "duration": 1.0, "path": "/x/kick.wav"}
    assert matching.matches(info)


def test_the_override_environment_variable_wins(monkeypatch, tmp_path):
    first = tmp_path / "one"
    second = tmp_path / "two"
    first.mkdir()
    second.mkdir()
    monkeypatch.setenv(paths.SAMPLE_DIRS_ENV, os.pathsep.join([str(first), str(second)]))
    assert paths.sample_roots() == [first, second]


def test_an_override_path_that_is_not_there_is_kept_so_it_can_be_reported(
    monkeypatch, tmp_path
):
    """The caller asked for it by name, so the answer must be able to say it is missing."""
    gone = tmp_path / "moved-drive" / "samples"
    monkeypatch.setenv(paths.SAMPLE_DIRS_ENV, str(gone))
    assert paths.sample_roots() == [gone]


def test_the_default_roots_are_only_ones_that_exist(monkeypatch):
    monkeypatch.delenv(paths.SAMPLE_DIRS_ENV, raising=False)
    for root in paths.sample_roots():
        assert root.is_dir(), f"{root} was listed but is not there"


def test_the_factory_packs_folder_is_discovered_not_hardcoded(monkeypatch, tmp_path):
    """The folder name carries the release year, so a fixed path breaks on upgrade."""
    packs = (
        tmp_path
        / "FL Studio 2049.app"
        / "Contents"
        / "Resources"
        / "FL"
        / "Data"
        / "Patches"
        / "Packs"
    )
    packs.mkdir(parents=True)
    monkeypatch.setattr(paths, "MACOS_APPLICATIONS", tmp_path)
    monkeypatch.delenv(paths.SAMPLE_DIRS_ENV, raising=False)
    assert packs in paths.sample_roots()


def test_the_factory_packs_folder_is_left_out_when_there_is_no_bundle(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(paths, "MACOS_APPLICATIONS", tmp_path / "nothing-installed")
    monkeypatch.delenv(paths.SAMPLE_DIRS_ENV, raising=False)
    listed = paths.sample_roots()
    assert all("Packs" not in str(root) for root in listed)
