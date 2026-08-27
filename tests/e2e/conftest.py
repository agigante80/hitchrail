"""The browser tier: a real server, a private tmux, and a fake agent.

This is the only tier that can see what the design decides. The stop
escalation is a sequence over time, the phone viewport is a measurement, and
SSE reconnection needs a tab: none of those are a status code, and
`httpx.ASGITransport` cannot even stream, so the integration tier hangs on the
event route rather than failing.

**A fake agent, never the real one.** A test that starts a real Claude costs
money, needs credentials, and cannot run in CI. The shim is a shell script
that prints a marker line and waits, which is enough to be `running`, enough
to have a pane to capture, and enough to be stopped. It exits on `/exit` the
way the real agent does, so the graceful path is genuinely exercised.

**The ASYNC Playwright API, not the sync one.** Playwright's sync API refuses
to run inside an asyncio event loop, and this project sets
`asyncio_mode = "auto"`, so a sync browser test poisons every async test in the
same session: the symptom was 150 unrelated failures and 50 errors in
`pytest_asyncio`'s setup, with each file passing perfectly on its own. Using
the async API keeps this tier consistent with the rest of the suite instead of
carving out an exception for it, and it drops the `pytest-playwright` plugin.

**A private tmux server**, on a short socket path, invoked through
`env -u TMUX`. A bare `tmux` honours `$TMUX` over `$TMUX_TMPDIR`, so a suite
run from inside tmux would otherwise drive the developer's real server. Same
rule as the `live_tmux` tier, and the socket path is short because a unix
socket path is capped near 108 bytes and a pytest tmp_path can exceed it.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
import uvicorn
from playwright.async_api import Page, async_playwright

from hitchrail.config import Config
from hitchrail.engine import Engine
from hitchrail.events import EventBus
from hitchrail.server import create_app

pytestmark = pytest.mark.e2e

STARTUP_TIMEOUT = 15.0

# Prints a line so the log drawer has something to show, then waits for the
# graceful stop the engine sends. `read` returns non zero when the pane closes,
# which ends the loop rather than leaving an orphan.
SHIM = """#!/bin/sh
echo "hitchrail-shim: started as $*"
while read -r line; do
  case "$line" in
    /exit) echo "hitchrail-shim: exiting"; exit 0 ;;
  esac
done
exit 0
"""

# Same, but it ignores the graceful request. Used by the stop escalation tests,
# where the point is what the interface does while nothing is happening.
STUBBORN_SHIM = """#!/bin/sh
echo "hitchrail-shim: started as $*"
while true; do sleep 1; done
"""

# Exits immediately, for the dead start flow.
DYING_SHIM = """#!/bin/sh
echo "hitchrail-shim: started as $*"
echo "hitchrail-shim: nothing to do, exiting"
exit 3
"""


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


class Harness:
    """What every browser test drives. Contract documented in the Phase 6 plan."""

    def __init__(self, root: Path, sock: str) -> None:
        self.root = root
        self._sock = sock
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None
        self.port = free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        self.bus = EventBus()
        self.engine: Engine | None = None
        self._config: Config | None = None
        self._agent = root / "bin" / "agent"

    # -- setup ----------------------------------------------------------

    def _write_shim(self, body: str) -> None:
        self._agent.parent.mkdir(parents=True, exist_ok=True)
        self._agent.write_text(body)
        self._agent.chmod(0o755)

    def seed(
        self,
        running: list[str] | None = None,
        stopped: list[str] | None = None,
        unsupported: list[str] | None = None,
        self_project: str | None = None,
        available_mb: int | None = None,
        stop_timeout: float = 30.0,
        ignores_graceful_stop: bool = False,
        agent_exits_immediately: bool = False,
        token: str | None = None,
    ) -> None:
        """Set the world up BEFORE the page loads."""
        body = SHIM
        if ignores_graceful_stop:
            body = STUBBORN_SHIM
        if agent_exits_immediately:
            body = DYING_SHIM
        self._write_shim(body)

        for name in (running or []) + (stopped or []):
            (self.root / name).mkdir(exist_ok=True)
        for name in unsupported or []:
            (self.root / name).mkdir(exist_ok=True)

        meminfo = f"MemTotal: 33554432 kB\nMemAvailable: {(available_mb or 24608) * 1024} kB\n"
        sessions = self.root / ".sessions"
        sessions.mkdir(exist_ok=True)
        self._config = Config(
            root=self.root,
            sessions_dir=sessions,
            port=self.port,
            tmux_socket=self._sock,
            self_project=self_project,
            agent_binary=str(self._agent),
            stop_timeout=stop_timeout,
            token=token,
        )
        self.engine = Engine(config=self._config, meminfo_fn=lambda: meminfo)
        for name in running or []:
            self.engine.start(name)
        self.start()

    # -- lifecycle ------------------------------------------------------

    def start(self) -> None:
        assert self._config is not None and self.engine is not None
        app = create_app(engine=self.engine, config=self._config, bus=self.bus)
        self._server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="warning")
        )
        self._thread = threading.Thread(target=self._server.run, daemon=True)
        self._thread.start()
        deadline = time.monotonic() + STARTUP_TIMEOUT
        while time.monotonic() < deadline:
            if self._server.started:
                return
            time.sleep(0.05)
        raise RuntimeError("uvicorn did not start")

    def stop_serving(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=10)

    # -- asking the machine, not the page -------------------------------

    def is_running(self, name: str) -> bool:
        assert self.engine is not None
        return self.engine.get(name).state.value == "running"

    def kill(self, name: str) -> None:
        assert self.engine is not None
        self.engine.kill(name)


@pytest.fixture
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Harness]:
    if shutil.which("tmux") is None:  # pragma: no cover - CI installs tmux
        pytest.skip("the browser tier drives a real tmux")

    root = tmp_path_factory.mktemp("hr")
    # A SHORT socket path. A unix socket path is capped near 108 bytes and a
    # pytest tmp_path plus a name can exceed it, which fails as a confusing
    # "No such file or directory" from tmux rather than as a length error.
    sock_dir = tempfile.mkdtemp(prefix="hrsk")
    sock = str(Path(sock_dir) / "s")
    harness = Harness(root, sock)
    try:
        yield harness
    finally:
        harness.stop_serving()
        # Scoped kill, never a bare `tmux kill-server`: this socket only.
        subprocess.run(
            ["tmux", "-S", sock, "kill-server"],
            capture_output=True,
            env={k: v for k, v in os.environ.items() if k != "TMUX"},
            check=False,
        )
        shutil.rmtree(sock_dir, ignore_errors=True)


@pytest.fixture
async def page() -> AsyncIterator[Page]:
    """A browser and a page per test.

    Function scoped deliberately. A session scoped browser would be launched
    once instead of once per test, but pytest-asyncio runs each test on its
    own loop unless every scope is aligned, and a session scoped async fixture
    on a function scoped loop HANGS rather than failing: the symptom is a
    single test that never returns and no error at all.

    The cost is about a second per test. The alternative is a loop scope
    dependency between this file and `pyproject.toml` that breaks the same
    silent way the day somebody changes the default.

    A fresh context per test is the isolation that matters anyway: the theme
    lives in `localStorage`, and a leaked one would make a dark theme test
    pass because the previous test set it.
    """
    async with async_playwright() as driver:
        browser = await driver.chromium.launch()
        context = await browser.new_context()
        try:
            yield await context.new_page()
        finally:
            await context.close()
            await browser.close()
