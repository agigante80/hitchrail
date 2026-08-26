from __future__ import annotations

import asyncio
import contextlib
import logging
import pathlib
import shutil
from collections.abc import AsyncIterator, Callable

import httpx
import pytest

from conftest import FakeClock, FakeTmux, ScriptedProcs, failing_procs, procs_from
from hitchrail import server
from hitchrail.config import Config
from hitchrail.engine import Engine
from hitchrail.events import EventBus
from hitchrail.procs import ProcTable
from hitchrail.server import create_app
from hitchrail.tmux import TmuxUnavailable

# The whole module drives a real Starlette app through `ASGITransport`, so it
# is one tier and says so once. #37, and `tests/test_tiers.py` enforces it.
pytestmark = pytest.mark.integration


@pytest.fixture
def root(tmp_path: pathlib.Path) -> pathlib.Path:
    """`vessel-social` and `dotted.site` are not decoration.

    The first is the tmux prefix match footgun, the second is a name tmux
    rewrites, and both must survive a round trip through the API rather than
    only through the engine.
    """
    for name in ("vessel", "vessel-social", "network", "dotted.site"):
        (tmp_path / name).mkdir()
    return tmp_path


@pytest.fixture
def config(root: pathlib.Path) -> Config:
    return Config(root=root, sessions_dir=root / ".sessions")


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


def make_engine(
    config: Config,
    tmux: FakeTmux,
    procs: Callable[[], ProcTable],
    mem: str = PLENTY,
) -> Engine:
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
async def client_for(
    engine: Engine, config: Config, bus: EventBus | None = None
) -> AsyncIterator[httpx.AsyncClient]:
    """A client wired to a real app. An async context manager rather than a
    bare generator, so the transport is actually closed when a test finishes.

    `bus` is passed in only by the stream tests, which have to watch
    `subscriber_count` to know when the publisher is actually listening.
    """
    app = create_app(engine=engine, config=config, bus=bus or EventBus())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as c:
        yield c


@pytest.fixture
def tmux() -> FakeTmux:
    """Held by the test rather than reached through `engine.tmux`.

    `Engine.tmux` is typed `Tmux`, so asserting on `.started` or `.killed`
    through it is an attribute error under mypy. Every other test module in
    this project keeps the fake beside the engine for the same reason.
    """
    return FakeTmux(sessions={"vessel": 500})


@pytest.fixture
def engine(config: Config, tmux: FakeTmux) -> Engine:
    return make_engine(config, tmux, procs_from(RUNNING_PS))


@pytest.fixture
async def client(engine: Engine, config: Config) -> AsyncIterator[httpx.AsyncClient]:
    async with client_for(engine, config) as c:
        yield c


async def test_projects_lists_every_folder_with_its_state(client: httpx.AsyncClient) -> None:
    body = (await client.get("/api/projects", headers=HEADERS)).json()
    names = [p["name"] for p in body["projects"]]
    assert names == ["vessel", "vessel-social", "network", "dotted.site"]
    assert body["projects"][0]["state"] == "running"
    assert body["projects"][2]["state"] == "stopped"


async def test_projects_reports_available_memory(client: httpx.AsyncClient) -> None:
    body = (await client.get("/api/projects", headers=HEADERS)).json()
    assert body["memory"]["available_mb"] == 24608


async def test_start_returns_the_new_session(config: Config) -> None:
    # `ScriptedProcs`, not `procs_from`: the table must be EMPTY at the first
    # look or the project derives `detached` before the start, and `start`
    # correctly refuses with `AlreadyRunning`. `ScriptedProcs` says so in its
    # own docstring, and the first draft of this test handed the engine a
    # table where the agent already existed.
    engine = make_engine(config, FakeTmux(), ScriptedProcs("", STARTED_PS))
    async with client_for(engine, config) as c:
        r = await c.post("/api/sessions/network", headers=HEADERS)
    assert r.status_code == 201
    assert r.json()["state"] == "running"


async def test_start_survives_a_process_table_that_lags(config: Config) -> None:
    # The engine's grace window, exercised through the API, because this is
    # the path a person actually taps.
    engine = make_engine(config, FakeTmux(), ScriptedProcs("", "", STARTED_PS))
    async with client_for(engine, config) as c:
        r = await c.post("/api/sessions/network", headers=HEADERS)
    assert r.status_code == 201


async def test_starting_a_running_session_is_a_conflict(client: httpx.AsyncClient) -> None:
    r = await client.post("/api/sessions/vessel", headers=HEADERS)
    assert r.status_code == 409
    assert r.json()["code"] == "already_running"


async def test_a_second_start_in_flight_is_reported_as_locked(
    config: Config, engine: Engine
) -> None:
    # Keyed by the resolved PATH, not the name. Identity is the folder, which
    # is what makes two names for one directory a single lock (#11), and the
    # first draft of this test seeded the name and locked nothing.
    engine._starting.add(str((config.root / "network").resolve()))
    async with client_for(engine, config) as c:
        r = await c.post("/api/sessions/network", headers=HEADERS)
    assert r.status_code == 409
    assert r.json()["code"] == "locked"


async def test_unknown_project_is_a_404_with_a_code(client: httpx.AsyncClient) -> None:
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
    client: httpx.AsyncClient, method: str, path: str
) -> None:
    # A caller who mistyped a folder name must not be told the session is
    # stopped. Two different questions, two different answers.
    r = await client.request(method, path, headers=HEADERS)
    assert r.status_code == 404
    assert r.json()["code"] == "unknown_project"


async def test_a_traversing_name_is_a_404_and_spawns_nothing(
    client: httpx.AsyncClient, engine: Engine, tmux: FakeTmux
) -> None:
    r = await client.post("/api/sessions/..%2f..%2fetc", headers=HEADERS)
    assert r.status_code == 404
    assert tmux.started == []


async def test_hard_memory_refusal_is_507_with_the_numbers(config: Config) -> None:
    engine = make_engine(config, FakeTmux(), procs_from(""), "MemAvailable: 1048576 kB\n")
    async with client_for(engine, config) as c:
        r = await c.post("/api/sessions/network", headers=HEADERS)
    assert r.status_code == 507
    assert r.json()["code"] == "ram_hard"
    assert r.json()["available_mb"] == 1024
    assert r.json()["needed_mb"] == 1536


async def test_soft_memory_needs_an_acknowledgement(config: Config) -> None:
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


async def test_a_soft_refusal_spawns_nothing_on_its_own(config: Config, tmux: FakeTmux) -> None:
    # The server never proceeds on a soft refusal by itself.
    tmux = FakeTmux()
    engine = make_engine(config, tmux, procs_from(""), "MemAvailable: 4194304 kB\n")
    async with client_for(engine, config) as c:
        await c.post("/api/sessions/network", headers=HEADERS)
    assert tmux.started == []


async def test_a_session_that_never_comes_up_is_502(config: Config, tmux: FakeTmux) -> None:
    tmux = FakeTmux()
    tmux.pane_text["network"] = "Error: claude not found\n"
    engine = make_engine(config, tmux, procs_from(""))
    async with client_for(engine, config) as c:
        r = await c.post("/api/sessions/network", headers=HEADERS)
    assert r.status_code == 502
    assert r.json()["code"] == "start_died"
    assert "claude not found" in r.json()["output"]


async def test_delete_begins_a_graceful_stop_and_kills_nothing(
    client: httpx.AsyncClient, engine: Engine, tmux: FakeTmux
) -> None:
    r = await client.delete("/api/sessions/vessel", headers=HEADERS)
    assert r.status_code == 202
    assert r.json()["stopping"] is True
    assert tmux.killed == []


async def test_the_kill_route_kills(
    client: httpx.AsyncClient, engine: Engine, tmux: FakeTmux
) -> None:
    r = await client.post("/api/sessions/vessel/kill", headers=HEADERS)
    assert r.status_code == 200
    assert tmux.killed == ["vessel"]


@pytest.mark.parametrize(
    "query", ["", "?kill=1", "?kill=true", "?force=1", "?kill=1&acknowledged=1"]
)
async def test_delete_never_kills_whatever_the_query_string(
    client: httpx.AsyncClient, engine: Engine, query: str, tmux: FakeTmux
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
    assert tmux.killed == [], "a query parameter reached the kill path"


async def test_kill_without_a_preceding_stop_is_accepted_by_the_api(
    client: httpx.AsyncClient, engine: Engine, tmux: FakeTmux
) -> None:
    """Etiquette is a property of the interface, not of the API."""
    await client.post("/api/sessions/vessel/kill", headers=HEADERS)
    assert tmux.killed == ["vessel"]


async def test_the_kill_route_is_origin_checked_like_every_mutating_route(
    client: httpx.AsyncClient, engine: Engine, tmux: FakeTmux
) -> None:
    """A kill route accidentally treated as a GET exemption would be strictly
    worse than the flag design it replaced."""
    r = await client.post(
        "/api/sessions/vessel/kill",
        headers={**HEADERS, "origin": "http://evil.example"},
    )
    assert r.status_code == 403
    assert tmux.killed == []


async def test_the_protected_project_is_423(root: pathlib.Path, config: Config) -> None:
    from hitchrail.config import Config

    cfg = Config(root=root, sessions_dir=root / ".s", self_project="vessel")
    engine = make_engine(cfg, FakeTmux(sessions={"vessel": 500}), procs_from(RUNNING_PS))
    async with client_for(engine, cfg) as c:
        r = await c.delete("/api/sessions/vessel", headers=HEADERS)
    assert r.status_code == 423
    assert r.json()["code"] == "self_protected"


async def test_logs_returns_the_pane_tail(
    client: httpx.AsyncClient, engine: Engine, tmux: FakeTmux
) -> None:
    tmux.pane_text["vessel"] = "one\ntwo\n"
    r = await client.get("/api/sessions/vessel/logs", headers=HEADERS)
    assert r.json()["text"] == "one\ntwo\n"


async def test_the_url_route_returns_the_link(
    client: httpx.AsyncClient, engine: Engine, tmux: FakeTmux
) -> None:
    tmux.pane_text["vessel"] = "https://claude.ai/code/session_live\n"
    r = await client.get("/api/sessions/vessel/url", headers=HEADERS)
    assert r.status_code == 200
    assert r.json()["url"] == "https://claude.ai/code/session_live"


async def test_the_url_route_reports_pending_rather_than_guessing(
    client: httpx.AsyncClient,
) -> None:
    # The design's url_pending code. Listing never captures a pane, so a link
    # that Claude has not written yet is absent, and this is where a client
    # finds out that absent means "not yet" rather than "never".
    r = await client.get("/api/sessions/vessel/url", headers=HEADERS)
    assert r.status_code == 409
    assert r.json()["code"] == "url_pending"


async def test_creating_a_folder_makes_it_appear(
    client: httpx.AsyncClient, config: Config
) -> None:
    r = await client.post("/api/projects", json={"name": "brand-new"}, headers=HEADERS)
    assert r.status_code == 201
    body = (await client.get("/api/projects", headers=HEADERS)).json()
    assert "brand-new" in [p["name"] for p in body["projects"]]
    assert (config.root / "brand-new").is_dir()


async def test_creating_a_traversing_folder_is_refused(
    client: httpx.AsyncClient, config: Config
) -> None:
    r = await client.post("/api/projects", json={"name": "../evil"}, headers=HEADERS)
    assert r.status_code == 400
    assert r.json()["code"] == "invalid_name"
    assert not (config.root.parent / "evil").exists()


async def test_creating_an_existing_folder_is_a_conflict(client: httpx.AsyncClient) -> None:
    r = await client.post("/api/projects", json={"name": "network"}, headers=HEADERS)
    assert r.status_code == 409
    assert r.json()["code"] == "already_exists"


async def test_a_body_that_is_not_json_is_a_400_not_a_500(client: httpx.AsyncClient) -> None:
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
    client: httpx.AsyncClient, method: str, path: str
) -> None:
    r = await client.request(method, path, headers=HEADERS)
    assert r.status_code >= 400, "this case is meant to be a refusal"
    body = r.text
    assert "Traceback" not in body
    assert ".py" not in body
    assert str(pathlib.Path.home()) not in body


# -- the refusals, which is what a security surface is ----------------------
#
# Every one of these was an uncovered line after the happy paths passed. The
# project rule is that a control with only a happy path test is untested, and
# the phase exit criteria require every code in the envelope to be returned by
# at least one test.


def _unreadable_tmux() -> FakeTmux:
    """A tmux that cannot be run, which is not the same as an empty one."""
    tmux = FakeTmux()

    def gone() -> dict[str, int]:
        raise TmuxUnavailable("tmux: command not found")

    tmux.pane_pids = gone  # type: ignore[method-assign]
    return tmux


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/projects"),
        ("POST", "/api/sessions/vessel"),
        ("DELETE", "/api/sessions/vessel"),
        ("POST", "/api/sessions/vessel/kill"),
        ("GET", "/api/sessions/vessel/logs"),
        ("GET", "/api/sessions/vessel/url"),
    ],
)
async def test_a_machine_that_cannot_be_read_is_503_not_500(
    config: Config, method: str, path: str
) -> None:
    """Phase 4 makes an unreadable machine an error rather than a fifth state,
    precisely so it is never derived as `stopped`. Answering 500 here would
    throw that away and hand the interface a crash instead of "ask again"."""
    engine = make_engine(config, _unreadable_tmux(), procs_from(RUNNING_PS))
    async with client_for(engine, config) as c:
        r = await c.request(method, path, headers=HEADERS)
    assert r.status_code == 503, f"{method} {path} gave {r.status_code}"
    assert r.json()["code"] == "machine_unreadable"


async def test_a_process_table_that_cannot_be_read_is_also_503(
    config: Config,
) -> None:
    """The other half of the same honesty: `ps` failing is not "nothing runs"."""
    engine = make_engine(config, FakeTmux(), failing_procs)
    async with client_for(engine, config) as c:
        r = await c.get("/api/projects", headers=HEADERS)
    assert r.status_code == 503
    assert r.json()["code"] == "machine_unreadable"


async def test_a_root_that_has_gone_away_is_503_not_an_empty_list(
    config: Config, engine: Engine
) -> None:
    """Reporting an empty list would be a lie the interface cannot tell from a
    genuinely empty root, and the operator would think their projects vanished."""
    shutil.rmtree(config.root)
    async with client_for(engine, config) as c:
        r = await c.get("/api/projects", headers=HEADERS)
    assert r.status_code == 503
    assert r.json()["code"] == "root_unavailable"


async def test_starting_the_self_project_is_423_not_500(root: pathlib.Path) -> None:
    """The route where the protection matters most: it is the one that would
    put a SECOND agent in the folder Hitchrail is running in."""
    config = Config(root=root, sessions_dir=root / ".sessions", self_project="vessel")
    engine = make_engine(config, FakeTmux(), procs_from(""))
    async with client_for(engine, config) as c:
        r = await c.post("/api/sessions/vessel", headers=HEADERS)
    assert r.status_code == 423
    assert r.json()["code"] == "self_protected"


@pytest.mark.parametrize("path", ["/api/sessions/vessel", "/api/sessions/vessel/kill"])
async def test_the_self_project_cannot_be_stopped_or_killed(
    root: pathlib.Path, path: str
) -> None:
    config = Config(root=root, sessions_dir=root / ".sessions", self_project="vessel")
    engine = make_engine(config, FakeTmux(sessions={"vessel": 500}), procs_from(RUNNING_PS))
    method = "POST" if path.endswith("/kill") else "DELETE"
    async with client_for(engine, config) as c:
        r = await c.request(method, path, headers=HEADERS)
    assert r.status_code == 423
    assert r.json()["code"] == "self_protected"


@pytest.mark.parametrize(
    ("method", "path", "code"),
    [
        ("DELETE", "/api/sessions/network", "not_running"),
        ("POST", "/api/sessions/network/kill", "not_running"),
        ("GET", "/api/sessions/network/logs", "not_running"),
        ("GET", "/api/sessions/network/url", "not_running"),
    ],
)
async def test_a_real_project_that_is_not_running_is_409_not_404(
    client: httpx.AsyncClient, method: str, path: str, code: str
) -> None:
    """The distinction #47 exists for, and the reason it is not one answer.

    `network` is a real folder that simply is not running, so the fix is to
    start it. `nope` is not a project at all, so the fix is to check the name.
    Collapsing them told a person to start something that was never there.
    """
    r = await client.request(method, path, headers=HEADERS)
    assert r.status_code == 409, f"{method} {path} gave {r.status_code}"
    assert r.json()["code"] == code


async def test_creating_a_folder_under_a_vanished_root_is_503(
    config: Config, engine: Engine
) -> None:
    """Not the caller's fault, and not answered by pretending it worked."""
    shutil.rmtree(config.root)
    async with client_for(engine, config) as c:
        r = await c.post("/api/projects", json={"name": "new"}, headers=HEADERS)
    assert r.status_code == 503
    assert r.json()["code"] == "root_unavailable"


async def test_the_kill_route_404s_an_unknown_project(
    client: httpx.AsyncClient,
) -> None:
    """The destructive route needs the same vocabulary as the gentle one."""
    r = await client.post("/api/sessions/nope/kill", headers=HEADERS)
    assert r.status_code == 404
    assert r.json()["code"] == "unknown_project"


@pytest.mark.parametrize("lines", ["abc", "", "1e3", "nine"])
async def test_a_junk_lines_parameter_falls_back_rather_than_500ing(
    client: httpx.AsyncClient, tmux: FakeTmux, lines: str
) -> None:
    """A query parameter is attacker controlled. `int()` on it raises, and an
    uncaught raise here is a 500 on a route that should simply use its
    default."""
    tmux.pane_text["vessel"] = "hello"
    r = await client.get(f"/api/sessions/vessel/logs?lines={lines}", headers=HEADERS)
    assert r.status_code == 200
    assert r.json()["text"] == "hello"


# -- the lifespan sweeper ---------------------------------------------------


def _coro_name(task: asyncio.Task[object]) -> str | None:
    coro = task.get_coro()
    code = getattr(coro, "cr_code", None)
    return code.co_name if code is not None else None


async def test_the_stop_sweep_outlives_a_failing_tick(
    config: Config, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The loop must survive one bad tick, and must not do it silently.

    If this task ends, no stop expires again for the life of the process and
    the interface shows a timer that never resolves. A bare
    `contextlib.suppress` would survive but make its own failure
    unfalsifiable: expiry could stop working for a whole phase and nothing
    would say so. Asserting only survival passes against that version, so this
    asserts the log too.

    Driven through `app.router.lifespan_context` rather than a client, because
    `httpx.ASGITransport` does not run lifespan at all, and the alternative is
    a fourth runtime dependency against a budget of three.
    """
    ticks: list[int] = []

    class Boom(Engine):
        def expire_stops(self) -> list[str]:
            ticks.append(len(ticks))
            if len(ticks) == 1:
                raise RuntimeError("one bad tick")
            return []

    monkeypatch.setattr(server, "SWEEP_INTERVAL_S", 0.01)
    engine = Boom(
        config=config,
        tmux=FakeTmux(),
        procs_fn=procs_from(""),
        meminfo_fn=lambda: PLENTY,
    )
    app = create_app(engine=engine, config=config, bus=EventBus())
    with caplog.at_level(logging.ERROR, logger="hitchrail.server"):
        async with app.router.lifespan_context(app):
            for _ in range(200):
                if len(ticks) >= 3:
                    break
                await asyncio.sleep(0.01)

    assert len(ticks) >= 3, f"the sweep stopped after the failing tick: {ticks}"
    assert "stop sweep failed" in caplog.text, "the failure was swallowed silently"


async def test_the_sweep_task_is_cancelled_on_shutdown(config: Config) -> None:
    """A task that outlives its app keeps a dead engine alive and keeps
    spawning `ps` after the server is meant to be gone."""
    engine = make_engine(config, FakeTmux(), procs_from(""))
    app = create_app(engine=engine, config=config, bus=EventBus())
    async with app.router.lifespan_context(app):
        # Excluding the CURRENT task is not tidiness. This test function is
        # itself named `..._sweep_task_...`, so a bare `"sweep" in repr(t)`
        # matches the test's own task, which is obviously still running, and
        # the assertion below fails against correct code.
        here = asyncio.current_task()
        # Matched on the CODE OBJECT name, not a substring of a repr. A
        # coroutine's own repr carries no parentheses (those appear only in
        # the Task repr), so `"sweep()" in repr(coro)` matched nothing and the
        # list came back empty, which is a test that cannot fail.
        sweeps = [t for t in asyncio.all_tasks() if t is not here and _coro_name(t) == "sweep"]
    assert sweeps, "the sweep never started"
    assert all(t.done() for t in sweeps), "the sweep outlived the app"


# -- #44: what the integration tier CAN see of the stream -------------------
#
# Not the stream itself. `httpx.ASGITransport` awaits the app to completion and
# accumulates the body, so an endless SSE generator hangs it forever: the
# streaming tests are in `tests/test_live_sse.py`, on a real socket. What
# belongs here is the routing, which does not require reading a body.


async def test_the_stream_is_a_get_because_eventsource_cannot_be_anything_else(
    config: Config, engine: Engine
) -> None:
    """`EventSource` issues a GET and cannot set a header: no `Authorization`,
    no custom anything. A stream behind a POST is one no browser reaches."""
    async with client_for(engine, config) as c:
        assert (await c.post("/api/events", headers=HEADERS)).status_code == 405
