"""One shared token, over three carriers.

EventSource cannot set request headers, so a token that lives only in
Authorization authenticates every route except the one the interface depends on
for live updates. That is why there is a cookie, and why there is a grant that
sets it from a link you can open on a phone.
"""

from __future__ import annotations

import secrets
from collections.abc import MutableMapping
from pathlib import Path
from typing import Any

import httpx
import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from hitchrail.config import Config
from hitchrail.security import TOKEN_COOKIE, _token_matches, middleware_stack

TOKEN = "s3cret-token-value"
HOST = {"host": "localhost"}
ORIGIN = {**HOST, "origin": "http://localhost:8787"}


def build(config: Config) -> Starlette:
    async def ok(request: httpx.Request) -> JSONResponse:
        return JSONResponse({"ok": True})

    return Starlette(
        routes=[
            Route("/x", ok, methods=["GET", "POST"]),
            Route("/deep/path", ok, methods=["GET"]),
            Route("/api/events", ok, methods=["GET"]),
        ],
        middleware=middleware_stack(config),
    )


def guarded(tmp_path: Path) -> Starlette:
    return build(Config(root=tmp_path, host="0.0.0.0", token=TOKEN))


async def call(
    app: Starlette,
    method: str = "GET",
    path: str = "/x",
    follow_redirects: bool = False,
    **kwargs: object,
) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://localhost",
        follow_redirects=follow_redirects,
    ) as c:
        return await c.request(method, path, **kwargs)  # type: ignore[arg-type]


# -- no token configured ---------------------------------------------------


async def test_no_token_configured_means_no_token_demanded(tmp_path: Path) -> None:
    app = build(Config(root=tmp_path))
    assert (await call(app, headers=HOST)).status_code == 200


# -- the header carrier ----------------------------------------------------


async def test_a_configured_token_is_demanded(tmp_path: Path) -> None:
    response = await call(guarded(tmp_path), headers=HOST)
    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"


async def test_the_right_bearer_token_is_accepted(tmp_path: Path) -> None:
    response = await call(
        guarded(tmp_path), headers={**HOST, "authorization": f"Bearer {TOKEN}"}
    )
    assert response.status_code == 200


@pytest.mark.parametrize("scheme", ["Bearer", "bearer", "BEARER", "BeArEr"])
async def test_the_bearer_scheme_is_case_insensitive(tmp_path: Path, scheme: str) -> None:
    # RFC 7235: auth schemes are case insensitive. A client sending "bearer" is
    # correct, and rejecting it is our bug rather than theirs.
    response = await call(
        guarded(tmp_path), headers={**HOST, "authorization": f"{scheme} {TOKEN}"}
    )
    assert response.status_code == 200


@pytest.mark.parametrize(
    "value",
    ["Bearer wrong", "Bearer ", "Basic abc", TOKEN, "", f"Bearer  {TOKEN}", "Bearer"],
    ids=["wrong", "empty", "wrong-scheme", "no-scheme", "blank", "double-space", "scheme-only"],
)
async def test_a_bad_authorization_header_is_rejected(tmp_path: Path, value: str) -> None:
    response = await call(guarded(tmp_path), headers={**HOST, "authorization": value})
    assert response.status_code == 401


@pytest.mark.parametrize(
    ("header", "raw"),
    [
        (b"authorization", "Bearer café".encode("latin-1")),
        (b"authorization", b"Bearer \xff\xfe"),
        (b"cookie", "hitchrail_token=café".encode("latin-1")),
        (b"authorization", "Bearer café".encode()),
    ],
    ids=["latin1-header", "invalid-utf8", "latin1-cookie", "utf8-header"],
)
async def test_a_non_ascii_token_is_a_refusal_not_a_crash(
    tmp_path: Path, header: bytes, raw: bytes
) -> None:
    """Named regression, two failure modes, both unauthenticated crashes.

        secrets.compare_digest("café", "s3cret")
        TypeError: comparing strings with non-ASCII characters is not supported

        b"caf\xe9".decode()
        UnicodeDecodeError: 'utf-8' codec can't decode byte 0xe9

    The comparison is done on encoded bytes and the headers are decoded latin-1,
    which is what RFC 7230 says a header field is and the only choice that
    cannot raise. An attacker picks these bytes, so decoding strictly turns a
    refusal into a 500.

    Driven at the ASGI layer because httpx refuses to put non ASCII in a header
    value at all, which is correct of httpx and unhelpful for this test.
    """
    app = guarded(tmp_path)
    sent: list[MutableMapping[str, Any]] = []

    async def receive() -> MutableMapping[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: MutableMapping[str, Any]) -> None:
        sent.append(message)

    await app(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/x",
            "raw_path": b"/x",
            "query_string": b"",
            "root_path": "",
            "headers": [(b"host", b"localhost"), (header, raw)],
            "client": ("127.0.0.1", 5000),
            "server": ("127.0.0.1", 8787),
        },
        receive,
        send,
    )
    start = next(m for m in sent if m["type"] == "http.response.start")
    assert start["status"] == 401


# -- the cookie carrier, which is the one EventSource can use --------------


async def test_the_cookie_carrier_is_accepted(tmp_path: Path) -> None:
    response = await call(
        guarded(tmp_path), headers={**HOST, "cookie": f"{TOKEN_COOKIE}={TOKEN}"}
    )
    assert response.status_code == 200


async def test_the_event_stream_authenticates_the_way_eventsource_sends_it(
    tmp_path: Path,
) -> None:
    """The whole reason this task exists.

    EventSource sends cookies and no Authorization header, and it is the
    interface's only live update path. A token carried only in a header
    authenticates every route except that one.
    """
    response = await call(
        guarded(tmp_path),
        path="/api/events",
        headers={**HOST, "cookie": f"{TOKEN_COOKIE}={TOKEN}"},
    )
    assert response.status_code == 200


async def test_a_wrong_cookie_is_rejected(tmp_path: Path) -> None:
    response = await call(guarded(tmp_path), headers={**HOST, "cookie": f"{TOKEN_COOKIE}=nope"})
    assert response.status_code == 401


@pytest.mark.parametrize(
    "cookie",
    [
        f"{TOKEN_COOKIE}={TOKEN}",
        f"{TOKEN_COOKIE}={TOKEN}; junk",
        f"junk; {TOKEN_COOKIE}={TOKEN}",
        f"other=1; {TOKEN_COOKIE}={TOKEN}; another=2",
        f"broken=; {TOKEN_COOKIE}={TOKEN}",
        f"=nonsense; {TOKEN_COOKIE}={TOKEN}",
    ],
    ids=["alone", "trailing-junk", "leading-junk", "neighbours", "empty-value", "empty-name"],
)
async def test_a_malformed_neighbour_cookie_does_not_lose_ours(
    tmp_path: Path, cookie: str
) -> None:
    """Named regression: SimpleCookie discards the whole jar for one bad crumb.

    localhost is shared with whatever else the developer runs. One malformed
    cookie from another application and the carrier EventSource depends on
    silently stopped working, with a 401 nobody could explain.
    """
    response = await call(guarded(tmp_path), headers={**HOST, "cookie": cookie})
    assert response.status_code == 200


# -- the one time grant ----------------------------------------------------


async def test_the_query_grant_sets_the_cookie_and_redirects(tmp_path: Path) -> None:
    response = await call(guarded(tmp_path), path=f"/x?token={TOKEN}", headers=HOST)
    assert response.status_code == 303
    assert response.headers["location"] == "/x"
    cookie = response.headers["set-cookie"]
    assert f"{TOKEN_COOKIE}={TOKEN}" in cookie
    assert "HttpOnly" in cookie
    # Lax, not Strict. Strict is withheld on a cross site TOP LEVEL navigation,
    # which is the phone flow this exists for: grant once, then later tap a
    # Hitchrail link from a dashboard and be answered 401 by a cookie you hold.
    # Lax sends it on a top level GET and still withholds it from a cross site
    # POST, and mutations are behind the origin check regardless.
    assert "samesite=lax" in cookie.lower()
    # Not Secure: over plain HTTP on a LAN, a documented deployment, a Secure
    # cookie is never sent and the tool silently stops working.
    assert "secure" not in cookie.lower()


async def test_the_grant_preserves_other_query_parameters(tmp_path: Path) -> None:
    response = await call(
        guarded(tmp_path), path=f"/x?filter=running&token={TOKEN}", headers=HOST
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/x?filter=running"


async def test_the_grant_removes_the_token_from_the_location(tmp_path: Path) -> None:
    # The point of redirecting at all: the token leaves the address bar and the
    # browser history rather than sitting in both.
    response = await call(guarded(tmp_path), path=f"/x?token={TOKEN}", headers=HOST)
    assert TOKEN not in response.headers["location"]


@pytest.mark.parametrize(
    "path",
    ["/\\evil.example", "//evil.example", "/\\\\evil.example"],
    ids=["backslash", "protocol-relative", "double-backslash"],
)
async def test_the_grant_never_redirects_off_the_site(tmp_path: Path, path: str) -> None:
    """Named regression: a path is not automatically a safe redirect target.

    `/\\evil.example` survives as scope["path"] and browsers normalise the
    backslash, so the Location left the site. The client under test normalised
    `//evil.example` away, which is exactly why this cannot be left to the
    client.
    """
    response = await call(guarded(tmp_path), path=f"{path}?token={TOKEN}", headers=HOST)
    assert response.status_code == 303
    location = response.headers["location"]
    assert location == "/" or not location.startswith(("//", "/\\"))


async def test_a_wrong_query_token_grants_nothing(tmp_path: Path) -> None:
    response = await call(guarded(tmp_path), path="/x?token=nope", headers=HOST)
    assert response.status_code == 401
    assert "set-cookie" not in response.headers


async def test_the_grant_is_not_available_on_a_mutating_request(tmp_path: Path) -> None:
    # A grant on POST would let a link perform an action, which is the shape of
    # the attack the origin check exists to stop.
    response = await call(guarded(tmp_path), "POST", path=f"/x?token={TOKEN}", headers=ORIGIN)
    assert response.status_code == 401
    assert "set-cookie" not in response.headers


async def test_a_granted_cookie_authenticates_the_next_request(tmp_path: Path) -> None:
    app = guarded(tmp_path)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost", follow_redirects=True
    ) as client:
        first = await client.get(f"/x?token={TOKEN}", headers=HOST)
        assert first.status_code == 200
        assert client.cookies.get(TOKEN_COOKIE) == TOKEN
        # The cookie alone carries the next request, which is what EventSource
        # will rely on.
        again = await client.get("/x", headers=HOST)
        assert again.status_code == 200


# -- leakage and comparison ------------------------------------------------


async def test_the_token_never_appears_in_a_refusal(tmp_path: Path) -> None:
    for headers in (HOST, {**HOST, "authorization": "Bearer wrong"}):
        response = await call(guarded(tmp_path), headers=headers)
        assert TOKEN not in response.text


async def test_a_wrong_token_and_a_missing_one_are_indistinguishable(
    tmp_path: Path,
) -> None:
    missing = await call(guarded(tmp_path), headers=HOST)
    wrong = await call(guarded(tmp_path), headers={**HOST, "authorization": "Bearer x"})
    assert missing.status_code == wrong.status_code
    assert missing.json() == wrong.json()


def test_the_comparison_is_constant_time(monkeypatch: pytest.MonkeyPatch) -> None:
    # Asserting the call rather than trying to time it. A timing test on a
    # shared CI runner is a flaky test that teaches people to rerun the suite.
    seen: list[int] = []
    real = secrets.compare_digest

    def spy(a: bytes, b: bytes) -> bool:
        seen.append(1)
        return real(a, b)

    monkeypatch.setattr("hitchrail.security.secrets.compare_digest", spy)
    assert _token_matches(TOKEN, TOKEN)
    assert not _token_matches("wrong", TOKEN)
    assert len(seen) == 2


# -- ordering --------------------------------------------------------------


async def test_host_checking_happens_before_token_checking(tmp_path: Path) -> None:
    """Asserted so that deleting the token middleware would fail this test.

    Checking only that a forged host answers 400 rather than 401 also passes if
    the token check never runs at all, which is what happens if somebody
    removes it. So this sends a VALID token with a forged host and additionally
    asserts the comparison was never reached.
    """
    reached: list[int] = []
    real = secrets.compare_digest

    def spy(a: bytes, b: bytes) -> bool:
        reached.append(1)
        return real(a, b)

    app = guarded(tmp_path)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("hitchrail.security.secrets.compare_digest", spy)
        response = await call(
            app, headers={"host": "evil.example", "authorization": f"Bearer {TOKEN}"}
        )
    assert response.status_code == 400
    assert response.json()["code"] == "host_rejected"
    assert reached == [], "the token comparison ran despite a forged Host"


@pytest.mark.parametrize(
    ("raw_path", "must_not_contain"),
    [("/p/foo%23bar", "#"), ("/x%3Fa=1", "?a=1"), ("/a%25b", None)],
    ids=["encoded-hash", "encoded-question", "encoded-percent"],
)
async def test_the_grant_reencodes_a_decoded_path(
    tmp_path: Path, raw_path: str, must_not_contain: str | None
) -> None:
    """Named regression: ASGI has already percent decoded scope["path"].

    RedirectResponse treats `#` and `?` as safe, so `%23` in the request path
    became a real fragment in the Location and the browser silently dropped
    everything after it. Verified live before the fix:
    `/p/foo%23bar?token=...` redirected to `/p/foo#bar`.
    """
    response = await call(guarded(tmp_path), path=f"{raw_path}?token={TOKEN}", headers=HOST)
    assert response.status_code == 303
    location = response.headers["location"]
    if must_not_contain is not None:
        assert must_not_contain not in location


async def test_a_websocket_handshake_is_not_waved_through(tmp_path: Path) -> None:
    """Named regression: the token and origin middlewares skipped every non
    http scope, so a websocket route added later would arrive unauthenticated.

    There is no websocket route today. The host middleware already anticipated
    the scope type, and the other two did not, which is exactly the kind of
    gap that is invisible until the day somebody adds the route.
    """
    from hitchrail.config import Config
    from hitchrail.security import TokenMiddleware

    reached: list[int] = []

    async def app(scope: object, receive: object, send: object) -> None:
        reached.append(1)

    middleware = TokenMiddleware(app, token=TOKEN)
    sent: list[MutableMapping[str, Any]] = []

    async def receive() -> MutableMapping[str, Any]:
        return {"type": "websocket.connect"}

    async def send(message: MutableMapping[str, Any]) -> None:
        sent.append(message)

    await middleware(
        {"type": "websocket", "path": "/ws", "headers": [(b"host", b"localhost")]},
        receive,
        send,
    )
    assert reached == [], "an unauthenticated websocket handshake reached the app"
    assert Config(root=tmp_path).token is None


async def test_a_query_string_with_a_high_byte_is_a_refusal_not_a_crash(
    tmp_path: Path,
) -> None:
    """Named regression: the same strict decode trap, one function from the fix.

    `_maybe_grant` did `scope["query_string"].decode()`, which throws
    UnicodeDecodeError on any byte over 0x7f, inside the auth middleware. That
    is an unauthenticated 500 rather than a 401, and an attacker chooses the
    bytes. `header_map` documents this trap and avoids it with latin-1;
    Starlette's own QueryParams does the same.
    """
    app = guarded(tmp_path)
    sent: list[MutableMapping[str, Any]] = []

    async def receive() -> MutableMapping[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: MutableMapping[str, Any]) -> None:
        sent.append(message)

    await app(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/x",
            "raw_path": b"/x",
            "query_string": b"token=caf\xe9",
            "root_path": "",
            "headers": [(b"host", b"localhost")],
            "client": ("127.0.0.1", 5000),
            "server": ("127.0.0.1", 8787),
        },
        receive,
        send,
    )
    start = next(m for m in sent if m["type"] == "http.response.start")
    assert start["status"] == 401
