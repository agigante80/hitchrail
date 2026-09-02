"""State derivation: four states from two independent scans.

#40 was not split, so these tests carry the weight a second reviewer would
have. They are organised around the ways the algorithm can be WRONG rather than
around its happy path: every cell of the state matrix, both directions of
orphan attribution, and the assumptions the derivation makes about its
neighbours.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from conftest import (
    DIRTY_INPUT_BOX,
    FakeClock,
    FakeTmux,
    ScriptedProcs,
    procs_from,
    ps_row,
)
from hitchrail import discovery
from hitchrail.claude_ipc import GRACEFUL_STOP_KEYS, launch_argv
from hitchrail.config import Config
from hitchrail.engine import (
    AlreadyRunning,
    Engine,
    Locked,
    MachineUnreadable,
    MemoryNeedsAck,
    MemoryRefused,
    NotRunning,
    Protected,
    StartFailed,
    State,
    StopRefused,
    UnknownProject,
)
from hitchrail.procs import ProcTable
from hitchrail.tmux import Tmux, TmuxUnavailable

PANE = 500
AGENT = 501
HELPER = 502
ORPHAN = 900


# The four machines, named once and reused by the parametrised state tests, so
# a row reads as the SITUATION it describes rather than as a wall of columns.
Machine = tuple[dict[str, int], str]

RUNNING_MACHINE: Machine = (
    {"vessel": PANE},
    ps_row(PANE, 1) + ps_row(AGENT, PANE, project="vessel"),
)
STALE_MACHINE: Machine = ({"vessel": PANE}, ps_row(PANE, 1))
DETACHED_MACHINE: Machine = ({}, ps_row(ORPHAN, 1, project="vessel"))
STOPPED_MACHINE: Machine = ({}, "")


@pytest.fixture
def root(tmp_path: Path) -> Path:
    for name in ("vessel", "vessel-social", "a", "ab", "dotted.site"):
        (tmp_path / name).mkdir()
    return tmp_path


def engine_for(
    root: Path,
    *,
    sessions: dict[str, int] | None = None,
    table: str = "",
    procs_fn: Callable[[], ProcTable] | None = None,
    self_project: str | None = None,
) -> tuple[Engine, FakeTmux]:
    tmux = FakeTmux(sessions=sessions)
    # Pinned INSIDE the temporary root. Without it `Config` defaults to
    # ~/.claude/sessions, and `bridge_url` reads the developer's real session
    # files: verified opening /home/<user>/.claude/sessions/501.json during a
    # running derivation. That breaks the hermetic rule outright, and it makes
    # the suite's result depend on whose home directory ran it and on pid
    # collisions with real sessions.
    sessions_dir = root / ".sessions"
    sessions_dir.mkdir(exist_ok=True)
    config = Config(root=root, self_project=self_project, sessions_dir=sessions_dir)
    return (
        Engine(
            config,
            tmux=tmux,
            procs_fn=procs_fn or procs_from(table),
            meminfo_fn=lambda: "MemAvailable: 8388608 kB\n",
        ),
        tmux,
    )


def state_of(engine: Engine, name: str) -> State:
    return engine.get(name).state


# -- 1. the state matrix, exhaustively -------------------------------------


def test_running_when_the_pane_owns_an_agent(root: Path) -> None:
    table = ps_row(PANE, 1) + ps_row(AGENT, PANE, project="vessel")
    engine, _ = engine_for(root, sessions={"vessel": PANE}, table=table)
    session = engine.get("vessel")
    assert session.state is State.RUNNING
    assert session.pid == AGENT


def test_stale_when_the_pane_holds_nothing(root: Path) -> None:
    """A tmux session outlived its agent. Not stopped: the shell is still there."""
    engine, _ = engine_for(root, sessions={"vessel": PANE}, table=ps_row(PANE, 1))
    assert state_of(engine, "vessel") is State.STALE


def test_stale_when_the_only_agent_belongs_to_another_pane(root: Path) -> None:
    """The cell a diagonal test list misses.

    An agent exists, but in somebody else's pane. Reporting `running` here
    would attribute a live agent to a project that has none.
    """
    table = ps_row(PANE, 1) + ps_row(600, 1) + ps_row(AGENT, 600, project="vessel-social")
    engine, _ = engine_for(root, sessions={"vessel": PANE, "vessel-social": 600}, table=table)
    assert state_of(engine, "vessel") is State.STALE
    assert state_of(engine, "vessel-social") is State.RUNNING


def test_detached_is_not_stopped(root: Path) -> None:
    """The state a naive implementation gets wrong, and the reason derivation
    runs in two directions.

    A tool that only asks tmux reports an agent that outlived its terminal as
    stopped, and then invites you to start a second one in the same folder.
    """
    engine, _ = engine_for(root, table=ps_row(ORPHAN, 1, project="vessel"))
    session = engine.get("vessel")
    assert session.state is State.DETACHED
    assert session.pid == ORPHAN, "detached must be surfaced WITH its pid"


def test_another_projects_orphan_does_not_make_us_detached(root: Path) -> None:
    engine, _ = engine_for(root, table=ps_row(ORPHAN, 1, project="vessel-social"))
    assert state_of(engine, "vessel") is State.STOPPED


def test_stopped_when_there_is_neither(root: Path) -> None:
    engine, _ = engine_for(root)
    assert state_of(engine, "vessel") is State.STOPPED


# -- 2. attribution: the failure that looks like success -------------------


def test_an_orphan_for_a_is_not_attributed_to_ab(root: Path) -> None:
    """The tmux prefix footgun, one layer up.

    `--remote-control ab` must not satisfy a lookup for `a`. Getting this wrong
    shows a healthy project as detached and offers to kill somebody else's
    agent.
    """
    engine, _ = engine_for(root, table=ps_row(ORPHAN, 1, project="ab"))
    assert state_of(engine, "a") is State.STOPPED
    assert state_of(engine, "ab") is State.DETACHED


def test_an_orphan_for_ab_is_not_attributed_to_a(root: Path) -> None:
    """The mirror, because asymmetric matching passes one way and fails the
    other, which is exactly how the FQDN root dot shipped."""
    engine, _ = engine_for(root, table=ps_row(ORPHAN, 1, project="a"))
    assert state_of(engine, "ab") is State.STOPPED
    assert state_of(engine, "a") is State.DETACHED


def test_two_orphans_go_to_their_own_projects(root: Path) -> None:
    table = ps_row(900, 1, project="a") + ps_row(901, 1, project="ab")
    engine, _ = engine_for(root, table=table)
    assert engine.get("a").pid == 900
    assert engine.get("ab").pid == 901


def test_an_orphan_whose_project_no_longer_exists_is_ignored(root: Path) -> None:
    """The folder was deleted while an agent ran. It appears in no listing and
    nothing crashes."""
    engine, _ = engine_for(root, table=ps_row(ORPHAN, 1, project="deleted-folder"))
    assert all(s.state is State.STOPPED for s in engine.list())


# -- 3. the coupling nobody would notice breaking --------------------------


def test_attribution_matches_what_launch_argv_actually_produces(root: Path) -> None:
    """`_find_detached` works only while the project name is the LAST element.

    Append a flag after it and every detached agent becomes invisible,
    silently, with no other test failing. This builds the row from
    `launch_argv` itself so a reorder breaks the test instead of the feature.
    """
    argv = launch_argv("claude", "vessel")
    assert argv[-1] == "vessel", "attribution depends on the project name being last"
    engine, _ = engine_for(root, table=ps_row(ORPHAN, 1, args=" ".join(argv)))
    assert state_of(engine, "vessel") is State.DETACHED


@pytest.mark.parametrize(
    "args",
    [
        "grep -r --remote-control vessel",
        "vim notes.txt --remote-control vessel",
        "less /var/log/thing --remote-control vessel",
        "echo --remote-control vessel",
    ],
)
def test_an_unrelated_process_is_not_a_detached_agent(root: Path, args: str) -> None:
    """Matching the marker and the name alone claimed any process mentioning both.

    `grep -r --remote-control vessel` derived as a detached agent. That is not
    a cosmetic mislabel: a detached row refuses to start, and a kill has no
    tmux session to kill, so **the project stays unstartable until that
    unrelated process exits**.

    The fix compares the whole argv tail from `launch_argv`, which also keeps
    the flags inside the quarantine rather than spelling them here.
    """
    engine, _ = engine_for(root, table=ps_row(ORPHAN, 1, args=args))
    assert state_of(engine, "vessel") is State.STOPPED


def test_a_real_agent_is_still_detached_after_that_tightening(root: Path) -> None:
    """The positive case, without which refusing everything would pass."""
    engine, _ = engine_for(root, table=ps_row(ORPHAN, 1, project="vessel"))
    assert state_of(engine, "vessel") is State.DETACHED


# #84: the wrapper we spawn through carries the whole agent argv as its own.


# The shape seen on the development machine on 2026-09-02: a tmux server whose
# argv ends with the entire command line of the session it was started for, and
# the agent itself one pid later as its child. The server was 14041 and the
# agent 14042, and every row on that machine but one was correct, because only
# the first session's command line survives as the server's argv.
TMUX_SERVER = 800


def _server_args(project: str, socket: str | None = None) -> str:
    """A tmux server's argv, built from `launch_argv` like every other row.

    Pasting the agent half would let a reorder of `launch_argv` pass this test
    while the real server's argv changed shape underneath it.
    """
    flags = ["-S", socket] if socket else []
    return " ".join(
        [
            "tmux",
            *flags,
            "new-session",
            "-d",
            "-s",
            f"hr-{project}",
            "-c",
            f"/root/{project}",
            *launch_argv("claude", project),
        ]
    )


def test_the_tmux_server_is_not_a_detached_agent(root: Path) -> None:
    """#84, observed on a real machine with 52 projects.

    `tmux new-session ... claude --dangerously-skip-permissions --remote-control X`
    stays as the SERVER's own argv for as long as the server lives, so it ends
    with the exact suffix the orphan scan matches. The project whose session
    was started first then reports the server's pid, RSS and uptime as if they
    were the agent's, and `ram_mb` feeds the start guard's memory decision.
    """
    engine, _ = engine_for(root, table=ps_row(TMUX_SERVER, 1, args=_server_args("vessel")))
    assert state_of(engine, "vessel") is State.STOPPED


def test_the_agent_is_reported_rather_than_the_server_that_spawned_it(root: Path) -> None:
    """The observed shape entire: both rows present, parent and child.

    Asserting only that the server is refused would pass against a scan that
    refused everything, and this is the half that says which pid a row shows.
    """
    table = ps_row(TMUX_SERVER, 1, args=_server_args("vessel")) + ps_row(
        ORPHAN, TMUX_SERVER, project="vessel"
    )
    engine, _ = engine_for(root, table=table)
    session = engine.get("vessel")
    assert session.state is State.DETACHED
    assert session.pid == ORPHAN, "the row must show the agent, not the server above it"


def test_a_tmux_server_on_a_private_socket_is_refused_too(root: Path) -> None:
    """`-S` sits between the binary and the subcommand, which is where a check
    anchored on `tmux new-session` as one string stops working. The e2e and
    live_tmux tiers both run this shape, so it is the one our own suite makes."""
    engine, _ = engine_for(
        root,
        table=ps_row(TMUX_SERVER, 1, args=_server_args("vessel", socket="/run/user/1000/hr/s")),
    )
    assert state_of(engine, "vessel") is State.STOPPED


def test_the_server_is_refused_even_with_no_agent_left_under_it(root: Path) -> None:
    """The case the parent/child relationship cannot rescue.

    Once the first session's agent exits, the server keeps that command line
    and there is no child to prefer over it. Anything that merely preferred the
    descendant would report the server here, which is the state a long lived
    server spends most of its life in.
    """
    engine, _ = engine_for(root, table=ps_row(TMUX_SERVER, 1, args=_server_args("vessel")))
    assert engine.get("vessel").pid is None


def test_the_binary_does_not_influence_the_match(root: Path) -> None:
    """A MISMATCH, because the same binary on both sides proves nothing.

    `[1:]` strips the binary from the suffix, so the match is deliberately
    binary independent: an operator who changes `--agent-binary` between
    starting an agent and restarting Hitchrail must not blind the orphan scan,
    and neither must an `env` wrapper putting something else at argv[0].

    An earlier version of this test passed the SAME binary on both sides and
    claimed the opposite, that the configured binary shapes the suffix.
    Mutating `self.config.agent_binary` to a literal, and `[1:]` to `[0:]`,
    both left it green.
    """
    tmux = FakeTmux()
    sessions_dir = root / ".sessions"
    sessions_dir.mkdir(exist_ok=True)
    # Configured with one binary; the running agent was started with another.
    config = Config(root=root, agent_binary="/opt/new-claude", sessions_dir=sessions_dir)
    argv = launch_argv("/usr/bin/old-claude", "vessel")
    engine = Engine(
        config,
        tmux=tmux,
        procs_fn=procs_from(ps_row(ORPHAN, 1, args=" ".join(argv))),
        meminfo_fn=lambda: "MemAvailable: 8388608 kB\n",
    )
    assert engine.get("vessel").state is State.DETACHED


# -- 4. tree walking, not child walking ------------------------------------


def test_a_grandchild_agent_is_found(root: Path) -> None:
    """A shell sits between the pane and the agent, which is the normal shape.

    `children()` would miss it and report `stale` for a running project.
    """
    table = (
        ps_row(PANE, 1)
        + ps_row(HELPER, PANE, args="bash")
        + ps_row(AGENT, HELPER, project="vessel")
    )
    engine, _ = engine_for(root, sessions={"vessel": PANE}, table=table)
    assert state_of(engine, "vessel") is State.RUNNING


def test_an_agent_inside_someone_elses_pane_is_not_detached(root: Path) -> None:
    """An exit criterion, and the case `owned` actually guards.

    Project `vessel` has NO tmux session, but an agent bearing its name runs as
    a grandchild of project `ab`'s pane: somebody started it by hand in the
    wrong window. It is owned by a pane of ours, so it is not an orphan, and
    reporting `vessel` as `detached` would offer to adopt a process that
    already has a home.

    A first version of this test gave `vessel` its own pane, which made
    derivation return `running` before the orphan scan ever ran, so it passed
    with `owned` reduced to bare pane pids and proved nothing about it.
    """
    table = (
        ps_row(PANE, 1)
        + ps_row(HELPER, PANE, args="bash")
        + ps_row(AGENT, HELPER, project="vessel")
    )
    engine, _ = engine_for(root, sessions={"ab": PANE}, table=table)
    assert state_of(engine, "vessel") is State.STOPPED
    assert not any(s.state is State.DETACHED for s in engine.list())


def test_an_agent_in_our_own_pane_is_never_also_detached(root: Path) -> None:
    """The straightforward half: it is running, and detached nowhere."""
    table = (
        ps_row(PANE, 1)
        + ps_row(HELPER, PANE, args="bash")
        + ps_row(AGENT, HELPER, project="vessel")
    )
    engine, _ = engine_for(root, sessions={"vessel": PANE}, table=table)
    assert state_of(engine, "vessel") is State.RUNNING
    assert not any(s.state is State.DETACHED for s in engine.list())


def test_a_cyclic_process_table_does_not_hang_derivation(root: Path) -> None:
    table = "2 3 10 10 a\n3 2 10 10 b\n" + ps_row(PANE, 1)
    engine, _ = engine_for(root, sessions={"vessel": PANE}, table=table)
    assert state_of(engine, "vessel") is State.STALE


# -- 5. names that are not what tmux stored --------------------------------


def test_a_project_needing_sanitizing_is_still_derived(root: Path) -> None:
    """A derivation that looks up the RAW name finds nothing and reports
    stopped while the agent runs."""
    table = ps_row(PANE, 1) + ps_row(AGENT, PANE, project="dotted.site")
    engine, _ = engine_for(root, sessions={"dotted.site": PANE}, table=table)
    assert state_of(engine, "dotted.site") is State.RUNNING


# -- 6. the two empty results, which are not the same ----------------------


def test_a_failed_ps_raises_rather_than_reporting_everything_stopped(root: Path) -> None:
    """`ProcTable.ok` is False, so the machine could not be read.

    Reporting every project as stopped would tell the user something false
    about their machine, which is a guard failing open. The design answers it:
    if a state cannot be determined, say so rather than guessing. An error, not
    a fifth state.
    """
    from conftest import failing_procs

    engine, _ = engine_for(root, procs_fn=failing_procs)
    with pytest.raises(MachineUnreadable):
        engine.list()
    with pytest.raises(MachineUnreadable):
        engine.get("vessel")


def test_no_tmux_server_is_not_an_error(root: Path) -> None:
    """The other half, so the two cannot be conflated.

    An empty pane map is legitimately "no sessions": it is the ordinary state
    of a machine with nothing started.
    """
    engine, tmux = engine_for(root)
    tmux.fail_pane_pids = True
    assert all(s.state is State.STOPPED for s in engine.list())


def test_a_failed_ps_raises_even_when_tmux_has_sessions(root: Path) -> None:
    """The combination that would otherwise look most convincingly like stale."""
    from conftest import failing_procs

    engine, _ = engine_for(root, sessions={"vessel": PANE}, procs_fn=failing_procs)
    with pytest.raises(MachineUnreadable):
        engine.list()


# -- 7. the performance contract -------------------------------------------


@pytest.mark.parametrize("count", [1, 5, 50])
def test_list_issues_one_tmux_call_and_one_ps_call(tmp_path: Path, count: int) -> None:
    """Asserted at more than one project count, because a call per project is
    a subprocess spawn per row and the cost is invisible until the folder is
    big."""
    for n in range(count):
        (tmp_path / f"p{n}").mkdir()
    reads = {"n": 0}

    def counting_procs() -> ProcTable:
        reads["n"] += 1
        return procs_from("")()

    engine, tmux = engine_for(tmp_path, procs_fn=counting_procs)
    assert len(engine.list()) == count
    assert tmux.pane_pids_calls == 1
    assert reads["n"] == 1


def test_list_captures_no_pane(root: Path) -> None:
    """Capturing is the expensive lookup and belongs in `session_url`."""
    table = ps_row(PANE, 1) + ps_row(AGENT, PANE, project="vessel")
    engine, tmux = engine_for(root, sessions={"vessel": PANE}, table=table)
    engine.list()
    assert tmux.capture_calls == 0


def test_get_derives_the_same_state_as_list(root: Path) -> None:
    """Or a detail view disagrees with the row that opened it."""
    table = ps_row(ORPHAN, 1, project="vessel")
    engine, _ = engine_for(root, table=table)
    from_list = {s.name: s.state for s in engine.list()}
    for name in from_list:
        assert engine.get(name).state is from_list[name]


# -- 8. determinism and ordering -------------------------------------------


def test_list_is_ordered_and_stable(root: Path) -> None:
    engine, _ = engine_for(root)
    assert [s.name for s in engine.list()] == [s.name for s in engine.list()]


def test_list_covers_every_project_exactly_once(root: Path) -> None:
    engine, _ = engine_for(root, table=ps_row(ORPHAN, 1, project="vessel"))
    names = [s.name for s in engine.list()]
    assert sorted(names) == sorted(set(names))
    assert set(names) == {"vessel", "vessel-social", "a", "ab", "dotted.site"}


# -- 9. the overlay applies to every state ---------------------------------


def test_a_fresh_engine_reports_nothing_as_stopping(root: Path) -> None:
    """The in flight stop is memory only. If Hitchrail restarts mid stop that
    knowledge is lost and the session reads as running again, which is the
    truth; a marker that outlived the process would be a lie."""
    engine, _ = engine_for(root, table=ps_row(ORPHAN, 1, project="vessel"))
    assert all(not s.stopping for s in engine.list())
    assert engine.stopping_since("vessel") is None


# -- 10. the fields, not just the state ------------------------------------


def test_ram_is_the_whole_subtree(root: Path) -> None:
    """The agent plus its helpers. Charging only the agent under reports what
    stopping it would release."""
    table = (
        ps_row(PANE, 1, rss_kb=1024)
        + ps_row(AGENT, PANE, project="vessel", rss_kb=2048)
        + ps_row(HELPER, AGENT, args="node", rss_kb=1024)
    )
    engine, _ = engine_for(root, sessions={"vessel": PANE}, table=table)
    assert engine.get("vessel").ram_mb == (2048 + 1024) // 1024


def test_uptime_comes_from_the_process(root: Path) -> None:
    table = ps_row(PANE, 1) + ps_row(AGENT, PANE, project="vessel", etime_s=4242)
    engine, _ = engine_for(root, sessions={"vessel": PANE}, table=table)
    assert engine.get("vessel").uptime_s == 4242


def test_pid_is_present_only_where_a_process_exists(root: Path) -> None:
    table = ps_row(PANE, 1) + ps_row(AGENT, PANE, project="vessel")
    engine, _ = engine_for(root, sessions={"vessel": PANE, "ab": 700}, table=table)
    assert engine.get("vessel").pid == AGENT  # running
    assert engine.get("ab").pid is None  # stale
    assert engine.get("a").pid is None  # stopped


def test_protected_is_true_only_for_the_self_project(root: Path) -> None:
    engine, _ = engine_for(root, self_project="vessel")
    assert engine.get("vessel").protected is True
    assert engine.get("ab").protected is False


@pytest.mark.parametrize(
    ("machine", "expected"),
    [
        (RUNNING_MACHINE, State.RUNNING),
        (STALE_MACHINE, State.STALE),
        (DETACHED_MACHINE, State.DETACHED),
        (STOPPED_MACHINE, State.STOPPED),
    ],
    ids=["running", "stale", "detached", "stopped"],
)
def test_protected_survives_in_every_state(
    root: Path, machine: Machine, expected: State
) -> None:
    """The safety flag, asserted where it MATTERS rather than where it is easy.

    The single earlier test used an empty machine, so it only ever reached the
    STOPPED branch: the one state where the lock is irrelevant. Mutating
    `protected` out of `_live` and out of the STALE branch left the whole suite
    green.

    This is the flag that turns the stop control into a lock for the session
    hosting Hitchrail, so it has to hold in the states where somebody might
    actually tap stop.
    """
    sessions, table = machine
    engine, _ = engine_for(root, sessions=sessions, table=table, self_project="vessel")
    session = engine.get("vessel")
    assert session.state is expected
    assert session.protected is True


@pytest.mark.parametrize(
    ("machine", "expected"),
    [
        (RUNNING_MACHINE, State.RUNNING),
        (STALE_MACHINE, State.STALE),
        (DETACHED_MACHINE, State.DETACHED),
    ],
    ids=["running", "stale", "detached"],
)
def test_the_stopping_overlay_applies_to_every_live_state(
    root: Path, machine: Machine, expected: State
) -> None:
    """An overlay, not a fifth state, and it must not change what is underneath.

    Nothing pinned this: removing `stopping=` from the STALE branch or `_live`
    each left the whole suite green, because `_stopping` is only populated by
    the stop path. A section headed "the overlay applies to every state"
    containing one test that asserts nothing IS stopping is not coverage.
    """
    sessions, table = machine
    engine, _ = engine_for(root, sessions=sessions, table=table)
    engine._stopping["vessel"] = 1234.0

    session = engine.get("vessel")
    assert session.stopping is True
    assert session.state is expected, "the marker must not change the derived state"
    assert engine.stopping_since("vessel") == 1234.0
    # And it is per session, not global.
    assert engine.get("ab").stopping is False


def test_the_overlay_does_not_apply_to_a_stopped_session(root: Path) -> None:
    """STOPPED is the exception, and this reverses an earlier decision.

    The parametrised test above used to cover STOPPED too, on the reasoning
    that an overlay applying everywhere is simpler to describe. Running a real
    agent showed what that meant: it obeyed the graceful request in about a
    second, and because the marker lives until the timeout, the session read
    `stopped` and `stopping` together for the next twenty nine. The interface
    shows a spinner on something that is already gone, and the expiry then
    announces a timeout for a stop that worked.

    An overlay needs something underneath it. Once nothing is running there is
    nothing to overlay, and the marker is dropped on read, which is the only
    moment the transition is visible.
    """
    sessions, table = STOPPED_MACHINE
    engine, _ = engine_for(root, sessions=sessions, table=table)
    engine._stopping["vessel"] = 1234.0

    session = engine.get("vessel")
    assert session.state is State.STOPPED
    assert session.stopping is False, "an overlay on a session that is not there"
    assert engine.stopping_since("vessel") is None, "the marker outlived the session"


def test_the_url_comes_from_the_bridge_file(root: Path, tmp_path: Path) -> None:
    """Listing uses `bridge_url`, never `session_url`: the latter captures a
    pane, which is a subprocess per running row on every list."""
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    (sessions_dir / f"{AGENT}.json").write_text(json.dumps({"bridgeSessionId": "session_abc"}))
    tmux = FakeTmux(sessions={"vessel": PANE})
    engine = Engine(
        Config(root=root, sessions_dir=sessions_dir),
        tmux=tmux,
        procs_fn=procs_from(ps_row(PANE, 1) + ps_row(AGENT, PANE, project="vessel")),
        meminfo_fn=lambda: "MemAvailable: 8388608 kB\n",
    )
    assert engine.get("vessel").url == "https://claude.ai/code/session_abc"
    assert tmux.capture_calls == 0


def test_as_dict_is_json_serialisable(root: Path) -> None:
    """It becomes an HTTP response in Phase 5. A StrEnum or a Path surviving
    into it fails there instead of here."""
    table = ps_row(PANE, 1) + ps_row(AGENT, PANE, project="vessel")
    engine, _ = engine_for(root, sessions={"vessel": PANE}, table=table)
    for session in engine.list():
        payload = json.dumps(session.as_dict())
        assert json.loads(payload)["name"] == session.name
    assert json.loads(json.dumps(engine.get("vessel").as_dict()))["state"] == "running"


def test_available_mb_reads_through_the_injected_seam(root: Path) -> None:
    engine, _ = engine_for(root)
    assert engine.available_mb() == 8388608 // 1024


def test_a_session_is_frozen(root: Path) -> None:
    """State is derived on demand and never stored, so nothing should be
    holding a Session and mutating it."""
    engine, _ = engine_for(root)
    with pytest.raises(AttributeError):
        engine.get("vessel").state = State.RUNNING  # type: ignore[misc]


def test_a_tmux_that_cannot_be_run_is_an_unreadable_machine(root: Path) -> None:
    """The other half of #40's honesty, which the first fix for it broke.

    An empty pane map means no sessions. A tmux that could not be RUN means we
    do not know, and deriving from it reported a live agent as `detached`:
    refuses to start, kill has no session, project unstartable.
    """

    def missing(argv: list[str]) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError(2, "No such file or directory", "tmux")

    sessions_dir = root / ".sessions"
    sessions_dir.mkdir(exist_ok=True)
    engine = Engine(
        Config(root=root, sessions_dir=sessions_dir),
        tmux=Tmux(prefix="hr-", run=missing),
        procs_fn=procs_from(ps_row(PANE, 1) + ps_row(AGENT, PANE, project="vessel")),
        meminfo_fn=lambda: "MemAvailable: 8388608 kB\n",
    )
    with pytest.raises(MachineUnreadable):
        engine.list()


# -- #41: starting ---------------------------------------------------------


def running_after(name: str = "vessel", blank_reads: int = 2) -> ScriptedProcs:
    """A table where the agent appears only after a few reads.

    The real one behaves this way: a freshly spawned agent is not in the
    process table when tmux returns, so a start that reads once sees a session
    with nothing in it and calls that a failure.

    `blank_reads` is 2 by default because `start` reads the machine BEFORE
    spawning, to check the current state, and that read consumes a stage. One
    blank stage would therefore be spent on the pre check and the very first
    poll would already succeed, which is a grace window that never waits.
    """
    empty = ps_row(1001, 1)
    with_agent = ps_row(1001, 1) + ps_row(AGENT, 1001, project=name)
    return ScriptedProcs(*([empty] * blank_reads), with_agent)


def start_engine(
    root: Path,
    *,
    table: object = None,
    sessions: dict[str, int] | None = None,
    mem_mb: int = 8192,
    self_project: str | None = None,
) -> tuple[Engine, FakeTmux, FakeClock]:
    tmux = FakeTmux(sessions=sessions)
    clock = FakeClock()
    sessions_dir = root / ".sessions"
    sessions_dir.mkdir(exist_ok=True)
    engine = Engine(
        Config(root=root, sessions_dir=sessions_dir, self_project=self_project),
        tmux=tmux,
        procs_fn=table or procs_from(""),  # type: ignore[arg-type]
        meminfo_fn=lambda: f"MemAvailable: {mem_mb * 1024} kB\n",
        clock=clock,
        sleep=clock.sleep,
    )
    return engine, tmux, clock


def test_starting_spawns_the_agent_in_the_projects_directory(root: Path) -> None:
    engine, tmux, _ = start_engine(root, table=running_after())
    session = engine.start("vessel")
    assert session.state is State.RUNNING
    name, cwd, argv = tmux.started[-1]
    assert name == "vessel"
    assert cwd == str((root / "vessel").resolve())
    assert argv == launch_argv("claude", "vessel"), "the argv must stay a list"


def test_a_start_survives_a_process_table_that_is_empty_at_first(root: Path) -> None:
    """The grace window, and the reason it exists."""
    engine, _, clock = start_engine(root, table=running_after())
    assert engine.start("vessel").state is State.RUNNING
    assert clock.slept, "it should have waited at least once"


def test_the_grace_window_is_bounded(root: Path) -> None:
    """A regression to an unbounded wait fails here rather than hanging CI."""
    engine, _, clock = start_engine(root, table=procs_from(ps_row(1001, 1)))
    with pytest.raises(StartFailed):
        engine.start("vessel")
    assert sum(clock.slept) <= engine.start_grace + engine.poll_interval


def test_a_failed_start_carries_the_pane_output(root: Path) -> None:
    """ "It did not start" without the reason is a support request."""
    engine, tmux, _ = start_engine(root, table=procs_from(ps_row(1001, 1)))
    tmux.pane_text["vessel"] = "claude: command not found"
    with pytest.raises(StartFailed) as caught:
        engine.start("vessel")
    assert "command not found" in caught.value.output


def test_a_second_start_of_the_same_folder_is_refused_immediately(root: Path) -> None:
    """`Locked`, not a queue. A queued start behind a slow one is a tap the
    user has forgotten about by the time it fires."""
    engine, tmux, _ = start_engine(root, table=running_after())
    # Keyed on the resolved DIRECTORY, not the name, because two names can be
    # one folder and starting both is the outcome the design exists to prevent.
    engine._starting.add(str((root / "vessel").resolve()))
    with pytest.raises(Locked):
        engine.start("vessel")
    assert tmux.started == [], "nothing may be spawned while one is in flight"


def test_a_start_of_a_different_folder_is_not_blocked(root: Path) -> None:
    """The lock is per FOLDER, not global."""
    engine, _, _ = start_engine(root, table=running_after("ab"))
    engine._starting.add(str((root / "vessel").resolve()))
    assert engine.start("ab").state is State.RUNNING


def test_the_lock_is_released_when_the_start_fails(root: Path) -> None:
    """A lock that outlives a failed start makes the folder permanently
    unstartable until Hitchrail restarts."""
    engine, _, _ = start_engine(root, table=procs_from(ps_row(1001, 1)))
    with pytest.raises(StartFailed):
        engine.start("vessel")
    assert engine._starting == set()


def test_the_lock_is_released_when_the_start_is_refused(root: Path) -> None:
    engine, _, _ = start_engine(root, mem_mb=100)
    with pytest.raises(MemoryRefused):
        engine.start("vessel")
    assert engine._starting == set()


def test_memory_below_the_hard_floor_refuses_and_spawns_nothing(root: Path) -> None:
    """Asserting the exception alone would pass for a refusal that already
    started something."""
    engine, tmux, _ = start_engine(root, mem_mb=100)
    with pytest.raises(MemoryRefused) as caught:
        engine.start("vessel")
    assert tmux.started == []
    assert caught.value.available_mb == 100
    assert caught.value.needed_mb == 1536


def test_memory_between_the_floors_asks_first(root: Path) -> None:
    """The third outcome. Collapsing SOFT into either neighbour removes the
    confirmation step the design asks for."""
    engine, tmux, _ = start_engine(root, table=running_after(), mem_mb=1536 + 2000)
    with pytest.raises(MemoryNeedsAck) as caught:
        engine.start("vessel")
    assert tmux.started == [], "nothing may be spawned while asking"
    assert caught.value.available_mb == 1536 + 2000


def test_an_acknowledged_soft_refusal_proceeds(root: Path) -> None:
    """A separate engine on purpose: reusing the one that refused would carry
    its scripted table's read counter forward, and the pre check would then see
    an agent that was never started."""
    engine, _, _ = start_engine(root, table=running_after(), mem_mb=1536 + 2000)
    assert engine.start("vessel", acknowledged=True).state is State.RUNNING


def test_starting_a_running_project_is_refused(root: Path) -> None:
    table = ps_row(PANE, 1) + ps_row(AGENT, PANE, project="vessel")
    engine, _, _ = start_engine(root, table=procs_from(table), sessions={"vessel": PANE})
    with pytest.raises(AlreadyRunning):
        engine.start("vessel")


def test_starting_a_detached_project_is_refused(root: Path) -> None:
    """Two agents in one folder is the outcome the whole design prevents."""
    engine, _, _ = start_engine(root, table=procs_from(ps_row(ORPHAN, 1, project="vessel")))
    with pytest.raises(AlreadyRunning):
        engine.start("vessel")


def test_a_stale_session_is_replaced_not_reused(root: Path) -> None:
    """Reusing it would start in a pane already holding somebody's scrollback."""
    engine, tmux, _ = start_engine(root, table=running_after(), sessions={"vessel": 1001})
    engine.start("vessel")
    assert "vessel" in tmux.killed


def test_starting_the_self_project_is_refused(root: Path) -> None:
    engine, tmux, _ = start_engine(root, self_project="vessel")
    with pytest.raises(Protected):
        engine.start("vessel")
    assert tmux.started == []


@pytest.mark.parametrize("name", ["", "../../etc", "no-such-project"])
def test_starting_something_that_is_not_a_project_is_refused(root: Path, name: str) -> None:
    engine, tmux, _ = start_engine(root)
    with pytest.raises(UnknownProject):
        engine.start(name)
    assert tmux.started == []


# -- #42: the three step stop ----------------------------------------------


def live_engine(
    root: Path, *, self_project: str | None = None
) -> tuple[Engine, FakeTmux, FakeClock]:
    """An engine with `vessel` genuinely running."""
    table = ps_row(PANE, 1) + ps_row(AGENT, PANE, project="vessel")
    engine, tmux, clock = start_engine(
        root,
        table=procs_from(table),
        sessions={"vessel": PANE},
        self_project=self_project,
    )
    return engine, tmux, clock


def test_stopping_asks_and_kills_nothing(root: Path) -> None:
    engine, tmux, _ = live_engine(root)
    session = engine.stop("vessel")
    assert session.stopping is True
    assert session.state is State.RUNNING, "asking does not change what it is"
    assert tmux.killed == [], "a graceful stop kills nothing"
    assert tmux.sent, "it must actually ask"


def test_the_stop_sequence_comes_from_the_quarantine(root: Path) -> None:
    """The engine must not know what a stop physically is."""

    engine, tmux, _ = live_engine(root)
    engine.stop("vessel")
    assert [keys for _project, keys in tmux.sent] == list(GRACEFUL_STOP_KEYS)


def test_the_engine_source_never_names_the_stop_sequence() -> None:
    """A grep, because no import contract sees a `for` loop over a constant."""
    source = (Path(__file__).parent.parent / "src" / "hitchrail" / "engine.py").read_text()
    assert "GRACEFUL_STOP_KEYS" not in source
    assert "send_keys" not in source


def test_kill_is_reachable_during_a_stop(root: Path) -> None:
    """The kill control stays within reach for the whole wait."""
    engine, tmux, _ = live_engine(root)
    engine.stop("vessel")
    engine.kill("vessel")
    assert tmux.killed == ["vessel"]
    assert engine.stopping_since("vessel") is None, "killing ends the wait"


def test_expiry_drops_the_marker_and_does_not_escalate(root: Path) -> None:
    """The behaviour most likely to be "helpfully" changed later.

    After the timeout Hitchrail stops WAITING. It does not kill: an automatic
    kill is a destructive action taken while the user was not looking, and the
    session is still alive so the choice remains theirs.

    Asserting no exception would pass for an implementation that killed
    quietly, so this asserts the fake recorded no kill.
    """
    engine, tmux, clock = live_engine(root)
    engine.stop("vessel")
    clock.advance(engine.config.stop_timeout + 1)

    assert engine.expire_stops() == ["vessel"]
    assert tmux.killed == [], "expiry must never escalate"
    assert engine.stopping_since("vessel") is None
    assert engine.get("vessel").state is State.RUNNING, "still alive, still theirs"


def test_expiry_leaves_a_stop_that_is_still_within_its_timeout(root: Path) -> None:
    engine, _, clock = live_engine(root)
    engine.stop("vessel")
    clock.advance(engine.config.stop_timeout - 1)
    assert engine.expire_stops() == []
    assert engine.stopping_since("vessel") is not None


def test_expiry_announces_so_the_interface_can_report_it(root: Path) -> None:
    """An expiry visible only on the next poll is one the interface cannot
    report, and somebody is watching that timer."""
    engine, _, clock = live_engine(root)
    published: list[dict[str, object]] = []

    class Recorder:
        def publish(self, event: dict[str, object]) -> None:
            published.append(event)

    engine.attach_bus(Recorder())  # type: ignore[arg-type]
    engine.stop("vessel")
    clock.advance(engine.config.stop_timeout + 1)
    engine.expire_stops()
    assert any(e["name"] == "vessel" for e in published)


def test_stopping_something_that_is_not_running_is_refused(root: Path) -> None:
    engine, tmux, _ = start_engine(root)
    with pytest.raises(NotRunning):
        engine.stop("vessel")
    assert tmux.sent == []


@pytest.mark.parametrize("action", ["stop", "kill"])
def test_the_self_project_cannot_be_stopped_or_killed(root: Path, action: str) -> None:
    """Taking the interface down has no undo."""
    engine, tmux, _ = live_engine(root, self_project="vessel")
    with pytest.raises(Protected):
        getattr(engine, action)("vessel")
    assert tmux.killed == []
    assert tmux.sent == []


def test_logs_return_the_pane_tail(root: Path) -> None:
    engine, tmux, _ = live_engine(root)
    tmux.pane_text["vessel"] = "hello from the agent"
    assert engine.logs("vessel") == "hello from the agent"


def test_session_url_pays_for_the_scrape_and_says_so(root: Path) -> None:
    """The expensive lookup listing skips, and the only place a scraped source
    can appear."""
    engine, tmux, _ = live_engine(root)
    tmux.pane_text["vessel"] = "open https://claude.ai/code/session_scraped"
    found = engine.session_url("vessel")
    assert found is not None
    assert found.source == "scraped"


def test_session_url_tells_three_answers_apart(root: Path) -> None:
    """Reverses an earlier decision, so the reason is here rather than in the log.

    This used to assert `None` for a stopped project, on the reasoning that a
    missing link is a missing link. Phase 5 showed what that costs: the route
    turns `None` into `url_pending`, which tells a client to "ask again
    shortly". For a typo that is a lie it will keep believing, and for a real
    project that is not running it is the wrong instruction, because the answer
    is start it.

    So there are three answers, not one. A name the root has never heard of is
    `UnknownProject`, a real project that is not running is `NotRunning`, and a
    RUNNING one that has not published a link yet is `None`, which is the only
    case where "ask again shortly" is true. See #47.
    """
    engine, _, _ = start_engine(root)
    with pytest.raises(NotRunning):
        engine.session_url("vessel")
    with pytest.raises(UnknownProject):
        engine.session_url("no-such-project")


def test_session_url_is_none_only_while_a_running_session_has_no_link(
    root: Path,
) -> None:
    """The `url_pending` case, which must stay `None` rather than raising."""
    engine, _, _ = live_engine(root)
    assert engine.get("vessel").state is State.RUNNING
    assert engine.session_url("vessel") is None


def test_sessions_does_not_import_engine() -> None:
    """The dependency runs one way, which is what makes #41's split a seam.

    Phase 5 imports the exceptions to map them to status codes; if `sessions`
    imported `engine` back, that would drag the whole engine into the API layer
    and the split would be a cut through a cycle.
    """
    source = (Path(__file__).parent.parent / "src" / "hitchrail" / "sessions.py").read_text()
    assert "import engine" not in source
    assert "from hitchrail.engine" not in source


def test_an_alias_cannot_start_a_second_agent_in_the_same_folder(
    tmp_path: Path,
) -> None:
    """The outcome the whole design exists to prevent, from the start path.

    `resolve_child` deliberately allows a symlink inside the root, so `alpha`
    and `zebra` are two names for one directory. #11 deduplicates them in
    `scan`, and `start` took a name directly and bypassed that: both spawned,
    into the same checkout, each invisible to the other's `AlreadyRunning`
    check because `get("alpha")` looks up `hr-alpha` and scans for a command
    line naming `alpha`.

    No race is needed. Sequential calls were enough.
    """
    (tmp_path / "zebra").mkdir()
    (tmp_path / "alpha").symlink_to(tmp_path / "zebra", target_is_directory=True)
    engine, tmux, _ = start_engine(tmp_path, table=running_after("zebra"))

    assert engine.start("zebra").state is State.RUNNING
    with pytest.raises(UnknownProject):
        engine.start("alpha")
    assert len(tmux.started) == 1
    assert len({cwd for _n, cwd, _a in tmux.started}) == 1


def test_the_start_lock_is_keyed_on_the_folder_not_the_name(tmp_path: Path) -> None:
    """Belt to the listing check's braces: the listing is recomputed per call."""
    (tmp_path / "zebra").mkdir()
    engine, _, _ = start_engine(tmp_path, table=running_after("zebra"))
    engine._starting.add(str((tmp_path / "zebra").resolve()))
    with pytest.raises(Locked):
        engine.start("zebra")


@pytest.mark.parametrize("action", ["start", "stop", "kill", "logs", "session_url"])
@pytest.mark.parametrize("name", ["../../etc", "", ".hidden", "a b"])
def test_every_entry_point_refuses_a_malformed_name(root: Path, action: str, name: str) -> None:
    """A name that could not be a project is `UnknownProject` everywhere.

    Phase 5 needs 404 rather than 409, and before this every one of these
    reported `NotRunning`, which an interface cannot tell from a real stopped
    project.
    """
    engine, _, _ = live_engine(root)
    with pytest.raises(UnknownProject):
        getattr(engine, action)(name)


@pytest.mark.parametrize("action", ["stop", "kill", "logs"])
def test_a_well_formed_name_with_nothing_behind_it_is_not_running(
    root: Path, action: str
) -> None:
    """Not `UnknownProject`: there is nothing to stop, which is a different
    thing from a name that could never be a project."""
    engine, _, _ = live_engine(root)
    with pytest.raises(NotRunning):
        getattr(engine, action)("ab")


@pytest.mark.parametrize("action", ["stop", "kill", "logs"])
def test_a_live_session_stays_actionable_when_its_name_is_not_listed(
    tmp_path: Path, action: str
) -> None:
    """The regression the first version of the gate introduced.

    A leftover `hr-alpha` is exactly what the alias bug produced, so gating
    the destructive path on the listing meant anybody who hit that bug could
    no longer clean it up through Hitchrail. A folder renamed under a running
    agent had the same shape.

    Creating and destroying are not the same question: identity must be unique
    where a NEW agent is created, and destroying must stay reachable, because
    the design keeps the kill backstop available throughout.
    """
    (tmp_path / "zebra").mkdir()
    (tmp_path / "alpha").symlink_to(tmp_path / "zebra", target_is_directory=True)
    sessions_dir = tmp_path / ".sessions"
    sessions_dir.mkdir()
    rows = ps_row(600, 1) + ps_row(601, 600, project="alpha")
    tmux = FakeTmux(sessions={"alpha": 600})
    engine = Engine(
        Config(root=tmp_path, sessions_dir=sessions_dir),
        tmux=tmux,
        procs_fn=procs_from(rows),
        meminfo_fn=lambda: "MemAvailable: 8388608 kB\n",
    )
    # `scan` deduplicates the alias away, so the name is not listed...
    assert "alpha" not in [s.name for s in engine.list()]
    # ...and the engine can still see the agent, so it must remain actionable.
    assert engine.get("alpha").state is State.RUNNING
    getattr(engine, action)("alpha")


def test_an_unlisted_name_still_cannot_start_a_second_agent(tmp_path: Path) -> None:
    """The other half: destroying stays open, creating stays closed."""
    (tmp_path / "zebra").mkdir()
    (tmp_path / "alpha").symlink_to(tmp_path / "zebra", target_is_directory=True)
    engine, _, _ = start_engine(tmp_path, table=running_after("zebra"))
    with pytest.raises(UnknownProject):
        engine.start("alpha")


def test_a_symlink_loop_is_an_engine_error_not_a_runtime_error(tmp_path: Path) -> None:
    """`scan` reports a loop as unsupported, so it appears in the listing.

    Without this it escaped `start` as a bare `RuntimeError` from
    `Path.resolve`, which is not an `EngineError`, so Phase 5 would answer 500
    for a row the interface had just drawn.
    """
    (tmp_path / "a").symlink_to(tmp_path / "b", target_is_directory=True)
    (tmp_path / "b").symlink_to(tmp_path / "a", target_is_directory=True)
    engine, _, _ = start_engine(tmp_path)
    with pytest.raises(UnknownProject):
        engine.start("a")


# -- tmux vanishing mid run ------------------------------------------------


class VanishingTmux(FakeTmux):
    """A tmux that disappears after a chosen number of calls.

    #28 refuses to start at all when tmux is missing. This is the other case:
    it was there and now is not, mid session, which is what an upgrade or a
    container restart looks like.
    """

    def __init__(self, fail_after: int = 0, **kw: object) -> None:
        super().__init__(**kw)  # type: ignore[arg-type]
        self.fail_after = fail_after
        self.calls = 0

    def _maybe_vanish(self) -> None:
        self.calls += 1
        if self.calls > self.fail_after:
            raise TmuxUnavailable("tmux is gone")

    def vanish_next(self) -> None:
        """Work until now, fail from the next call on.

        For a test that wants one operation to succeed and the next to fail
        without knowing how many tmux calls the first one makes. `fail_after`
        with a hand counted number encodes the mechanism into the test: the
        one below said "three, because the stop sequence is three key groups"
        and went red when #89 added the two captures that verify the box, for
        a reason that had nothing to do with what it was testing.
        """
        self.fail_after = self.calls

    def kill_session(self, project: str) -> None:
        self._maybe_vanish()
        super().kill_session(project)

    def new_session(self, project: str, cwd: str, argv: list[str]) -> None:
        self._maybe_vanish()
        super().new_session(project, cwd, argv)

    def capture_pane(self, project: str, lines: int = 40, escapes: bool = False) -> str:
        self._maybe_vanish()
        return super().capture_pane(project, lines, escapes)

    def send_keys(self, project: str, *keys: str) -> None:
        self._maybe_vanish()
        super().send_keys(project, *keys)


def vanishing_engine(root: Path, *, fail_after: int = 0, live: bool = True) -> Engine:
    sessions_dir = root / ".sessions"
    sessions_dir.mkdir(exist_ok=True)
    table = ps_row(PANE, 1) + ps_row(AGENT, PANE, project="vessel") if live else ps_row(PANE, 1)
    clock = FakeClock()
    return Engine(
        Config(root=root, sessions_dir=sessions_dir),
        tmux=VanishingTmux(fail_after=fail_after, sessions={"vessel": PANE}),
        procs_fn=procs_from(table),
        meminfo_fn=lambda: "MemAvailable: 8388608 kB\n",
        clock=clock,
        sleep=clock.sleep,
    )


@pytest.mark.parametrize("action", ["stop", "kill", "logs"])
def test_a_tmux_that_vanishes_is_an_honest_refusal_not_a_500(root: Path, action: str) -> None:
    """Every path that touches tmux must map `TmuxUnavailable`.

    This is the invariant the module argues for hardest, and every one of these
    mappings was written with no test: coverage named exactly those five lines
    as the only misses in the file. An unmapped one escapes as a raw `OSError`,
    which is not an `EngineError`, so Phase 5 answers 500 instead of saying the
    machine could not be read.
    """
    engine = vanishing_engine(root)
    with pytest.raises(MachineUnreadable):
        getattr(engine, action)("vessel")


def test_a_tmux_that_vanishes_during_a_start_is_an_honest_refusal(root: Path) -> None:
    engine = vanishing_engine(root, live=False)
    with pytest.raises(MachineUnreadable):
        engine.start("vessel")


def test_a_failed_stop_does_not_leave_a_phantom_marker(root: Path) -> None:
    """The wait must not outlive the request that could not be sent."""
    engine = vanishing_engine(root)
    with pytest.raises(MachineUnreadable):
        engine.stop("vessel")
    assert engine.stopping_since("vessel") is None


def test_a_stop_the_adapter_will_not_send_is_an_honest_refusal(root: Path) -> None:
    """#89. The sequence verifies the input box before it types, and a box it
    cannot vouch for stops the whole thing.

    The engine's job is to turn that into a refusal rather than a 500, and to
    take the marker back with it: a wait must not outlive a request that was
    never sent, which is the same rule `test_a_failed_stop_does_not_leave_a_
    phantom_marker` states for a tmux that vanished.
    """
    engine, tmux = engine_for(root, sessions={"vessel": PANE}, table=RUNNING_MACHINE[1])
    tmux.pane_text["vessel"] = DIRTY_INPUT_BOX

    with pytest.raises(StopRefused):
        engine.stop("vessel")
    assert engine.stopping_since("vessel") is None


def test_a_refused_stop_types_nothing(root: Path) -> None:
    """The half that matters. A refusal that had already sent `/exit` would be
    a refusal in name only, and the thing being refused is submitting text into
    somebody else's session with their authority (#91)."""
    engine, tmux = engine_for(root, sessions={"vessel": PANE}, table=RUNNING_MACHINE[1])
    tmux.pane_text["vessel"] = DIRTY_INPUT_BOX

    with pytest.raises(StopRefused):
        engine.stop("vessel")
    assert not any("/exit" in keys for _, keys in tmux.sent), (
        "typed into a box it could not read"
    )


def test_a_failed_kill_keeps_the_stop_indicator(root: Path) -> None:
    """The pop moved AFTER the kill. Popping first meant a kill that failed
    took the indicator with it, so a graceful stop still in flight looked as
    though nobody had asked."""
    # A working stop, and then tmux goes away. Armed after the fact rather than
    # counted in advance, so this test says what it means: the KILL is the call
    # that fails.
    engine = vanishing_engine(root, fail_after=99)
    engine.stop("vessel")
    assert engine.stopping_since("vessel") is not None

    tmux = engine.tmux
    assert isinstance(tmux, VanishingTmux)
    tmux.vanish_next()

    with pytest.raises(MachineUnreadable):
        engine.kill("vessel")
    assert engine.stopping_since("vessel") is not None


def test_a_start_that_fails_still_reports_why_when_tmux_is_gone(root: Path) -> None:
    """`_safe_capture` exists solely for this branch, and nothing entered it.

    A tmux that went away must not replace "your session did not start, here is
    why" with a different exception entirely.
    """
    engine = vanishing_engine(root, fail_after=1, live=False)
    engine.start_grace = 0.0
    with pytest.raises((StartFailed, MachineUnreadable)):
        engine.start("vessel")


def test_a_bus_that_raises_does_not_fail_the_stop(root: Path, caplog: object) -> None:
    """A successful stop must not be reported as a failed one.

    `EventBus.publish` guarantees it does not raise; this holds if a future bus
    does not. Silent would make "events stopped arriving" unfalsifiable, so it
    logs.
    """
    import logging

    engine, _, _ = live_engine(root)

    class Exploding:
        def publish(self, event: dict[str, object]) -> None:
            raise RuntimeError("the bus is on fire")

    engine.attach_bus(Exploding())  # type: ignore[arg-type]
    with caplog.at_level(logging.ERROR, logger="hitchrail.engine"):  # type: ignore[attr-defined]
        session = engine.stop("vessel")

    assert session.stopping is True, "the stop succeeded and must be reported so"
    assert any("could not announce" in r.message for r in caplog.records)  # type: ignore[attr-defined]


def test_a_failed_start_reports_why_even_when_the_pane_cannot_be_read(
    root: Path,
) -> None:
    """`_safe_capture`'s whole reason to exist, and nothing entered it.

    While raising `StartFailed`, a tmux that has gone away must not replace
    "your session did not start, here is why" with a different exception.
    """
    sessions_dir = root / ".sessions"
    sessions_dir.mkdir(exist_ok=True)

    class CaptureFails(FakeTmux):
        def capture_pane(self, project: str, lines: int = 40, escapes: bool = False) -> str:
            raise TmuxUnavailable("tmux is gone")

    clock = FakeClock()
    engine = Engine(
        Config(root=root, sessions_dir=sessions_dir),
        tmux=CaptureFails(),
        procs_fn=procs_from(ps_row(1001, 1)),
        meminfo_fn=lambda: "MemAvailable: 8388608 kB\n",
        clock=clock,
        sleep=clock.sleep,
    )
    engine.start_grace = 0.0
    with pytest.raises(StartFailed) as caught:
        engine.start("vessel")
    assert caught.value.output == "", "an unreadable pane is empty output, not a crash"


def test_an_unreadable_machine_does_not_kill_the_expiry_ticker(tmp_path: Path) -> None:
    """Phase 5 drives `expire_stops` from a ticker, and a raise ends it.

    The announce loop runs outside the lock, so `get` can fail there, and by
    then the markers are already dropped. Uncaught, one tmux hiccup means no
    stop expires again for the life of the process. Losing an announcement is
    a stale timer on one page; losing the ticker is every timer, forever.
    """
    (tmp_path / "alpha").mkdir()
    sessions_dir = tmp_path / ".sessions"
    sessions_dir.mkdir()
    now = [0.0]
    tmux = FakeTmux(sessions={"alpha": 600})
    engine = Engine(
        Config(root=tmp_path, sessions_dir=sessions_dir, stop_timeout=1.0),
        tmux=tmux,
        procs_fn=procs_from(ps_row(600, 1) + ps_row(601, 600, project="alpha")),
        meminfo_fn=lambda: "MemAvailable: 8388608 kB\n",
        clock=lambda: now[0],
        sleep=lambda _s: None,
    )
    engine.stop("alpha")
    now[0] = 99.0

    def gone() -> dict[str, int]:
        raise TmuxUnavailable("tmux is gone")

    tmux.pane_pids = gone  # type: ignore[method-assign]
    # Reports the expiry rather than raising it...
    assert engine.expire_stops() == ["alpha"]
    # ...and the marker is gone, so the next tick does not re-expire it.
    assert engine.stopping_since("alpha") is None
    # The ticker is still usable, which is the whole point.
    assert engine.expire_stops() == []


def test_a_project_that_vanishes_between_the_listing_and_the_path_is_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The race the `except` in `_require_startable` exists for.

    The gate asks the listing first and resolves the path second, so a folder
    deleted between those two calls reaches `project_path` after passing the
    listing. Without the guard that surfaces as a raw `NoSuchProject` from the
    discovery layer, which the API has no code for and would return as a 500.

    Worth a test because a guard nobody can reach is worse than no guard: a
    reader who finds one stops trusting the rest. This one is reachable, and
    this is the door.
    """
    (tmp_path / "alpha").mkdir()
    sessions_dir = tmp_path / ".sessions"
    sessions_dir.mkdir()
    engine = Engine(
        Config(root=tmp_path, sessions_dir=sessions_dir),
        tmux=FakeTmux(sessions={}),
        procs_fn=procs_from(""),
        meminfo_fn=lambda: "MemAvailable: 8388608 kB\n",
        sleep=lambda _s: None,
    )
    real = discovery.project_path

    def vanishing(root: Path, name: str) -> Path:
        shutil.rmtree(tmp_path / "alpha", ignore_errors=True)
        return real(root, name)

    monkeypatch.setattr(discovery, "project_path", vanishing)
    with pytest.raises(UnknownProject):
        engine.start("alpha")


def test_a_stop_that_worked_is_not_reported_as_a_timeout(tmp_path: Path) -> None:
    """Found by running a real agent, which no fake had caught.

    The agent obeyed the graceful request in about a second. The marker lived
    for the full thirty, so the session read `stopped` and `stopping` at the
    same time, and the expiry then announced a timeout for a stop that had
    worked. The user is told their agent would not stop, after it already had.
    """
    (tmp_path / "alpha").mkdir()
    sessions_dir = tmp_path / ".sessions"
    sessions_dir.mkdir()
    now = [0.0]
    table = [ps_row(600, 1) + ps_row(601, 600, project="alpha")]
    tmux = FakeTmux(sessions={"alpha": 600})
    engine = Engine(
        Config(root=tmp_path, sessions_dir=sessions_dir, stop_timeout=30.0),
        tmux=tmux,
        procs_fn=lambda: procs_from(table[0])(),
        meminfo_fn=lambda: "MemAvailable: 8388608 kB\n",
        clock=lambda: now[0],
        sleep=lambda _s: None,
    )
    engine.stop("alpha")
    assert engine.get("alpha").stopping, "the overlay should show while it is alive"

    # The agent obeys and exits.
    now[0] = 1.0
    table[0] = ""
    tmux.sessions = {}

    session = engine.get("alpha")
    assert session.state is State.STOPPED
    assert not session.stopping, "an overlay on a session that is not there"
    assert engine.stopping_since("alpha") is None, "the marker outlived the stop"

    # ...so the expiry has nothing to report thirty seconds later.
    now[0] = 31.0
    assert engine.expire_stops() == []


def test_the_overlay_survives_while_the_agent_is_still_running(root: Path) -> None:
    """The other half: reconciling on read must not drop a stop in flight.

    Clearing the marker whenever it is convenient would make the spinner
    vanish the moment anybody refreshed, which is the failure the fix above
    could easily have introduced.
    """
    engine, _, _ = live_engine(root)
    engine.stop("vessel")
    for _ in range(3):
        assert engine.get("vessel").stopping, "a stop in flight was reconciled away"
    assert engine.stopping_since("vessel") is not None


def _killing_engine(tmp_path: Path, polls_until_reaped: int) -> tuple[Engine, list[float]]:
    """An engine whose agent keeps running for a while after the tmux session
    goes, which is what really happens: `kill-session` returns before the
    kernel has reaped anything."""
    (tmp_path / "alpha").mkdir()
    sessions_dir = tmp_path / ".sessions"
    sessions_dir.mkdir()
    table = [ps_row(600, 1) + ps_row(601, 600, project="alpha")]
    remaining = [polls_until_reaped]
    tmux = FakeTmux(sessions={"alpha": 600})

    def killed(project: str) -> None:
        tmux.sessions.pop(project, None)
        # Orphaned but alive: no pane owns it, so derivation sees `detached`.
        table[0] = ps_row(601, 1, project="alpha")

    tmux.kill_session = killed  # type: ignore[method-assign]
    now = [0.0]

    def procs() -> ProcTable:
        if remaining[0] <= 0:
            table[0] = ""
        remaining[0] -= 1
        return procs_from(table[0])()

    engine = Engine(
        Config(root=tmp_path, sessions_dir=sessions_dir),
        tmux=tmux,
        procs_fn=procs,
        meminfo_fn=lambda: "MemAvailable: 8388608 kB\n",
        clock=lambda: now[0],
        sleep=lambda s: now.__setitem__(0, now[0] + s),
    )
    return engine, now


def test_kill_does_not_report_a_dying_agent_as_detached(tmp_path: Path) -> None:
    """`kill` used to hand back `detached` with a pid.

    `tmux kill-session` returns before the process finishes dying, so the pane
    map is empty while the agent is still in the table. Derivation is right to
    call that detached; handing it back from `kill` is not, because the user
    asked to kill and is told they now have a detached agent, which reads as
    the kill having failed and orphaned something.

    Raised against the stop sequence on #49 and decided here.
    """
    engine, now = _killing_engine(tmp_path, polls_until_reaped=2)
    session = engine.kill("alpha")
    assert session.state is State.STOPPED, "a dying agent was reported detached"
    assert session.pid is None
    assert now[0] <= 2.0, "the wait must stay inside the grace window"


def test_kill_still_surfaces_an_agent_that_genuinely_will_not_die(
    tmp_path: Path,
) -> None:
    """The wait is a courtesy, not a cover up.

    Past the grace window `detached` with its pid is the correct answer and the
    user needs it: that is the state the design surfaces on purpose so a person
    can act on it. Returning `stopped` here would be the lie the whole
    derivation exists to avoid.
    """
    engine, now = _killing_engine(tmp_path, polls_until_reaped=10_000)
    session = engine.kill("alpha")
    assert session.state is State.DETACHED
    assert session.pid == 601
    assert now[0] == pytest.approx(engine.kill_grace), "the wait must be bounded"


def test_list_accepts_a_listing_and_does_not_scan_the_root_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The API walks the root once per response, not twice.

    `discovery.list_projects` is `scan(root).projects`, so a caller that also
    needs the unsupported folders used to walk the root a second time for its
    own `scan`. Passing the listing in collapses that.
    """
    for name in ("alpha", "beta"):
        (tmp_path / name).mkdir()
    sessions_dir = tmp_path / ".sessions"
    sessions_dir.mkdir()
    engine, _, _ = start_engine(tmp_path, table=procs_from(""))

    scans = []
    real = discovery.scan

    def counting(root: Path) -> discovery.Listing:
        scans.append(root)
        return real(root)

    monkeypatch.setattr(discovery, "scan", counting)

    listing = discovery.scan(tmp_path)
    scans.clear()
    sessions = engine.list(listing=listing)
    assert scans == [], "the root was walked again despite being handed a listing"
    assert sorted(s.name for s in sessions) == ["alpha", "beta"]


def test_list_without_a_listing_still_scans_for_itself(tmp_path: Path) -> None:
    """The plain form is what every caller that only wants sessions uses."""
    (tmp_path / "alpha").mkdir()
    (tmp_path / ".sessions").mkdir()
    engine, _, _ = start_engine(tmp_path, table=procs_from(""))
    assert [s.name for s in engine.list()] == ["alpha"]


def test_a_listing_decides_the_names_so_one_answer_cannot_contradict_itself(
    tmp_path: Path,
) -> None:
    """The consistency half, which is the real reason for the seam.

    A folder created between the caller's scan and the engine's own would
    appear in one half of a single JSON body and not the other. Handed one
    listing, both halves describe the same instant.
    """
    (tmp_path / "alpha").mkdir()
    (tmp_path / ".sessions").mkdir()
    engine, _, _ = start_engine(tmp_path, table=procs_from(""))
    listing = discovery.scan(tmp_path)

    # The root changes after the listing was taken.
    (tmp_path / "beta").mkdir()

    assert [s.name for s in engine.list(listing=listing)] == ["alpha"], (
        "the engine used the live root instead of the listing it was given"
    )
    assert sorted(s.name for s in engine.list()) == ["alpha", "beta"]


def test_session_url_is_none_for_a_stale_session(root: Path) -> None:
    """A tmux session with no agent in it: there is a pane but no pid.

    Not `NotRunning`, because something IS there and the shell can still be
    attached to. Not an error either: there is simply no link, which is the
    `url_pending` case the route reports.
    """
    engine, _ = engine_for(root, sessions={"vessel": PANE}, table=ps_row(PANE, 1))
    assert engine.get("vessel").state is State.STALE
    assert engine.session_url("vessel") is None


# -- #66: a start that dies keeps what it printed ---------------------------


def test_a_dead_start_carries_the_output_and_leaves_no_session(root: Path) -> None:
    """The pane is kept alive past its process precisely so this read finds
    something. Without it the pane, the window, the session and the tmux
    server are gone inside fifty milliseconds, and `start_died` arrives empty:
    the interface then says a session died and cannot say why, which is the
    failure "Started, then exited after 3 seconds" was written to avoid.
    """
    engine, tmux, _ = start_engine(root, table=procs_from(""))
    tmux.pane_text["vessel"] = "agent: missing credential\nPane is dead (status 3)"
    tmux.dead_panes.add("vessel")

    with pytest.raises(StartFailed) as raised:
        engine.start("vessel")

    assert "missing credential" in raised.value.output
    assert "status 3" in raised.value.output, "the exit status is the diagnostic"
    assert tmux.killed == ["vessel"], "the kept pane was not cleaned up"


def test_a_start_that_is_merely_slow_is_not_killed(root: Path) -> None:
    """`StartFailed` fires on a timeout, and a timeout is not proof of death.

    A loaded machine, a cold cache, or a grace window that was generous
    yesterday all produce one while the agent is starting perfectly well.
    Killing on every timeout would end a healthy agent, which is strictly
    worse than the empty output this whole ticket is about. The pane is
    observably dead only when it really is.
    """
    engine, tmux, _ = start_engine(root, table=procs_from(""))
    tmux.pane_text["vessel"] = "agent: still waking up"
    # The pane is NOT marked dead, so the agent may still be coming.

    with pytest.raises(StartFailed):
        engine.start("vessel")

    assert tmux.killed == [], "a slow start was killed as though it had died"


def test_an_undeterminable_pane_counts_as_alive(root: Path) -> None:
    """The caller acts destructively on True, so a guess is not a reason to
    kill something."""
    engine, tmux, _ = start_engine(root, table=procs_from(""))

    def cannot_tell(project: str) -> bool:
        raise TmuxUnavailable("tmux went away")

    tmux.pane_is_dead = cannot_tell  # type: ignore[method-assign]

    with pytest.raises(StartFailed):
        engine.start("vessel")

    assert tmux.killed == []


def test_a_dead_start_reads_the_whole_scrollback(root: Path) -> None:
    """tmux writes its own "Pane is dead" line into the VISIBLE pane, so a
    bounded read can return that and nothing else while what the agent printed
    has scrolled above it."""
    engine, tmux, _ = start_engine(root, table=procs_from(""))
    tmux.pane_text["vessel"] = "anything"

    with pytest.raises(StartFailed):
        engine.start("vessel")

    assert tmux.capture_lines == [0], (
        f"the dead start read {tmux.capture_lines}, not the whole scrollback"
    )


def test_a_successful_start_stops_keeping_the_pane(root: Path) -> None:
    """Left on, a later graceful exit leaves a dead pane, the session lingers,
    and the engine derives `stale` where the truth is `stopped`. That would
    silently change the outcome of the stop flow."""
    engine, tmux, _ = start_engine(root, table=running_after())

    engine.start("vessel")

    assert ("vessel", False) in tmux.pane_kept, "remain-on-exit was left on"


def test_a_start_is_not_failed_by_a_tmux_that_dies_while_tidying_up(
    root: Path,
) -> None:
    """The start WORKED. Reporting it as a failure because the tidy up
    afterwards did not is the wrong answer to a cosmetic problem."""
    engine, tmux, _ = start_engine(root, table=running_after())

    def gone(project: str, keep: bool) -> None:
        raise TmuxUnavailable("tmux went away")

    tmux.keep_pane_on_exit = gone  # type: ignore[method-assign]

    assert engine.start("vessel").state is State.RUNNING


def test_a_dead_start_still_reports_when_the_cleanup_fails(root: Path) -> None:
    """The message matters more than the tidying. A machine that has lost tmux
    will not be told about it by this path."""
    engine, tmux, _ = start_engine(root, table=procs_from(""))
    tmux.pane_text["vessel"] = "agent: exploded"
    tmux.dead_panes.add("vessel")

    def gone(project: str) -> None:
        raise TmuxUnavailable("tmux went away")

    tmux.kill_session = gone  # type: ignore[method-assign]

    with pytest.raises(StartFailed) as raised:
        engine.start("vessel")
    assert "exploded" in raised.value.output
