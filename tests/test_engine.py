"""State derivation: four states from two independent scans.

#40 was not split, so these tests carry the weight a second reviewer would
have. They are organised around the ways the algorithm can be WRONG rather than
around its happy path: every cell of the state matrix, both directions of
orphan attribution, and the assumptions the derivation makes about its
neighbours.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from conftest import FakeTmux, procs_from, ps_row
from hitchrail.claude_ipc import launch_argv
from hitchrail.config import Config
from hitchrail.engine import Engine, MachineUnreadable, State
from hitchrail.procs import ProcTable

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
        (STOPPED_MACHINE, State.STOPPED),
    ],
    ids=["running", "stale", "detached", "stopped"],
)
def test_the_stopping_overlay_applies_to_every_state(
    root: Path, machine: Machine, expected: State
) -> None:
    """An overlay, not a fifth state, and it must not change what is underneath.

    Nothing pinned this: removing `stopping=` from the STALE branch, the
    STOPPED branch or `_live` each left the whole suite green, because
    `_stopping` is only populated by the stop path in a later ticket. A section
    headed "the overlay applies to every state" containing one test that
    asserts nothing IS stopping is not coverage.
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
    from hitchrail.tmux import Tmux

    def missing(argv: list[str]) -> object:
        raise FileNotFoundError(2, "No such file or directory", "tmux")

    sessions_dir = root / ".sessions"
    sessions_dir.mkdir(exist_ok=True)
    engine = Engine(
        Config(root=root, sessions_dir=sessions_dir),
        tmux=Tmux(prefix="hr-", run=missing),  # type: ignore[arg-type]
        procs_fn=procs_from(ps_row(PANE, 1) + ps_row(AGENT, PANE, project="vessel")),
        meminfo_fn=lambda: "MemAvailable: 8388608 kB\n",
    )
    with pytest.raises(MachineUnreadable):
        engine.list()
