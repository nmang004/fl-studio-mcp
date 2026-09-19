"""The project reader, against synthetic bytes rather than the producer's work.

CI has no FL Studio and the producer's projects are not this suite's to read, so every
file here is assembled from events: a helper builds one event, another builds the two
chunk container around the events, and each test states only the events it cares about.
The one case the bytes cannot make obvious is the 0xAC event, so its test asserts that
the fixture really holds the sequence this reader exists to handle.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fl_studio_mcp.utils import flp

# The reply shape, pinned so a refused file cannot quietly lose a key.
RESULT_KEYS = {
    "ok",
    "status",
    "problems",
    "header",
    "version",
    "build",
    "tempo",
    "title",
    "time_signature",
    "plugins",
    "size",
    "modified",
    "walk",
}


def _varint(value: int) -> bytes:
    """A base-128 little-endian length, the way a text event stores it."""
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _scalar(event_id: int, value: int) -> bytes:
    """One scalar event: the id, then a value whose width the id chooses.

    The 0xAC case is three bytes wide here too, because that is the measured quirk; a
    helper that used the published four would build files no FL Studio writes.
    """
    if event_id < 64:
        width = 1
    elif event_id < 128:
        width = 2
    elif event_id == 0xAC:
        width = 3
    else:
        width = 4
    return bytes([event_id]) + value.to_bytes(width, "little")


def _text(event_id: int, text: str, utf16: bool = True) -> bytes:
    """One text event: the id, a varint length, then the string and its terminator."""
    if utf16:
        body = text.encode("utf-16-le") + b"\x00\x00"
    else:
        body = text.encode("latin-1") + b"\x00"
    return bytes([event_id]) + _varint(len(body)) + body


def _channel(
    channel_type: int, name: str, factory: str | None = None, sample: str | None = None
) -> bytes:
    """The channel identity events, in the order FL writes them."""
    parts = [_scalar(21, channel_type), _text(201, factory or ""), _text(203, name)]
    if sample is not None:
        parts.append(_text(196, sample))
    return b"".join(parts)


def _header_events(
    tempo: int = 130000,
    title: str = "Deep Stab",
    tsnum: int = 4,
    tsden: int = 4,
    version: str = "26.1.6.5406",
    build: int = 5406,
) -> bytes:
    """The events a real project opens with, so a test states only what it varies."""
    return b"".join(
        [
            _text(199, version, utf16=False),
            _scalar(159, build),
            _scalar(156, tempo),
            _scalar(17, tsnum),
            _scalar(18, tsden),
            _text(194, title),
        ]
    )


def _project(events: bytes, channels: int = 0, ppq: int = 96, declared: int | None = None) -> bytes:
    """The two chunk container, exactly as the study measured it.

    The format field is always 0, which is the one value the measured corpus has.
    """
    length = len(events) if declared is None else declared
    return b"".join(
        [
            b"FLhd",
            (6).to_bytes(4, "little"),
            (0).to_bytes(2, "little"),
            channels.to_bytes(2, "little"),
            ppq.to_bytes(2, "little"),
            b"FLdt",
            length.to_bytes(4, "little"),
            events,
        ]
    )


def _write(tmp_path: Path, data: bytes, name: str = "sketch.flp") -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


def test_a_well_formed_project_reports_its_header_and_fields(tmp_path):
    """The whole point: a project the reader trusts, with every field named."""
    events = _header_events() + _channel(0, "808 Kick", sample="Basic 808 Kick.wav")
    path = _write(tmp_path, _project(events, channels=1))
    result = flp.read_flp(path)

    assert result["ok"] is True
    assert result["status"] == "ok"
    assert result["problems"] == []
    assert result["header"] == {"format": 0, "channels": 1, "ppq": 96}
    assert result["version"] == "26.1.6.5406"
    assert result["build"] == "5406"
    assert result["tempo"] == 130.0
    assert result["title"] == "Deep Stab"
    assert result["time_signature"] == {"tsnum": 4, "tsden": 4}
    assert result["walk"] == {"events": 10, "landed": True}
    assert result["size"] == len(path.read_bytes())
    assert result["modified"] == path.stat().st_mtime


def test_a_tempo_of_130000_is_reported_as_130_bpm(tmp_path):
    """Event 156 is thousandths of a BPM, observed in a real project."""
    path = _write(tmp_path, _project(_scalar(156, 130000)))
    assert flp.read_flp(path)["tempo"] == 130.0


@pytest.mark.parametrize("raw,expected", [(10000, 10.0), (522000, 522.0)])
def test_the_ends_of_the_trusted_tempo_range_are_inside_it(tmp_path, raw, expected):
    """The guard refuses what is outside 10 to 522, so both ends stay readable."""
    result = flp.read_flp(_write(tmp_path, _project(_scalar(156, raw))))
    assert result["tempo"] == expected
    assert not any("tempo" in problem for problem in result["problems"])


@pytest.mark.parametrize("raw", [9999, 522001, 0, 4000000])
def test_an_out_of_range_tempo_is_refused_rather_than_reported(tmp_path, raw):
    """A misread walk can land on a plausible looking integer, so refuse it by name.

    The file itself is not condemned: everything else it holds is still reported, and
    only the tempo comes back blank.
    """
    result = flp.read_flp(_write(tmp_path, _project(_scalar(156, raw))))

    assert result["tempo"] is None
    assert any(f"{raw / 1000.0}" in problem for problem in result["problems"])
    assert result["ok"] is True


def test_a_project_with_no_tempo_event_says_so(tmp_path):
    """Nothing to read is reported as nothing, never invented."""
    events = _text(199, "26.1.6.5406", utf16=False) + _scalar(159, 5406)
    result = flp.read_flp(_write(tmp_path, _project(events)))

    assert result["tempo"] is None
    assert any("156" in problem for problem in result["problems"])


def test_time_signature_comes_from_two_events(tmp_path):
    """Event 17 is the numerator and 18 the denominator: a meter other than 4/4 works."""
    events = _header_events(tsnum=3, tsden=4)
    result = flp.read_flp(_write(tmp_path, _project(events)))
    assert result["time_signature"] == {"tsnum": 3, "tsden": 4}


def test_a_meter_with_only_one_of_its_two_events_is_unknown(tmp_path):
    """Half a meter is not a meter, so it comes back None with a reason."""
    events = b"".join(
        [
            _text(199, "26.1.6.5406", utf16=False),
            _scalar(159, 5406),
            _scalar(156, 130000),
            _scalar(17, 4),
        ]
    )
    result = flp.read_flp(_write(tmp_path, _project(events)))

    assert result["time_signature"] is None
    assert any("17" in problem and "18" in problem for problem in result["problems"])


def test_a_utf16_title_comes_back_as_text(tmp_path):
    """The payload's strings are UTF-16LE, so a title outside ASCII survives intact."""
    result = flp.read_flp(_write(tmp_path, _project(_header_events(title="Café noir"))))
    assert result["title"] == "Café noir"


def test_an_empty_title_is_an_empty_string_not_a_missing_one(tmp_path):
    """The measured project is untitled, and untitled is not the same as unreadable."""
    result = flp.read_flp(_write(tmp_path, _project(_header_events(title=""))))
    assert result["title"] == ""


def test_the_version_event_is_single_byte_text(tmp_path):
    """Measured: event 199 holds "26.1.6.5406" as single byte text, not UTF-16.

    Reading those bytes as UTF-16 is what produces mojibake, and the version is one of
    the few fields an index prints, so it has to come back readable.
    """
    result = flp.read_flp(_write(tmp_path, _project(_header_events())))
    assert result["version"] == "26.1.6.5406"
    assert result["build"] == "5406"


def test_the_second_chunk_length_must_match_the_file_size(tmp_path):
    """The invariant that catches a padded or rewritten file.

    FLdt's length is exactly the file size minus the 22 byte preamble in all six
    projects measured on this machine, so a mismatch means the file is not what it
    claims and no field from it should be believed.
    """
    events = _header_events()
    path = _write(tmp_path, _project(events, declared=len(events) - 4))
    result = flp.read_flp(path)

    assert result["ok"] is False
    assert result["status"] == "size_mismatch"
    assert result["header"] is None
    assert result["tempo"] is None
    message = " ".join(result["problems"])
    assert str(len(events) - 4) in message
    assert str(len(events)) in message


def test_a_truncated_file_is_reported_not_raised(tmp_path):
    """Half an autosave is a real thing to find in a folder, so it must not raise."""
    data = _project(_header_events() + _channel(0, "808 Kick"), channels=1)
    path = _write(tmp_path, data[: len(data) // 2])
    result = flp.read_flp(path)

    assert result["ok"] is False
    assert result["status"] == "truncated"
    assert result["problems"]


def test_a_file_without_the_magic_is_reported_not_raised(tmp_path):
    """A note, an mp3 and a half written download all land in a project folder."""
    path = _write(tmp_path, b"this is a text file, not a project, and it is long enough")
    result = flp.read_flp(path)

    assert result["ok"] is False
    assert result["status"] == "not_a_project"
    assert result["header"] is None


def test_a_file_too_short_for_the_preamble_is_truncated(tmp_path):
    """The magic is there and then the file stops, which is a truncation, not a lie."""
    path = _write(tmp_path, b"FLhd" + (6).to_bytes(4, "little"))
    assert flp.read_flp(path)["status"] == "truncated"


def test_a_header_length_this_reader_does_not_know_is_refused(tmp_path):
    """The three uint16s sit at fixed offsets behind a six byte header, measured."""
    data = bytearray(_project(_header_events()))
    data[4:8] = (8).to_bytes(4, "little")
    result = flp.read_flp(_write(tmp_path, bytes(data)))

    assert result["status"] == "unexpected_header"
    assert result["header"] is None


def test_a_walk_that_does_not_land_exactly_on_eof_is_not_trusted(tmp_path):
    """The rule the whole reader is built around.

    The walk below reads real fields and then runs off the end, which is what a desync
    looks like from here: a desynced walk can produce plausible looking numbers, so
    every field that came out of it is refused. The header comes from the container
    check rather than the walk, so it survives.
    """
    events = _header_events() + bytes([194]) + _varint(4096) + b"\x00\x00"
    result = flp.read_flp(_write(tmp_path, _project(events)))

    assert result["ok"] is False
    assert result["status"] == "walk_failed"
    assert result["walk"]["landed"] is False
    assert result["header"] == {"format": 0, "channels": 0, "ppq": 96}
    assert result["version"] is None
    assert result["build"] is None
    assert result["tempo"] is None
    assert result["title"] is None
    assert result["time_signature"] is None
    assert result["plugins"] == []
    assert any("stopped at byte" in problem for problem in result["problems"])


def test_the_size_quirk_in_the_128_to_191_band_is_handled(tmp_path):
    """The 0xAC event carries three value bytes, not the four the published rule says.

    Reading it as four shifts every event after it by one byte, and the shift still
    lands on the end of the payload, so this is the only place the difference shows:
    the version, the tempo and the meter all sit after the quirk.
    """
    events = b"".join(
        [
            _scalar(0xAC, 0x101),
            _text(199, "26.1.6.5406", utf16=False),
            _scalar(156, 130000),
            _scalar(17, 4),
            _scalar(18, 4),
            _text(194, "After the quirk"),
        ]
    )
    data = _project(events)
    assert b"\xac\x01\x01\x00\xc7\x0c" in data, "the fixture must hold the real sequence"

    result = flp.read_flp(_write(tmp_path, data))
    assert result["walk"]["landed"] is True
    assert result["version"] == "26.1.6.5406"
    assert result["tempo"] == 130.0
    assert result["time_signature"] == {"tsnum": 4, "tsden": 4}
    assert result["title"] == "After the quirk"


def test_plugin_names_are_extracted_from_the_channel_events(tmp_path):
    """Events 21, 201, 203 and 196 name the instrument on each channel."""
    events = (
        _header_events()
        + _channel(0, "808 Kick", sample="Basic 808 Kick.wav")
        + _channel(2, "808 Astronomic", factory="FLEX")
    )
    result = flp.read_flp(_write(tmp_path, _project(events, channels=2)))

    assert result["plugins"] == [
        {"name": "808 Kick", "factory": None, "type": 0, "sample": "Basic 808 Kick.wav"},
        {"name": "808 Astronomic", "factory": "FLEX", "type": 2, "sample": None},
    ]


def test_a_mixer_plugin_event_after_the_last_channel_does_not_relabel_it(tmp_path):
    """Measured in a real project: a mixer effect's factory event arrives last.

    The event stream carries "Emphasizer", an effect on a mixer track, after the last
    channel's events, so a reader where the last value wins would report the FLEX
    channel as an effect.
    """
    events = (
        _header_events()
        + _channel(2, "808 Astronomic", factory="FLEX")
        + _text(201, "Emphasizer")
        + _text(203, "Insert 1")
    )
    result = flp.read_flp(_write(tmp_path, _project(events, channels=1)))

    assert result["plugins"] == [
        {"name": "808 Astronomic", "factory": "FLEX", "type": 2, "sample": None}
    ]


def test_a_channel_count_the_walk_disagrees_with_is_reported(tmp_path):
    """The header count is FL's own statement, so a disagreement is worth naming."""
    events = _header_events() + _channel(0, "808 Kick")
    result = flp.read_flp(_write(tmp_path, _project(events, channels=3)))

    assert result["ok"] is True, "the walk landed, so only the channel list is in doubt"
    assert len(result["plugins"]) == 1
    assert "the header declares 3 channels but the walk found 1 channel starts" in (
        result["problems"]
    )


def test_a_missing_file_is_reported_not_raised(tmp_path):
    """A path from a stale index is ordinary, so it comes back as a status."""
    result = flp.read_flp(tmp_path / "not-there.flp")

    assert result["ok"] is False
    assert result["status"] == "unreadable"
    assert result["problems"]
    assert result["size"] is None
    assert result["modified"] is None


def test_a_directory_is_reported_not_raised(tmp_path):
    """A folder named something.flp is a real thing to find, and it must not raise."""
    result = flp.read_flp(tmp_path)

    assert result["ok"] is False
    assert result["status"] == "unreadable"


@pytest.mark.parametrize("kind", ["good", "rejected", "desynced"])
def test_every_read_carries_the_same_keys(tmp_path, kind):
    """A caller should never have to guard a lookup, whatever the file did."""
    if kind == "good":
        data = _project(_header_events())
    elif kind == "rejected":
        data = b"not a project at all, but long enough to look like one"
    else:
        data = _project(_header_events() + bytes([194]) + _varint(4096) + b"\x00\x00")

    result = flp.read_flp(_write(tmp_path, data))
    assert set(result) == RESULT_KEYS
    assert set(result["walk"]) == {"events", "landed"}
