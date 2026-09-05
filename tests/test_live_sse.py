"""The event stream, on a real socket, because no other tier can see it.

`httpx.ASGITransport.handle_async_request` awaits the app to COMPLETION and
accumulates the body before returning a response. An SSE generator never
completes, so the integration tier hangs on this route forever rather than
failing: the symptom is a test suite that stops, not one that reports.

That is not a defect in the route. It is the reason `.claude/CLAUDE.md` says
the live tier is the only one that can see the stream, and the reason these
tests bind a socket for something the rest of the suite proves hermetically.
"""

from __future__ import annotations

import asyncio
import json
import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
import uvicorn
from starlette.applications import Starlette

from conftest import FakeTmux, procs_from
from hitchrail.engine import Engine
from hitchrail.events import EventBus
from hitchrail.server import create_app
from support import DEFAULT_LABEL, make_config


def proj(folder: str) -> str:
    """The identifier for a folder in this file's single test root. #119."""
    return f"{DEFAULT_LABEL}~{folder}"


pytestmark = pytest.mark.live

TIMEOUT = 8.0
RUNNING_PS = """\
 500     1   4096   600 tmux new-session -d -s hr-vessel
 501   500 512000   600 claude --dangerously-skip-permissions --remote-control vessel
"""
PLENTY = "MemAvailable: 25198592 kB\n"


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


class LiveServer:
    """A real uvicorn on loopback, started and stopped around one test."""

    def __init__(self, app: Starlette, port: int) -> None:
        self.port = port
        self.base = f"http://127.0.0.1:{port}"
        self._server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
        )
        self._thread = threading.Thread(target=self._server.run, daemon=True)

    def start(self) -> None:
        self._thread.start()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if self._server.started:
                return
            time.sleep(0.05)
        raise RuntimeError("uvicorn did not start within 10 seconds")

    def stop(self) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=10)


class Fixture:
    def __init__(self, server: LiveServer, engine: Engine, bus: EventBus) -> None:
        self.server = server
        self.engine = engine
        self.bus = bus
        self.headers = {"host": "localhost", "origin": f"http://localhost:{server.port}"}


@pytest.fixture
def live(tmp_path: Path) -> Iterator[Fixture]:
    for name in ("vessel", "network"):
        (tmp_path / name).mkdir()
    config = make_config(tmp_path, sessions_dir=tmp_path / ".sessions")
    bus = EventBus()
    engine = Engine(
        config=config,
        tmux=FakeTmux(sessions={proj("vessel"): 500}),
        procs_fn=procs_from(RUNNING_PS),
        meminfo_fn=lambda: PLENTY,
        sleep=lambda _s: None,
    )
    server = LiveServer(create_app(engine=engine, config=config, bus=bus), free_port())
    server.start()
    try:
        yield Fixture(server, engine, bus)
    finally:
        server.stop()


async def _await_subscriber(bus: EventBus) -> None:
    """Wait until the publisher has actually subscribed.

    The response headers arrive before the generator body has subscribed, so
    triggering a change on the strength of `status_code == 200` publishes into
    an empty subscriber set. This bus does not replay history on purpose: a
    subscriber gets what happens from now on. Sleeping "long enough" instead
    would pass on a quiet laptop and flake in CI.
    """
    deadline = time.monotonic() + TIMEOUT
    while bus.subscriber_count == 0:
        if time.monotonic() > deadline:
            raise AssertionError("the stream never subscribed to the bus")
        await asyncio.sleep(0.01)


async def _events(response: httpx.Response, count: int) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    async for line in response.aiter_lines():
        if line.startswith("data:"):
            out.append(json.loads(line.removeprefix("data:").strip()))
            if len(out) >= count:
                return out
    raise AssertionError(f"the stream closed after {len(out)} of {count} events")


async def test_the_stream_opens_before_anything_has_happened(live: Fixture) -> None:
    """Idle is the NORMAL state, so headers cannot wait on the first change.

    A stream that only answers once something moves leaves `EventSource` in
    CONNECTING on a healthy system, and the interface looks broken exactly when
    nothing is wrong.
    """
    async with httpx.AsyncClient(base_url=live.server.base) as c:
        async with asyncio.timeout(TIMEOUT):
            async with c.stream("GET", "/api/events", headers=live.headers) as r:
                assert r.status_code == 200
                assert r.headers["content-type"].startswith("text/event-stream")


async def test_a_change_arrives_on_the_stream(live: Fixture) -> None:
    """The claim the design rests on: state is derived on demand, and the
    interface still learns about changes without polling for them."""
    async with httpx.AsyncClient(base_url=live.server.base) as c:
        async with asyncio.timeout(TIMEOUT):
            async with c.stream("GET", "/api/events", headers=live.headers) as r:
                assert r.status_code == 200
                reader = asyncio.create_task(_events(r, 1))
                await _await_subscriber(live.bus)
                live.engine.stop(proj("vessel"))
                (event,) = await reader
    assert event["name"] == proj("vessel")
    assert event["stopping"] is True
    assert event["state"] == "running", "the marker must not change the derived state"


async def test_two_readers_both_receive_the_same_change(live: Fixture) -> None:
    """A phone and a laptop must not have to take turns."""
    async with httpx.AsyncClient(base_url=live.server.base) as c:
        async with asyncio.timeout(TIMEOUT):
            async with c.stream("GET", "/api/events", headers=live.headers) as first:
                async with c.stream("GET", "/api/events", headers=live.headers) as second:
                    readers = asyncio.gather(_events(first, 1), _events(second, 1))
                    while live.bus.subscriber_count < 2:
                        await asyncio.sleep(0.01)
                    live.engine.stop(proj("vessel"))
                    (a,), (b,) = await readers
    assert a["name"] == b["name"] == proj("vessel")


async def test_the_subscriber_slot_is_released_when_a_reader_goes_away(
    live: Fixture,
) -> None:
    """A phone disconnects by vanishing, not by closing politely, so the slot
    has to be freed on the exceptional exit as well as the tidy one. Leaked
    slots are how a long lived server ends up publishing into dead queues."""
    async with httpx.AsyncClient(base_url=live.server.base) as c:
        async with asyncio.timeout(TIMEOUT):
            async with c.stream("GET", "/api/events", headers=live.headers) as r:
                assert r.status_code == 200
                await _await_subscriber(live.bus)
                assert live.bus.subscriber_count == 1

    deadline = time.monotonic() + TIMEOUT
    while live.bus.subscriber_count and time.monotonic() < deadline:
        await asyncio.sleep(0.02)
    assert live.bus.subscriber_count == 0, "the subscriber slot outlived the reader"


async def test_the_stream_carries_the_whole_session_shape(live: Fixture) -> None:
    """The interface renders rows from these events, so a missing field is a
    row it cannot draw without a second request."""
    async with httpx.AsyncClient(base_url=live.server.base) as c:
        async with asyncio.timeout(TIMEOUT):
            async with c.stream("GET", "/api/events", headers=live.headers) as r:
                reader = asyncio.create_task(_events(r, 1))
                await _await_subscriber(live.bus)
                live.engine.stop(proj("vessel"))
                (event,) = await reader
    assert set(event) == {
        "name",
        "state",
        "pid",
        "ram_mb",
        "uptime_s",
        "url",
        "stopping",
        "protected",
        "awaiting_trust",
        "awaiting_input",
        "foreign_session",
    }


async def test_an_idle_stream_survives_its_own_poll_timeout(live: Fixture) -> None:
    """The normal state of this system is nothing happening.

    The publisher waits on the queue with a one second timeout so a vanished
    reader is noticed promptly. That timeout fires constantly on a healthy
    idle stream, and treating it as anything but "carry on" would close the
    connection roughly once a second on a system where nothing is wrong.

    Held open past the timeout deliberately, then given a change: the event
    must still arrive on the same connection.
    """
    async with httpx.AsyncClient(base_url=live.server.base) as c:
        async with asyncio.timeout(TIMEOUT):
            async with c.stream("GET", "/api/events", headers=live.headers) as r:
                assert r.status_code == 200
                reader = asyncio.create_task(_events(r, 1))
                await _await_subscriber(live.bus)
                # Past the publisher's own 1.0s queue timeout, so the loop has
                # gone round at least once with nothing to send.
                await asyncio.sleep(1.4)
                assert live.bus.subscriber_count == 1, "the idle stream dropped"
                live.engine.stop(proj("vessel"))
                (event,) = await reader
    assert event["name"] == proj("vessel")
