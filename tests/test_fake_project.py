"""The fake project is the substrate every later phase asserts against.

Its job is to be a faithful, boring model of FL's documented surface: correct
signatures, documented value ranges, and honest errors for indices that do not
exist. It is not a DAW, and it is never more capable than the real API.
"""

from __future__ import annotations

import pytest

from tests.fakes.project import FakeProject


def test_channels_carry_the_properties_the_api_exposes():
    project = FakeProject.with_channels(3)
    assert [c.name for c in project.channels] == ["Channel 1", "Channel 2", "Channel 3"]
    assert project.channels[0].volume == pytest.approx(0.8)  # FL's documented default
    assert project.channels[0].pan == pytest.approx(0.0)
    assert project.channels[0].pitch == 0
    assert project.channels[0].target_fx_track == 0


def test_step_grid_is_per_channel():
    project = FakeProject.with_channels(2)
    project.channels[0].grid[0] = True
    assert project.channels[0].grid[0] is True
    assert project.channels[1].grid[0] is False


def test_each_channel_gets_its_own_grid():
    """A shared mutable default would make every channel the same channel."""
    project = FakeProject.with_channels(2)
    project.channels[0].grid[3] = True
    assert project.channels[1].grid[3] is False


def test_mixer_has_a_master_track_at_index_zero():
    project = FakeProject.with_tracks(4)
    assert project.tracks[0].name == "Master"
    assert len(project.tracks) == 4


def test_tempo_is_stored_in_thousandths():
    """Live FL Studio returned 130000 at 130 BPM, so the unit is thousandths."""
    assert FakeProject().tempo == 130000


def test_unknown_channel_index_raises():
    project = FakeProject.with_channels(1)
    with pytest.raises(IndexError):
        project.channel(5)


def test_negative_channel_index_raises():
    """Python would happily read from the end of the list. FL would not."""
    project = FakeProject.with_channels(3)
    with pytest.raises(IndexError):
        project.channel(-1)


def test_unknown_track_index_raises():
    project = FakeProject.with_tracks(2)
    with pytest.raises(IndexError):
        project.track(9)


def test_index_zero_is_the_first_channel_not_a_default():
    """The upstream bug was reading index 0 when the caller omitted the index.

    The fake cannot reproduce that bug, but it must make the bug impossible to
    hide: index 0 has to be a perfectly ordinary channel, so a handler that
    defaults to it edits the wrong thing loudly rather than the right thing by
    luck.
    """
    project = FakeProject.with_channels(3)
    assert project.channel(0).name == "Channel 1"
    assert project.channel(2).name == "Channel 3"


def test_notes_carry_all_sixteen_documented_properties():
    """Phase 4 writes expression, so the fake has to hold it."""
    from tests.fakes.project import Note

    note = Note(number=36, time=0, length=48)
    documented = {
        "number",
        "time",
        "length",
        "velocity",
        "pan",
        "color",
        "fcut",
        "fres",
        "group",
        "muted",
        "pitchofs",
        "porta",
        "release",
        "repeats",
        "selected",
        "slide",
    }
    assert documented <= set(vars(note))


def test_clamp_holds_values_to_the_documented_range():
    from tests.fakes.project import clamp

    assert clamp(1.5, 0.0, 1.0) == 1.0
    assert clamp(-0.5, 0.0, 1.0) == 0.0
    assert clamp(0.5, 0.0, 1.0) == 0.5
    assert clamp(-2.0, -1.0, 1.0) == -1.0
