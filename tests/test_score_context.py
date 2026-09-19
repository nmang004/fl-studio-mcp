"""The project's key and meter, so the server stops assuming C major 4/4.

The stubs put the key and the meter in the piano roll script's sandbox, on
flpianoroll.score, not in the controller. The roadmap lists them as controller
sources; they are not, and this is the correction. The controller contributes only
the PPQ, which the piano roll sandbox does not expose.

snap_scale_helper is a string of 0 and 1 separated by commas, where 0 means in the
scale and 1 means out, always aligned to C. It is not an index or an enum.
"""

from __future__ import annotations

import pytest

from fl_studio_mcp.musical import score

# C major: the black keys are out of scale.
C_MAJOR = "0,1,0,1,0,0,1,0,1,0,1,0"
# A natural minor, which contains exactly the same notes as C major: C, D, E, F, G,
# A, B. The key is different because the root is, and the helper is always
# C-aligned, so A sits at index 9. Two earlier versions of this constant were wrong
# in different ways, which is a fair illustration of how easy the C alignment is to
# get wrong.
A_MINOR = "0,1,0,1,0,0,1,0,1,0,1,0"


def read(fl_env, root=0, helper=C_MAJOR, tsnum=4, tsden=4, ppq=96):
    fl_env.project.snap_root_note = root
    fl_env.project.snap_scale_helper = helper
    fl_env.project.tsnum = tsnum
    fl_env.project.tsden = tsden
    fl_env.project.ppq = ppq
    return score.read_context(
        fl_env.pyscript, fl_env.piano_roll_response_file, fl_env.request_file
    )


def test_the_context_reports_the_root_note(fl_env):
    assert read(fl_env, root=9, helper=A_MINOR)["root_note"] == 9


def test_the_context_translates_the_helper_into_scale_degrees(fl_env):
    assert read(fl_env)["in_scale"] == [0, 2, 4, 5, 7, 9, 11]


def test_the_context_reports_a_minor_scale(fl_env):
    """in_scale is semitone offsets from the root, so A minor starts at 0."""
    context = read(fl_env, root=9, helper=A_MINOR)
    assert context["in_scale"] == [0, 2, 3, 5, 7, 8, 10]
    assert context["c_aligned_degrees"] == [0, 2, 4, 5, 7, 9, 11]


def test_the_context_reports_the_meter(fl_env):
    context = read(fl_env, tsnum=3, tsden=4)
    assert context["time_signature"] == "3/4"
    assert context["beats_per_bar"] == 3


def test_the_context_reports_the_ppq(fl_env):
    assert read(fl_env, ppq=192)["ppq"] == 192


def test_the_context_names_a_minor_key(fl_env):
    assert score.key_name(9, A_MINOR) == "A minor"


def test_the_context_names_a_major_key(fl_env):
    assert score.key_name(0, C_MAJOR) == "C major"


def test_the_context_names_an_accidental_key(fl_env):
    assert score.key_name(10, C_MAJOR).startswith("A#")


def test_a_helper_that_is_not_twelve_entries_is_refused(fl_env):
    """A malformed helper would silently produce a wrong scale."""
    with pytest.raises(ValueError):
        score.scale_degrees("0,1,0")


def test_a_helper_with_an_unexpected_character_is_refused(fl_env):
    with pytest.raises(ValueError):
        score.scale_degrees("0,1,0,1,0,0,1,0,1,0,1,x")


def test_a_scale_with_no_notes_is_refused(fl_env):
    """Twelve ones means every note is out of scale, which cannot be right."""
    with pytest.raises(ValueError):
        score.scale_degrees(",".join(["1"] * 12))


def test_the_tool_reports_the_context(piano_roll_wired):
    """The whole path: transport, script, reply, and the PPQ from the controller."""
    from fl_studio_mcp.tools import score as score_tool

    fl_env = piano_roll_wired
    fl_env.project.ppq = 96
    context = score_tool.get_project_context()
    assert context["key"] == "C major"
    assert context["ppq"] == 96
    assert context["beats_per_bar"] == 4


def test_the_context_is_found_even_when_another_request_is_queued(piano_roll_wired):
    """The reply carries every response, and the context is looked up by its id.

    Found live: a context read queued alongside a write returned null for the key,
    because the reply echoed whichever response came first.
    """
    from fl_studio_mcp.musical import score as score_module

    reply = {
        "responses": [
            {"id": "a-write", "notes_added": 2},
            {"id": "project-context", "root_note": 9, "scale_helper": A_MINOR,
             "tsnum": 3, "tsden": 4, "ppq": 96},
        ]
    }
    context = score_module.context_from_reply(reply)
    assert context["key"] == "A minor"
    assert context["time_signature"] == "3/4"


def test_an_absent_scale_is_reported_as_absent(fl_env):
    """Measured live: with snap to scale off, the helper is an empty string.

    Treating that as malformed would make every project without snap to scale
    unusable, and naming C major would invent a key the producer never chose.
    """
    context = read(fl_env, root=0, helper="")
    assert context["scale_set"] is False
    assert "key" not in context
    assert context["time_signature"] == "4/4", "the meter is still knowable"


def test_an_empty_helper_gives_no_degrees(fl_env):
    assert score.scale_degrees("") == []
