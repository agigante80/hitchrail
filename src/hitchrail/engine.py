"""State derivation: four states from two independent scans.

**State is derived on demand and never stored.** There is no database and no
session registry, so there is nothing to drift.

Derivation runs in two directions, and the second one is the whole point. For
each prefixed tmux session, find the agent process it owns; then INDEPENDENTLY
scan for agent processes no pane owns. A tool that only asks tmux reports an
agent that outlived its terminal as `stopped`, and invites you to start a
second one in the same folder.

One piece of state is not derived: the in flight graceful stop, held in memory,
keyed by session name, deliberately not persisted. It is an overlay on the four
states, not a fifth. If Hitchrail restarts mid stop that knowledge is lost and
the session reads as `running` again, which is the truth; a `stopping` marker
that outlived the process would be a lie.

Every external surface is injected: tmux, the process table, memory readings
and the clock. That is what makes this testable without a machine.

This module is in the engine layer and imports nothing from the web layer;
`lint-imports` enforces it.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from hitchrail import claude_ipc, discovery, ram
from hitchrail.config import Config
from hitchrail.procs import ProcTable, snapshot
from hitchrail.tmux import Tmux


class EngineError(Exception):
    """Anything the engine refuses to do, and the base the API maps from."""


class UnknownProject(EngineError):
    """No such folder in the root."""


class MachineUnreadable(EngineError):
    """The process table could not be read, so no state can be derived.

    An ERROR rather than a state, deliberately. `ProcTable.ok` distinguishes
    "nothing is running" from "we could not look", and rendering the second as
    the first tells the user something false about their machine: every running
    agent would appear as `stale` or `stopped`. The design settles it, "if
    Hitchrail cannot determine a session's state, it says so rather than
    guessing", and it must not become a fifth state, because the table below
    has four and the in flight stop is an overlay rather than a member.

    Note this is NOT the same as tmux returning no sessions. An empty pane map
    is the ordinary state of a machine with nothing started.
    """


class State(StrEnum):
    """A `StrEnum` so the wire format is the NAME.

    An `IntEnum` would put the ordering into the API, and inserting a fifth
    member later would change what an old client reads.
    """

    RUNNING = "running"
    STALE = "stale"
    DETACHED = "detached"
    STOPPED = "stopped"


@dataclass(frozen=True)
class Session:
    """One project's derived state. Frozen: nothing holds one and mutates it."""

    name: str
    state: State
    pid: int | None = None
    ram_mb: int = 0
    uptime_s: int = 0
    url: str | None = None
    stopping: bool = False
    protected: bool = False

    def as_dict(self) -> dict[str, object]:
        """Serialising a session is not HTTP knowledge.

        The engine needs this to publish events, the import contract forbids
        borrowing a formatter from the server, and a second copy of this shape
        would drift from the first.
        """
        return {
            "name": self.name,
            "state": str(self.state),
            "pid": self.pid,
            "ram_mb": self.ram_mb,
            "uptime_s": self.uptime_s,
            "url": self.url,
            "stopping": self.stopping,
            "protected": self.protected,
        }


@dataclass(frozen=True)
class _Machine:
    """One consistent look at the machine, taken once per read.

    Two subprocess calls answer every project. Asking tmux per project is a
    spawn per row, and the design draws fifty rows.
    """

    table: ProcTable
    pane_pids: dict[str, int]
    owned: frozenset[int]


class Engine:
    """Derivation, and in later tickets the session lifecycle."""

    def __init__(
        self,
        config: Config,
        tmux: Tmux | None = None,
        procs_fn: Callable[[], ProcTable] | None = None,
        meminfo_fn: Callable[[], str] | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        bus: object | None = None,
    ) -> None:
        self.config = config
        self.tmux = tmux or Tmux(prefix=config.session_prefix, socket=config.tmux_socket)
        self._procs_fn = procs_fn or snapshot
        self._meminfo_fn = meminfo_fn or ram.read_meminfo
        self._clock = clock
        self._sleep = sleep
        self._bus = bus
        # The one piece of state that is not derived. Memory only, and lost on
        # restart on purpose: see the module docstring.
        self._stopping: dict[str, float] = {}

    # -- reading -------------------------------------------------------

    def _look(self) -> _Machine:
        """One tmux call and one `ps` call, whatever the project count."""
        table = self._procs_fn()
        if not table.ok:
            raise MachineUnreadable(
                "the process table could not be read, so no session state can "
                "be determined; this is not the same as nothing running"
            )
        pane_pids = self.tmux.pane_pids()
        owned: set[int] = set()
        for pid in pane_pids.values():
            owned.add(pid)
            # Descendants, not children: a shell usually sits between the pane
            # and the agent, and an agent one level down that is not counted as
            # owned is reported as somebody else's orphan.
            owned.update(p.pid for p in table.descendants(pid))
        return _Machine(table=table, pane_pids=pane_pids, owned=frozenset(owned))

    def list(self) -> list[Session]:
        machine = self._look()
        return [
            self._derive(name, machine) for name in discovery.list_projects(self.config.root)
        ]

    def get(self, name: str) -> Session:
        return self._derive(name, self._look())

    def available_mb(self) -> int:
        return ram.available_mb(self._meminfo_fn())

    def stopping_since(self, name: str) -> float | None:
        """When a graceful stop was requested, or None. Memory only."""
        return self._stopping.get(name)

    # -- derivation ----------------------------------------------------

    def _derive(self, name: str, machine: _Machine) -> Session:
        protected = self.config.self_project is not None and name == self.config.self_project
        # The SANITIZED name, because that is what tmux stored. Looking up the
        # raw name finds nothing and reports stopped while the agent runs.
        pane_pid = machine.pane_pids.get(self.tmux.session_name(name))

        if pane_pid is not None:
            agent = machine.table.first_matching_in_tree(
                pane_pid, claude_ipc.REMOTE_CONTROL_MARKER
            )
            if agent is not None:
                return self._live(name, agent.pid, machine, State.RUNNING, protected)
            # A session with no agent in it. Not stopped: the shell is there.
            return Session(
                name=name,
                state=State.STALE,
                stopping=name in self._stopping,
                protected=protected,
            )

        orphan = self._find_detached(name, machine)
        if orphan is not None:
            return self._live(name, orphan, machine, State.DETACHED, protected)

        return Session(
            name=name,
            state=State.STOPPED,
            stopping=name in self._stopping,
            protected=protected,
        )

    def _find_detached(self, name: str, machine: _Machine) -> int | None:
        """An agent that outlived its terminal.

        Without this, such a session reads as stopped while it is very much
        alive, and starting again gives you two agents in one folder.

        Matched on the marker followed by the project name at the END of the
        command line, not on a bare substring: a command line for project `ab`
        must not satisfy a lookup for `a`, which is the tmux prefix footgun one
        layer up. **That depends on the project name being the last element of
        `claude_ipc.launch_argv`.** Append a flag after it and every detached
        agent becomes invisible, silently. There is a test that builds the
        process args by CALLING `launch_argv` for exactly that reason.
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
        suffix = " ".join(claude_ipc.launch_argv(self.config.agent_binary, name)[1:])
        for proc in machine.table.matching(claude_ipc.REMOTE_CONTROL_MARKER):
            if proc.pid in machine.owned:
                continue
            if proc.args.rstrip().endswith(suffix):
                return proc.pid
        return None

    def _live(
        self, name: str, pid: int, machine: _Machine, state: State, protected: bool
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
            url=claude_ipc.bridge_url(pid, self.config.sessions_dir),
            stopping=name in self._stopping,
            protected=protected,
        )
