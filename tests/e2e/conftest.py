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
import contextlib
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

from hitchrail import claude_ipc, discovery
from hitchrail.config import Config
from hitchrail.engine import Engine
from hitchrail.events import EventBus
from hitchrail.roots import Root
from hitchrail.server import create_app
from hitchrail.tmux import Tmux, is_tmux_argv
from support import DEFAULT_LABEL, make_config

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
# An EMPTY input row, the real one, captured from a live session: U+276F then
# U+00A0 and padding.
#
# Added at round 2 of #89's review, when the graceful stop stopped typing into
# panes it does not recognise. Before that this fake painted no input box at
# all and was stopped anyway, which is the shape the project keeps finding:
# the fake was easier to satisfy than the thing it stands in for. A shim that
# draws no box now refuses, correctly, so it draws one.
print("\\x1b[39m\\u276f\\u00a0                     ", flush=True)
"""

# Waits, and exits on the graceful request the engine sends through send-keys.
SHIM_BODY = """
while True:
    line = sys.stdin.readline()
    if line == "":
        # EOF, which a detached pane gives immediately. Not a reason to stop.
        time.sleep(0.2)
        continue
    # Everything up to the last ESC is control input, not text.
    #
    # This fake reads LINES from a pty in canonical mode, so the Escape the
    # stop sequence sends (#89) arrives as a 0x1b byte at the head of the next
    # line and the comparison below never matches. A real agent puts its
    # terminal in raw mode and consumes ESC as a keypress, which is the whole
    # reason the sequence can use it to interrupt a turn.
    #
    # Modelling that, rather than removing the key from the sequence to suit
    # the fake: the fake is the thing that is wrong here.
    line = line.rsplit("\\x1b", 1)[-1]
    if line.strip() == "/exit":
        print("hitchrail-shim: exiting", flush=True)
        sys.exit(0)
"""

# Ignores the graceful request. For the stop escalation tests, where the point
# is what the interface does while nothing is happening.
#
# The SIGINT guard is kept and is no longer what makes this stubborn. It was
# added when the sequence was `C-c C-c` then `/exit`: `C-c` raises SIGINT in a
# pane's foreground process, so a fake that only declined to read `/exit` died
# on the first keystroke, and a stop escalation test found its session already
# stopped with the kill control apparently absent.
#
# #89 replaced those interrupts with `C-u` and `Escape`, neither of which
# signals anything, so today this body is stubborn because it never reads
# stdin at all. The guard stays because nothing says the sequence will not
# carry a signal again, and a fake that dies on one is a confusing failure a
# long way from its cause.
STUBBORN_BODY = """
import signal
signal.signal(signal.SIGINT, signal.SIG_IGN)
while True:
    time.sleep(0.2)
"""

# Paints a bright Claude Code input row and leaves it there.
#
# #89: the graceful stop reads the box before it asks the agent to exit, and
# refuses when what it finds is bright text, because appending an exit command
# to a half typed sentence submits the pair with the operator's authority
# (#91). The ordinary shim paints no input row at all, so without this the
# refusal path has no browser test.
#
# **This models a box that will NOT CLEAR, not a draft**, and the distinction
# is worth stating because the first version of this comment got it wrong. The
# row here is printed output, so `C-u` cannot erase it, whereas a real draft
# lives in the agent's input buffer and `C-u` does erase it. That makes this
# the MODAL case (#88): a bright row that survives the clear. It is also the
# only case the first checkpoint can catch in production, since an ordinary
# draft is gone before the box is ever read.
#
# The row is the real one, captured from a live session: U+276F, U+00A0, then
# text with no dim attribute. `\x1b[39m` in front of it is what the real
# terminal emits and is kept so the fixture is not a tidied version of the
# thing it stands in for.
UNCLEARABLE_BOX_BODY = """
print("\\x1b[39m\\u276f\\u00a0half a sentence", flush=True)
while True:
    time.sleep(0.2)
"""

# Answers a stop request with a PROMPT rather than exiting, then sits on it.
#
# What a real agent does when asked to quit with background work running: it
# opens a confirmation whose entries decide what happens to that work, and
# waits for somebody at the terminal. #101, seen against a real mid task
# session, and the stop sequence produces it by its own doing.
#
# The bright row is the modal's selected entry: prompt ornament, no NBSP, a
# colour rather than the dim placeholder, which is exactly what makes it read
# as "somebody typed here" to `input_is_clear`.
PROMPTS_AFTER_STOP_BODY = """
print("\\x1b[39m\\u276f\\u00a0                     ", flush=True)
while True:
    line = sys.stdin.readline()
    if line == "":
        time.sleep(0.2)
        continue
    # Anything sent at it turns into a question rather than an exit.
    print("Background work is running", flush=True)
    print("\\x1b[39m\\u276f\\x1b[38;5;153m1. Exit and stop tasks", flush=True)
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
    """The FOLDER a test asks for, made impossible to confuse with a real one."""
    return name if name.startswith(E2E_PREFIX) else f"{E2E_PREFIX}{name}"


def e2e_id(name: str, label: str = DEFAULT_LABEL) -> str:
    """The IDENTIFIER for that folder, which is what the API and the DOM use.

    #119 made a project `<root-label>~<folder>`, and this harness labels its
    single root through `support.make_config`. The distinction matters here
    more than anywhere else: this tier creates real directories AND drives real
    routes, so the two names are used within lines of each other.
    """
    return f"{label}~{e2e_name(name)}"


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


class Harness:
    """What every browser test drives. Contract documented in the Phase 6 plan."""

    def __init__(self, root: Path, sock: str) -> None:
        self.root = root
        # #120. The primary root is labelled `main` and every existing test
        # uses only that one. `also_in` on `seed` adds more, which is what the
        # two root tests need: the phase exists for the case where the same
        # folder name appears in two of them.
        self.extra_roots: dict[str, Path] = {}
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
        # Beside the shim rather than inside the root, so it is never mistaken
        # for a project folder by discovery.
        self._agent_config = root.parent / f"{root.name}-bin" / "agent-config.json"
        self._agent_config.parent.mkdir(parents=True, exist_ok=True)
        self._agent_config.write_text("{}")

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
        stale: list[str] | None = None,
        untrusted: list[str] | None = None,
        unsupported: list[str] | None = None,
        self_project: str | None = None,
        available_mb: int | None = None,
        stop_timeout: float = 30.0,
        ignores_graceful_stop: bool = False,
        box_will_not_clear: bool = False,
        prompts_after_stop: bool = False,
        agent_exits_immediately: bool = False,
        token: str | None = None,
        also_in: dict[str, list[str]] | None = None,
    ) -> None:
        """Set the world up BEFORE the page loads.

        `also_in` maps a root LABEL to the projects running in it, and it is
        what the two root tests use. The folders are created under a sibling
        directory named for the label, so the roots are genuinely disjoint and
        the overlap refusal is not what is under test.
        """
        for label, names in (also_in or {}).items():
            extra = self.root.parent / f"root-{label}"
            extra.mkdir(exist_ok=True)
            self.extra_roots[label] = extra
            for name in names:
                (extra / e2e_name(name)).mkdir(exist_ok=True)
        body = SHIM_BODY
        if ignores_graceful_stop:
            body = STUBBORN_BODY
        if box_will_not_clear:
            body = UNCLEARABLE_BOX_BODY
        if prompts_after_stop:
            body = PROMPTS_AFTER_STOP_BODY
        if agent_exits_immediately:
            body = DYING_BODY
        self._write_shim(_SHIM_HEAD.format(python=sys.executable) + body)

        for name in (
            (running or [])
            + (stopped or [])
            + (detached or [])
            + (stale or [])
            + (untrusted or [])
        ):
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

        # Every seeded project is trusted unless a test says otherwise, because
        # a real machine has already accepted the folders it works in: 50 of 69
        # on the development machine. `untrusted` is the fresh folder case,
        # which is the one Hitchrail's own New folder button guarantees (#88).
        #
        # Keyed through `discovery.project_path`, the same call `start` gives
        # `tmux -c`, and NOT by joining the root to the name. The first version
        # of this seeding did the naive join, which is the join the code itself
        # was making, so the fixture agreed with a bug that put the warning on
        # every running row under the default `--root .` and could never have
        # caught it. A fixture built from the production path fails when the
        # production path is wrong, which is the only reason to have one.
        untrusted_names = {e2e_name(n) for n in untrusted or []}
        seeded = (running or []) + (stopped or []) + (detached or []) + (stale or [])
        # #120: every root, not just the primary one. Built as (root, name)
        # pairs so a project in an extra root gets the same trust entry. Before
        # this, projects seeded through `also_in` were absent from the file, so
        # they derived `awaiting_trust` and rendered as `waiting` while their
        # counterparts in the primary root rendered as `running`. The rows were
        # then telling apart by STATE, which is exactly the confusion the root
        # chip exists to remove, in the one picture meant to prove it does.
        trusted_paths = [
            (self.root, n) for n in seeded if e2e_name(n) not in untrusted_names
        ] + [
            (self.extra_roots[label], n)
            for label, names in (also_in or {}).items()
            for n in names
            if e2e_name(n) not in untrusted_names
        ]
        self._agent_config.write_text(
            json.dumps(
                {
                    "projects": {
                        str(discovery.project_path(root, e2e_name(n))): {
                            "hasTrustDialogAccepted": True
                        }
                        for root, n in trusted_paths
                    }
                }
            )
        )

        def build(protect: str | None) -> Config:
            if self.extra_roots:
                return Config(
                    roots=(
                        Root(label=DEFAULT_LABEL, path=self.root.resolve()),
                        *(
                            Root(label=label, path=path.resolve())
                            for label, path in self.extra_roots.items()
                        ),
                    ),
                    sessions_dir=sessions,
                    agent_config_path=self._agent_config,
                    port=self.port,
                    tmux_socket=self._sock,
                    agent_binary=str(self._agent),
                    stop_timeout=stop_timeout,
                    token=token,
                    self_project=protect,
                )
            return make_config(
                self.root,
                sessions_dir=sessions,
                # OURS, never the developer's `~/.claude.json` (#88). That file
                # decides whether a row says "waiting to be trusted", and every
                # folder this harness creates is under a pytest temp path that
                # no real config has ever heard of, so the default would put
                # that warning on every seeded row and the suite's answer would
                # depend on whose home directory ran it.
                agent_config_path=self._agent_config,
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
            opener.start(e2e_id(name))
        for label, names in (also_in or {}).items():
            for name in names:
                opener.start(e2e_id(name, label))

        # `detached` is an agent that outlived its terminal, so it is spawned
        # OUTSIDE tmux rather than by killing a session. Killing a session
        # kills the pane's process group with it, which leaves `stopped` and
        # not `detached`: the state a naive tool gets wrong cannot be faked by
        # breaking the tmux half.
        for name in detached or []:
            self._orphans.append(
                subprocess.Popen(
                    claude_ipc.launch_argv(str(self._agent), e2e_id(name)),
                    cwd=self.root / e2e_name(name),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            )
        if detached:
            time.sleep(0.4)

        # `stale` is a tmux session of ours with no agent in it, so it is
        # created with a command that is NOT the agent. That is the whole of
        # the state: derivation looks for the agent's argv tail under the
        # pane, finds nothing, and the session is alive regardless.
        #
        # Not created by starting an agent and killing it. The pane goes with
        # the process, and the session goes with the pane, which leaves
        # `stopped`. This is the same reason `detached` above is spawned
        # outside tmux rather than faked by breaking the tmux half.
        # The session NAME comes from the adapter, not from an f-string. It
        # applies the configured prefix and the sanitising that makes a name
        # like `dotted.site` addressable, and a hand built `hr-<name>` agrees
        # with it only by luck. When it stopped agreeing, these tests would
        # fail as "expected stale, got stopped", which says nothing about the
        # cause, and leave a session behind on the socket.
        #
        # `check=True`, likewise. A `new-session` that fails silently produces
        # the same opaque failure one step later.
        namer = Tmux(prefix=make_config(self.root).session_prefix, socket=self._sock)
        for name in stale or []:
            subprocess.run(
                [
                    "env",
                    "-u",
                    "TMUX",
                    "tmux",
                    "-S",
                    self._sock,
                    "new-session",
                    "-d",
                    "-s",
                    namer.session_name(e2e_id(name)),
                    "-c",
                    str(self.root / e2e_name(name)),
                    "sleep",
                    "300",
                ],
                check=True,
                capture_output=True,
            )
        if stale:
            time.sleep(0.4)

        self._config = build(e2e_id(self_project) if self_project else None)
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

    def sessions_on_the_socket(self, sock: str) -> list[str]:
        """What the server on this socket still holds, or nothing if it is gone.

        A non zero return is the ordinary success case here: it means no server
        is listening, which is what a kill-server that worked leaves behind.
        """
        result = subprocess.run(
            ["tmux", "-S", sock, "list-sessions", "-F", "#{session_name}"],
            capture_output=True,
            text=True,
            env={k: v for k, v in os.environ.items() if k != "TMUX"},
            check=False,
        )
        return result.stdout.split() if result.returncode == 0 else []

    def processes_still_naming(self, sock: str, grace: float = 0.0) -> list[str]:
        """Any process whose argv mentions this socket, tmux servers included.

        Deliberately NOT excluding tmux here, unlike the agent reaper: a tmux
        server is exactly what this is looking for.

        `grace` because a server told to die is not dead yet, and a scan taken
        the instant `kill-server` returns fails a run over one that was about to
        exit. Returns as soon as nothing is left, so the wait costs nothing on
        the ordinary path.
        """
        deadline = time.monotonic() + grace
        while True:
            rows = self._rows_mentioning(sock, agents_only=False)
            if not rows or time.monotonic() >= deadline:
                return rows
            time.sleep(0.05)

    def end_stragglers(self, rows: list[str]) -> None:
        """Kill what the scan found, by pid, so it cannot outlive the run.

        Matched back to pids through a second `ps` rather than parsed out of the
        rows, because the rows are argv only. Signals nothing whose argv does
        not still name this harness's socket, which is the whole scoping here:
        these are processes only this run could have created.
        """
        if not rows:
            return
        table = subprocess.run(
            ["ps", "-eww", "-o", "pid,args", "--no-headers"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout
        wanted = set(rows)
        for line in table.splitlines():
            pid, _, args = line.strip().partition(" ")
            if args.strip() in wanted and pid.isdigit():
                with contextlib.suppress(OSError):
                    os.kill(int(pid), signal.SIGTERM)

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
            if not self._rows_mentioning(str(self._agent), agents_only=True):
                return
            time.sleep(0.05)
        raise RuntimeError(f"agents from {self._agent} outlived their tmux server")

    @staticmethod
    def _rows_mentioning(needle: str, *, agents_only: bool) -> list[str]:
        """`ps` rows carrying a string, optionally excluding tmux's own.

        The exclusion is #84's shape inside this harness. A tmux server keeps
        the argv of the invocation that started it, and ours names the shim, so
        a plain substring search over `ps` sees the SERVER as an agent. The
        reaper above would then wait its full timeout and report that "agents
        outlived their tmux server", naming the wrong thing entirely: what
        outlived is the server, and there is no agent.

        `is_tmux_argv` is the production predicate, not a copy, so this cannot
        drift from what derivation believes a tmux process looks like.
        """
        table = subprocess.run(
            ["ps", "-eww", "-o", "args", "--no-headers"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout
        return [
            line
            for line in table.splitlines()
            if needle in line and not (agents_only and is_tmux_argv(line))
        ]

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
        # The IDENTIFIER: `launch_argv` puts it last, and #120 made it the
        # qualified form, which is what makes this exact match exact ACROSS
        # roots as well as within one.
        wanted = e2e_id(name)

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
        pid = self.engine.get(e2e_id(name)).pid
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

    def is_running(self, name: str, label: str = DEFAULT_LABEL) -> bool:
        assert self.engine is not None
        return self.engine.get(e2e_id(name, label)).state.value == "running"

    def kill(self, name: str, label: str = DEFAULT_LABEL) -> None:
        assert self.engine is not None
        self.engine.kill(e2e_id(name, label))

    def displayed(self, name: str, label: str | None = None) -> str:
        """What a PERSON reads for this project, not what addresses it.

        #122: the interface shows the FOLDER, and adds the root only when there
        is more than one to tell apart. Pass `label` for the several roots
        case; leave it out for the single root one, which is every test written
        before #120 and which must keep reading exactly as it did.
        """
        folder = e2e_name(name)
        return f"{folder} in {label}" if label else folder

    def project(self, name: str, label: str = DEFAULT_LABEL) -> str:
        """The IDENTIFIER, for a test that needs to select on it.

        #119: the DOM's `data-project` and every API path carry
        `<root-label>~<folder>`, so this returns the qualified form. A test
        that wants the FOLDER, to create it or to look at it on disk, calls
        `e2e_name` instead. Keeping the distinction in one place here is what
        stopped the migration being a per selector edit.
        """
        return e2e_id(name, label)


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
        killed = subprocess.run(
            ["tmux", "-S", sock, "kill-server"],
            capture_output=True,
            text=True,
            env={k: v for k, v in os.environ.items() if k != "TMUX"},
            check=False,
        )
        harness.wait_until_the_agents_are_gone()
        # #99. A tmux server outlived a green run and accumulated for hours,
        # found by looking at `ps` for an unrelated reason, because nothing
        # here looked. `tests/test_live_tmux.py` learned this already and its
        # `PrivateTmux.close` says why the order matters: after the socket goes
        # `list-sessions` cannot connect and returns nothing, so an assertion
        # made then is vacuously true.
        #
        # Asked of the SERVER, before the socket is removed.
        survivors = harness.sessions_on_the_socket(sock)
        # And of `ps`, which is the check that would actually have caught the
        # observed leak: that server's socket directory was already gone, so
        # nothing could address it, while its argv still named the socket. A
        # session created between the kill above and this line lands here too,
        # which is the suspected mechanism and what #67 may also be.
        #
        # BEFORE the socket directory is removed, and with a grace period.
        # Scanning after the `rmtree` made teardown ITSELF the thing that put
        # the server beyond reach, so the assertion announced the accumulation
        # it exists to stop while doing nothing about it. Scanning with no wait
        # failed a passing run over a server milliseconds from exiting.
        stragglers = harness.processes_still_naming(sock, grace=3.0)
        # Reported AND ended. A check that only complains leaves the next run to
        # meet the same server, which is how one of these reached 3.4 hours.
        harness.end_stragglers(stragglers)
        shutil.rmtree(sock_dir, ignore_errors=True)
        # FIRST of the three, because a serving thread that would not stop is
        # the failure most likely to have caused the other two, and an assert
        # that fires swallows every assert after it. An earlier version of this
        # comment said "last, so it is reported rather than swallowed", which
        # was true when it was the only one.
        assert harness.stopped_cleanly, "the server thread did not stop"
        assert survivors == [], f"sessions outlived the kill-server: {survivors}"
        assert stragglers == [], (
            f"a tmux server outlived teardown and is now unreachable "
            f"(its socket is gone): {stragglers}. kill-server said "
            f"{killed.returncode}: {killed.stderr.strip()!r}"
        )


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
