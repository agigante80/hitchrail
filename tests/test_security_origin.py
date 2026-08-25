"""The CSRF control for a same origin JSON API.

Browsers attach Origin to cross site requests and a rebound attacker cannot
forge it, so requiring it to name an origin we already serve is sufficient here
and needs no token round trip.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from hitchrail.config import Config
from hitchrail.security import middleware_stack

HOST = {"host": "localhost"}


def build(config: Config) -> Starlette:
    async def ok(request: httpx.Request) -> JSONResponse:
        return JSONResponse({"ok": True})

    return Starlette(
        routes=[
            Route("/x", ok, methods=["GET", "POST", "PUT", "PATCH", "DELETE"]),
            Route("/api/events", ok, methods=["GET"]),
        ],
        middleware=middleware_stack(config),
    )


async def call(
    app: Starlette, method: str = "GET", path: str = "/x", **kwargs: object
) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as c:
        return await c.request(method, path, **kwargs)  # type: ignore[arg-type]


# -- the deliberate GET exemption ------------------------------------------


async def test_a_get_needs_no_origin(tmp_path: Path) -> None:
    app = build(Config(root=tmp_path))
    assert (await call(app, headers=HOST)).status_code == 200


async def test_the_event_stream_needs_no_origin(tmp_path: Path) -> None:
    """The exemption is deliberate, and this test exists to say so.

    EventSource cannot set request headers, so `/api/events` cannot carry an
    Origin requirement. Without this test somebody notices the gap, "fixes" it,
    and silently breaks every live update in the product.
    """
    app = build(Config(root=tmp_path))
    response = await call(app, path="/api/events", headers=HOST)
    assert response.status_code == 200


@pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
async def test_safe_methods_are_exempt(tmp_path: Path, method: str) -> None:
    app = build(Config(root=tmp_path))
    assert (await call(app, method, headers=HOST)).status_code in (200, 405)


# -- refusals --------------------------------------------------------------


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
async def test_a_mutating_request_without_an_origin_is_rejected(
    tmp_path: Path, method: str
) -> None:
    # Refused rather than treated as same origin. A control whose premise is
    # that browsers always send it has no business assuming when they do not.
    app = build(Config(root=tmp_path))
    response = await call(app, method, headers=HOST)
    assert response.status_code == 403
    assert response.json()["code"] == "origin_missing"


@pytest.mark.parametrize(
    "origin",
    [
        "https://evil.example",
        "http://localhost:3000",
        "http://localhost.evil.example:8787",
        "null",
        "http://127.0.0.1:9999",
        "http://localhost",
        "https://localhost:8787",
        "",
    ],
    ids=[
        "foreign",
        "other-local-app",
        "prefix-confusion",
        "null-sandboxed-iframe",
        "wrong-port",
        "port-80-implicit",
        "wrong-scheme",
        "empty",
    ],
)
async def test_a_mutating_request_with_a_foreign_origin_is_rejected(
    tmp_path: Path, origin: str
) -> None:
    app = build(Config(root=tmp_path, port=8787))
    response = await call(app, "POST", headers={**HOST, "origin": origin})
    assert response.status_code == 403
    assert response.json()["code"] in {"origin_rejected", "origin_missing"}


async def test_another_local_application_is_not_same_origin(tmp_path: Path) -> None:
    """The reason the comparison is an origin and not a hostname.

    Matching on hostname alone would make every other development server on
    the machine same origin with an API equivalent to a shell.
    """
    app = build(Config(root=tmp_path, port=8787))
    served = await call(app, "POST", headers={**HOST, "origin": "http://localhost:8787"})
    refused = await call(app, "POST", headers={**HOST, "origin": "http://localhost:3000"})
    assert served.status_code == 200
    assert refused.status_code == 403


# -- what is accepted ------------------------------------------------------


async def test_a_mutating_request_with_the_matching_origin_is_served(
    tmp_path: Path,
) -> None:
    app = build(Config(root=tmp_path, port=8787))
    response = await call(app, "POST", headers={**HOST, "origin": "http://localhost:8787"})
    assert response.status_code == 200


async def test_a_configured_proxy_origin_is_served(tmp_path: Path) -> None:
    # The TLS terminating proxy case. Configured, never derived: the scheme and
    # the port are the proxy's, and only the operator knows either.
    cfg = Config(
        root=tmp_path,
        host="0.0.0.0",
        token="t",
        extra_hosts=("box.lan",),
        extra_origins=("https://box.lan:8443",),
        resolver=lambda: ("192.168.1.10",),
    )
    app = build(cfg)
    response = await call(
        app,
        "POST",
        headers={
            "host": "box.lan",
            "origin": "https://box.lan:8443",
            # A non loopback bind demands a token. The subject here is the
            # origin check, so the request is otherwise authenticated.
            "authorization": "Bearer t",
        },
    )
    assert response.status_code == 200


async def test_an_ipv6_origin_is_bracketed_the_way_a_browser_sends_it(
    tmp_path: Path,
) -> None:
    cfg = Config(root=tmp_path, port=8787)
    app = build(cfg)
    response = await call(app, "POST", headers={"host": "[::1]", "origin": "http://[::1]:8787"})
    assert response.status_code == 200


@pytest.mark.parametrize("suffix", ["", "/"])
async def test_a_trailing_slash_on_the_origin_does_not_change_the_answer(
    tmp_path: Path, suffix: str
) -> None:
    # Some clients append one. It is not part of an origin, so it is trimmed
    # rather than turned into a refusal nobody can explain.
    app = build(Config(root=tmp_path, port=8787))
    response = await call(
        app, "POST", headers={**HOST, "origin": f"http://localhost:8787{suffix}"}
    )
    assert response.status_code == 200


async def test_origin_matching_is_case_insensitive_on_scheme_and_host(
    tmp_path: Path,
) -> None:
    # Scheme and host are case insensitive per RFC 3986; the port is digits.
    app = build(Config(root=tmp_path, port=8787))
    response = await call(app, "POST", headers={**HOST, "origin": "HTTP://LOCALHOST:8787"})
    assert response.status_code == 200


# -- ordering --------------------------------------------------------------


async def test_the_host_check_runs_before_the_origin_check(tmp_path: Path) -> None:
    # A rebound request must not learn which origins this server accepts.
    app = build(Config(root=tmp_path))
    response = await call(
        app, "POST", headers={"host": "evil.example", "origin": "http://localhost:8787"}
    )
    assert response.status_code == 400
    assert response.json()["code"] == "host_rejected"
