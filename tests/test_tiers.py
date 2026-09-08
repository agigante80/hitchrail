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
# **Every marker that names a tier, or this file guards a shrinking subset.**
# `cli` and `device` were added without being registered here, which is the case
# this module's own premise was written for: a tier is a DECLARATION only while
# something checks it.
#
# The glob below is RECURSIVE since #216. It was not, so `tests/e2e/`,
# `tests/cli_tier/` and `tests/device/` were not scanned at all: the markers
# were registered here while the files using them went unchecked, which is a
# guard reporting on a shrinking subset without saying so.
TIERS = {"integration", "live", "live_tmux", "e2e", "cli", "device"}
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


@pytest.mark.parametrize("path", sorted(TESTS.rglob("test_*.py")), ids=lambda p: p.name)
def test_no_test_claims_two_tiers(path: Path) -> None:
    """A test in two tiers is in neither, because every selection contradicts.

    `-m "not integration"` would exclude it from a live run and `-m live` would
    pull it into one, so which tier it is depends on how you ask.
    """
    module = _module_tiers(path)
    for node, marks in _tests_in(path):
        both = marks | module
        assert len(both) <= 1, f"{path.name}::{node.name} claims tiers {sorted(both)}"


@pytest.mark.parametrize("path", sorted(TESTS.rglob("test_*.py")), ids=lambda p: p.name)
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


# -- #216: the cli tier must not touch the operator's own tmux server ---------

CLI_TIER = TESTS / "cli_tier"

# The one helper that builds a child environment for this tier. Every spawn goes
# through it, and the guard below is what makes "every" true rather than
# intended.
_CHILD_ENV = "_child_env"
_SPAWNERS = {"run", "Popen", "call", "check_call", "check_output"}


def _runs_the_console_script(call: ast.Call) -> bool:
    """Whether this spawn's argv starts with the console script.

    Structural: the first positional argument is a list whose first element
    mentions `CONSOLE_SCRIPT`. Not a text search for the name, which would match
    the docstrings that explain it.
    """
    if not call.args or not isinstance(call.args[0], ast.List) or not call.args[0].elts:
        return False
    first = call.args[0].elts[0]
    return any(
        isinstance(node, ast.Name) and node.id == "CONSOLE_SCRIPT" for node in ast.walk(first)
    )


def _spawn_calls(tree: ast.AST) -> list[ast.Call]:
    """Every `subprocess.<spawner>(...)` call in a module."""
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in _SPAWNERS
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "subprocess"
    ]


@pytest.mark.parametrize("path", sorted(CLI_TIER.rglob("*.py")), ids=lambda p: p.name)
def test_the_cli_tier_never_spawns_without_an_isolated_tmux(path: Path) -> None:
    """#216. This tier runs the installed console script, and the program it
    runs talks to whichever tmux server its environment names.

    `env -u TMUX` stops the child inheriting an ambient SESSION. It does not
    choose a SOCKET, so without `TMUX_TMPDIR` the spawned Hitchrail addresses the
    operator's own server. Contact is read only today, one `list-panes -a`, and
    the hazard is the next commit: a tier called "runs the program" grows a start
    case, and then a spawned Hitchrail creates `hr-` sessions on the real server,
    whose kill paths are scoped to the same `hr-` prefix a real one uses.

    **The conftest used to ask the next author not to do that, in a comment.**
    This project has repeatedly found that worthless, so the property is asserted
    instead: every spawn in this tier passes an environment built by
    `_child_env`, which sets `TMUX_TMPDIR` and cannot be called without one.

    **Scoped to the console script, and the scope is the claim.** Other spawns
    here are tmux, each explicitly scoped with `-S` or deliberately unscoped to
    ask the operator's own server a question. The program under test is the one
    whose environment must not depend on a reader noticing.

    Read structurally, in both halves: which spawns run the console script, and
    whether the env came from `_child_env`. A guard that grepped for the string
    `TMUX_TMPDIR` would match this docstring and the comment above it, which is
    the trap this repository has hit four times.
    """
    tree = ast.parse(path.read_text())
    spawns = _spawn_calls(tree)
    running_the_script = [c for c in spawns if _runs_the_console_script(c)]

    # **This guard inspects nothing in two of its three files, and used to say
    # so nowhere (round 1 review).** Measured: `__init__.py` has 0 spawns,
    # `test_running_the_program.py` has 2 spawns and 0 that run the console
    # script, `conftest.py` has 3 and 2. So the whole check rests on one file,
    # and its sibling below already asserts its own input is non-empty.
    #
    # It is brittle in exactly the way that takes the count to zero:
    # `_runs_the_console_script` needs `call.args[0]` to be a literal `ast.List`
    # and `_spawn_calls` needs a `subprocess.<verb>` attribute. Hoisting
    # `argv = [str(CONSOLE_SCRIPT), ...]` into a variable, or writing
    # `from subprocess import run`, drops every match and this passes while
    # enforcing nothing. That is the shrinking-subset failure this module's own
    # docstring names about its non-recursive glob.
    #
    # So the per-file assertion is on the TIER, not on each file: at least one
    # file here must still spawn the console script.
    if path.name == "conftest.py":
        assert running_the_script, (
            "no spawn in the cli tier's conftest runs the console script any "
            "more, so this guard is matching nothing. Either the tier stopped "
            "spawning it, or the argv is no longer a literal list and this "
            "check has to be repointed rather than left green."
        )

    offenders: list[str] = []
    for call in spawns:
        if not _runs_the_console_script(call):
            # Other spawns in this tier are tmux itself, and each is either
            # scoped with `-S` to a socket the caller made or is deliberately
            # UNSCOPED to ask the operator's own server whether it holds a
            # session, which is the negative half of the isolation proof. Both
            # are legible at the call site; the program under test is the one
            # whose environment cannot be left to a reader's care.
            continue
        env = next((kw for kw in call.keywords if kw.arg == "env"), None)
        built_here = (
            env is not None
            and isinstance(env.value, ast.Call)
            and isinstance(env.value.func, ast.Name)
            and env.value.func.id == _CHILD_ENV
        )
        if not built_here:
            offenders.append(f"line {call.lineno}")

    assert not offenders, (
        f"{path.relative_to(TESTS.parent)} spawns a process at {', '.join(offenders)} "
        f"without `env={_CHILD_ENV}(...)`. Every child in this tier must carry an "
        "isolated TMUX_TMPDIR, or the program under test addresses the operator's "
        "own tmux server and its kill paths are scoped to the same prefix a real "
        "Hitchrail uses."
    )


# -- #94: the live tmux tier reads the machine's whole process table ----------

LIVE_TIER = TESTS / "test_live_tmux.py"

# The two shapes a project name may arrive in at a `derive` call. `machine.project`
# is the fixture handing back the folder it made; `live_project(...)` is the one
# function that stamps the namespace on. Anything else is a name a test chose.
_NAMESPACER = "live_project"
_FIXTURE_ATTR = "project"


def _derive_calls(tree: ast.AST) -> list[ast.Call]:
    """Every `derive.derive(...)` call in a module."""
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "derive"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "derive"
    ]


def _is_namespaced(node: ast.expr) -> bool:
    """Whether this expression can only be a name the tier itself minted."""
    if isinstance(node, ast.Attribute) and node.attr == _FIXTURE_ATTR:
        return True
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == _NAMESPACER
    )


def test_the_live_tier_never_derives_a_project_it_did_not_namespace() -> None:
    """#94. This tier isolates tmux and cannot isolate the PROCESS TABLE.

    `derive` calls `procs.snapshot()`, which reads every process on the machine
    running the suite, and orphan attribution matches on the argv tail with the
    binary deliberately stripped. So a real agent for a real project of the same
    name is indistinguishable from the fixture's, whatever binary started it.

    That is not hypothetical. The first version of #84's test used the tier's
    usual fixture name `vessel` and failed on a real agent 8 hours old, because
    `tests/conftest.py` named its fixtures after the developer's real projects.
    **It could as easily have passed**, and a green test satisfied by somebody
    else's agent is the failure this phase exists to remove.

    The browser tier made this structural with `E2E_PREFIX` and has never had
    the failure. The answer here is the same shape and this guard is what makes
    it hold: a name reaching `derive` is either `machine.project`, which the
    fixture minted along with the folder, or a `live_project(...)` call, which
    cannot return an un-namespaced string. A literal, an f-string or a module
    constant fails here.

    **Its limit, stated rather than implied.** Rebinding a namespaced name
    through a local variable would pass. That is not the mistake this guards:
    #94 was written by somebody typing the name they were used to, and the
    shape above is what stops the typing.
    """
    tree = ast.parse(LIVE_TIER.read_text())
    calls = _derive_calls(tree)
    assert calls, (
        f"{LIVE_TIER.name} no longer derives anything, so this guard is asserting "
        "nothing. Delete it or point it at the tier that took over."
    )

    offenders = [
        f"line {call.lineno}"
        for call in calls
        if not (call.args and _is_namespaced(call.args[0]))
    ]
    assert not offenders, (
        f"{LIVE_TIER.name} derives an un-namespaced project at {', '.join(offenders)}. "
        f"Use the `machine` fixture's `.{_FIXTURE_ATTR}`, or `{_NAMESPACER}(...)`. A "
        "name a real agent could also be running makes this tier's result depend on "
        "what else the machine happens to be doing."
    )


def test_no_other_test_reads_the_real_process_table() -> None:
    """The guard above names ONE file, and this is what makes that honest.

    `snapshot()` with no runner shells out to `ps` and reads the machine. Every
    other caller in the suite passes a fake, so the namespace requirement lands
    exactly where the hazard is. Nothing said so, and a guard scoped to a file
    on an unstated assumption is the shrinking-subset failure this module has
    already had once: the glob above was non-recursive, so three directories
    went unchecked while their markers were registered here.

    A new file calling the real thing has to come here and decide, rather than
    inheriting the isolation of a tier it is not in.
    """
    offenders = []
    for path in sorted(TESTS.rglob("test_*.py")):
        if path == LIVE_TIER:
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "snapshot"
                and not node.args
            ):
                offenders.append(f"{path.name}:{node.lineno}")

    assert not offenders, (
        f"{', '.join(offenders)} calls `snapshot()` with no runner, so it reads every "
        f"process on the machine. Either pass a fake, or give it the namespace "
        f"{LIVE_TIER.name} uses and widen the guard above to cover it."
    )
