"""#297. `POST` and `GET /api/plugins/update` through the real app, no socket.

The operation is always injected. The stream's framing cannot be tested at
this tier (`server.event_stream` says why); `test_live_sse.py` holds it.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import pathlib
import sys
import threading
from collections.abc import AsyncIterator, Callable

import httpx
import pytest

from conftest import FakeTmux, PluginUpdateGuard, procs_from
from hitchrail import claude_ipc
from hitchrail.claude_ipc import PluginOutcome, PluginsFailed
from hitchrail.config import Config
from hitchrail.engine import Engine
from hitchrail.events import EventBus
from hitchrail.plugin_runs import operation_for
from hitchrail.server import create_app
from support import make_config
from test_plugins import FakeAgent

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


async def test_the_default_operation_is_never_the_real_one_under_test(
    config: Config, no_real_plugin_update: PluginUpdateGuard
) -> None:
    """The autouse guard in conftest: a test that forgot to inject an
    operation fails instead of updating this machine's plugins.

    This is the one test that means to reach it (#310), so it calls
    `expect()` first: without that, the fixture's own teardown would fail
    THIS test for the very firing it exists to prove.

    #310 round 1 review (M4): asserts `no_real_plugin_update.fired` too, not
    only the `internal_error` record it produces. Before this, deleting the
    `guard.fired.append(exc)` line in the fixture's `refuse` left this test
    green, because nothing here read `fired` at all; the record it checks
    comes from `PluginRuns` catching the same `AssertionError`, not from the
    guard's own bookkeeping.
    """
    no_real_plugin_update.expect()
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
    assert no_real_plugin_update.fired, "the guard's own bookkeeping never recorded the firing"


def test_an_unexpected_firing_of_the_guard_fails_loudly() -> None:
    """#310. The refusal above runs on `PluginRuns`'s own daemon thread and
    would otherwise only ever surface as an ordinary `internal_error` record,
    same as any other bug in the operation: a test that forgot
    `plugin_operation=` and asserted only the 202 passed silently. This is
    the decision `no_real_plugin_update`'s own teardown makes, on the same
    `PluginUpdateGuard` object it yields, so it fails if that check is ever
    weakened back to a no-op."""
    guard = PluginUpdateGuard()
    guard.fired.append(AssertionError("a test reached the REAL plugin update"))
    with pytest.raises(AssertionError, match="only failed the run's own daemon thread"):
        guard.check()


def test_expect_lets_the_one_deliberate_test_reach_the_guard() -> None:
    """The escape hatch `test_the_default_operation_is_never_the_real_one_under_test`
    uses: a firing after `expect()` must not raise, or that test could never
    pass."""
    guard = PluginUpdateGuard()
    guard.fired.append(AssertionError("a test reached the REAL plugin update"))
    guard.expect()
    guard.check()


def test_a_forgetful_test_errors_at_teardown_not_silently(pytester: pytest.Pytester) -> None:
    """#310 round 1 review (M4): the two tests above exercise `PluginUpdateGuard`
    directly, never through pytest's own fixture teardown, so deleting either
    `guard.fired.append(exc)` or the fixture's own `guard.check()` after
    `yield` in `tests/conftest.py` left every test in this file green. Proven
    by reverting each of those two lines by hand, with `PYTHONDONTWRITEBYTECODE=1`,
    and watching THIS test go from one error to none.

    Runs a "forgetful" test inside its own isolated pytest session, reusing
    the REAL `no_real_plugin_update` fixture (imported, not reimplemented):
    it swallows the guard's `AssertionError` the way `PluginRuns._run`'s own
    `except Exception` does for real, so nothing escapes the test body, and
    the only way this can still fail the inner run is the fixture's own
    teardown noticing what its bookkeeping recorded.
    """
    pytester.makepyfile(
        """
        from conftest import no_real_plugin_update
        from hitchrail import server


        def test_forgetful(no_real_plugin_update):
            try:
                server.operation_for("agent-binary")(object())
            except Exception:
                pass
        """
    )
    result = pytester.runpytest()
    result.assert_outcomes(passed=1, errors=1)


async def test_the_wired_operation_spawns_the_resolved_binary_not_the_raw_one(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#298 regression at the wiring in `create_app`, not at `update_plugins`
    alone: every other test in this file passes `plugin_operation=`, which is
    what lets the autouse `no_real_plugin_update` fixture refuse the real
    builder everywhere else and would swallow a regression at server.py's own
    `operation_for(config....)` call just as quietly.

    So this test restores the real `operation_for` for itself and replaces
    the one thing under it that would otherwise touch a real process, the
    runner, with the fake one `tests/test_plugins.py` already uses for
    `update_plugins` directly. `FakeAgent` never calls `subprocess.run`, so
    nothing here can run a real plugin update.
    """
    (tmp_path / "vessel").mkdir()
    config = make_config(
        tmp_path, agent_binary="fake-agent", resolved_agent_binary="/abs/fake-agent"
    )
    agent = FakeAgent()
    monkeypatch.setattr("hitchrail.server.operation_for", operation_for)
    # #361 added a keyword-only `handle`, threaded from `create_app` on every
    # call; accepted and ignored here, since `FakeAgent` never spawns a real
    # process for a handle to name.
    monkeypatch.setattr(claude_ipc, "plugin_runner", lambda withhold, **_kw: agent)

    engine = Engine(config=config, tmux=FakeTmux(), procs_fn=procs_from(""))
    app = create_app(engine=engine, config=config, bus=EventBus())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
        assert (await client.post(PATH, headers=HEADERS)).status_code == 202
        for _ in range(100):
            record = (await client.get(PATH, headers=HEADERS)).json()
            if record["state"] != "running":
                break
            await asyncio.sleep(0.01)
        else:
            pytest.fail("the update never finished")

    assert record["state"] == "done"
    assert agent.argvs, "the fake runner was never called"
    assert {argv[0] for argv in agent.argvs} == {"/abs/fake-agent"}


async def test_the_lifespan_kills_an_in_flight_update_on_shutdown(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#361. Ctrl-C on the terminal cannot reach this run: the operation goes
    on `PluginRuns`'s own daemon thread, and Python delivers `KeyboardInterrupt`
    to the main thread only, never a daemon one. Since #299 the child is also
    its own process group leader, so it no longer shares the terminal's group
    either. The server's lifespan, tearing down through `RunningChild`, is the
    only thing left that can end it.

    A real child, not `FakeAgent`: the bug is a real process outliving a real
    shutdown, which a runner that never calls `subprocess.Popen` cannot prove
    either way, the same reasoning `test_plugins.py`'s real-runner tests use.
    It writes its own pid to a marker file the moment the marketplace refresh
    starts, then sleeps five seconds; the test waits for the marker, exits the
    lifespan, and asserts the pid is gone well inside that five seconds.

    Reverting `plugin_updates.handle.kill()` in `server.py`'s lifespan, with
    `PYTHONDONTWRITEBYTECODE=1`, fails this: the marker's pid is still alive
    at the two second bound, because nothing ever signalled it and the fake
    agent's own sleep has not finished yet.
    """
    (tmp_path / "vessel").mkdir()
    marker = tmp_path / "started"
    agent = tmp_path / "claude"
    agent.write_text(
        f"#!{sys.executable}\n"
        "import os, sys, time\n"
        "args = sys.argv[1:]\n"
        "if args[:2] == ['plugin', 'marketplace']:\n"
        f"    with open({str(marker)!r}, 'w') as f:\n"
        "        f.write(str(os.getpid()))\n"
        "    time.sleep(5)\n"
    )
    agent.chmod(0o755)
    config = make_config(tmp_path, agent_binary="fake-agent", resolved_agent_binary=str(agent))
    # The autouse `no_real_plugin_update` guard replaces `operation_for` with
    # a stub that refuses every run; restored here, as
    # `test_the_wired_operation_spawns_the_resolved_binary_not_the_raw_one`
    # does, because this test needs the real wiring from `create_app` through
    # to `plugin_runner`, including the `handle=` #361 added. `plugin_runner`
    # itself is left untouched: replacing it with a fake would prove nothing
    # about a real process outliving a real shutdown.
    monkeypatch.setattr("hitchrail.server.operation_for", operation_for)
    engine = Engine(config=config, tmux=FakeTmux(), procs_fn=procs_from(""))
    app = create_app(engine=engine, config=config, bus=EventBus())

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://localhost"
        ) as client:
            response = await client.post(PATH, headers=HEADERS)
            assert response.status_code == 202
            for _ in range(500):
                if marker.exists():
                    break
                await asyncio.sleep(0.02)
            else:
                raise AssertionError("the fake agent never reached the marketplace refresh")
        pid = int(marker.read_text())
    # The lifespan's `finally` ran on the `async with` above exiting: the kill
    # was sent before this point, and what remains is the daemon thread's own
    # `communicate()` reaping the child once its pipes close, which is not
    # instant but is not the five second sleep either.
    for _ in range(40):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        await asyncio.sleep(0.05)
    else:
        raise AssertionError(f"pid {pid} outlived the lifespan by more than 2 seconds")
