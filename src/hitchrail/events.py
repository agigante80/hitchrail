"""A publish and subscribe bus for state changes, sized for one small machine.

Every property here exists because the alternative breaks the product in a way
that is hard to see from the outside:

- `publish` never blocks and never raises, because it is called from engine
  code that may be running on a worker thread. If it awaited a full queue, one
  phone that backgrounded its tab would stall the engine and every other
  client with it.
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

# What crosses the bus. A plain dict because it becomes an SSE payload, and
# anything that is not JSON serialisable fails at the far end rather than here.
Event = dict[str, object]

# Deep enough to absorb a burst while a client is briefly busy, shallow enough
# that a client which stopped reading cannot cost much memory. Thirty two
# events is several seconds of a very busy machine.
DEFAULT_MAXSIZE = 32


class EventBus:
    """One bus, many subscribers, no memory of what they missed."""

    def __init__(self, maxsize: int = DEFAULT_MAXSIZE) -> None:
        self._maxsize = maxsize
        self._subscribers: set[asyncio.Queue[Event]] = set()
        self._dropped = 0

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    @property
    def dropped(self) -> int:
        """Events discarded because a subscriber was full.

        Observable on purpose. A drop that nobody can see is a bug report that
        says "it sometimes misses updates" with nothing to go on.
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
        self._subscribers.add(queue)
        try:
            yield queue
        finally:
            self._subscribers.discard(queue)

    def publish(self, event: Event) -> None:
        """Never blocks, never raises.

        Iterates a SNAPSHOT of the subscriber set: a subscriber leaving while
        this runs would otherwise mutate the set under the iteration and raise,
        from a function whose contract is that it does not.
        """
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                self._dropped += 1
