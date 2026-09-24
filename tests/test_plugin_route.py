"""#297. `POST` and `GET /api/plugins/update` through the real app, no socket.

The operation is always injected. The stream's framing cannot be tested at
this tier (`server.event_stream` says why); `test_live_sse.py` holds it.
"""

from __future__ import annotations

import asyncio
import contextlib
import pathlib
import threading
from collections.abc import AsyncIterator, Callable

import httpx
import pytest

from conftest import FakeTmux, procs_from
from hitchrail.claude_ipc import PluginOutcome, PluginsFailed
from hitchrail.config import Config
from hitchrail.engine import Engine
from hitchrail.events import EventBus
from hitchrail.server import create_app
from support import make_config

pytestmark = pytest.mark.integration

HEADERS = {"host": "localhost", "origin": "http://localhost:8787"}
PATH = "/api/plugins/update"

Report = Callable[[PluginOutcome], None]


class Gate:
    """An operation that blocks until the test lets it finish."""

    def __init__(
        self, outcomes: tuple[PluginOutcome, ...] = (), fail: PluginsFailed | None = None
    ) -> None:
        self.outcomes = outcomes
        self.fail = fail
        self.release = threading.Event()
        self.finished = threading.Event()
        self.calls = 0

    def __call__(self, report: Report) -> list[PluginOutcome]:
        self.calls += 1
        try:
            assert self.release.wait(5), "the test never released the run"
            for o in self.outcomes:
                report(o)
            if self.fail is not None:
                raise self.fail
            return list(self.outcomes)
        finally:
            self.finished.set()


@pytest.fixture
def config(tmp_path: pathlib.Path) -> Config:
    (tmp_path / "vessel").mkdir()
    return make_config(tmp_path)


@contextlib.asynccontextmanager
async def client_for(
    config: Config, operation: Callable[[Report], list[PluginOutcome]]
) -> AsyncIterator[httpx.AsyncClient]:
    engine = Engine(config=config, tmux=FakeTmux(), procs_fn=procs_from(""))
    app = create_app(engine=engine, config=config, bus=EventBus(), plugin_operation=operation)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as c:
        yield c


async def finished(gate: Gate) -> None:
    await asyncio.to_thread(gate.finished.wait, 5)
    # The run's last write happens after the operation returns.
    await asyncio.sleep(0.05)


async def test_before_any_run_the_record_is_idle(config: Config) -> None:
    async with client_for(config, Gate()) as client:
        response = await client.get(PATH, headers=HEADERS)
    assert response.status_code == 200
    assert response.json()["state"] == "idle"
    assert response.json()["counts"] is None


async def test_a_post_starts_a_run_and_answers_at_once_with_the_record(config: Config) -> None:
    gate = Gate((PluginOutcome("a@m", "user", "updated"),))
    async with client_for(config, gate) as client:
        response = await client.post(PATH, headers=HEADERS)
        assert response.status_code == 202
        assert response.json()["state"] == "running"
        # Answered while the operation is still held: the POST did not wait.
        assert not gate.finished.is_set()
        gate.release.set()
        await finished(gate)
        record = (await client.get(PATH, headers=HEADERS)).json()
    assert record["state"] == "done"
    assert record["counts"] == {"updated": 1, "failed": 0, "skipped": 0}
    assert record["outcomes"][0]["plugin"] == "a@m"


async def test_a_second_post_while_running_is_update_in_flight(config: Config) -> None:
    gate = Gate()
    async with client_for(config, gate) as client:
        first = await client.post(PATH, headers=HEADERS)
        second = await client.post(PATH, headers=HEADERS)
        gate.release.set()
        await finished(gate)
    assert first.status_code == 202
    assert second.status_code == 409
    assert second.json()["code"] == "update_in_flight"
    assert set(second.json()) == {"code", "message"}
    assert gate.calls == 1


@pytest.mark.parametrize(
    "code", ["agent_missing", "marketplace_refresh_failed", "plugins_unreadable"]
)
async def test_an_operation_failure_is_in_the_record_with_no_count(
    config: Config, code: str
) -> None:
    gate = Gate(fail=PluginsFailed(code, "words"))  # type: ignore[arg-type]
    async with client_for(config, gate) as client:
        assert (await client.post(PATH, headers=HEADERS)).status_code == 202
        gate.release.set()
        await finished(gate)
        record = (await client.get(PATH, headers=HEADERS)).json()
    assert record["state"] == "failed"
    assert record["code"] == code
    assert record["counts"] is None


async def test_after_a_failure_the_next_post_is_accepted(config: Config) -> None:
    gate = Gate(fail=PluginsFailed("plugins_unreadable", "words"))
    async with client_for(config, gate) as client:
        await client.post(PATH, headers=HEADERS)
        gate.release.set()
        await finished(gate)
        again = await client.post(PATH, headers=HEADERS)
    assert again.status_code == 202


@pytest.mark.parametrize(
    ("headers", "status", "code"),
    [
        ({"host": "localhost"}, 403, "origin_missing"),
        ({"host": "localhost", "origin": "http://evil.example"}, 403, "origin_rejected"),
        ({"host": "evil.example", "origin": "http://localhost:8787"}, 400, "host_rejected"),
    ],
    ids=["no-origin", "foreign-origin", "forged-host"],
)
async def test_the_post_is_refused_before_anything_runs(
    config: Config, headers: dict[str, str], status: int, code: str
) -> None:
    gate = Gate()
    async with client_for(config, gate) as client:
        response = await client.post(PATH, headers=headers)
    assert response.status_code == status
    assert response.json()["code"] == code
    assert gate.calls == 0


async def test_without_the_token_both_methods_are_unauthorized(tmp_path: pathlib.Path) -> None:
    (tmp_path / "vessel").mkdir()
    config = make_config(tmp_path, token="t" * 32)
    gate = Gate()
    async with client_for(config, gate) as client:
        post = await client.post(PATH, headers=HEADERS)
        get = await client.get(PATH, headers=HEADERS)
    assert (post.status_code, post.json()["code"]) == (401, "unauthorized")
    assert (get.status_code, get.json()["code"]) == (401, "unauthorized")
    assert gate.calls == 0


async def test_other_methods_are_not_allowed(config: Config) -> None:
    async with client_for(config, Gate()) as client:
        response = await client.delete(PATH, headers=HEADERS)
    assert response.status_code == 405
    assert response.json()["code"] == "method_not_allowed"


async def test_the_default_operation_is_never_the_real_one_under_test(config: Config) -> None:
    """The autouse guard in conftest: a test that forgot to inject an
    operation fails instead of updating this machine's plugins."""
    engine = Engine(config=config, tmux=FakeTmux(), procs_fn=procs_from(""))
    app = create_app(engine=engine, config=config, bus=EventBus())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
        await client.post(PATH, headers=HEADERS)
        for _ in range(100):
            record = (await client.get(PATH, headers=HEADERS)).json()
            if record["state"] != "running":
                break
            await asyncio.sleep(0.01)
    assert record["state"] == "failed"
    assert record["code"] == "internal_error"
