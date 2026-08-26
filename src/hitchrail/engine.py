"""State derivation and the session lifecycle.

What a session IS, and every refusal, live in `sessions.py`; this module is
what derives and drives them. Both are re exported here, so `from
hitchrail.engine import State` keeps working for the callers that already do.

Four states from two independent scans.

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

import builtins
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from hitchrail import claude_ipc, discovery, ram
from hitchrail.config import Config
from hitchrail.events import EventBus
from hitchrail.procs import ProcTable, snapshot
from hitchrail.sessions import (
    AlreadyRunning,
    EngineError,
    Locked,
    MachineUnreadable,
    MemoryNeedsAck,
    MemoryRefused,
    NotRunning,
    Protected,
    Session,
    StartFailed,
    State,
    UnknownProject,
)
from hitchrail.tmux import Tmux, TmuxUnavailable


@dataclass(frozen=True)
class _Machine:
    """One consistent look at the machine, taken once per read.

    Two subprocess calls answer every project. Asking tmux per project is a
    spawn per row, and the design draws fifty rows.
    """

    table: ProcTable
    pane_pids: dict[str, int]
    owned: frozenset[int]


logger = logging.getLogger(__name__)


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
        bus: EventBus | None = None,
    ) -> None:
        self.config = config
        self.tmux = tmux or Tmux(prefix=config.session_prefix, socket=config.tmux_socket)
        self._procs_fn = procs_fn or snapshot
        self._meminfo_fn = meminfo_fn or ram.read_meminfo
        self._clock = clock
        self._sleep = sleep
        self._bus: EventBus | None = bus
        # The one piece of state that is not derived. Memory only, and lost on
        # restart on purpose: see the module docstring.
        self._stopping: dict[str, float] = {}
        # Guarded for the same reason `_starting` is: stop, kill and the
        # expiry ticker all run on worker threads. Without it, iterating in
        # `expire_stops` while `stop` adds raises "dictionary changed size
        # during iteration", and that raise kills the ticker.
        self._stopping_guard = threading.Lock()
        # Per FOLDER, never global: starting one project must not block
        # starting another. Guarded because start runs on worker threads, which
        # is the whole reason the lock exists.
        self._starting: set[str] = set()
        self._starting_guard = threading.Lock()
        # Generous on purpose. Being too eager reports a working start as a
        # failure; being too patient is only a slow error message.
        self.start_grace = 8.0
        self.poll_interval = 0.25

    # -- reading -------------------------------------------------------

    def _look(self) -> _Machine:
        """One tmux call and one `ps` call, whatever the project count."""
        table = self._procs_fn()
        if not table.ok:
            raise MachineUnreadable(
                "the process table could not be read, so no session state can "
                "be determined; this is not the same as nothing running"
            )
        try:
            pane_pids = self.tmux.pane_pids()
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
        with self._stopping_guard:
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

    # -- the lifecycle -------------------------------------------------

    def attach_bus(self, bus: EventBus) -> None:
        """Wired after construction, because the API owns the bus's lifetime."""
        self._bus = bus

    def _announce(self, session: Session) -> None:
        """Never blocks and never raises, whatever the bus does.

        Called from engine code on worker threads. `EventBus.publish` already
        guarantees this; the guard means a future bus with a different contract
        cannot turn an announcement into a failed stop.
        """
        if self._bus is None:
            return
        # Deliberately broad. This is the last line of defence around a
        # notification: a bus that raised would turn a SUCCESSFUL stop into a
        # failed one, and the user would be told their agent did not stop when
        # it did. `EventBus.publish` already guarantees it does not raise; this
        # holds if a future bus does not.
        try:
            self._bus.publish(session.as_dict())
        except Exception:
            # Deliberately broad, and deliberately logged. This is the last
            # line of defence around a NOTIFICATION: a bus that raised would
            # turn a successful stop into a failed one, and the user would be
            # told their agent did not stop when it did. Silent, though, meant
            # "events stopped arriving" was unfalsifiable.
            logger.exception("could not announce %s", session.name)

    def _require_project(self, name: str) -> str:
        """The name must be one `scan` actually LISTS, and its directory.

        Two guarantees, and the first is the one that matters.

        **Identity is the folder, not the name.** `discovery.resolve_child`
        deliberately allows a symlink that stays inside the root, so `alpha`
        and `zebra` can be two names for one directory. #11 deduplicates them
        in `scan`, but `start` took a name directly and bypassed that: starting
        both spawned two agents in the same checkout, each invisible to the
        other's `AlreadyRunning` check, because `get("alpha")` looks up
        `hr-alpha` and scans for a command line naming `alpha`. That is the
        outcome the whole design exists to prevent, reached from the start path
        instead of the list path. Requiring a LISTED name closes it, because
        the listing is where the deduplication happens.

        And it makes "unknown" a distinct answer. Without it, `stop` on a name
        that is not a project reported `NotRunning`, which the interface cannot
        tell from a real stopped project, and Phase 5 could not map to 404
        rather than 409.
        """
        try:
            path = discovery.project_path(self.config.root, name)
        except (
            discovery.InvalidName,
            discovery.NoSuchProject,
            discovery.OutsideRoot,
            # A symlink loop. `Path.resolve` raises this, `scan` reports the
            # folder as unsupported, and without it here a loop shows in the
            # listing and then escapes as a bare RuntimeError when tapped.
            RuntimeError,
        ) as exc:
            raise UnknownProject(name) from exc
        if name not in discovery.list_projects(self.config.root):
            raise UnknownProject(name)
        return str(path)

    def _require_live(self, name: str) -> Session:
        """Unknown, protected and not running are three different answers.

        Collapsing them gives the interface one message for three situations a
        user would act on differently.
        """
        self._require_project(name)
        session = self.get(name)
        if session.protected:
            raise Protected(name)
        if session.state is State.STOPPED:
            raise NotRunning(name)
        return session

    def start(self, name: str, acknowledged: bool = False) -> Session:
        """Start an agent in a folder, once, with the machine's consent."""
        path_str = self._require_project(name)

        # Keyed on the resolved DIRECTORY, not the name. Two names for one
        # folder must not both hold a start, and the listing check above
        # already refuses the alias; this is the belt to that braces, because
        # the listing is recomputed per call and could change between them.
        with self._starting_guard:
            if path_str in self._starting:
                raise Locked(name)
            self._starting.add(path_str)
        try:
            return self._start_locked(name, path_str, acknowledged)
        finally:
            # In a finally, always. A lock that outlives a failed start makes
            # the folder permanently unstartable until Hitchrail restarts.
            with self._starting_guard:
                self._starting.discard(path_str)

    def _start_locked(self, name: str, path_str: str, acknowledged: bool) -> Session:
        current = self.get(name)
        if current.protected:
            raise Protected(name)
        if current.state in (State.RUNNING, State.DETACHED):
            # DETACHED counts. Starting over an agent that outlived its
            # terminal is exactly the two-agents-in-one-folder outcome the
            # whole design exists to prevent.
            raise AlreadyRunning(name)

        available = self.available_mb()
        verdict = ram.guard(
            available,
            need_mb=self.config.session_mb,
            hard_mb=self.config.hard_floor_mb,
            soft_mb=self.config.soft_floor_mb,
        )
        if verdict is ram.Verdict.HARD:
            raise MemoryRefused(available, self.config.session_mb)
        if verdict is ram.Verdict.SOFT and not acknowledged:
            raise MemoryNeedsAck(available, self.config.session_mb)

        try:
            if current.state is State.STALE:
                # A terminal with no agent in it. Reusing it would start the
                # new session in a pane already holding old scrollback.
                self.tmux.kill_session(name)
            self.tmux.new_session(
                name, path_str, claude_ipc.launch_argv(self.config.agent_binary, name)
            )
        except TmuxUnavailable as exc:
            raise MachineUnreadable(str(exc)) from exc
        return self._await_running(name)

    def _await_running(self, name: str) -> Session:
        """Poll until the agent appears, or the grace window runs out.

        A freshly spawned agent is not in the process table yet, so the first
        look after `new-session` finds nothing and the start looks failed. The
        window is BOUNDED and driven by the injected clock and sleep: a test
        that really waits is a test somebody deletes when the suite gets slow.

        It does not trust `new_session` having returned. tmux reports a failed
        `new-session` through a return code the write path discards, so the
        only reliable evidence a start worked is the agent appearing.
        """
        deadline = self._clock() + self.start_grace
        while True:
            started = self.get(name)
            if started.state is State.RUNNING:
                self._announce(started)
                return started
            if self._clock() >= deadline:
                raise StartFailed(self._safe_capture(name))
            self._sleep(self.poll_interval)

    def _safe_capture(self, name: str) -> str:
        """Pane output for an error message, never an error of its own.

        This runs while raising `StartFailed`, and a tmux that has gone away
        must not replace "your session did not start, here is why" with a
        different exception entirely.
        """
        try:
            return self.tmux.capture_pane(name, lines=40)
        except TmuxUnavailable:
            return ""

    def stop(self, name: str) -> Session:
        """Ask the agent to finish. Nothing is killed."""
        self._require_live(name)
        with self._stopping_guard:
            self._stopping[name] = self._clock()
        # One call, and the engine does not learn what a stop physically is.
        # Iterating the key sequence here would teach it three Claude Code
        # facts: that stopping is keystrokes, that it is a sequence of them,
        # and that they travel through a pane. The engine owns the policy, the
        # timeout, the marker and the refusal to escalate; the adapter owns the
        # mechanism.
        try:
            claude_ipc.request_stop(self.tmux, name)
        except TmuxUnavailable as exc:
            with self._stopping_guard:
                self._stopping.pop(name, None)
            raise MachineUnreadable(str(exc)) from exc
        updated = self.get(name)
        self._announce(updated)
        return updated

    def kill(self, name: str) -> Session:
        """The backstop, reachable at any point during a graceful wait.

        Deliberately not agent specific: killing the tmux session works
        whatever is running in it, which is exactly why it is reliable.
        """
        self._require_live(name)
        try:
            self.tmux.kill_session(name)
        except TmuxUnavailable as exc:
            raise MachineUnreadable(str(exc)) from exc
        # AFTER the kill, not before. Popping first meant a kill that failed
        # took the indicator with it, so a graceful stop still in flight looked
        # as though nobody had asked.
        with self._stopping_guard:
            self._stopping.pop(name, None)
        updated = self.get(name)
        self._announce(updated)
        return updated

    # `builtins.list`, not `list`. This class defines a method called `list`,
    # which shadows the builtin for every annotation after it, and mypy reads
    # the bare form as "returns Engine.list". The design names that method
    # `list`, so the qualified builtin is the smaller compromise.
    def expire_stops(self) -> builtins.list[str]:
        """Drop stop markers older than the timeout, and say so.

        Expiry means "we stopped waiting", never "escalate". The session is
        still alive and the decision to kill it belongs to a person: an
        automatic kill is a destructive action taken while they were not
        looking.

        It announces, because the person watching the timer has to learn the
        wait ended. An expiry visible only on the next poll is one the
        interface cannot report.
        """
        now = self._clock()
        with self._stopping_guard:
            # A snapshot, taken under the lock. Iterating the live dict while
            # `stop` adds on another thread raises, and that raise kills the
            # ticker Phase 5 drives this from.
            candidates = [
                (name, began)
                for name, began in self._stopping.items()
                if now - began >= self.config.stop_timeout
            ]
            # No "is it still the same stop" check, deliberately. The
            # snapshot and the removal are inside ONE lock, so nothing can
            # install a fresh marker between them, and a guard against that
            # would be a condition that cannot be false. This module removed
            # one of those from `Tmux.kill_session` for the same reason: a
            # guard that looks meaningful and cannot execute is worse than
            # none, because a reader stops looking.
            #
            # If the announce loop below is ever moved inside the lock, or the
            # snapshot taken outside it, that stops being true.
            expired = [name for name, _began in candidates]
            for name in expired:
                del self._stopping[name]
        # Announced outside the lock: `get` does two subprocess calls, and
        # holding a lock across those would serialise every stop behind them.
        for name in expired:
            self._announce(self.get(name))
        return expired

    def logs(self, name: str, lines: int = 40) -> str:
        """The tail of a pane."""
        # A real guard now. This read `self.get(name)` with a comment saying it
        # stopped an unknown project returning empty output; `get` cannot
        # raise, so it did nothing but spend two subprocess calls arriving
        # there.
        self._require_project(name)
        try:
            return self.tmux.capture_pane(name, lines=lines)
        except TmuxUnavailable as exc:
            raise MachineUnreadable(str(exc)) from exc

    def session_url(self, name: str) -> claude_ipc.SessionUrl | None:
        """The link, paid for on demand.

        The EXPENSIVE lookup listing deliberately skips: it captures a pane.
        Returns the source alongside the URL, because a scraped one can be
        scrollback from a session that ended hours ago.
        """
        self._require_project(name)
        session = self.get(name)
        if session.pid is None:
            return None
        return claude_ipc.session_url(
            session.pid, self.config.sessions_dir, self._safe_capture(name)
        )


__all__ = [
    "AlreadyRunning",
    "Engine",
    "EngineError",
    "Locked",
    "MachineUnreadable",
    "MemoryNeedsAck",
    "MemoryRefused",
    "NotRunning",
    "Protected",
    "Session",
    "StartFailed",
    "State",
    "UnknownProject",
]
