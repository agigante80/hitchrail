# Hitchrail Phase 2: The Security Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the controls that stand between a web page and a shell, and prove them on a real socket, before there is anything to serve.

**Architecture:** Three plain ASGI middlewares composed in a fixed order by one function, so the ordering is a single reviewable decision rather than an emergent property of wherever somebody added the next `Middleware(...)`. Each middleware depends only on `Config` from Phase 1, which is why this phase can run before the engine exists.

**Tech Stack:** Python 3.11+, Starlette 1.6 (`TrustedHostMiddleware` and raw ASGI), uvicorn for the live socket test, pytest, httpx.

**Spec:** `docs/superpowers/specs/2026-08-25-hitchrail-design.md` section 5

**Roadmap:** `docs/roadmap.md` (this plan is Phase 2 of 7)

## Global Constraints

Copied verbatim from the spec. Every task inherits these.

- **Python `>=3.11`.** CI runs 3.11, 3.12 and 3.13. All blocking.
- **Exactly three runtime dependencies:** `starlette>=1.6,<2`, `uvicorn>=0.52,<1`, `sse-starlette>=3.4,<4`. A fourth requires a written justification in the pull request.
- **Starlette 1.x API only.** `on_startup`, `on_shutdown`, `add_event_handler()`, `@app.route()` and `@app.websocket_route()` were removed at 1.0. Use the `lifespan` async context manager and an explicit `routes=` list. Examples written against 0.4x are wrong.
- **No shell, ever.** Every subprocess call takes an argument list. `shell=True` is forbidden with no exceptions.
- **The engine layer must not import** `hitchrail.server`, `hitchrail.cli`, `starlette`, `uvicorn` or `sse_starlette`. `hitchrail.security` is part of the web layer and is deliberately outside that contract.
- **The root stays lean.** Every tool is configured from `pyproject.toml`.
- **No em dashes or en dashes** anywhere, including commit messages. A hook enforces it.
- Tests are hermetic. No test touches a real tmux server, a real Claude process, the network, or the filesystem outside a temporary root. **One documented exception is introduced in Task 6:** a loopback socket on an ephemeral port. The design asks specifically for a forged `Host` to be refused on a live socket, and an `ASGITransport` test cannot make that claim.

## Why this phase runs before the engine

It depends only on `Config`, so nothing forces it late, and two things push it early.

The first is the CVE precedent. CVE-2026-32632 (GHSA-hhcg-r27j-fhv9) hit Glances, a localhost and LAN monitoring web UI, for a missing host allowlist: no host check, therefore DNS rebinding, therefore an attacker's page reading the API through the victim's own browser. Hitchrail has the same shape and a worse blast radius, because Glances reports state while Hitchrail starts processes. Building the answer first means every route added later is born behind it.

The second is that the token has to reach the event stream, and it is not obvious that it can. `EventSource` cannot set request headers, so a token carried only in `Authorization` authenticates every route except the one the interface depends on for live updates. The first draft of this plan put security at task 12 of 15 and did not surface that until review. Task 6 solves it with a cookie and a one time query grant, and this is the phase where being wrong about it is cheap.

## Phase 2 file structure

| File | Responsibility |
|---|---|
| `src/hitchrail/security.py` | all three middlewares and the one function that orders them |
| `tests/test_security_host.py` | the host allowlist and the DNS rebinding refusal |
| `tests/test_security_origin.py` | the CSRF control, including the deliberate `GET` exemption |
| `tests/test_security_token.py` | the three token carriers and the grant redirect |
| `tests/test_live_socket.py` | the refusals on a real loopback socket |
| `pyproject.toml` | gains one registered pytest marker |

One module rather than three. They are 120 lines together, they change together
whenever the threat model changes, and splitting them would put the ordering
decision in a fourth file that reviewers would have to go find.

---

### Task 4: The host allowlist

**Files:**
- Modify: `src/hitchrail/security.py`
- Test: `tests/test_security_host.py`

**Interfaces:**
- Consumes: `hitchrail.config.Config` (Phase 1 Task 2), specifically `Config.allowed_hosts`.
- Produces: `middleware_stack(config: Config) -> list[Middleware]`; `deny(status: int, code: str, message: str) -> JSONResponse`.

- [ ] **Step 1: Write the failing tests**

`tests/test_security_host.py`:

```python
from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from hitchrail.config import Config
from hitchrail.security import middleware_stack


def build(config: Config) -> Starlette:
    async def ok(request):  # type: ignore[no-untyped-def]
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


async def test_a_known_host_is_served(tmp_path: Path) -> None:
    app = build(Config(root=tmp_path))
    assert (await call(app, headers={"host": "localhost"})).status_code == 200


async def test_a_host_with_a_port_still_matches(tmp_path: Path) -> None:
    app = build(Config(root=tmp_path))
    assert (await call(app, headers={"host": "localhost:8787"})).status_code == 200


@pytest.mark.parametrize(
    "host",
    [
        "evil.example",
        "localhost.evil.example",
        "evil.example.localhost",
        "127.0.0.1.evil.example",
        "",
    ],
    ids=["foreign", "prefix-confusion", "suffix-confusion", "ip-prefix", "empty"],
)
async def test_a_forged_host_is_rejected(tmp_path: Path, host: str) -> None:
    # DNS rebinding. Without this, any page the user visits in any browser on
    # the network can drive this API from their own browser, and the browser
    # treats the response as same origin. This is the Glances CVE, verbatim.
    app = build(Config(root=tmp_path))
    assert (await call(app, headers={"host": host})).status_code == 400


async def test_the_event_stream_is_behind_the_allowlist_too(tmp_path: Path) -> None:
    # The route people forget, and the one an attacker most wants: a long
    # lived stream of everything happening on the machine.
    app = build(Config(root=tmp_path))
    r = await call(app, path="/api/events", headers={"host": "evil.example"})
    assert r.status_code == 400


async def test_the_allowlist_never_contains_a_wildcard(tmp_path: Path) -> None:
    cfg = Config(root=tmp_path, host="0.0.0.0", token="t", resolver=lambda: ("10.0.0.2",))
    assert "*" not in cfg.allowed_hosts
    assert "0.0.0.0" not in cfg.allowed_hosts  # noqa: S104
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_security_host.py -v`
Expected: FAIL with `ImportError: cannot import name 'middleware_stack' from 'hitchrail.security'`.

- [ ] **Step 3: Implement**

Replace the stub `src/hitchrail/security.py` with:

```python
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
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import JSONResponse

from hitchrail.config import Config

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def deny(status: int, code: str, message: str) -> JSONResponse:
    """Every refusal uses the same envelope the API uses, so a client parses one shape."""
    return JSONResponse({"code": code, "message": message}, status_code=status)


def middleware_stack(config: Config) -> list[Middleware]:
    """Order matters, and it is asserted by a test rather than left to habit.

    Starlette applies this list as an onion: the first entry is outermost and
    runs first. Host is outermost so a rebound request never reaches anything
    that could leak whether a token is even correct.
    """
    return [
        Middleware(TrustedHostMiddleware, allowed_hosts=list(config.allowed_hosts)),
    ]
```

- [ ] **Step 4: Run to verify passing**

Run: `uv run pytest tests/test_security_host.py -v`
Expected: PASS, 9 tests (4 plain plus one parametrised case with 5 values).

- [ ] **Step 5: Gates and commit**

```bash
uv run ruff check && uv run ruff format --check && uv run mypy && uv run lint-imports
git add src/hitchrail/security.py tests/test_security_host.py
git commit -m "feat(security): host allowlist on every route, event stream included"
```

---

### Task 5: The origin check

**Files:**
- Modify: `src/hitchrail/security.py`
- Test: `tests/test_security_origin.py`

**Interfaces:**
- Consumes: `Config.allowed_origins` (Phase 1 Task 2), `SAFE_METHODS`, `deny` (Task 4).
- Produces: `OriginCheckMiddleware(app: ASGIApp, allowed_origins: frozenset[str])`; `middleware_stack` gains a second entry.

The control is exact origin matching, not hostname matching. Comparing only the
hostname makes `http://localhost:3000` same origin with this API, which means
any other development server on the machine can drive a shell. The port has to
be in the comparison, and the default port forms have to be accepted because
behind the TLS terminating proxy the README recommends, the browser sends
`https://name` with no port at all.

- [ ] **Step 1: Write the failing tests**

`tests/test_security_origin.py`:

```python
from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from hitchrail.config import Config
from hitchrail.security import middleware_stack


def build(config: Config) -> Starlette:
    async def ok(request):  # type: ignore[no-untyped-def]
        return JSONResponse({"ok": True})

    return Starlette(
        routes=[
            Route("/x", ok, methods=["GET", "POST", "DELETE"]),
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


async def test_a_get_needs_no_origin(tmp_path: Path) -> None:
    app = build(Config(root=tmp_path))
    assert (await call(app, headers={"host": "localhost"})).status_code == 200


async def test_the_event_stream_needs_no_origin(tmp_path: Path) -> None:
    # EventSource cannot set headers, and GET is a safe method, so the origin
    # check must not apply to it. This test exists so that a later tidy up
    # cannot "fix" the exemption and silently break live updates.
    app = build(Config(root=tmp_path))
    r = await call(app, path="/api/events", headers={"host": "localhost"})
    assert r.status_code == 200


@pytest.mark.parametrize("method", ["POST", "DELETE"])
async def test_a_mutating_request_without_an_origin_is_rejected(
    tmp_path: Path, method: str
) -> None:
    app = build(Config(root=tmp_path))
    r = await call(app, method, headers={"host": "localhost"})
    assert r.status_code == 403
    assert r.json()["code"] == "origin_missing"


@pytest.mark.parametrize(
    "origin",
    [
        "https://evil.example",
        "http://localhost:3000",
        "http://localhost.evil.example:8787",
        "null",
        "http://127.0.0.1:9999",
    ],
    ids=["foreign", "other-local-app", "prefix-confusion", "null", "wrong-port"],
)
async def test_a_mutating_request_with_a_foreign_origin_is_rejected(
    tmp_path: Path, origin: str
) -> None:
    app = build(Config(root=tmp_path))
    r = await call(app, "POST", headers={"host": "localhost", "origin": origin})
    assert r.status_code == 403
    assert r.json()["code"] == "origin_rejected"


async def test_a_mutating_request_with_the_matching_origin_is_served(
    tmp_path: Path,
) -> None:
    app = build(Config(root=tmp_path, port=8787))
    r = await call(
        app, "POST", headers={"host": "localhost", "origin": "http://localhost:8787"}
    )
    assert r.status_code == 200


async def test_the_proxy_origin_form_is_served(tmp_path: Path) -> None:
    # https://name with no port, which is what a TLS terminating reverse proxy
    # in front of this server produces. The README recommends that deployment.
    app = build(Config(root=tmp_path, port=8787))
    r = await call(
        app, "POST", headers={"host": "localhost", "origin": "https://localhost"}
    )
    assert r.status_code == 200
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_security_origin.py -v`
Expected: FAIL. The mutating requests return 200 because nothing checks the origin yet.

- [ ] **Step 3: Implement**

Add to `src/hitchrail/security.py`, after `deny`:

```python
class OriginCheckMiddleware:
    """CSRF control for a same origin JSON API.

    Browsers attach Origin to cross site requests and a rebound attacker
    cannot forge it, so requiring it to be an origin we already serve is
    sufficient here and needs no token round trip.

    Exact origins, not hostnames. Matching on hostname alone would make
    http://localhost:3000 same origin with an API equivalent to a shell, so
    every other development server on the machine could drive it.
    """

    def __init__(self, app: ASGIApp, allowed_origins: frozenset[str]) -> None:
        self.app = app
        self.allowed = {o.lower() for o in allowed_origins}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] in SAFE_METHODS:
            await self.app(scope, receive, send)
            return

        headers = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
        origin = headers.get("origin")
        if not origin:
            await deny(403, "origin_missing", "this request needs an Origin header")(
                scope, receive, send
            )
            return
        if origin.lower().rstrip("/") not in self.allowed:
            await deny(403, "origin_rejected", f"origin not allowed: {origin}")(
                scope, receive, send
            )
            return
        await self.app(scope, receive, send)
```

Add the import at the top:

```python
from starlette.types import ASGIApp, Receive, Scope, Send
```

And extend `middleware_stack`:

```python
def middleware_stack(config: Config) -> list[Middleware]:
    """Order matters, and it is asserted by a test rather than left to habit.

    Starlette applies this list as an onion: the first entry is outermost and
    runs first. Host is outermost so a rebound request never reaches anything
    that could leak whether a token is even correct.
    """
    return [
        Middleware(TrustedHostMiddleware, allowed_hosts=list(config.allowed_hosts)),
        Middleware(OriginCheckMiddleware, allowed_origins=config.allowed_origins),
    ]
```

- [ ] **Step 4: Run to verify passing**

Run: `uv run pytest tests/test_security_origin.py -v`
Expected: PASS, 11 tests (4 plain, one parametrised with 2 values, one parametrised with 5 values).

- [ ] **Step 5: Gates and commit**

```bash
uv run ruff check && uv run ruff format --check && uv run mypy && uv run lint-imports
git add src/hitchrail/security.py tests/test_security_origin.py
git commit -m "feat(security): exact origin matching, so another local app is not same origin"
```

---

### Task 6: The token, and the carrier the event stream can actually use

**Files:**
- Modify: `src/hitchrail/security.py`
- Modify: `pyproject.toml` (register one pytest marker)
- Test: `tests/test_security_token.py`
- Test: `tests/test_live_socket.py`

**Interfaces:**
- Consumes: `Config.token`, `Config.allowed_hosts` (Phase 1 Task 2); `deny`, `SAFE_METHODS`, `OriginCheckMiddleware` (Tasks 4 and 5).
- Produces: `TokenMiddleware(app: ASGIApp, token: str | None)`; constant `TOKEN_COOKIE = "hitchrail_token"`; `middleware_stack` gains its third entry, ordered between host and origin.

`EventSource` cannot set request headers. A token carried only in
`Authorization` therefore authenticates every route except the one the
interface needs for live updates, which is the whole point of having a live
interface. Three carriers, in this order:

1. `Authorization: Bearer <token>`, for `curl` and scripts. Scheme comparison
   is case insensitive, because RFC 7235 says auth schemes are.
2. The `hitchrail_token` cookie, which `EventSource` sends automatically
   because it is a same origin request.
3. A one time `?token=<token>` on any safe method, which sets the cookie and
   redirects to the same path with the token stripped from the query. This is
   how the link you open on your phone works, and the redirect keeps the token
   out of the address bar and the browser history.

A cookie reintroduces CSRF as a live concern, which is exactly why the cookie
is `SameSite=Strict` **and** the origin check from Task 5 stays on every
mutating request. Either one alone would do for the cases we can think of.

The cookie is not `Secure`. Over plain HTTP on a LAN, which is a documented and
supported deployment, a `Secure` cookie is never sent and the tool silently
stops working. The cleartext exposure is already stated as a limitation in the
README, and the remedy stated there is a TLS terminating proxy.

- [ ] **Step 1: Confirm the pytest marker is registered in `pyproject.toml`**

`--strict-markers` is on, so an unregistered marker is an error rather than a
warning. Phase 1 Task 1 already ships this; confirm it is present rather than
adding a second copy:

```toml
markers = [
  "live: binds a real loopback socket on an ephemeral port",
]
```

- [ ] **Step 2: Write the failing token tests**

`tests/test_security_token.py`:

```python
from __future__ import annotations

import secrets
from pathlib import Path

import httpx
import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from hitchrail.config import Config
from hitchrail.security import TOKEN_COOKIE, middleware_stack

TOKEN = "s3cret-token-value"


def build(config: Config) -> Starlette:
    async def ok(request):  # type: ignore[no-untyped-def]
        return JSONResponse({"ok": True})

    return Starlette(
        routes=[
            Route("/x", ok, methods=["GET", "POST"]),
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
        transport=transport, base_url="http://localhost", follow_redirects=follow_redirects
    ) as c:
        return await c.request(method, path, **kwargs)  # type: ignore[arg-type]


async def test_no_token_configured_means_no_token_demanded(tmp_path: Path) -> None:
    app = build(Config(root=tmp_path))
    assert (await call(app, headers={"host": "localhost"})).status_code == 200


async def test_a_configured_token_is_demanded(tmp_path: Path) -> None:
    r = await call(guarded(tmp_path), headers={"host": "localhost"})
    assert r.status_code == 401
    assert r.json()["code"] == "unauthorized"


async def test_the_right_bearer_token_is_accepted(tmp_path: Path) -> None:
    r = await call(
        guarded(tmp_path),
        headers={"host": "localhost", "authorization": f"Bearer {TOKEN}"},
    )
    assert r.status_code == 200


async def test_the_bearer_scheme_is_case_insensitive(tmp_path: Path) -> None:
    # RFC 7235: auth schemes are case insensitive. A client sending "bearer"
    # is correct, and rejecting it is our bug, not theirs.
    r = await call(
        guarded(tmp_path),
        headers={"host": "localhost", "authorization": f"bearer {TOKEN}"},
    )
    assert r.status_code == 200


@pytest.mark.parametrize(
    "value",
    ["Bearer wrong", "Bearer ", "Basic abc", TOKEN, "", "Bearer  " + TOKEN],
    ids=["wrong", "empty", "wrong-scheme", "no-scheme", "blank", "double-space"],
)
async def test_a_bad_authorization_header_is_rejected(tmp_path: Path, value: str) -> None:
    r = await call(guarded(tmp_path), headers={"host": "localhost", "authorization": value})
    assert r.status_code == 401


async def test_the_cookie_carrier_is_accepted(tmp_path: Path) -> None:
    # This is the carrier EventSource can actually use.
    r = await call(
        guarded(tmp_path),
        headers={"host": "localhost", "cookie": f"{TOKEN_COOKIE}={TOKEN}"},
    )
    assert r.status_code == 200


async def test_a_wrong_cookie_is_rejected(tmp_path: Path) -> None:
    r = await call(
        guarded(tmp_path), headers={"host": "localhost", "cookie": f"{TOKEN_COOKIE}=nope"}
    )
    assert r.status_code == 401


async def test_the_query_grant_sets_the_cookie_and_redirects(tmp_path: Path) -> None:
    r = await call(
        guarded(tmp_path), path=f"/x?token={TOKEN}", headers={"host": "localhost"}
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/x"
    cookie = r.headers["set-cookie"]
    assert f"{TOKEN_COOKIE}={TOKEN}" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=strict" in cookie.replace("SameSite=Strict", "SameSite=strict")


async def test_the_grant_preserves_other_query_parameters(tmp_path: Path) -> None:
    r = await call(
        guarded(tmp_path),
        path=f"/x?filter=running&token={TOKEN}",
        headers={"host": "localhost"},
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/x?filter=running"


async def test_a_wrong_query_token_grants_nothing(tmp_path: Path) -> None:
    r = await call(guarded(tmp_path), path="/x?token=nope", headers={"host": "localhost"})
    assert r.status_code == 401
    assert "set-cookie" not in r.headers


async def test_the_grant_is_not_available_on_a_mutating_request(tmp_path: Path) -> None:
    # A grant on POST would let a link perform an action, which is exactly the
    # shape of a CSRF attack. The grant is for safe methods only.
    r = await call(
        guarded(tmp_path),
        "POST",
        path=f"/x?token={TOKEN}",
        headers={"host": "localhost", "origin": "http://localhost:8787"},
    )
    assert r.status_code == 401


async def test_the_event_stream_authenticates_the_way_eventsource_sends_it(
    tmp_path: Path,
) -> None:
    # The whole reason this task exists. EventSource sends cookies and no
    # Authorization header, and it is the interface's only live update path.
    r = await call(
        guarded(tmp_path),
        path="/api/events",
        headers={"host": "localhost", "cookie": f"{TOKEN_COOKIE}={TOKEN}"},
    )
    assert r.status_code == 200


async def test_the_token_never_appears_in_a_refusal(tmp_path: Path) -> None:
    r = await call(guarded(tmp_path), headers={"host": "localhost"})
    assert TOKEN not in r.text


def test_the_comparison_is_constant_time(monkeypatch: pytest.MonkeyPatch) -> None:
    # Asserting the call rather than trying to time it. A timing test on a
    # shared CI runner is a flaky test that teaches people to rerun the suite.
    seen: list[tuple[str, str]] = []
    real = secrets.compare_digest

    def spy(a: object, b: object) -> bool:
        seen.append((str(a), str(b)))
        return bool(real(a, b))  # type: ignore[arg-type]

    monkeypatch.setattr("hitchrail.security.secrets.compare_digest", spy)
    from hitchrail.security import _token_matches

    assert _token_matches(TOKEN, TOKEN)
    assert not _token_matches("wrong", TOKEN)
    assert len(seen) == 2


async def test_host_checking_happens_before_token_checking(tmp_path: Path) -> None:
    # A rebound request must not even reach the token comparison, or the
    # response tells an attacker whether their guess was the right shape.
    r = await call(guarded(tmp_path), headers={"host": "evil.example"})
    assert r.status_code == 400
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/test_security_token.py -v`
Expected: FAIL with `ImportError: cannot import name 'TOKEN_COOKIE' from 'hitchrail.security'`.

- [ ] **Step 4: Implement**

Add to `src/hitchrail/security.py`:

```python
TOKEN_COOKIE = "hitchrail_token"


def _token_matches(presented: str, expected: str) -> bool:
    """Constant time, always. `==` on a secret leaks its prefix through timing."""
    return secrets.compare_digest(presented, expected)


def _bearer(header: str) -> str:
    """Extract a bearer credential. RFC 7235 auth schemes are case insensitive."""
    scheme, _, credential = header.partition(" ")
    if scheme.lower() != "bearer":
        return ""
    return credential.strip()


class TokenMiddleware:
    """One shared token, over three carriers.

    EventSource cannot set request headers, so a token that lives only in
    Authorization authenticates every route except the live update stream.
    The cookie is the carrier EventSource can use; the query grant is how that
    cookie gets set from a link you open on a phone.

    The cookie is SameSite=Strict, and the origin check still runs on every
    mutating request. Either one alone would cover the cases we can think of,
    which is why there are two.

    Not Secure: over plain HTTP on a LAN, a documented deployment, a Secure
    cookie is never sent and the tool silently stops working. The cleartext
    exposure is stated as a limitation in the README, with a TLS terminating
    proxy as the remedy.
    """

    def __init__(self, app: ASGIApp, token: str | None) -> None:
        self.app = app
        self.token = token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or self.token is None:
            await self.app(scope, receive, send)
            return

        headers = {k.decode().lower(): v.decode() for k, v in scope["headers"]}

        presented = _bearer(headers.get("authorization", ""))
        if presented and _token_matches(presented, self.token):
            await self.app(scope, receive, send)
            return

        cookies = SimpleCookie()
        cookies.load(headers.get("cookie", ""))
        morsel = cookies.get(TOKEN_COOKIE)
        if morsel is not None and _token_matches(morsel.value, self.token):
            await self.app(scope, receive, send)
            return

        if scope["method"] in SAFE_METHODS:
            granted = await self._maybe_grant(scope, receive, send)
            if granted:
                return

        await deny(401, "unauthorized", "a valid token is required")(scope, receive, send)

    async def _maybe_grant(self, scope: Scope, receive: Receive, send: Send) -> bool:
        """Trade `?token=` for a cookie, then redirect the token out of the URL.

        Safe methods only. A grant on a mutating request would let a link
        perform an action, which is the shape of the attack the origin check
        exists to stop.

        The redirect target is rebuilt from this request's own path, never from
        anything the caller supplied, so this cannot become an open redirect.
        """
        assert self.token is not None
        params = parse_qsl(scope.get("query_string", b"").decode(), keep_blank_values=True)
        offered = next((v for k, v in params if k == "token"), None)
        if offered is None or not _token_matches(offered, self.token):
            return False

        remaining = urlencode([(k, v) for k, v in params if k != "token"])
        path = scope["path"]
        location = f"{path}?{remaining}" if remaining else path

        response = RedirectResponse(location, status_code=303)
        response.set_cookie(
            TOKEN_COOKIE,
            self.token,
            httponly=True,
            samesite="strict",
            path="/",
            max_age=60 * 60 * 24 * 30,
        )
        await response(scope, receive, send)
        return True
```

Add these imports at the top:

```python
import secrets
from http.cookies import SimpleCookie
from urllib.parse import parse_qsl, urlencode

from starlette.responses import RedirectResponse
```

And put the token middleware between host and origin in `middleware_stack`:

```python
def middleware_stack(config: Config) -> list[Middleware]:
    """Order matters, and it is asserted by a test rather than left to habit.

    Starlette applies this list as an onion: the first entry is outermost and
    runs first.

    Host is outermost so a rebound request never reaches anything that could
    leak whether a token is even correct. Token sits before Origin so an
    unauthenticated caller cannot learn which origins this server accepts.
    """
    return [
        Middleware(TrustedHostMiddleware, allowed_hosts=list(config.allowed_hosts)),
        Middleware(TokenMiddleware, token=config.token),
        Middleware(OriginCheckMiddleware, allowed_origins=config.allowed_origins),
    ]
```

- [ ] **Step 5: Run to verify passing**

Run: `uv run pytest tests/test_security_token.py -v`
Expected: PASS, 20 tests (14 plain plus one parametrised case with 6 values).

- [ ] **Step 6: Write the live socket test**

This is the step that makes Phase 2 done. An `ASGITransport` test proves the
middleware is configured. It does not prove the server people run refuses
anything, because a real request arrives through uvicorn's HTTP parser, not
through a dictionary a test constructed.

`tests/test_live_socket.py`:

```python
"""The refusals, on a real socket.

The hermetic rule in docs/tech-guidelines.md section 7.4 says no test touches
the network. This file is the documented exception, and it is narrow: it binds
127.0.0.1 on an ephemeral port, talks to itself, and shuts down. It exists
because the design asks specifically for a forged Host to be refused on a live
socket rather than in theory.
"""

from __future__ import annotations

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

pytestmark = pytest.mark.live


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    return int(port)


@pytest.fixture
def live(tmp_path: Path) -> Iterator[str]:
    async def ok(request):  # type: ignore[no-untyped-def]
        return JSONResponse({"ok": True})

    port = free_port()
    config = Config(root=tmp_path, host="127.0.0.1", port=port, token=TOKEN)
    app = Starlette(
        routes=[Route("/x", ok, methods=["GET", "POST"])],
        middleware=middleware_stack(config),
    )
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    base = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if server.started:
            break
        time.sleep(0.05)
    else:  # pragma: no cover - only on a machine too slow to start uvicorn
        pytest.fail("uvicorn did not start within 10 seconds")

    try:
        yield base
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def test_a_forged_host_is_refused_on_a_live_socket(live: str) -> None:
    r = httpx.get(f"{live}/x", headers={"Host": "evil.example"}, timeout=5)
    assert r.status_code == 400


def test_the_right_token_is_accepted_on_a_live_socket(live: str) -> None:
    r = httpx.get(
        f"{live}/x",
        headers={"Host": "127.0.0.1", "Authorization": f"Bearer {TOKEN}"},
        timeout=5,
    )
    assert r.status_code == 200


def test_a_missing_token_is_refused_on_a_live_socket(live: str) -> None:
    r = httpx.get(f"{live}/x", headers={"Host": "127.0.0.1"}, timeout=5)
    assert r.status_code == 401


def test_the_query_grant_round_trips_on_a_live_socket(live: str) -> None:
    with httpx.Client(timeout=5, follow_redirects=True) as client:
        r = client.get(f"{live}/x", params={"token": TOKEN}, headers={"Host": "127.0.0.1"})
        assert r.status_code == 200
        assert client.cookies.get(TOKEN_COOKIE) == TOKEN
        # The cookie alone carries the next request, which is what EventSource
        # will rely on.
        again = client.get(f"{live}/x", headers={"Host": "127.0.0.1"})
        assert again.status_code == 200


def test_a_mutating_request_with_a_foreign_origin_is_refused_on_a_live_socket(
    live: str,
) -> None:
    r = httpx.post(
        f"{live}/x",
        headers={
            "Host": "127.0.0.1",
            "Authorization": f"Bearer {TOKEN}",
            "Origin": "https://evil.example",
        },
        timeout=5,
    )
    assert r.status_code == 403
```

- [ ] **Step 7: Run the live tests**

Run: `uv run pytest tests/test_live_socket.py -v`
Expected: PASS, 5 tests. They take a second or two, which is the cost of the
claim being true.

- [ ] **Step 8: Gates and commit**

```bash
uv run ruff check && uv run ruff format --check && uv run mypy && uv run lint-imports && uv run pytest
git add pyproject.toml src/hitchrail/security.py tests/test_security_token.py tests/test_live_socket.py
git commit -m "feat(security): token over header, cookie and a one time grant the stream can use"
```

---

## Phase 2 exit criteria

- [ ] All five gates green on 3.11, 3.12 and 3.13.
- [ ] A forged `Host` is refused on every route including `/api/events`, and on a real loopback socket, not only through `ASGITransport`.
- [ ] A mutating request with a missing, foreign, or wrong port `Origin` is refused, and `http://localhost:3000` is among the refused.
- [ ] A `GET` needs no `Origin`, and a test asserts that exemption is deliberate.
- [ ] A request shaped the way `EventSource` sends one, cookie only and no `Authorization` header, authenticates successfully.
- [ ] `?token=` grants a cookie and redirects the token out of the URL, on safe methods only.
- [ ] The host check is proven to run before the token check.
- [ ] The token appears in no refusal body.

When these hold, start Phase 3 from `docs/roadmap.md`.
