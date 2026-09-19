"""What a file's own header says, tested against headers assembled here.

Every fixture below is built byte by byte rather than downloaded or borrowed, because
the module's whole claim is that a header is enough: two seconds of PCM would be a
third of a megabyte of samples no test reads, and a real FL factory file belongs to the
producer who owns it.
"""

from __future__ import annotations

import struct
from pathlib import Path

from fl_studio_mcp.utils import audio_meta


def riff_chunk(chunk_id: bytes, payload: bytes) -> bytes:
    """One RIFF chunk, padded to an even length the way the format requires."""
    padding = b"\x00" if len(payload) % 2 else b""
    return chunk_id + struct.pack("<I", len(payload)) + payload + padding


def write_wav(
    path: Path,
    *,
    fmt_tag: int = 0x0001,
    channels: int = 2,
    rate: int = 44100,
    bits: int = 16,
    seconds: float = 2.0,
    data: bytes | None = None,
    extra_fmt: bytes = b"",
) -> Path:
    """A RIFF/WAVE file whose header says exactly what the caller asked for."""
    block_align = max(1, channels * bits // 8)
    byte_rate = rate * block_align
    fmt = struct.pack("<HHIIHH", fmt_tag, channels, rate, byte_rate, block_align, bits) + extra_fmt
    if data is None:
        data = b"\x00" * (int(seconds * rate) * block_align)
    body = b"WAVE" + riff_chunk(b"fmt ", fmt) + riff_chunk(b"data", data)
    path.write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)
    return path


def write_flac(
    path: Path,
    *,
    rate: int = 44100,
    channels: int = 2,
    bits: int = 16,
    samples: int = 88200,
) -> Path:
    """A FLAC file whose STREAMINFO block declares a length and a rate."""
    packed = (rate << 44) | ((channels - 1) << 41) | ((bits - 1) << 36) | samples
    streaminfo = b"\x00" * 10 + packed.to_bytes(8, "big") + b"\x00" * 16
    path.write_bytes(b"fLaC" + b"\x80" + len(streaminfo).to_bytes(3, "big") + streaminfo)
    return path


def extended_float(value: float) -> bytes:
    """An 80 bit IEEE extended float, which is how AIFF stores a sample rate."""
    exponent = 16383 + 63
    mantissa = int(value)
    while mantissa < (1 << 63):
        mantissa <<= 1
        exponent -= 1
    return exponent.to_bytes(2, "big") + mantissa.to_bytes(8, "big")


def form_chunk(chunk_id: bytes, payload: bytes) -> bytes:
    """One AIFF chunk, whose sizes are big endian and whose payloads are even."""
    padding = b"\x00" if len(payload) % 2 else b""
    return chunk_id + len(payload).to_bytes(4, "big") + payload + padding


def write_aiff(
    path: Path,
    *,
    form: bytes = b"AIFF",
    channels: int = 2,
    frames: int = 88200,
    bits: int = 16,
    rate: int = 44100,
    compression: bytes = b"NONE",
) -> Path:
    """An AIFF or AIFF-C file, with the frame count in its COMM chunk."""
    comm = struct.pack(">hIh", channels, frames, bits) + extended_float(rate)
    if form == b"AIFC":
        # The compression type, then a pascal string of length zero plus its pad byte.
        comm += compression + b"\x00\x00"
    body = form + form_chunk(b"COMM", comm) + form_chunk(b"SSND", b"\x00" * 8)
    path.write_bytes(b"FORM" + len(body).to_bytes(4, "big") + body)
    return path


def ogg_page(payload: bytes, granule: int, sequence: int, *, header_type: int = 0) -> bytes:
    """One Ogg page, with a segment table that covers its payload."""
    segments = bytes([255] * (len(payload) // 255) + [len(payload) % 255])
    header = (
        b"OggS"
        + bytes([0, header_type])
        + struct.pack("<q", granule)
        + struct.pack("<I", 1)
        + struct.pack("<I", sequence)
        + b"\x00\x00\x00\x00"
        + bytes([len(segments)])
    )
    return header + segments + payload


def write_ogg(path: Path, *, channels: int = 2, rate: int = 44100, samples: int = 88200) -> Path:
    """A two page Ogg Vorbis file: identification first, granule last."""
    ident = b"\x01vorbis" + struct.pack("<I", 0) + bytes([channels]) + struct.pack("<I", rate)
    first = ogg_page(ident, 0, 0, header_type=0x02)
    # A large final page, so the tail read cannot see the first one as well.
    last = ogg_page(b"\x00" * 3000, samples, 1, header_type=0x04)
    path.write_bytes(first + last)
    return path


def test_a_vorbis_wav_is_not_reported_as_pcm(tmp_path):
    """FL's factory wavs are Ogg Vorbis in a RIFF container, tag 0x674F.

    Python's wave module refuses them, so the extension is not evidence of anything. A
    duration computed as if this were PCM would be a lie.
    """
    path = write_wav(tmp_path / "kick.wav", fmt_tag=0x674F, data=b"OggS" + b"\x00" * 100)
    info = audio_meta.read_audio_info(path)
    assert info["format"] == "wav"
    assert info["codec"] == "vorbis"
    assert info["duration"] is None
    assert info["readable"] is False
    assert "compressed" in info["reason"]


def test_a_compressed_payload_is_recognised_even_when_fmt_says_pcm(tmp_path):
    """The payload wins over the fmt chunk, because the fmt chunk is what lies."""
    path = write_wav(tmp_path / "sneaky.wav", fmt_tag=0x0001, data=b"OggS" + b"\x00" * 100)
    info = audio_meta.read_audio_info(path)
    assert info["codec"] == "ogg"
    assert info["duration"] is None
    assert "compressed" in info["reason"]


def test_a_vorbis_wav_reports_the_rate_from_its_ogg_identification_header(tmp_path):
    """The identification header is in the data chunk, and it is measurable."""
    ident = b"\x01vorbis" + struct.pack("<I", 0) + bytes([1]) + struct.pack("<I", 22050)
    page = ogg_page(ident, 0, 0, header_type=0x02)
    path = write_wav(tmp_path / "pad.wav", fmt_tag=0x674F, data=page)
    info = audio_meta.read_audio_info(path)
    assert info["codec"] == "vorbis"
    assert info["sample_rate"] == 22050
    assert info["channels"] == 1
    assert info["duration"] is None


def test_a_pcm_wav_reports_its_duration_exactly(tmp_path):
    """Two seconds of 44.1k stereo 16 bit is two seconds."""
    path = write_wav(tmp_path / "two.wav")
    info = audio_meta.read_audio_info(path)
    assert info["format"] == "wav"
    assert info["container"] == "RIFF"
    assert info["codec"] == "pcm"
    assert info["sample_rate"] == 44100
    assert info["channels"] == 2
    assert info["bits"] == 16
    assert info["duration"] == 2.0
    assert info["readable"] is True
    assert "reason" not in info


def test_an_ieee_float_wav_reports_its_duration(tmp_path):
    path = write_wav(tmp_path / "float.wav", fmt_tag=0x0003, bits=32, seconds=1.5)
    info = audio_meta.read_audio_info(path)
    assert info["codec"] == "float"
    assert info["duration"] == 1.5


def test_an_extensible_wav_is_measured_through_its_subformat(tmp_path):
    """Format tag 0xFFFE hides the real codec in a GUID, and the valid bits can be narrower."""
    guid = struct.pack("<H", 0x0001) + b"\x00" * 14
    extra = struct.pack("<HHI", 22, 24, 3) + guid
    path = write_wav(tmp_path / "ext.wav", fmt_tag=0xFFFE, bits=32, extra_fmt=extra)
    info = audio_meta.read_audio_info(path)
    assert info["codec"] == "pcm"
    assert info["bits"] == 24
    assert info["duration"] == 2.0


def test_a_wav_whose_other_format_is_not_pcm_is_named_not_measured(tmp_path):
    path = write_wav(tmp_path / "voice.wav", fmt_tag=0x0011, data=b"\x00" * 64)
    info = audio_meta.read_audio_info(path)
    assert info["codec"] == "adpcm"
    assert info["duration"] is None
    assert "adpcm" in info["reason"]


def test_a_wav_shorter_than_its_data_chunk_is_not_given_a_duration(tmp_path):
    """A declared size past the end of the file is a truncated file, not a long one."""
    fmt = struct.pack("<HHIIHH", 1, 2, 44100, 176400, 4, 16)
    body = (
        b"WAVE"
        + riff_chunk(b"fmt ", fmt)
        + b"data"
        + struct.pack("<I", 176400)
        + b"\x00" * 16
    )
    path = tmp_path / "cut.wav"
    path.write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)
    info = audio_meta.read_audio_info(path)
    assert info["codec"] == "pcm"
    assert info["duration"] is None
    assert "ends before" in info["reason"]


def test_a_streamed_wav_with_no_data_size_is_not_given_a_duration(tmp_path):
    fmt = struct.pack("<HHIIHH", 1, 2, 44100, 176400, 4, 16)
    body = (
        b"WAVE"
        + riff_chunk(b"fmt ", fmt)
        + b"data"
        + struct.pack("<I", 0xFFFFFFFF)
        + b"\x00" * 8
    )
    path = tmp_path / "stream.wav"
    path.write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)
    info = audio_meta.read_audio_info(path)
    assert info["duration"] is None
    assert "declares no size" in info["reason"]


def test_a_flac_header_reports_its_duration(tmp_path):
    """STREAMINFO gives the total sample count and the rate directly."""
    path = write_flac(tmp_path / "pad.flac")
    info = audio_meta.read_audio_info(path)
    assert info["format"] == "flac"
    assert info["codec"] == "flac"
    assert info["sample_rate"] == 44100
    assert info["channels"] == 2
    assert info["bits"] == 16
    assert info["duration"] == 2.0


def test_a_flac_without_a_declared_length_has_no_duration(tmp_path):
    """A stream can leave its total sample count at zero, which is not zero seconds."""
    path = write_flac(tmp_path / "live.flac", samples=0)
    info = audio_meta.read_audio_info(path)
    assert info["duration"] is None
    assert info["readable"] is False
    assert "no total sample count" in info["reason"]


def test_an_aiff_header_reports_its_duration(tmp_path):
    """The COMM chunk carries the frame count and the rate, so the arithmetic is direct."""
    path = write_aiff(tmp_path / "pad.aif")
    info = audio_meta.read_audio_info(path)
    assert info["format"] == "aiff"
    assert info["container"] == "FORM"
    assert info["sample_rate"] == 44100
    assert info["channels"] == 2
    assert info["bits"] == 16
    assert info["duration"] == 2.0


def test_a_compressed_aifc_is_named_not_measured(tmp_path):
    path = write_aiff(tmp_path / "voice.aifc", form=b"AIFC", compression=b"ima4")
    info = audio_meta.read_audio_info(path)
    assert info["format"] == "aifc"
    assert info["codec"] == "ima4"
    assert info["duration"] is None
    assert "compressed" in info["reason"]


def test_an_uncompressed_aifc_is_measured(tmp_path):
    path = write_aiff(tmp_path / "plain.aifc", form=b"AIFC", compression=b"sowt")
    info = audio_meta.read_audio_info(path)
    assert info["codec"] == "pcm"
    assert info["duration"] == 2.0


def test_an_ogg_file_reports_its_length_from_the_last_page(tmp_path):
    """The granule position is in the tail, so the whole file is never read."""
    path = write_ogg(tmp_path / "pad.ogg")
    info = audio_meta.read_audio_info(path)
    assert info["format"] == "ogg"
    assert info["codec"] == "vorbis"
    assert info["sample_rate"] == 44100
    assert info["channels"] == 2
    assert info["duration"] == 2.0


def test_an_extension_that_lies_is_still_read_by_header(tmp_path):
    """A FLAC named .wav is described as FLAC, because the bytes say so."""
    path = write_flac(tmp_path / "mislabelled.wav")
    info = audio_meta.read_audio_info(path)
    assert info["format"] == "flac"
    assert info["duration"] == 2.0


def test_a_wavpack_file_is_named_but_not_measured(tmp_path):
    path = tmp_path / "pad.wv"
    path.write_bytes(b"wvpk" + b"\x00" * 64)
    info = audio_meta.read_audio_info(path)
    assert info["format"] == "wv"
    assert info["codec"] == "wavpack"
    assert info["duration"] is None
    assert info["readable"] is False
    assert "WavPack" in info["reason"]


def test_a_caf_file_is_named_but_not_measured(tmp_path):
    path = tmp_path / "pad.caf"
    path.write_bytes(b"caff" + b"\x00" * 64)
    info = audio_meta.read_audio_info(path)
    assert info["format"] == "caf"
    assert info["duration"] is None
    assert "Core Audio" in info["reason"]


def test_an_mp3_file_is_named_but_not_measured(tmp_path):
    path = tmp_path / "pad.mp3"
    path.write_bytes(b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\x00" * 64)
    info = audio_meta.read_audio_info(path)
    assert info["format"] == "mp3"
    assert info["codec"] == "mp3"
    assert info["duration"] is None


def test_a_truncated_file_is_unreadable_rather_than_fatal(tmp_path):
    path = tmp_path / "cut.wav"
    path.write_bytes(b"RIFF\x2c\x00\x00\x00WAVE")
    info = audio_meta.read_audio_info(path)
    assert info["readable"] is False
    assert info["duration"] is None
    assert "fmt chunk" in info["reason"]


def test_an_empty_file_is_unreadable(tmp_path):
    path = tmp_path / "empty.wav"
    path.write_bytes(b"")
    info = audio_meta.read_audio_info(path)
    assert info["readable"] is False
    assert "empty" in info["reason"]


def test_a_missing_file_reports_the_exception_rather_than_raising(tmp_path):
    info = audio_meta.read_audio_info(tmp_path / "not-there.wav")
    assert info["readable"] is False
    assert info["format"] is None
    assert "No such file" in info["reason"] or "not-there.wav" in info["reason"]


def test_something_that_is_not_audio_is_reported_not_guessed(tmp_path):
    path = tmp_path / "notes.wav"
    path.write_bytes(b"this is a text file pretending to be a sample")
    info = audio_meta.read_audio_info(path)
    assert info["format"] is None
    assert info["readable"] is False
    assert "not a container" in info["reason"]


def test_a_riff_file_that_is_not_wave_is_named_and_refused(tmp_path):
    path = tmp_path / "clip.avi"
    path.write_bytes(b"RIFF" + struct.pack("<I", 4) + b"AVI " + b"\x00" * 16)
    info = audio_meta.read_audio_info(path)
    assert info["container"] == "RIFF"
    assert info["duration"] is None
    assert "not WAVE" in info["reason"]


def test_every_result_carries_the_same_keys(tmp_path):
    """A caller reads the fields of an unreadable file as freely as a readable one."""
    expected = {
        "format",
        "container",
        "codec",
        "sample_rate",
        "channels",
        "bits",
        "duration",
        "readable",
    }
    for path in (write_wav(tmp_path / "a.wav"), tmp_path / "missing.flac"):
        assert expected <= set(audio_meta.read_audio_info(path))
