"""The event bus: never blocks, never raises, never leaks a subscriber.

Every property here exists because the alternative breaks the product in a way
that is hard to see. A blocking publish stalls the engine on a client nobody is
reading. A leaked subscriber grows the bus on a device that reconnects
constantly. A silent drop is indistinguishable from nothing having happened.
"""

from __future__ import annotations

import asyncio

import pytest

from hitchrail.events import EventBus


def test_a_new_bus_has_no_subscribers() -> None:
    assert EventBus().subscriber_count == 0
    assert EventBus().dropped == 0


async def test_every_subscriber_receives_a_published_event() -> None:
    bus = EventBus()
    with bus.subscribe() as one, bus.subscribe() as two:
        bus.publish({"kind": "state", "name": "vessel"})
        assert one.get_nowait() == {"kind": "state", "name": "vessel"}
        assert two.get_nowait() == {"kind": "state", "name": "vessel"}


async def test_publishing_with_no_subscribers_is_not_an_error() -> None:
    """The ordinary state before anyone connects, and after everyone leaves."""
    EventBus().publish({"kind": "state"})


async def test_a_full_queue_drops_rather_than_blocking() -> None:
    """The property the engine depends on.

    `publish` is called from engine code that may be on a worker thread. If it
    awaited a full queue, one backgrounded phone tab would stall every other
    client and the engine with them.
    """
    bus = EventBus(maxsize=2)
    with bus.subscribe() as queue:
        bus.publish({"n": 1})
        bus.publish({"n": 2})
        bus.publish({"n": 3})  # would block if this awaited
        assert queue.qsize() == 2
        assert bus.dropped == 1


async def test_drops_are_counted_not_swallowed() -> None:
    """Silent loss is indistinguishable from nothing having happened."""
    bus = EventBus(maxsize=1)
    with bus.subscribe():
        for n in range(5):
            bus.publish({"n": n})
    assert bus.dropped == 4


async def test_a_slow_subscriber_does_not_starve_a_fast_one() -> None:
    """Named regression, and the reason this is a class rather than a list.

    One client that stopped draining must not cost another client its events.
    """
    bus = EventBus(maxsize=1)
    with bus.subscribe() as slow, bus.subscribe() as fast:
        bus.publish({"n": 1})
        # The fast one drains; the slow one does not.
        assert fast.get_nowait() == {"n": 1}
        bus.publish({"n": 2})
        assert fast.get_nowait() == {"n": 2}
        assert slow.qsize() == 1
        assert bus.dropped == 1


async def test_a_subscriber_is_removed_on_normal_exit() -> None:
    bus = EventBus()
    with bus.subscribe():
        assert bus.subscriber_count == 1
    assert bus.subscriber_count == 0


async def test_a_subscriber_is_removed_when_the_block_raises() -> None:
    """The error path is where subscriber leaks survive review.

    A phone disconnects by vanishing, not by closing politely, so the
    exceptional exit is the common one rather than the rare one.
    """
    bus = EventBus()
    with pytest.raises(RuntimeError), bus.subscribe():
        assert bus.subscriber_count == 1
        raise RuntimeError("the client vanished")
    assert bus.subscriber_count == 0


async def test_subscribers_are_independent() -> None:
    """Draining one queue must not consume another's copy."""
    bus = EventBus()
    with bus.subscribe() as one, bus.subscribe() as two:
        bus.publish({"n": 1})
        one.get_nowait()
        assert two.qsize() == 1


async def test_a_subscriber_added_after_an_event_does_not_receive_it() -> None:
    """No replay. A reconnecting client needs a snapshot, not history, and
    pretending otherwise would make the bus a queue with unbounded memory."""
    bus = EventBus()
    bus.publish({"n": 1})
    with bus.subscribe() as queue:
        assert queue.qsize() == 0


async def test_nesting_and_overlapping_subscriptions_are_counted_correctly() -> None:
    bus = EventBus()
    with bus.subscribe():
        with bus.subscribe():
            assert bus.subscriber_count == 2
        assert bus.subscriber_count == 1
    assert bus.subscriber_count == 0


async def test_publish_survives_a_subscriber_leaving_mid_publish() -> None:
    """`publish` iterates a SNAPSHOT of the subscriber set.

    Without that, a subscriber removed while the loop is running mutates the
    set under the iteration and raises `RuntimeError`, from a function whose
    documented contract is that it never raises.

    The real scenario is threaded: `publish` is called from engine code on a
    worker thread while the event loop unsubscribes a client that has just
    disconnected. That race is hard to schedule deterministically, so this
    provokes the same mutation from inside the loop instead: a queue that
    unsubscribes a sibling the moment it is written to.

    Verified to fail when the snapshot is removed.
    """

    class UnsubscribesASibling(asyncio.Queue):  # type: ignore[type-arg]
        def __init__(self, bus: EventBus) -> None:
            super().__init__(maxsize=4)
            self._bus = bus

        def put_nowait(self, item: object) -> None:
            # Whatever else is subscribed leaves, right now, mid iteration.
            for other in list(self._bus._subscribers):
                if other is not self:
                    self._bus._subscribers.discard(other)
            super().put_nowait(item)

    bus = EventBus()
    with bus.subscribe():
        bus._subscribers.add(UnsubscribesASibling(bus))
        bus.publish({"n": 1})  # must not raise RuntimeError
