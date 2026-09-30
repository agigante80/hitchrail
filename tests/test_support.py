"""The shared module walker the structural guards stand on (#368).

A guard that walks the wrong set of files passes by looking at nothing, so the
walker's own two properties are asserted here rather than trusted.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from support import keyed_modules, module_name, source_modules


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
