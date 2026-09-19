"""Guarantees about the harness itself.

A fake that is missing a function the scripts call produces a green suite and a
broken FL. These tests derive the required surface from the scripts' own source,
so they cannot drift, and they pin the sandbox rules that are invisible to a local
interpreter.
"""

from __future__ import annotations

import ast

import pytest

from tests.helpers import CONTROLLER_MODULES, CONTROLLER_PATH, PYSCRIPT_PATH


def _attribute_calls(source: str, module_names) -> set[tuple[str, str]]:
    """Find every `module.function(...)` call in a source file."""
    tree = ast.parse(source)
    found = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id in module_names
        ):
            found.add((func.value.id, func.attr))
    return found


def test_the_parser_finds_the_controllers_fl_calls():
    """Guard the guard: if this finds nothing, the test below proves nothing."""
    calls = _attribute_calls(CONTROLLER_PATH.read_text(), CONTROLLER_MODULES)
    assert len(calls) > 20, f"only found {len(calls)} FL calls in the controller"


def test_every_fl_call_in_the_controller_exists_in_the_fakes(fl_env):
    calls = _attribute_calls(CONTROLLER_PATH.read_text(), CONTROLLER_MODULES)
    missing = []
    for module_name, function in sorted(calls):
        module = fl_env.modules[module_name]
        if not hasattr(module, function):
            missing.append(f"{module_name}.{function}")
    assert not missing, f"the controller calls FL APIs the fakes do not define: {missing}"


def test_every_fl_call_in_the_pyscript_exists_in_the_fake_flpianoroll(fl_env):
    calls = _attribute_calls(PYSCRIPT_PATH.read_text(), ("flp", "flpianoroll"))
    assert calls, "found no flpianoroll calls in the pyscript; the parser is broken"
    fake = fl_env.modules["flpianoroll"]
    missing = []
    for _, attribute_path in sorted(calls):
        target = fake
        for part in attribute_path.split("."):
            if not hasattr(target, part):
                missing.append(f"flp.{attribute_path}")
                break
            target = getattr(target, part)
    assert not missing, f"the pyscript calls flpianoroll APIs the fake lacks: {missing}"


def test_the_controller_imports_nothing_outside_the_sandbox():
    """FL's embedded Python has no __file__ and a restricted stdlib."""
    allowed = {"json", "os", "sys", "pathlib", *CONTROLLER_MODULES}
    tree = ast.parse(CONTROLLER_PATH.read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported <= allowed, f"the controller imports outside the sandbox: {imported - allowed}"


def test_the_pyscript_imports_only_flpianoroll_from_fl():
    """The piano roll sandbox has no channels and no mixer. That is the split."""
    tree = ast.parse(PYSCRIPT_PATH.read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    forbidden = imported & set(CONTROLLER_MODULES)
    assert not forbidden, f"the pyscript imports modules its sandbox does not have: {forbidden}"


def test_no_fake_playlist_can_place_a_clip(fl_env):
    """playlist has no clip placement function, so the fake must not invent one.

    This is the mechanism that keeps "not possible" in ROADMAP.md honest: the
    fake could implement anything, so it deliberately implements only what the
    stubs define.
    """
    fake = fl_env.modules["playlist"]
    for forbidden in ("add", "insert", "create", "addClip", "insertClip", "placeClip"):
        assert not hasattr(fake, forbidden), f"the fake playlist gained a {forbidden}()"


def test_no_fake_plugins_can_load_a_plugin(fl_env):
    """Loading VST or AU plugins is confirmed impossible against the stubs."""
    fake = fl_env.modules["plugins"]
    for forbidden in ("load", "loadPlugin", "addPlugin", "insertPlugin"):
        assert not hasattr(fake, forbidden), f"the fake plugins module gained a {forbidden}()"


def test_the_fake_module_set_is_exactly_what_the_scripts_may_import():
    from tests.fakes.modules import MODULE_NAMES

    assert set(MODULE_NAMES) == set(CONTROLLER_MODULES) | {"flpianoroll"}


def test_the_harness_loads_both_real_scripts(fl_env):
    """Not copies, and not stubs: the files that ship."""
    import fl_controller_under_test
    import fl_pyscript_under_test

    assert fl_controller_under_test is fl_env.controller
    assert fl_pyscript_under_test is fl_env.pyscript


@pytest.mark.parametrize(
    "attribute",
    ["getChannelName", "setChannelName", "getGridBit", "setGridBit", "midiNoteOn"],
)
def test_the_fake_channels_module_exposes_what_the_controller_calls(fl_env, attribute):
    assert hasattr(fl_env.modules["channels"], attribute)


def test_fake_modules_are_bound_to_the_project_under_test(fl_env):
    """A fake bound to a different project would make every assertion a lie."""
    fl_env.project.channels[2].name = "Bound To Me"
    assert fl_env.modules["channels"].getChannelName(2) == "Bound To Me"


def test_no_em_dash_or_en_dash_in_shipped_text():
    """Style rule from ROADMAP.md, enforced rather than remembered."""
    offenders = []
    for path in CONTROLLER_PATH.parent.parent.rglob("*"):
        if not path.is_file():
            continue
        parts = set(path.relative_to(CONTROLLER_PATH.parent.parent).parts)
        if parts & {".git", ".venv", ".pytest_cache", ".ruff_cache", "__pycache__"}:
            continue
        if path.suffix not in {
            ".py",
            ".md",
            ".pyscript",
            ".toml",
            ".yml",
            ".yaml",
            ".sh",
            ".ps1",
        }:
            continue
        text = path.read_text(errors="ignore")
        if "\u2014" in text or "\u2013" in text:
            offenders.append(str(path.relative_to(CONTROLLER_PATH.parent.parent)))
    assert not offenders, f"em dash or en dash found in: {offenders}"
