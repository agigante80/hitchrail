"""The event bus: never blocks, never raises, never leaks a subscriber.

Every property here exists because the alternative breaks the product in a way
that is hard to see. A blocking publish stalls the engine on a client nobody is
reading. A leaked subscriber grows the bus on a device that reconnects
constantly. A silent drop is indistinguishable from nothing having happened.
"""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

from hitchrail.events import EventBus, _Subscriber


async def settle() -> None:
    """Let the loop run the callbacks `publish` scheduled.

    Delivery hops to each subscriber's loop, because `asyncio.Queue` is not
    thread safe and the engine publishes from worker threads. So a publish is
    scheduled rather than performed, and a test that reads the queue in the
    same step reads it too early. That is the contract, not a wart: see the
    module docstring for what publishing inline actually does across threads.
    """
    # Only valid when the publisher was on THIS loop. A cross thread publish
    # has to reach the loop first, and one sleep(0) does not wait for that;
    # test_publish_from_a_worker_thread_arrives_promptly awaits with a timeout.
    await asyncio.sleep(0)


def test_a_new_bus_has_no_subscribers() -> None:
    assert EventBus().subscriber_count == 0
    assert EventBus().dropped == 0


async def test_every_subscriber_receives_a_published_event() -> None:
    bus = EventBus()
    with bus.subscribe() as one, bus.subscribe() as two:
        bus.publish({"kind": "state", "name": "vessel"})
        await settle()
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
        await settle()
        assert queue.qsize() == 2
        assert bus.dropped == 1


async def test_drops_are_counted_not_swallowed() -> None:
    """Silent loss is indistinguishable from nothing having happened."""
    bus = EventBus(maxsize=1)
    with bus.subscribe():
        for n in range(5):
            bus.publish({"n": n})
        await settle()
    assert bus.dropped == 4


async def test_a_slow_subscriber_does_not_starve_a_fast_one() -> None:
    """Named regression, and the reason this is a class rather than a list.

    One client that stopped draining must not cost another client its events.
    """
    bus = EventBus(maxsize=1)
    with bus.subscribe() as slow, bus.subscribe() as fast:
        bus.publish({"n": 1})
        await settle()
        # The fast one drains; the slow one does not.
        assert fast.get_nowait() == {"n": 1}
        bus.publish({"n": 2})
        await settle()
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
        await settle()
        one.get_nowait()
        assert two.qsize() == 1


async def test_a_subscriber_added_after_an_event_does_not_receive_it() -> None:
    """No replay. A reconnecting client needs a snapshot, not history, and
    pretending otherwise would make the bus a queue with unbounded memory."""
    bus = EventBus()
    bus.publish({"n": 1})
    with bus.subscribe() as queue:
        await settle()
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

    Verified to fail when the snapshot is removed.
    """
    bus = EventBus()

    class ClearsTheSetWhenScheduled:
        """Stands in for a loop, and unsubscribes everyone the moment
        `publish` reaches it: the mutation the snapshot has to survive."""

        def call_soon_threadsafe(self, *args: object) -> None:
            bus._subscribers.clear()

    with bus.subscribe():
        bus._subscribers.add(
            _Subscriber(queue=asyncio.Queue(maxsize=4), loop=ClearsTheSetWhenScheduled())  # type: ignore[arg-type]
        )
        bus.publish({"n": 1})  # must not raise RuntimeError


async def test_publish_from_a_worker_thread_arrives_promptly() -> None:
    """The contract the module docstring makes, and the one it did not keep.

    `asyncio.Queue` is not thread safe. Publishing inline from another thread
    puts the value in the queue and wakes the getter through `loop.call_soon`,
    which never writes the self pipe, so a sleeping loop is not woken. Measured
    before the fix: published at 0.30s, delivered at 2.00s when an unrelated
    timeout fired. With an idle loop the delay is unbounded, which for SSE
    means a state change arrives whenever the next unrelated thing happens.

    Phase 5 routes every blocking engine call through `in_thread`, so this is
    the path the product actually uses rather than a hypothetical.
    """
    published_at = 0.2
    bus = EventBus()

    def worker() -> None:
        # The delay is load bearing. Publishing immediately can land BEFORE the
        # loop parks on `get()`, and then even the broken inline version works,
        # because no wakeup was ever needed. A first version of this test did
        # exactly that and passed against the defect it was written for.
        time.sleep(published_at)
        bus.publish({"n": 1})

    with bus.subscribe() as queue:
        threading.Thread(target=worker, daemon=True).start()
        start = time.monotonic()
        event = await asyncio.wait_for(queue.get(), timeout=3.0)
        elapsed = time.monotonic() - start

    assert event == {"n": 1}
    # Delivered when it was published, not when something else happened to
    # wake the loop. The inline version delivered at the timeout instead.
    assert elapsed < published_at + 1.0, f"delivered late, after {elapsed:.2f}s"


async def test_a_closed_loop_subscriber_is_a_drop_not_a_raise() -> None:
    """A client whose loop has gone never had the event, and `publish` still
    must not raise: its contract holds even for a subscriber that vanished."""
    bus = EventBus()
    dead = asyncio.new_event_loop()
    dead.close()
    bus._subscribers.add(_Subscriber(queue=asyncio.Queue(), loop=dead))
    bus.publish({"n": 1})
    assert bus.dropped == 1
