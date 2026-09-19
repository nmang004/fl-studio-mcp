"""MIDI files, so notes can leave FL and come back.

`mido` is already a dependency for the transport, and it reads and writes standard
MIDI files, so this is a thin bridge rather than a parser.

Times are converted at the boundary: notes in this project are in beats, and MIDI
files are in ticks at whatever PPQ the file declares. A file written at 480 PPQ
imported into a project at 96 would be four times too long if the file's own PPQ
were ignored, which is the mistake this module exists to avoid.

Articulation does not survive the trip. FL's slide and portamento are FL concepts
with no standard MIDI equivalent, and inventing an encoding for them would produce
files that other programs misread. The export drops them and says so, rather than
writing something that looks portable and is not.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import mido

Note = dict[str, Any]

DEFAULT_PPQ = 96
DEFAULT_TEMPO = 120.0
TICKS_PER_BEAT = 1


def to_midi_file(
    notes: list[Note],
    path: str | Path,
    ppq: int = DEFAULT_PPQ,
    tempo: float = DEFAULT_TEMPO,
    time_signature: tuple[int, int] = (4, 4),
    track_name: str = "FL Studio MCP",
) -> Path:
    """Write notes to a standard MIDI file.

    Args:
        notes: Notes with `midi`, `time` and `duration` in beats, and `velocity`
            from 0.0 to 1.0.
        path: Where to write. The parent directory must exist.
        ppq: Ticks per quarter note for the file.
        tempo: Beats per minute, written as a tempo event.
        time_signature: Numerator and denominator, written as a meta event.
        track_name: The track's name in the file.

    Returns:
        The path written.

    Note:
        FL's slide and portamento flags are not written. There is no standard MIDI
        representation of them, and a private encoding would be read as something
        else by every other program.
    """
    if ppq <= 0:
        raise ValueError(f"ppq must be positive, got {ppq}")

    target = Path(path)
    midi = mido.MidiFile(ticks_per_beat=ppq)
    track = mido.MidiTrack()
    midi.tracks.append(track)

    track.append(mido.MetaMessage("track_name", name=track_name, time=0))
    track.append(
        mido.MetaMessage(
            "time_signature",
            numerator=time_signature[0],
            denominator=time_signature[1],
            time=0,
        )
    )
    track.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(tempo), time=0))

    # MIDI files are a flat stream of events with delta times, so the notes have to
    # be flattened into note-on and note-off pairs in time order.
    events: list[tuple[int, int, str, int, int]] = []
    for note in notes:
        start = int(round(float(note.get("time", 0.0)) * ppq))
        length = int(round(float(note.get("duration", 1.0)) * ppq))
        if length <= 0:
            continue
        pitch = int(note["midi"])
        velocity = _to_midi_velocity(note.get("velocity", 0.8))
        events.append((start, 1, "note_on", pitch, velocity))
        events.append((start + length, 0, "note_off", pitch, 0))
    # Note that this used to insert a variable named "duration" here, and a later
    # line read `tick + message.time if "duration" in message.type else ...`. The
    # substring test is true for "end_of_track", so the loop overwrote the variable
    # with 0.5 and every note came back 960 times too short. The conditional is gone
    # rather than corrected, because a substring match on a message type is a trap
    # that will be sprung again by whoever adds the next condition.

    # Note-offs sort before note-ons at the same tick, so a note ending exactly
    # where the next begins does not cut it off.
    events.sort(key=lambda event: (event[0], event[1]))

    previous = 0
    for tick, _, kind, pitch, velocity in events:
        track.append(
            mido.Message(kind, note=pitch, velocity=velocity, time=tick - previous)
        )
        previous = tick

    midi.save(str(target))
    return target


def from_midi_file(path: str | Path) -> dict[str, Any]:
    """Read notes from a standard MIDI file.

    Args:
        path: The file to read.

    Returns:
        notes: notes with `midi`, `time` and `duration` in beats, and `velocity`
               from 0.0 to 1.0
        ppq: the file's own ticks per beat, which is what the conversion used
        tempo: the first tempo in BPM, or None
        time_signature: the first time signature, or None

    Raises:
        ValueError: If the file cannot be read, rather than returning an empty list.
            An empty list would look like an empty pattern, which is a different
            problem with a different fix.
    """
    source = Path(path)
    try:
        midi = mido.MidiFile(str(source))
    except Exception as error:
        raise ValueError(f"Could not read {source}: {error}") from error

    ppq = midi.ticks_per_beat or DEFAULT_PPQ
    tempo = None
    time_signature = None
    notes: list[Note] = []
    # A note-on with velocity 0 is a note-off, which every MIDI file in the wild
    # uses, and reading it as a note-on would leave notes hanging forever.
    sounding: dict[int, tuple[int, int]] = {}
    tick = 0

    # Iterate the track rather than the file. mido's file iterator returns
    # different deltas from the track it holds: measured here, the same file gave
    # a note_off delta of 96 through `midi.tracks[0]` and 0.5 through `for message
    # in midi`, with ticks_per_beat reading 96 either way. That silently shrinks
    # every note by a factor of the PPQ times two, which is exactly the bug that
    # took a while to find. The track is the source of truth.
    for message in _all_messages(midi):
        tick += message.time
        if message.type == "set_tempo" and tempo is None:
            tempo = mido.tempo2bpm(message.tempo)
        elif message.type == "time_signature" and time_signature is None:
            time_signature = (message.numerator, message.denominator)
        elif message.type == "note_on" and message.velocity > 0:
            sounding[message.note] = (tick, message.velocity)
        elif message.type in ("note_off", "note_on"):
            start = sounding.pop(message.note, None)
            if start is None:
                continue
            start_tick, velocity = start
            notes.append({
                "midi": message.note,
                "time": start_tick / ppq,
                "duration": (tick - start_tick) / ppq,
                "velocity": velocity / 127.0,
            })

    notes.sort(key=lambda note: (note["time"], note["midi"]))
    return {
        "notes": notes,
        "ppq": ppq,
        "tempo": tempo,
        "time_signature": time_signature,
    }


def _all_messages(midi: mido.MidiFile):
    """Every message in the file, in order, read from the tracks.

    Reading the tracks directly avoids mido's file level iterator, which rescales
    delta times against the track length.
    """
    for track in midi.tracks:
        for message in track:
            yield message


def _to_midi_velocity(velocity: Any) -> int:
    """A 0.0 to 1.0 velocity as a MIDI 1 to 127 value.

    Zero would be a note-off rather than a very quiet note, so a quiet note is
    clamped to 1 instead of vanishing.
    """
    value = int(round(float(velocity) * 127))
    return max(1, min(127, value))
