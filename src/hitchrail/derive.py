"""Deriving what is running, from one look at the machine.

Split out of `engine` at #50, along the seam the design already names: this
module answers "what state is this project in", and the engine acts on the
answer. Nothing here mutates anything, and nothing here spawns or signals, so
the whole file can be read as a question rather than a decision.

The split is also why the parameters are explicit rather than an `Engine`.
Derivation needs the config, tmux, and whether a graceful stop is in flight;
passing those in keeps the dependency one way, and means these functions can
be tested with three plain values instead of a constructed engine.
"""

from __future__ import annotations

from collections.abc import Callable, Container
from dataclasses import dataclass

from hitchrail import claude_ipc
from hitchrail.config import Config
from hitchrail.procs import ProcTable
from hitchrail.sessions import MachineUnreadable, Session, State
from hitchrail.tmux import Tmux, TmuxUnavailable


@dataclass(frozen=True)
class Machine:
    """One consistent look at the machine, taken once per read.

    Two subprocess calls answer every project. Asking tmux per project is a
    spawn per row, and the design draws fifty rows.
    """

    table: ProcTable
    pane_pids: dict[str, int]
    owned: frozenset[int]


def look(procs_fn: Callable[[], ProcTable], tmux: Tmux) -> Machine:
    """One tmux call and one `ps` call, whatever the project count."""
    table = procs_fn()
    if not table.ok:
        raise MachineUnreadable(
            "the process table could not be read, so no session state can "
            "be determined; this is not the same as nothing running"
        )
    try:
        pane_pids = tmux.pane_pids()
    except TmuxUnavailable as exc:
        # The other half of the same honesty. An empty pane map means no
        # sessions; a tmux that could not be run means we do not know, and
        # deriving `stopped` from it would report every running agent as
        # not running.
        raise MachineUnreadable(str(exc)) from exc
    owned: set[int] = set()
    for pid in pane_pids.values():
        owned.add(pid)
        # Descendants, not children: a shell usually sits between the pane
        # and the agent, and an agent one level down that is not counted as
        # owned is reported as somebody else's orphan.
        owned.update(p.pid for p in table.descendants(pid))
    return Machine(table=table, pane_pids=pane_pids, owned=frozenset(owned))


def derive(
    name: str, machine: Machine, config: Config, tmux: Tmux, stopping: Container[str]
) -> Session:
    protected = config.self_project is not None and name == config.self_project
    # The SANITIZED name, because that is what tmux stored. Looking up the
    # raw name finds nothing and reports stopped while the agent runs.
    pane_pid = machine.pane_pids.get(tmux.session_name(name))

    if pane_pid is not None:
        agent = machine.table.first_matching_in_tree(pane_pid, claude_ipc.REMOTE_CONTROL_MARKER)
        if agent is not None:
            return live(name, agent.pid, machine, State.RUNNING, protected, config, stopping)
        # A session with no agent in it. Not stopped: the shell is there.
        return Session(
            name=name,
            state=State.STALE,
            stopping=name in stopping,
            protected=protected,
        )

    orphan = find_detached(name, machine, config)
    if orphan is not None:
        return live(name, orphan, machine, State.DETACHED, protected, config, stopping)

    return Session(
        name=name,
        state=State.STOPPED,
        stopping=name in stopping,
        protected=protected,
    )


def find_detached(name: str, machine: Machine, config: Config) -> int | None:
    """An agent that outlived its terminal.

    Without this, such a session reads as stopped while it is very much
    alive, and starting again gives you two agents in one folder.

    Matched on the argv tail rather than a bare substring: a command line
    for project `ab` must not satisfy a lookup for `a`, which is the tmux
    prefix footgun one layer up.

    An earlier version matched only the marker and the name, and warned
    here that it depended on the project name being last in `launch_argv`.
    **Building the suffix from `launch_argv` removed that dependency**, so
    the warning is gone with it: appending a flag after the project name
    now changes both sides together. The tests build their process rows the
    same way, so the two cannot drift apart.

    The binary is stripped (`[1:]`) on purpose: an operator who changes
    `--agent-binary`, or an `env` wrapper at argv[0], must not blind the
    scan for agents that are already running.
    """
    # The WHOLE argv tail, not just the marker and the name. Matching on
    # those two alone claims any process that happens to mention both: a
    # `grep -r` for the marker across a project directory derived as a
    # detached agent for that project. Since a detached row refuses to
    # start, and a kill has no tmux session to kill, the project stayed
    # unstartable until the unrelated process exited.
    #
    # Built by calling `launch_argv`, so this cannot drift from what we
    # actually spawn, and the flags stay inside the quarantine.
    suffix = " ".join(claude_ipc.launch_argv(config.agent_binary, name)[1:])
    for proc in machine.table.matching(claude_ipc.REMOTE_CONTROL_MARKER):
        if proc.pid in machine.owned:
            continue
        if proc.args.rstrip().endswith(suffix):
            return proc.pid
    return None


def live(
    name: str,
    pid: int,
    machine: Machine,
    state: State,
    protected: bool,
    config: Config,
    stopping: Container[str],
) -> Session:
    proc = machine.table.by_pid.get(pid)
    return Session(
        name=name,
        state=state,
        pid=pid,
        ram_mb=machine.table.tree_rss_mb(pid),
        uptime_s=proc.etime_s if proc else 0,
        # `bridge_url` reads a file. `session_url` would capture a pane,
        # which is a subprocess per running row on every list. The link is
        # simply absent until the agent writes it, and the API's /url route
        # pays for the fallback when somebody actually asks for a link.
        url=claude_ipc.bridge_url(pid, config.sessions_dir),
        stopping=name in stopping,
        protected=protected,
    )
