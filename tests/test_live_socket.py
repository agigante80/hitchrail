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

from conftest import FakeTmux, procs_from
from hitchrail.config import Config
from hitchrail.engine import Engine
from hitchrail.events import EventBus
from hitchrail.security import TOKEN_COOKIE, middleware_stack
from hitchrail.server import create_app
from support import make_config

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
    config = make_config(tmp_path, host="127.0.0.1", port=port, token=TOKEN)
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
    config = make_config(tmp_path, host="127.0.0.1", port=port, token=TOKEN)
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


def test_the_fragment_grant_puts_the_token_in_no_access_line(tmp_path: Path) -> None:
    """#79. The server side half of the fragment claim.

    `tests/e2e/test_token.py::test_the_fragment_never_reaches_the_server`
    asserts against the URLs Playwright records, and the browser has already
    stripped the fragment before that recording happens, so it cannot fail on
    account of the fragment. What it does constrain is that the page never
    BUILDS a URL carrying the key, which is worth having and is not this.

    **What this guards, precisely.** `_scrub_grant_param` removes exactly one
    parameter name, `GRANT_PARAM`, which is "token". That is correct for the
    legacy carrier it was written for and it is not a general secret filter: a
    token arriving in the URL under ANY other name reaches uvicorn's access log
    verbatim. So the thing worth asserting is not "the scrub works", which
    `test_the_grant_keeps_the_token_out_of_the_access_log` already covers, but
    that the fragment flow puts the token in no URL at all and therefore never
    depends on that one spelling.

    Verified by mutation: sending the same POST as `?k=<token>` fails this
    test, while the scrubbed `?token=<token>` spelling does not, which is the
    whole asymmetry.

    It has to run here because uvicorn builds its access line after the app
    returns, from the live scope, so no unit test can see it.

    The flow is driven to COMPLETION and the completion is asserted. A grant
    that silently failed would log no token either, and would pass.
    """
    port = free_port()
    config = make_config(tmp_path, host="127.0.0.1", port=port, token=TOKEN)
    app = create_app(
        engine=Engine(
            config=config,
            tmux=FakeTmux(sessions={}),
            procs_fn=procs_from(""),
            meminfo_fn=lambda: "MemAvailable: 25198592 kB\n",
            sleep=lambda _s: None,
        ),
        config=config,
        bus=EventBus(),
    )
    server = LiveServer(app, port, log_level="info")

    records: list[str] = []

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record.getMessage())

    handler = Capture()
    access = logging.getLogger("uvicorn.access")
    server.start()
    access.addHandler(handler)
    try:
        host = {"Host": f"127.0.0.1:{port}"}
        # httpx drops the fragment before sending, which is what a browser
        # does. Writing it here is the point: this is the URL a person opens,
        # and the server must never see the part after the `#`.
        page = httpx.get(f"{server.base}/grant#token={TOKEN}", headers=host, timeout=TIMEOUT)
        assert page.status_code == 200, page.text

        traded = httpx.post(
            f"{server.base}/api/grant",
            json={"token": TOKEN},
            headers={**host, "Origin": f"http://127.0.0.1:{port}"},
            timeout=TIMEOUT,
        )
        assert traded.status_code == 200, traded.text
        cookie = traded.cookies.get(TOKEN_COOKIE)
        assert cookie == TOKEN, "the grant set no usable cookie, so the flow did not complete"

        # The cookie now authenticates a real route. Without this the test
        # would pass against a grant that returned 200 and granted nothing.
        listing = httpx.get(
            f"{server.base}/api/projects",
            headers=host,
            cookies={TOKEN_COOKIE: cookie},
            timeout=TIMEOUT,
        )
        assert listing.status_code == 200, listing.text

        deadline = time.monotonic() + TIMEOUT
        while time.monotonic() < deadline and len(records) < 3:
            time.sleep(0.05)
    finally:
        access.removeHandler(handler)
        server.stop()

    logged = "\n".join(records)
    assert records, "uvicorn wrote no access line, so this test proves nothing"
    # All three requests are present, so the absence below is about the token
    # and not about the capture having missed the interesting line.
    assert "/grant" in logged and "/api/grant" in logged and "/api/projects" in logged, logged
    assert TOKEN not in logged, f"the token reached the access log: {logged}"


def test_a_query_token_now_reaches_the_access_log_and_that_is_correct(tmp_path: Path) -> None:
    """#115 deleted the scrub, so this asserts the consequence deliberately.

    `_scrub_grant_param` rewrote the scope so uvicorn's access line, which it
    builds from that same dict after the app returns, would not carry the
    token. That existed because `?token=` WAS a credential. It is not one now:
    the request below is refused 401.

    **This test exists so nobody restores the scrub.** Stripping a parameter
    the server does not accept would keep the misleading half of the old
    behaviour, editing a caller's query string for no security benefit, and it
    would quietly resume depending on where uvicorn emits its access line,
    which `_maybe_grant`'s own comment flagged as resting on an implementation
    detail rather than on anything ASGI guarantees.

    What must stay clean is the flow that carries a real credential, and
    `test_the_fragment_grant_puts_the_token_in_no_access_line` is that test.
    """
    port = free_port()
    config = make_config(tmp_path, host="127.0.0.1", port=port, token=TOKEN)
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
        assert response.status_code == 401, "a query token is not a carrier any more"
        deadline = time.monotonic() + TIMEOUT
        while time.monotonic() < deadline and not records:
            time.sleep(0.05)
    finally:
        access.removeHandler(handler)
        server.stop()

    logged = "\n".join(records)
    assert records, "uvicorn wrote no access line, so this test proves nothing"
    assert f"token={TOKEN}" in logged, (
        "the query string is passed through untouched; if this fails somebody "
        "has restored the scrub, which #115 removed with the carrier it served"
    )
