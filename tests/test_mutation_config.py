"""Can the mutation sweep's configuration assemble a tree that imports, and does
everything it deselects still exist?
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from mutation_support import _REPO, _mutmut_config
from support import in_claude_ipc

# -- #131: the mutation config has to be able to assemble a tree that imports -


def _module_files(dotted: str) -> set[str]:
    """The files importing `dotted` loads, relative to `src/hitchrail`, or an
    empty set when no file is behind the name.

    #368. A name resolved as `<name>.py` only, which after `claude_ipc`
    became a package resolved to nothing, so the guard below checked nothing
    for the quarantine. Importing a submodule runs every package's
    `__init__.py` above it, so each of those is needed in the tree too.
    """
    src = _REPO / "src" / "hitchrail"
    parts = dotted.split(".")[1:]
    files = {"__init__.py"}
    for depth in range(1, len(parts) + 1):
        stem = "/".join(parts[:depth])
        if (src / stem / "__init__.py").exists():
            files.add(f"{stem}/__init__.py")
        elif depth == len(parts) and (src / f"{stem}.py").exists():
            files.add(f"{stem}.py")
        else:
            return set()
    return files


def _first_party_imports(path: Path) -> set[str]:
    """Every `hitchrail` file this file's imports load, relative to `src/hitchrail`.

    `ast.walk`, not `tree.body`: an import inside a function fails a mutmut run
    just as hard as a top level one, and later.
    """
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if (
            isinstance(node, ast.ImportFrom)
            and (node.module or "").split(".")[0] == "hitchrail"
        ):
            module = node.module or ""
            found |= _module_files(module)
            # `from hitchrail import claude_ipc, discovery`, where a name is a
            # MODULE only if there is a file behind it. `from hitchrail import
            # __version__` binds a string in `__init__.py`, and reading it as a
            # module asked for `__version__.py` to be copied. Checked against
            # the source tree rather than by pattern: a dunder rule would still
            # be wrong about any other re-exported name.
            for alias in node.names:
                found |= _module_files(f"{module}.{alias.name}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] == "hitchrail":
                    found |= _module_files(alias.name)
    return found


def test_every_mutated_module_can_be_imported_from_the_mutants_tree() -> None:
    """#131. mutmut copies `source_paths` mutated plus `also_copy` verbatim, and
    nothing else. A mutated module importing something in neither list produces
    a tree that cannot import, and the run dies before scoring one mutant.

    **This has broken twice.** Once on `tests/conftest.py`, because `also_copy`
    does not create parent directories, and once on `roots.py` (#130), where
    `config` and `discovery` both import a module the config never copied.

    The check is a `tomllib` read and an `ast` walk, so it costs milliseconds
    and needs no mutation run. That shape is the point: the expensive sweep
    stays on demand, per `.claude/CLAUDE.md`, and the cheap invariant that keeps it
    RUNNABLE becomes a gate. A check exempt from CI is a check that can rot
    without anybody learning.

    Structure, never file text. A guard that grepped `pyproject.toml` for a
    module name would match this docstring, which is the trap this repository
    has now hit three times.
    """
    section = _mutmut_config()
    entries = section["source_paths"] + section.get("also_copy", [])
    src = _REPO / "src" / "hitchrail"
    # Relative to `src/hitchrail`, never a bare name (#368): two
    # `__init__.py` would otherwise stand in for each other.
    copied: set[str] = set()
    for entry in entries:
        path = _REPO / entry
        if path.is_relative_to(src):
            found = sorted(path.rglob("*.py")) if path.is_dir() else [path]
            copied |= {f.relative_to(src).as_posix() for f in found}
    assert any(in_claude_ipc(rel) for rel in copied), "no claude_ipc module is copied"

    # **Every copied file, not only the mutated ones, and #221 is why.** This
    # walked `source_paths` alone, so it checked seven modules and ignored the
    # twelve in `also_copy` and every test. `engine.py` is copied rather than
    # mutated and imports `attention`, which was in neither list, so the tree
    # had `engine.py` and no `attention.py`: `conftest.py` failed to import, and
    # pytest exited 4, a USAGE error rather than a test failure. mutmut reported
    # only "Failed to run pytest with args", which is why it read as a broken
    # command for a day. The guard was green throughout, because the module that
    # could not import was one it never looked at.
    scanned: list[Path] = []
    for rel in entries:
        path = _REPO / rel
        if path.is_dir():
            scanned.extend(sorted(path.rglob("*.py")))
        elif path.suffix == ".py":
            scanned.append(path)

    missing: dict[str, set[str]] = {}
    for module in scanned:
        gaps = {i for i in _first_party_imports(module) if i not in copied}
        if gaps:
            missing[str(module.relative_to(_REPO))] = gaps

    assert not missing, (
        "the mutants tree cannot import: "
        + "; ".join(f"{m} imports {sorted(g)}" for m, g in sorted(missing.items()))
        + ". Add each to [tool.mutmut] source_paths or also_copy, or `uv run mutmut run` "
        "dies before it scores a single mutant."
    )


def test_every_test_the_sweep_deselects_still_exists() -> None:
    """#221. A `--deselect` naming a test that is gone makes pytest exit 4, and
    mutmut renders that as "Failed to run pytest with args: [...]".

    **That message names the arguments, so it reads as a malformed command**,
    and every argument in it is valid. The one time this happened the cause was
    a missing module rather than a stale node id, and it still cost a day. This
    closes the other way in.

    Reads the node id structurally: the file must exist and the function must be
    DEFINED in it. A substring search would match the name in a docstring, which
    is how a guard in this repository has failed three times.
    """
    deselected = [
        arg.split("=", 1)[1]
        for arg in _mutmut_config().get("pytest_add_cli_args", [])
        if arg.startswith("--deselect=")
    ]
    assert deselected, (
        "[tool.mutmut] pytest_add_cli_args deselects nothing. The repository shape "
        "guards MUST be deselected under a sweep: they read the source, and under a "
        "run that source is a tree nobody wrote."
    )

    gone: list[str] = []
    for nodeid in deselected:
        path, _, name = nodeid.partition("::")
        target = _REPO / path
        defined = target.exists() and re.search(
            rf"^def {re.escape(name)}\(", target.read_text(), re.M
        )
        if not defined:
            gone.append(nodeid)

    assert not gone, (
        "[tool.mutmut] deselects tests that do not exist: "
        + ", ".join(gone)
        + ". pytest exits 4 on an unknown node id, and mutmut reports that as a bad "
        "command rather than a missing test."
    )
