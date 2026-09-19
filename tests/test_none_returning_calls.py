"""No script may consume the return value of a function the stubs declare as None.

The pattern creation freeze of 2026-09-19 was this bug: the controller assigned
`patterns.findFirstNextEmptyPat(0)` to a variable and compared it with an integer,
while `patterns/__properties.py:189` declares `-> None`. The fake had been written from
the same misunderstanding, so the whole suite agreed with it.

The FL API declares a lot of functions as returning nothing, and a Python script that
reads one of those values gets None rather than an error at the call site. This test
reads the stubs and the two shipped scripts and refuses a call whose value is used.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CONTROLLER = REPO_ROOT / "fl_controller" / "device_FLStudioMCP.py"
PYSCRIPT = REPO_ROOT / "scripts" / "ComposeWithLLM.pyscript"

# One entry per FL module either script can import, mapped to the names it is bound
# to in that script.
CONTROLLER_MODULES = (
    "channels",
    "mixer",
    "transport",
    "plugins",
    "general",
    "patterns",
    "playlist",
    "arrangement",
    "ui",
    "device",
    "midi",
    "screen",
    "launchMapPages",
)
PYSCRIPT_MODULES = ("flp", "flpianoroll")

# The fewest uses the audit must find for its own parsing to be believable. A regex
# that silently stopped matching would otherwise turn this whole file into a pass.
# Measured: 65 in the controller, 3 in the piano roll script.
MIN_USES = 55
MIN_PYSCRIPT_USES = 3


def stub_root() -> Path | None:
    """Where the FL stubs live, found by looking rather than by importing.

    Not `find_spec("midi")`: this suite installs fake FL modules into sys.modules, and
    a fake has no __spec__, so find_spec raises ValueError depending on which test ran
    before this one. Scanning the import path for a file only the stubs have is
    independent of whatever happens to be installed at the time.
    """
    for entry in sys.path:
        candidate = Path(entry)
        if (candidate / "midi" / "__ffnep_flags.py").is_file():
            return candidate
    return None


def return_annotations(root: Path) -> dict[str, set[str]]:
    """Every stub function name mapped to the return types it is declared with."""
    annotations: dict[str, set[str]] = {}
    for path in root.glob("*/*.py"):
        try:
            text = path.read_text(errors="ignore")
        except OSError:
            continue
        for match in re.finditer(
            r"^def (\w+)\([^)]*\)\s*(->\s*([^:]+))?:", text, re.M | re.S
        ):
            name = match.group(1)
            declared = (match.group(3) or "UNANNOTATED").strip()
            annotations.setdefault(name, set()).add(declared)
    return annotations


def consumed_returns(text: str, modules: tuple[str, ...]) -> list[str]:
    """Calls in `text` whose return value is assigned or tested, as source lines."""
    names = "|".join(modules)
    patterns = (
        rf"^\s*\w+\s*=\s*(?:{names})\.\w+\(",  # assigned
        rf"^\s*(?:if|elif|while|return)\s+(?:not\s+)?(?:{names})\.\w+\(",  # tested
        rf"^\s*\w+\s*=\s*(?:{names})\.\w+\.\w+\(",  # a submodule, for the pyscript
    )
    found = []
    for pattern in patterns:
        found.extend(match.group(0).strip() for match in re.finditer(pattern, text, re.M))
    return found


@pytest.fixture(scope="module")
def annotations() -> dict[str, set[str]]:
    root = stub_root()
    if root is None:
        pytest.skip("the FL stubs are not installed, so this audit cannot run")
    return return_annotations(root)


def none_returning(annotations: dict[str, set[str]]) -> set[str]:
    return {
        name
        for name, declared in annotations.items()
        if declared & {"None", "NoneType"}
    }


def test_the_controller_never_uses_a_none_returning_call(annotations):
    text = CONTROLLER.read_text()
    uses = consumed_returns(text, CONTROLLER_MODULES)
    assert len(uses) >= MIN_USES, (
        f"only {len(uses)} uses were parsed, so the audit is not reading the file"
    )

    offenders = []
    for use in uses:
        function = re.search(r"\.(\w+)\(", use)
        if function and function.group(1) in none_returning(annotations):
            offenders.append(use)
    assert not offenders, (
        "these calls consume a value the stubs declare as None: " + "; ".join(offenders)
    )


def test_the_piano_roll_script_never_uses_a_none_returning_call(annotations):
    """The same rule for the other sandbox, which writes notes rather than reading."""
    text = PYSCRIPT.read_text()
    uses = consumed_returns(text, PYSCRIPT_MODULES)
    assert len(uses) >= MIN_PYSCRIPT_USES, (
        f"only {len(uses)} uses were parsed, so the audit is not reading the file"
    )
    offenders = []
    for use in uses:
        function = re.search(r"\.(\w+)\(", use)
        if function and function.group(1) in none_returning(annotations):
            offenders.append(use)
    assert not offenders, (
        "these calls consume a value the stubs declare as None: " + "; ".join(offenders)
    )


def test_the_audit_can_see_the_function_that_caused_the_freeze(annotations):
    """A guard on the guard, using the one case whose history is known."""
    assert "findFirstNextEmptyPat" in annotations
    assert annotations["findFirstNextEmptyPat"] == {"None"}
