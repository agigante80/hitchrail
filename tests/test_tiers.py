"""The tier structure in `docs/tech-guidelines.md` 7.4, asserted rather than described.

#37 added the `integration` marker so a tier is a declaration. That only stays
true if something checks it: the previous boundary lived in an import
statement, so a test that stopped reaching for `httpx.ASGITransport` silently
changed tier and nothing failed.

A separate file on purpose. These assertions are about the suite as a whole, so
putting them in any one test module makes that module the odd one out, and #30
is already about test files that grew past what they are named for.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

TESTS = Path(__file__).parent
TIERS = {"integration", "live", "live_tmux", "e2e"}
# Unambiguous: a module that names one of these is talking to an ASGI app.
TRANSPORTS = {"ASGITransport", "AsyncClient"}
# Ambiguous on their own, and only consulted INSIDE a module that already names
# a transport. The security tests wrap their transport in local `build` and
# `call` helpers, so the tests themselves never mention httpx. Checking these
# names globally reported `test_tmux.py`, which has its own unrelated `call`,
# and a guard that flags correct tests is one somebody deletes.
LOCAL_HELPERS = {"build", "call", "create_app", "client_for"}


def _tests_in(path: Path) -> list[tuple[ast.FunctionDef | ast.AsyncFunctionDef, set[str]]]:
    """Every top level test in a module, with the marker names on it."""
    out = []
    for node in ast.parse(path.read_text()).body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not node.name.startswith("test_"):
            continue
        marks = {
            d.attr
            for d in node.decorator_list
            if isinstance(d, ast.Attribute) and d.attr in TIERS
        }
        out.append((node, marks))
    return out


def _names_in(node: ast.AST) -> set[str]:
    """Every bare name and attribute mentioned under this node."""
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)} | {
        n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)
    }


def _module_tiers(path: Path) -> set[str]:
    """Tier markers applied to the whole module via `pytestmark`."""
    found: set[str] = set()
    for node in ast.parse(path.read_text()).body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(getattr(t, "id", None) == "pytestmark" for t in node.targets):
            continue
        found |= {
            n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute) and n.attr in TIERS
        }
    return found


@pytest.mark.parametrize("path", sorted(TESTS.glob("test_*.py")), ids=lambda p: p.name)
def test_no_test_claims_two_tiers(path: Path) -> None:
    """A test in two tiers is in neither, because every selection contradicts.

    `-m "not integration"` would exclude it from a live run and `-m live` would
    pull it into one, so which tier it is depends on how you ask.
    """
    module = _module_tiers(path)
    for node, marks in _tests_in(path):
        both = marks | module
        assert len(both) <= 1, f"{path.name}::{node.name} claims tiers {sorted(both)}"


@pytest.mark.parametrize("path", sorted(TESTS.glob("test_*.py")), ids=lambda p: p.name)
def test_a_test_that_drives_the_app_declares_a_tier(path: Path) -> None:
    """The boundary that used to be an import statement.

    Anything that builds a real Starlette app and sends a request through it is
    integration or above. Unmarked, it lands in the unit tier, and the tier
    people run in a tight loop quietly stops being fast and hermetic.
    """
    source = path.read_text()
    if not (TRANSPORTS & set(_names_in(ast.parse(source)))):
        # No ASGI transport anywhere in the module, so nothing in it can be
        # driving a real app, whatever its helpers are called.
        return
    module = _module_tiers(path)
    for node, marks in _tests_in(path):
        names = set(_names_in(node))
        if not (names & (TRANSPORTS | LOCAL_HELPERS)):
            continue
        assert marks | module, (
            f"{path.name}::{node.name} drives a real app but declares no tier. "
            "Add @pytest.mark.integration, or a module level pytestmark if the "
            "whole file is one tier."
        )
