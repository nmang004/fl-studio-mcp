"""The server must survive a response file it catches mid write.

FL Studio's embedded Python sandbox blocks the rename syscalls, so the controller
cannot write a response atomically: `os.replace` raises `SystemError: <built-in
function replace> returned NULL without setting an exception` on FL Studio 2026,
build 5406, which bundles CPython 3.12.1. The same is true of `Path.mkdir`, which
is why the controller no longer creates its own directory.

That means Path.write_text truncates and rewrites the response file in place, and
the polling server can read it in the moment it is empty or half written. The
response format is one JSON object followed by a newline, so anything that does
not parse is unfinished rather than malformed, unless it ends with a closing
brace.
"""

from __future__ import annotations

import json
import threading
import time

from fl_studio_mcp.utils.midi_connection import NOT_READY, MIDIResponseReader
from tests.helpers import load_controller, module_with


def _reader(settings) -> MIDIResponseReader:
    return MIDIResponseReader(settings / "Hardware" / "FLStudioMCP" / "mcp_response.json")


def _response_file(settings):
    return settings / "Hardware" / "FLStudioMCP" / "mcp_response.json"


def test_a_complete_object_is_read(fl_settings):
    _response_file(fl_settings).write_text('{"success": true, "count": 7}\n')
    assert _reader(fl_settings).read() == {"success": True, "count": 7}


def test_an_empty_file_is_not_finished(fl_settings):
    """The truncate-then-write window, and the exact case that broke live FL."""
    _response_file(fl_settings).write_text("")
    assert _reader(fl_settings).read() is NOT_READY


def test_a_half_written_object_is_not_finished(fl_settings):
    _response_file(fl_settings).write_text('{"success": true, "cou')
    assert _reader(fl_settings).read() is NOT_READY


def test_a_missing_file_is_not_finished(fl_settings):
    assert _reader(fl_settings).read() is NOT_READY


def test_a_complete_but_invalid_object_is_an_error(fl_settings):
    """Ends with a brace, so it is finished; it is simply wrong."""
    _response_file(fl_settings).write_text("{not json}\n")
    result = _reader(fl_settings).read()
    assert result is not NOT_READY
    assert result["success"] is False


def test_an_object_without_a_success_field_is_an_error(fl_settings):
    _response_file(fl_settings).write_text('{"count": 7}\n')
    result = _reader(fl_settings).read()
    assert result["success"] is False
    assert "success" in result["error"]


def test_a_non_object_response_is_an_error(fl_settings):
    """Valid JSON that is not an object is finished, so it is an error."""
    _response_file(fl_settings).write_text("[1, 2, 3]\n")
    result = _reader(fl_settings).read()
    assert result is not NOT_READY
    assert result["success"] is False


def test_reading_does_not_consume_the_file(fl_settings):
    """The poller deletes it, so the reader itself must leave it alone."""
    path = _response_file(fl_settings)
    path.write_text('{"success": true}\n')
    _reader(fl_settings).read()
    assert path.exists()


def test_polling_waits_for_a_response_that_appears_late(fl_settings):
    """The reader is polled, so a truncated file must not end the wait."""
    reader = _reader(fl_settings)
    _response_file(fl_settings).write_text("")
    assert reader.read() is NOT_READY
    _response_file(fl_settings).write_text('{"success": true}\n')
    assert reader.read() == {"success": True}


def test_a_response_written_late_is_still_read(fl_settings):
    """Whole-sequence proof: truncated first, complete a moment later."""
    reader = _reader(fl_settings)

    def slow_write():
        _response_file(fl_settings).write_text('{"success": false, "error": "bo')
        time.sleep(0.01)
        _response_file(fl_settings).write_text('{"success": false, "error": "boom"}\n')

    thread = threading.Thread(target=slow_write)
    thread.start()
    deadline = time.time() + 2.0
    result = reader.read()
    while result is NOT_READY and time.time() < deadline:
        result = reader.read()
        time.sleep(0.001)
    thread.join()
    assert result == {"success": False, "error": "boom"}


def test_the_controller_writes_a_trailing_newline(fl_settings, monkeypatch):
    """The newline is what lets the reader tell complete from truncated."""
    controller = load_controller(monkeypatch, {"mixer": module_with(trackCount=lambda: 3)})
    controller.COMMAND_FILE.write_text(json.dumps({"action": "mixer.getTrackCount"}))
    controller.execute_pending_command()
    assert controller.RESPONSE_FILE.read_text().endswith("}\n")


def test_the_controller_does_not_need_a_rename_to_write(controller):
    """A rename raises SystemError inside FL, so the write must not call one.

    Checked against the parse tree rather than the source text, because the
    docstring has to be free to explain why a rename is impossible.
    """
    import ast
    import inspect
    import textwrap

    source = textwrap.dedent(inspect.getsource(controller.write_response))
    called = {
        node.func.attr
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "replace" not in called
    assert "rename" not in called


def test_the_pyscript_calls_no_blocked_filesystem_function():
    """The piano roll sandbox blocks os.replace too, and it crashed there.

    Measured on FL Studio 2026, build 5406, from inside a piano roll script:

        os.replace(temporary, path)
        SystemError: error return without exception set

    The builtin open() does work in this sandbox, unlike the controller sandbox,
    so the blocklist here is the rename and directory family only. This test
    exists because the code belied its own docstring: it claimed this sandbox was
    an ordinary CPython, and FL answered with an error dialog.
    """
    import ast

    from tests.helpers import PYSCRIPT_PATH

    blocked = {
        "replace",
        "rename",
        "remove",
        "removedirs",
        "rmdir",
        "mkdir",
        "makedirs",
        "unlink",
        "glob",
        "rglob",
        "walk",
    }
    tree = ast.parse(PYSCRIPT_PATH.read_text())
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in blocked:
            offenders.append(f"{func.attr}() at line {node.lineno}")
        elif isinstance(func, ast.Name) and func.id in blocked:
            offenders.append(f"{func.id}() at line {node.lineno}")

    assert not offenders, f"the pyscript calls functions FL's sandbox blocks: {offenders}"


def test_the_controller_calls_no_blocked_filesystem_function():
    """FL's Python sandbox blocks a set of filesystem calls.

    Measured against live FL Studio 2026, build 5406, which bundles CPython
    3.12.1. Each of these raises "SystemError: <...> returned NULL without
    setting an exception" when called from the controller:

        Path.mkdir, os.makedirs, os.replace, os.rename, os.remove,
        Path.unlink, Path.glob, open

    These work, and are the only file operations the controller may use:

        Path.write_text, Path.read_text, Path.exists, Path.is_dir,
        Path.stat, Path.iterdir, Path.home, Path.expanduser

    A blocked call breaks the whole script, because FL's loader cannot import a
    module whose body raised SystemError. The symptom is identical to FL not
    running, so this is a test rather than a comment.
    """
    import ast

    from tests.helpers import CONTROLLER_PATH

    # Dispatched by call name rather than by receiver, because the syscall is
    # blocked whichever object it is reached through: SCRIPT_DIR.mkdir is as
    # fatal as os.mkdir.
    blocked = {
        "mkdir",
        "makedirs",
        "replace",
        "rename",
        "remove",
        "removedirs",
        "rmdir",
        "unlink",
        "glob",
        "rglob",
        "walk",
        "open",
    }
    tree = ast.parse(CONTROLLER_PATH.read_text())
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in blocked:
            offenders.append(f"{func.attr}() at line {node.lineno}")
        elif isinstance(func, ast.Name) and func.id in blocked:
            offenders.append(f"{func.id}() at line {node.lineno}")

    assert not offenders, f"the controller calls functions FL's sandbox blocks: {offenders}"
