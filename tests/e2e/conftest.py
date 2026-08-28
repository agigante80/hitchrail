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

**Project names are prefixed and must stay that way.** This tier reads the
REAL process table, which is the point: it is the only tier that can see what
the machine actually does. That means a test project called `hitchrail` or
`forge-kit` collides with whatever the developer is genuinely running, and
`_find_detached` matches on the argv tail, so a real `claude ... --remote-control
forge-kit` is indistinguishable from a seeded one. Verified on this machine:
eight real sessions were running, three of them sharing a name with a name
these tests used. `e2e_names` below is the guard.

**A private tmux server**, on a short socket path, invoked through
`env -u TMUX`. A bare `tmux` honours `$TMUX` over `$TMUX_TMPDIR`, so a suite
run from inside tmux would otherwise drive the developer's real server. Same
rule as the `live_tmux` tier, and the socket path is short because a unix
socket path is capped near 108 bytes and a pytest tmp_path can exceed it.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
import uvicorn
from playwright.async_api import Page, async_playwright

from hitchrail import claude_ipc
from hitchrail.config import Config
from hitchrail.engine import Engine
from hitchrail.events import EventBus
from hitchrail.server import create_app

pytestmark = pytest.mark.e2e

STARTUP_TIMEOUT = 15.0

# Prints a line so the log drawer has something to show, then waits for the
# graceful stop the engine sends. `read` returns non zero when the pane closes,
# which ends the loop rather than leaving an orphan.
# A PYTHON shim, not a shell one, and that is not a preference.
#
# A detached tmux pane has no client attached, so a `read` in `/bin/sh` returns
# EOF immediately rather than blocking, and a plain `while read` loop exits at
# once. The symptom is the worst kind: the pane still shows the line it
# printed and the session still exists, so a start looks like it worked while
# the process table has no agent in it. That reads as a broken derivation
# rather than a broken fake, and it cost an hour.
#
# Python is already a dependency here, `sys.stdin.readline()` returning "" on
# EOF is documented rather than shell dependent, and the loop is explicit
# about what it does on each outcome.
_SHIM_HEAD = """#!{python}
import sys, time
print("hitchrail-shim: started as " + " ".join(sys.argv[1:]), flush=True)
"""

# Waits, and exits on the graceful request the engine sends through send-keys.
SHIM_BODY = """
while True:
    line = sys.stdin.readline()
    if line == "":
        # EOF, which a detached pane gives immediately. Not a reason to stop.
        time.sleep(0.2)
        continue
    if line.strip() == "/exit":
        print("hitchrail-shim: exiting", flush=True)
        sys.exit(0)
"""

# Ignores the graceful request. For the stop escalation tests, where the point
# is what the interface does while nothing is happening.
#
# It has to ignore SIGINT, not just `/exit`. The graceful stop is `C-c C-c`
# and then `/exit`, sent through `send-keys`, and `C-c` in a pane raises
# SIGINT in the foreground process: a "stubborn" fake that only declines to
# read `/exit` still dies on the first keystroke. The symptom was a stop
# escalation test whose session had already stopped, so the dialog closed
# before the assertion ran and the kill control looked absent when it was
# there.
STUBBORN_BODY = """
import signal
signal.signal(signal.SIGINT, signal.SIG_IGN)
while True:
    time.sleep(0.2)
"""

# Exits at once, for the dead start flow.
DYING_BODY = """
print("hitchrail-shim: nothing to do, exiting", flush=True)
sys.exit(3)
"""


# Prefixed so a seeded project can never be a real one. `hr` is short because
# the name reaches a tmux session name and a filesystem path.
E2E_PREFIX = "hrx-"


def e2e_name(name: str) -> str:
    """The name a test asks for, made impossible to confuse with a real one."""
    return name if name.startswith(E2E_PREFIX) else f"{E2E_PREFIX}{name}"


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
        self._loop: asyncio.AbstractEventLoop | None = None
        self._meminfo = ""
        self.stopped_cleanly = True
        self.port = free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        self.bus = EventBus()
        self.engine: Engine | None = None
        self._config: Config | None = None
        self._orphans: list[subprocess.Popen[bytes]] = []
        # OUTSIDE the project root. `discovery.scan` lists every direct
        # subfolder, so a `bin/` beside the projects becomes a project: the
        # tab counts read one too high and every count assertion is off by the
        # harness rather than by the code.
        self._agent = root.parent / f"{root.name}-bin" / "agent"

    # -- setup ----------------------------------------------------------

    def _write_shim(self, body: str) -> None:
        self._agent.parent.mkdir(parents=True, exist_ok=True)
        self._agent.write_text(body)
        self._agent.chmod(0o755)

    def seed(
        self,
        running: list[str] | None = None,
        stopped: list[str] | None = None,
        detached: list[str] | None = None,
        unsupported: list[str] | None = None,
        self_project: str | None = None,
        available_mb: int | None = None,
        stop_timeout: float = 30.0,
        ignores_graceful_stop: bool = False,
        agent_exits_immediately: bool = False,
        token: str | None = None,
    ) -> None:
        """Set the world up BEFORE the page loads."""
        body = SHIM_BODY
        if ignores_graceful_stop:
            body = STUBBORN_BODY
        if agent_exits_immediately:
            body = DYING_BODY
        self._write_shim(_SHIM_HEAD.format(python=sys.executable) + body)

        for name in (running or []) + (stopped or []) + (detached or []):
            (self.root / e2e_name(name)).mkdir(exist_ok=True)
        # NOT prefixed: an unsupported folder is one Hitchrail cannot use, so
        # its name is the point and it never becomes a session.
        for name in unsupported or []:
            (self.root / name).mkdir(exist_ok=True)

        self._meminfo = (
            f"MemTotal: 33554432 kB\nMemAvailable: {(available_mb or 24608) * 1024} kB\n"
        )
        sessions = self.root / ".sessions"
        sessions.mkdir(exist_ok=True)

        def build(protect: str | None) -> Config:
            return Config(
                root=self.root,
                sessions_dir=sessions,
                port=self.port,
                tmux_socket=self._sock,
                agent_binary=str(self._agent),
                stop_timeout=stop_timeout,
                token=token,
                self_project=protect,
            )

        # Seeding runs through an engine with NO self_project and PLENTY of
        # memory, and the real settings are applied afterwards.
        #
        # Both are the same argument: `start` refuses the protected project and
        # refuses a start under the hard floor, which are the behaviours #55
        # and #56 test, so a harness that applied them first could never seed
        # the rows those tests are about. Setting up the world is not the same
        # act as exercising the guards on it.
        plenty = "MemTotal: 33554432 kB\nMemAvailable: 25198592 kB\n"
        opener = Engine(config=build(None), meminfo_fn=lambda: plenty)
        for name in running or []:
            opener.start(e2e_name(name))

        # `detached` is an agent that outlived its terminal, so it is spawned
        # OUTSIDE tmux rather than by killing a session. Killing a session
        # kills the pane's process group with it, which leaves `stopped` and
        # not `detached`: the state a naive tool gets wrong cannot be faked by
        # breaking the tmux half.
        for name in detached or []:
            self._orphans.append(
                subprocess.Popen(
                    claude_ipc.launch_argv(str(self._agent), e2e_name(name)),
                    cwd=self.root / e2e_name(name),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            )
        if detached:
            time.sleep(0.4)

        self._config = build(e2e_name(self_project) if self_project else None)
        # Read through the attribute rather than closed over, so `break_machine`
        # can make the reading unreadable mid test.
        self.engine = Engine(config=self._config, meminfo_fn=lambda: self._meminfo)
        self.start()

    # -- lifecycle ------------------------------------------------------

    def start(self) -> None:
        assert self._config is not None and self.engine is not None
        app = create_app(engine=self.engine, config=self._config, bus=self.bus)
        self._server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="warning")
        )
        # Our own loop rather than `Server.run`'s, because `drop_connections`
        # needs a handle to schedule onto from this thread.
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        deadline = time.monotonic() + STARTUP_TIMEOUT
        while time.monotonic() < deadline:
            if self._server.started:
                return
            time.sleep(0.05)
        raise RuntimeError("uvicorn did not start")

    def _serve(self) -> None:
        assert self._loop is not None and self._server is not None
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._server.serve())

    def reap_orphans(self) -> None:
        """Anything spawned outside tmux is ours to clean up.

        Nothing else will: it has no pane, so no `kill-server` reaches it, and
        a leaked one keeps matching the argv tail for every later test on this
        machine.
        """
        for orphan in self._orphans:
            orphan.terminate()
            try:
                orphan.wait(timeout=5)
            except subprocess.TimeoutExpired:  # pragma: no cover - a stuck fake
                orphan.kill()
        self._orphans.clear()

    def _abort_connections(self) -> int:
        """Abort every live connection's transport, from the serving loop.

        Nothing gentler reaches an SSE stream. `should_exit` waits for open
        connections and a stream never closes on its own. `force_exit` skips
        that wait and still does not help, because `Server.shutdown` first
        gathers `wait_closed()` on the asyncio servers and since Python 3.12
        that waits for the connections too. uvicorn's own
        `connection.shutdown()` is no better: for a response still in flight it
        only clears `keep_alive`. And the browser notices none of it, because
        this server is a THREAD in a live process, so an accepted socket nobody
        closed stays open (measured: readyState still 1 after twelve seconds).
        """
        server, loop = self._server, self._loop
        if server is None or loop is None or not loop.is_running():
            return 0

        cut = 0

        def cut_and_signal() -> None:
            nonlocal cut
            for connection in list(server.server_state.connections):
                transport = getattr(connection, "transport", None)
                if transport is not None:
                    transport.abort()
                    cut += 1
            done.set()

        done = threading.Event()
        loop.call_soon_threadsafe(cut_and_signal)
        done.wait(timeout=5)
        return cut

    def drop_connections(self) -> None:
        """Cut every live connection, leaving the server up.

        What a phone losing its network looks like from the page: the stream
        dies, and the server is still there to reconnect to.
        """
        # `server_state.connections` and `.transport` are uvicorn internals. If
        # either is renamed this becomes a silent no op and the two tests that
        # depend on it fail as opaque timeouts, so it says so itself.
        cut = self._abort_connections()
        assert cut > 0, (
            "no connection was cut. Either the serving loop is not running, or "
            "`server_state.connections` and `.transport` have moved in uvicorn. "
            "Without this the tests that depend on it fail as opaque timeouts."
        )

    def stop_serving(self) -> None:
        """Teardown, and neither exit flag can do it alone.

        Measured before this loop existed: the join hit its full ten second
        timeout on EVERY browser test and the loop was still running
        afterwards, because `Server.shutdown` gathers `wait_closed()` on the
        asyncio servers and since Python 3.12 that waits for the open
        connections too, `force_exit` or not. Every test that loaded the page
        leaves an SSE stream open, so every teardown paid ten seconds.

        Flags first, then cut, then cut again until the thread is gone. One cut
        is not enough: the page's `EventSource` reconnects the instant its
        connection dies, and a connection accepted between the abort and the
        listener closing puts `wait_closed` back where it started.
        """
        if self._server is not None:
            self._server.should_exit = True
            self._server.force_exit = True
        if self._thread is not None:
            deadline = time.monotonic() + 10
            while self._thread.is_alive() and time.monotonic() < deadline:
                self._abort_connections()
                self._thread.join(timeout=0.2)
            # RECORDED, not raised. This is the first thing the fixture's
            # finalizer calls, and raising here would skip `reap_orphans`, the
            # scoped `kill-server` and the wait for the agents, leaking a tmux
            # server and processes under the shared `hrx-` prefix onto the
            # machine and poisoning every test after this one. The fixture
            # raises once it has cleaned up.
            self.stopped_cleanly = not self._thread.is_alive()
        if self._loop is not None and self.stopped_cleanly:
            # Only when the thread actually stopped. If it did not, the loop is
            # still RUNNING, and both statements below raise on a running loop:
            # `run_until_complete` with "This event loop is already running" and
            # `close` with "Cannot close a running event loop". That raise came
            # straight back out of the fixture's finally and skipped the tmux
            # cleanup, which is the leak recording `stopped_cleanly` instead of
            # asserting was meant to prevent. A leaked loop on a path that is
            # already failing is the cheaper of the two.
            #
            # Cancel what force exit left behind before closing. Aborting the
            # connections cuts uvicorn's shutdown short, so the lifespan task
            # and sse-starlette's shutdown watcher are still pending; closing
            # the loop under them logs "Task was destroyed but it is pending"
            # once per test, which is noise that trains people to ignore
            # asyncio errors in this suite.
            pending = asyncio.all_tasks(self._loop)
            for task in pending:
                task.cancel()
            if pending:
                self._loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            # The fixture is function scoped, so an unclosed loop leaks its
            # epoll and self pipe descriptors once per browser test.
            self._loop.close()
            self._loop = None

    # -- asking the machine, not the page -------------------------------

    def wait_until_the_agents_are_gone(self, timeout: float = 15.0) -> None:
        """Block until no process still runs THIS harness's agent shim.

        `tmux kill-server` returns as soon as the server is told, and the
        agents it owned are then leaving rather than gone. Every browser test
        seeds under the same `hrx-` prefix, so an agent still exiting is seen
        by the NEXT test's derivation and reported as `running`, which fails
        its seed with `AlreadyRunning`. This was invisible while teardown
        stalled for ten seconds on the join: the stall was doing this job by
        accident, and fixing the stall is what surfaced it.

        Matched on the shim's own path, which is unique per harness, rather
        than on the session prefix, which is not.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            table = subprocess.run(
                ["ps", "-eww", "-o", "args", "--no-headers"],
                capture_output=True,
                text=True,
                check=False,
            ).stdout
            if str(self._agent) not in table:
                return
            time.sleep(0.05)
        raise RuntimeError(f"agents from {self._agent} outlived their tmux server")

    def kill_the_agent_quietly(self, name: str) -> None:
        """Kill the agent process, out of band, so NOTHING is announced.

        `Engine._announce` fires on start, stop, kill and the stop timer. An
        agent that exits on its own fires none of them, so a listing is the
        only thing that can ever report it. That is why a listing must not be
        overruled by an event older than itself, and this is how a test gets a
        change the stream cannot carry.

        The pane goes with the process, and the window, session and server go
        with the pane, so this derives as `stopped` rather than `stale`. That
        is the tmux behaviour `remain-on-exit` defeats during a start and which
        is cleared once one succeeds.
        """
        # EXACT, on argv's last element. A substring test would match
        # `hrx-vessel-social` for `vessel`, which is the same prefix footgun
        # `.claude/CLAUDE.md` documents for tmux target specs, reintroduced in
        # the harness against a different tool. `claude_ipc.launch_argv` puts
        # the project last, so the comparison has somewhere exact to stand.
        wanted = e2e_name(name)

        def agent_pids() -> list[int]:
            table = subprocess.run(
                ["ps", "-eww", "-o", "pid,args", "--no-headers"],
                capture_output=True,
                text=True,
                check=False,
            ).stdout
            found = []
            for line in table.splitlines():
                fields = line.split()
                if len(fields) < 2 or fields[-1] != wanted:
                    continue
                if str(self._agent) not in line or "tmux" in line:
                    continue
                found.append(int(fields[0]))
            return found

        pids = agent_pids()
        assert pids, f"no agent process for {name}"
        for pid in pids:
            os.kill(pid, signal.SIGKILL)

        # And WAIT for it. The caller's next act is a single listing, with
        # nothing to re-fetch it afterwards, so a process still in the `ps`
        # snapshot derives `detached` and the test fails as an opaque timeout
        # rather than as "the kill had not landed".
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if not agent_pids():
                return
            time.sleep(0.02)
        raise RuntimeError(f"the agent for {name} survived SIGKILL")

    def publish_link(self, name: str, bridge_id: str = "session_01TestBridgeId") -> str:
        """Write the session file Claude Code writes, for a session we started.

        Hitchrail does not generate the link. `claude_ipc.bridge_url` reads
        `<sessions_dir>/<pid>.json` and takes `bridgeSessionId` verbatim,
        including its `session_` prefix, so writing that file is how a test
        gets a session with a link without a real agent behind it.

        The real file carries about twenty keys, confirmed against a live
        session: `cwd`, `tmux`, `status`, `messagingSocketPath` and the rest.
        Only `bridgeSessionId` is read here, and pretending otherwise would
        make this fixture claim to know more of an undocumented format than
        the code it feeds.
        """
        assert self.engine is not None and self._config is not None
        pid = self.engine.get(e2e_name(name)).pid
        assert pid is not None, f"{name} is not running, so it has no session file"
        path = self._config.sessions_dir / f"{pid}.json"
        path.write_text(json.dumps({"bridgeSessionId": bridge_id, "pid": pid}))
        return f"https://claude.ai/code/{bridge_id}"

    def break_machine(self) -> None:
        """Make the machine unreadable, through the seam the engine injects.

        The memory reading, because it is the one external surface a test can
        corrupt without corrupting the developer's actual machine: an
        unparseable `meminfo` is `MachineUnreadable` at `engine.py:185`, which
        is a 503 `machine_unreadable` on the listing. `ps` and tmux reach the
        same state and neither can be broken from here without breaking them
        for real.
        """
        self._meminfo = "not a meminfo"

    def heal_machine(self) -> None:
        self._meminfo = "MemTotal: 33554432 kB\nMemAvailable: 25198592 kB\n"

    def is_running(self, name: str) -> bool:
        assert self.engine is not None
        return self.engine.get(e2e_name(name)).state.value == "running"

    def kill(self, name: str) -> None:
        assert self.engine is not None
        self.engine.kill(e2e_name(name))

    def project(self, name: str) -> str:
        """The prefixed name, for a test that needs to select on it."""
        return e2e_name(name)


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
        harness.reap_orphans()
        # Scoped kill, never a bare `tmux kill-server`: this socket only.
        subprocess.run(
            ["tmux", "-S", sock, "kill-server"],
            capture_output=True,
            env={k: v for k, v in os.environ.items() if k != "TMUX"},
            check=False,
        )
        harness.wait_until_the_agents_are_gone()
        shutil.rmtree(sock_dir, ignore_errors=True)
        # Last, so a server that would not stop is reported rather than
        # swallowed, and reported only once everything else has been released.
        assert harness.stopped_cleanly, "the server thread did not stop"


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
