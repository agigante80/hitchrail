"""#124. The plugin update, one operation with an outcome per plugin.

Every case here runs against an injected runner, so no test starts a real
agent. The runner records each argv and its timeout and answers from a table
keyed by the argv's tail, which is what lets a case say "the second update
fails" without knowing how the operation builds the call.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from hitchrail import claude_ipc
from hitchrail.claude_ipc import PluginOutcome, PluginsFailed, update_plugins

SRC = Path(__file__).parent.parent / "src" / "hitchrail"

REFRESH = ["claude", "plugin", "marketplace", "update"]
LISTING = ["claude", "plugin", "list", "--json"]


def update_argv(plugin_id: str) -> list[str]:
    return ["claude", "plugin", "update", plugin_id, "-s", "user", "-y", "--json"]


def row(plugin_id: str, scope: str = "user") -> dict[str, object]:
    """A listing row in the shape 2.1.280 prints, extra keys and all."""
    return {
        "id": plugin_id,
        "scope": scope,
        "version": "1.0.0",
        "enabled": True,
        "installPath": f"/var/cache/agent/plugins/{plugin_id}",
        "installedAt": "2026-09-01T00:00:00Z",
        "lastUpdated": "2026-09-01T00:00:00Z",
    }


Answer = subprocess.CompletedProcess[str] | BaseException


class FakeAgent:
    """Answers by argv. Unlisted calls succeed with no output."""

    def __init__(self, listing: object = (), **answers: Answer) -> None:
        self.calls: list[tuple[list[str], float]] = []
        self.answers: dict[str, Answer] = dict(answers)
        text = listing if isinstance(listing, str) else json.dumps(list(listing))  # type: ignore[call-overload]
        self.answers.setdefault("list", done(stdout=text))

    def __call__(self, argv: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
        self.calls.append((argv, timeout))
        key = {
            "marketplace": "refresh",
            "list": "list",
        }.get(argv[2], argv[3] if argv[2] == "update" else argv[2])
        answer = self.answers.get(key, done())
        if isinstance(answer, BaseException):
            raise answer
        return answer

    @property
    def argvs(self) -> list[list[str]]:
        return [argv for argv, _ in self.calls]

    @property
    def updated(self) -> list[str]:
        return [argv[3] for argv in self.argvs if argv[2] == "update"]


def done(
    returncode: int = 0, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


def run(
    agent: FakeAgent, report: Callable[[PluginOutcome], None] | None = None
) -> list[PluginOutcome]:
    return update_plugins("claude", run=agent, report=report or (lambda _o: None))


def results(outcomes: list[PluginOutcome]) -> list[tuple[str, str, str]]:
    return [(o.plugin, o.scope, o.result) for o in outcomes]


# -- the argv, exactly -------------------------------------------------------


def test_the_calls_are_argument_lists_in_order() -> None:
    agent = FakeAgent([row("superpowers@x")])
    run(agent)
    assert agent.argvs == [REFRESH, LISTING, update_argv("superpowers@x")]


def test_every_call_has_a_finite_timeout() -> None:
    """Fails if 2 in the plan: a hung call must not hold the marker forever."""
    agent = FakeAgent([row("a@m"), row("b@m")])
    run(agent)
    assert agent.calls
    assert all(0 < timeout < float("inf") for _, timeout in agent.calls)


def test_the_binary_is_the_configured_one() -> None:
    agent = FakeAgent([row("a@m")])
    update_plugins("/opt/agent/bin/agent", run=agent, report=lambda _o: None)
    assert {argv[0] for argv in agent.argvs} == {"/opt/agent/bin/agent"}


# -- the ordinary run --------------------------------------------------------


def test_each_user_plugin_is_updated_once_in_listing_order() -> None:
    agent = FakeAgent([row("a@m"), row("b@m"), row("c@m")])
    outcomes = run(agent)
    assert agent.updated == ["a@m", "b@m", "c@m"]
    assert results(outcomes) == [
        ("a@m", "user", "updated"),
        ("b@m", "user", "updated"),
        ("c@m", "user", "updated"),
    ]


def test_each_outcome_is_reported_as_it_happens() -> None:
    """Part B streams these, so they must arrive one at a time, in order."""
    seen: list[str] = []
    agent = FakeAgent([row("a@m"), row("b@m")])

    def report(outcome: PluginOutcome) -> None:
        # By the time a plugin is reported, its own update has run and the
        # next one has not.
        seen.append(f"{outcome.plugin} after {len(agent.updated)}")

    run(agent, report)
    assert seen == ["a@m after 1", "b@m after 2"]


def test_no_plugins_is_an_empty_answer_not_a_failure() -> None:
    """A JSON list with nothing in it is a machine with no plugins."""
    agent = FakeAgent([])
    assert run(agent) == []
    assert agent.argvs == [REFRESH, LISTING]


# -- scopes -------------------------------------------------------------------


def test_other_scopes_are_counted_and_never_updated() -> None:
    """Fails if 3 in the plan. Six `local` rows are six projects' installs."""
    agent = FakeAgent(
        [
            row("a@m"),
            row("adapt@kit", "local"),
            row("adapt@kit", "local"),
            row("adapt@kit", "local"),
            row("cowork@synced", "synced"),
            row("b@m"),
        ]
    )
    outcomes = run(agent)
    assert agent.updated == ["a@m", "b@m"]
    assert all(argv[5] == "user" for argv in agent.argvs if argv[2] == "update")
    assert results(outcomes) == [
        ("a@m", "user", "updated"),
        ("adapt@kit", "local", "skipped"),
        ("adapt@kit", "local", "skipped"),
        ("adapt@kit", "local", "skipped"),
        ("cowork@synced", "synced", "skipped"),
        ("b@m", "user", "updated"),
    ]


def test_a_genuine_user_duplicate_is_updated_and_reported_once() -> None:
    agent = FakeAgent([row("a@m"), row("b@m"), row("a@m")])
    outcomes = run(agent)
    assert agent.updated == ["a@m", "b@m"]
    assert [o.plugin for o in outcomes] == ["a@m", "b@m"]


# -- one plugin fails ----------------------------------------------------------


def test_one_failure_does_not_stop_the_rest() -> None:
    agent = FakeAgent(
        [row("a@m"), row("b@m"), row("c@m"), row("d@m")],
        **{"b@m": done(1, stderr="fetch failed\nnetwork unreachable\n")},
    )
    outcomes = run(agent)
    assert agent.updated == ["a@m", "b@m", "c@m", "d@m"]
    assert results(outcomes) == [
        ("a@m", "user", "updated"),
        ("b@m", "user", "failed"),
        ("c@m", "user", "updated"),
        ("d@m", "user", "updated"),
    ]
    assert outcomes[1].detail == "exited 1: network unreachable"


def test_a_hung_update_is_a_failure_and_the_next_still_runs() -> None:
    agent = FakeAgent(
        [row("a@m"), row("b@m"), row("c@m")],
        **{"b@m": subprocess.TimeoutExpired(update_argv("b@m"), 1)},
    )
    outcomes = run(agent)
    assert agent.updated == ["a@m", "b@m", "c@m"]
    assert outcomes[1].result == "failed"
    assert outcomes[1].detail == "timed out"


def test_a_failure_detail_is_bounded() -> None:
    """The vendor's stderr reaches a phone screen; a megabyte must not."""
    agent = FakeAgent([row("a@m")], **{"a@m": done(2, stderr="x" * 10_000)})
    (outcome,) = run(agent)
    assert outcome.detail is not None
    assert len(outcome.detail) <= 240


# -- the operation fails ---------------------------------------------------------


def test_a_failed_refresh_updates_nothing() -> None:
    agent = FakeAgent([row("a@m")], refresh=done(1, stderr="offline"))
    with pytest.raises(PluginsFailed) as caught:
        run(agent)
    assert caught.value.code == "marketplace_refresh_failed"
    assert agent.argvs == [REFRESH]


def test_a_hung_refresh_updates_nothing() -> None:
    agent = FakeAgent([row("a@m")], refresh=subprocess.TimeoutExpired(REFRESH, 1))
    with pytest.raises(PluginsFailed) as caught:
        run(agent)
    assert caught.value.code == "marketplace_refresh_failed"
    assert agent.updated == []


@pytest.mark.parametrize(
    "listing",
    [
        "not json",
        "",
        json.dumps({"plugins": []}),
        json.dumps([{"name": "a"}]),
        json.dumps([{"id": 7, "scope": "user"}]),
        json.dumps([{"id": "a@m"}]),
        json.dumps(["a@m"]),
        # One good row beside a bad one is still a listing this code does not
        # understand: updating the subset it could parse is the fail open.
        json.dumps([row("a@m"), {"name": "b"}]),
    ],
    ids=[
        "text",
        "empty",
        "object",
        "no-id",
        "id-not-str",
        "no-scope",
        "strings",
        "one-bad-row",
    ],
)
def test_an_unreadable_listing_updates_nothing(listing: str) -> None:
    """Fails if 1 in the plan: never "0 updated" on a machine with plugins."""
    agent = FakeAgent(listing)
    with pytest.raises(PluginsFailed) as caught:
        run(agent)
    assert caught.value.code == "plugins_unreadable"
    assert agent.updated == []


def test_a_listing_that_times_out_is_unreadable() -> None:
    agent = FakeAgent(list=subprocess.TimeoutExpired(LISTING, 1))
    with pytest.raises(PluginsFailed) as caught:
        run(agent)
    assert caught.value.code == "plugins_unreadable"
    assert agent.updated == []


def test_a_listing_that_exits_non_zero_is_unreadable() -> None:
    agent = FakeAgent(list=done(1, stdout="[]"))
    with pytest.raises(PluginsFailed) as caught:
        run(agent)
    assert caught.value.code == "plugins_unreadable"


@pytest.mark.parametrize(
    "plugin_id",
    # `a\n` because `$` would accept it: the anchors are `\A` and `\Z`.
    ["--help", "-s", "a b", "a;b", "", "a\nb", "a\n", "é@m", "a" * 300],
)
def test_a_hostile_id_makes_the_whole_listing_unreadable(plugin_id: str) -> None:
    """An argv element cannot become a flag, but a flag-shaped id is still a
    listing this code does not understand, and nothing is updated."""
    agent = FakeAgent([row("a@m"), row(plugin_id)])
    with pytest.raises(PluginsFailed) as caught:
        run(agent)
    assert caught.value.code == "plugins_unreadable"
    assert agent.updated == []


@pytest.mark.parametrize("scope", ["", "USER", "us er", "-s", "user\n", "x" * 100])
def test_a_hostile_scope_makes_the_listing_unreadable(scope: str) -> None:
    agent = FakeAgent([row("a@m", scope)])
    with pytest.raises(PluginsFailed) as caught:
        run(agent)
    assert caught.value.code == "plugins_unreadable"


@pytest.mark.parametrize("error", [FileNotFoundError(), PermissionError()])
def test_a_missing_agent_spawns_nothing_further(error: OSError) -> None:
    agent = FakeAgent([row("a@m")], refresh=error)
    with pytest.raises(PluginsFailed) as caught:
        run(agent)
    assert caught.value.code == "agent_missing"
    assert agent.argvs == [REFRESH]


def test_the_agent_vanishing_mid_run_is_agent_missing() -> None:
    """Uninstalled between the listing and an update: what ran is reported
    through `report`, and the operation fails rather than calling each
    remaining plugin `failed` with the same cause."""
    seen: list[PluginOutcome] = []
    agent = FakeAgent([row("a@m"), row("b@m"), row("c@m")], **{"b@m": FileNotFoundError()})
    with pytest.raises(PluginsFailed) as caught:
        run(agent, seen.append)
    assert caught.value.code == "agent_missing"
    assert [o.plugin for o in seen] == ["a@m"]
    assert agent.updated == ["a@m", "b@m"]


# -- what -y approved ----------------------------------------------------------


def test_the_command_y_approved_is_carried_in_the_outcome() -> None:
    line = json.dumps(
        {"shownCommand": {"command": "curl -s https://x/install", "sha256": "ab"}}
    )
    agent = FakeAgent([row("a@m")], **{"a@m": done(0, stdout=f"{line}\n")})
    (outcome,) = run(agent)
    assert outcome.result == "updated"
    assert outcome.approved_command == "curl -s https://x/install"


@pytest.mark.parametrize(
    "stdout",
    [
        "",
        "Updated a@m to 1.2.0\n",
        "{not json",
        json.dumps({"shownCommand": 7}),
        json.dumps([1]),
    ],
)
def test_an_update_without_that_field_is_still_updated(stdout: str) -> None:
    agent = FakeAgent([row("a@m")], **{"a@m": done(0, stdout=stdout)})
    (outcome,) = run(agent)
    assert outcome.result == "updated"
    assert outcome.approved_command is None


# -- the real runner -------------------------------------------------------------


def test_the_real_runner_withholds_what_it_is_told_to(tmp_path: Path) -> None:
    """#113 for the plugin path. A marketplace's install command runs with
    this process's environment, and `-y` approves it unseen, so the token
    must not be in it."""
    runner = claude_ipc.plugin_runner(withhold=("HITCHRAIL_TEST_SECRET",))
    os.environ["HITCHRAIL_TEST_SECRET"] = "s3cret"
    try:
        result = runner(["env"], 10)
    finally:
        del os.environ["HITCHRAIL_TEST_SECRET"]
    assert "HITCHRAIL_TEST_SECRET" not in result.stdout
    assert "PATH=" in result.stdout


def test_the_real_runner_runs_in_the_home_directory() -> None:
    """Not wherever `hitchrail` happened to be started: the vendor resolves a
    project scope from the working directory, so the listing would otherwise
    depend on the operator's shell."""
    result = claude_ipc.plugin_runner(withhold=())(["pwd"], 10)
    assert result.stdout.strip() == str(Path.home())


def test_the_real_runner_gives_the_child_no_terminal_to_ask_on() -> None:
    """Under `hitchrail update-plugins` stdin is the operator's terminal, and
    a child that prompts on it would wait for an answer nobody expects to
    give. A closed stdin reads as end of file at once."""
    runner = claude_ipc.plugin_runner(withhold=())
    result = runner(["cat"], 10)
    assert result.returncode == 0
    assert result.stdout == ""


# -- the quarantine ---------------------------------------------------------------


def _string_constants(path: Path) -> set[str]:
    """Every string literal in a module, docstrings and comments excluded.

    The structure, not a grep, for the reason [[guards fail on their own
    explanation]]: a text search for `"--json"` matches the comment that
    forbids it.
    """
    tree = ast.parse(path.read_text())
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    }


def test_the_plugin_vocabulary_lives_only_in_the_quarantine() -> None:
    """Fails if 4 in the plan. `lint-imports` cannot see a string."""
    # `-s` is not in the set: tmux uses it for its own socket and session
    # flags, so it names nothing vendor specific outside this module.
    vocabulary = {"plugin", "marketplace", "--json", "-y", "shownCommand"}
    assert vocabulary <= _string_constants(SRC / "claude_ipc.py"), (
        "the quarantine no longer holds this vocabulary, so this guard checks nothing"
    )
    leaked = {
        p.name: sorted(vocabulary & _string_constants(p))
        for p in SRC.glob("*.py")
        if p.name != "claude_ipc.py" and vocabulary & _string_constants(p)
    }
    assert leaked == {}, f"plugin vocabulary outside the quarantine: {leaked}"
