"""The controls that stand between a web page and a shell on this machine.

Hitchrail spawns `claude --dangerously-skip-permissions`. Anyone who can drive
this API can run arbitrary code as the user who started it, so each control
below is a refusal, and each has a test that asserts the refusal rather than
the success path.

The host allowlist is not optional. CVE-2026-32632 (GHSA-hhcg-r27j-fhv9) hit
Glances, a localhost and LAN monitoring web UI, for exactly this gap: no host
validation, therefore DNS rebinding, therefore an attacker's page reading the
API through the victim's own browser. Fixed in 4.5.2 by adding a host
allowlist. Hitchrail has the same shape and a worse blast radius, because it
starts processes rather than reporting on them.
"""

from __future__ import annotations

import secrets
from urllib.parse import parse_qsl, urlencode

from starlette.middleware import Middleware
from starlette.requests import cookie_parser
from starlette.responses import JSONResponse, RedirectResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from hitchrail.config import Config

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
# The cookie NAME, not a secret. S105 pattern matches on the word "token".
TOKEN_COOKIE = "hitchrail_token"  # noqa: S105
GRANT_PARAM = "token"
# Thirty days. Long enough that a phone is not re-granted every session, short
# enough that a device left behind stops working eventually.
COOKIE_MAX_AGE = 60 * 60 * 24 * 30


def deny(status: int, code: str, message: str) -> JSONResponse:
    """Every refusal uses the envelope the API uses, so a client parses one shape."""
    return JSONResponse({"code": code, "message": message}, status_code=status)


def header_map(scope: Scope) -> dict[str, str]:
    """Lowercased header names, decoded once per request.

    latin-1, which is what RFC 7230 says an HTTP header field is and what
    Starlette's own `Headers` uses. It is also the only choice that cannot
    raise: utf-8 strict throws `UnicodeDecodeError` on a header carrying
    latin-1 bytes, and an attacker chooses those bytes, so decoding strictly
    here is an unauthenticated crash rather than a refusal.

    Shared because all three middlewares need it and decoding the raw scope
    headers three times per request is work nobody asked for.
    """
    headers: dict[str, str] = {}
    for raw_key, raw_value in scope["headers"]:
        key = raw_key.decode("latin-1").lower()
        value = raw_value.decode("latin-1")
        if key == "cookie":
            # RFC 9113 lets an HTTP/2 client split the cookie jar across
            # several Cookie fields, and reverse proxies do it too. Joining
            # them is what the spec says to do; taking one and dropping the
            # rest loses whichever half held our token.
            headers[key] = f"{headers[key]}; {value}" if key in headers else value
        elif key not in headers:
            # First wins, which is what Starlette's Headers.get returns. Taking
            # the last meant this middleware authenticated a request
            # differently from the rest of the stack that reads the same
            # header, and a difference like that is where smuggling lives.
            headers[key] = value
    return headers


def parse_host(raw: str) -> str:
    """A Host header to a bare host: brackets stripped, port removed, lowercased.

    Returns "" for anything malformed, which matches no allowlist entry because
    `Config` filters empty entries out, so an unparseable Host is refused
    rather than guessed at.

    This exists rather than `TrustedHostMiddleware` because that does
    `host.split(":")[0]`, which turns every IPv6 literal into "[":

        Host: localhost:8787       ->  localhost   ->  served
        Host: [::1]:8787           ->  [           ->  400
        Host: [2001:db8::5]:8787   ->  [           ->  400

    so `http://[::1]:8787/` is refused whatever the allowlist holds, and a
    phone on an IPv6 network cannot reach Hitchrail at all.
    """
    value = raw.strip().lower()
    if value.startswith("["):
        end = value.find("]")
        if end == -1:
            return ""
        # Anything after the closing bracket must be a port, or this is junk.
        rest = value[end + 1 :]
        if rest and not rest.startswith(":"):
            return ""
        return value[1:end]
    # A bare `::1` is not a legal Host header, and more than one colon in an
    # unbracketed value means it is not a host and a port either. Refuse both
    # rather than guess which half is the host.
    if value.count(":") > 1:
        return ""
    host = value.split(":")[0]
    # A Host header has no whitespace in it. Smuggling one past a proxy that
    # splits differently is a known trick, so anything containing it is junk.
    return "" if any(c.isspace() for c in host) else host


class HostAllowlistMiddleware:
    """DNS rebinding defence, applied to every route including the event stream.

    No wildcards, deliberately. `Config` already refuses a wildcard entry, so
    honouring one here would implement a feature the layer below rejects, and
    "*" would then mean "allow everything" the way Starlette's does.

    No www redirect either. Answering an unrecognised Host with a redirect
    built from that same Host is the opposite of not trusting it, and it is
    what `TrustedHostMiddleware` does by default.
    """

    def __init__(self, app: ASGIApp, allowed_hosts: frozenset[str]) -> None:
        self.app = app
        self.allowed = frozenset(h.lower() for h in allowed_hosts if h and h != "*")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):  # pragma: no cover - lifespan
            await self.app(scope, receive, send)
            return

        host = parse_host(header_map(scope).get("host", ""))
        if host not in self.allowed:
            await deny(400, "host_rejected", "unrecognised Host header")(scope, receive, send)
            return
        await self.app(scope, receive, send)


class OriginCheckMiddleware:
    """CSRF control for a same origin JSON API.

    Browsers attach Origin to cross site requests and a rebound attacker cannot
    forge it, so requiring it to name an origin we already serve is sufficient
    here and needs no token round trip.

    Exact origins, not hostnames. Matching on hostname alone would make
    `http://localhost:3000` same origin with an API equivalent to a shell, so
    every other development server on the machine could drive it.

    Safe methods are exempt, and that is deliberate rather than an oversight:
    `EventSource` cannot set request headers, so `/api/events` cannot carry an
    Origin requirement. There is a named test asserting the exemption exists on
    purpose, because otherwise somebody notices the gap, fixes it, and silently
    breaks every live update in the product.
    """

    def __init__(self, app: ASGIApp, allowed_origins: frozenset[str]) -> None:
        self.app = app
        self.allowed = frozenset(o.strip().rstrip("/").lower() for o in allowed_origins)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):  # pragma: no cover - lifespan
            await self.app(scope, receive, send)
            return
        # A websocket handshake has no method and is never safe: it is a long
        # lived connection, so it is checked rather than waved through. There
        # is no websocket route today, and adding one later must not silently
        # arrive unauthenticated because this middleware only knew about http.
        if scope["type"] == "http" and scope["method"] in SAFE_METHODS:
            await self.app(scope, receive, send)
            return

        origin = header_map(scope).get("origin", "")
        if not origin:
            await deny(403, "origin_missing", "this request needs an Origin header")(
                scope, receive, send
            )
            return
        # Scheme and host are case insensitive per RFC 3986, and some clients
        # append a slash that is not part of an origin. Normalise both rather
        # than turn either into a refusal nobody can explain.
        if origin.strip().rstrip("/").lower() not in self.allowed:
            await deny(403, "origin_rejected", f"origin not allowed: {origin}")(
                scope, receive, send
            )
            return
        await self.app(scope, receive, send)


def _token_matches(presented: str, expected: str) -> bool:
    """Constant time, always. `==` on a secret leaks its prefix through timing.

    Compared as BYTES. `compare_digest` on `str` raises TypeError for anything
    non ASCII, and `presented` comes from an attacker supplied header, cookie
    or query value, so the str form turned `Authorization: Bearer café` into an
    unauthenticated 500.
    """
    return secrets.compare_digest(presented.encode("utf-8"), expected.encode("utf-8"))


def _bearer(header: str) -> str:
    """Extract a bearer credential. RFC 7235 auth schemes are case insensitive.

    Exactly one space, and the credential is not trimmed. `Bearer  token` with
    two spaces means the credential is ` token`, which is not the token, and a
    security control has no business deciding the client meant something other
    than what it sent.
    """
    scheme, separator, credential = header.partition(" ")
    if not separator or scheme.lower() != "bearer":
        return ""
    return credential


def _safe_redirect_path(path: str) -> str:
    r"""A path is not automatically a safe redirect target.

    `/\evil.example` survives as `scope["path"]`, and browsers normalise the
    backslash, so a Location built from it leaves the site. `//evil.example` is
    protocol relative and does the same thing more obviously. One client under
    test normalised the second away by itself, which is exactly why this cannot
    be left to the client.
    """
    if not path.startswith("/") or path[1:2] in {"/", "\\"}:
        return "/"
    # ASGI has already percent decoded the path, and RedirectResponse treats
    # `#` and `?` as safe characters, so a `%23` in the request path became a
    # real fragment in the Location and the browser silently dropped
    # everything after it. Verified live: `/p/foo%23bar` redirected to
    # `/p/foo#bar`. Re-encode both rather than trying to guess intent.
    return path.replace("%", "%25").replace("#", "%23").replace("?", "%3F")


class TokenMiddleware:
    """One shared token, over three carriers.

    `EventSource` cannot set request headers, so a token that lives only in
    `Authorization` authenticates every route except the live update stream,
    which is the one the interface exists to use. The cookie is the carrier
    `EventSource` can use; the query grant is how that cookie gets set from a
    link you open on a phone.

    The cookie is `SameSite=Lax`, not `Strict`, and the origin check still runs
    on every mutating request. Either alone would cover the cases we can think
    of, which is why there are two.

    Lax rather than Strict because Strict is withheld on a cross site TOP LEVEL
    navigation, which is exactly the phone flow this exists for: grant the
    cookie once, then later tap a Hitchrail link from a dashboard or a message
    and be answered 401 by a cookie you do hold, which a reload then fixes. Lax
    sends it on a top level GET and still withholds it from a cross site POST,
    and the mutations that matter are behind the origin check regardless.

    It is deliberately not `Secure`. Over plain HTTP on a LAN, a documented and
    supported deployment, a `Secure` cookie is never sent and the tool silently
    stops working. The cleartext exposure is stated as a limitation in the
    README, with a TLS terminating proxy as the remedy.
    """

    def __init__(self, app: ASGIApp, token: str | None) -> None:
        self.app = app
        self.token = token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket") or self.token is None:
            await self.app(scope, receive, send)
            return

        headers = header_map(scope)

        presented = _bearer(headers.get("authorization", ""))
        if presented and _token_matches(presented, self.token):
            await self.app(scope, receive, send)
            return

        # cookie_parser, not SimpleCookie: SimpleCookie discards the WHOLE jar
        # when any crumb is malformed, so one bad cookie set by another
        # application on the same host silently stops us authenticating.
        offered = cookie_parser(headers.get("cookie", "")).get(TOKEN_COOKIE)
        if offered is not None and _token_matches(offered, self.token):
            await self.app(scope, receive, send)
            return

        # The grant is an HTTP redirect, so it has no meaning for a websocket
        # handshake; such a connection is refused rather than granted.
        if (
            scope["type"] == "http"
            and scope["method"] in SAFE_METHODS
            and await self._maybe_grant(scope, receive, send)
        ):
            return

        await deny(401, "unauthorized", "a valid token is required")(scope, receive, send)

    async def _maybe_grant(self, scope: Scope, receive: Receive, send: Send) -> bool:
        """Trade `?token=` for a cookie, then redirect the token out of the URL.

        Safe methods only. A grant on a mutating request would let a link
        perform an action, which is the shape of the attack the origin check
        exists to stop.

        Returns True when it answered the request.
        """
        assert self.token is not None
        # latin-1, for the reason header_map spells out: an attacker picks
        # these bytes, and `.decode()` strict throws UnicodeDecodeError on a
        # byte over 0x7f, which is an unauthenticated 500 rather than a 401.
        # Starlette's own QueryParams uses latin-1 too. This trap was fixed for
        # headers and missed here, one function away.
        query = scope.get("query_string", b"").decode("latin-1")
        params = parse_qsl(query, keep_blank_values=True)
        offered = next((v for k, v in params if k == GRANT_PARAM), None)
        if offered is None or not _token_matches(offered, self.token):
            return False

        remaining = urlencode([(k, v) for k, v in params if k != GRANT_PARAM])
        path = _safe_redirect_path(scope["path"])
        location = f"{path}?{remaining}" if remaining else path

        response = RedirectResponse(location, status_code=303)
        response.set_cookie(
            TOKEN_COOKIE,
            self.token,
            httponly=True,
            samesite="lax",
            path="/",
            max_age=COOKIE_MAX_AGE,
        )
        await response(scope, receive, send)
        return True


def middleware_stack(config: Config) -> list[Middleware]:
    """Order matters, and it is asserted by a test rather than left to habit.

    Starlette applies this list as an onion: the first entry is outermost and
    runs first.

    Host is outermost so a rebound request never reaches anything that could
    leak whether a token is even correct. Token sits before Origin so an
    unauthenticated caller cannot learn which origins this server accepts.
    """
    return [
        Middleware(HostAllowlistMiddleware, allowed_hosts=frozenset(config.allowed_hosts)),
        Middleware(TokenMiddleware, token=config.token),
        Middleware(OriginCheckMiddleware, allowed_origins=config.allowed_origins),
    ]
