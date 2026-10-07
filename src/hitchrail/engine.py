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
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from hitchrail import attention, claude_ipc, derive, discovery, ram, settings, signals
from hitchrail.config import TOKEN_ENV, Config
from hitchrail.derive import Machine
from hitchrail.events import EventBus
from hitchrail.procs import ProcTable, snapshot
from hitchrail.roots import RootError, split_identifier
from hitchrail.sessions import (
    AlreadyRunning,
    EngineError,
    Gone,
    InvalidValue,
    Locked,
    MachineUnreadable,
    MemoryNeedsAck,
    MemoryRefused,
    NoAgent,
    NotAsking,
    NotDetached,
    NotOurs,
    NotRunning,
    OperatorDisabled,
    OperatorPinned,
    OwnedElsewhere,
    PidfdUnavailable,
    Protected,
    Session,
    StartFailed,
    State,
    StateUnwritable,
    StopRefused,
    UnknownProject,
    UnknownRoot,
)
from hitchrail.tmux import Tmux, TmuxUnavailable

logger = logging.getLogger(__name__)


def _no_session_here(session: Session, consequence: str) -> str:
    """Why a `detached` row cannot be acted on, without overclaiming (#85).

    Both refusals used to open "has no tmux session", which is the sentence
    #85 removed from the interface for being a claim this tool cannot make.
    Ownership is read from one `list-panes -a` against the server Hitchrail is
    configured to use, so "no session" is only ever "no session we found".

    When the owner IS known the message says so, because that is the one thing
    the person can act on: the agent is somewhere, and knowing where turns a
    dead end into an instruction.

    One builder rather than two f-strings, because these two messages went out
    of step with the row's copy by being edited separately, which is the whole
    shape of this defect.
    """
    if session.held_elsewhere is not None:
        return (
            f"the agent for {session.name} is in {session.held_elsewhere}, which "
            f"Hitchrail did not create, so there is {consequence} here; attach "
            f"there, or end its process, {session.pid}, directly"
        )
    return (
        f"the agent for {session.name} is in no tmux session Hitchrail can "
        f"address, so there is {consequence}; its process, {session.pid}, has "
        "to be ended directly"
    )


# Re-exported so the HTTP layer can check membership without importing the
# quarantine directly. **Membership only.** The rule this project keeps is that
# nothing outside `claude_ipc` ITERATES a key constant, because iterating is
# what encodes a sequence; asking whether one key is allowed encodes nothing.
ANSWER_KEYS = claude_ipc.ANSWER_KEYS


@dataclass(eq=False)
class StopMarker:
    """One graceful stop in flight (#242). Compared by identity, never value.

    `closing` is the wrap up: the prompt is queued behind the task and the
    sweep watches for the agent to finish both. `exiting` is the exit
    sequence sent, which is all a stop was before #242 and still is with no
    prompt configured.

    **No path claims a marker while something types into its pane.** `watch`
    is None while the prompt is being typed, and `typing` is True while the
    exit sequence is, whether the sweep or `stop()` types it (#406). A Stop
    on either is the no-op 202: a second sequence would interleave its keys
    with the first.

    **A caller that holds a marker removes it by identity**, through
    `Engine._drop`: a pop by name removes whatever marker is there now, which
    after a repeated Stop is a newer one than the caller holds. Three removals
    are by name on purpose (#407), because each ends every stop on the row,
    not one: `_derive` on a row it read `stopped`, `kill` before its
    `kill-session` and again after it, and `expire_stops`, whose snapshot and
    removal share one critical section.

    A claim that fails gives the marker back rather than replacing it: Exit
    now mutates the `closing` marker in place, and a refused exit restores
    `closing` and its watch on the same object (`Engine._give_back`).

    A claim writes `exit_at`, `ceiling` and `typing` BEFORE `phase`, and
    `_derive` reads `phase` first without the lock, so a reader that sees
    `exiting` sees the flags that came with it.

    `policy` is the stop policy when Stop was confirmed, and the one its
    expiry acts on (#419): the dialog promised it, and the page can change
    the live setting during the wait. Required, so no path forgets it.
    """

    began: float
    phase: Literal["closing", "exiting"]
    policy: str
    watch: claude_ipc.WrapUpWatch | None = None
    exit_at: float | None = None
    ceiling: bool = False
    typing: bool = False


class Engine:
    """Derivation, and in later tickets the session lifecycle."""

    def __init__(
        self,
        config: Config,
        tmux: Tmux | None = None,
        procs_fn: Callable[[], ProcTable] | None = None,
        meminfo_fn: Callable[[], str] | None = None,
        ceiling_fn: Callable[[int], int | None] | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        bus: EventBus | None = None,
        open_pidfd: Callable[[int], int] | None = None,
        send_signal: Callable[[int, int], None] | None = None,
        close_pidfd: Callable[[int], None] | None = None,
        owner_uid: Callable[[int], int] | None = None,
        cwd_of: Callable[[int], Path] | None = None,
    ) -> None:
        self.config = config
        # #113. Named here rather than inside `Tmux`, because which variable
        # holds the token is this application's vocabulary and tmux knows
        # nothing about it. An injected adapter is a test's own, untouched.
        self.tmux = tmux or Tmux(
            prefix=config.session_prefix,
            socket=config.tmux_socket,
            scrub_env=(TOKEN_ENV,),
        )
        self._procs_fn = procs_fn or snapshot
        # #107. The pidfd seam, held for `signals.py` (#274); a test hands in
        # a recorder through these parameters, which is why they stay here.
        self._pidfd = signals.Seam.with_defaults(
            open_pidfd, send_signal, close_pidfd, owner_uid, cwd_of
        )
        self._meminfo_fn = meminfo_fn or ram.read_meminfo
        # #243. Cached per pid for `ram.CEILING_TTL_S`, because the reader is
        # ten sysfs reads and the listing route asks once per running row on
        # every poll; the cost paragraph on `memory_ceiling_mb` has the
        # numbers. Keyed by pid only: a pid reused inside the window is read
        # afresh on the next expiry, the bound the attention overlay accepts.
        self._ceiling_fn = ceiling_fn or ram.memory_ceiling_mb
        self._ceilings: dict[int, tuple[float, int | None]] = {}
        self._clock = clock
        self._sleep = sleep
        self._bus: EventBus | None = bus
        # The one piece of state that is not derived. Memory only, and lost on
        # restart on purpose: see the module docstring.
        self._stopping: dict[str, StopMarker] = {}
        # Names whose LAST stop ran out of patience with the agent showing
        # something that needs a person (#101). In memory and not persisted,
        # for the same reason the stop marker is not: it describes one attempt,
        # and a marker that outlived the process would be a claim about a
        # screen nobody has looked at since.
        self._awaiting_input: set[str] = set()
        # The SECOND source of the same flag, added at #100, and the second
        # thing in this class that is remembered rather than derived.
        #
        # `_awaiting_input` above describes one stop ATTEMPT. This describes a
        # standing observation: a running row with no session link that was
        # last seen showing something other than an ordinary input box. Name to
        # the time it was observed, because a row the sweep did not reach this
        # pass keeps its last answer until `STUCK_TTL_S` rather than blinking
        # off, and a row it did reach is updated or removed outright.
        #
        # Not persisted, for the same reason neither of the others is: it is a
        # claim about a screen, and a claim that outlived the process would be
        # about a screen nobody has looked at since. A restart loses it and the
        # next sweep re establishes it within a second.
        self._stuck: dict[str, float] = {}
        # #182. Bumped by every `_forget_attention`, read by `scan_for_stuck`
        # around its capture. A sweep decides what is stuck OUTSIDE the lock,
        # deliberately, because capturing panes under it would hold it across a
        # subprocess. That leaves a window where a stop clears a project and
        # then an observation made BEFORE the clear puts it straight back.
        self._attention_epoch = 0
        # Guarded for the same reason `_starting` is: stop, kill and the
        # expiry ticker all run on worker threads. Without it, iterating in
        # `expire_stops` while `stop` adds raises "dictionary changed size
        # during iteration", and that raise costs the tick its expiries.
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
        # #154, #238. What the interface may change: which configured roots
        # are hidden, and the stop wait. `config.roots` stays every configured
        # root and is what anything that RESOLVES a name reads: a session in a
        # hidden root is still a session, and refusing it by name would be a
        # lie. `prefs.active_roots()` is what the listing shows, the sheet
        # creates in and the sweep reads.
        self.prefs = settings.Preferences(config)
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
        return derive.look(
            self._procs_fn, self.tmux, self.config.agent_config_path, self._ceiling_mb
        )

    def _ceiling_mb(self, pid: int) -> int | None:
        """`ram.memory_ceiling_mb`, remembered per pid for the TTL."""
        now = self._clock()
        cached = self._ceilings.get(pid)
        if cached is not None and now - cached[0] < ram.CEILING_TTL_S:
            return cached[1]
        ceiling = self._ceiling_fn(pid)
        self._ceilings[pid] = (now, ceiling)
        # Bounded: the table is a snapshot and pids come and go, so entries
        # older than the TTL are dropped here rather than kept for the life of
        # the process.
        #
        # **From a snapshot, with `pop`, and not by rebuilding the dict.** The
        # listing runs on the request executor and the attention sweep on its
        # own thread, and both arrive here. A comprehension iterating the live
        # dict while the other thread inserted raised "dictionary changed size
        # during iteration", reproduced under two threads in the suite: a 500
        # on the route the page polls hardest. `list(items())` completes under
        # the GIL and `pop` is atomic, so no lock is needed for a cache whose
        # worst case is one extra read.
        for p, v in list(self._ceilings.items()):
            if now - v[0] >= ram.CEILING_TTL_S:
                self._ceilings.pop(p, None)
        return ceiling

    def _derive(
        self, name: str, machine: Machine, needs_a_person: frozenset[str] | None = None
    ) -> Session:
        """One row. `needs_a_person` is computed ONCE per listing, not per row.

        **Passed in rather than read here, and the note on `_stopping_guard`
        is why.** That note says `_derive` deliberately reads `self._stopping`
        without the lock, because taking it here would put a lock acquisition
        on the path of every derived row. #100's second source needs the lock,
        since it iterates a dict rather than testing membership, so the union
        is built once by the caller and handed down. A version that built it
        here would acquire the lock and walk that dict once per project per
        listing, which is exactly what the existing note forbids.

        `None` is for the single row callers, where once per listing and once
        per row are the same thing.
        """
        if needs_a_person is None:
            needs_a_person = self._needs_a_person()
        # `self._stopping` is passed unguarded on purpose: see the note on
        # `_stopping_guard`. `derive` only asks `name in stopping`.
        session = derive.derive(
            name, machine, self.config, self.tmux, self._stopping, needs_a_person
        )
        # **The membership test comes first, and it is not a micro optimisation
        # (#178).** The note on `_stopping_guard` says `_derive` reads
        # `self._stopping` WITHOUT the lock, deliberately, because taking it
        # here would put it on the path of every derived row. This method then
        # took it on every STOPPED row, which on an ordinary machine is most of
        # them: measured at 18 acquisitions for one listing of a 16 project
        # root, where the note describes one.
        #
        # The cost was never the point. A comment that states a rule about the
        # method twenty lines below it, and is contradicted by that method, is a
        # defect in the record: the next reader either trusts the note and is
        # wrong about the code, or trusts the code and deletes the note.
        #
        # The test uses the note's own reasoning. A membership check is atomic
        # under the GIL and cannot see a torn dict, so it is safe unguarded, and
        # the lock is taken only when there is something to remove.
        if session.state is State.STOPPED and name in self._stopping:
            # Reconciled on read, which is the only place the transition is
            # visible: nothing calls us when an agent exits. Without this the
            # marker survives a stop that WORKED, and `expire_stops` reports it
            # as a timeout thirty seconds later, telling the user their agent
            # would not stop when it had already gone.
            with self._stopping_guard:
                gone = self._stopping.pop(name, None)
            # Only the call that removed the marker says so, since two
            # listings can both see STOPPED and race to this line.
            if gone is not None:
                logger.info(
                    "stop %s: the agent exited after %.1fs", name, self._clock() - gone.began
                )
            return session
        # #242. Unlocked, by `_stopping_guard`'s reasoning: one dict load, then
        # one attribute load each, `phase` first (see `StopMarker`).
        marker = self._stopping.get(name)
        if session.stopping and marker is not None:
            phase = marker.phase
            session = replace(session, stopping_phase=phase, stop_ceiling=marker.ceiling)
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
            discovery.list_root_projects(self.prefs.active_roots())
            if listing is None
            else list(listing.projects)
        )
        waiting = self._needs_a_person()
        return [self._derive(name, machine, waiting) for name in names]

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
            marker = self._stopping.get(name)
            return None if marker is None else marker.began

    def _done_typing(self, marker: StopMarker) -> None:
        """The sequence is out, or failed: a Stop may claim the marker again."""
        with self._stopping_guard:
            marker.typing = False

    def _give_back(
        self, name: str, marker: StopMarker, resume: claude_ipc.WrapUpWatch | None
    ) -> None:
        """Undo a claim whose sequence never went out.

        A refused Exit now goes back to the wrap up it interrupted (#407): the
        prompt WAS sent and is still queued, so the person, shown a refusal,
        is right to expect the wrap up to end in an exit. Every other claim
        has nothing to go back to and is dropped: a wait must not outlive a
        request that was never sent.
        """
        if resume is None:
            self._drop(name, marker)
            return
        with self._stopping_guard:
            if self._stopping.get(name) is marker:
                marker.exit_at, marker.ceiling, marker.typing = None, False, False
                marker.watch = resume
                marker.phase = "closing"

    def _drop(self, name: str, marker: StopMarker) -> None:
        """Remove `marker`, and only it: a newer stop's stays (#242)."""
        with self._stopping_guard:
            if self._stopping.get(name) is marker:
                del self._stopping[name]

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
        # #120: `name` is a qualified identifier now, so the folder allowlist
        # applies to its FOLDER half. Validating the whole thing rejected every
        # real identifier, because `~` is exactly the character the allowlist
        # forbids: the separator was doing its job and this check was reading
        # it as the thing it protects against.
        try:
            _, folder = split_identifier(name)
            discovery.validate_name(folder)
        except (discovery.InvalidName, RootError) as exc:
            raise UnknownProject(name) from exc
        # The label is NOT checked against the configured roots here, on
        # purpose (Phase 14 review of #107): a live `hr-main~alpha` left over
        # after a restart under a different label has to stay stoppable, the
        # #42 guarantee above, and the tmux routes are prefix scoped anyway.
        # `signal_detached` checks it, because a pid is not.

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
        if name not in discovery.list_root_projects(self.config.roots):
            raise UnknownProject(name)
        # `enabled = false` in the operator's file narrows what can be
        # STARTED, not only what is listed: the security audit of #154 read
        # the README's `confidential` example the way an operator would, as
        # "no agent runs there", and this is what makes that reading true.
        # A root the INTERFACE hid is not refused here: hiding is a listing
        # preference and the logs page can still start a row it shows.
        # Everything that resolves a name for stop, kill and logs stays on
        # `config.roots`, so an agent already in a disabled root can be ended.
        label, _ = split_identifier(name)
        if any(r.label == label and not r.enabled for r in self.config.roots):
            raise OperatorDisabled(
                f"root {label!r} is disabled in the operator's config file, so "
                f"nothing is started in it"
            )
        try:
            return str(discovery.resolve_identifier(self.config.roots, name))
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
        if name not in discovery.list_root_projects(self.config.roots):
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

        # Before anything is spawned. Whatever the last screen here was, it
        # belonged to a previous agent, and the row about to appear is a new
        # one: `attention.MIN_UPTIME_S` means the sweep will not look at it for
        # fifteen seconds, so a claim left standing here is one nothing would
        # correct.
        self._forget_attention(name)
        argv = claude_ipc.launch_argv(self.config.spawn_agent_binary, name)
        # The argv the scrub left (#113): the environment is withheld from
        # the child, never the arguments, so there is nothing in it to hide.
        logger.info("start %s: starting in %s with %s", name, path_str, argv)
        try:
            if current.state is State.STALE:
                # A terminal with no agent in it. Reusing it would start the
                # new session in a pane already holding old scrollback.
                self.tmux.kill_session(name)
            self.tmux.new_session(name, path_str, argv)
        except TmuxUnavailable as exc:
            self._abandon_partial_session(name)
            raise MachineUnreadable(str(exc)) from exc
        return self._await_running(name)

    def _abandon_partial_session(self, name: str) -> None:
        """Clean up a session `new_session` may have created before it failed.

        #102. `subprocess`'s timeout kills the tmux CLIENT it was waiting on. It
        does not kill the server and it undoes nothing the server already did,
        so `new_session` can report unavailable while the session exists with
        `remain-on-exit` on. Such a session never closes its pane when the
        process exits, so it lingers and the engine derives `stale` for as long
        as it lives: the person sees a project that will not start, and a row
        saying there is no agent in the session.

        **This asks rather than guesses, which is the distinction the ticket
        drew.** Assuming the session was created would kill something that may
        not exist; assuming it was not leaves exactly the defect. `has-session`
        answers, and the answer is acted on.

        **A failure here never replaces the original error.** The machine being
        unreadable is what the caller has to be told; if the tidy up cannot
        reach tmux either, that is the same cause showing twice, and reporting
        the second one would hide the first. `kill_session` is scoped by the
        prefix in `Tmux.__init__`, so this cannot reach a session we did not
        name.
        """
        try:
            if self.tmux.has_session(name):
                self.tmux.kill_session(name)
        except TmuxUnavailable:
            logger.warning(
                "could not check or clean up a partial session for %s; "
                "if it exists it will read as stale",
                name,
            )

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
                logger.info("start %s: the agent is running as pid %s", name, started.pid)
                if started.awaiting_trust:
                    # One of the two states that make a correct system look
                    # broken: the agent is up, and asking whether to trust
                    # the folder, so the row looks idle and nothing happens.
                    logger.info(
                        "start %s: the agent is waiting for its folder to be trusted", name
                    )
                self._announce(started)
                return started
            if self._clock() >= deadline:
                # The output goes to the caller, never here: it is pane
                # content, and a journal is persistent (#167).
                logger.warning(
                    "start %s: no agent appeared within %.0fs", name, self.start_grace
                )
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
        logger.info("stop %s: requested, the row reads %s", name, session.state)
        # A fresh attempt starts from nothing (#101). The flag describes ONE
        # stop, and a prompt the person has since answered would otherwise go
        # on being reported at them.
        self._forget_attention(name)
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
            raise NoAgent(_no_session_here(session, "no terminal to type into"))
        prompt = self.config.stop_prompt
        policy = self.prefs.stop_policy()
        now = self._clock()
        # #242. The claim: who may type is decided here, in one critical
        # section, and only the caller that wrote the marker types. The table
        # on the ticket is the whole rule.
        resume: claude_ipc.WrapUpWatch | None = None
        with self._stopping_guard:
            current = self._stopping.get(name)
            if current is not None and (
                current.typing or (current.phase == "closing" and current.watch is None)
            ):
                # Something is typing into this pane this moment, the prompt
                # or an exit sequence (#406). Typing the exit sequence now
                # would land in the middle of it.
                typing = None
            elif current is not None and current.phase == "closing":
                # "Exit now": a second Stop during the wait skips to the exit,
                # and never retypes the prompt. Mutated in place, never
                # replaced, so a refusal can hand the wrap up back (#407).
                resume = current.watch
                current.exit_at, current.ceiling, current.typing = now, False, True
                current.phase = "exiting"
                typing = current
            elif current is not None:
                # A repeated Stop on `exiting`, as before #242, keeping the
                # ceiling flag so the dialog still says why it is exiting.
                typing = StopMarker(
                    now, "exiting", policy, exit_at=now, ceiling=current.ceiling, typing=True
                )
            elif prompt is not None:
                typing = StopMarker(now, "closing", policy)
            else:
                typing = StopMarker(now, "exiting", policy, exit_at=now, typing=True)
            if typing is not None:
                self._stopping[name] = typing
        if typing is None:
            logger.info("stop %s: a sequence is still being typed into it, so nothing is", name)
            return session
        wrapping_up = typing.phase == "closing"
        # One call, and the engine does not learn what a stop physically is.
        # Iterating the key sequence here would teach it three Claude Code
        # facts: that stopping is keystrokes, that it is a sequence of them,
        # and that they travel through a pane. The engine owns the policy, the
        # timeout, the marker and the refusal to escalate; the adapter owns the
        # mechanism.
        try:
            if wrapping_up:
                assert prompt is not None
                claude_ipc.request_wrap_up(self.tmux, name, prompt, settle=self._sleep)
            else:
                claude_ipc.request_stop(self.tmux, name, settle=self._sleep)
        except TmuxUnavailable as exc:
            self._give_back(name, typing, resume)
            raise MachineUnreadable(str(exc)) from exc
        except claude_ipc.StopNotSafe as exc:
            logger.info("stop %s: refused, %s", name, exc)
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
            self._give_back(name, typing, resume)
            raise StopRefused(str(exc)) from exc
        except Exception:
            # Anything else, too (#407): a marker left `closing` with no watch
            # made every later Stop a no-op and was invisible to the sweep and
            # to expiry, so only a Kill could clear it.
            self._give_back(name, typing, resume)
            raise
        finally:
            self._done_typing(typing)
        if wrapping_up:
            with self._stopping_guard:
                if self._stopping.get(name) is typing:
                    typing.watch = claude_ipc.WrapUpWatch(sent_at=self._clock())
            logger.info(
                "stop %s: wrap up sent, waiting up to %gs for it",
                name,
                self.config.stop_prompt_timeout,
            )
        else:
            logger.info(
                "stop %s: exit requested, waiting up to %gs", name, self.prefs.stop_timeout()
            )
        updated = self.get(name)
        self._announce(updated)
        return updated

    def answer(self, name: str, key: str) -> Session:
        """Carry ONE keypress from a person to a prompt they read (#204).

        The narrowest mutating operation in this project, and every narrowing
        is a security property rather than a design preference:

        - **Only a key from `ANSWER_KEYS`.** The adapter checks, before it
          reads any pane, and there is no free text path to here at all.
        - **Only while the screen still asks.** The adapter re-reads the pane
          inside the send. The engine deliberately does NOT pre-check and pass
          the result down: two reads with a gap is the race this exists to
          close.
        - **Never chosen.** Nothing here picks a key, defaults one, or presses
          one on a timer. The operator read the question.

        Refused for the self project like every other mutating call. Hitchrail
        answering a prompt in its own session could type into the process
        serving the request.

        **The bound is "a session Hitchrail started", NOT "a folder inside a
        root".** Those coincide, because the only thing that creates a prefixed
        session is `start`, which resolves through the root boundary. But the
        looser wording is what let the `stale` case above through review: a
        stale pane satisfies "inside a configured root" and is not Claude Code.
        Reason about what is IN the pane, not about where the folder is.

        **Why this is not the deferred terminal.** `docs/roadmap.md` defers
        sending input to a session. That is an input box carrying arbitrary
        text on demand. This carries one key from a fixed set, only when the
        screen holds a question, in reply to words the operator read. The
        distinction lives in `ANSWER_KEYS` and in the adapter's re-read, and
        both have tests that fail if either is widened.
        """
        session = self._require_live(name)
        # **`stale` is refused for the same reason `stop` refuses it, and the
        # reason is stronger here.** A stale session is a terminal whose agent
        # has gone, so what is left in it is a shell. `stop` recorded that
        # relaying to it is the #91 authority hazard bought for nothing, because
        # what it relayed meant nothing to a shell.
        #
        # It is bought for something here: what this relays is chosen by a
        # person to be acted on, and a shell will act on it.
        #
        # **The adapter cannot make this decision**, which is why it is here.
        # Whether a screen is showing a question is answered by looking at the
        # screen, and a shell's own prompt can be indistinguishable from an
        # agent's. Only the engine knows there is no agent, and it knows it by
        # derivation rather than by looking. That asymmetry is the same one
        # `stop` names twenty lines above: a refusal built on a capture cannot
        # tell an empty screen from a failed read.
        #
        # A stale session can also be one whose terminal is dead rather than
        # shelled (#67). Then the relay goes nowhere and this route would answer
        # 200 for something that did not happen, which is what #83 fixed on
        # `kill` and #98 on `stop`.
        #
        # `docs/api.md` carries the mechanism, and #204 the measurement.
        if session.state is State.STALE:
            raise NoAgent(
                f"the tmux session for {name} holds no agent, so there is "
                "nothing there to answer; killing the session clears it and "
                "no agent is lost, though the pane may still hold a shell"
            )
        if session.state is State.DETACHED:
            raise NoAgent(_no_session_here(session, "no terminal to answer in"))
        # One call, like the stop. The engine does not learn that answering is
        # a keystroke, nor that the check is a pane read.
        try:
            claude_ipc.send_answer(self.tmux, name, key)
        except TmuxUnavailable as exc:
            raise MachineUnreadable(str(exc)) from exc
        except claude_ipc.AnswerNotSafe as exc:
            raise NotAsking(str(exc)) from exc
        return session

    def kill(self, name: str) -> Session:
        """The backstop, reachable at any point during a graceful wait.

        Deliberately not agent specific: killing the tmux session works
        whatever is running in it, which is exactly why it is reliable.

        **And why it cannot touch a detached agent** (#83). That agent has no
        session, so there is nothing here to target. The route used to answer
        200 anyway: `kill_session` addressed a name that does not exist,
        `Tmux._try` discarded the non zero return, and `_await_gone` polled a
        process that never left. Success reported for something that did not
        happen, which is worse than a refusal.

        Whether Hitchrail should gain the power to signal a bare pid was a
        design question with a security argument attached, and #107 answered
        it: `signal_detached`, its own route, scoped by a check in one order
        rather than by the prefix. This route stays what it was.
        """
        session = self._require_live(name)
        if session.state is State.DETACHED:
            raise NoAgent(_no_session_here(session, "nothing here to kill"))
        # Taken out BEFORE the kill, and handed back if it fails (#387). Taken
        # out only after, a listing landing between the two read the row
        # `stopped` with the marker still there and journalled the kill as
        # "the agent exited after", a graceful exit that never happened. The
        # give back is what the old order was for: a kill that failed must
        # not take the indicator of a stop still in flight with it.
        with self._stopping_guard:
            marker = self._stopping.pop(name, None)
        try:
            self.tmux.kill_session(name)
        except TmuxUnavailable as exc:
            if marker is not None:
                with self._stopping_guard:
                    self._stopping.setdefault(name, marker)
            raise MachineUnreadable(str(exc)) from exc
        # Before `_await_gone`, which reads the machine and can raise: the
        # kill happened whatever that read says.
        logger.info("kill %s: session killed", name)
        # A Stop that landed while the kill ran marked a row that is gone.
        with self._stopping_guard:
            self._stopping.pop(name, None)
        updated = self._await_gone(name)
        self._announce(updated)
        return updated

    def signal_detached(
        self, name: str, force: bool = False, seen_pid: int | None = None
    ) -> Session:
        """End an agent nothing addressable owns, through a handle (#107).
        The path, its order and its refusals are `signals.py`'s (#274)."""
        return signals.signal_detached(self, name, force, seen_pid)

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
    def _forget_attention(self, name: str) -> None:
        """Drop every standing claim that this project needs a person.

        **Both sources, in one place, and #101's rule is why.** The design says
        the overlay describes ONE attempt, so a fresh action has to start from
        nothing: a prompt the person has since answered must not go on being
        reported at them.

        `stop` did this for the attempt marker and nothing did it for the
        standing observation, which review found is not a corner. `kill` then
        `start` inside the TTL rendered a BRAND NEW agent as "waiting for an
        answer", and the sweep could not correct it, because
        `attention.MIN_UPTIME_S` makes a young session no candidate for its
        first fifteen seconds. The stale claim outlived the agent it was about.

        **Two call sites, and the reason there are not four is worth writing
        down**, because the obvious reading is that every path which ends an
        agent should clear this. `derive` sets `awaiting_input` only on a
        RUNNING row: a `stopped`, `stale` or `detached` session is built
        without it and cannot carry it whatever these sets hold. So clearing
        after a kill, or when a row is reconciled to `stopped`, would be
        clearing something nothing reads, and this project's own rule about a
        guard that cannot execute applies to a clear that cannot be observed.

        What matters is the moment a row becomes RUNNING again with a DIFFERENT
        agent in it, and there is exactly one of those: `start`. Plus `stop`,
        where the row stays running and #101's rule is that a fresh attempt
        starts from nothing.

        The caller holds no lock. This one takes it.
        """
        with self._stopping_guard:
            self._awaiting_input.discard(name)
            self._stuck.pop(name, None)
            # #182. Tells an in flight sweep that its evidence predates this
            # clear. Under the same lock as the clear itself, so a sweep can
            # never read the counter and the map in disagreement.
            self._attention_epoch += 1

    def _needs_a_person(self) -> frozenset[str]:
        """Every name the `awaiting_input` overlay is true for, from both sources.

        The union, built once per LISTING by the caller and handed into
        `_derive`, never per row: `_derive` used to hand `derive` the attempt
        set directly, and #100 gave the flag a second source that has to be
        combined somewhere. `_stopping_guard`'s own note is why the combining
        cannot happen inside `_derive`, and there is a test on the call count.

        Combined HERE rather than in `derive`, so that `get`, `list` and the
        event published after an action all read the same answer. A version
        that flagged rows only inside `list` would have blinked the flag off
        every time an event arrived, because the interface replaces a row
        wholesale from an event payload.

        The TTL is `attention`'s, and so is the reason for one.
        """
        now = self._clock()
        with self._stopping_guard:
            return frozenset(self._awaiting_input) | attention.standing(self._stuck, now)

    def scan_for_stuck(self) -> builtins.list[str]:
        """Record which running rows are waiting on a person (#100).

        Driven by the sweep that already expires stop markers, never by a
        request. `attention` carries the argument for that and the bounds; this
        is the part that touches the machine and holds the answer.

        **It does nothing while nobody is watching**, and that is not an
        optimisation. Before #100 an idle tick was free: `expire_stops` with no
        markers runs no subprocess at all. A look is a `ps`, a
        `tmux list-panes -a` and a file read, and doing that every second for
        the life of a user unit, on a machine with no browser open and nothing
        running, is a cost this feature has no claim on. It would also make the
        sweep look more often than the polling browser whose cost was the
        argument for moving off the request path in the first place.

        The subscriber count is the honest test for "somebody is watching":
        outside a stop wait the page only refreshes on an event, so with no
        stream there is nobody this could tell anything to. The first sweep
        after a client connects re establishes the flag within one interval,
        which is the same freshness a client gets on any other row.

        A bus is always attached in the running application, by `create_app`.
        `None` means an engine built directly, which is a test asking for one
        scan rather than a process idling, so it scans.

        May raise past the look and the root scan (#181). The server's done
        callback logs it and the next tick scans again; caught here, it would
        answer "nobody is waiting" on no evidence.
        """
        if self._bus is not None and self._bus.subscriber_count == 0:
            return []
        try:
            machine = self._look()
            names = discovery.list_root_projects(self.prefs.active_roots())
        except (MachineUnreadable, discovery.RootUnavailable):
            # We could not look. That is not evidence about anybody's screen,
            # so nothing is added and nothing already known is dropped.
            return []
        # Sorted, so which rows a truncated budget reaches is deterministic
        # rather than a property of iteration order.
        waiting = self._needs_a_person()
        rows = [self._derive(name, machine, waiting) for name in sorted(names)]
        # #182. Read BEFORE the capture, compared after it. Everything between
        # these two lines happens without the lock, which is the whole point:
        # `attention.scan` runs a subprocess per row.
        epoch = self._attention_epoch
        stuck, clear = attention.scan(
            attention.candidates(rows), self._pane_needs_a_person, self._clock
        )
        now = self._clock()
        with self._stopping_guard:
            discarded = self._attention_epoch != epoch
            if discarded:
                # A stop or a start cleared this overlay while we were looking
                # at screens, so every `stuck` here is evidence from before an
                # action the person has already taken. #101's rule is that a
                # fresh attempt starts from nothing, and writing these would
                # undo that with an observation older than the clear.
                #
                # **The whole batch, not the cleared name.** Knowing WHICH
                # project was cleared would need a per project record, and this
                # is one integer. The cost of the coarse version is that an
                # unrelated stop delays a true "waiting for an answer" by one
                # sweep interval, which the next scan corrects because it reads
                # the pane again.
                #
                # The `clear` half is still applied below: dropping a claim on
                # stale evidence is the safe direction, and refusing to drop it
                # would leave a person told they are needed when they are not.
                stuck = []
            # **The prune comes BEFORE `changed`, and before the renewal.** Two
            # representations of one fact: `changed` asks the store, the
            # interface asks `attention.standing`, which filters by the TTL,
            # and inside the gap they disagreed (#218). A name past `TTL_S`
            # was still in the dict, so a sweep re-confirming it computed
            # "nothing changed" and told nobody, while a page that reconnected
            # in the meantime had read `standing` and showed the row as not
            # waiting. Pruning first makes the store agree with the view, so
            # `in self._stuck` below is safe everywhere rather than only where
            # somebody remembered the TTL, and a re-confirmed name reads as
            # new, announces, and is renewed by the loop after.
            #
            # This is NOT round 1 of #182, which looks the same in a diff and
            # is the opposite: that version popped AFTER the renewal, so a
            # re-confirmed entry was written with `now` and then removed by the
            # same block, silently. This pops before the renewal, and the
            # renewal puts a re-confirmed name back.
            #
            # **Skipped on a discarded sweep**, which is round 1's own point: a
            # standing observation stays alive by being rewritten, so aging an
            # entry this scan declined to renew drops a row on evidence the
            # sweep does not trust. Nothing is announced for an aged name that
            # this sweep did not re-confirm: `standing` already hid it from
            # every reader, so there is no change to report.
            if not discarded:
                for name in attention.expired(self._stuck, now):
                    self._stuck.pop(name, None)
            # What CHANGED, computed under the lock beside the write, because
            # announcing what did not change is how a page that is already
            # right redraws itself once a second.
            changed = [name for name in stuck if name not in self._stuck]
            changed += [name for name in clear if name in self._stuck]
            for name in stuck:
                self._stuck[name] = now
            for name in clear:
                self._stuck.pop(name, None)
        # Announced, OUTSIDE the lock, exactly as `expire_stops` does it and
        # for the reason its docstring gives: outside a stop wait the page does
        # not poll at all, so a change visible only on the next listing is one
        # the interface cannot report. The person this exists for is holding a
        # phone, looking at a row that will not change on its own.
        #
        # **From the row already derived, not from `self.get(name)`.**
        # `expire_stops` uses `get` because it holds no rows; this method
        # derived every one of them a moment ago, and re deriving would spend a
        # whole machine look per changed row: ten changes would be ten more
        # `ps` and `tmux` pairs inside one tick, which is the cost this ticket
        # moved off the request path in the first place. It is also more
        # consistent, since the payload then comes from the same look the
        # decision came from rather than from a newer one that may disagree.
        by_name = {row.name: row for row in rows}
        for name in changed:
            if name in stuck:
                logger.info("%s: its screen is waiting on a person", name)
            else:
                logger.debug("%s: no longer waiting on a person", name)
        for name in changed:
            row = by_name.get(name)
            if row is not None:
                self._announce(replace(row, awaiting_input=name in stuck))
        return stuck

    def _pane_needs_a_person(self, name: str) -> bool:
        """Whether this agent's screen is showing something only a human can
        answer. False whenever that cannot be told.

        Never raises. `expire_stops` calls it per name after it has dropped
        the markers, so a raise would lose every later name's report and
        announcement, though the server's sweep survives it (#181).

        What "clear" means is Claude Code knowledge and stays in `claude_ipc`;
        this asks and does not interpret.
        """
        try:
            pane = self.tmux.capture_pane(name, escapes=True)
        except TmuxUnavailable:
            return False
        # `is False` and not `is not True`: `None` means the row could not be
        # read at all, which is not evidence of a prompt. Only a screen we can
        # see and that is not an ordinary input box counts.
        #
        # **`shows_input_box`, not `input_is_clear`, and #100 is why.** The two
        # differ on exactly one case: an ordinary box with text in it. That is a
        # person's draft, and a draft is not somebody being needed. The design's
        # own words for this overlay are "showing something that had to be
        # answered, not an ordinary input box", which is this predicate; the
        # other one was an approximation that also fired on the draft, and it
        # cannot be reused here because #89 shortened its anchor deliberately so
        # that a modal and a box would both match.
        return claude_ipc.shows_input_box(pane) is False

    def _flag_waiting(self, name: str, epoch: int) -> None:
        """Add the overlay from a look taken at `epoch`, unless a start or a
        stop cleared it since (#410): that look was at the old agent's screen."""
        with self._stopping_guard:
            if self._attention_epoch == epoch:
                self._awaiting_input.add(name)

    def advance_wrap_ups(self) -> builtins.list[str]:
        """Move each finished or overdue wrap up on to the exit (#242).

        Driven by the server's sweep, started rather than awaited and at most
        one in flight, because it captures a pane per `closing` row and may
        run the exit sequence with its settles: awaited beside `expire_stops`,
        one hung capture would hold back every other row's expiry. And not
        inside `scan_for_stuck`, which does nothing while no browser is
        connected: a wrap up has to finish with the phone in a pocket.

        Whether a screen reads finished is `claude_ipc`'s, through the watch;
        this only asks. Returns the names sent to the exit. Never raises: a
        refused exit's marker is dropped first, so a raise loses its report.
        """
        with self._stopping_guard:
            closing = [
                (name, marker)
                for name, marker in self._stopping.items()
                if marker.phase == "closing" and marker.watch is not None
            ]
        moved: builtins.list[str] = []
        for name, marker in closing:
            watch = marker.watch
            assert watch is not None
            try:
                pane = self.tmux.capture_pane(name, escapes=True)
            except TmuxUnavailable:
                pane = ""
            now = self._clock()
            finished = watch.observe(now, pane)
            ceiling = not finished and now - marker.began >= self.config.stop_prompt_timeout
            if not (finished or ceiling):
                continue
            with self._stopping_guard:
                if self._stopping.get(name) is not marker or marker.phase != "closing":
                    # A second Stop claimed it, or a kill or a refusal took it,
                    # while this pane was being read.
                    continue
                marker.exit_at, marker.ceiling, marker.typing = now, ceiling, True
                marker.phase = "exiting"
            logger.info(
                "stop %s: wrap up %s after %.0fs",
                name,
                "hit the ceiling" if ceiling else "finished",
                now - marker.began,
            )
            try:
                claude_ipc.request_stop(self.tmux, name, settle=self._sleep)
                moved.append(name)
            except (claude_ipc.StopNotSafe, TmuxUnavailable) as exc:
                self._drop(name, marker)
                logger.info("stop %s: exit refused after wrap up, %s", name, exc)
                # The stop ends here, so this is `expire_stops`' moment: one
                # look at the pane, or the page says "no answer" over a
                # question the person was never shown (#242 review). Only the
                # report; `end_anyway` kills a stop that expired after its exit
                # was SENT, and this one never was.
                epoch = self._attention_epoch
                if self._pane_needs_a_person(name):
                    self._flag_waiting(name, epoch)
            finally:
                self._done_typing(marker)
            try:
                self._announce(self.get(name))
            except MachineUnreadable:
                logger.warning(
                    "stop %s: the wrap up moved on but the machine could not be "
                    "read, so no event was sent",
                    name,
                )
        return moved

    def expire_stops(self) -> builtins.list[str]:
        """Drop stop markers older than the timeout, and say so.

        Expiry means "we stopped waiting", never "escalate". The session is
        still alive and the decision to kill it belongs to a person: an
        automatic kill is a destructive action taken while they were not
        looking.

        **Unless the operator decided before they tapped** (#239):
        `stop_policy = end_anyway`, off by default, kills a stop that ended on
        a prompt. Escalation by choice made once in configuration, not by
        default, which is what section 7 forbids; and a kill, not an answer.
        The policy is the one recorded at that Stop, never the live one (#419).

        It announces, because the person watching the timer has to learn the
        wait ended. An expiry visible only on the next poll is one the
        interface cannot report.
        """
        now = self._clock()
        with self._stopping_guard:
            # A snapshot, taken under the lock. Iterating the live dict while
            # `stop` adds on another thread raises, and the tick loses its
            # expiries to that raise.
            # #242. A `closing` marker is the sweep's, not this method's, and
            # the wait is measured from the exit: under a wrap up the time
            # before it is the rest of the agent's task.
            candidates = [
                (name, marker)
                for name, marker in self._stopping.items()
                if marker.exit_at is not None
                and marker.phase == "exiting"
                and now - marker.exit_at >= self.prefs.stop_timeout()
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
            expired = [name for name, _marker in candidates]
            for name in expired:
                del self._stopping[name]
        # Announced outside the lock: `get` does two subprocess calls, and
        # holding a lock across those would serialise every stop behind them.
        #
        # Outside the lock also means `get` can fail out here, and the markers
        # are already gone by then. `_announce` cannot raise, but `get` can:
        # it reads the machine, and a tmux that has gone away is exactly the
        # MachineUnreadable case. Uncaught, that raise ends this pass with its
        # markers already gone, so every later name in it goes unreported and
        # unannounced, and their timers sit on the page until the next listing.
        # The sweep itself survives it, inside the server's loop (#181).
        # ONE look at each expired pane, before announcing (#101).
        #
        # This is the only place the interface can learn that a stop ended
        # because the agent is waiting on something a person has to answer.
        # The sequence itself produces that state: asked to exit with
        # background work running, Claude Code opens a confirmation and sits on
        # it, and the row goes on saying `running` while the screen says
        # "it has not finished" and offers a kill.
        #
        # Affordable HERE and nowhere else. A `capture-pane` per running row on
        # every listing is the cost the design refused for the session link; a
        # stop that runs out of patience is rare by construction, and this is
        # the one moment where the answer is worth a subprocess.
        #
        # It only ever ADDS. Nothing here answers the prompt: the options in
        # that dialog decide what happens to work the operator did not ask to
        # end, and choosing for them is the power #88 declined to take.
        #
        # One name at a time, look then act, never every look first (#239
        # review). Each end_anyway kill waits up to `kill_grace` for the
        # session to go, so with the looks taken up front a later row's look
        # could be seconds old by its kill, long enough for a person to Kill
        # and Start it again, and the fresh agent, which never saw a prompt,
        # would be killed for the old one's question.
        for name, marker in candidates:
            end_anyway = marker.policy == "end_anyway"
            # The agent, read BEFORE its screen (#418), and only when the
            # policy could act on it. Read after, a Kill and Start between the
            # two would pair the fresh agent's pid with the old one's question.
            seen = self._agent_pid(name) if end_anyway else None
            epoch = self._attention_epoch
            waiting = self._pane_needs_a_person(name)
            if waiting:
                self._flag_waiting(name, epoch)
            # #239. The operator's answer, given in advance, to a stop that
            # ran out of time on a question: the kill the dialog offers at
            # this moment, taken without the tap. Only on THIS look at the
            # pane, never the sweep's overlay, and never a key typed into the
            # prompt. The protected project is refused after the handle.
            if waiting and seen is not None and signals.end_anyway(self, name, seen):
                continue
            person = "; its screen is waiting on a person" if waiting else ""
            try:
                session = self.get(name)
            except MachineUnreadable:
                logger.warning(
                    "stop timer for %s expired but the machine could not be "
                    "read, so no event was sent; the marker is already dropped%s",
                    name,
                    person,
                )
                continue
            # Worded from the state read AFTER the timer, never assumed (#167
            # review). Only `get` clears the marker on a clean exit, and with
            # no browser connected nothing calls it, so an agent that exited at
            # 12s still reaches this line at 30s. Saying "still running" there
            # is the journal calling a stop that worked a failure.
            # `stale` too (#390): the agent went and only its session stayed,
            # held by another window or a failed `remain-on-exit` clear. The
            # time is from the Stop, an upper bound nothing watched shrink.
            if session.state is State.STOPPED:
                logger.info(
                    "stop %s: the %gs wait ran out after the agent had already "
                    "exited, within %.1fs of the stop",
                    name,
                    self.prefs.stop_timeout(),
                    now - marker.began,
                )
            elif session.state is State.STALE:
                logger.info(
                    "stop %s: the %gs wait ran out; the agent exited and its "
                    "tmux session remains",
                    name,
                    self.prefs.stop_timeout(),
                )
            else:
                logger.info(
                    "stop %s: gave up waiting after %gs, and the row is still %s%s",
                    name,
                    self.prefs.stop_timeout(),
                    session.state.value,
                    person,
                )
            self._announce(session)
        return expired

    def _agent_pid(self, name: str) -> int | None:
        """The running agent's pid, or None when there is none or no look."""
        try:
            session = self.get(name)
        except MachineUnreadable:
            return None
        return session.pid if session.state is State.RUNNING else None

    def locate(self, name: str) -> Session:
        """The row a client may address by name, or the refusal the API gives.

        One function for the two routes that take a name and read rather than
        act (#151): the logs API and the logs page. A page that resolved a
        name more loosely than the API route beside it is the asymmetry that
        gets missed, so there is one ladder and both climb it. Addressable
        rather than startable, because reading a pane must keep working for a
        session whose folder is gone; and a name with nothing live behind it
        is `UnknownProject` only when the root has never heard of it, which
        keeps "stopped" and "unknown" the two answers they are (#47).
        """
        # A real guard now. This read `self.get(name)` with a comment saying it
        # stopped an unknown project returning empty output; `get` cannot
        # raise, so it did nothing but spend two subprocess calls arriving
        # there.
        self._require_addressable(name)
        session = self.get(name)
        if session.state is State.STOPPED:
            self._reject_if_not_a_project(name)
        return session

    def logs(self, name: str, lines: int = 40) -> str:
        """The tail of a pane."""
        if self.locate(name).state is State.STOPPED:
            # Not `_require_live`: that also refuses the self project, and
            # reading the log of the session hosting Hitchrail is harmless and
            # occasionally the only way to see what it is doing.
            #
            # The point of the check is that empty output and no session are
            # different answers. Without it a name with nothing behind it
            # returns "", which a client cannot tell from a pane that has
            # printed nothing yet.
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
    "ANSWER_KEYS",
    "AlreadyRunning",
    "Engine",
    "EngineError",
    "Gone",
    "InvalidValue",
    "Locked",
    "MachineUnreadable",
    "MemoryNeedsAck",
    "MemoryRefused",
    "NoAgent",
    "NotAsking",
    "NotDetached",
    "NotOurs",
    "NotRunning",
    "OperatorDisabled",
    "OperatorPinned",
    "OwnedElsewhere",
    "PidfdUnavailable",
    "Protected",
    "Session",
    "StartFailed",
    "State",
    "StateUnwritable",
    "StopRefused",
    "UnknownProject",
    "UnknownRoot",
]
