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

from starlette.middleware import Middleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from hitchrail.config import Config

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def deny(status: int, code: str, message: str) -> JSONResponse:
    """Every refusal uses the envelope the API uses, so a client parses one shape."""
    return JSONResponse({"code": code, "message": message}, status_code=status)


def header_map(scope: Scope) -> dict[str, str]:
    """Lowercased header names, decoded once per request.

    Shared because all three middlewares need it and decoding the raw scope
    headers three times per request is work nobody asked for.
    """
    return {key.decode().lower(): value.decode() for key, value in scope["headers"]}


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


def middleware_stack(config: Config) -> list[Middleware]:
    """Order matters, and it is asserted by a test rather than left to habit.

    Starlette applies this list as an onion: the first entry is outermost and
    runs first. Host is outermost so a rebound request never reaches anything
    that could leak whether a token is even correct.
    """
    return [
        Middleware(HostAllowlistMiddleware, allowed_hosts=frozenset(config.allowed_hosts)),
    ]
