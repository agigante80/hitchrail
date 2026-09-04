"""The host allowlist: DNS rebinding defence, and the control the CVE was about.

Driven through httpx.ASGITransport against a real Starlette app, so the
middleware stack under test is the one that ships. No socket is opened here;
the live socket tier is tests/test_live_socket.py.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import JSONResponse
from starlette.routing import Route

from hitchrail.config import Config
from hitchrail.security import HostAllowlistMiddleware, middleware_stack, parse_host
from support import make_config


def build(config: Config) -> Starlette:
    async def ok(request: httpx.Request) -> JSONResponse:
        return JSONResponse({"ok": True})

    return Starlette(
        routes=[
            Route("/x", ok, methods=["GET", "POST"]),
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


def fixed_resolver(*addresses: str) -> Callable[[], tuple[str, ...]]:
    return lambda: tuple(addresses)


# -- parse_host ------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("localhost", "localhost"),
        ("localhost:8787", "localhost"),
        ("LOCALHOST", "localhost"),
        ("  localhost  ", "localhost"),
        ("192.168.1.10:8787", "192.168.1.10"),
        ("[::1]", "::1"),
        ("[::1]:8787", "::1"),
        ("[2001:db8::5]:8787", "2001:db8::5"),
        ("[2001:DB8::5]", "2001:db8::5"),
        # A bare IPv6 is not a legal Host header, and cannot be told apart from
        # a host and a port without guessing. Refuse rather than guess.
        ("::1", ""),
        ("2001:db8::5", ""),
        ("[unclosed", ""),
        ("", ""),
        (":8787", ""),
    ],
)
def test_parse_host_normalises_every_form_a_browser_sends(raw: str, expected: str) -> None:
    assert parse_host(raw) == expected


def test_an_unparseable_host_can_never_match(tmp_path: Path) -> None:
    # parse_host returns "" for anything malformed, and Config filters empty
    # entries out of the allowlist, so "" matches nothing. Asserted rather than
    # assumed, because it is the whole fail closed argument.
    cfg = make_config(tmp_path)
    assert "" not in cfg.allowed_hosts
    assert parse_host("[unclosed") == ""


# -- refusals --------------------------------------------------------------


@pytest.mark.integration
async def test_a_known_host_is_served(tmp_path: Path) -> None:
    app = build(make_config(tmp_path))
    assert (await call(app, headers={"host": "localhost"})).status_code == 200


@pytest.mark.integration
async def test_a_host_with_a_port_still_matches(tmp_path: Path) -> None:
    app = build(make_config(tmp_path))
    assert (await call(app, headers={"host": "localhost:8787"})).status_code == 200


@pytest.mark.integration
@pytest.mark.parametrize(
    "host",
    [
        "evil.example",
        "localhost.evil.example",
        "evil.example.localhost",
        "127.0.0.1.evil.example",
        "",
        "[unclosed",
        "localhost\tevil",
    ],
    ids=[
        "foreign",
        "prefix-confusion",
        "suffix-confusion",
        "ip-prefix",
        "empty",
        "malformed-bracket",
        "whitespace-smuggling",
    ],
)
async def test_a_forged_host_is_rejected(tmp_path: Path, host: str) -> None:
    """DNS rebinding.

    Without this, any page the user visits in any browser on the network can
    rebind a name to this address and drive the API from their own browser,
    with the browser treating the response as same origin. That is
    CVE-2026-32632 in Glances, verbatim, and Hitchrail has the worse blast
    radius because it starts processes rather than reporting on them.
    """
    app = build(make_config(tmp_path))
    response = await call(app, headers={"host": host})
    assert response.status_code == 400
    assert response.json()["code"] == "host_rejected"


@pytest.mark.integration
async def test_the_event_stream_is_behind_the_allowlist_too(tmp_path: Path) -> None:
    # The route people forget, and the one an attacker most wants: a long lived
    # stream of everything happening on the machine.
    app = build(make_config(tmp_path))
    response = await call(app, path="/api/events", headers={"host": "evil.example"})
    assert response.status_code == 400


# -- IPv6, which is why this is not TrustedHostMiddleware -------------------


@pytest.mark.integration
async def test_an_ipv6_loopback_browser_is_served(tmp_path: Path) -> None:
    """Named regression: Starlette's TrustedHostMiddleware cannot do this.

    It does `host.split(":")[0]`, which turns every IPv6 literal into "[", so
    `http://[::1]:8787/` is refused whatever the allowlist holds. That is why
    this project writes its own ten lines.
    """
    app = build(make_config(tmp_path))
    for host in ("[::1]", "[::1]:8787"):
        assert (await call(app, headers={"host": host})).status_code == 200


@pytest.mark.integration
async def test_an_ipv6_lan_address_is_served_when_allowed(tmp_path: Path) -> None:
    cfg = make_config(
        tmp_path,
        host="0.0.0.0",
        token="t",
        resolver=fixed_resolver("2001:db8::5"),
    )
    app = build(cfg)
    # A non loopback bind demands a token, so this carries one: the subject
    # here is the host check, not the absence of authentication.
    response = await call(
        app, headers={"host": "[2001:db8::5]:8787", "authorization": "Bearer t"}
    )
    assert response.status_code == 200


@pytest.mark.integration
async def test_stripping_brackets_did_not_become_any_ipv6_is_fine(tmp_path: Path) -> None:
    cfg = make_config(
        tmp_path,
        host="0.0.0.0",
        token="t",
        resolver=fixed_resolver("2001:db8::5"),
    )
    app = build(cfg)
    response = await call(
        app, headers={"host": "[2001:db8::9]:8787", "authorization": "Bearer t"}
    )
    assert response.status_code == 400


# -- no redirect, ever -----------------------------------------------------


@pytest.mark.integration
async def test_an_unrecognised_host_is_refused_never_redirected(tmp_path: Path) -> None:
    """Named regression: Starlette's www_redirect default does redirect.

    Given `www.box.lan` in the allowlist and `Host: box.lan`, it answers 307
    with `Location: http://www.box.lan/x`, a redirect built from the same
    untrusted header, in the middleware whose whole job is not trusting it.
    """
    cfg = make_config(tmp_path, host="0.0.0.0", token="t", extra_hosts=("www.box.lan",))
    app = build(cfg)
    response = await call(app, headers={"host": "box.lan"})
    assert response.status_code == 400
    assert "location" not in response.headers


@pytest.mark.integration
async def test_the_refusal_uses_the_api_error_envelope(tmp_path: Path) -> None:
    # One shape for every refusal, so a client parses one thing. Starlette's
    # version answers with a plain text body instead.
    app = build(make_config(tmp_path))
    response = await call(app, headers={"host": "evil.example"})
    assert set(response.json()) == {"code", "message"}
    assert response.headers["content-type"].startswith("application/json")


@pytest.mark.integration
async def test_no_wildcard_is_honoured_even_if_one_reached_the_allowlist(
    tmp_path: Path,
) -> None:
    # Config refuses a wildcard entry, so this can only happen if somebody
    # constructs the middleware directly. It must not mean "allow everything",
    # which is what Starlette's implementation does with "*".

    async def ok(request: httpx.Request) -> JSONResponse:
        return JSONResponse({"ok": True})

    app = Starlette(
        routes=[Route("/x", ok)],
        middleware=[Middleware(HostAllowlistMiddleware, allowed_hosts=frozenset({"*"}))],
    )
    assert (await call(app, headers={"host": "evil.example"})).status_code == 400


def test_a_repeated_header_keeps_the_first_like_the_rest_of_the_stack() -> None:
    """Named regression: this collapsed duplicates to the LAST.

    Starlette's `Headers.get` returns the first, so a request carrying two of
    the same header authenticated differently here than everywhere else that
    reads it, and a difference like that is where request smuggling lives.
    """
    from hitchrail.security import header_map

    scope = {"headers": [(b"host", b"first"), (b"host", b"second")]}
    assert header_map(scope)["host"] == "first"


def test_split_cookie_headers_are_joined_not_dropped() -> None:
    """Named regression: HTTP/2 may split the cookie jar across fields.

    RFC 9113 lets a client send several Cookie fields, and reverse proxies do
    it too. Taking one and dropping the rest lost whichever half held the
    token, so the same two headers in the other order answered differently.
    """
    from hitchrail.security import header_map

    scope = {"headers": [(b"cookie", b"a=1"), (b"cookie", b"hitchrail_token=tok")]}
    assert header_map(scope)["cookie"] == "a=1; hitchrail_token=tok"

    reversed_scope = {"headers": [(b"cookie", b"hitchrail_token=tok"), (b"cookie", b"a=1")]}
    assert "hitchrail_token=tok" in header_map(reversed_scope)["cookie"]


# -- #19: a root dot on the Host header ------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("box.lan.", "box.lan"),
        ("box.lan.:8787", "box.lan"),
        ("BOX.LAN.", "box.lan"),
        ("box.lan...", "box.lan"),
        # Not a host at all once the dots go, so it matches nothing.
        (".", ""),
        ("..", ""),
    ],
)
def test_parse_host_strips_the_root_dot(raw: str, expected: str) -> None:
    """The header side of #19.

    Stripping in `config.normalise_host` alone made things worse: the two
    sides then disagreed and no spelling of `--allow-host` served a dotted
    Host. Both doors strip, or neither does.
    """
    assert parse_host(raw) == expected


@pytest.mark.integration
@pytest.mark.parametrize("configured", ["box.lan", "box.lan."])
@pytest.mark.parametrize("sent", ["box.lan", "box.lan."])
async def test_dotted_and_undotted_hosts_all_match(
    tmp_path: Path, configured: str, sent: str
) -> None:
    """All four combinations, because the defect was asymmetry.

    Testing one direction passes while the other is broken, which is exactly
    how the first attempt shipped.
    """
    cfg = make_config(
        tmp_path,
        host="0.0.0.0",
        token="t",
        extra_hosts=(configured,),
        resolver=fixed_resolver("10.0.0.2"),
    )
    response = await call(build(cfg), headers={"host": sent, "authorization": "Bearer t"})
    assert response.status_code == 200


@pytest.mark.parametrize("raw", ["[::1]junk", "[::1]x", "[2001:db8::5]/path", "[::1]]"])
def test_junk_after_the_closing_bracket_can_never_match(raw: str) -> None:
    """Anything following `]` must be a port, or the header is not a host.

    Returning the bracketed part regardless would accept
    `Host: [::1]@evil.example` as `::1`, which is a host we serve. Refusing
    outright is what makes the allowlist a whitelist rather than a prefix test.
    """
    assert parse_host(raw) == ""
