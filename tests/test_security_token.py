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
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.types import Scope

from hitchrail.config import Config
from hitchrail.security import (
    TOKEN_COOKIE,
    UNAUTHENTICATED,
    middleware_stack,
    route_path,
    token_matches,
)

TOKEN = "s3cret-token-value"
HOST = {"host": "localhost"}
ORIGIN = {**HOST, "origin": "http://localhost:8787"}


async def _ok(request: httpx.Request) -> JSONResponse:
    return JSONResponse({"ok": True})


def build(config: Config) -> Starlette:
    ok = _ok

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


@pytest.mark.integration
async def test_no_token_configured_means_no_token_demanded(tmp_path: Path) -> None:
    app = build(Config(root=tmp_path))
    assert (await call(app, headers=HOST)).status_code == 200


# -- the header carrier ----------------------------------------------------


@pytest.mark.integration
async def test_a_configured_token_is_demanded(tmp_path: Path) -> None:
    response = await call(guarded(tmp_path), headers=HOST)
    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"


@pytest.mark.integration
async def test_the_right_bearer_token_is_accepted(tmp_path: Path) -> None:
    response = await call(
        guarded(tmp_path), headers={**HOST, "authorization": f"Bearer {TOKEN}"}
    )
    assert response.status_code == 200


@pytest.mark.integration
@pytest.mark.parametrize("scheme", ["Bearer", "bearer", "BEARER", "BeArEr"])
async def test_the_bearer_scheme_is_case_insensitive(tmp_path: Path, scheme: str) -> None:
    # RFC 7235: auth schemes are case insensitive. A client sending "bearer" is
    # correct, and rejecting it is our bug rather than theirs.
    response = await call(
        guarded(tmp_path), headers={**HOST, "authorization": f"{scheme} {TOKEN}"}
    )
    assert response.status_code == 200


@pytest.mark.integration
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


@pytest.mark.integration
async def test_the_cookie_carrier_is_accepted(tmp_path: Path) -> None:
    response = await call(
        guarded(tmp_path), headers={**HOST, "cookie": f"{TOKEN_COOKIE}={TOKEN}"}
    )
    assert response.status_code == 200


@pytest.mark.integration
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


@pytest.mark.integration
async def test_a_wrong_cookie_is_rejected(tmp_path: Path) -> None:
    response = await call(guarded(tmp_path), headers={**HOST, "cookie": f"{TOKEN_COOKIE}=nope"})
    assert response.status_code == 401


@pytest.mark.integration
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


# -- leakage and comparison ------------------------------------------------


@pytest.mark.integration
async def test_the_token_never_appears_in_a_refusal(tmp_path: Path) -> None:
    for headers in (HOST, {**HOST, "authorization": "Bearer wrong"}):
        response = await call(guarded(tmp_path), headers=headers)
        assert TOKEN not in response.text


@pytest.mark.integration
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
    assert token_matches(TOKEN, TOKEN)
    assert not token_matches("wrong", TOKEN)
    assert len(seen) == 2


# -- ordering --------------------------------------------------------------


@pytest.mark.integration
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


# -- #20: the token must not reach the access log on ANY path ---------------
#
# The scrub used to live inside `_maybe_grant`, which is only reached when no
# valid header and no valid cookie were presented AND the method is safe.
# Three reachable paths therefore still logged the token in cleartext.


def _scope_seen_by(app_scope: list[Scope]) -> Scope:
    assert app_scope, "the request never reached the application"
    return app_scope[-1]


def _recording_app(config: Config) -> tuple[Starlette, list[Scope]]:
    """An app that keeps the scope it was handed.

    uvicorn builds its access line from this same dict after the app returns,
    so what the application sees here is what the logger prints. Asserting on
    the scope is the hermetic half of the live socket test that pins the real
    logger.
    """
    seen: list[Scope] = []

    async def ok(request: Request) -> JSONResponse:
        seen.append(request.scope)
        return JSONResponse({"ok": True})

    app = Starlette(
        routes=[Route("/x", ok, methods=["GET", "POST"])],
        middleware=middleware_stack(config),
    )
    return app, seen


# -- #21: the two paths reachable without a token ---------------------------


@pytest.mark.integration
async def test_the_grant_paths_are_the_only_ones_exempt(tmp_path: Path) -> None:
    """The exemption is a list of two, and nothing else may join it by accident.

    A fragment is readable only by JavaScript in the browser, so the flow needs
    one unauthenticated door. That door was argued: a dedicated route rather
    than the app shell on a 401, because every future addition to the shell
    would inherit the exemption.
    """
    app = build(
        Config(root=tmp_path, host="0.0.0.0", token=TOKEN),
    )
    for path in ("/x", "/deep/path", "/api/events"):
        assert (await call(app, path=path, headers=HOST)).status_code == 401, path


@pytest.mark.integration
@pytest.mark.parametrize("path", ["/grant", "/api/grant"])
async def test_an_exempt_path_reaches_the_application(tmp_path: Path, path: str) -> None:
    """Asserted through the middleware stack rather than by reading the set.

    A test that only read `UNAUTHENTICATED` would pass against a
    middleware that never consulted it.
    """
    app = Starlette(
        routes=[
            Route("/grant", _ok, methods=["GET"]),
            Route("/api/grant", _ok, methods=["POST"]),
        ],
        middleware=middleware_stack(Config(root=tmp_path, host="0.0.0.0", token=TOKEN)),
    )
    method = "POST" if path.startswith("/api/") else "GET"
    response = await call(app, method, path=path, headers=ORIGIN)
    assert response.status_code == 200


@pytest.mark.integration
async def test_an_exempt_path_is_matched_exactly(tmp_path: Path) -> None:
    """`/grant` and not `/grantstuff`, `/grant/x` or `/x/grant`.

    A prefix or substring test here would exempt anything a route was later
    mounted under, which is the whole boundary given away by a comparison
    operator.
    """
    app = Starlette(
        routes=[
            Route("/grantstuff", _ok, methods=["GET"]),
            Route("/grant/x", _ok, methods=["GET"]),
            Route("/x/grant", _ok, methods=["GET"]),
        ],
        middleware=middleware_stack(Config(root=tmp_path, host="0.0.0.0", token=TOKEN)),
    )
    for path in ("/grantstuff", "/grant/x", "/x/grant"):
        assert (await call(app, path=path, headers=HOST)).status_code == 401, path


@pytest.mark.integration
async def test_an_exempt_path_still_answers_to_the_host_allowlist(tmp_path: Path) -> None:
    """Host is outermost, and the exemption is inside it. A rebound request
    must not reach the one page that is served without a token either."""
    app = Starlette(
        routes=[Route("/grant", _ok, methods=["GET"])],
        middleware=middleware_stack(Config(root=tmp_path, host="0.0.0.0", token=TOKEN)),
    )
    response = await call(app, path="/grant", headers={"host": "evil.example"})
    assert response.status_code == 400
    assert response.json()["code"] == "host_rejected"


@pytest.mark.integration
async def test_the_grant_api_still_answers_to_the_origin_check(tmp_path: Path) -> None:
    """A grant is MUTATING, so a link must not be able to perform one. That is
    the whole reason it is a POST rather than a GET."""
    app = Starlette(
        routes=[Route("/api/grant", _ok, methods=["POST"])],
        middleware=middleware_stack(Config(root=tmp_path, host="0.0.0.0", token=TOKEN)),
    )
    response = await call(
        app, "POST", path="/api/grant", headers={**HOST, "origin": "http://evil.example"}
    )
    assert response.status_code == 403
    assert response.json()["code"] == "origin_rejected"


# -- #21 round 1: what the review found -------------------------------------


@pytest.mark.integration
async def test_head_on_the_grant_page_is_exempt_like_get(tmp_path: Path) -> None:
    """Starlette adds HEAD to every route that has GET, so the router DOES
    serve `HEAD /grant`. A guard that refused it named a different route from
    the one that runs, which is the reason the comparison uses `route_path` in
    the first place. It failed closed, so this is correctness and not a hole.
    """
    app = Starlette(
        routes=[Route("/grant", _ok, methods=["GET"])],
        middleware=middleware_stack(Config(root=tmp_path, host="0.0.0.0", token=TOKEN)),
    )
    assert (await call(app, "HEAD", path="/grant", headers=HOST)).status_code == 200


def test_the_exemption_is_exactly_three_entries() -> None:
    """The cheapest guard there is, and it was the missing one.

    Every other test here probes paths a test file chose, so adding
    `/api/projects` to the set left all of them green. `.claude/rules/security.md`
    says an added entry needs the argument #21 made; this is what mechanically
    notices there is one. It NAMES the entries rather than counting them, which
    is the difference between this and the comment beside the set, which said
    "two long" for a while after the set had three.
    """
    assert (
        frozenset(
            {
                ("http", "GET", "/grant"),
                ("http", "HEAD", "/grant"),
                ("http", "POST", "/api/grant"),
            }
        )
        == UNAUTHENTICATED
    )


@pytest.mark.integration
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/grant"),
        ("DELETE", "/grant"),
        ("GET", "/api/grant"),
        ("HEAD", "/api/grant"),
    ],
)
async def test_the_exemption_is_scoped_to_one_method_each(
    tmp_path: Path, method: str, path: str
) -> None:
    """A path alone exempts every method on it.

    The router turns the extras into 405 today, so nothing is reachable, and
    that is the router's doing rather than the guard's. Widening
    `/api/grant` to `methods=["POST", "DELETE"]` would have arrived
    unauthenticated with every test green.
    """
    app = Starlette(
        routes=[
            Route("/grant", _ok, methods=["GET", "POST", "DELETE"]),
            Route("/api/grant", _ok, methods=["GET", "POST"]),
        ],
        middleware=middleware_stack(Config(root=tmp_path, host="0.0.0.0", token=TOKEN)),
    )
    response = await call(app, method, path=path, headers=ORIGIN)
    assert response.status_code == 401, f"{method} {path} arrived unauthenticated"


async def test_a_websocket_to_an_exempt_path_is_not_exempt(tmp_path: Path) -> None:
    """The exemption is keyed on the scope type as well as the method.

    `test_a_websocket_handshake_is_not_waved_through` above is the same
    argument for the general case: the token middleware once skipped every non
    http scope, so a websocket route added later would have arrived
    unauthenticated. An exemption keyed on the path alone would reopen that,
    on the two paths where it matters most.
    """
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

    for path in ("/grant", "/api/grant"):
        await middleware(
            {"type": "websocket", "path": path, "headers": [(b"host", b"localhost")]},
            receive,
            send,
        )
        assert reached == [], f"an unauthenticated websocket reached the app at {path}"
    assert tmp_path.is_dir()


def test_our_route_path_agrees_with_starlettes() -> None:
    """`security.route_path` duplicates six lines of Starlette.

    Deliberately: the function lives in `starlette._utils`, and
    `starlette.routing` re-exports it without declaring it, so the public
    spelling fails mypy and the private one can move in a patch release. This
    is what stops the duplicate drifting. It reads the private symbol on
    purpose, because a TEST that stops importing is a loud failure and a guard
    that stops importing is a deployment.
    """
    from starlette._utils import get_route_path as theirs

    cases = [
        ("/grant", ""),
        ("/grant", "/"),
        ("/hitchrail/grant", "/hitchrail"),
        ("/hitchrail", "/hitchrail"),
        ("/hitchrailish/grant", "/hitchrail"),
        ("/api/grant", "/api"),
        ("/other/grant", "/hitchrail"),
        ("", ""),
    ]
    for path, root in cases:
        scope = {"path": path, "root_path": root}
        assert route_path(scope) == theirs(scope), (path, root)


@pytest.mark.integration
async def test_the_guard_and_the_router_agree_behind_a_sub_path_proxy(
    tmp_path: Path,
) -> None:
    """Comparing the unstripped path meant the guard named one route and the
    router served another. Not exploitable, because every suffix that could
    differ is itself exempt, but behind a sub path proxy it made the grant flow
    unreachable: `GET /hitchrail/grant` was not exempt, so it answered 401."""
    app = Starlette(
        routes=[Route("/grant", _ok, methods=["GET"])],
        middleware=middleware_stack(Config(root=tmp_path, host="0.0.0.0", token=TOKEN)),
    )
    transport = httpx.ASGITransport(app, root_path="/hitchrail")
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as c:
        response = await c.get("/hitchrail/grant", headers=HOST)
    assert response.status_code == 200, response.text


def test_a_token_that_utf8_cannot_encode_is_false_and_not_a_crash() -> None:
    """The same bug this function's docstring records as fixed, a second time.

    Every carrier that existed then is decoded as latin-1, so all of them
    produce a str UTF-8 can encode. #21 added a JSON body, and the JSON decoder
    accepts a lone surrogate: an unauthenticated 500 on the one route reachable
    without a token, where every other input gets 401.
    """
    # REAL surrogates. An earlier draft wrote `"\\ud800"`, which is six ASCII
    # characters, so it passed against the UNFIXED comparison: the commit that
    # claimed to re-arm six tests shipped this one disarmed.
    assert len("\ud800") == 1, "not a lone surrogate"
    assert token_matches("\ud800", TOKEN) is False
    assert token_matches("a\udfffb", TOKEN) is False
    assert token_matches(TOKEN, TOKEN) is True


# -- #112: which refusal answers first --------------------------------------
#
# `middleware_stack` promises "Order matters, and it is asserted by a test
# rather than left to habit". Host outermost was asserted, by
# `test_an_exempt_path_still_answers_to_the_host_allowlist` above. Token before
# Origin was asserted by nothing, because `tests/test_security_origin.py`
# builds almost every case with a tokenless loopback config and therefore runs
# with the middleware under discussion switched off.
#
# The property is not cosmetic: if Origin answered first, a caller with no
# token could enumerate the origin allowlist by watching 403 turn into 401, and
# that allowlist names the hosts this machine answers to.

FOREIGN = {**HOST, "origin": "http://evil.example"}


@pytest.mark.integration
async def test_a_missing_token_answers_before_the_origin_check(tmp_path: Path) -> None:
    response = await call(guarded(tmp_path), "POST", headers=FOREIGN)
    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"


@pytest.mark.integration
async def test_a_wrong_token_answers_before_the_origin_check(tmp_path: Path) -> None:
    """A wrong token must not be distinguishable from a missing one here
    either, or the ordering buys nothing: both have to stop short of Origin."""
    response = await call(
        guarded(tmp_path), "POST", headers={**FOREIGN, "authorization": "Bearer wrong"}
    )
    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"


@pytest.mark.integration
async def test_a_valid_token_still_meets_the_origin_check(tmp_path: Path) -> None:
    """The control the two tests above must not have disabled. Authenticating
    gets you past the token, not past CSRF."""
    response = await call(
        guarded(tmp_path), "POST", headers={**FOREIGN, "authorization": f"Bearer {TOKEN}"}
    )
    assert response.status_code == 403
    assert response.json()["code"] == "origin_rejected"


@pytest.mark.integration
async def test_a_forged_host_answers_before_both(tmp_path: Path) -> None:
    """Host stays outermost even when every other credential is wrong, so the
    full precedence reads in one place rather than across three files."""
    response = await call(
        guarded(tmp_path),
        "POST",
        headers={
            "host": "evil.lan",
            "origin": "http://evil.example",
            "authorization": "Bearer wrong",
        },
    )
    assert response.status_code == 400
    assert response.json()["code"] == "host_rejected"


# -- #115: the query carrier is gone --------------------------------------


@pytest.mark.integration
@pytest.mark.parametrize("method", ["GET", "HEAD"])
async def test_a_query_token_is_no_longer_a_carrier(tmp_path: Path, method: str) -> None:
    """`?token=` used to be traded for a cookie. It is a query parameter now.

    Safe methods are the ones the grant used to accept, so they are the ones
    worth asserting: a correct token in the query buys nothing.
    """
    response = await call(guarded(tmp_path), method, path=f"/x?token={TOKEN}", headers=HOST)
    assert response.status_code == 401
    if method != "HEAD":
        assert response.json()["code"] == "unauthorized"


@pytest.mark.integration
async def test_the_query_string_is_no_longer_rewritten(tmp_path: Path) -> None:
    """The scrub went with the carrier, and this asserts the consequence.

    `_scrub_grant_param` existed to keep the token out of uvicorn's access
    line, which it built from this same scope after the app returned. Nothing
    accepts a token there now, so nothing rewrites a caller's query string, and
    a route sees exactly what was sent.

    **The token does reach the access log if somebody puts it in a URL**, and
    that is correct rather than a regression: it is not a credential this
    server accepts, and scrubbing it would be the misleading half of the old
    behaviour kept without the useful half.
    """
    config = Config(root=tmp_path, token=TOKEN)
    app, seen = _recording_app(config)
    response = await call(
        app,
        path=f"/x?token={TOKEN}&keep=1",
        headers={"host": "localhost", "cookie": f"{TOKEN_COOKIE}={TOKEN}"},
    )
    assert response.status_code == 200
    query = _scope_seen_by(seen)["query_string"].decode("latin-1")
    assert query == f"token={TOKEN}&keep=1", "a caller's query string is not ours to edit"
