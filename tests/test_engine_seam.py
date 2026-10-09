"""#424. `sweep.py` and `signals.py` reach the engine through `EngineSeam`.

Read from the syntax tree and not from the text, because a grep for `._` matches
the comment explaining the rule (and `Engine._await_gone` in a docstring). What
counts is an attribute access, or a `getattr` style call naming one, on a
parameter whose annotation is the engine's type: there, a leading underscore is
a reach past the interface into the engine's layout.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src" / "hitchrail"
GUARDED = ("signals.py", "sweep.py")
ENGINE_TYPES = {"Engine", "EngineSeam"}
STRING_REACHES = {"getattr", "setattr", "hasattr", "delattr"}


def _private(name: str) -> bool:
    return name.startswith("_") and not (name.startswith("__") and name.endswith("__"))


def underscore_reaches(source: str) -> list[str]:
    """Every `<engine param>._x` access, and every getattr style call naming
    `"_x"` on one, as `line: text`."""
    tree = ast.parse(source)
    found: list[str] = []
    for func in ast.walk(tree):
        if not isinstance(func, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        params = {
            arg.arg
            for arg in [*func.args.posonlyargs, *func.args.args, *func.args.kwonlyargs]
            if isinstance(arg.annotation, ast.Name) and arg.annotation.id in ENGINE_TYPES
        }
        if not params:
            continue
        for node in ast.walk(func):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id in params
                and _private(node.attr)
            ):
                found.append(f"{node.lineno}: {node.value.id}.{node.attr}")
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in STRING_REACHES
                and len(node.args) >= 2
                and isinstance(node.args[0], ast.Name)
                and node.args[0].id in params
                and isinstance(node.args[1], ast.Constant)
                and isinstance(node.args[1].value, str)
                and _private(node.args[1].value)
            ):
                found.append(f"{node.lineno}: {node.func.id}({node.args[0].id}, ...)")
    return found


@pytest.mark.parametrize("module", GUARDED)
def test_the_module_reaches_no_underscore_member_of_the_engine(module: str) -> None:
    reaches = underscore_reaches((SRC / module).read_text())
    assert reaches == [], f"{module} reaches past EngineSeam: {reaches}"


@pytest.mark.parametrize("module", GUARDED)
def test_the_module_takes_the_engine_by_its_interface(module: str) -> None:
    """Annotated `EngineSeam`, never `Engine`: naming the class is how the next
    underscore reach would type check."""
    tree = ast.parse((SRC / module).read_text())
    annotated = {
        arg.annotation.id
        for func in ast.walk(tree)
        if isinstance(func, ast.FunctionDef | ast.AsyncFunctionDef)
        for arg in func.args.args
        if isinstance(arg.annotation, ast.Name) and arg.annotation.id in ENGINE_TYPES
    }
    assert annotated == {"EngineSeam"}


def test_the_checker_is_not_vacuous() -> None:
    """The guard has to be able to fail: each shape it claims to catch."""
    bad = (
        "def f(engine: EngineSeam) -> None:\n"
        "    engine._clock()\n"
        "    getattr(engine, '_stuck')\n"
        "    setattr(engine, '_stuck', {})\n"
    )
    assert len(underscore_reaches(bad)) == 3
    assert underscore_reaches("def f(engine: EngineSeam) -> None:\n    engine.now()\n") == []
    # A comment or docstring naming the member is not a reach.
    quiet = (
        "def f(engine: EngineSeam) -> None:\n"
        '    """Not engine._clock."""\n'
        "    # engine._stuck\n"
    )
    assert underscore_reaches(quiet) == []
    # Another object's private is not the engine's.
    assert underscore_reaches("def f(engine: EngineSeam, x: int) -> None:\n    x._y\n") == []
