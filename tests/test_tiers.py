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


def test_the_cli_tier_still_spawns_the_console_script_somewhere() -> None:
    """The canary for the guard below, and it asks about the TIER.

    That guard inspects nothing in two of the tier's three files, and it is
    brittle in the way that takes the count to zero everywhere:
    `_runs_the_console_script` needs `call.args[0]` to be a literal `ast.List`
    and `_spawn_calls` needs a `subprocess.<verb>` attribute. Hoisting
    `argv = [str(CONSOLE_SCRIPT), ...]` into a variable, or writing
    `from subprocess import run`, drops every match and it passes while
    enforcing nothing. That is the shrinking-subset failure this module's own
    docstring names about its non-recursive glob.

    Asked of the tier as a whole rather than per file, so moving the spawn
    between files is not a failure and losing it altogether is.
    """
    spawns = [
        call
        for path in sorted(CLI_TIER.rglob("*.py"))
        for call in _spawn_calls(ast.parse(path.read_text()))
    ]

    assert any(_runs_the_console_script(call) for call in spawns), (
        "no spawn anywhere in the cli tier runs the console script, so the guard "
        "below is matching nothing. Either the tier stopped spawning it, or the "
        "argv is no longer a literal list and the check has to be repointed "
        "rather than left green."
    )


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

    # **The canary is a separate test now, over the whole tier (#236 F3).**
    # It was `if path.name == "conftest.py":` inside this parametrised check,
    # which said TIER in its comment and implemented FILENAME. Two ordinary
    # changes made it fail for the wrong reason: the spawn moving out of
    # `conftest.py` into a helper, and the tier gaining a second `conftest.py`
    # in a subdirectory, which `rglob` yields and which would also collide on
    # the `ids=lambda p: p.name` id.

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


# -- criterion 2: no tier's result depends on what the machine has ------------

# The roadmap's second exit criterion allows exactly ONE tier to require
# something of the machine, and requires that it FAIL rather than skip:
#
#   "No tier's result depends on what the machine happens to have, with one
#    stated exception: a tier may require hardware if it is opt in and FAILS
#    rather than skips when the hardware is absent. `device` is that exception
#    and is the only one."
#
# It was not true when it was written. `test_live_tmux.py` and the browser
# harness both skipped on a missing tmux, so on such a machine two tiers went
# green having proved nothing, and `ci.yml`'s grep for the word `skipped` was
# the only thing that noticed. A grep on a log is not the criterion.
_MAY_SKIP = {
    # Not tiers. These skip on a FACT ABOUT THE REPOSITORY rather than about
    # the machine: no tags yet, no publish workflow yet, `.claude/` gitignored
    # out of a worktree. A different checkout is not a different machine.
    "test_workflows_are_pinned.py",
    "test_docs_are_true.py",
    "test_config.py",
    # A filesystem that will not create a name, and an `is_symlink` that did not
    # raise. Both are properties of the platform and both are asserted about,
    # not skipped past, in the tests that own them.
    "test_api.py",
    "test_mutation_survivors.py",
    "test_discovery.py",
}


def test_no_tier_skips_itself_when_the_machine_is_missing_something() -> None:
    """Criterion 2, made checkable rather than felt.

    A tier that skips looks like coverage while proving less than none, which
    `AGENTS.md` states and which this project has already paid for: the browser
    tier and the live tmux tier both skipped on a missing tmux, and tmux is a
    RUNTIME prerequisite of Hitchrail, so such a machine cannot run the tool
    either.

    The `device` tier is the one exception the criterion allows, and it earns it
    by failing: `tests/device/conftest.py` raises with a long message naming the
    four taps that usually fix it.

    **The allowlist is by FILE and by reason**, not by pattern, so adding a skip
    means coming here and saying which fact about the repository it turns on.
    """
    offenders: list[str] = []
    for path in sorted(TESTS.rglob("*.py")):
        if path.name in _MAY_SKIP:
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            # A CALL to `pytest.skip(...)`, or an `Attribute` naming `skipif`
            # anywhere in a decorator or a `pytestmark`. Read structurally: a
            # text search for `pytest.skip(` matches the sentence forbidding it,
            # and this guard's own docstring says the words. That trap has cost
            # this repository four separate guards.
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "skip"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "pytest"
            ):
                offenders.append(f"{path.relative_to(TESTS.parent)}:{node.lineno} pytest.skip")
            elif isinstance(node, ast.Attribute) and node.attr == "skipif":
                offenders.append(f"{path.relative_to(TESTS.parent)}:{node.lineno} skipif")

    assert not offenders, (
        f"a tier skips instead of failing: {offenders}. A tier that skips when "
        f"the machine is missing something reports success having proved "
        f"nothing. Fail with a message naming the fix, as `tests/device/` does, "
        f"or add the file to `_MAY_SKIP` with the repository fact it turns on."
    )
