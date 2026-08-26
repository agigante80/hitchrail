# Hitchrail Phase 5: The HTTP API and the CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put a thin HTTP layer on the engine and a command line entry point on top of that, so `uvx hitchrail --root ~/dev` serves an API a person can drive with `curl`.

**Architecture:** Routing and translation only. Every handler turns an engine exception into a status code and a stable error `code`, and holds no logic worth testing separately. Every engine call is dispatched to a worker thread, because the engine does blocking subprocess work and the event loop must stay free for the SSE stream.

**Tech Stack:** Python 3.11+, Starlette 1.6, sse-starlette 3.4, uvicorn 0.52, httpx for tests.

**Spec:** `docs/superpowers/specs/2026-08-25-hitchrail-design.md` section 6

**Roadmap:** `docs/roadmap.md` (this plan is Phase 5 of 7)

## Global Constraints

Copied verbatim from the spec. Every task inherits these.

- **Python `>=3.11`.** CI runs 3.11, 3.12 and 3.13. All blocking.
- **Exactly three runtime dependencies:** `starlette>=1.6,<2`, `uvicorn>=0.52,<1`, `sse-starlette>=3.4,<4`. A fourth requires a written justification in the pull request.
- **Starlette 1.x API only.** `on_startup`, `on_shutdown`, `add_event_handler()`, `@app.route()` and `@app.websocket_route()` were removed at 1.0. Use the `lifespan` async context manager and an explicit `routes=` list. Examples written against 0.4x are wrong.
- **No shell, ever.** Every subprocess call takes an argument list. `shell=True` is forbidden with no exceptions.
- **The engine layer must not import** `hitchrail.server`, `hitchrail.cli`, `starlette`, `uvicorn` or `sse_starlette`.
- **The root stays lean.** Every tool is configured from `pyproject.toml`.
- **No em dashes or en dashes** anywhere, including commit messages. A hook enforces it.
- Defaults: session prefix `hr-`, stop timeout 30 seconds, hard memory floor 1536 MB, soft floor 3072 MB, per session estimate 1536 MB, port 8787.
- Tests are hermetic, with the loopback socket exception introduced in Phase 2.

## Phase 5 file structure

| File | Responsibility |
|---|---|
| `src/hitchrail/server.py` | routes, the error envelope, the SSE stream, the lifespan sweeper |
| `src/hitchrail/cli.py` | argument parsing, config assembly, the token banner, uvicorn |

## The error envelope

Every failure is `{"code": <stable>, "message": <human>}`, plus any numbers the
interface needs. The codes, and the ones from the design's section 6 that the
first draft of this plan quietly dropped:

| Code | Status | Meaning |
|---|---|---|
| `invalid_name` | 400 | the name is not one we will turn into a path |
| `root_unavailable` | 503 | the configured root cannot be read right now |
| `machine_unreadable` | 503 | tmux or the process table could not be read, so no state can be determined |
| `unknown_project` | 404 | no such folder under the root |
| `already_running` | 409 | a session is already live there |
| `already_exists` | 409 | a folder of that name is already there |
| `not_running` | 409 | there is no session to act on |
| `locked` | 409 | a start is already in flight for this folder |
| `ram_soft` | 409 | starting would leave the machine short; resubmit acknowledged |
| `url_pending` | 409 | the session has no link yet; ask again shortly |
| `self_protected` | 423 | this is the folder Hitchrail is running in |
| `start_died` | 502 | the session did not come up within the grace window |
| `ram_hard` | 507 | not enough memory, and not overridable |

`ram_soft` is a confirmation gate. The server never proceeds on a soft refusal
by itself; the client resubmits with `?acknowledged=1`.

`root_unavailable` is not in the design's section 6 list, and it is not a
refusal of the caller. `Config` checks the root once at construction; a USB
drive, an autofs mount or a sync client can take it away afterwards, and
`discovery.RootUnavailable` reports that honestly rather than letting a
`FileNotFoundError` escape as a 500 or answering with an empty project list,
which would report every session as stopped. That is control 7.

`unknown_project` comes from `discovery.NoSuchProject`, which subclasses
`InvalidName`. Catch the subclass first, or a missing project answers 400.

## Why every handler dispatches to a thread

The engine spawns `ps` and `tmux`. Those calls block. An `async def` handler
that calls them blocks the event loop, and the loop is what the SSE stream runs
on, so one slow `ps` stalls live updates for every connected browser.

Starlette runs a **sync** `def` handler in a worker thread automatically, which
would be the simpler answer, but a sync handler cannot `await request.json()`
and the create route needs a body. So the handlers stay `async def` and every
engine call goes through one `in_thread` helper. It is visible in every handler
on purpose: the threading is part of the contract, and the per folder start lock
in Phase 4 exists precisely because two taps land on two threads.

---

## Phase 5 tickets, in dependency order

| Ticket | Task | Note |
|---|---|---|
| #37 | mark the integration tier | first, before the tier triples and marking becomes a large mechanical diff |
| #43 | 15, the REST surface and the error envelope | |
| #44 | 16, the event stream | needs #43's app and #39's bus |
| #45 | 17, the command line entry point | needs #43's `create_app` |
| #28 | the startup preflight | lands inside #45; separate because its value is entirely in the wording of its refusals |
| #20 | the grant token in the access log | touches the `log_level` decision #45 makes |
| #48 | `self_project` is never validated | **before #43**: the `self_protected` refusal on three routes protects nothing while the name can be wrong |
| #47 | `get()` answers for names that are not projects | with or just after #43, which is the first caller to take a name from a URL |

Added on the 2026-08-26 re validation. #47 and #48 were filed during Phase 4
reviews, after this table was written.

## Corrections found when validating this plan

Written before Phases 3 and 4, and it drifted. Everything in this section has
now been **applied to the snippets below**, on 2026-08-26, after Phase 4
closed. The findings are kept rather than deleted, because a plan that looks
like it was always right teaches the next reader nothing about how it went
wrong.

The instruction that produced this section is worth keeping too: **re validate
this plan again before Phase 6**, and again before Phase 7. The last three
plans each drifted from the phase built after them, and this one drifted in
nine separate places.

### 1. `session_url` no longer returns a string (APPLIED)

The route does `JSONResponse({"name": name, "url": url})`, where `url` came
from `engine.session_url`. That now returns `SessionUrl(url, source)`, decided
in #29 because a scraped URL can be scrollback from a session that ended hours
ago, and #29 records that the provenance reaches the API.

So the response carries both, and the interface can present a scraped link
differently from a known good one instead of showing them as equals. A
dataclass handed to `JSONResponse` unchanged is not serialisable, so this
fails loudly rather than silently, which is the one mercy.

### 2. The CLI is missing flags the README already promises (APPLIED)

`parse_args` defines `--root`, `--host`, `--port`, `--token`, `--allow-host`,
`--allow-origin` and `--self-project`. `Config` has fifteen settable fields.

Not every field needs a flag, and `sessions_dir` and `tmux_socket` are
reasonable to leave out of v1. But **`--agent-binary` is promised in the
README's prerequisites table** and required by #28, which refuses to start when
that binary is missing and names it in the message. A flag the README documents
and the CLI does not accept is a bug the first user finds.

Worth deciding rather than defaulting: `--stop-timeout` and the three memory
floors are documented in `.claude/CLAUDE.md` as defaults, and a default that
cannot be changed is a constant. The design does not require them as flags, so
this plan should either add them or say why they stay fixed.

### 3. Re validated after Phase 4, 2026-08-26

The instruction above says to re validate when Phase 5 actually starts. Phase 4
is closed, so this is that pass. Corrections 1 and 2 above still stand and are
still unfixed in the snippets. What follows is new.

#### 3a. `?kill=1` contradicts the rule it is written next to (APPLIED, #52 decided: separate route)

The design's section 6 table specifies `DELETE /api/sessions/{name}?kill=1`,
and the paragraph directly beneath it says the kill "is a distinct call rather
than a flag on the same one ... so a kill is never a query parameter away from
a client that meant to be gentle". Those cannot both hold. `.claude/CLAUDE.md`
carries the prose version as a non negotiable; this plan implements the table
version; ticket #43 states the rule and then specifies the flag, in the same
paragraph.

Nobody introduced this. It has been copied forward four times because each copy
looked like the source. **Filed as #52, because it changes an operator
visible contract and the call is not this plan's to make.** Settle #52 before
#43 implements either side.

#### 3b. `MachineUnreadable` is caught nowhere, so an unreadable machine is a 500 (APPLIED)

Every engine read goes through `_look`, which raises `MachineUnreadable` when
the process table cannot be read or tmux cannot be run. That is deliberate in
Phase 4: an unreadable machine is an error rather than a fifth state, because
deriving `stopped` from it reports every running agent as not running.

No route in this plan catches it and the envelope has no code for it, so a
machine without tmux answers every request with a 500 and an empty body. The
one state the engine works hardest to report honestly is the one the API turns
into a crash. Needs a code, a status, and a handler on every route that reads.
`503` alongside `root_unavailable` is the natural shape: both mean "ask again",
neither is the caller's fault.

#### 3c. Two `except eng.Protected` handlers cannot fire (APPLIED)

Phase 4 settled which methods refuse the self project, and it is not the set
this plan assumes. Verified against the built engine:

```
start        -> raises Protected
stop         -> raises Protected
kill         -> raises Protected
logs         -> no Protected
session_url  -> no Protected
```

`logs` deliberately does not refuse the self project: reading the log of the
session hosting Hitchrail is harmless and occasionally the only way to see what
it is doing. So the `except eng.Protected` on the `logs` and `session_url`
routes is dead code, and this project treats a guard that cannot execute as
worse than none, because a reader who finds one stops trusting the rest.

#### 3d. The `start` route does not catch `Protected`, and `start` raises it (APPLIED)

The mirror of 3c. `POST /api/sessions/{self_project}` returns a 500 rather than
the documented `423 self_protected`. That is the route where the protection
matters most: it is the one that would put a second agent in Hitchrail's own
folder.

#### 3e. The ticket table is missing #47 and #48 (APPLIED)

Both were filed during Phase 4 reviews, after this plan was written, and both
are milestoned Phase 5. #47 is `get()` answering for names that are not
projects; #48 is `self_project` never being validated, so the protection in 3c
and 3d silently protects nothing when the name is wrong. #48 in particular is a
prerequisite for 3d being worth anything.

#### 3g. `/api/projects` walked the root twice, and could contradict itself

Found while applying 3b. The route called `engine.list()` and
`discovery.scan()` separately, and `engine.list` resolves its names through
`discovery.list_projects`, which IS `scan(root).projects`. Two walks of the
root per request, on the route the interface polls hardest, and measured rather
than assumed: two `scan` calls and three thread hops for one response.

The cost is the smaller half. The two walks can DISAGREE, so a folder created
between them appeared in `unsupported` while being absent from `projects`, in
the same JSON body. `Engine.list` now takes an optional `listing`, added in
Phase 4 with three tests, and the route takes one scan and hands it in.

#### 3f. Phase 4 changes this plan predates

- `engine.logs` now raises `NotRunning` for a name with no session rather than
  returning empty output. The plan's `logs` route already maps that to 409, so
  this one is aligned and needs no change. Recorded so the next reader does not
  re-derive it.
- `engine.kill` now waits a bounded 2 seconds for the process to leave the
  table, so the route's `in_thread(engine.kill)` can block for that long. It is
  already off the event loop, so nothing changes here either.
- The `stopping` overlay no longer applies to a `stopped` session. The two
  places this plan asserts `stopping is True` are both on live sessions, so
  they still hold.

### Task 15: The REST surface and the error envelope

**Files:**
- Modify: `src/hitchrail/server.py`
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: `Engine` and `Session` (Phase 4), `EventBus` (Phase 4 Task 11), `Config` (Phase 1), `middleware_stack` (Phase 2).
- Produces: `create_app(engine: Engine, config: Config, bus: EventBus) -> Starlette`; `in_thread(fn: Callable[..., T], *args: object) -> T`. The bus is REQUIRED and the caller owns it: see the note on `create_app`.

- [ ] **Step 1: Write the failing tests**

`tests/test_api.py`:

```python
from __future__ import annotations

import asyncio
import contextlib
import logging
import pathlib
from collections.abc import AsyncIterator

import httpx
import pytest

from hitchrail.engine import Engine
from hitchrail.events import EventBus
from hitchrail.server import SWEEP_INTERVAL_S, create_app

from .conftest import FakeClock, FakeTmux, ScriptedProcs, procs_from

RUNNING_PS = """\
 500     1   4096   600 tmux new-session -d -s hr-vessel
 501   500 512000   600 claude --dangerously-skip-permissions --remote-control vessel
"""

STARTED_PS = """\
 1001     1   4096      5 tmux new-session -d -s hr-network
 1002  1001 300000      5 claude --dangerously-skip-permissions --remote-control network
"""

PLENTY = "MemAvailable: 25198592 kB\n"
HEADERS = {"host": "localhost", "origin": "http://localhost:8787"}


def make_engine(config, tmux, procs, mem: str = PLENTY) -> Engine:
    clock = FakeClock()
    return Engine(
        config=config,
        tmux=tmux,
        procs_fn=procs,
        meminfo_fn=lambda: mem,
        clock=clock,
        sleep=clock.sleep,
    )


@contextlib.asynccontextmanager
async def client_for(engine: Engine, config) -> AsyncIterator[httpx.AsyncClient]:
    """A client wired to a real app. An async context manager rather than a
    bare generator, so the transport is actually closed when a test finishes."""
    app = create_app(engine=engine, config=config, bus=EventBus())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as c:
        yield c


@pytest.fixture
def engine(config):
    return make_engine(config, FakeTmux(sessions={"vessel": 500}), procs_from(RUNNING_PS))


@pytest.fixture
async def client(engine, config) -> AsyncIterator[httpx.AsyncClient]:
    async with client_for(engine, config) as c:
        yield c


async def test_projects_lists_every_folder_with_its_state(client) -> None:
    body = (await client.get("/api/projects", headers=HEADERS)).json()
    names = [p["name"] for p in body["projects"]]
    assert names == ["vessel", "vessel-social", "network", "dotted.site"]
    assert body["projects"][0]["state"] == "running"
    assert body["projects"][2]["state"] == "stopped"


async def test_projects_reports_available_memory(client) -> None:
    body = (await client.get("/api/projects", headers=HEADERS)).json()
    assert body["memory"]["available_mb"] == 24608


async def test_start_returns_the_new_session(config) -> None:
    engine = make_engine(config, FakeTmux(), procs_from(STARTED_PS))
    async with client_for(engine, config) as c:
        r = await c.post("/api/sessions/network", headers=HEADERS)
    assert r.status_code == 201
    assert r.json()["state"] == "running"


async def test_start_survives_a_process_table_that_lags(config) -> None:
    # The engine's grace window, exercised through the API, because this is
    # the path a person actually taps.
    engine = make_engine(config, FakeTmux(), ScriptedProcs("", "", STARTED_PS))
    async with client_for(engine, config) as c:
        r = await c.post("/api/sessions/network", headers=HEADERS)
    assert r.status_code == 201


async def test_starting_a_running_session_is_a_conflict(client) -> None:
    r = await client.post("/api/sessions/vessel", headers=HEADERS)
    assert r.status_code == 409
    assert r.json()["code"] == "already_running"


async def test_a_second_start_in_flight_is_reported_as_locked(config, engine) -> None:
    engine._starting.add("network")
    async with client_for(engine, config) as c:
        r = await c.post("/api/sessions/network", headers=HEADERS)
    assert r.status_code == 409
    assert r.json()["code"] == "locked"


async def test_unknown_project_is_a_404_with_a_code(client) -> None:
    r = await client.post("/api/sessions/nope", headers=HEADERS)
    assert r.status_code == 404
    assert r.json()["code"] == "unknown_project"


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/sessions/nope"),
        ("DELETE", "/api/sessions/nope"),
        ("GET", "/api/sessions/nope/logs"),
        ("GET", "/api/sessions/nope/url"),
    ],
)
async def test_every_route_agrees_that_an_unknown_project_is_a_404(
    client, method: str, path: str
) -> None:
    # A caller who mistyped a folder name must not be told the session is
    # stopped. Two different questions, two different answers.
    r = await client.request(method, path, headers=HEADERS)
    assert r.status_code == 404
    assert r.json()["code"] == "unknown_project"


async def test_a_traversing_name_is_a_404_and_spawns_nothing(client, engine) -> None:
    r = await client.post("/api/sessions/..%2f..%2fetc", headers=HEADERS)
    assert r.status_code == 404
    assert engine.tmux.started == []


async def test_hard_memory_refusal_is_507_with_the_numbers(config) -> None:
    engine = make_engine(
        config, FakeTmux(), procs_from(""), "MemAvailable: 1048576 kB\n"
    )
    async with client_for(engine, config) as c:
        r = await c.post("/api/sessions/network", headers=HEADERS)
    assert r.status_code == 507
    assert r.json()["code"] == "ram_hard"
    assert r.json()["available_mb"] == 1024
    assert r.json()["needed_mb"] == 1536


async def test_soft_memory_needs_an_acknowledgement(config) -> None:
    engine = make_engine(
        config, FakeTmux(), ScriptedProcs("", "", STARTED_PS), "MemAvailable: 4194304 kB\n"
    )
    async with client_for(engine, config) as c:
        first = await c.post("/api/sessions/network", headers=HEADERS)
        assert first.status_code == 409
        assert first.json()["code"] == "ram_soft"
        assert first.json()["available_mb"] == 4096
        second = await c.post("/api/sessions/network?acknowledged=1", headers=HEADERS)
    assert second.status_code == 201
    assert second.json()["state"] == "running"


async def test_a_soft_refusal_spawns_nothing_on_its_own(config) -> None:
    # The server never proceeds on a soft refusal by itself.
    tmux = FakeTmux()
    engine = make_engine(config, tmux, procs_from(""), "MemAvailable: 4194304 kB\n")
    async with client_for(engine, config) as c:
        await c.post("/api/sessions/network", headers=HEADERS)
    assert tmux.started == []


async def test_a_session_that_never_comes_up_is_502(config) -> None:
    tmux = FakeTmux()
    tmux.pane_text["network"] = "Error: claude not found\n"
    engine = make_engine(config, tmux, procs_from(""))
    async with client_for(engine, config) as c:
        r = await c.post("/api/sessions/network", headers=HEADERS)
    assert r.status_code == 502
    assert r.json()["code"] == "start_died"
    assert "claude not found" in r.json()["output"]


async def test_delete_begins_a_graceful_stop_and_kills_nothing(client, engine) -> None:
    r = await client.delete("/api/sessions/vessel", headers=HEADERS)
    assert r.status_code == 202
    assert r.json()["stopping"] is True
    assert engine.tmux.killed == []


async def test_the_kill_route_kills(client, engine) -> None:
    r = await client.post("/api/sessions/vessel/kill", headers=HEADERS)
    assert r.status_code == 200
    assert engine.tmux.killed == ["vessel"]


@pytest.mark.parametrize(
    "query", ["", "?kill=1", "?kill=true", "?force=1", "?kill=1&acknowledged=1"]
)
async def test_delete_never_kills_whatever_the_query_string(
    client, engine, query: str
) -> None:
    """The regression test this whole design decision exists for.

    An earlier draft read `?kill=1` off the DELETE and picked the engine method
    from it, so a graceful stop and a kill differed by four characters in a
    query string: a templating mistake, a copied `curl`, or a UI building the
    URL from a variable turns "ask nicely" into "kill now" with no type error
    and no 404. `?kill=1` is in this list on purpose, because it is the exact
    string that used to work.
    """
    r = await client.delete(f"/api/sessions/vessel{query}", headers=HEADERS)
    assert r.status_code == 202
    assert engine.tmux.killed == [], "a query parameter reached the kill path"


async def test_kill_without_a_preceding_stop_is_accepted_by_the_api(client, engine) -> None:
    """Etiquette is a property of the interface, not of the API."""
    await client.post("/api/sessions/vessel/kill", headers=HEADERS)
    assert engine.tmux.killed == ["vessel"]


async def test_the_kill_route_is_origin_checked_like_every_mutating_route(
    client, engine
) -> None:
    """A kill route accidentally treated as a GET exemption would be strictly
    worse than the flag design it replaced."""
    r = await client.post(
        "/api/sessions/vessel/kill",
        headers={**HEADERS, "origin": "http://evil.example"},
    )
    assert r.status_code == 403
    assert engine.tmux.killed == []


async def test_the_protected_project_is_423(root, config) -> None:
    from hitchrail.config import Config

    cfg = Config(root=root, sessions_dir=root / ".s", self_project="vessel")
    engine = make_engine(cfg, FakeTmux(sessions={"vessel": 500}), procs_from(RUNNING_PS))
    async with client_for(engine, cfg) as c:
        r = await c.delete("/api/sessions/vessel", headers=HEADERS)
    assert r.status_code == 423
    assert r.json()["code"] == "self_protected"


async def test_logs_returns_the_pane_tail(client, engine) -> None:
    engine.tmux.pane_text["vessel"] = "one\ntwo\n"
    r = await client.get("/api/sessions/vessel/logs", headers=HEADERS)
    assert r.json()["text"] == "one\ntwo\n"


async def test_the_url_route_returns_the_link(client, engine) -> None:
    engine.tmux.pane_text["vessel"] = "https://claude.ai/code/session_live\n"
    r = await client.get("/api/sessions/vessel/url", headers=HEADERS)
    assert r.status_code == 200
    assert r.json()["url"] == "https://claude.ai/code/session_live"


async def test_the_url_route_reports_pending_rather_than_guessing(client) -> None:
    # The design's url_pending code. Listing never captures a pane, so a link
    # that Claude has not written yet is absent, and this is where a client
    # finds out that absent means "not yet" rather than "never".
    r = await client.get("/api/sessions/vessel/url", headers=HEADERS)
    assert r.status_code == 409
    assert r.json()["code"] == "url_pending"


async def test_creating_a_folder_makes_it_appear(client, config) -> None:
    r = await client.post("/api/projects", json={"name": "brand-new"}, headers=HEADERS)
    assert r.status_code == 201
    body = (await client.get("/api/projects", headers=HEADERS)).json()
    assert "brand-new" in [p["name"] for p in body["projects"]]
    assert (config.root / "brand-new").is_dir()


async def test_creating_a_traversing_folder_is_refused(client, config) -> None:
    r = await client.post("/api/projects", json={"name": "../evil"}, headers=HEADERS)
    assert r.status_code == 400
    assert r.json()["code"] == "invalid_name"
    assert not (config.root.parent / "evil").exists()


async def test_creating_an_existing_folder_is_a_conflict(client) -> None:
    r = await client.post("/api/projects", json={"name": "network"}, headers=HEADERS)
    assert r.status_code == 409
    assert r.json()["code"] == "already_exists"


async def test_a_body_that_is_not_json_is_a_400_not_a_500(client) -> None:
    r = await client.post(
        "/api/projects",
        content=b"not json",
        headers={**HEADERS, "content-type": "application/json"},
    )
    assert r.status_code == 400
    assert r.json()["code"] == "invalid_name"


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/sessions/nope"),
        ("POST", "/api/sessions/vessel"),
        ("GET", "/api/sessions/nope/url"),
        ("GET", "/api/sessions/vessel/url"),
        ("POST", "/api/projects"),
    ],
)
async def test_no_error_body_leaks_a_path_or_a_traceback(
    client, method: str, path: str
) -> None:
    r = await client.request(method, path, headers=HEADERS)
    assert r.status_code >= 400, "this case is meant to be a refusal"
    body = r.text
    assert "Traceback" not in body
    assert ".py" not in body
    assert str(pathlib.Path.home()) not in body
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_api.py -v`
Expected: FAIL with `ImportError: cannot import name 'create_app' from 'hitchrail.server'`.

- [ ] **Step 3: Implement**

Replace the stub `src/hitchrail/server.py` with:

```python
"""The HTTP layer. Routing and translation only; the logic lives in the engine.

Starlette 1.x: lifespan context manager and an explicit routes list. The
on_startup, on_shutdown, add_event_handler and @app.route decorators were all
removed at 1.0, so any example using them predates this API.
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import logging
from collections.abc import AsyncIterator, Callable
from typing import TypeVar

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from hitchrail import discovery
from hitchrail import engine as eng
from hitchrail.config import Config
from hitchrail.events import EventBus
from hitchrail.security import middleware_stack

T = TypeVar("T")

SWEEP_INTERVAL_S = 1.0

logger = logging.getLogger(__name__)


async def in_thread(fn: Callable[..., T], *args: object, **kwargs: object) -> T:
    """Run a blocking engine call off the event loop.

    The engine spawns `ps` and `tmux`. Doing that on the loop stalls the SSE
    stream for every connected browser, because the stream lives on the same
    loop. A sync `def` handler would get this for free from Starlette, but a
    sync handler cannot await a request body, and the create route needs one.

    Two taps therefore land on two threads, which is what the per folder start
    lock in the engine exists to serialise.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, functools.partial(fn, *args, **kwargs))


def _error(status: int, code: str, message: str, **extra: object) -> JSONResponse:
    return JSONResponse({"code": code, "message": message, **extra}, status_code=status)


def create_app(engine: eng.Engine, config: Config, bus: EventBus) -> Starlette:
    """The bus is REQUIRED, and the caller owns it.

    An earlier draft took it optionally and reconciled it against `engine.bus`.
    There is no such attribute: `Engine` has a private `_bus` and
    `attach_bus()`, so that draft raised `AttributeError` on this line. Worth
    more than the typo, though, is that it was reading two sources of truth to
    decide which bus wins, which is precisely how the "published into a void"
    bug it warned about gets written. One owner, passed in, attached once.
    """
    engine.attach_bus(bus)
    events = bus

    async def list_projects(request: Request) -> Response:
        # ONE scan, one thread hop, one consistent answer.
        #
        # An earlier draft called `engine.list()` and `discovery.scan()`
        # separately. `engine.list` resolves its names through
        # `discovery.list_projects`, which IS `scan(root).projects`, so the
        # root was walked twice per request on the route the interface polls
        # hardest. Worse than the cost: the two walks can disagree, so a folder
        # created between them appeared in `unsupported` while being absent
        # from `projects`, or the reverse.
        #
        # `unsupported` is the folders under the root that cannot be projects,
        # each with the rule it broke. Dropping them silently made a folder
        # called `my app` look like one Hitchrail could not see. See issue #7.
        def read() -> tuple[discovery.Listing, list[eng.Session], int]:
            listing = discovery.scan(config.root)
            return listing, engine.list(listing=listing), engine.available_mb()

        try:
            listing, sessions, available = await in_thread(read)
        except discovery.RootUnavailable as exc:
            # The root going away, an unmounted drive or a deleted directory,
            # is not "no projects". Reporting an empty list would be a lie the
            # interface cannot tell from a genuinely empty root.
            return _error(503, "root_unavailable", str(exc))
        except eng.MachineUnreadable as exc:
            # Same honesty, one layer down. Phase 4 makes an unreadable machine
            # an error rather than a fifth state precisely so this is not
            # derived as `stopped`, and answering 500 here would throw that
            # away on the one route that renders the whole table.
            return _error(503, "machine_unreadable", str(exc))
        return JSONResponse(
            {
                "projects": [s.as_dict() for s in sessions],
                "unsupported": [
                    {"name": u.name, "reason": u.reason} for u in listing.unsupported
                ],
                # The true count, because the list above is capped. The
                # interface says "50 of 1240 shown"; hiding the excess
                # silently would be the bug this whole field exists to fix.
                "unsupported_total": listing.unsupported_total,
                "memory": {"available_mb": available},
            }
        )

    async def create_project(request: Request) -> Response:
        try:
            payload = await request.json()
            name = str(payload["name"])
        except (ValueError, KeyError, TypeError):
            # A malformed body is a bad name, not a server fault. Returning 500
            # here would put a traceback where a client expects a code.
            return _error(400, "invalid_name", "a JSON body with a 'name' is required")
        try:
            await in_thread(discovery.create_project, config.root, name)
        except discovery.AlreadyExists as exc:
            return _error(409, "already_exists", str(exc))
        except discovery.RootUnavailable as exc:
            # The root went away under us. Not the caller's fault, and not
            # something to answer by pretending there are no projects.
            return _error(503, "root_unavailable", str(exc))
        except (discovery.InvalidName, discovery.OutsideRoot) as exc:
            # Both mean "not a name we will turn into a path here". Telling the
            # caller which guard caught it describes the filesystem to them.
            return _error(400, "invalid_name", str(exc))
        session = await in_thread(engine.get, name)
        events.publish({"kind": "session", "session": session.as_dict()})
        return JSONResponse(session.as_dict(), status_code=201)

    async def start(request: Request) -> Response:
        name = request.path_params["name"]
        acknowledged = request.query_params.get("acknowledged") in {"1", "true"}
        try:
            session = await in_thread(engine.start, name, acknowledged)
        except eng.UnknownProject as exc:
            return _error(404, "unknown_project", str(exc))
        except eng.AlreadyRunning as exc:
            return _error(409, "already_running", str(exc))
        except eng.Locked as exc:
            return _error(409, "locked", f"a start is already in flight for {exc}")
        except eng.MemoryNeedsAck as exc:
            return _error(
                409,
                "ram_soft",
                "starting would leave the machine short on memory",
                available_mb=exc.available_mb,
                needed_mb=exc.needed_mb,
            )
        except eng.MemoryRefused as exc:
            return _error(
                507,
                "ram_hard",
                "not enough memory to start a session",
                available_mb=exc.available_mb,
                needed_mb=exc.needed_mb,
            )
        except eng.StartFailed as exc:
            return _error(502, "start_died", str(exc), output=exc.output)
        except eng.Protected as exc:
            # `start` raises this and an earlier draft did not catch it, so the
            # one route where the protection matters most, the one that would
            # put a SECOND agent in Hitchrail's own folder, answered 500.
            return _error(423, "self_protected", str(exc))
        except eng.MachineUnreadable as exc:
            return _error(503, "machine_unreadable", str(exc))
        return JSONResponse(session.as_dict(), status_code=201)

    async def stop(request: Request) -> Response:
        """The graceful one. NOTHING in the query string reaches `kill`.

        The two used to be one handler picking a method from `?kill=1`, which
        contradicted the design paragraph it was written next to. See #52: a
        duration is a parameter, an action is a route, and there is not even a
        duration here because the wait is `stop_timeout` in the configuration.
        """
        name = request.path_params["name"]
        try:
            session = await in_thread(engine.stop, name)
        except eng.UnknownProject as exc:
            return _error(404, "unknown_project", str(exc))
        except eng.Protected as exc:
            return _error(423, "self_protected", str(exc))
        except eng.NotRunning as exc:
            return _error(409, "not_running", str(exc))
        except eng.MachineUnreadable as exc:
            return _error(503, "machine_unreadable", str(exc))
        return JSONResponse(session.as_dict(), status_code=202)

    async def kill(request: Request) -> Response:
        """The destructive one, on its own path and its own method.

        Accepted whether or not a graceful stop preceded it: the requirement to
        try gently first is a property of the interface, not of the API. A CLI
        user has a legitimate need to kill outright, and enforcing etiquette in
        the transport would only invite working around it.

        200 rather than 202 because, unlike the graceful stop, this one has
        already happened by the time it answers. `engine.kill` waits a bounded
        two seconds for the process to actually leave the table, so the session
        in the body is settled rather than in flight.
        """
        name = request.path_params["name"]
        try:
            session = await in_thread(engine.kill, name)
        except eng.UnknownProject as exc:
            return _error(404, "unknown_project", str(exc))
        except eng.Protected as exc:
            return _error(423, "self_protected", str(exc))
        except eng.NotRunning as exc:
            return _error(409, "not_running", str(exc))
        except eng.MachineUnreadable as exc:
            return _error(503, "machine_unreadable", str(exc))
        return JSONResponse(session.as_dict(), status_code=200)

    async def logs(request: Request) -> Response:
        name = request.path_params["name"]
        try:
            lines = int(request.query_params.get("lines", 40))
        except ValueError:
            lines = 40
        lines = max(1, min(lines, 2000))
        try:
            text = await in_thread(engine.logs, name, lines)
        except eng.UnknownProject as exc:
            return _error(404, "unknown_project", str(exc))
        except eng.NotRunning as exc:
            return _error(409, "not_running", str(exc))
        except eng.MachineUnreadable as exc:
            return _error(503, "machine_unreadable", str(exc))
        # No `Protected` arm, and that is not an oversight. `engine.logs`
        # deliberately does not refuse the self project: reading the log of the
        # session hosting Hitchrail is harmless and occasionally the only way
        # to see what it is doing. An arm here could never fire, and this
        # project treats a guard that cannot execute as worse than none.
        return JSONResponse({"name": name, "text": text})

    async def session_url(request: Request) -> Response:
        """The link, paid for on demand.

        Listing never captures a pane, so a session whose link Claude has not
        written yet simply has none. This is where a client learns that the
        absence means "not yet" rather than "never".
        """
        name = request.path_params["name"]
        try:
            found = await in_thread(engine.session_url, name)
        except eng.UnknownProject as exc:
            return _error(404, "unknown_project", str(exc))
        except eng.NotRunning as exc:
            return _error(409, "not_running", str(exc))
        except eng.MachineUnreadable as exc:
            return _error(503, "machine_unreadable", str(exc))
        # No `Protected` arm here either, for the same reason as `logs`:
        # `engine.session_url` gates on the name only, so it cannot fire.
        if found is None:
            return _error(409, "url_pending", "the session has not published a link yet")
        # BOTH fields. `engine.session_url` returns `SessionUrl(url, source)`,
        # not a string, and handing the dataclass to `JSONResponse` unchanged
        # is a TypeError rather than a wrong answer, which is the one mercy.
        #
        # `source` travels because a scraped link can be scrollback from a
        # session that ended hours ago, while a bridge link is known good. The
        # interface has to be able to present those differently instead of
        # showing them as equals. Decided in #29.
        return JSONResponse(
            {"name": name, "url": found.url, "source": found.source}
        )

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        app.state.events = events
        app.state.engine = engine

        async def sweep() -> None:
            """Expire stop markers on a timer, so a timeout the user is
            watching resolves without waiting for the next poll.

            The loop must outlive any single failure, because if this task
            ends no stop expires again for the life of the process, and the
            interface shows a timer that never resolves. It must NOT do that
            silently, though: a bare suppress here makes "expiry stopped
            working" unfalsifiable, and this ran for a whole phase before
            anybody would notice. The engine already logs the expected
            operational case (a machine it cannot read); this catches the
            unexpected one and says so.
            """
            while True:
                await asyncio.sleep(SWEEP_INTERVAL_S)
                try:
                    await in_thread(engine.expire_stops)
                except Exception:
                    logger.exception("stop sweep failed; the timer continues")

        task = asyncio.create_task(sweep())
        try:
            yield
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    return Starlette(
        routes=[
            Route("/api/projects", list_projects, methods=["GET"]),
            Route("/api/projects", create_project, methods=["POST"]),
            Route("/api/sessions/{name}", start, methods=["POST"]),
            Route("/api/sessions/{name}", stop, methods=["DELETE"]),
            # Its own route, deliberately. #52 and the design's section 6.
            Route("/api/sessions/{name}/kill", kill, methods=["POST"]),
            Route("/api/sessions/{name}/logs", logs, methods=["GET"]),
            Route("/api/sessions/{name}/url", session_url, methods=["GET"]),
        ],
        middleware=middleware_stack(config),
        lifespan=lifespan,
    )
```

The `json` import is unused until Task 16 adds the event stream. Leave it out
for now; ruff's `F401` will fail the gate otherwise, and Task 16 adds it back
with the route that needs it.

- [ ] **Step 3b: The sweep survives a failing tick, and says so**

The loop must outlive one bad tick, because if the task ends no stop expires
again for the life of the process and the interface shows a timer that never
resolves. Add to `tests/test_api.py`:

```python
async def test_the_stop_sweep_outlives_a_failing_tick(config, caplog) -> None:
    """A silent suppress here would make "expiry stopped working"
    unfalsifiable, so the test asserts the log as well as the survival."""
    calls = []

    class Boom(Engine):
        def expire_stops(self):
            calls.append(len(calls))
            if len(calls) == 1:
                raise RuntimeError("one bad tick")
            return []

    engine = Boom(
        config=config,
        tmux=FakeTmux(sessions={}),
        procs_fn=procs_from(""),
        meminfo_fn=lambda: PLENTY,
    )
    with caplog.at_level(logging.ERROR, logger="hitchrail.server"):
        async with client_for(engine, config):
            # Long enough for at least two ticks at SWEEP_INTERVAL_S.
            await asyncio.sleep(SWEEP_INTERVAL_S * 2.5)

    assert len(calls) >= 2, "the sweep stopped after the failing tick"
    assert "stop sweep failed" in caplog.text, "the failure was swallowed silently"
```

- [ ] **Step 4: Run to verify passing**

Run: `uv run pytest tests/test_api.py -v`
Expected: PASS. Count from the output; the parametrised cases make the total
larger than the function count.

- [ ] **Step 5: Gates and commit**

```bash
uv run ruff check && uv run ruff format --check && uv run mypy && uv run lint-imports
git add src/hitchrail/server.py tests/test_api.py
git commit -m "feat(api): REST surface, stable error codes, engine calls off the loop"
```

---

### Task 16: The event stream

**Files:**
- Modify: `src/hitchrail/server.py`
- Test: `tests/test_sse.py`

**Interfaces:**
- Consumes: `EventBus`, `create_app` (Task 15).
- Produces: a `GET /api/events` route returning `EventSourceResponse`.

- [ ] **Step 1: Write the failing tests**

`tests/test_sse.py`:

```python
from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from hitchrail.config import Config
from hitchrail.engine import Engine
from hitchrail.events import EventBus
from hitchrail.security import TOKEN_COOKIE
from hitchrail.server import create_app

from .conftest import FakeClock, FakeTmux, procs_from

HEADERS = {"host": "localhost", "accept": "text/event-stream"}


def parts(config: Config) -> tuple[EventBus, object]:
    bus = EventBus()
    clock = FakeClock()
    engine = Engine(
        config=config,
        tmux=FakeTmux(sessions={"vessel": 500}),
        procs_fn=procs_from(""),
        meminfo_fn=lambda: "MemAvailable: 25198592 kB\n",
        clock=clock,
        sleep=clock.sleep,
        bus=bus,
    )
    return bus, create_app(engine=engine, config=config, bus=bus)


@pytest.fixture
def app_and_bus(config):
    return parts(config)


async def test_the_stream_announces_itself_as_event_stream(app_and_bus) -> None:
    _bus, app = app_and_bus
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as c:
        async with c.stream("GET", "/api/events", headers=HEADERS) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")


async def test_a_published_event_reaches_the_stream(app_and_bus) -> None:
    bus, app = app_and_bus
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as c:
        async with c.stream("GET", "/api/events", headers=HEADERS) as response:

            async def publish_soon() -> None:
                await asyncio.sleep(0.05)
                bus.publish({"kind": "session", "session": {"name": "vessel"}})

            task = asyncio.create_task(publish_soon())
            payload = None
            async for line in response.aiter_lines():
                if line.startswith("data:"):
                    payload = json.loads(line.removeprefix("data:").strip())
                    break
            await task
    assert payload == {"kind": "session", "session": {"name": "vessel"}}


async def test_the_stream_is_reachable_without_an_origin_header(app_and_bus) -> None:
    # EventSource cannot set headers, and GET is a safe method, so the origin
    # check must not apply to it.
    _bus, app = app_and_bus
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as c:
        async with c.stream("GET", "/api/events", headers=HEADERS) as response:
            assert response.status_code == 200


async def test_the_stream_authenticates_by_cookie(root) -> None:
    # The reason Phase 2 Task 6 exists. EventSource sends cookies and no
    # Authorization header, so a token that only lives in a header
    # authenticates every route except the one the interface depends on.
    cfg = Config(root=root, sessions_dir=root / ".s", host="0.0.0.0", token="tok")
    _bus, app = parts(cfg)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as c:
        async with c.stream(
            "GET",
            "/api/events",
            headers={**HEADERS, "cookie": f"{TOKEN_COOKIE}=tok"},
        ) as response:
            assert response.status_code == 200


async def test_the_stream_refuses_an_unauthenticated_reader(root) -> None:
    cfg = Config(root=root, sessions_dir=root / ".s", host="0.0.0.0", token="tok")
    _bus, app = parts(cfg)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as c:
        r = await c.get("/api/events", headers=HEADERS)
    assert r.status_code == 401


async def test_a_forged_host_cannot_open_the_stream(app_and_bus) -> None:
    _bus, app = app_and_bus
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as c:
        r = await c.get("/api/events", headers={"host": "evil.example"})
    assert r.status_code == 400


async def test_a_state_change_made_through_the_api_reaches_the_stream(config) -> None:
    # The end to end claim of the whole design: progress arrives over SSE like
    # every other state change, rather than being polled for.
    bus = EventBus()
    clock = FakeClock()
    running = """\
 500     1   4096   600 tmux new-session -d -s hr-vessel
 501   500 512000   600 claude --dangerously-skip-permissions --remote-control vessel
"""
    engine = Engine(
        config=config,
        tmux=FakeTmux(sessions={"vessel": 500}),
        procs_fn=procs_from(running),
        meminfo_fn=lambda: "MemAvailable: 25198592 kB\n",
        clock=clock,
        sleep=clock.sleep,
        bus=bus,
    )
    app = create_app(engine=engine, config=config, bus=bus)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as c:
        async with c.stream("GET", "/api/events", headers=HEADERS) as response:

            async def stop_soon() -> None:
                await asyncio.sleep(0.05)
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url="http://localhost"
                ) as actor:
                    await actor.delete(
                        "/api/sessions/vessel",
                        headers={"host": "localhost", "origin": "http://localhost:8787"},
                    )

            task = asyncio.create_task(stop_soon())
            payload = None
            async for line in response.aiter_lines():
                if line.startswith("data:"):
                    payload = json.loads(line.removeprefix("data:").strip())
                    break
            await task
    assert payload is not None
    assert payload["session"]["stopping"] is True
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_sse.py -v`
Expected: FAIL with 404 on `/api/events`.

- [ ] **Step 3: Implement**

Add `import json` to the imports in `src/hitchrail/server.py`, and:

```python
from sse_starlette.sse import EventSourceResponse
```

Add the handler inside `create_app`, before the `return Starlette(...)`:

```python
    async def event_stream(request: Request) -> Response:
        async def publisher() -> AsyncIterator[dict[str, str]]:
            with events.subscribe() as queue:
                while True:
                    if await request.is_disconnected():
                        return
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=1.0)
                    except TimeoutError:
                        continue
                    yield {"event": "message", "data": json.dumps(event)}

        # sse-starlette handles ping keepalive, disconnect detection and
        # generator shutdown, which are the parts of SSE that are awkward to
        # get right. Note its documented caveat: SSE and GZipMiddleware do not
        # mix, which is why no gzip middleware appears anywhere in this app.
        return EventSourceResponse(publisher())
```

Add the route to the list, last, so the more specific session routes are
matched first:

```python
            Route("/api/events", event_stream, methods=["GET"]),
```

- [ ] **Step 4: Run to verify passing**

Run: `uv run pytest tests/test_sse.py -v`
Expected: PASS, 7 tests.

- [ ] **Step 5: Gates and commit**

```bash
uv run ruff check && uv run ruff format --check && uv run mypy && uv run lint-imports
git add src/hitchrail/server.py tests/test_sse.py
git commit -m "feat(sse): event stream over sse-starlette, reachable by cookie"
```

---

### Task 17: The command line entry point

**Files:**
- Modify: `src/hitchrail/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `Config`, `ConfigError`, `is_loopback_host`, `is_wildcard_host` (Phase 1); `Engine` (Phase 4); `create_app` (Task 15).
- Produces: `parse_args(argv: list[str]) -> argparse.Namespace`; `build_config(args: argparse.Namespace) -> Config`; `banner(config: Config) -> str`; `main(argv: list[str] | None = None) -> int`.

- [ ] **Step 1: Write the failing tests**

`tests/test_cli.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from hitchrail.cli import banner, build_config, main, parse_args


def test_root_is_required_to_be_a_real_directory(tmp_path: Path) -> None:
    args = parse_args(["--root", str(tmp_path)])
    assert build_config(args).root == tmp_path


def test_loopback_is_the_default_bind(tmp_path: Path) -> None:
    cfg = build_config(parse_args(["--root", str(tmp_path)]))
    assert cfg.host == "127.0.0.1"
    assert cfg.is_loopback
    assert cfg.token is None


def test_a_network_bind_generates_a_token_when_none_is_given(tmp_path: Path) -> None:
    cfg = build_config(parse_args(["--root", str(tmp_path), "--host", "0.0.0.0"]))
    assert cfg.token
    assert len(cfg.token) >= 24


def test_an_explicit_token_is_used_verbatim(tmp_path: Path) -> None:
    cfg = build_config(
        parse_args(["--root", str(tmp_path), "--host", "0.0.0.0", "--token", "mine"])
    )
    assert cfg.token == "mine"


def test_a_missing_root_exits_with_a_message(tmp_path: Path, capsys) -> None:
    code = main(["--root", str(tmp_path / "nope")])
    assert code == 2
    assert "root is not a directory" in capsys.readouterr().err


def test_the_banner_carries_a_link_a_phone_can_open(tmp_path: Path) -> None:
    # The token grant from Phase 2 is only useful if something hands the user
    # a URL that carries it. This is that something.
    cfg = build_config(
        parse_args(
            [
                "--root",
                str(tmp_path),
                "--host",
                "0.0.0.0",
                "--token",
                "abc123",
                "--allow-host",
                "box.lan",
            ]
        )
    )
    text = banner(cfg)
    assert "http://box.lan:8787/?token=abc123" in text
    assert "run code on this machine as you" in text.lower()


def test_the_banner_is_silent_on_loopback(tmp_path: Path) -> None:
    cfg = build_config(parse_args(["--root", str(tmp_path)]))
    assert banner(cfg) == ""


def test_the_banner_never_offers_a_wildcard_as_a_link(tmp_path: Path) -> None:
    cfg = build_config(
        parse_args(["--root", str(tmp_path), "--host", "0.0.0.0", "--token", "t"])
    )
    assert "0.0.0.0" not in banner(cfg)


def test_the_token_is_printed_once_on_a_network_bind(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    monkeypatch.setattr("hitchrail.cli._serve", lambda app, cfg: 0)
    main(["--root", str(tmp_path), "--host", "0.0.0.0"])
    out = capsys.readouterr().out
    assert "token" in out.lower()


def test_no_token_banner_on_loopback(tmp_path: Path, capsys, monkeypatch) -> None:
    monkeypatch.setattr("hitchrail.cli._serve", lambda app, cfg: 0)
    main(["--root", str(tmp_path)])
    assert "token" not in capsys.readouterr().out.lower()


def test_extra_allowed_hosts_reach_the_config(tmp_path: Path) -> None:
    cfg = build_config(
        parse_args(
            [
                "--root",
                str(tmp_path),
                "--host",
                "0.0.0.0",
                "--token",
                "t",
                "--allow-host",
                "box.lan",
            ]
        )
    )
    assert "box.lan" in cfg.allowed_hosts


def test_build_config_asks_the_shared_loopback_question(tmp_path: Path) -> None:
    # Two copies of "is this loopback" would drift, and the copy that drifts is
    # the one deciding whether a token is demanded.
    import hitchrail.cli as cli

    assert cli.is_loopback_host is not None


def test_main_returns_two_rather_than_raising_on_a_bad_bind(tmp_path: Path, capsys) -> None:
    code = main(["--root", str(tmp_path), "--host", "0.0.0.0", "--allow-host", "*"])
    assert code == 2
    assert "wildcard" in capsys.readouterr().err
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_cli.py -v`
Expected: FAIL with `ImportError: cannot import name 'banner' from 'hitchrail.cli'`.

- [ ] **Step 3: Implement**

Replace the stub `src/hitchrail/cli.py` with:

```python
"""Command line entry point."""

from __future__ import annotations

import argparse
import secrets
import sys
from pathlib import Path

import uvicorn
from starlette.applications import Starlette

from hitchrail import __version__
from hitchrail.config import Config, ConfigError, is_loopback_host, is_wildcard_host
from hitchrail.engine import Engine
from hitchrail.events import EventBus
from hitchrail.server import create_app


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="hitchrail",
        description="Start and stop headless Claude Code sessions across a folder of projects.",
    )
    parser.add_argument("--root", default=".", type=Path, help="folder holding the projects")
    parser.add_argument("--host", default="127.0.0.1", help="address to bind")
    parser.add_argument("--port", default=8787, type=int)
    parser.add_argument(
        "--token", default=None, help="required off loopback; generated if omitted"
    )
    parser.add_argument(
        "--allow-host",
        dest="allow_hosts",
        action="append",
        default=[],
        help="an extra hostname this server will answer to; repeatable",
    )
    parser.add_argument(
        "--allow-origin",
        dest="allow_origins",
        action="append",
        default=[],
        help=(
            "an exact origin a browser may claim, scheme://host[:port]; "
            "repeatable. Needed behind a TLS terminating proxy, whose scheme "
            "and port cannot be derived from our own bind"
        ),
    )
    parser.add_argument(
        "--self-project", default=None, help="a project that must never be stopped"
    )
    # Promised by the README's prerequisites table and required by #28, which
    # refuses to start when this binary is missing and names it in the message.
    # A flag the README documents and the CLI does not accept is a bug the
    # first user finds.
    #
    # `--agent-binary`, never `--claude-binary`: no vendor name enters the
    # operator contract. The quarantine is a seam, not an abstraction.
    parser.add_argument(
        "--agent-binary",
        default="claude",
        help="the agent executable to run; must be on PATH or an absolute path",
    )
    # A documented default that cannot be changed is a constant, and this one
    # is the wait a person actually watches. The three memory floors stay fixed
    # in v1 deliberately: they are a safety net rather than a preference, and
    # an operator who wants a different one is usually asking for a machine
    # with more memory.
    parser.add_argument(
        "--stop-timeout",
        default=30,
        type=int,
        help="seconds to wait for a graceful stop before reporting it timed out",
    )
    parser.add_argument("--version", action="version", version=f"hitchrail {__version__}")
    return parser.parse_args(argv)


def build_config(args: argparse.Namespace) -> Config:
    token = args.token
    # is_loopback_host is imported rather than reimplemented. Two copies of
    # this rule would drift, and the one that drifts is the one deciding
    # whether a token is demanded at all.
    if not is_loopback_host(args.host) and not token:
        token = secrets.token_urlsafe(24)
    return Config(
        root=args.root,
        host=args.host,
        port=args.port,
        token=token,
        extra_hosts=tuple(args.allow_hosts),
        extra_origins=tuple(args.allow_origins),
        self_project=args.self_project,
        agent_binary=args.agent_binary,
        stop_timeout=args.stop_timeout,
    )


def banner(config: Config) -> str:
    """What to print before serving. Empty on loopback, where there is no token.

    The links matter: the token grant only helps if something hands the user a
    URL carrying it, and typing a 32 character token into a phone is not a
    thing anybody does twice.
    """
    if not config.token:
        return ""

    reachable = [h for h in config.allowed_hosts if not is_wildcard_host(h)]
    lines = [
        "",
        f"  token: {config.token}",
        "  Anyone with this token can run code on this machine as you.",
        "",
        "  Open one of these on your phone:",
    ]
    lines += [
        f"    http://{h}:{config.port}/?token={config.token}"
        for h in reachable
        if h not in {"::1", "[::1]"}
    ]
    lines += [
        "",
        "  The link sets a cookie and drops the token from the address bar.",
        "  Over plain HTTP the token crosses the network in cleartext; put a",
        "  TLS terminating proxy in front of this if that matters to you.",
        "",
    ]
    return "\n".join(lines)


def _serve(app: Starlette, config: Config) -> int:
    uvicorn.run(app, host=config.host, port=config.port, log_level="info")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        config = build_config(args)
        # allowed_hosts is a property, so a bad extra host only raises when it
        # is read. Read it here, inside the guard, rather than letting it
        # surface as a traceback from inside uvicorn.
        _ = config.allowed_hosts
    except ConfigError as exc:
        print(f"hitchrail: {exc}", file=sys.stderr)
        return 2

    text = banner(config)
    if text:
        print(text)

    engine = Engine(config=config)
    # One bus, built here and owned here, because the CLI owns the process.
    return _serve(create_app(engine=engine, config=config, bus=EventBus()), config)
```

- [ ] **Step 4: Run to verify passing**

Run: `uv run pytest tests/test_cli.py -v`
Expected: PASS, 13 tests.

- [ ] **Step 5: Prove it against a real machine**

This is the step that makes Phase 5, and the whole core, done. Tests passing is
not this step.

```bash
mkdir -p /tmp/hitchrail-demo/demo-project
uv run hitchrail --root /tmp/hitchrail-demo &
sleep 2

# the list, and the memory footer
curl -s -H 'Host: localhost' localhost:8787/api/projects | python3 -m json.tool

# start a real session
curl -s -X POST -H 'Host: localhost' -H 'Origin: http://localhost:8787' \
  localhost:8787/api/sessions/demo-project | python3 -m json.tool

# confirm a real tmux session exists and Claude is in it
tmux list-sessions | grep hr-
ps -eo pid,args | grep -- --remote-control | grep -v grep

# the link, once Claude has published one
sleep 5
curl -s -H 'Host: localhost' localhost:8787/api/sessions/demo-project/url | python3 -m json.tool

# ask it to stop, and watch the marker rather than a kill
curl -s -X DELETE -H 'Host: localhost' -H 'Origin: http://localhost:8787' \
  localhost:8787/api/sessions/demo-project | python3 -m json.tool
tmux list-sessions | grep hr-   # still there: nothing was killed

# prove the graceful route cannot be talked into killing, while it is still alive
curl -s -o /dev/null -w 'delete with ?kill=1: %{http_code}\n' \
  -X DELETE -H 'Host: localhost' -H 'Origin: http://localhost:8787' \
  'localhost:8787/api/sessions/demo-project?kill=1'
tmux list-sessions | grep hr-   # STILL THERE: the flag does nothing now

# escalate. A DIFFERENT route and a different method, not a flag on the one above
curl -s -X POST -H 'Host: localhost' -H 'Origin: http://localhost:8787' \
  'localhost:8787/api/sessions/demo-project/kill' | python3 -m json.tool
tmux list-sessions | grep hr- || echo "gone, correct"

# the rebinding refusal, on a live socket
curl -s -o /dev/null -w 'forged host: %{http_code}\n' \
  -H 'Host: evil.example' localhost:8787/api/projects

# the CSRF refusal, on a live socket
curl -s -o /dev/null -w 'foreign origin: %{http_code}\n' -X POST \
  -H 'Host: localhost' -H 'Origin: https://evil.example' \
  localhost:8787/api/sessions/demo-project

# and the token refusal, which needs a second run
kill %1
uv run hitchrail --root /tmp/hitchrail-demo --host 0.0.0.0 --token demo &
sleep 2
curl -s -o /dev/null -w 'no token: %{http_code}\n' -H 'Host: localhost' \
  localhost:8787/api/projects
curl -s -o /dev/null -w 'grant: %{http_code}\n' \
  -H 'Host: localhost' 'localhost:8787/api/projects?token=demo'
kill %1
```

Expected: the list shows `demo-project`; starting it produces a real tmux
session with Claude inside and returns 201 rather than `start_died`; the URL
route eventually returns a `claude.ai/code` link; the graceful stop returns 202
and kills nothing; the kill ROUTE removes the session while `?kill=1` on the
graceful route does not; the forged host returns 400,
the foreign origin 403, the missing token 401, and the grant 303.

- [ ] **Step 6: Gates and commit**

```bash
uv run ruff check && uv run ruff format --check && uv run mypy && uv run lint-imports && uv run pytest
git add src/hitchrail/cli.py tests/test_cli.py
git commit -m "feat(cli): serve command with a generated token and a link a phone can open"
```

---

## Test coverage for this phase

`docs/tech-guidelines.md` 7.4 and 7.5 define the tiers. What this phase owes:

- **This phase is where the integration tier grows**, so it is where the
  missing marker starts to hurt. Mark it, and the tiers become selectable
  instead of being told apart by which file imports `ASGITransport`.
- **Every route gets its success path AND every documented refusal**, each with
  the stable error `code` it returns. A route tested only for 200 is a route
  whose error contract is undefined, and the interface in Phase 6 is written
  against those codes.
- **The SSE stream needs a test that a slow subscriber is dropped rather than
  blocking**, which no unit test of the event bus can see.
- **The CLI preflight (#28) is tested with the lookup injected**, never by
  mutating a real `PATH`, and its refusal messages are asserted for the NAME of
  the missing binary rather than only for a non zero exit. A test that checks
  the exit code passes for a message that says nothing, and the whole value of
  that ticket is in the wording.
- **The token in the access log (#20) is proven on the live socket tier**, not
  through `ASGITransport`. uvicorn writes that line, so a transport test
  structurally cannot see it: that is exactly how the leak survived Phase 2.

## Phase 5 exit criteria

- [ ] All five gates green on 3.11, 3.12 and 3.13.
- [ ] `uvx hitchrail --root ~/dev` serves an API a person can drive with `curl`.
- [ ] A real session has been started, observed, gracefully stopped and killed by hand, and the start returned 201 rather than `start_died`.
- [ ] Every code in the error envelope table above is returned by at least one test, `locked` and `url_pending` included.
- [ ] `GET /api/projects` reports `unsupported` and `unsupported_total` alongside `projects`, so a folder the root holds but Hitchrail cannot open is accounted for rather than absent.
- [ ] A folder whose name is not valid UTF-8 does not turn the project list into a 500. `discovery.display_name` escapes it; the raw name never leaves the module.
- [ ] An unknown project is 404 on every route that takes a name.
- [ ] A malformed JSON body is 400, not 500, and no error body contains a traceback or a filesystem path.
- [ ] The event stream authenticates by cookie with no `Authorization` header, and refuses an unauthenticated reader.
- [ ] A state change made through the API arrives on the stream.
- [ ] A forged `Host`, a foreign `Origin` and a missing token are refused on a live socket, not only in a test.

When these hold, write the Phase 6 plan from `docs/roadmap.md`.

---

## Self review against the design

Checked section by section after writing all five phase plans.

| Design section | Covered by |
|---|---|
| 3, scope: list, refresh, create, start, stop, filter, RAM guard, SSE, log tail | Phases 4 and 5. Filter and search are interface concerns, Phase 6. |
| 4, module layout | Phase 1 Task 1 creates every module; each later task fills one in. |
| 4.1, four states | Phase 4 Task 12. |
| 4.2, five tmux footguns | Phase 3 Task 7, one named test each, plus the injectivity test review added. |
| 4.3, three step stop and the transient marker | Phase 4 Task 14. |
| 4.4, Claude Code quarantine | Phase 3 Task 9, extended to hold the stop key sequence. |
| 5, five security controls | Phase 2 Tasks 4 to 6, plus the path boundary in Phase 1 Task 3. |
| 5.3, stated limitations | Surfaced in the CLI banner in Phase 5 Task 17. |
| 6, HTTP interface and error codes | Phase 5 Tasks 15 and 16. Two additions to the route table are recorded in `docs/roadmap.md`. |
| 7, interface design | Phase 6, not planned yet. |
| 8, versions | Phase 1 Task 1 pins them. |
| 9, distribution and layout | Phase 1 Task 1; publication is Phase 7. |
| 10, testing tiers | Unit throughout, integration in Phase 5, the live socket exception in Phase 2, and the Playwright E2E tier in Phase 6. |
| 11, risks | `bridgeSessionId` (Phase 3 Task 9), hostile network (Phase 2), start race (Phase 4 Task 13), start died (Phase 4 Task 13), memory (Phase 3 Task 10). |
