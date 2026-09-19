"""The host's list of mutating actions must equal the controller's.

Two copies of a list drift. The journal decides what to record from the host's copy,
and FL decides what to allow from its own, so a disagreement means either an edit that
never reaches the log or a refusal that never happens. This test is what makes the
duplication safe.
"""

from __future__ import annotations

import re
from pathlib import Path

from fl_studio_mcp.utils import actions

CONTROLLER = Path(__file__).resolve().parent.parent / "fl_controller" / "device_FLStudioMCP.py"


def controller_actions() -> set[str]:
    """Parse the controller's own frozenset, rather than importing the script."""
    text = CONTROLLER.read_text(encoding="utf-8")
    block = text.split("MUTATING_ACTIONS = frozenset([", 1)[1].split("])", 1)[0]
    return set(re.findall(r'"([^"]+)"', block))


def test_the_two_lists_are_identical():
    assert controller_actions() == set(actions.MUTATING_ACTIONS)


def test_the_list_is_not_empty():
    """A parse that silently found nothing would make the equality test vacuous."""
    assert len(controller_actions()) > 30


def test_reading_the_mixer_is_not_a_mutation():
    for action in ("mixer.getSnapshot", "mixer.getLevels", "system.getInfo", "transport.getStatus"):
        assert not actions.is_mutating(action), f"{action} is a read"


def test_writing_a_fader_is_a_mutation():
    for action in ("mixer.setTrackVolume", "channels.setChannelName", "plugins.setParamValue"):
        assert actions.is_mutating(action), f"{action} changes the project"


def test_a_batch_is_not_on_the_list():
    """A batch mutates only if what it carries does.

    The controller leaves system.batch out of its own list and checks the commands
    inside it instead, and the journal expands a batch into the commands it carried
    rather than labelling the wrapper. Both follow from this one fact.
    """
    assert not actions.is_mutating("system.batch")
