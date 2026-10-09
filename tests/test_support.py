"""The shared module walker the structural guards stand on (#368).

A guard that walks the wrong set of files passes by looking at nothing, so the
walker's own two properties are asserted here rather than trusted.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from support import Orphan, keyed_modules, module_name, source_modules


def test_two_init_files_are_two_modules(tmp_path: Path) -> None:
    """A package's `__init__.py` and the top level one were one key under
    `p.name`, so a guard saw whichever the walk reached last."""
    (tmp_path / "__init__.py").write_text("")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    (tmp_path / "pkg" / "keys.py").write_text("")
    assert set(source_modules(tmp_path)) == {"__init__.py", "pkg/__init__.py", "pkg/keys.py"}


def test_a_repeated_key_is_refused_rather_than_merged(tmp_path: Path) -> None:
    path = tmp_path / "a.py"
    with pytest.raises(ValueError, match=r"two modules keyed 'a\.py'"):
        keyed_modules([path, path], tmp_path)


@pytest.mark.parametrize(
    ("rel", "dotted"),
    [
        ("config.py", "hitchrail.config"),
        ("__init__.py", "hitchrail"),
        ("claude_ipc/__init__.py", "hitchrail.claude_ipc"),
        ("claude_ipc/keys.py", "hitchrail.claude_ipc.keys"),
    ],
)
def test_a_key_names_its_module(rel: str, dotted: str) -> None:
    assert module_name(rel) == dotted


def test_an_orphan_whose_exec_fails_says_why_to_its_caller(tmp_path: Path) -> None:
    """#277. fds 0 to 2 are /dev/null before the exec, and the launcher used
    to exit 0 regardless, so a path that cannot be executed surfaced later as
    a bare `ProcessLookupError` from `pidfd_open`."""
    not_executable = tmp_path / "agent"
    not_executable.write_text("#!/bin/sh\nexit 0\n")
    for path in (tmp_path / "missing", not_executable):
        with pytest.raises(OSError, match=f"cannot exec {path}"):
            Orphan([str(path)], cwd=tmp_path)


def test_an_orphan_that_execs_is_a_live_process_not_the_launcher(tmp_path: Path) -> None:
    """The other half: the launcher now waits for the exec, and must not wait
    for the agent. A `sleep` is running and reparented when the call returns."""
    orphan = Orphan(["/bin/sleep", "30"], cwd=tmp_path)
    try:
        assert orphan.poll() is None
        assert Path(f"/proc/{orphan.pid}/cmdline").read_bytes().startswith(b"/bin/sleep")
    finally:
        orphan.close()
