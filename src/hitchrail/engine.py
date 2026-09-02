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

from hitchrail import claude_ipc, derive, discovery, ram
from hitchrail.config import Config
from hitchrail.derive import Machine
from hitchrail.events import EventBus
from hitchrail.procs import ProcTable, snapshot
from hitchrail.sessions import (
    AlreadyRunning,
    EngineError,
    Locked,
    MachineUnreadable,
    MemoryNeedsAck,
    MemoryRefused,
    NoAgent,
    NotRunning,
    Protected,
    Session,
    StartFailed,
    State,
    StopRefused,
    UnknownProject,
)
from hitchrail.tmux import Tmux, TmuxUnavailable

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
        #
        # The lock covers MUTATION and ITERATION. `_derive` reads
        # `name in self._stopping` without it, deliberately: a membership test
        # is atomic under the GIL and cannot see a torn dict, and taking the
        # lock there would put it on the path of every derived row, which is
        # once per project per listing.
        self._stopping_guard = threading.Lock()
        # Per FOLDER, never global: starting one project must not block
        # starting another. Guarded because start runs on worker threads, which
        # is the whole reason the lock exists.
        self._starting: set[str] = set()
        self._starting_guard = threading.Lock()
        # Generous on purpose. Being too eager reports a working start as a
        # failure; being too patient is only a slow error message.
        self.start_grace = 8.0
        # Much shorter than `start_grace`: a killed process is already gone in
        # the normal case, and this only covers the moment between tmux
        # returning and the kernel reaping. Waiting longer would block a caller
        # to hide a state that, past a second or two, is genuinely true.
        self.kill_grace = 2.0
        self.poll_interval = 0.25

    # -- reading -------------------------------------------------------

    def _look(self) -> Machine:
        return derive.look(self._procs_fn, self.tmux)

    def _derive(self, name: str, machine: Machine) -> Session:
        # `self._stopping` is passed unguarded on purpose: see the note on
        # `_stopping_guard`. `derive` only asks `name in stopping`.
        session = derive.derive(name, machine, self.config, self.tmux, self._stopping)
        if session.state is State.STOPPED:
            # Reconciled on read, which is the only place the transition is
            # visible: nothing calls us when an agent exits. Without this the
            # marker survives a stop that WORKED, and `expire_stops` reports it
            # as a timeout thirty seconds later, telling the user their agent
            # would not stop when it had already gone.
            with self._stopping_guard:
                self._stopping.pop(name, None)
        return session

    def list(self, listing: discovery.Listing | None = None) -> list[Session]:
        """Every project, derived from one look at the machine.

        `listing` is for a caller that has already scanned the root and needs
        the unsupported folders too. `discovery.list_projects` IS
        `scan(root).projects`, so without this the API walked the root twice
        for one response: once here, once for its own `scan`. The cost is the
        smaller half. The two walks could DISAGREE, so a folder created between
        them appeared in one answer and not the other, in the same JSON body.

        Passing nothing keeps the plain behaviour, which is what every caller
        that only wants sessions should do.
        """
        machine = self._look()
        names = (
            discovery.list_projects(self.config.root)
            if listing is None
            else list(listing.projects)
        )
        return [self._derive(name, machine) for name in names]

    def get(self, name: str) -> Session:
        return self._derive(name, self._look())

    def available_mb(self) -> int:
        return ram.available_mb(self._meminfo_fn())

    def machine_memory(self) -> tuple[int, int | None]:
        """Available and total, in megabytes, from ONE read of the file.

        One read on purpose. Reading twice lets the figure and the proportion
        the interface draws from them come from different instants, which is a
        small lie but a visible one while memory is moving.

        **The two halves fail differently, and that asymmetry is the point.**
        `available` is what the memory guard decides on, so an unreadable one
        raises: guessing it would approve a start on an exhausted machine.
        `total` is only ever a denominator for a bar, so an unreadable one is
        `None` and the interface draws no bar.

        A first version raised for both, which made a missing `MemTotal` return
        503 for the whole listing. That is a cosmetic figure taking the entire
        page down, and it is the wrong direction: the rows are what the person
        came for.
        """
        text = self._meminfo_fn()
        try:
            available = ram.available_mb(text)
        except ValueError as exc:
            # `MachineUnreadable`, not a bare ValueError. A meminfo we cannot
            # read IS a machine we cannot read, and the API already has a code
            # and a 503 for that. Left raw it escaped as an unhandled
            # exception, so the route answered 500 with a traceback rather
            # than the envelope it documents.
            raise MachineUnreadable(str(exc)) from exc
        try:
            return available, ram.total_mb(text)
        except ValueError:
            logger.warning("MemTotal is unreadable, so no memory proportion is reported")
            return available, None

    def stopping_since(self, name: str) -> float | None:
        """When a graceful stop was requested, or None. Memory only."""
        with self._stopping_guard:
            return self._stopping.get(name)

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
        try:
            self._bus.publish(session.as_dict())
        except Exception:
            # Deliberately broad, and deliberately logged. A bus that raised
            # would turn a SUCCESSFUL stop into a failed one, and the user
            # would be told their agent did not stop when it did. Silent,
            # though, made "events stopped arriving" unfalsifiable.
            logger.exception("could not announce %s", session.name)

    def _require_addressable(self, name: str) -> None:
        """A name that could name a project. Nothing more.

        Used by the paths that ACT on a session that already exists, and
        deliberately weaker than `_require_startable`.

        A first version gated these on the listing too, and that made a LIVE
        session unkillable the moment its name stopped being listed. The worst
        case is a migration one: a leftover `hr-alpha` is exactly what the
        alias bug produced, so anybody who hit it could no longer clean it up
        through Hitchrail. A folder renamed under a running agent did the same.

        Creating and destroying are not the same question. Identity has to be
        unique where a NEW agent is created, or two land in one folder.
        Destroying has to stay reachable, because the design keeps the kill
        backstop available throughout and surfaces `detached` precisely so a
        person can act on it. So this checks the name is safe and stops there;
        a name with nothing behind it still reaches `NotRunning`, which is the
        honest answer rather than a refusal.
        """
        try:
            discovery.validate_name(name)
        except discovery.InvalidName as exc:
            raise UnknownProject(name) from exc

    def _require_startable(self, name: str) -> str:
        """A name the listing actually RETURNS, and its directory.

        **Identity is the folder, not the name.** `discovery.resolve_child`
        deliberately allows a symlink that stays inside the root, so `alpha`
        and `zebra` can be two names for one directory. #11 deduplicates them
        in `scan`, but `start` took a name directly and bypassed that: starting
        both spawned two agents in the same checkout, each invisible to the
        other's `AlreadyRunning` check, because `get("alpha")` looks up
        `hr-alpha` and scans for a command line naming `alpha`. Requiring a
        LISTED name closes it, because the listing is where the deduplication
        happens.

        The listing is checked FIRST so a root that has gone away reports
        `RootUnavailable` here as it does from `list()`, rather than being
        flattened into "no such project" by the existence check below.
        """
        if name not in discovery.list_projects(self.config.root):
            raise UnknownProject(name)
        try:
            return str(discovery.project_path(self.config.root, name))
        except (
            discovery.InvalidName,
            discovery.NoSuchProject,
            discovery.OutsideRoot,
            # A symlink loop. `Path.resolve` raises `RuntimeError` for one on
            # 3.11 and 3.12; 3.13 reimplemented it over `os.path.realpath` and
            # returns the path unchanged, so the loop arrives as
            # `NoSuchProject` there instead. `OSError` covers the filesystem
            # failing underneath. All three mean the same thing to a caller.
            RuntimeError,
            OSError,
        ) as exc:
            raise UnknownProject(name) from exc

    def _require_live(self, name: str) -> Session:
        """Unknown, protected and not running are three different answers.

        Collapsing them gives the interface one message for three situations a
        user would act on differently.
        """
        self._require_addressable(name)
        session = self.get(name)
        if session.protected:
            raise Protected(name)
        if session.state is State.STOPPED:
            self._reject_if_not_a_project(name)
            raise NotRunning(name)
        return session

    def _reject_if_not_a_project(self, name: str) -> None:
        """Nothing live here, so the listing decides which refusal this is.

        Consulted ONLY on the way to a refusal, never on the way to an action,
        and that ordering is the whole design. Checking the listing first is
        what made a live session unreachable the moment its name stopped being
        listed (#42): a leftover `hr-alpha`, or a folder renamed under a
        running agent, could no longer be stopped at all.

        Asking last costs a scan on an error path and keeps both answers
        honest. A name with a live session behind it never reaches here, so it
        stays actionable whatever the listing says. A name with nothing behind
        it is `unknown_project` if the root has never heard of it, and
        `not_running` if it is a real project that simply is not running, which
        is a 404 and a 409 the interface has to tell apart (#47).
        """
        if name not in discovery.list_projects(self.config.root):
            raise UnknownProject(name)

    def start(self, name: str, acknowledged: bool = False) -> Session:
        """Start an agent in a folder, once, with the machine's consent."""
        path_str = self._require_startable(name)

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
                # The start worked, so stop keeping the pane alive past its
                # process. Left on, a later graceful exit would leave a dead
                # pane and the session would linger, so the engine would derive
                # `stale` where the truth is `stopped`. See #66.
                self._release_pane(name)
                self._announce(started)
                return started
            if self._clock() >= deadline:
                raise StartFailed(self._dead_start_output(name))
            self._sleep(self.poll_interval)

    def _release_pane(self, name: str) -> None:
        """Undo `new_session`'s `remain-on-exit`, never fatally.

        A start that worked must not be reported as a failure because tidying
        up afterwards did not. The cost of failing to clear it is a session
        that lingers after its agent exits, which reads as `stale`: wrong, but
        honest, and visible.
        """
        try:
            self.tmux.keep_pane_on_exit(name, False)
        except TmuxUnavailable:
            logger.warning("could not clear remain-on-exit for %s", name)

    def _dead_start_output(self, name: str) -> str:
        """What the agent printed on its way out, and then no session.

        The whole point of #66. `new_session` keeps the pane alive past its
        process precisely so this read has something to find: without it the
        pane, the window, the session and the server are gone inside fifty
        milliseconds and this returns nothing at all.

        The WHOLE scrollback, because tmux writes its own "Pane is dead
        (status N)" line into the visible pane. A bounded read of a dead pane
        can return that and nothing else, while what the agent printed has
        scrolled above it. That status line is worth keeping: it is the exit
        code, which nothing else in this system reports.

        The session is then killed ONLY if its pane is actually dead.

        That condition is the whole of the care here. `StartFailed` also fires
        when an agent is merely SLOW to appear: a loaded machine, a cold cache,
        a grace window that was generous enough yesterday. Killing on every
        timeout would end an agent that was starting perfectly well, which is
        strictly worse than the problem this method exists to solve. A dead
        pane is observable precisely because `new_session` kept it, and an
        undeterminable answer counts as alive.

        Left alive, the session reads as `stale`, which is honest and already
        drawn, and a person can stop it from the interface.

        `kill_session` is prefix scoped in the adapter and that is not relaxed
        here.
        """
        output = self._safe_capture(name, lines=0)
        try:
            if self.tmux.pane_is_dead(name):
                self.tmux.kill_session(name)
            else:
                logger.info(
                    "%s did not appear in time but its pane is alive, so it is "
                    "left running rather than killed",
                    name,
                )
        except TmuxUnavailable:
            # The message matters more than the tidying. A machine that has
            # lost tmux will not be told about it by this path.
            logger.warning("could not clean up the dead session for %s", name)
        return output

    def _safe_capture(self, name: str, lines: int = 40) -> str:
        """Pane output for an error message, never an error of its own.

        This runs while raising `StartFailed`, and a tmux that has gone away
        must not replace "your session did not start, here is why" with a
        different exception entirely.
        """
        try:
            return self.tmux.capture_pane(name, lines=lines)
        except TmuxUnavailable:
            return ""

    def stop(self, name: str) -> Session:
        """Ask the agent to finish. Nothing is killed."""
        session = self._require_live(name)
        # Refused from the STATE, before any subprocess and before any key
        # (#98). `_require_live` admits `stale` and `detached`, and neither has
        # an agent to ask:
        #
        # `stale` is a tmux session whose agent is gone, so the pane holds a
        # shell. The old sequence typed at it and achieved nothing, verified
        # against a real tmux: the quit command an agent understands is not one
        # a shell does, so bash answers "No such file or directory" and the
        # session survives the whole thirty second wait. Typing there was the
        # #91 authority hazard bought for nothing.
        #
        # `detached` has no tmux session at all, so the keys went to a pane
        # that was not there and the API still answered 202: a stop reporting
        # success that could not have worked.
        #
        # Deciding here rather than letting the adapter fail to recognise the
        # screen, because the engine derived both facts already. A refusal
        # built on a capture that came back empty cannot tell these apart from
        # a capture that failed.
        if session.state is State.STALE:
            raise NoAgent(
                f"the tmux session for {name} holds no agent, so there is "
                "nothing to ask to exit; killing the session clears it and "
                "no agent is lost, though the pane may still hold something "
                "else"
            )
        if session.state is State.DETACHED:
            raise NoAgent(
                f"the agent for {name} has no tmux session, so there is no "
                f"terminal to type into; its process, {session.pid}, has to be "
                "ended directly"
            )
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
        except claude_ipc.StopNotSafe as exc:
            # The marker goes back for the same reason a vanished tmux takes it
            # back: a wait must not outlive a request that was never sent. The
            # adapter looked at the pane and declined to ask the agent to exit,
            # so nothing is coming and a spinner would be describing nothing.
            #
            # Not "the agent is exactly as it was", which is what this said
            # first and is false: the adapter sends keys before it decides.
            # What is true is that no exit was requested.
            #
            # Translated at this boundary rather than let through. The server
            # catching a `claude_ipc` exception would put Claude Code knowledge
            # in the HTTP layer, which is the whole point of the quarantine.
            with self._stopping_guard:
                self._stopping.pop(name, None)
            raise StopRefused(str(exc)) from exc
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
        updated = self._await_gone(name)
        self._announce(updated)
        return updated

    def _await_gone(self, name: str) -> Session:
        """Poll until the killed agent actually leaves the process table.

        `tmux kill-session` returns before the process finishes dying, so the
        pane map is already empty while the agent is still listed. Derivation
        is right to call that `detached`: it is describing the machine
        accurately. It is a terrible thing to hand back from `kill`, though,
        because the user asked to kill and is told they now have a detached
        agent with a pid, which reads as the kill having failed and orphaned
        something.

        So the wait is here rather than in derivation, which stays honest, and
        it is the same shape as `_await_running`: BOUNDED, and driven by the
        injected clock and sleep so no test really waits.

        A timeout returns whatever is true rather than raising. If the process
        genuinely will not die, `detached` with its pid is the correct answer
        and the user needs to see it: that is the state the design surfaces on
        purpose so a person can act on it. This decision belongs to the stop
        sequence and was raised against it on #49.
        """
        deadline = self._clock() + self.kill_grace
        while True:
            settled = self.get(name)
            if settled.state is not State.DETACHED:
                return settled
            if self._clock() >= deadline:
                return settled
            self._sleep(self.poll_interval)

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
        #
        # Outside the lock also means `get` can fail out here, and the markers
        # are already gone by then. `_announce` cannot raise, but `get` can:
        # it reads the machine, and a tmux that has gone away is exactly the
        # MachineUnreadable case. Uncaught, that raise leaves the ticker dead,
        # so no stop expires again for the life of the process, which is the
        # failure this method's own docstring says it guards against. Losing
        # one announcement is a stale timer on a page; losing the ticker is
        # every timer, forever.
        for name in expired:
            try:
                self._announce(self.get(name))
            except MachineUnreadable:
                logger.warning(
                    "stop timer for %s expired but the machine could not be "
                    "read, so no event was sent; the marker is already dropped",
                    name,
                )
        return expired

    def logs(self, name: str, lines: int = 40) -> str:
        """The tail of a pane."""
        # A real guard now. This read `self.get(name)` with a comment saying it
        # stopped an unknown project returning empty output; `get` cannot
        # raise, so it did nothing but spend two subprocess calls arriving
        # there. Addressable rather than startable: reading a pane must keep
        # working for a session whose folder is gone.
        self._require_addressable(name)
        if self.get(name).state is State.STOPPED:
            # Not `_require_live`: that also refuses the self project, and
            # reading the log of the session hosting Hitchrail is harmless and
            # occasionally the only way to see what it is doing.
            #
            # The point of the check is that empty output and no session are
            # different answers. Without it a name with nothing behind it
            # returns "", which a client cannot tell from a pane that has
            # printed nothing yet.
            self._reject_if_not_a_project(name)
            raise NotRunning(name)
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
        self._require_addressable(name)
        session = self.get(name)
        if session.pid is None:
            # Three answers, not two. A name the root has never heard of is a
            # 404; a real project that is not running is a 409; a running one
            # that has not published a link yet is `None`, which the route
            # turns into `url_pending`. Returning `None` for all three told a
            # client to "ask again shortly" about a typo.
            self._reject_if_not_a_project(name)
            if session.state is State.STOPPED:
                raise NotRunning(name)
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
    "NoAgent",
    "NotRunning",
    "Protected",
    "Session",
    "StartFailed",
    "State",
    "StopRefused",
    "UnknownProject",
]
