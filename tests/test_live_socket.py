"""The three refusals, on a real socket.

The hermetic rule in docs/tech-guidelines.md section 7.4 says no test touches
the network. This file is the documented exception, and it is narrow: it binds
127.0.0.1 on an ephemeral port, talks to itself, and shuts down. It exists
because the design asks specifically for a forged Host to be refused on a live
socket rather than in theory.

An ASGITransport test proves the middleware is CONFIGURED. It cannot prove the
deployed server refuses anything, because a real request arrives through
uvicorn's HTTP parser rather than through a dictionary a test constructed.
Those are different claims and only the second one is the design's.
"""

from __future__ import annotations

import logging
import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
import uvicorn
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from hitchrail.config import Config
from hitchrail.security import TOKEN_COOKIE, middleware_stack

TOKEN = "live-socket-token"
TIMEOUT = 5.0

pytestmark = pytest.mark.live


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


class LiveServer:
    """A real uvicorn on loopback, started and stopped around one test."""

    def __init__(self, app: Starlette, port: int, log_level: str = "warning") -> None:
        self.port = port
        self.base = f"http://127.0.0.1:{port}"
        self._server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=port, log_level=log_level)
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


def make_app(config: Config) -> Starlette:
    async def ok(request: httpx.Request) -> JSONResponse:
        return JSONResponse({"ok": True})

    return Starlette(
        routes=[
            Route("/x", ok, methods=["GET", "POST"]),
            Route("/api/events", ok, methods=["GET"]),
        ],
        middleware=middleware_stack(config),
    )


@pytest.fixture
def live(tmp_path: Path) -> Iterator[LiveServer]:
    port = free_port()
    config = Config(root=tmp_path, host="127.0.0.1", port=port, token=TOKEN)
    server = LiveServer(make_app(config), port)
    server.start()
    try:
        yield server
    finally:
        # In a finally, always. A test that leaves a listener behind poisons
        # every later run on the machine.
        server.stop()


def auth() -> dict[str, str]:
    return {"Host": "127.0.0.1", "Authorization": f"Bearer {TOKEN}"}


# -- a success case, so a dead server cannot look like a passing suite ------


def test_a_valid_request_is_served_on_a_live_socket(live: LiveServer) -> None:
    """Without this, every refusal test would also pass against a dead server.

    A connection refused and a 400 are not the same thing, but a test that only
    asserts "not 200" cannot tell them apart.
    """
    response = httpx.get(f"{live.base}/x", headers=auth(), timeout=TIMEOUT)
    assert response.status_code == 200
    assert response.json() == {"ok": True}


# -- the host allowlist ----------------------------------------------------


def test_a_forged_host_is_refused_on_a_live_socket(live: LiveServer) -> None:
    """The claim the design actually makes, and the CVE precedent.

    Through uvicorn's HTTP parser, not through a scope a test built.
    """
    response = httpx.get(
        f"{live.base}/x",
        headers={"Host": "evil.example", "Authorization": f"Bearer {TOKEN}"},
        timeout=TIMEOUT,
    )
    assert response.status_code == 400
    assert response.json()["code"] == "host_rejected"


def test_an_ipv6_loopback_host_is_served_on_a_live_socket(live: LiveServer) -> None:
    """The case Starlette's TrustedHostMiddleware cannot do at all.

    It splits the Host header on the first colon, so `[::1]:8787` becomes "["
    and is refused whatever the allowlist holds. The socket here is IPv4; what
    is under test is the header handling, which is where that bug lives.
    """
    response = httpx.get(
        f"{live.base}/x",
        headers={"Host": f"[::1]:{live.port}", "Authorization": f"Bearer {TOKEN}"},
        timeout=TIMEOUT,
    )
    assert response.status_code == 200


def test_the_event_stream_is_behind_the_allowlist_on_a_live_socket(
    live: LiveServer,
) -> None:
    response = httpx.get(
        f"{live.base}/api/events",
        headers={"Host": "evil.example"},
        timeout=TIMEOUT,
    )
    assert response.status_code == 400


# -- the token -------------------------------------------------------------


def test_a_missing_token_is_refused_on_a_live_socket(live: LiveServer) -> None:
    response = httpx.get(f"{live.base}/x", headers={"Host": "127.0.0.1"}, timeout=TIMEOUT)
    assert response.status_code == 401
    assert TOKEN not in response.text


def test_the_query_grant_round_trips_on_a_live_socket(live: LiveServer) -> None:
    """The flow a phone actually performs.

    Open the link once, get a cookie, and every request after that carries it
    with no token in the URL. That second request is what EventSource will do.
    """
    with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as client:
        granted = client.get(
            f"{live.base}/x", params={"token": TOKEN}, headers={"Host": "127.0.0.1"}
        )
        assert granted.status_code == 200
        assert client.cookies.get(TOKEN_COOKIE) == TOKEN

        # The cookie alone, no token in the URL and no Authorization header.
        again = client.get(f"{live.base}/x", headers={"Host": "127.0.0.1"})
        assert again.status_code == 200


def test_a_wrong_query_token_grants_nothing_on_a_live_socket(live: LiveServer) -> None:
    with httpx.Client(timeout=TIMEOUT) as client:
        response = client.get(
            f"{live.base}/x", params={"token": "wrong"}, headers={"Host": "127.0.0.1"}
        )
        assert response.status_code == 401
        assert client.cookies.get(TOKEN_COOKIE) is None


# -- the origin check ------------------------------------------------------


def test_a_mutating_request_with_a_foreign_origin_is_refused_on_a_live_socket(
    live: LiveServer,
) -> None:
    response = httpx.post(
        f"{live.base}/x",
        headers={**auth(), "Origin": "https://evil.example"},
        timeout=TIMEOUT,
    )
    assert response.status_code == 403
    assert response.json()["code"] == "origin_rejected"


def test_a_mutating_request_with_the_right_origin_is_served_on_a_live_socket(
    live: LiveServer,
) -> None:
    response = httpx.post(
        f"{live.base}/x",
        headers={**auth(), "Origin": f"http://127.0.0.1:{live.port}"},
        timeout=TIMEOUT,
    )
    assert response.status_code == 200


# -- teardown --------------------------------------------------------------


def test_the_server_is_shut_down_afterwards(tmp_path: Path) -> None:
    """A test that leaves a listener behind poisons every later run.

    Asserted by binding the same port again, which only succeeds once the
    previous server has actually released it.
    """
    port = free_port()
    config = Config(root=tmp_path, host="127.0.0.1", port=port, token=TOKEN)
    server = LiveServer(make_app(config), port)
    server.start()
    assert httpx.get(f"{server.base}/x", headers=auth(), timeout=TIMEOUT).status_code == 200
    server.stop()

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", port))
            return
        except OSError:
            time.sleep(0.1)
    raise AssertionError(f"port {port} was still bound after the server stopped")


def test_the_grant_keeps_the_token_out_of_the_access_log(tmp_path: Path) -> None:
    """Named regression: the redirect hides the token from the browser, not the server.

    uvicorn builds its access line after the app returns, from the same scope
    dict the app was handed, so `?token=` was written to the server's log in
    cleartext on every grant. Its own fixture runs at log_level="warning", which
    is exactly why the suite could not see this; this test turns access logging
    on deliberately.

    Fails if `scope["query_string"]` stops being overwritten in _maybe_grant.
    """
    port = free_port()
    config = Config(root=tmp_path, host="127.0.0.1", port=port, token=TOKEN)
    server = LiveServer(make_app(config), port, log_level="info")

    records: list[str] = []

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record.getMessage())

    handler = Capture()
    access = logging.getLogger("uvicorn.access")
    server.start()
    access.addHandler(handler)
    try:
        response = httpx.get(
            f"{server.base}/x?token={TOKEN}&keep=1",
            headers={"Host": "127.0.0.1"},
            follow_redirects=False,
            timeout=TIMEOUT,
        )
        assert response.status_code == 303
        # The redirect still carries the rest of the query, so the fix is not
        # "throw the query away".
        assert response.headers["location"] == "/x?keep=1"
        deadline = time.monotonic() + TIMEOUT
        while time.monotonic() < deadline and not records:
            time.sleep(0.05)
    finally:
        access.removeHandler(handler)
        server.stop()

    assert records, "uvicorn wrote no access line, so this test proves nothing"
    logged = "\n".join(records)
    assert TOKEN not in logged, f"the token reached the access log: {logged}"
    assert "keep=1" in logged
