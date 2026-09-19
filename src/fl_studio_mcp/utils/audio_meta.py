"""What an audio file's own header says, without trusting its extension.

FL Studio's factory .wav files are Ogg Vorbis inside a RIFF container: the name says
PCM, the fmt chunk says format tag 0x674F, and the data chunk starts with "OggS".
Python's wave module refuses them outright, and a duration worked out as if they were
PCM would be wrong by whatever ratio the encoder chose. That is why every number here
is either measured from the file's own header or absent with a reason.

Every read is bounded. The head read is a kilobyte, a chunk walk reads eight byte chunk
headers and seeks over their payloads, and an Ogg length comes from the last page in
the tail of the file. Nothing decodes audio, and nothing raises: a truncated, empty or
unreadable file comes back described as far as it could be, with the exception's own
message, because a producer's sample folder is written by a dozen programs and one bad
file must not stop a search.
"""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Any

# How much of a file a header read takes. Half a kilobyte covers every header this
# reader measures; anything further in is reached a chunk header at a time, so this is
# never a whole file read: a sample is minutes of audio and the answer is in the first
# bytes of it.
HEADER_BYTES = 512

# An Ogg stream carries its total length in the last page's granule position, so the
# tail is read rather than the file. A page can be up to about 64 KB; the granule is in
# the page header, so the tail only has to reach back to the start of the last page.
TAIL_BYTES = 8192

# How many chunk headers a walk will step over before giving up on a container. A file
# with more metadata chunks than this is not one a producer made.
MAX_CHUNKS = 64

# The WAVE format tags whose payload this reader can measure. Everything else in a
# RIFF container is compressed or codec specific, and calling it PCM would be a lie.
_MEASURED_WAVE_TAGS = (0x0001, 0x0003)

# The tags worth naming. The Vorbis tags are the five modes Microsoft registered, and
# 0x674F is the one FL's own factory content uses.
_WAVE_CODECS = {
    0x0001: "pcm",
    0x0003: "float",
    0x0006: "alaw",
    0x0007: "mulaw",
    0x0011: "adpcm",
    0x0050: "mp2",
    0x0055: "mp3",
    0x674F: "vorbis",
    0x6750: "vorbis",
    0x6751: "vorbis",
    0x676F: "vorbis",
    0x6770: "vorbis",
    0x6771: "vorbis",
}

# AIFF-C compression types that still describe uncompressed samples, so the frame count
# in the COMM chunk means what it says. Anything else is compressed and is named rather
# than measured.
_UNCOMPRESSED_AIFC = frozenset(
    {b"NONE", b"twos", b"sowt", b"raw ", b"in24", b"in32", b"fl32", b"FL32", b"fl64", b"FL64"}
)


def read_audio_info(path: str | Path) -> dict[str, Any]:
    """Describe an audio file from its header alone.

    The extension is never consulted for the format: the bytes decide, so a FLAC named
    .wav is described as FLAC.

    Args:
        path: The file to read.

    Returns:
        format, container, codec, sample_rate, channels, bits, duration and readable,
        plus a reason whenever a number could not be measured. readable is True when
        the duration was measured; when it is False the numbers that could not be
        measured are None and reason says why. A missing, empty, truncated or
        unreadable file returns readable False with the exception's message rather
        than raising.
    """
    target = Path(path)
    try:
        head = _read_head(target)
    except Exception as error:  # a caller's path may be anything at all
        return _info(reason=f"{type(error).__name__}: {error}")

    if not head:
        return _info(reason="the file is empty")
    if len(head) < 12:
        return _info(reason=f"the file is {len(head)} bytes, too short for any audio header")

    try:
        return _dispatch(target, head)
    except Exception as error:  # noqa: BLE001 - a broken header must never be fatal
        return _info(reason=f"{type(error).__name__}: {error}")


def _dispatch(path: Path, head: bytes) -> dict[str, Any]:
    """Send the file to the reader its first bytes name."""
    if head[:4] == b"RIFF":
        if head[8:12] != b"WAVE":
            return _info(
                format="riff",
                container="RIFF",
                reason="a RIFF file that is not WAVE, so this reader has nothing to measure",
            )
        return _read_riff(path, head)
    if head[:4] == b"FORM" and head[8:12] in (b"AIFF", b"AIFC"):
        return _read_aiff(path, head)
    if head[:4] == b"fLaC":
        return _read_flac(path, head)
    if head[:4] == b"OggS":
        return _read_ogg(path, head)
    if head[:4] == b"wvpk":
        return _info(
            format="wv",
            container="WavPack",
            codec="wavpack",
            reason=(
                "the file is WavPack, which this reader does not measure: the duration is "
                "in the blocks and needs a decoder, so a number here would be invented"
            ),
        )
    if head[:4] == b"caff":
        return _info(
            format="caf",
            container="CAF",
            reason=(
                "the file is a Core Audio Format container, whose description chunk comes "
                "after an arbitrary number of other chunks, so this bounded reader does not "
                "measure it"
            ),
        )
    if head[:3] == b"ID3" or (head[0] == 0xFF and (head[1] & 0xE0) == 0xE0):
        return _info(
            format="mp3",
            container="MPEG",
            codec="mp3",
            reason=(
                "the file is MPEG audio, whose frame count is only known after decoding or "
                "a full scan, so no duration is given"
            ),
        )
    return _info(reason="the first bytes are not a container this reader recognises")


def _read_riff(path: Path, head: bytes) -> dict[str, Any]:
    """A WAVE file: the fmt chunk decides the codec, the data chunk the length."""
    fmt = None
    data_offset = None
    data_size = None
    data_prefix = b""
    for chunk_id, offset, size in _chunks(path, 12, head):
        if chunk_id == b"fmt " and fmt is None:
            fmt = _payload(path, head, offset, min(size, 64))
        elif chunk_id == b"data":
            data_offset, data_size = offset, size
            data_prefix = _payload(path, head, offset, 64)
            break

    if fmt is None or len(fmt) < 16:
        return _info(format="wav", container="RIFF", reason="the file has no usable fmt chunk")

    tag, channels, rate, byte_rate, _block_align, bits = struct.unpack_from("<HHIIHH", fmt, 0)
    if tag == 0xFFFE and len(fmt) >= 40:
        # Extensible: the first two bytes of the subformat GUID are the real tag, and the
        # valid bits can be narrower than the container a plugin wrote into.
        valid_bits = struct.unpack_from("<H", fmt, 18)[0]
        tag = struct.unpack_from("<H", fmt, 24)[0]
        if valid_bits:
            bits = valid_bits
    if byte_rate <= 0 and channels > 0 and bits > 0:
        byte_rate = rate * channels * bits // 8

    if data_prefix[:4] == b"OggS":
        # The payload is the authority, not the fmt chunk: a file can be tagged as PCM
        # and still hold a compressed stream.
        ogg_codec, ogg_rate, ogg_channels = _ogg_identification(data_prefix)
        tag_codec = None if tag in _MEASURED_WAVE_TAGS else _WAVE_CODECS.get(tag)
        codec = tag_codec or ogg_codec or "ogg"
        return _info(
            format="wav",
            container="RIFF",
            codec=codec,
            sample_rate=ogg_rate,
            channels=ogg_channels,
            reason=(
                f"the payload is compressed ({codec} in a RIFF container), so its duration "
                "cannot be measured without decoding it"
            ),
        )

    if tag not in _MEASURED_WAVE_TAGS:
        codec = _WAVE_CODECS.get(tag) or f"wav tag 0x{tag:04X}"
        return _info(
            format="wav",
            container="RIFF",
            codec=codec,
            sample_rate=rate or None,
            channels=channels or None,
            bits=bits or None,
            reason=(
                f"the fmt chunk names {codec}, which is not PCM, so its duration cannot be "
                "worked out from the data chunk's size"
            ),
        )

    codec = "pcm" if tag == 0x0001 else "float"
    common = {
        "format": "wav",
        "container": "RIFF",
        "codec": codec,
        "sample_rate": rate or None,
        "channels": channels or None,
        "bits": bits or None,
    }
    if data_offset is None:
        return _info(
            **common,
            reason="the file has no data chunk, so there is no length to measure",
        )
    if data_size == 0xFFFFFFFF:
        return _info(
            **common,
            reason=(
                "the data chunk declares no size, the way a streamed or interrupted "
                "writer leaves it"
            ),
        )
    if byte_rate <= 0:
        return _info(
            **common,
            reason="the fmt chunk gives no byte rate, so the length cannot be worked out",
        )
    try:
        file_size = path.stat().st_size
    except OSError as error:
        return _info(**common, reason=str(error))
    if data_offset + data_size > file_size:
        return _info(
            **common,
            reason=(
                "the file ends before the data chunk does, so a duration from it would "
                "be a guess"
            ),
        )
    return _info(**common, duration=data_size / byte_rate)


def _read_aiff(path: Path, head: bytes) -> dict[str, Any]:
    """An AIFF or AIFF-C file: the COMM chunk carries frames, rate and codec."""
    form = head[8:12].decode("ascii", "replace")
    name = "aiff" if form == "AIFF" else "aifc"

    comm = None
    for chunk_id, offset, size in _chunks(path, 12, head, big_endian=True):
        if chunk_id == b"COMM":
            comm = _payload(path, head, offset, min(size, 64))
            break
    if comm is None or len(comm) < 18:
        return _info(format=name, container="FORM", reason="the file has no usable COMM chunk")

    channels, frames, bits = struct.unpack_from(">hIh", comm, 0)
    rate = int(round(_extended_float(comm[8:18])))
    if form == "AIFC" and len(comm) >= 22:
        compression = comm[18:22]
        if compression not in _UNCOMPRESSED_AIFC:
            codec = compression.decode("ascii", "replace").strip() or "unknown"
            return _info(
                format=name,
                container="FORM",
                codec=codec,
                sample_rate=rate or None,
                channels=channels or None,
                bits=bits or None,
                reason=(
                    f"the payload is compressed ({codec}), so the frame count does not give "
                    "a duration without decoding it"
                ),
            )

    common = {
        "format": name,
        "container": "FORM",
        "codec": "pcm",
        "sample_rate": rate or None,
        "channels": channels or None,
        "bits": bits or None,
    }
    if frames == 0xFFFFFFFF:
        return _info(**common, reason="the COMM chunk does not declare a frame count")
    if not rate:
        return _info(**common, reason="the COMM chunk gives no sample rate")
    return _info(**common, duration=frames / rate)


def _read_flac(path: Path, head: bytes) -> dict[str, Any]:
    """A FLAC file: STREAMINFO gives the total samples and the rate directly."""
    offset = 4
    for _ in range(8):
        if offset + 4 > len(head):
            break
        last = bool(head[offset] & 0x80)
        kind = head[offset] & 0x7F
        size = int.from_bytes(head[offset + 1 : offset + 4], "big")
        if kind == 0:
            if size < 34:
                break
            payload = _payload(path, head, offset + 4, 34)
            if len(payload) < 34:
                return _info(
                    format="flac",
                    container="native",
                    codec="flac",
                    reason="the STREAMINFO block is truncated",
                )
            # The 64 bits after the first ten hold rate, channels, depth and length.
            packed = int.from_bytes(payload[10:18], "big")
            rate = (packed >> 44) & 0xFFFFF
            channels = ((packed >> 41) & 0x07) + 1
            bits = ((packed >> 36) & 0x1F) + 1
            total = packed & ((1 << 36) - 1)
            common = {
                "format": "flac",
                "container": "native",
                "codec": "flac",
                "sample_rate": rate or None,
                "channels": channels or None,
                "bits": bits or None,
            }
            if not rate or not total:
                return _info(
                    **common,
                    reason="the stream declares no sample rate or no total sample count",
                )
            return _info(**common, duration=total / rate)
        if last:
            break
        offset += 4 + size
    return _info(
        format="flac",
        container="native",
        codec="flac",
        reason="the file has no usable STREAMINFO block",
    )


def _read_ogg(path: Path, head: bytes) -> dict[str, Any]:
    """An Ogg file: the identification header for the codec, the last page for length."""
    codec, rate, channels = _ogg_identification(head)
    common = {
        "format": "ogg",
        "container": "Ogg",
        "codec": codec or "ogg",
        "sample_rate": rate,
        "channels": channels,
    }
    granule = _last_granule(path)
    if granule is None:
        return _info(
            **common,
            reason="no complete page was found in the tail of the file, so its length is unknown",
        )
    if not rate:
        return _info(
            **common,
            reason=(
                f"the {common['codec']} identification header gives no sample rate, so the "
                "granule position cannot be turned into seconds"
            ),
        )
    return _info(**common, duration=granule / rate)


def _ogg_identification(prefix: bytes) -> tuple[str | None, int | None, int | None]:
    """The codec, sample rate and channel count from an Ogg stream's first packet.

    The identification header sits in the first page, so a prefix of the file is enough
    for it even when the length comes from the other end of the file.
    """
    at = prefix.find(b"\x01vorbis")
    if at != -1:
        if len(prefix) >= at + 16:
            channels = prefix[at + 11]
            rate = struct.unpack_from("<I", prefix, at + 12)[0]
            return "vorbis", rate or None, channels or None
        return "vorbis", None, None
    at = prefix.find(b"OpusHead")
    if at != -1:
        channels = prefix[at + 9] if len(prefix) >= at + 10 else None
        # An Opus granule is always counted at 48 kHz, whatever the input rate was.
        return "opus", 48000, channels or None
    if prefix[:4] == b"OggS":
        return "ogg", None, None
    return None, None, None


def _last_granule(path: Path) -> int | None:
    """The granule position of the last page, or None when no page can be found.

    The check is structural: the capture pattern, a version byte of zero, a page header
    that fits, and a granule that is not the "no packet completed" sentinel. A CRC check
    would be stronger and would mean decoding the page, which is the expensive thing
    this module exists to avoid.
    """
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            handle.seek(max(0, size - TAIL_BYTES))
            tail = handle.read(TAIL_BYTES)
    except OSError:
        return None

    at = tail.rfind(b"OggS")
    while at != -1:
        page = tail[at:]
        if len(page) >= 27 and page[4] == 0:
            segments = page[26]
            if len(page) >= 27 + segments:
                granule = struct.unpack_from("<q", page, 6)[0]
                if granule >= 0:
                    return granule
        at = tail.rfind(b"OggS", 0, at)
    return None


def _extended_float(value: bytes) -> float:
    """An 80 bit IEEE extended float, which is how an AIFF stores its sample rate.

    The standard library has no reader for this width, and the value is one number in
    an otherwise ordinary header, so it is unpacked here rather than pulled in.
    """
    if len(value) < 10:
        raise ValueError("an 80 bit extended float needs 10 bytes")
    exponent = int.from_bytes(value[:2], "big")
    negative = bool(exponent & 0x8000)
    exponent &= 0x7FFF
    if exponent == 0x7FFF:
        raise ValueError("the sample rate is not a finite number")
    mantissa = int.from_bytes(value[2:], "big")
    if exponent == 0 and mantissa == 0:
        return 0.0
    result = mantissa * (2.0 ** (exponent - 16383 - 63))
    return -result if negative else result


def _chunks(
    path: Path,
    start: int,
    head: bytes,
    *,
    big_endian: bool = False,
    limit: int = MAX_CHUNKS,
):
    """Step over a chunked container, yielding (id, payload offset, payload size).

    Chunk headers inside the head buffer come from it. Anything past that is read eight
    bytes at a time, so a file with a large LIST or SSND chunk costs a seek rather than
    a read of the chunk.
    """
    order = ">" if big_endian else "<"
    offset = start
    with path.open("rb") as handle:
        for _ in range(limit):
            if offset + 8 <= len(head):
                header = head[offset : offset + 8]
            else:
                handle.seek(offset)
                header = handle.read(8)
            if len(header) < 8:
                return
            size = struct.unpack_from(f"{order}I", header, 4)[0]
            yield header[:4], offset + 8, size
            if size == 0xFFFFFFFF:
                return
            offset += 8 + size + (size & 1)


def _payload(path: Path, head: bytes, offset: int, size: int) -> bytes:
    """A payload, bounded by the caller, from the head buffer or a positioned read."""
    if size <= 0:
        return b""
    if offset + size <= len(head):
        return head[offset : offset + size]
    with path.open("rb") as handle:
        handle.seek(offset)
        return handle.read(size)


def _read_head(path: Path) -> bytes:
    """The first bytes of the file. The only read that is not positional."""
    with path.open("rb") as handle:
        return handle.read(HEADER_BYTES)


def _info(
    *,
    format: str | None = None,
    container: str | None = None,
    codec: str | None = None,
    sample_rate: int | None = None,
    channels: int | None = None,
    bits: int | None = None,
    duration: float | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    """One result, with every field present so a caller never has to guess a key.

    readable is True only when the duration was measured. A file described without one
    is a file to go and listen to, which is the point: a caller who sees None and a
    reason will audition it, and a caller handed a wrong number will not.
    """
    info: dict[str, Any] = {
        "format": format,
        "container": container,
        "codec": codec,
        "sample_rate": sample_rate,
        "channels": channels,
        "bits": bits,
        "duration": duration,
        "readable": duration is not None,
    }
    if reason:
        info["reason"] = reason
    return info
