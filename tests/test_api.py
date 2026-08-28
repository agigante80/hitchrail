from __future__ import annotations

import asyncio
import contextlib
import logging
import pathlib
import re
import shutil
from collections.abc import AsyncIterator, Callable

import httpx
import pytest
from starlette.responses import Response

from conftest import FakeClock, FakeTmux, ScriptedProcs, failing_procs, procs_from
from hitchrail import pages, server
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

# Both fields, because the listing reports a proportion as well as a figure.
PLENTY = "MemTotal: 33554432 kB\nMemAvailable: 25198592 kB\n"
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


async def test_every_publisher_puts_the_same_shape_on_the_bus(config: Config) -> None:
    """Two publishers, one wire.

    `Engine._announce` publishes the bare session dict and `create_project`
    once wrapped it in `{"kind": ..., "session": ...}`. The stream serialises
    whatever is on the bus verbatim, so the client read `session.name` as
    undefined, decided it did not know the project, and refetched the whole
    listing: a root scan, a `ps` and a tmux call per connected client per
    folder created. It looked correct because a refetch IS the right answer
    for a new project, which is how it survived review.
    """
    bus = EventBus()
    # `ScriptedProcs` so the start actually succeeds and therefore announces.
    # Three entries, not two: `create_project` calls `engine.get` to build the
    # session it publishes, which consumes a look of its own before the start
    # has taken its pre check.
    engine = make_engine(config, FakeTmux(), ScriptedProcs("", "", STARTED_PS))
    async with client_for(engine, config, bus=bus) as c:
        with bus.subscribe() as queue:
            r = await c.post("/api/projects", json={"name": "brand-new"}, headers=HEADERS)
            assert r.status_code == 201
            # `await`, not `get_nowait`: the bus schedules delivery on the
            # subscriber's loop rather than handing it over inline, so it has
            # not necessarily arrived by the time the POST returns.
            from_create = await asyncio.wait_for(queue.get(), timeout=2)

            r = await c.post("/api/sessions/network", headers=HEADERS)
            assert r.status_code == 201, r.text
            from_engine = await asyncio.wait_for(queue.get(), timeout=2)

    assert from_create.keys() == from_engine.keys(), (from_create, from_engine)
    assert from_create["name"] == "brand-new"


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


# -- the envelope is universal, including the failures routing produces ------


@pytest.mark.parametrize(
    ("method", "path", "status", "code"),
    [
        ("GET", "/nope", 404, "not_found"),
        # `/` is no longer here: #53 gave it the page. `/nope` still covers
        # the routing 404, which is what this test is about.
        ("POST", "/api/events", 405, "method_not_allowed"),
        ("PUT", "/api/projects", 405, "method_not_allowed"),
        ("PATCH", "/api/sessions/vessel", 405, "method_not_allowed"),
        ("GET", "/api/sessions/vessel/kill", 405, "method_not_allowed"),
    ],
)
async def test_routing_failures_use_the_error_envelope_too(
    client: httpx.AsyncClient, method: str, path: str, status: int, code: str
) -> None:
    """The contract said every failure is `{code, message}`, and it held for
    every failure a HANDLER produced and none of the ones routing produced.

    A typo in a path or a wrong method returned `text/plain` saying "Not
    Found", so a client parsing JSON on any non 2xx got a parse error rather
    than a code. The interface meets this on the first mistyped URL.
    """
    r = await client.request(method, path, headers=HEADERS)
    assert r.status_code == status
    assert r.headers["content-type"].startswith("application/json")
    assert r.json()["code"] == code


async def test_a_routing_failure_names_no_path_and_no_traceback(
    client: httpx.AsyncClient, config: Config
) -> None:
    """Rendering Starlette's detail must not start leaking what it knows."""
    r = await client.get("/api/sessions/vessel/nope", headers=HEADERS)
    assert r.status_code == 404
    assert str(config.root) not in r.text
    assert "Traceback" not in r.text


async def test_an_unlisted_http_status_still_gets_an_envelope(
    config: Config, engine: Engine
) -> None:
    """The `error` fallback is a real path, not a dead default.

    Routing raises 404 and 405 today. A handler or a future Starlette raising
    any other `HTTPException` must still produce a code and the right status
    rather than a crash or a `text/plain` body.
    """
    from starlette.exceptions import HTTPException
    from starlette.routing import Route

    async def teapot(request: httpx.Request) -> Response:
        raise HTTPException(status_code=418, detail="short and stout")

    app = create_app(engine=engine, config=config, bus=EventBus())
    app.router.routes.append(Route("/teapot", teapot, methods=["GET"]))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as c:
        r = await c.get("/teapot", headers=HEADERS)
    assert r.status_code == 418
    assert r.headers["content-type"].startswith("application/json")
    assert r.json() == {"code": "error", "message": "short and stout"}


# -- exit criteria that only the API can show -------------------------------


async def test_the_listing_accounts_for_folders_it_cannot_open(
    client: httpx.AsyncClient, config: Config
) -> None:
    """A folder the root holds but Hitchrail cannot use must be ACCOUNTED for,
    not absent. Dropping them silently made a folder called `my app` look like
    one Hitchrail could not see, which is issue #7."""
    (config.root / "my app").mkdir()
    (config.root / ".hidden").mkdir()
    body = (await client.get("/api/projects", headers=HEADERS)).json()

    assert "unsupported" in body and "unsupported_total" in body
    names = {u["name"] for u in body["unsupported"]}
    assert "my app" in names
    assert all(u["reason"] for u in body["unsupported"]), "a reason is the point"
    assert body["unsupported_total"] >= len(body["unsupported"])
    assert "my app" not in {p["name"] for p in body["projects"]}


async def test_a_folder_whose_name_is_not_utf8_does_not_500_the_listing(
    client: httpx.AsyncClient, config: Config
) -> None:
    """The raw name never leaves `discovery`, so the JSON encoder never meets
    a byte it cannot represent. Without that this route is a 500 that any user
    can cause by naming a directory, and the whole page goes with it."""
    try:
        (config.root / b"caf\xe9-broken".decode("latin-1")).mkdir()
    except OSError:  # pragma: no cover - filesystem refused the name
        pytest.skip("this filesystem will not create the name")

    response = await client.get("/api/projects", headers=HEADERS)

    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body["projects"], list)
    assert "\udce9" not in response.text, "a lone surrogate reached the response"


# -- #64: the listing describes the machine, not only the projects ----------


async def test_the_listing_carries_the_root_it_is_listing(
    client: httpx.AsyncClient, config: Config
) -> None:
    """The header names the folder. Two Hitchrails open on one phone are
    otherwise indistinguishable, which is the entire point of that line."""
    body = (await client.get("/api/projects", headers=HEADERS)).json()
    assert body["root"] == str(config.root)


async def test_the_listing_carries_a_memory_total_for_the_proportion(
    client: httpx.AsyncClient,
) -> None:
    body = (await client.get("/api/projects", headers=HEADERS)).json()
    memory = body["memory"]
    assert memory["total_mb"] >= memory["available_mb"] > 0


async def test_an_unreadable_total_leaves_the_rows_intact(
    config: Config, tmux: FakeTmux
) -> None:
    """The failure direction. `total_mb` is a denominator for a bar; a missing
    one must not take the whole listing down with it, because the rows are
    what the person came for.

    A first version raised for both figures and returned 503 for the listing.
    """
    engine = make_engine(
        config, tmux, procs_from(RUNNING_PS), mem="MemAvailable: 25198592 kB\n"
    )
    async with client_for(engine, config) as c:
        response = await c.get("/api/projects", headers=HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["memory"]["total_mb"] is None
    assert body["memory"]["available_mb"] == 24608
    assert [p["name"] for p in body["projects"]], "the rows went with the bar"


async def test_an_unreadable_available_figure_still_refuses(
    config: Config, tmux: FakeTmux
) -> None:
    """The other half of the asymmetry. Available is what the memory guard
    decides on, so guessing it would approve a start on an exhausted machine."""
    engine = make_engine(config, tmux, procs_from(RUNNING_PS), mem="MemTotal: 100 kB\n")
    async with client_for(engine, config) as c:
        response = await c.get("/api/projects", headers=HEADERS)
    assert response.status_code == 503
    assert response.json()["code"] == "machine_unreadable"


async def test_the_page_route_exists_and_is_html(client: httpx.AsyncClient) -> None:
    """`/` used to be a routing 404 and is now the interface. Asserted so the
    envelope test above cannot quietly start covering a route that moved."""
    response = await client.get("/", headers=HEADERS)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "hitchrail" in response.text


# -- #53: the page and its assets, at the tier that does not need a browser --


@pytest.mark.parametrize(
    ("path", "content_type"),
    [("/", "text/html"), ("/app.css", "text/css"), ("/app.js", "javascript")],
)
async def test_the_page_and_its_assets_are_served(
    client: httpx.AsyncClient, path: str, content_type: str
) -> None:
    """Asserted here as well as in the browser tier, because this is the tier
    that runs everywhere: a wheel missing `web/` fails here without needing a
    browser to notice."""
    response = await client.get(path, headers=HEADERS)
    assert response.status_code == 200, path
    assert content_type in response.headers["content-type"], path
    assert response.content, f"{path} was served empty"


@pytest.mark.parametrize(
    "attempt",
    [
        "/../pyproject.toml",
        "/app.css/../../pyproject.toml",
        "/%2e%2e/pyproject.toml",
        "/app.js%00.css",
        "/APP.CSS",
    ],
)
async def test_no_request_reaches_a_file_the_module_did_not_name(
    client: httpx.AsyncClient, attempt: str
) -> None:
    """The security content of the asset routes. They take NO path parameter,
    so traversal is not refused: it is unreachable. `/APP.CSS` is in the list
    because a case insensitive match would be a second way in."""
    response = await client.get(attempt, headers=HEADERS)
    assert response.status_code in (301, 307, 404), f"{attempt} -> {response.status_code}"
    assert "[project]" not in response.text, f"{attempt} served pyproject.toml"


async def test_the_page_is_behind_the_token(tmp_path: pathlib.Path) -> None:
    """#21 argued it and kept it behind the token: `/grant` is the door, and
    the shell stays shut so no future addition to it inherits an exemption."""
    (tmp_path / "vessel").mkdir()
    config = Config(root=tmp_path, sessions_dir=tmp_path / ".s", token="s3cret")
    engine = make_engine(config, FakeTmux(), procs_from(""))
    async with client_for(engine, config) as c:
        for path in ("/", "/app.css", "/app.js"):
            assert (await c.get(path, headers={"host": "localhost"})).status_code == 401, path


# -- #21: the grant route ---------------------------------------------------


def _token_app(tmp_path: pathlib.Path) -> tuple[Engine, Config]:
    (tmp_path / "vessel").mkdir()
    config = Config(root=tmp_path, sessions_dir=tmp_path / ".s", token="s3cret")
    return make_engine(config, FakeTmux(), procs_from("")), config


GRANT_HEADERS = {"host": "localhost", "origin": "http://localhost:8787"}


async def test_every_route_but_the_two_grant_ones_needs_a_token(
    tmp_path: pathlib.Path,
) -> None:
    """Swept off the REAL route table, so a route added later is covered by
    this without anybody remembering to add it."""
    engine, config = _token_app(tmp_path)
    app = create_app(engine=engine, config=config, bus=EventBus())
    checked = 0
    async with client_for(engine, config) as c:
        for route in app.routes:
            path = getattr(route, "path", "")
            methods = getattr(route, "methods", set()) or {"GET"}
            if "{" in path:
                path = path.replace("{name}", "vessel")
            for method in sorted(methods - {"HEAD", "OPTIONS"}):
                if (method, path) in {("GET", "/grant"), ("POST", "/api/grant")}:
                    continue
                r = await c.request(method, path, headers={"host": "localhost"})
                assert r.status_code == 401, f"{method} {path} -> {r.status_code}"
                checked += 1
    assert checked >= 10, f"only {checked} routes were swept"


async def test_the_grant_page_is_served_without_a_token(tmp_path: pathlib.Path) -> None:
    engine, config = _token_app(tmp_path)
    async with client_for(engine, config) as c:
        r = await c.get("/grant", headers={"host": "localhost"})
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


async def test_the_grant_page_names_nothing_on_the_machine(tmp_path: pathlib.Path) -> None:
    """A page reachable without a token must not say what is on the machine.
    Folder names are among the things the token protects."""
    engine, config = _token_app(tmp_path)
    async with client_for(engine, config) as c:
        body = (await c.get("/grant", headers={"host": "localhost"})).text
    # BYTE for byte the file on disk, not two substrings. Substring checks pass
    # for a page that interpolated the host, the port, the user or the agent
    # binary; "this page is static" is the property, and this is it stated.
    assert body == (pages.WEB / "grant.html").read_text()
    assert "vessel" not in body
    assert str(tmp_path) not in body


async def test_the_grant_page_asks_for_no_protected_asset(tmp_path: pathlib.Path) -> None:
    """Self contained, and that is not a style preference.

    Every asset route stays behind the token, so a `<link>` or `<script src>`
    here would be answered 401 and the page would arrive unstyled and inert.
    """
    engine, config = _token_app(tmp_path)
    async with client_for(engine, config) as c:
        body = (await c.get("/grant", headers={"host": "localhost"})).text
    assert "app.css" not in body
    assert "app.js" not in body
    assert "<script src" not in body


async def test_the_grant_trades_a_token_for_a_cookie(tmp_path: pathlib.Path) -> None:
    engine, config = _token_app(tmp_path)
    async with client_for(engine, config) as c:
        r = await c.post("/api/grant", json={"token": "s3cret"}, headers=GRANT_HEADERS)
        assert r.status_code == 200
        # And the cookie it set is the one the middleware accepts.
        listing = await c.get("/api/projects", headers=GRANT_HEADERS)
    assert "hitchrail_token" in r.cookies
    assert listing.status_code == 200


async def test_the_grant_cookie_is_httponly_and_lax(tmp_path: pathlib.Path) -> None:
    """`HttpOnly` so script cannot read it back out, and `SameSite=Lax` rather
    than `Strict` for the reason `TokenMiddleware` documents. Not `Secure`,
    because over plain HTTP on a LAN a `Secure` cookie is never sent and the
    tool silently stops working."""
    engine, config = _token_app(tmp_path)
    async with client_for(engine, config) as c:
        r = await c.post("/api/grant", json={"token": "s3cret"}, headers=GRANT_HEADERS)
    header = r.headers["set-cookie"].lower()
    assert "httponly" in header
    assert "samesite=lax" in header
    assert "secure" not in header


async def test_a_wrong_token_gets_the_same_answer_as_no_token(
    tmp_path: pathlib.Path,
) -> None:
    """The route must not become the oracle the middleware refuses to be."""
    engine, config = _token_app(tmp_path)
    async with client_for(engine, config) as c:
        wrong = await c.post("/api/grant", json={"token": "nope"}, headers=GRANT_HEADERS)
        missing = await c.get("/api/projects", headers=GRANT_HEADERS)
    assert wrong.status_code == missing.status_code == 401
    assert wrong.json() == missing.json()
    # Headers too. A `WWW-Authenticate` on one of the two would be the oracle,
    # and comparing only the body would not see it.
    ignored = {"date", "server", "content-length"}
    assert {k: v for k, v in wrong.headers.items() if k not in ignored} == {
        k: v for k, v in missing.headers.items() if k not in ignored
    }
    assert "hitchrail_token" not in wrong.cookies


async def test_a_wrong_token_is_not_echoed_back(tmp_path: pathlib.Path) -> None:
    engine, config = _token_app(tmp_path)
    async with client_for(engine, config) as c:
        r = await c.post("/api/grant", json={"token": "hunter2-typo"}, headers=GRANT_HEADERS)
    assert "hunter2-typo" not in r.text


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"token": None},
        {"token": 7},
        {"token": ["s3cret"]},
        {"other": "x"},
    ],
)
async def test_a_body_without_a_string_token_is_refused(
    tmp_path: pathlib.Path, body: dict[str, object]
) -> None:
    """A JSON body is attacker shaped input. `token` being a list once meant
    `compare_digest` raised `TypeError` rather than answering False, which is a
    500 where a 400 belongs."""
    engine, config = _token_app(tmp_path)
    async with client_for(engine, config) as c:
        r = await c.post("/api/grant", json=body, headers=GRANT_HEADERS)
    assert r.status_code in (400, 401), body
    assert r.json()["code"] in ("invalid_body", "unauthorized")


async def test_a_grant_on_a_server_with_no_token_is_not_a_way_in(
    client: httpx.AsyncClient,
) -> None:
    """Answering 200 would tell an unauthenticated caller the deployment is
    open, which is a thing worth knowing before attacking it."""
    r = await client.post("/api/grant", json={"token": "anything"}, headers=HEADERS)
    assert r.status_code == 404
    assert "hitchrail_token" not in r.cookies
    # IDENTICAL to what a genuinely unrouted path answers, not merely free of
    # the word "token". A first draft argued this in a comment and then said
    # "no token is configured" in words; a second said "no such route on this
    # server", which no other path answers, so the two were still tellable
    # apart by anyone who compared them.
    unrouted = await client.post("/api/nope", json={}, headers=HEADERS)
    assert unrouted.status_code == 404
    assert r.json() == unrouted.json(), (r.json(), unrouted.json())


@pytest.mark.parametrize("raw", [b'{"token": "\\ud800"}', b'{"token": "a\\udfffb"}'])
async def test_a_token_json_accepts_and_utf8_cannot_encode_is_a_refusal(
    tmp_path: pathlib.Path, raw: bytes
) -> None:
    """Sent as RAW BYTES, because `httpx` cannot encode it either.

    A lone surrogate is a `str` Python's JSON decoder produces happily and
    `.encode("utf-8")` refuses, so it passed the `isinstance` check and then
    raised: an unauthenticated 500 on the one route reachable without a token,
    where every other input gets 401. A 500 among 401s is the oracle this
    route is written not to be.
    """
    engine, config = _token_app(tmp_path)
    async with client_for(engine, config) as c:
        r = await c.post(
            "/api/grant",
            content=raw,
            headers={**GRANT_HEADERS, "content-type": "application/json"},
        )
    assert r.status_code == 401, r.text
    assert "hitchrail_token" not in r.cookies


async def test_the_fragment_grant_cannot_be_performed_by_following_a_link(
    tmp_path: pathlib.Path,
) -> None:
    """A GET that granted would be a link performing a mutation, which is the
    shape the origin check exists to stop, and links are what this flow is made
    of. So `/api/grant` is exempt for POST only, and a GET to it is refused
    like anything else.

    The legacy `?token=` carrier is a separate mechanism that still works on
    any safe method, deliberately, so an already saved link keeps working. It
    is removed before 1.0.
    """
    engine, config = _token_app(tmp_path)
    async with client_for(engine, config) as c:
        r = await c.get("/api/grant", headers=GRANT_HEADERS)
    assert r.status_code == 401
    assert "hitchrail_token" not in r.cookies


def test_the_grant_page_palette_agrees_with_the_stylesheet() -> None:
    """The grant page duplicates the palette because it cannot link to it.

    That duplication is the price of the security boundary, and a price paid
    once and then forgotten is how a page ends up rendering last year's colours
    next to this year's. Every token the grant page defines must have the same
    value in the real stylesheet, in the light palette and in the dark one.
    """
    web = pages.WEB
    grant = web.joinpath("grant.html").read_text()
    sheet = web.joinpath("app.css").read_text()

    def palette(text: str, marker: str) -> dict[str, str]:
        """The first `:root` declaration block at or after `marker`.

        Matched on the marker and not on the whole selector, because the two
        files spell the dark selector differently: the stylesheet guards it as
        `:root:not([data-theme="light"])` so an explicit light choice wins,
        which the grant page has no toggle to need.
        """
        after = text.index(marker)
        opened = text.index("{", text.index(":root", after))
        body = text[opened + 1 : text.index("}", opened)]
        return {
            name.strip(): value.strip()
            for name, _, value in (
                line.partition(":") for line in body.split(";") if "--" in line
            )
        }

    for marker in (":root", "@media (prefers-color-scheme: dark)"):
        here = palette(grant, marker)
        there = palette(sheet, marker)
        assert here, f"no tokens parsed out of the grant page for {marker!r}"
        assert there, f"no tokens parsed out of the stylesheet for {marker!r}"
        for name, value in here.items():
            assert there.get(name) == value, (
                f"{name} is {value} on the grant page and {there.get(name)} in "
                f"the stylesheet, under {marker!r}"
            )


def test_every_file_the_server_serves_exists() -> None:
    """A `FileResponse` on a missing path is a 500 at request time.

    Verified by reading the SOURCE for the names, not by listing the directory,
    so a file that stops being referenced is not mistaken for one that is
    served. `pyproject.toml` ships `src/hitchrail/web/*` as a glob, so the
    packaging follows whatever is here; what it cannot follow is a rename that
    only half happened.
    """
    source = pathlib.Path(pages.__file__).read_text()
    web = pages.WEB
    served = set(re.findall(r'WEB / "([^"]+)"', source))
    served |= {filename for filename, _ in pages.ASSETS.values()}
    assert served, "no served filenames were found in pages.py"
    missing = sorted(name for name in served if not (web / name).is_file())
    assert not missing, missing
