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
import ssl
import threading
import time
import warnings
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import uvicorn
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from conftest import FakeTmux, procs_from
from hitchrail import logs
from hitchrail.cli import build_tls_context
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

    def __init__(
        self,
        app: Starlette,
        port: int,
        log_level: str = "warning",
        log_config: dict[str, Any] | None = uvicorn.config.LOGGING_CONFIG,
    ) -> None:
        self.port = port
        self.base = f"http://127.0.0.1:{port}"
        self._server = uvicorn.Server(
            uvicorn.Config(
                app, host="127.0.0.1", port=port, log_level=log_level, log_config=log_config
            )
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


def test_a_query_string_token_reaches_no_journal_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """#388. An old `/?token=` bookmark writes no token into the journal.

    This REVERSES #115's `test_a_query_token_now_reaches_the_access_log_and_`
    `that_is_correct`, deliberately. Its argument was against the scrub, which
    rewrote `scope["query_string"]` and so edited a caller's request for a
    parameter the server no longer reads. That stays true and
    `test_the_query_string_is_no_longer_rewritten` still holds it. What it
    missed is that the token is still a secret when the server refuses it: a
    phone opening a pre #115 link sends the real token, and the journal outlives
    the session. The fix is a filter on the log record, so the application
    sees the query untouched and only the written line loses it.

    Through `logs.configure` and `log_config=None`, the way `cli._serve` runs
    uvicorn, and read from captured stderr: a handler added to the logger in
    the test would see the record whatever the configured handler wrote.
    The filter keys on the shape of uvicorn's record, so only a real uvicorn
    can say it still matches.
    """
    port = free_port()
    config = make_config(tmp_path, host="127.0.0.1", port=port, token=TOKEN)
    logs.configure("info")
    server = LiveServer(make_app(config), port, log_level=logs.uvicorn_level(), log_config=None)
    server.start()
    try:
        host = {"Host": "127.0.0.1"}
        refused = httpx.get(f"{server.base}/x?token={TOKEN}", headers=host, timeout=TIMEOUT)
        assert refused.status_code == 401, "a query token is not a carrier"
        # Any name, not only the old one: the filter is not a list of names.
        other = httpx.get(f"{server.base}/x?k={TOKEN}&keep=1", headers=auth(), timeout=TIMEOUT)
        assert other.status_code == 200, other.text
        err = ""
        deadline = time.monotonic() + TIMEOUT
        while time.monotonic() < deadline and err.count("uvicorn.access") < 2:
            err += capsys.readouterr().err
            time.sleep(0.05)
        # Raw bytes: an HTTP client normalises all of these. Absolute form is
        # what a forwarding proxy sends; the others have no leading slash.
        raw = {
            "absolute": f"http%3A//127.0.0.1/?token={TOKEN}2",
            "bare": f"?token={TOKEN}3",
            "relative": f"x?token={TOKEN}4",
        }
        for target in raw.values():
            _raw_request(server.port, target)
        deadline = time.monotonic() + TIMEOUT
        while time.monotonic() < deadline and err.count("uvicorn.access") < 2 + len(raw):
            err += capsys.readouterr().err
            time.sleep(0.05)
    finally:
        server.stop()
    err += capsys.readouterr().err
    assert '"GET /x?' in err and " 401" in err and " 200" in err, (
        f"uvicorn wrote no access line naming the path, so this proves nothing: {err}"
    )
    assert err.count("uvicorn.access") >= 2 + len(raw), (
        f"a raw target got no access line, so this proves nothing: {err}"
    )
    assert TOKEN not in err, f"the token reached the journal: {err}"


def _raw_request(port: int, target: str) -> None:
    """One request line written byte for byte, answered or not."""
    with socket.create_connection(("127.0.0.1", port), timeout=TIMEOUT) as sock:
        sock.sendall(
            f"GET {target} HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n".encode()
        )
        while sock.recv(4096):
            pass


SERVER_REFUSALS = ("UNEXPECTED_EOF_WHILE_READING", "TLSV1_ALERT_PROTOCOL_VERSION")


def _tls11_client() -> ssl.SSLContext:
    """A client that offers TLS 1.1 and nothing else. `@SECLEVEL=0` lets
    OpenSSL 3 offer it at all; without it the handshake fails on the CLIENT
    side and the test would pass against any server."""
    client = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    client.check_hostname = False
    client.verify_mode = ssl.CERT_NONE
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        client.minimum_version = client.maximum_version = ssl.TLSVersion.TLSv1_1
    client.set_ciphers("DEFAULT:@SECLEVEL=0")
    return client


# -- #152: TLS from the server itself, on a real socket ----------------------


def test_a_grant_and_a_start_go_through_our_own_tls(tmp_path: Path) -> None:
    """Premortem 1 of the Phase 14 plan, which only a socket can see.

    The hermetic tier proves the derivation says `https`; it cannot prove a
    browser's request over HTTPS is accepted, because an ASGITransport
    carries whatever scheme the test writes. Here uvicorn terminates TLS
    with a certificate minted for this test, `httpx` verifies it, the grant
    sets a `Secure` cookie, and a START goes through with that cookie and
    the `https` origin: the request the origin check refused when the
    derivation said `http`.
    """
    from conftest import FakeTmux, ScriptedProcs
    from support import make_certificate
    from test_api import NO_AGENT_CONFIG, PLENTY, STARTED_PS, make_engine

    cert, key = make_certificate(tmp_path)
    (tmp_path / "root" / "network").mkdir(parents=True)
    port = free_port()
    config = make_config(
        tmp_path / "root",
        host="127.0.0.1",
        port=port,
        token=TOKEN,
        tls_cert=cert,
        tls_key=key,
        sessions_dir=tmp_path / ".s",
        agent_config_path=NO_AGENT_CONFIG,
    )
    engine = make_engine(config, FakeTmux(), ScriptedProcs("", STARTED_PS), PLENTY)
    app = create_app(engine=engine, config=config, bus=EventBus())
    # The CLI's own context through the factory, never the two paths (#267):
    # premortem 1 of the Phase 20 plan is a factory that differs from the
    # `ssl_certfile=` path the hermetic tier cannot see.
    context = build_tls_context(config)
    assert context is not None
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_level="warning",
            ssl_context_factory=lambda _config, _default: context,
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.05)
        assert server.started, "uvicorn did not start with the certificate"
        base = f"https://127.0.0.1:{port}"
        origin = {"Host": "127.0.0.1", "Origin": base}
        trust = ssl.create_default_context(cafile=str(cert))
        with httpx.Client(verify=trust, timeout=TIMEOUT) as client:
            # Plain HTTP on the TLS port is not served: the failure that must
            # never happen is HTTP on the port the operator believed was TLS.
            with pytest.raises(httpx.HTTPError):
                httpx.get(f"http://127.0.0.1:{port}/api/projects", timeout=TIMEOUT)
            granted = client.post(f"{base}/api/grant", json={"token": TOKEN}, headers=origin)
            assert granted.status_code == 200, granted.text
            assert "secure" in granted.headers["set-cookie"].lower().split("; ")
            assert TOKEN_COOKIE in client.cookies
            # An `http` origin is refused by OUR check, so the derivation is
            # what is being tested and not the transport alone.
            wrong = client.post(
                f"{base}/api/sessions/main~network",
                headers={"Host": "127.0.0.1", "Origin": f"http://127.0.0.1:{port}"},
            )
            assert wrong.status_code == 403
            assert wrong.json()["code"] == "origin_rejected"
            started = client.post(f"{base}/api/sessions/main~network", headers=origin)
            assert started.status_code == 201, started.text
            assert started.json()["state"] == "running"
            # What the socket SERVES refuses a client capped at 1.1 (#275).
            # This proves the property and not its cause: under OpenSSL 3 at
            # the distribution's default security level a server with no
            # floor refuses 1.1 as well, measured on 3.0.13, so the floor
            # itself is guarded by `minimum_version` in `test_tls.py`. The
            # assertion this replaced read the negotiated version, which is
            # 1.3 with or without a floor and so could not fail.
            with (
                pytest.raises(ssl.SSLError) as refused,
                socket.create_connection(("127.0.0.1", port), timeout=TIMEOUT) as raw,
                _tls11_client().wrap_socket(raw, server_hostname="localhost"),
            ):
                pass
            # #396. Which side refused, since a client that cannot offer 1.1
            # fails with `NO_PROTOCOLS_AVAILABLE` before the server is asked
            # and `SSLError` alone passed on that. Only the server can end
            # the handshake these two ways. The protocol_version alert the
            # ticket expected is not what arrives: measured on OpenSSL 3.0.13,
            # uvicorn's asyncio transport closes without flushing it, so the
            # client reads an EOF; the alert stays for a build that sends it.
            assert refused.value.reason in SERVER_REFUSALS, refused.value
    finally:
        server.should_exit = True
        thread.join(timeout=10)
