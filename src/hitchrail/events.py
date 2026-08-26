"""A publish and subscribe bus for state changes, sized for one small machine.

Every property here exists because the alternative breaks the product in a way
that is hard to see from the outside:

- `publish` never blocks and never raises, because it is called from engine
  code that may be running on a worker thread. If it awaited a full queue, one
  phone that backgrounded its tab would stall the engine and every other
  client with it.
- **Delivery hops to each subscriber's event loop.** `asyncio.Queue` is not
  thread safe, and the engine is driven from worker threads: Phase 5 routes
  every blocking engine call through `in_thread`. Calling `put_nowait` across
  threads appears to work and does not: the value lands in the queue, but the
  parked getter is woken through `loop.call_soon`, which never writes the self
  pipe, so a sleeping loop is not woken at all. Measured before this was fixed:
  an event published at 0.30s was delivered at 2.00s, when an unrelated timeout
  happened to fire. With an idle loop the delay is unbounded. On a debug loop
  it is worse than late: `put_nowait` raises after storing the value, leaving
  the getter future finished with its callbacks unscheduled, which is a dead
  stream rather than a dropped event.
- A full subscriber loses the event and the loss is COUNTED, because silent
  loss is indistinguishable from nothing having happened.
- `subscribe` is a context manager, because a subscriber that is not removed on
  disconnect is a leak that grows with every reconnection, and a phone
  reconnects constantly.

There is deliberately no replay. A client that reconnects has missed whatever
happened while it was away and needs a snapshot of current state, not a
history; keeping one would make this an unbounded queue.

This module is in the engine layer and imports nothing from the web layer.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Iterator
from dataclasses import dataclass

# What crosses the bus. A plain dict because it becomes an SSE payload, and
# anything that is not JSON serialisable fails at the far end rather than here.
Event = dict[str, object]

# Deep enough to absorb a burst while a client is briefly busy, shallow enough
# that a client which stopped reading cannot cost much memory. Thirty two
# events is several seconds of a very busy machine.
DEFAULT_MAXSIZE = 32


@dataclass(frozen=True, eq=False)
class _Subscriber:
    """A queue and the loop it belongs to.

    The loop is captured at subscribe time because that is the only moment we
    are certainly running on it. `eq=False` keeps identity hashing, so two
    subscribers with equal looking fields stay distinct members of the set.
    """

    queue: asyncio.Queue[Event]
    loop: asyncio.AbstractEventLoop


class EventBus:
    """One bus, many subscribers, no memory of what they missed."""

    def __init__(self, maxsize: int = DEFAULT_MAXSIZE) -> None:
        self._maxsize = maxsize
        self._subscribers: set[_Subscriber] = set()
        self._dropped = 0

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    @property
    def dropped(self) -> int:
        """Events a subscriber never received: a full queue, or a closed loop.

        Observable on purpose. A drop that nobody can see is a bug report that
        says "it sometimes misses updates" with nothing to go on.

        **Eventually consistent, for every publisher.** Delivery is scheduled
        on the subscriber's loop rather than performed inline, so this
        increments once that loop runs the callback even when the publisher was
        already on it. An earlier version of this docstring said "from a worker
        thread", which reads as though same loop publishes were still
        synchronous; they are not, and every same loop test here has to let the
        loop run before reading a queue.
        """
        return self._dropped

    @contextlib.contextmanager
    def subscribe(self) -> Iterator[asyncio.Queue[Event]]:
        """A queue of events, removed on exit however the block ends.

        The `finally` is the whole point: a phone disconnects by vanishing
        rather than by closing politely, so the exceptional exit is the common
        one and a subscriber removed only on the happy path leaks on every
        reconnection.
        """
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=self._maxsize)
        # Captured here because this is the one moment we are certainly on the
        # subscriber's loop. `publish` may be called from anywhere.
        subscriber = _Subscriber(queue=queue, loop=asyncio.get_running_loop())
        self._subscribers.add(subscriber)
        try:
            yield queue
        finally:
            self._subscribers.discard(subscriber)

    def publish(self, event: Event) -> None:
        """Never blocks, never raises, from any thread.

        Iterates a SNAPSHOT of the subscriber set: a subscriber leaving while
        this runs would otherwise mutate the set under the iteration and raise,
        from a function whose contract is that it does not.

        The actual delivery is scheduled on each subscriber's own loop, which
        is what makes the cross thread case correct rather than merely
        plausible. See the module docstring for what happens without it.
        """
        # `list(...)` and the `+= 1` below both rely on CPython's GIL for
        # atomicity, which holds on 3.11 to 3.13 and is not guaranteed on a
        # free threaded build. Stress tested at eight threads and twenty
        # thousand publishes each with an exact drop count and no iteration
        # error. If this project ever targets a free threaded interpreter, the
        # set and the counter need a lock.
        for subscriber in list(self._subscribers):
            try:
                subscriber.loop.call_soon_threadsafe(self._deliver, subscriber, event)
            except RuntimeError:
                # The loop is closed, so the subscriber is gone and simply
                # never had this event. Raising here would break the contract
                # over a client that has already disconnected.
                #
                # Dropped AND removed. A closed loop is terminal, so keeping
                # the subscriber would count a phantom drop on every publish
                # forever and leave `subscriber_count` reporting a client that
                # cannot exist. Safe to mutate here: the loop above iterates a
                # snapshot.
                self._dropped += 1
                self._subscribers.discard(subscriber)

    def _deliver(self, subscriber: _Subscriber, event: Event) -> None:
        """Runs on the subscriber's loop, so `put_nowait` is safe here."""
        try:
            subscriber.queue.put_nowait(event)
        except asyncio.QueueFull:
            self._dropped += 1
