"""Which sessions are waiting on a person, and what looking for them costs.

Split out of `engine.py` at #100, along the seam `derive.py` already
established: the engine acts on sessions, and this decides one thing ABOUT
them. The difference from `derive` is the cost. Derivation answers every
project from one look at the machine; this one has to read a screen, which is a
subprocess per row, so the whole module is really about the budget that makes
that affordable.

**The placement of the scan is the decision this module records.** The obvious
shape is a second pass inside `Engine.list`, and it bounds the wrong axis: the
cost then scales with how often a browser polls rather than with the state of
the machine, and `app.js` polls every 700 ms for a whole stop wait. Worse,
`tmux._CALL_TIMEOUT_S` is ten seconds, so a cap of ten captures is a hundred
seconds of worst case wall clock, taken on the executor that also serves
`DELETE /api/sessions/{name}`, which is the operator's escape hatch when an
agent is misbehaving. Run from the sweep instead, the ceiling is
`MAX_CAPTURES` per sweep interval, machine wide, whatever any client is doing.

Nothing here mutates anything or spawns anything: the capture arrives as a
callable, like every other external surface in this project.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping

from hitchrail.sessions import Session, State

# How many panes one sweep may capture. A capture is a subprocess, and this is
# the ceiling per sweep interval. On a healthy machine the rule below matches
# no rows at all.
MAX_CAPTURES = 10

# How long one sweep may spend capturing before abandoning the rest.
#
# The COUNT is not the bound that matters. Ten captures against a wedged tmux
# is a hundred seconds at the adapter's own call timeout, and a sweep that long
# overlaps the next one. This bounds the wall clock instead, and the rows it
# does not reach keep whatever the last sweep found.
BUDGET_S = 3.0

# How long an observation stands without being renewed. A row the sweep did not
# reach keeps its last answer this long rather than blinking off, and a stale
# claim expires on its own if the sweep stops running at all.
TTL_S = 30.0

# How long a session must have been up before its screen is worth reading. One
# still painting its first frame has no input box either, and flagging that
# would put "waiting for an answer" on every healthy start.
MIN_UPTIME_S = 15


def candidates(sessions: Iterable[Session]) -> list[str]:
    """The rows whose screen is worth a subprocess, in the order given.

    Narrow on purpose, because each of these costs a spawn:

    - `running`, because only a running row has an agent sitting at anything.
    - no session link, because a row with one is reachable and there is nothing
      to warn about. **This clause is not vacuous:** the link comes from a file
      the agent writes, and its own documentation says it is not written for
      every session, which is exactly why a missing link cannot be the whole
      signal and a capture is what tells "no link because stuck" from "no link
      because this one never gets one".
    - up longer than `MIN_UPTIME_S`.

    The caller passes sessions in the listing's own order, so which rows a
    truncated budget reaches is deterministic rather than a property of dict
    iteration. With more candidates than `MAX_CAPTURES`, the ones after it are
    never examined, and #100 states that rather than leaving it to be found.
    """
    return [
        session.name
        for session in sessions
        if session.state is State.RUNNING
        and session.url is None
        and session.uptime_s > MIN_UPTIME_S
    ]


def scan(
    names: list[str],
    needs_a_person: Callable[[str], bool],
    clock: Callable[[], float],
) -> tuple[list[str], list[str]]:
    """Look at up to `MAX_CAPTURES` screens, within `BUDGET_S`.

    Returns the names found waiting on a person and the names found NOT waiting,
    kept apart because the caller does different things with them: the first is
    recorded, and the second is REMOVED rather than left to expire, since a
    person who has answered the prompt should see the row stop saying otherwise
    on the next listing rather than in thirty seconds.

    A row neither list mentions was not looked at, which is not evidence in
    either direction and is why the caller keeps its previous answer.
    """
    deadline = clock() + BUDGET_S
    stuck: list[str] = []
    clear: list[str] = []
    for name in names[:MAX_CAPTURES]:
        if clock() >= deadline:
            # Abandon the rest rather than let every remaining row pay its own
            # call timeout. The next sweep starts fresh.
            break
        (stuck if needs_a_person(name) else clear).append(name)
    return stuck, clear


def standing(observations: Mapping[str, float], now: float) -> frozenset[str]:
    """The observations still inside their TTL.

    The TTL is what makes a remembered observation safe to keep at all: a claim
    about a screen that outlived the process watching it would be a claim
    nobody has checked since, which is the argument this project already makes
    for not persisting the stop marker.
    """
    cutoff = now - TTL_S
    return frozenset(name for name, seen in observations.items() if seen > cutoff)


def expired(observations: Mapping[str, float], now: float) -> list[str]:
    """The observations to forget. The other half of `standing`, named so the
    sweep's pruning cannot drift from what the reader is told."""
    cutoff = now - TTL_S
    return [name for name, seen in observations.items() if seen <= cutoff]
