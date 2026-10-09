"""The sweep: what the server's ticker does to the engine once a second.

Expiring stop markers, advancing a wrap up to its exit, and looking at running
screens for one that waits on a person. Split out of `engine.py` at #473, which
was past its cap, along the seam the ticker already drew: these three entry
points are driven from the lifespan and from nothing else, and each reads the
machine and the engine's in memory overlays rather than deciding what a start
or a stop does. `end_anyway`'s kill is `signals.py`'s, and is reached from here.

`Engine.scan_for_stuck`, `advance_wrap_ups` and `expire_stops` stay as one line
delegates, so the lifespan and the tests reach them where they always did.

This module is in the engine layer and imports nothing from the web layer;
`lint-imports` enforces it.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import TYPE_CHECKING

from hitchrail import attention, claude_ipc, discovery, signals
from hitchrail.sessions import MachineUnreadable, State
from hitchrail.tmux import TmuxUnavailable

if TYPE_CHECKING:
    from hitchrail.engine_seam import EngineSeam
    from hitchrail.stopmarker import StopMarker

# Named, not `__name__`: these lines were `hitchrail.engine`'s before the move,
# and the journal and the tests know them by that name.
logger = logging.getLogger("hitchrail.engine")


def scan_for_stuck(engine: EngineSeam) -> list[str]:
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
    if engine.watchers() == 0:
        return []
    try:
        machine = engine.look()
        names = discovery.list_root_projects(engine.prefs.active_roots())
    except (MachineUnreadable, discovery.RootUnavailable):
        # We could not look. That is not evidence about anybody's screen,
        # so nothing is added and nothing already known is dropped.
        return []
    # Sorted, so which rows a truncated budget reaches is deterministic
    # rather than a property of iteration order.
    waiting = engine.needs_a_person()
    rows = [engine.derive(name, machine, waiting) for name in sorted(names)]
    # #182. Read BEFORE the capture, compared after it. Everything between
    # these two lines happens without the lock, which is the whole point:
    # `attention.scan` runs a subprocess per row.
    epoch = engine.attention_epoch
    stuck, clear = attention.scan(
        attention.candidates(rows), lambda n: _pane_needs_a_person(engine, n), engine.now
    )
    now = engine.now()
    with engine.stopping_guard:
        discarded = engine.attention_epoch != epoch
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
        # `in engine.stuck` below is safe everywhere rather than only where
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
            for name in attention.expired(engine.stuck, now):
                engine.stuck.pop(name, None)
        # What CHANGED, computed under the lock beside the write, because
        # announcing what did not change is how a page that is already
        # right redraws itself once a second.
        changed = [name for name in stuck if name not in engine.stuck]
        changed += [name for name in clear if name in engine.stuck]
        for name in stuck:
            engine.stuck[name] = now
        for name in clear:
            engine.stuck.pop(name, None)
    # Announced, OUTSIDE the lock, exactly as `expire_stops` does it and
    # for the reason its docstring gives: outside a stop wait the page does
    # not poll at all, so a change visible only on the next listing is one
    # the interface cannot report. The person this exists for is holding a
    # phone, looking at a row that will not change on its own.
    #
    # **From the row already derived, not from `engine.get(name)`.**
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
            engine.announce(replace(row, awaiting_input=name in stuck))
    return stuck


def _pane_needs_a_person(engine: EngineSeam, name: str) -> bool:
    """Whether this agent's screen is showing something only a human can
    answer. False whenever that cannot be told.

    Never raises. `expire_stops` calls it per name after it has dropped
    the markers, so a raise would lose every later name's report and
    announcement, though the server's sweep survives it (#181).

    What "clear" means is Claude Code knowledge and stays in `claude_ipc`;
    this asks and does not interpret.
    """
    try:
        pane = engine.tmux.capture_pane(name, escapes=True)
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
    #
    # **`awaits_answer`, not `shows_input_box` directly (#429).** It is the
    # same answer today, and it is the one the answer route tests with
    # `is True`: this asks the vendor module the question it names.
    return claude_ipc.awaits_answer(pane) is True


def _held_by_a_second_look(
    engine: EngineSeam, name: str, marker: StopMarker, seen: int
) -> bool:
    """Whether `end_anyway` may still end this agent a settle after the
    first look found a prompt (#429).

    One look is not enough: while the box is not drawn, an output line
    carrying the ornament reads as a modal for the length of a redraw, and
    the agent writes that line itengine. Ending on it kills a working agent
    for a question nobody asked. A modal is still there a settle later; a
    redraw is not. No lock is held across the sleep or the capture, as the
    sweep does not hold one across its reads.

    False, and the expiry is then reported as `ask` reports it, when
    anything moved: the stop was withdrawn or is typing (its owner is
    acting), a newer Stop is in the table, the agent is not the one looked
    at, or the screen no longer shows a prompt.
    """
    engine.sleep(engine.end_anyway_settle)
    with engine.stopping_guard:
        moved = marker.withdrawn or marker.typing or name in engine.stopping
    if moved or _agent_pid(engine, name) != seen:
        return False
    return _pane_needs_a_person(engine, name)


def _flag_waiting(engine: EngineSeam, name: str, epoch: int) -> None:
    """Add the overlay from a look taken at `epoch`, unless a start or a
    stop cleared THIS name since (#410): that look was at the old agent's
    screen.

    **Per name, unlike `scan_for_stuck`'s whole batch (#430).** The epoch is
    one counter, so comparing it here discarded a true flag whenever ANY
    project started or stopped during the capture, and nothing adds it back:
    the stuck sweep skips a row with a session link. The counter only grows,
    so a look is stale for a name exactly when that name's last clear is
    newer than the epoch read before the look. `scan_for_stuck` keeps the
    single comparison on purpose: it reads every row again a second later,
    which corrects what the coarse version costs, and this does not.
    """
    with engine.stopping_guard:
        if engine.attention_cleared.get(name, 0) <= epoch:
            engine.awaiting_input.add(name)


def advance_wrap_ups(engine: EngineSeam) -> list[str]:
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
    with engine.stopping_guard:
        closing = [
            (name, marker)
            for name, marker in engine.stopping.items()
            if marker.phase == "closing" and marker.watch is not None
        ]
    moved: list[str] = []
    for name, marker in closing:
        watch = marker.watch
        assert watch is not None
        try:
            pane = engine.tmux.capture_pane(name, escapes=True)
        except TmuxUnavailable:
            pane = ""
        now = engine.now()
        finished = watch.observe(now, pane)
        ceiling = not finished and now - marker.began >= engine.config.stop_prompt_timeout
        if not (finished or ceiling):
            continue
        with engine.stopping_guard:
            if engine.stopping.get(name) is not marker or marker.phase != "closing":
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
            claude_ipc.request_stop(engine.tmux, name, settle=engine.sleep)
            moved.append(name)
        except (claude_ipc.StopNotSafe, TmuxUnavailable) as exc:
            engine.drop(name, marker)
            logger.info("stop %s: exit refused after wrap up, %s", name, exc)
            # The stop ends here, so this is `expire_stops`' moment: one
            # look at the pane, or the page says "no answer" over a
            # question the person was never shown (#242 review). Only the
            # report; `end_anyway` kills a stop that expired after its exit
            # was SENT, and this one never was.
            epoch = engine.attention_epoch
            if _pane_needs_a_person(engine, name):
                _flag_waiting(engine, name, epoch)
        finally:
            engine.done_typing(marker)
        try:
            engine.announce(engine.get(name))
        except MachineUnreadable:
            logger.warning(
                "stop %s: the wrap up moved on but the machine could not be "
                "read, so no event was sent",
                name,
            )
    return moved


def expire_stops(engine: EngineSeam) -> list[str]:
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
    now = engine.now()
    with engine.stopping_guard:
        # A snapshot, taken under the lock. Iterating the live dict while
        # `stop` adds on another thread raises, and the tick loses its
        # expiries to that raise.
        # #242. A `closing` marker is the sweep's, not this method's, and
        # the wait is measured from the exit: under a wrap up the time
        # before it is the rest of the agent's task.
        candidates = [
            (name, marker)
            for name, marker in engine.stopping.items()
            if marker.exit_at is not None
            and marker.phase == "exiting"
            and now - marker.exit_at >= engine.prefs.stop_timeout()
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
            del engine.stopping[name]
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
        seen = _agent_pid(engine, name) if end_anyway else None
        epoch = engine.attention_epoch
        waiting = _pane_needs_a_person(engine, name)
        if waiting:
            _flag_waiting(engine, name, epoch)
        # #239. The operator's answer, given in advance, to a stop that
        # ran out of time on a question: the kill the dialog offers at
        # this moment, taken without the tap. Only on THIS look at the
        # pane, never the sweep's overlay, and never a key typed into the
        # prompt. The protected project is refused after the handle.
        if waiting and seen is not None:
            if _held_by_a_second_look(engine, name, marker, seen):
                if signals.end_anyway(engine, name, seen):
                    continue
            else:
                logger.info(
                    "stop %s: end_anyway did not hold: a second look, %gs "
                    "later, did not agree it was waiting on a person",
                    name,
                    engine.end_anyway_settle,
                )
        person = "; its screen is waiting on a person" if waiting else ""
        try:
            session = engine.get(name)
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
                engine.prefs.stop_timeout(),
                now - marker.began,
            )
        elif session.state is State.STALE:
            logger.info(
                "stop %s: the %gs wait ran out; the agent exited and its tmux session remains",
                name,
                engine.prefs.stop_timeout(),
            )
        else:
            logger.info(
                "stop %s: gave up waiting after %gs, and the row is still %s%s",
                name,
                engine.prefs.stop_timeout(),
                session.state.value,
                person,
            )
        engine.announce(session)
    return expired


def _agent_pid(engine: EngineSeam, name: str) -> int | None:
    """The running agent's pid, or None when there is none or no look."""
    try:
        session = engine.get(name)
    except MachineUnreadable:
        return None
    return session.pid if session.state is State.RUNNING else None
