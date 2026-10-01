"""Does the source keep the boundaries no type checker or linter can see?

Each test here reads `src/` as text or as an AST: the import seams, the
environment variables a spawn scrubs, and the one resolved read of the agent
binary.
"""

from __future__ import annotations

import ast
import tomllib
from collections import Counter
from pathlib import Path

import pytest

from support import in_claude_ipc, module_name, source_modules

# -- #18: the seam holds ---------------------------------------------------


def test_hostnames_does_not_import_config() -> None:
    """The dependency runs one way, which is what makes this a seam.

    `config` imports `hostnames`. If `hostnames` ever imports `config` back,
    the split stops being a seam and becomes a cut through a cycle, and the
    next person to tidy up will reasonably merge them again.
    """
    source = (Path(__file__).parent.parent / "src" / "hitchrail" / "hostnames.py").read_text()
    assert "import config" not in source
    assert "from hitchrail.config" not in source
    assert "from .config" not in source


def test_the_import_contract_covers_every_engine_layer_module() -> None:
    """A new module is unguarded until somebody remembers to list it.

    `lint-imports` checks the modules it is given and says nothing about the
    ones it is not, so it passes just as loudly with a gap in it. Splitting
    `derive` out of `engine` at #50 opened exactly that gap: the new module
    could have imported Starlette and the contract would still have reported
    "1 kept, 0 broken".

    The web layer is the exception list below, and it is spelled out rather
    than inferred, so adding a module to it is a deliberate act.
    """
    web = {"server.py", "pages.py", "cli.py", "security.py", "headers.py", "__init__.py"}
    modules = source_modules()
    assert any(in_claude_ipc(rel) for rel in modules), "the walk saw no claude_ipc module"
    engine_layer = {module_name(rel) for rel in modules if rel not in web}
    contract = tomllib.loads(
        (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text()
    )["tool"]["importlinter"]["contracts"][0]
    listed = set(contract["source_modules"])
    # A submodule is covered by its package's entry: import-linter's forbidden
    # contracts include descendants unless told otherwise (#368).
    missing = {
        m for m in engine_layer - listed if not any(m.startswith(f"{pkg}.") for pkg in listed)
    }
    assert not missing, (
        f"engine layer modules outside the import contract: {sorted(missing)}. "
        "Add them to `source_modules` in pyproject.toml, or to `web` here if "
        "they are genuinely part of the web layer."
    )


def test_every_environment_variable_the_product_reads_is_scrubbed() -> None:
    """#203. The fixtures describe an empty machine, and the environment was
    the one surface that rule was not applied to.

    `JOURNAL_STREAM` was scrubbed at #110 and `HITCHRAIL_TOKEN` was not, so
    four `test_cli.py` tests failed on every machine that runs Hitchrail and
    passed in CI. Scrubbing the second one fixes today. This is what stops the
    third: a new read of the environment fails here until somebody decides
    whether the suite should inherit it.

    `ast`, not a grep. A grep for `os.environ` matches this docstring, which is
    the failure mode `test_the_engine_never_iterates_the_stop_keys` already
    documents about greps that describe what they forbid.
    """
    read: dict[str, str] = {}
    modules = source_modules()
    assert any(in_claude_ipc(rel) for rel in modules), "the walk saw no claude_ipc module"
    for rel, path in modules.items():
        tree = ast.parse(path.read_text())
        # `ast.walk`, not `tree.body`: these live inside functions.
        for node in ast.walk(tree):
            # os.environ.get("X") and os.getenv("X")
            if isinstance(node, ast.Call) and node.args:
                target = ast.unparse(node.func)
                if target in {"os.environ.get", "os.getenv"}:
                    first = node.args[0]
                    read[ast.unparse(first)] = rel
            # "X" in os.environ
            if (
                isinstance(node, ast.Compare)
                and isinstance(node.ops[0], ast.In)
                and ast.unparse(node.comparators[0]) == "os.environ"
            ):
                read[ast.unparse(node.left)] = rel

    # Guard the guard. If the parser stops matching, every assertion below is
    # vacuously true and the next variable walks straight past it.
    assert read, (
        "the parser found no environment reads at all, which means it has "
        "stopped matching rather than that the product stopped reading"
    )

    # The names as they appear in the source, which is how they are written in
    # `conftest.AMBIENT_ENV` too. A literal string here would pass while the
    # constant it duplicates drifted.
    scrubbed = {"TOKEN_ENV", "JOURNAL_ENV", "CONFIG_HOME_ENV"}
    unscrubbed = {name: where for name, where in read.items() if name not in scrubbed}
    assert not unscrubbed, (
        f"environment variables read by the product and not scrubbed by "
        f"`conftest.no_ambient_environment`: {unscrubbed}. Add them to "
        f"`AMBIENT_ENV`, or to `scrubbed` here with the reason the suite "
        f"should inherit the developer's value."
    )


# -- Phase 22 batch 1, #302/#196/#298: one resolved agent binary ------------


class _FunctionScopedAttributeReads(ast.NodeVisitor):
    """Every `ast.Attribute` read (`Load` context) whose name is `attr`,
    tagged with the name of the function it is lexically inside.

    Keyed by the immediate enclosing function rather than the line number
    (#298 batch 1 review), because a line number allowlist is invalidated by
    an unrelated edit two lines above it and nobody notices until the guard
    it protects has already gone quiet. A nested function, such as
    `server.py`'s `_config_view` inside `create_app`, is its OWN scope: the
    outer function's name would let every closure inside it read the raw
    setting once one legitimate read anywhere in `create_app` was allowed.
    """

    def __init__(self, attr: str) -> None:
        self.attr = attr
        self.hits: list[tuple[str, int, str]] = []
        self._stack: list[str] = ["<module>"]

    def _scope(self, node: ast.AST, name: str) -> None:
        self._stack.append(name)
        self.generic_visit(node)
        self._stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._scope(node, node.name)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._scope(node, node.name)

    # A lambda, a comprehension and a class body are scopes of their own
    # (#347): tagged with the enclosing function's name, a lambda written
    # inside an exempt function inherited that function's exemption.
    def visit_Lambda(self, node: ast.Lambda) -> None:
        self._scope(node, "<lambda>")

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._scope(node, node.name)

    def visit(self, node: ast.AST) -> None:
        if isinstance(node, ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp):
            self._scope(node, f"<{type(node).__name__.lower()}>")
        else:
            super().visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr == self.attr and isinstance(node.ctx, ast.Load):
            self.hits.append((self._stack[-1], node.lineno, ast.unparse(node)))
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        """`getattr(config, "agent_binary")` and
        `operator.attrgetter("agent_binary")` read the attribute without an
        `ast.Attribute` node (#347), so a name given as a string constant to
        either is a read too. A dotted `attrgetter("config.agent_binary")`
        counts, since its last part is the attribute read."""
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
        if name in {"getattr", "attrgetter"}:
            for arg in node.args:
                value = arg.value if isinstance(arg, ast.Constant) else None
                if isinstance(value, str) and value.rsplit(".", 1)[-1] == self.attr:
                    self.hits.append((self._stack[-1], node.lineno, ast.unparse(node)))
        self.generic_visit(node)


def test_every_read_of_agent_binary_is_the_resolved_property_or_allowlisted() -> None:
    """#196's premortem, widened after the round 1 finding on this guard
    itself: the first version only flagged `.agent_binary` passed directly
    as the first argument to `claude_ipc.launch_argv` or
    `claude_ipc.update_plugins`, so `server.py`'s plugin route, which goes
    through `plugin_runs.operation_for(...)` rather than calling
    `claude_ipc.update_plugins` itself, could revert to
    `operation_for(config.agent_binary)` and pass every test in this file.

    So this flags ANY read of the `agent_binary` attribute anywhere in
    `src/hitchrail`, on any object, `Config` included, and allows only the
    handful that are legitimately reading the OPERATOR'S raw setting rather
    than what preflight resolved: the one shape check, preflight's own
    lookup, the CLI's own re-check before it spawns the update directly, the
    Config built from argparse's `args.agent_binary` (also named
    `agent_binary`, since the attribute name is what this guard matches, not
    the object it lives on), `cli.main` threading `Preflight.agent_binary`
    through, and the settings page showing the operator what they typed.
    Every other read must go through `.spawn_agent_binary` instead.

    #345, round 2 of batch 1's review: keyed by (module, function) alone,
    `("cli.py", "main")` allowed EVERY read anywhere in `main`, not only the
    one line 802 that threads `found.agent_binary` through, so a raw spawn
    added anywhere else in that function passed silently
    (`claude_ipc.launch_argv(config.agent_binary, ...)`, verified on a
    scratch copy). Keyed by the exact expression `ast.unparse` reads too, so
    only that one line is exempt and a second read in the same function is
    caught like any other offender.
    """
    # Each entry carries how many reads it exempts (#358): an entry exempts
    # that many occurrences of its expression in its function, not every one,
    # so a second raw read beside an allowed one fails like any other. And
    # the count is exact both ways, so an entry whose read was removed is
    # reported as stale rather than left waiting to exempt the next one.
    allowed: dict[tuple[str, str, str], int] = {
        # The one shape check itself (#302): normalises and validates the
        # operator's raw value before anything is derived from it.
        ("config.py", "__post_init__", "self.agent_binary"): 1,
        # `spawn_agent_binary` IS the safe read every spawn site must use
        # instead; its own fallback to the raw field, for a Config built
        # outside `cli.main`, is what it exists to hold in one place.
        ("config.py", "spawn_agent_binary", "self.agent_binary"): 1,
        # Builds a Config from the operator's own flags: `args.agent_binary`
        # is what they typed, becoming `Config.agent_binary`, not a spawn.
        ("cli.py", "build_config", "args.agent_binary"): 1,
        # What preflight is resolving. This function's whole job is finding
        # the absolute path from the raw name: one lookup, one `dirname`, and
        # three messages quoting what the operator typed (#341).
        ("cli.py", "preflight", "config.agent_binary"): 5,
        # `hitchrail update-plugins`: no Config exists yet, so this resolves
        # and checks its OWN copy of the raw `--agent-binary` flag before it
        # ever calls `claude_ipc.update_plugins` with the resolved value.
        ("cli.py", "update_plugins_command", "args.agent_binary"): 1,
        # Threads `Preflight.agent_binary`, the field preflight resolved,
        # into `Config.resolved_agent_binary`. `Preflight` is a different
        # object from `Config`, but the attribute name is the same string,
        # which is exactly why this guard cannot key on the object either.
        ("cli.py", "main", "found.agent_binary"): 1,
        # The startup block (#167) prints what the operator typed beside
        # what it resolved to, `spawn_agent_binary`, so a journal shows both.
        # A display, never a spawn.
        ("cli.py", "startup_block", "config.agent_binary"): 1,
        # The settings page shows the operator's raw setting, with `source`
        # saying where it came from; showing the resolved absolute path here
        # while `source` still said "default" would misrepresent provenance.
        ("server.py", "_config_view", "config.agent_binary"): 1,
    }

    offenders: dict[str, str] = {}
    seen: Counter[tuple[str, str, str]] = Counter()
    found_a_read = False
    modules = source_modules()
    assert any(in_claude_ipc(rel) for rel in modules), "the walk saw no claude_ipc module"
    for rel, path in modules.items():
        finder = _FunctionScopedAttributeReads("agent_binary")
        finder.visit(ast.parse(path.read_text()))
        for func, lineno, text in finder.hits:
            found_a_read = True
            key = (rel, func, text)
            seen[key] += 1
            if seen[key] > allowed.get(key, 0):
                offenders[f"{rel}:{lineno} ({func})"] = text
    stale = {key: (count, seen[key]) for key, count in allowed.items() if seen[key] < count}

    # Guard the guard, the same way test_every_environment_variable... does:
    # if the parser stops matching at all, every assertion below is
    # vacuously true.
    assert found_a_read, (
        "the parser found no read of .agent_binary anywhere, which means it "
        "has stopped matching rather than that nothing reads it any more"
    )
    assert not offenders, (
        f"a read of the raw, unresolved agent binary outside the allowlist: "
        f"{offenders}. Read `config.spawn_agent_binary` instead, so this runs "
        f"the exact file `cli.preflight` checked; if this read is genuinely "
        f"the operator's raw setting rather than a spawn site, add it to "
        f"`allowed` above with the reason."
    )
    assert not stale, (
        f"allowlist entries exempting more reads than exist, as (allowed, "
        f"found): {stale}. Lower each count to what is there, so the spare "
        f"exemption cannot quietly admit the next raw read."
    )


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        # #347: neither is an `ast.Attribute`, and both read the field.
        (
            "def f(c):\n    return getattr(c, 'agent_binary')",
            ("f", "getattr(c, 'agent_binary')"),
        ),
        (
            "def f(c):\n    return operator.attrgetter('config.agent_binary')(c)",
            ("f", "operator.attrgetter('config.agent_binary')"),
        ),
        # #347: a lambda inside an exempt function is its own scope, so it
        # cannot borrow that function's exemption.
        ("def preflight(c):\n    g = lambda: c.agent_binary", ("<lambda>", "c.agent_binary")),
        (
            "def preflight(cs):\n    [c.agent_binary for c in cs]",
            ("<listcomp>", "c.agent_binary"),
        ),
    ],
    ids=["getattr", "attrgetter", "lambda", "comprehension"],
)
def test_the_agent_binary_guard_sees_reads_that_are_not_plain_attributes(
    source: str, expected: tuple[str, str]
) -> None:
    finder = _FunctionScopedAttributeReads("agent_binary")
    finder.visit(ast.parse(source))
    assert [(func, text) for func, _, text in finder.hits] == [expected]


def test_the_agent_binary_guard_ignores_other_names_given_as_strings() -> None:
    """The negative half: `getattr` of another field is not a read of this one."""
    finder = _FunctionScopedAttributeReads("agent_binary")
    finder.visit(ast.parse("def f(c):\n    return getattr(c, 'spawn_agent_binary')"))
    assert finder.hits == []


def test_tmuxnames_does_not_import_the_adapter() -> None:
    """#93. The dependency runs one way, the third time this seam is cut.

    `tmux` imports `tmuxnames` for `sanitize` and `BINARY`. If the vocabulary
    ever imports the adapter back, the split stops being a seam and becomes a
    cut through a cycle, and the next person to tidy up will reasonably merge
    them again.

    **The point is not tidiness.** `tmuxnames` holds pure functions over strings
    and `lint-imports` cannot express "and no subprocess", so this is what stops
    the vocabulary acquiring one: a module that cannot import the adapter cannot
    borrow its runner.
    """
    import ast

    source = (Path(__file__).parent.parent / "src" / "hitchrail" / "tmuxnames.py").read_text()
    # **Parsed imports, never the file text.** The first version of this asserted
    # `"subprocess" not in source` and failed on the module docstring, which says
    # "No subprocess, no state, no server". That is the fourth time in this
    # repository that a guard has matched the sentence explaining the thing it
    # forbids, and the only way to make the text version pass is to delete the
    # explanation. Read what the module IMPORTS.
    imported = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[-1] if node.level == 0 else node.module)
    assert "tmux" not in imported, "the vocabulary imports the adapter, so the seam is a cycle"
    assert "subprocess" not in imported, (
        "the name vocabulary imports subprocess, which is the thing the split exists to prevent"
    )


def test_projectnames_does_not_import_config() -> None:
    """The dependency runs one way, the same seam `hostnames` has.

    `config` imports `projectnames` for #48. If `projectnames` ever imports
    `config` back, the split stops being a seam and becomes a cut through a
    cycle, and the next person to tidy up will reasonably merge them.
    """
    source = (
        Path(__file__).parent.parent / "src" / "hitchrail" / "projectnames.py"
    ).read_text()
    assert "import config" not in source
    assert "from hitchrail.config" not in source
    assert "from .config" not in source
