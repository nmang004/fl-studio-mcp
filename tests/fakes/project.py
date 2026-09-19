"""An in-memory stand-in for the FL Studio project.

Values and defaults come from the official stubs, not from guesswork. Where a
stub documents a range, the accessors here clamp to it, so a handler that passes
1.5 for a volume fails in tests rather than silently working on FL, which clamps
for you, and hiding the bug.

Deliberately absent: anything the stubs do not define. The fake playlist has no
clip placement function because the real one has none, and a test asserts that,
which is how "not possible" in ROADMAP.md stays honest.
"""

from __future__ import annotations

from dataclasses import dataclass, field


def clamp(value: float, low: float, high: float) -> float:
    """Clamp to a documented range, the way FL does."""
    return max(low, min(high, value))


@dataclass
class Channel:
    """A Channel Rack channel.

    `grid` is the step sequencer's on/off lane, which is what channels.getGridBit
    and setGridBit read and write. Per-step velocity and pan live in the graph
    editor and are research spike T2, so they are deliberately absent.
    """

    name: str
    color: int = 0x808080
    volume: float = 0.8
    pan: float = 0.0
    pitch: int = 0
    muted: bool = False
    solo: bool = False
    selected: bool = False
    target_fx_track: int = 0
    channel_type: int = 1  # channels.CT_Native
    grid_assigned: bool = False
    grid: list[bool] = field(default_factory=lambda: [False] * 16)

    @property
    def active_steps(self) -> int:
        return sum(1 for step in self.grid if step)


@dataclass
class MixerTrack:
    """A mixer insert. Index 0 is the Master, as it is in FL."""

    name: str
    color: int = 0x808080
    volume: float = 0.8
    pan: float = 0.0
    stereo_sep: float = 0.0
    muted: bool = False
    solo: bool = False
    armed: bool = False
    routes: dict[int, float] = field(default_factory=dict)
    eq_gains: list[float] = field(default_factory=lambda: [0.0] * 7)
    eq_freqs: list[float] = field(default_factory=lambda: [0.5] * 7)
    eq_bandwidths: list[float] = field(default_factory=lambda: [0.5] * 7)

    def volume_db(self) -> float:
        """A monotonic stand-in for FL's volume-to-decibels mapping.

        The exact curve is not documented in the stubs and has not been measured,
        so this is an approximation. It is monotonic in the right direction,
        which is what tests need to distinguish 0.5 from 0.8. Do not use it to
        predict a decibel value in FL.
        """
        if self.volume <= 0.0:
            return float("-inf")
        import math

        return 20.0 * math.log10(self.volume / 0.8)


@dataclass
class Pattern:
    name: str
    color: int = 0x808080
    length: int = 16  # steps


@dataclass
class Note:
    """A piano roll note.

    All sixteen flpianoroll.Note properties are present, because the fake is the
    only place Phase 4's expression work can be tested. `number` is the MIDI note
    number, and `time` and `length` are in ticks, matching the API.
    """

    number: int = 60
    time: int = 0
    length: int = 0
    velocity: float = 0.8
    pan: float = 0.0
    color: int = 0
    fcut: float = 0.0
    fres: float = 0.0
    group: int = 0
    muted: bool = False
    pitchofs: float = 0.0
    porta: bool = False
    release: bool = False
    repeats: int = 0
    selected: bool = False
    slide: bool = False


class FakeProject:
    """The whole fake project, one instance per test.

    Nothing is shared between instances, and nothing is shared between the
    mutable fields of one instance, so a test that mutates one channel cannot
    affect another or leak into the next test.
    """

    def __init__(
        self,
        *,
        channels: list[Channel] | None = None,
        tracks: list[MixerTrack] | None = None,
        patterns: list[Pattern] | None = None,
    ) -> None:
        self.channels = channels if channels is not None else []
        self.tracks = tracks if tracks is not None else [MixerTrack("Master")]
        self.patterns = patterns if patterns is not None else [Pattern("Pattern 1")]
        self.notes: list[Note] = []

        # Thousandths of a BPM. Live FL Studio returned 130000 at 130 BPM.
        self.tempo = 130000
        # general.getRecPPQ. Not measured yet, so this is the common default.
        self.ppq = 96
        self.is_playing = False
        self.is_recording = False
        self.song_pos_hint = "1:01:00"
        self.loop_mode = 0  # 0 is pattern mode, 1 is song mode
        self.selected_channel: int | None = None
        self.api_version = 45  # observed on FL Studio 2026, build 5406
        self.safe_to_edit = True
        self.undo_stack: list[str] = []
        # How many history entries one mutating command costs. FL Studio 2026
        # files mixer changes separately from channel and step changes, which was
        # measured live: two mixer writes cost three entries, while two channel
        # writes cost one.
        self.undo_entries_per_write = 1
        self.current_pattern = 0
        self.markers: list[tuple[int, str]] = []
        self.snap_mode = 0
        self.metronome = False
        self.focused_window = -1
        self.song_length_ticks = 0
        self.playback_speed = 1.0
        self.rec_events: list[tuple[int, int, int]] = []
        self.ui_state: dict[str, object] = {}
        self.notifications: list[int] = []
        self.browser_calls: list[tuple] = []
        self.device_assigned = False
        self.device_port_number = -1
        self.sysex_sent: list[bytes] = []
        self.midi_out: list[tuple] = []
        self.focused_node_caption = ""
        self.selected_mixer_track = 0
        self.mixer_selected: list[int] = []
        self.snap_root_note = 0
        self.snap_scale_helper = 0
        self.tsnum = 4
        self.tsden = 4
        self.timeline_selection = (0, 0)
        self.midi_notes: list[tuple[int, int, int, int]] = []
        self.plugin_params: dict[tuple[int, int], dict[int, float]] = {}
        self.group_index = 0
        self.plugin_names: dict[tuple[int, int], str] = {}
        self.arrangement_selection = (0, 0)
        self.arrangement_time = 0
        self.notes_by_pattern: dict[int, list[Note]] = {}
        self.playlist_tracks: list[tuple[str, int, bool, bool]] = []
        self.live_clips: list[tuple] = []
        self.performance_mode = False

    @classmethod
    def with_channels(cls, count: int) -> FakeProject:
        return cls(channels=[Channel(f"Channel {i + 1}") for i in range(count)])

    @classmethod
    def with_tracks(cls, count: int) -> FakeProject:
        tracks = [MixerTrack("Master")]
        tracks += [MixerTrack(f"Insert {i}") for i in range(1, count)]
        return cls(tracks=tracks)

    def record_undo(self, label: str) -> None:
        """Record one undo history entry for one logical edit.

        A mutating API call moves the undo history, so the fake has to as well, or
        a test that reads the history would see nothing after a real-looking edit.
        Live FL Studio 2026 files some edits as several entries; that is modelled
        by `undo_entries_per_write`, which a test sets when the case matters.
        """
        for _ in range(max(1, self.undo_entries_per_write)):
            self.undo_stack.append(label)

    def channel(self, index: int) -> Channel:
        """Return a channel, or raise IndexError the way FL would not.

        FL silently ignores an out-of-range index, which is how a missing
        parameter used to end up editing the Master track. The fake fails loudly
        instead, so the mistake surfaces in a test rather than in someone's song.
        """
        if not 0 <= index < len(self.channels):
            raise IndexError(f"channel index {index} out of range")
        return self.channels[index]

    def track(self, index: int) -> MixerTrack:
        if not 0 <= index < len(self.tracks):
            raise IndexError(f"mixer track index {index} out of range")
        return self.tracks[index]

    def pattern(self, index: int) -> Pattern:
        if not 0 <= index < len(self.patterns):
            raise IndexError(f"pattern index {index} out of range")
        return self.patterns[index]
