---
name: owasp-api-security
description: OWASP API Security Top 10 patterns adapted to Hitchrail - a token authenticated JSON API whose real attack classes are DNS rebinding, CSRF, argument injection into a spawn path, path traversal past the root boundary, and tmux target confusion. Payload libraries and pytest patterns for the refusals. Use when writing security tests, reviewing routes, or auditing input validation.
---

<!-- owasp-api-security-version: 1 -->

# OWASP API Security Testing (Hitchrail)

Security testing knowledge for Hitchrail's HTTP API, aligned with OWASP API Security Top
10:2023 and OWASP ASVS 5.0, and cut down to the classes this API actually has.

## When to use this skill

- Writing security tests for a route
- Reviewing a route for vulnerabilities
- Generating payloads for a test suite
- Auditing the token and host checks
- Assessing what a refusal must actually assert

## Read this first: the surface is not a typical API

Hitchrail spawns `claude --dangerously-skip-permissions`. Anyone who can drive its API can run
arbitrary code as the user who started it.

There is **no database, no ORM, no accounts, no roles, no personal data**. State is derived on
demand from tmux and the process table. So the OWASP categories that dominate a typical API test
suite are simply absent here, and writing tests for them produces coverage that proves nothing:

| Category | Status here |
|---|---|
| SQL / NoSQL injection | **Absent.** No database of any kind |
| BOLA / IDOR between users | **Absent.** One shared token, no per-user resources |
| Mass assignment of a role or tier | **Absent.** No user model |
| JWT and OAuth handling | **Absent.** One shared token, compared in constant time |
| XSS | **Marginal.** The single page renders folder names; still test output encoding |
| SSRF | **Absent.** No URL is ever fetched server side |

What replaces them is below. Do not pad a suite with the absent categories to make it look
thorough; state that they are N/A and why.

## The routes

| Method | Path |
|---|---|
| GET | `/` |
| GET | `/api/projects` |
| POST | `/api/projects` |
| POST | `/api/sessions/{name}` |
| DELETE | `/api/sessions/{name}` |
| POST | `/api/sessions/{name}/kill` |
| GET | `/api/sessions/{name}/logs` |
| GET | `/api/events` |

Error bodies: `{"code": str, "message": str}`. The codes the interface branches on are
`ram_soft`, `ram_hard`, `self_protected`, `start_died`, `url_pending`, `locked`.

---

## API1 revisited: DNS rebinding (the one that produced the precedent)

**What:** an attacker's page rebinds a hostname to Hitchrail's address. The browser then treats
the response as same origin and the page reads and drives the API. This is not theoretical:
CVE-2026-32632 (GHSA-hhcg-r27j-fhv9) hit Glances, a localhost and LAN monitoring web UI, for
exactly the missing host allowlist. Fixed in 4.5.2 by adding one.

**Control:** `TrustedHostMiddleware` on every route, always on.

```python
import pytest

BAD_HOSTS = [
    "evil.example",
    "localhost.evil.example",     # allowed name as a prefix
    "evil.example.localhost",     # allowed name as a suffix
    "127.0.0.1.evil.example",
    "localhost:8787.evil.example",
    "",                            # absent Host
]

@pytest.mark.parametrize("host", BAD_HOSTS, ids=lambda h: h or "empty")
@pytest.mark.parametrize("path", ["/", "/api/projects", "/api/events"])
async def test_forged_host_is_rejected(client, host, path):
    r = await client.get(path, headers={"Host": host})
    assert r.status_code == 400
```

**Checklist:**

- [ ] every route covered, `/api/events` explicitly. The event stream is the one people forget
      and the one an attacker most wants
- [ ] the allowlist is never `*`
- [ ] prefix and suffix confusions rejected
- [ ] the host check runs **before** the token check, so a rebound request cannot learn whether a
      token is correct. Assert the ordering, not just both checks

---

## API2: Authentication

One shared token. Mandatory for any non loopback bind, and the server **refuses to start**
without one rather than warning.

```python
async def test_missing_token_rejected(client_with_token):
    r = await client_with_token.get("/api/projects")
    assert r.status_code == 401

async def test_wrong_token_rejected(client_with_token):
    r = await client_with_token.get("/api/projects", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401

def test_constant_time_comparison(monkeypatch):
    calls = []
    real = secrets.compare_digest
    monkeypatch.setattr(secrets, "compare_digest", lambda a, b: calls.append(1) or real(a, b))
    ...
    assert calls, "token comparison must go through secrets.compare_digest, never =="

def test_non_loopback_bind_without_token_refuses_to_start():
    with pytest.raises(SystemExit):
        cli.main(["--root", str(tmp_path), "--host", "0.0.0.0"])
    # and assert no socket was ever bound
```

**Checklist:**

- [ ] `secrets.compare_digest`, never `==`. Grep for `== token`, `!= token`, `token in`
- [ ] the token never appears in a response body, an error message, or a log record
- [ ] wrong token and missing token are indistinguishable to the caller
- [ ] the startup refusal is asserted, and asserts nothing was bound

---

## API3 revisited: CSRF on a same origin JSON API

Browsers attach `Origin` to cross site requests, and a rebound attacker cannot forge it. That
makes the Origin check the CSRF control here.

```python
MUTATING = [("POST", "/api/projects"), ("POST", "/api/sessions/alpha"), ("DELETE", "/api/sessions/alpha")]

@pytest.mark.parametrize("method,path", MUTATING)
@pytest.mark.parametrize("origin", ["https://evil.example", None])
async def test_mutating_requires_same_origin(client, method, path, origin, spawn_spy):
    headers = {} if origin is None else {"Origin": origin}
    r = await client.request(method, path, headers=headers)
    assert r.status_code == 403
    assert spawn_spy.calls == []          # the side effect must not have happened
```

**The GET exemption is deliberate.** `EventSource` cannot set headers, so `/api/events` cannot
carry an `Origin` requirement. Write a test that *asserts the exemption*, with a comment saying
why, so a future tidy up does not "fix" it and silently break the stream.

---

## API4: Argument injection into the spawn path

This is what "injection" means in a project with no database. A folder name reaches an argv
position. Without a shell, a name beginning with `-` can still become a **flag**.

```python
ARGV_PAYLOADS = [
    "--dangerously-skip-permissions",
    "-rf",
    "--version",
    "-",
    "--",
]

@pytest.mark.parametrize("name", ARGV_PAYLOADS)
async def test_flag_shaped_names_rejected(client, name, spawn_spy):
    r = await client.post("/api/projects", json={"name": name})
    assert r.status_code == 400
    assert spawn_spy.calls == []
```

**Checklist:**

- [ ] the name allowlist rejects a leading `-`
- [ ] the spawn seam records argv and the test asserts a **list** was passed, never a string
- [ ] a repository wide guard test: no `shell=True`, no `os.system`, no
      `asyncio.create_subprocess_shell` anywhere in `src/`. The async form is the trap, since it
      is a shell without the words `shell=True` appearing

### Shell metacharacter payloads

These must never reach a shell, and with an argument list they cannot. Test them anyway, because
the test is what stops someone reintroducing a shell later.

```python
SHELL_PAYLOADS = [
    "; ls -la",
    "| cat /etc/passwd",
    "$(whoami)",
    "`id`",
    "& ping -c 1 attacker.example",
    "\n/bin/sh",
    "a\x00b",
]
```

---

## API5: Path traversal past the root boundary

The root is a hard boundary. Names are validated against an **allowlist pattern, never a
denylist**, and the resolved path is confirmed a direct child of the configured root.

```python
PATH_PAYLOADS = [
    "..", "../..", "../etc", "..%2fetc", "%2e%2e%2f", "....//....//etc",
    "/etc/passwd", "C:\\Windows", "a/b", "a\\b", ".hidden", "", " ", "a" * 4096,
    "\u202e",                       # right to left override
    "sky.tale",                     # tmux window separator
    "sky:tale",                     # tmux pane separator
]
```

```python
@pytest.mark.parametrize("name", PATH_PAYLOADS)
async def test_root_boundary(client, name, spawn_spy, tmp_root):
    r = await client.post(f"/api/sessions/{quote(name)}")
    assert r.status_code in (400, 404)
    assert spawn_spy.calls == []
    assert list(tmp_root.iterdir()) == []          # and nothing was created
```

**The symlink case needs its own named test.** A symlink inside the root pointing outside it
passes a string prefix comparison and is caught only by resolving both sides:

```python
def test_symlink_escaping_the_root_is_rejected(tmp_root, spawn_spy):
    (tmp_root / "escape").symlink_to("/etc")
    ...
    assert spawn_spy.calls == []
```

**Checklist:**

- [ ] allowlist pattern, not a denylist, and the test names the pattern
- [ ] `Path.resolve()` on both sides, parent compared to the resolved root
- [ ] the check runs before the spawn, and the test proves nothing was spawned
- [ ] the same check guards folder creation, not only session start

---

## API6: tmux target confusion

Not an OWASP category, and the most likely way this project attaches an operation to the wrong
project's session. Each gets a named regression test that fails if the workaround is removed.

- `has-session -t name` **prefix matches**: `hr-alpha` resolves `hr-alpha-two`. `=` forces exact,
  and only for a session target
- `list-panes` ignores a leading `=` and needs a trailing `:` to be read as a session. Getting
  this wrong makes a stopped project read as running on a sibling's process
- `.` and `:` are window and pane separators, so a session named `sky.tale` can be created and
  never addressed. Sanitize on the way in; keep the display name separate from the tmux name
- never a bare `kill-server`; never kill a session without the configured prefix
- concurrent starts serialize behind a lock. A web UI makes double submission far easier than a
  CLI does, so test two simultaneous starts produce one session

---

## API7: Unrestricted resource consumption

```python
async def test_oversized_body_rejected(client):
    r = await client.post("/api/projects", json={"name": "a" * 1_000_000})
    assert r.status_code in (400, 413)
```

- the log tail is bounded; a request cannot return an unbounded amount of pane output
- the memory guard refuses at the hard floor (`ram_hard`) and gates at the soft floor
  (`ram_soft`). **`ram_soft` is a confirmation gate:** assert that a soft refusal with no explicit
  acknowledgement spawns nothing. A server that proceeds on its own after a soft refusal is the
  bug this catches
- `self_protected`: the folder Hitchrail is itself running in cannot be stopped

---

## API8: Security misconfiguration and information leakage

```python
async def test_error_body_shape(client):
    r = await client.post("/api/sessions/does-not-exist")
    assert r.status_code >= 400
    body = r.json()
    assert set(body) == {"code", "message"}
    assert "Traceback" not in body["message"]
    assert "/home/" not in body["message"]
    assert ".py" not in body["message"]
```

- no traceback, no absolute filesystem path, no Python type name in a message
- an unhandled exception produces a generic body; the detail goes to the log
- unsupported methods return 405, not 500
- **SSE is not wrapped in `GZipMiddleware`.** `sse-starlette` documents the incompatibility, so
  write a test asserting the event route is excluded. It stops someone adding gzip globally later

---

## API9 revisited: honest refusal on indeterminate state

The control most easily broken by a refactor, and the one with the worst consequence.

A tool that reports `stopped` for a session it could not inspect invites the user to start a
second agent in the same folder. So:

```python
async def test_tmux_failure_reports_indeterminate_not_stopped(client, tmux_stub):
    tmux_stub.raise_on("list-sessions", OSError("boom"))
    r = await client.get("/api/projects")
    body = r.json()
    assert body["projects"][0]["state"] != "stopped"
```

- when the tmux seam raises, the route says it cannot determine the state
- when the process table seam raises, the same
- a `detached` session (a live Claude process no pane owns) is reported as `detached` with its
  pid, and never silently reconciled
- `url_pending` when `bridgeSessionId` is unavailable, rather than a fabricated link

---

## API10: Unsafe consumption of an undocumented internal

`claude_ipc.py` reads `~/.claude/sessions/<pid>.json` for `bridgeSessionId`. That file is an
undocumented internal, it is not written for every session, and the terminal scraping fallback can
match a `claude.ai/code` URL that merely appeared as text rather than a live bridge.

Test it as untrusted input, because that is what it is:

- missing file -> `url_pending`, never a fabricated URL
- malformed JSON -> `url_pending`, no exception escaping
- `bridgeSessionId` absent or not a string -> `url_pending`
- a value containing a path separator or a scheme -> rejected, not interpolated into a URL
- the file owned by another user, or a symlink -> refused

When this breaks on a Claude Code update, exactly one module changes and the interface degrades to
`pending` rather than reporting something false. A test that asserts the degradation is what
guarantees that.

---

## Test template

```python
"""Security tests for <route>.

Integration tier: the real Starlette app through httpx.ASGITransport, faked engine,
no socket opened. Build the app through the same factory the CLI uses, so the middleware
stack under test is the one that ships.
"""
import httpx
import pytest

from hitchrail.server import create_app


@pytest.fixture
async def client(fake_engine, config):
    app = create_app(engine=fake_engine, config=config)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as c:
        yield c


class TestHostAllowlist:
    @pytest.mark.parametrize("host", BAD_HOSTS)
    async def test_rejects_forged_host(self, client, host):
        r = await client.get("/api/projects", headers={"Host": host})
        assert r.status_code == 400


class TestOrigin:
    async def test_rejects_foreign_origin_on_mutation(self, client, spawn_spy):
        r = await client.post("/api/sessions/alpha", headers={"Origin": "https://evil.example"})
        assert r.status_code == 403
        assert spawn_spy.calls == []

    async def test_get_is_deliberately_exempt(self, client):
        # EventSource cannot set headers, so /api/events cannot require an Origin.
        # This test exists so a future tidy up does not "fix" the exemption and break SSE.
        r = await client.get("/api/events")
        assert r.status_code == 200


class TestErrorBody:
    async def test_no_leakage(self, client):
        r = await client.post("/api/sessions/nope")
        assert set(r.json()) == {"code", "message"}
```

## The rule that governs all of it

**After every rejection, assert the side effect did not happen.** A guard that returns 403 after
spawning the process passes a status code assertion and is exactly the bug worth finding. Status
code plus `spawn_spy.calls == []` plus "nothing was created in the root" is the shape of a real
refusal test here.
