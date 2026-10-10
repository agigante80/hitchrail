"""Restart: a stop that starts (#472, Phase 26 task 240).

`POST /api/sessions/{name}/restart` is the graceful stop, unchanged, plus a
mark that a start follows once the agent has gone. It is not a third
mechanism: `Engine.stop` does the first half and `Engine.start` the second,
with every refusal either already has.

**The mark is `RestartOverlay.pending`, in engine memory and never persisted,
for the reason the stop marker is not.** A `restarting` row that outlived the
process would be a claim about a stop nobody is waiting on, and Hitchrail
restarting mid stop means no start follows, which is what two presses do today.

**Who may start, and when.** Only `advance`, driven by the sweep, and only from
a row it DERIVED `stopped` with no stop marker in the table. The decision and
the removal of the mark are one critical section under the engine's
`stopping_guard`, the lock `stop`, `kill` and `expire_stops` already write the
marker under, so two ticks, or two Restart presses, hold and consume ONE mark.
The start itself runs outside the lock (it can take seconds), after the mark
is gone: that is what makes "exactly once" true. A start that is refused is
recorded on the row and never retried.

**Every way the stop does not end in `stopped` clears the mark and starts
nothing.** A timeout and `end_anyway` (`sweep.expire_stops`, at the removal of
the marker), a Kill (`Engine.kill`, before its `kill-session`, so the sweep
cannot read the dying session as `stopped` first), and any other end of the
marker with the agent still there (a refused exit given back, `_drop`): `advance`
clears those when it finds the row not stopped and no marker. Kill means "end
this", not "end this faster", and nothing here escalates in order to restart.

This module is in the engine layer and imports nothing from the web layer;
`lint-imports` enforces it.
"""

from __future__ import annotations

import contextlib
import logging
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, cast

from hitchrail.sessions import AlreadyRunning, Locked, MachineUnreadable, Session, State

if TYPE_CHECKING:
    from hitchrail.engine_seam import EngineSeam

# The engine's name, as `sweep.py` does: the journal knows these lines by it.
logger = logging.getLogger("hitchrail.engine")


@dataclass
class RestartOverlay:
    """What the engine remembers about restarts. Writes are under the engine's
    `stopping_guard`; `overlay` reads without it, as `_derive` reads the stop
    table, because a membership test is atomic under the GIL."""

    # Name to when Restart was confirmed (the engine's clock), for the journal.
    pending: dict[str, float] = field(default_factory=dict)
    # Name to the reason a start that followed a stop was refused.
    refused: dict[str, str] = field(default_factory=dict)
    # Name to how many times a Kill, a signal or an expiry has ended a restart
    # for it. `request` reads it before `stop` and again before it marks.
    ended: dict[str, int] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return bool(self.pending or self.refused)

    def cancel(self, name: str) -> None:
        """Forget a pending start, and count that it was ended. Under
        `stopping_guard`. Counting is the point: a Restart whose `stop` is
        still typing has no mark to forget yet, and the count is what tells
        `request` that someone ended it meanwhile."""
        self.ended[name] = self.ended.get(name, 0) + 1
        self.pending.pop(name, None)

    def forget(self, name: str) -> None:
        """Forget a pending start WITHOUT counting. Under `stopping_guard`.
        For an end that does not end the agent: the sweep's expiry of a stop
        that ran out of time. Counting there would silence a Restart whose
        `stop` returned just before the expiry and has not yet marked, though
        the agent is still there to be restarted by the mark's own rules."""
        self.pending.pop(name, None)

    def epoch(self, name: str) -> int:
        """How many times `cancel` has run for `name`. Under `stopping_guard`."""
        return self.ended.get(name, 0)

    def overlay(self, session: Session) -> Session:
        """The two fields on a derived row."""
        name = session.name
        if not self:
            return session
        if session.state is not State.STOPPED:
            # A refusal describes a row that stayed stopped. Once the row is
            # anything else (started by hand, say) it is history, and left in
            # place it would come back on the NEXT stop.
            self.refused.pop(name, None)
        return replace(
            session,
            restarting=name in self.pending,
            restart_refused=self.refused.get(name),
        )


def request(engine: EngineSeam, name: str) -> Session:
    """Begin a graceful stop and mark that a start follows it.

    `stop` first and the mark after, so every refusal `stop` can raise is this
    route's refusal with nothing marked: a Restart on a `stopped` row must not
    leave a mark for the sweep to start from. The mark is set when the stop is
    in flight or the agent has already gone; a Stop that was a no-op on a row
    with no marker (a Kill holds it out) marks nothing, since a Kill in flight
    is the person saying "end this".

    A second Restart is a second Stop (it resends the exit on an `exiting`
    row, and types nothing while a sequence is going out) and finds the mark
    already there: `setdefault` keeps one, with the first press's time.
    """
    with engine.stopping_guard:
        epoch = engine.restarts.epoch(name)
    session = engine.stop(name)
    if not (session.stopping or session.state is State.STOPPED):
        return session
    with engine.stopping_guard:
        # Decided against the epoch, never from the row alone. `stop` types
        # the exit over several seconds and the mark does not exist yet, so a
        # Kill, a /signal or an end_anyway in that window has nothing to
        # cancel, and the row it leaves reads STOPPED, indistinguishable from
        # a clean exit: the check above passes and the sweep would start a
        # new agent after the person said "end this". Anything that ended the
        # agent bumped the epoch under this lock, so a changed epoch means no
        # mark. Do not replace this with a look at the row.
        if engine.restarts.epoch(name) != epoch:
            logger.info("restart %s: ended while the stop was typing, so no start", name)
            return session
        engine.restarts.refused.pop(name, None)
        engine.restarts.pending.setdefault(name, engine.now())
    logger.info("restart %s: a start will follow the stop", name)
    session = replace(session, restarting=True, restart_refused=None)
    engine.announce(session)
    return session


def advance(engine: EngineSeam) -> list[str]:
    """Start every row whose restart has reached `stopped`. The sweep's.

    Returns the names it started. Cheap with nothing pending: one dict read.
    """
    restarts = engine.restarts
    with engine.stopping_guard:
        names = list(restarts.pending)
    if not names:
        return []
    try:
        machine = engine.look()
    except MachineUnreadable as exc:
        # Keep the marks: a machine that cannot be read says nothing about the
        # stop, and a start is only ever made from a `stopped` that was read.
        logger.warning("restart: the machine could not be read, so no start: %s", exc)
        return []
    started: list[str] = []
    for name in names:
        try:
            session = engine.derive(name, machine)
        except MachineUnreadable as exc:
            logger.warning(
                "restart %s: the row could not be derived, so no start: %s", name, exc
            )
            continue
        if _consume(engine, name, session) and _start(engine, name):
            started.append(name)
    return started


def _consume(engine: EngineSeam, name: str, session: Session) -> bool:
    """Read the row's verdict and take the mark, in one critical section.

    True only for the call that removed the mark from a `stopped` row with no
    stop marker. `_derive` leaves a marker whose exit is still being typed
    (#453), and a row stopped under one is not done: the next tick decides.
    """
    restarts = engine.restarts
    with engine.stopping_guard:
        if name not in restarts.pending:
            return False
        if name in engine.stopping:
            return False
        if session.state is not State.STOPPED and session.stopping:
            # The look saw a marker that has gone since, say a listing's
            # reconcile on an exit just made. Clearing on that look would lose
            # a restart whose agent has in fact gone: the next tick reads the
            # row afresh.
            return False
        del restarts.pending[name]
    if session.state is State.STOPPED:
        return True
    logger.info(
        "restart %s: the stop ended with the row %s and not stopped, so no start follows",
        name,
        session.state.value,
    )
    # The row said "restarting" until now and nothing else will change it:
    # announce, as `_start` does for a refusal.
    with contextlib.suppress(MachineUnreadable):
        engine.announce(engine.get(name))
    return False


def _reason(exc: Exception) -> str:
    """Words for the row. `Locked` and `AlreadyRunning` carry only the folder's
    name, which on a row reads as "restart not started: main~vessel"."""
    if isinstance(exc, Locked):
        return "another start is already in flight for this folder"
    if isinstance(exc, AlreadyRunning):
        return "an agent is already running here"
    return str(exc) or type(exc).__name__


def _start(engine: EngineSeam, name: str) -> bool:
    """`Engine.start`, once, with its refusals kept on the row."""
    logger.info("restart %s: the agent has exited, starting a new one", name)
    try:
        engine.start(name)
    except Exception as exc:
        # Broad on purpose: the mark is already gone, so a raise that left the
        # row silent would be a restart that vanished. Every refusal `start`
        # has (the memory guard, a lock, a folder that left) is a reason the
        # person reads on the row; none is retried, since a retry would loop on
        # the same refusal with nobody to read it.
        reason = _reason(exc)
        logger.warning("restart %s: the start was refused: %s", name, reason)
        with engine.stopping_guard:
            engine.restarts.refused[name] = reason
        with contextlib.suppress(MachineUnreadable):
            engine.announce(engine.get(name))
        return False
    return True


class RestartMembers:
    """`Engine`'s two public entry points, as a mixin like `SeamMembers`, so
    `engine.py` (held to a size cap) gains no methods. `self` is the engine."""

    def restart(self, name: str) -> Session:
        """A stop that starts (#472). `request` is the whole of it."""
        return request(cast("EngineSeam", self), name)

    def advance_restarts(self) -> list[str]:
        """Start rows whose restart reached `stopped`. The sweep's."""
        return advance(cast("EngineSeam", self))
