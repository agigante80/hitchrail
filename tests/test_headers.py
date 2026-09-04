"""#77. Every response says nosniff, refuses framing, and carries a policy.

Written as the refusals rather than the happy path, per the project's rule that
a security control with only a positive test is untested. The refusal a header
performs happens in the browser, which no test here can run, so what is
asserted is that the instruction is present, exact, and on the responses that
matter: the refusals, the unauthenticated grant page, and the event stream.

The browser actually honouring the policy is the e2e tier's job.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import JSONResponse
from starlette.routing import Route

from hitchrail.config import Config
from hitchrail.headers import (
    API_CSP,
    GRANT_CSP,
    PAGE_CSP,
    SecurityHeadersMiddleware,
    policy_for,
)
from hitchrail.security import middleware_stack
from support import make_config

pytestmark = pytest.mark.integration

TOKEN = "headers-token"
HOST = {"host": "localhost"}


async def _ok(request: httpx.Request) -> JSONResponse:
    return JSONResponse({"ok": True})


def build(config: Config) -> Starlette:
    return Starlette(
        routes=[Route("/x", _ok, methods=["GET", "POST"]), Route("/", _ok, methods=["GET"])],
        middleware=[Middleware(SecurityHeadersMiddleware), *middleware_stack(config)],
    )


async def call(
    app: Starlette, method: str = "GET", path: str = "/x", **kw: object
) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as c:
        return await c.request(method, path, **kw)  # type: ignore[arg-type]


# -- the headers reach the REFUSALS, which is the point of being outermost ---


@pytest.mark.parametrize(
    ("label", "headers", "expect"),
    [
        ("a forged Host", {"host": "evil.example"}, 400),
        ("a missing token", HOST, 401),
    ],
)
async def test_a_refusal_still_carries_the_headers(
    tmp_path: Path, label: str, headers: dict[str, str], expect: int
) -> None:
    """A refusal is the response most likely to be rendered somewhere
    unexpected, and it is returned before the app exists. If the middleware sat
    inside the access controls these would carry nothing."""
    app = build(make_config(tmp_path, host="0.0.0.0", token=TOKEN))
    response = await call(app, headers=headers)
    assert response.status_code == expect, label
    assert response.headers["x-content-type-options"] == "nosniff", label
    assert response.headers["x-frame-options"] == "DENY", label
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"], label


async def test_a_body_limit_refusal_carries_them_too(tmp_path: Path) -> None:
    """413 comes from OUTSIDE the app, per the note in server.py, so it is the
    one refusal this middleware could plausibly miss."""
    from hitchrail.server import MAX_BODY_BYTES

    app = build(make_config(tmp_path))
    response = await call(app, "POST", content=b"x" * (MAX_BODY_BYTES + 1), headers=HOST)
    assert response.headers.get("x-content-type-options") == "nosniff"


# -- the clickjacking case #77 was actually about ---------------------------


async def test_the_grant_page_refuses_to_be_framed(tmp_path: Path) -> None:
    """The concrete exposure. `/grant` is reachable with no token and holds a
    password field, so a page that guesses an allowlisted hostname could frame
    it and draw its own chrome around the field. Both spellings, because
    X-Frame-Options is what a browser honours when it ignores a CSP directive
    it does not know."""
    from hitchrail.headers import policy_for

    assert "frame-ancestors 'none'" in policy_for("/grant")
    app = build(make_config(tmp_path, host="0.0.0.0", token=TOKEN))
    response = await call(app, path="/", headers={**HOST, "authorization": f"Bearer {TOKEN}"})
    assert response.headers["x-frame-options"] == "DENY"


# -- the policy is per route, and exactly per route --------------------------


def test_the_grant_policy_is_not_handed_to_a_neighbour() -> None:
    """Exact comparison, like `security.route_path`. A prefix test would give
    the grant page's inline hashes to anything mounted under it later."""
    assert policy_for("/grant") == GRANT_CSP
    for near in ("/grantstuff", "/grant/x", "/x/grant", "/grant/"):
        assert policy_for(near) == API_CSP, near


def test_the_api_policy_allows_nothing() -> None:
    """A JSON response is not a document and should pull nothing at all."""
    assert API_CSP.startswith("default-src 'none'")
    assert "'self'" not in API_CSP


def test_the_page_policy_is_self_only_and_names_no_third_party() -> None:
    """#76 is what makes this possible: the faces are served from here now, so
    the policy needs no fonts.googleapis.com and no 'unsafe-inline'."""
    assert "'unsafe-inline'" not in PAGE_CSP
    assert "'unsafe-eval'" not in PAGE_CSP
    assert "http" not in PAGE_CSP
    for directive in ("frame-ancestors 'none'", "base-uri 'none'", "form-action 'none'"):
        assert directive in PAGE_CSP, directive


def test_the_grant_policy_carries_a_hash_and_never_unsafe_inline() -> None:
    """`'unsafe-inline'` on the one unauthenticated page with a password field
    would give away most of what the policy is for."""
    assert "'unsafe-inline'" not in GRANT_CSP
    assert GRANT_CSP.count("'sha256-") >= 2, (
        "one for the inline script, one for the inline style"
    )


def test_the_grant_hashes_are_the_hashes_of_the_page_as_shipped() -> None:
    """Computed from the file rather than pasted, so it cannot drift. This
    recomputes them independently: a hash that matched only itself would be a
    guard that cannot fail."""
    import hashlib
    import re
    from base64 import b64encode

    from hitchrail.headers import WEB

    html = (WEB / "grant.html").read_text()
    blocks = re.findall(r"<(script|style)(?![^>]*\ssrc=)[^>]*>(.*?)</\1>", html, re.S | re.I)
    assert blocks, "grant.html has no inline block, so the policy would break the page"
    for _tag, body in blocks:
        digest = b64encode(hashlib.sha256(body.encode()).digest()).decode()
        assert f"'sha256-{digest}'" in GRANT_CSP


# -- the stream, which a buffering middleware would have broken --------------


async def test_the_event_stream_still_streams(tmp_path: Path) -> None:
    """`BaseHTTPMiddleware` buffers through an anyio stream and would hang a
    response that never ends. This middleware touches http.response.start and
    nothing else, and this asserts that choice rather than trusting it."""
    from starlette.responses import StreamingResponse

    async def forever(request: httpx.Request) -> StreamingResponse:
        async def gen() -> AsyncIterator[bytes]:
            yield b"data: one\n\n"
            yield b"data: two\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream")

    app = Starlette(
        routes=[Route("/api/events", forever, methods=["GET"])],
        middleware=[Middleware(SecurityHeadersMiddleware)],
    )
    transport = httpx.ASGITransport(app=app)
    async with (
        httpx.AsyncClient(transport=transport, base_url="http://localhost") as c,
        c.stream("GET", "/api/events") as response,
    ):
        assert response.headers["x-content-type-options"] == "nosniff"
        chunks = [chunk async for chunk in response.aiter_bytes()]
    assert b"".join(chunks) == b"data: one\n\ndata: two\n\n"


# -- the response that carries the credential --------------------------------


def test_the_cookie_response_refuses_to_be_stored() -> None:
    """Both grant carriers set the cookie through one function, so both get it.

    Hardening: a POST response and a 303 are effectively never cached anyway.
    The value is that a future carrier which IS cacheable inherits it rather
    than having to remember.
    """
    from starlette.responses import JSONResponse

    from hitchrail.security import set_token_cookie

    response = JSONResponse({"ok": True})
    set_token_cookie(response, TOKEN)
    assert response.headers["cache-control"] == "no-store"
    assert TOKEN in response.headers["set-cookie"]
