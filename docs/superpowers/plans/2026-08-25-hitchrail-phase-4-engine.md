# Hitchrail Phase 4: The Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Derive session state from the operating system and run the session lifecycle, with no HTTP anywhere, so that a Python session can start, watch, gracefully stop and kill a real Claude before a web server exists.

**Architecture:** No database and no session registry. Every read takes one snapshot of the process table and one snapshot of tmux, and answers every project from those two. The only state the engine holds is the fact that a graceful stop is in flight, which lives in memory and is deliberately not persisted.

**Tech Stack:** Python 3.11+, stdlib `threading`, `asyncio` (the event bus only). No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-25-hitchrail-design.md` sections 4.1 and 4.3

**Roadmap:** `docs/roadmap.md` (this plan is Phase 4 of 7)

## Global Constraints

Copied verbatim from the spec. Every task inherits these.

- **Python `>=3.11`.** CI runs 3.11, 3.12 and 3.13. All blocking.
- **Exactly three runtime dependencies:** `starlette>=1.6,<2`, `uvicorn>=0.52,<1`, `sse-starlette>=3.4,<4`. A fourth requires a written justification in the pull request.
- **No shell, ever.** Every subprocess call takes an argument list. `shell=True` is forbidden with no exceptions.
- **The engine layer must not import** `hitchrail.server`, `hitchrail.cli`, `starlette`, `uvicorn` or `sse_starlette`. Both modules in this phase are in that layer.
- **Never a bare `tmux kill-server`.** Never kill a session whose name does not carry the configured prefix.
- **`claude_ipc.py` is quarantine.** No Claude Code knowledge leaves it, strings included.
- **The root stays lean.** Every tool is configured from `pyproject.toml`.
- **No em dashes or en dashes** anywhere, including commit messages. A hook enforces it.
- Defaults: session prefix `hr-`, stop timeout 30 seconds, hard memory floor 1536 MB, soft floor 3072 MB, per session estimate 1536 MB.
- Tests are hermetic. No test touches a real tmux server, a real Claude process, the network, or the filesystem outside a temporary root.

## Phase 4 tickets, in dependency order

| Ticket | Task | Blocks |
|---|---|---|
| #39 | 11, the event bus | nothing here; Phase 5's SSE route consumes it |
| #40 | 12, four states from two scans | #41, #42 |
| #41 | 13, starting, the lock, the grace window | #42 |
| #42 | 14, the stop sequence, expiry, log tail | |
| #34 | property based tests | best early, so #40 is written with the tool |
| #36 | three untested refusals and a dead tmux guard | independent |

#40 is large and deliberately not split: the four states come from one
algorithm run in two directions, and shipping half of it means shipping a
derivation that is knowingly wrong about `detached`, which is the state the
whole design exists to get right.

**Because it is not split, its tests carry the weight the second reviewer
would have**, and #40 spells them out: every cell of the state matrix rather
than the diagonal, both directions of orphan attribution rather than one, and
the coupling to `launch_argv`'s argument ORDER that would otherwise break
`detached` silently. That last one is worth reading before implementing:
`_find_detached` matches on the project name being the LAST element of the
command line, so a flag appended after it makes every detached agent invisible
with no other test failing. The fake process table builds its `args` by calling
`launch_argv` for exactly that reason.

#42 carries the phase's runtime proof, because a real Claude session cannot be
started, watched, stopped and killed until stop and kill exist.

## Phase 4 file structure

| File | Responsibility |
|---|---|
| `src/hitchrail/events.py` | a lossy in process fan out, so a stalled tab cannot slow the machine |
| `src/hitchrail/engine.py` | state derivation and the session lifecycle |
| `tests/conftest.py` | the fakes every engine test shares |

The event bus comes first because the engine publishes to it. It is a leaf with
no dependencies, so it could sit anywhere; putting it immediately before its
only consumer is what makes the phase readable in order.

## Corrections found when validating this plan against the built adapters

This plan was written before Phase 3 existed. Two of its assumptions no longer
match the adapters it consumes, and both are recorded here because the snippets
below still show the old shape.

### 1. `_look` must consult `ProcTable.ok`, or a failed `ps` reads as idle

`_look()` calls `self._procs_fn()` and uses the table without asking whether
the call succeeded. `ProcTable.ok` was added in #24, after this plan was
written, precisely because an empty table is ambiguous.

If `ps` fails the table is empty, so `first_matching_in_tree` finds nothing and
the orphan scan finds nothing, and **every running agent derives as `stale` or
`stopped`**. The interface then shows agents as not running while they are,
which is a guard failing open and is what `docs/tech-guidelines.md` control 7
forbids.

The design answers it: "If Hitchrail cannot determine a session's state, it
says so rather than guessing." An unreadable machine is an ERROR, not a state.
Raise, and let Phase 5 render it. **Do not add a fifth state**: the design is
explicit that the table has four and that the in flight stop is an overlay
rather than a fifth member.

The tmux side is NOT the same and must not be conflated: `pane_pids()`
returning `{}` when no server is running is legitimately "no sessions", because
that is the ordinary state of a machine with nothing started. #40 has a test
for each half so the two cannot be merged later.

### 2. `session_url` returns provenance, not a bare string

Task 14's interface says `Engine.session_url(name) -> str | None` and one of
its tests asserts a bare URL string. `claude_ipc.session_url` returns
`SessionUrl(url, source)` where source is `bridge` or `scraped`, decided in
#29 because a scraped URL can be scrollback from a session that ended hours
ago: syntactically perfect and semantically stale. #29 records that the
provenance reaches the API, so `Session` carries it and `as_dict()` exposes it.

## The three things this phase gets right that a first draft does not

**Two subprocess calls per list, not two per project.** Phase 3 gave `Tmux` a
`pane_pids()` that answers every session at once. The engine takes one process
table snapshot and one tmux snapshot, then derives every project from those.
The shape that asks tmux per project is a subprocess spawn per row, and the
design draws fifty rows.

**Listing never captures a pane.** Deriving the session link from terminal
output costs a `capture-pane` per running row. `bridge_url` reads Claude's own
state file instead, which is a file read, and the link is simply absent until
Claude writes it. Reaching for the expensive fallback is the job of the
`/api/sessions/{name}/url` route in Phase 5, which is where the design's
`url_pending` code is returned.

**Start waits.** `tmux new-session -d` returns as soon as the session exists.
Claude Code takes seconds to appear in the process table. A start that reads
state immediately sees a tmux session with no Claude in it, which is exactly the
`stale` state, and reports `StartFailed` on every successful start. The tests
pass anyway if the fake process table already contains the process, which is how
a first draft shipped this. Task 13 polls for a grace window and has a
regression test whose fake table is deliberately empty on the first look.

---

### Task 11: The event bus

**Files:**
- Modify: `src/hitchrail/events.py`
- Test: `tests/test_events.py`

**Interfaces:**
- Consumes: nothing.
- Produces: type alias `Event = dict[str, object]`; class `EventBus(maxsize: int = 32)` with `subscribe() -> AbstractContextManager[asyncio.Queue[Event]]`, `publish(event: Event) -> None`, property `subscriber_count: int`, property `dropped: int`.

- [ ] **Step 1: Write the failing tests**

`tests/test_events.py`:

```python
from __future__ import annotations

import asyncio

from hitchrail.events import EventBus


async def test_a_subscriber_receives_a_published_event() -> None:
    bus = EventBus()
    with bus.subscribe() as queue:
        bus.publish({"kind": "session", "name": "vessel"})
        assert await asyncio.wait_for(queue.get(), timeout=1) == {
            "kind": "session",
            "name": "vessel",
        }


async def test_every_subscriber_receives_the_same_event() -> None:
    bus = EventBus()
    with bus.subscribe() as a, bus.subscribe() as b:
        bus.publish({"kind": "ping"})
        assert await asyncio.wait_for(a.get(), timeout=1) == {"kind": "ping"}
        assert await asyncio.wait_for(b.get(), timeout=1) == {"kind": "ping"}


async def test_leaving_the_context_unsubscribes() -> None:
    bus = EventBus()
    with bus.subscribe():
        assert bus.subscriber_count == 1
    assert bus.subscriber_count == 0


async def test_an_exception_inside_the_context_still_unsubscribes() -> None:
    bus = EventBus()
    try:
        with bus.subscribe():
            raise RuntimeError("client went away")
    except RuntimeError:
        pass
    assert bus.subscriber_count == 0


async def test_publishing_with_no_subscribers_is_harmless() -> None:
    EventBus().publish({"kind": "ping"})


async def test_a_slow_subscriber_is_dropped_not_blocking() -> None:
    # A stalled browser tab must never be able to apply back pressure to the
    # machine it is watching. Events are dropped, and the drop is counted so
    # the behaviour is observable rather than merely asserted here.
    bus = EventBus(maxsize=2)
    with bus.subscribe() as queue:
        for i in range(10):
            bus.publish({"n": i})
        assert queue.qsize() == 2
        assert bus.dropped == 8


async def test_one_slow_subscriber_does_not_starve_a_fast_one() -> None:
    bus = EventBus(maxsize=1)
    with bus.subscribe() as slow, bus.subscribe() as fast:
        bus.publish({"n": 0})
        assert await asyncio.wait_for(fast.get(), timeout=1) == {"n": 0}
        bus.publish({"n": 1})  # slow is full, fast has room
        assert await asyncio.wait_for(fast.get(), timeout=1) == {"n": 1}
        assert slow.qsize() == 1
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_events.py -v`
Expected: FAIL with `ImportError: cannot import name 'EventBus' from 'hitchrail.events'`.

- [ ] **Step 3: Implement**

Replace the stub `src/hitchrail/events.py` with:

```python
"""A tiny in-process fan out, so the SSE route has something to await.

Deliberately lossy. A browser that cannot keep up gets events dropped rather
than being allowed to apply back pressure to the engine: a stalled tab must
never be able to slow down the machine it is watching.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Iterator

Event = dict[str, object]


class EventBus:
    def __init__(self, maxsize: int = 32) -> None:
        self._maxsize = maxsize
        self._subscribers: set[asyncio.Queue[Event]] = set()
        self._dropped = 0

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    @property
    def dropped(self) -> int:
        """Events discarded because a subscriber was full. Observable on purpose:
        silent loss is indistinguishable from nothing having happened."""
        return self._dropped

    @contextlib.contextmanager
    def subscribe(self) -> Iterator[asyncio.Queue[Event]]:
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=self._maxsize)
        self._subscribers.add(queue)
        try:
            yield queue
        finally:
            self._subscribers.discard(queue)

    def publish(self, event: Event) -> None:
        """Never blocks and never raises. Called from engine code that may be
        running on a worker thread, where awaiting is not available anyway."""
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                self._dropped += 1
```

- [ ] **Step 4: Run to verify passing**

Run: `uv run pytest tests/test_events.py -v`
Expected: PASS, 7 tests.

- [ ] **Step 5: Gates and commit**

```bash
uv run ruff check && uv run ruff format --check && uv run mypy && uv run lint-imports
git add src/hitchrail/events.py tests/test_events.py
git commit -m "feat(events): lossy fan out so a stalled tab cannot slow the machine"
```

---

### Task 12: State derivation across all four states

**Files:**
- Modify: `src/hitchrail/engine.py`
- Test: `tests/conftest.py`
- Test: `tests/test_engine_state.py`

**Interfaces:**
- Consumes: `Config` (Phase 1), `Tmux`, `ProcTable`, `snapshot`, `claude_ipc`, `discovery`, `ram` (Phase 3), `EventBus` (Task 11).
- Produces: `StrEnum State` with `RUNNING`, `STALE`, `DETACHED`, `STOPPED`; frozen dataclass `Session(name, state, pid, ram_mb, uptime_s, url, stopping, protected)` with `as_dict() -> dict[str, object]`; class `Engine(config, tmux=None, procs_fn=None, meminfo_fn=None, clock=time.monotonic, sleep=time.sleep, bus=None)` with `list() -> list[Session]`, `get(name: str) -> Session`, `available_mb() -> int`. Tasks 13 and 14 add `start`, `stop`, `kill`, `logs`, `session_url`, `stopping_since` and `expire_stops` to the same class.

`Session.as_dict` lives on the dataclass rather than in the server, because
serialising a session is not HTTP knowledge and the engine needs it to publish
events. The import contract forbids the engine from reaching into the server to
borrow a formatter.

- [ ] **Step 1: Write the shared fixtures**

`tests/conftest.py`:

```python
from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from hitchrail.config import Config
from hitchrail.procs import ProcTable, parse_ps
from hitchrail.tmux import Tmux


class FakeTmux(Tmux):
    """A Tmux whose server is a dict.

    Keyed by PROJECT name, not by tmux session name, because every test reads
    better that way. The real sanitising and prefixing is exercised by
    tests/test_tmux.py; what this fake stands in for is the server.
    """

    def __init__(self, prefix: str = "hr-", sessions: dict[str, int] | None = None) -> None:
        super().__init__(prefix=prefix, run=self._never)
        self.sessions: dict[str, int] = dict(sessions or {})
        self.pane_text: dict[str, str] = {}
        self.killed: list[str] = []
        self.started: list[tuple[str, str, list[str]]] = []
        self.sent: list[tuple[str, tuple[str, ...]]] = []
        self.next_pid = 1000

    @staticmethod
    def _never(argv: list[str]) -> subprocess.CompletedProcess[str]:
        raise AssertionError(f"FakeTmux must never shell out: {argv}")

    def pane_pids(self) -> dict[str, int]:
        return {self.session_name(project): pid for project, pid in self.sessions.items()}

    def has_session(self, project: str) -> bool:
        return project in self.sessions

    def pane_pid(self, project: str) -> int | None:
        return self.sessions.get(project)

    def new_session(self, project: str, cwd: str, argv: list[str]) -> None:
        self.started.append((project, cwd, argv))
        self.next_pid += 1
        self.sessions[project] = self.next_pid

    def kill_session(self, project: str) -> None:
        self.killed.append(project)
        self.sessions.pop(project, None)

    def capture_pane(self, project: str, lines: int = 40) -> str:
        return self.pane_text.get(project, "")

    def send_keys(self, project: str, *keys: str) -> None:
        self.sent.append((project, keys))


class FakeClock:
    """A monotonic clock a test can move, plus the sleep that moves it.

    Passing `clock=c, sleep=c.sleep` into the Engine is what lets the start
    grace window be exercised in microseconds instead of seconds.
    """

    def __init__(self, now: float = 1000.0) -> None:
        self.now = now
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.advance(seconds)


class ScriptedProcs:
    """A process table that changes between reads.

    The real one does. A start that reads the table once, immediately after
    tmux returns, sees a session with no Claude in it yet. Tests that hand the
    engine a table where the process already exists cannot see that bug.
    """

    def __init__(self, *stages: str) -> None:
        self.stages = list(stages)
        self.reads = 0

    def __call__(self) -> ProcTable:
        text = self.stages[min(self.reads, len(self.stages) - 1)]
        self.reads += 1
        return ProcTable(parse_ps(text))


def procs_from(text: str) -> Callable[[], ProcTable]:
    def _fn() -> ProcTable:
        return ProcTable(parse_ps(text))

    return _fn


@pytest.fixture
def root(tmp_path: Path) -> Path:
    for name in ("vessel", "vessel-social", "network", "dotted.site"):
        (tmp_path / name).mkdir()
    return tmp_path


@pytest.fixture
def config(root: Path) -> Config:
    return Config(root=root, sessions_dir=root / ".sessions")


@pytest.fixture
def sessions_dir(config: Config) -> Path:
    config.sessions_dir.mkdir(parents=True, exist_ok=True)
    return config.sessions_dir


@pytest.fixture
def plenty_of_memory() -> Callable[[], str]:
    return lambda: "MemAvailable:   25198592 kB\n"
```

- [ ] **Step 2: Write the failing state tests**

`tests/test_engine_state.py`:

```python
from __future__ import annotations

from collections.abc import Callable

from hitchrail.config import Config
from hitchrail.engine import Engine, State

from .conftest import FakeClock, FakeTmux, procs_from

TMUX_PID = 500
CLAUDE_PID = 501

RUNNING_PS = f"""\
 {TMUX_PID}     1   4096   600 tmux new-session -d -s hr-vessel
 {CLAUDE_PID}  {TMUX_PID} 512000   600 claude --dangerously-skip-permissions --remote-control vessel
"""

STALE_PS = f"""\
 {TMUX_PID}     1   4096   600 tmux new-session -d -s hr-vessel
"""

DETACHED_PS = """\
 900     1 480000   120 claude --dangerously-skip-permissions --remote-control vessel
"""


def build(
    config: Config, tmux: FakeTmux, ps_text: str, memory: Callable[[], str]
) -> Engine:
    return Engine(
        config=config,
        tmux=tmux,
        procs_fn=procs_from(ps_text),
        meminfo_fn=memory,
        clock=FakeClock(),
    )


def test_running_when_tmux_owns_a_live_claude(config, plenty_of_memory) -> None:
    tmux = FakeTmux(sessions={"vessel": TMUX_PID})
    session = build(config, tmux, RUNNING_PS, plenty_of_memory).get("vessel")
    assert session.state is State.RUNNING
    assert session.pid == CLAUDE_PID
    assert session.ram_mb == 500
    assert session.uptime_s == 600


def test_stale_when_the_terminal_outlives_claude(config, plenty_of_memory) -> None:
    tmux = FakeTmux(sessions={"vessel": TMUX_PID})
    session = build(config, tmux, STALE_PS, plenty_of_memory).get("vessel")
    assert session.state is State.STALE
    assert session.pid is None


def test_detached_when_claude_outlives_its_terminal(config, plenty_of_memory) -> None:
    # The blind spot. A tool that only asks tmux reports this as stopped,
    # which invites starting a second agent in the same folder.
    session = build(config, FakeTmux(), DETACHED_PS, plenty_of_memory).get("vessel")
    assert session.state is State.DETACHED
    assert session.pid == 900


def test_stopped_when_neither_exists(config, plenty_of_memory) -> None:
    session = build(config, FakeTmux(), "", plenty_of_memory).get("network")
    assert session.state is State.STOPPED
    assert session.pid is None
    assert session.url is None


def test_a_claude_inside_our_own_session_is_not_also_reported_detached(
    config, plenty_of_memory
) -> None:
    # The pid is owned by a pane, so it must not be picked up a second time by
    # the orphan scan, or one agent reads as two.
    tmux = FakeTmux(sessions={"vessel": TMUX_PID})
    engine = build(config, tmux, RUNNING_PS, plenty_of_memory)
    states = {s.name: s.state for s in engine.list()}
    assert states["vessel"] is State.RUNNING
    assert states["network"] is State.STOPPED


def test_sibling_prefixes_do_not_bleed(config, plenty_of_memory) -> None:
    tmux = FakeTmux(sessions={"vessel-social": TMUX_PID})
    engine = build(config, tmux, RUNNING_PS, plenty_of_memory)
    assert engine.get("vessel").state is State.STOPPED


def test_a_detached_claude_is_matched_by_exact_project_name(
    config, plenty_of_memory
) -> None:
    ps = """\
 900     1 480000   120 claude --dangerously-skip-permissions --remote-control vessel-social
"""
    engine = build(config, FakeTmux(), ps, plenty_of_memory)
    assert engine.get("vessel").state is State.STOPPED
    assert engine.get("vessel-social").state is State.DETACHED


def test_list_covers_every_folder_including_dotted_names(config, plenty_of_memory) -> None:
    names = [s.name for s in build(config, FakeTmux(), "", plenty_of_memory).list()]
    assert names == ["vessel", "vessel-social", "network", "dotted.site"]


def test_list_asks_tmux_once_not_once_per_project(config, plenty_of_memory) -> None:
    # Four projects. The shape this replaces made two tmux calls per project.
    tmux = FakeTmux(sessions={"vessel": TMUX_PID})
    calls = 0
    original = tmux.pane_pids

    def counting() -> dict[str, int]:
        nonlocal calls
        calls += 1
        return original()

    tmux.pane_pids = counting  # type: ignore[method-assign]
    build(config, tmux, RUNNING_PS, plenty_of_memory).list()
    assert calls == 1


def test_list_never_captures_a_pane(config, plenty_of_memory) -> None:
    # capture-pane is a subprocess per running row. Listing reads Claude's own
    # state file instead, and reports no link until Claude has written one.
    def refuse(project: str, lines: int = 40) -> str:
        raise AssertionError("list() must not capture a pane")

    tmux = FakeTmux(sessions={"vessel": TMUX_PID})
    tmux.capture_pane = refuse  # type: ignore[method-assign]
    build(config, tmux, RUNNING_PS, plenty_of_memory).list()


def test_url_comes_from_the_state_file(config, sessions_dir, plenty_of_memory) -> None:
    (sessions_dir / f"{CLAUDE_PID}.json").write_text('{"bridgeSessionId":"session_zz"}')
    tmux = FakeTmux(sessions={"vessel": TMUX_PID})
    session = build(config, tmux, RUNNING_PS, plenty_of_memory).get("vessel")
    assert session.url == "https://claude.ai/code/session_zz"


def test_url_is_none_while_pending(config, plenty_of_memory) -> None:
    tmux = FakeTmux(sessions={"vessel": TMUX_PID})
    assert build(config, tmux, RUNNING_PS, plenty_of_memory).get("vessel").url is None


def test_the_controller_project_is_marked_protected(root, plenty_of_memory) -> None:
    cfg = Config(root=root, sessions_dir=root / ".s", self_project="vessel")
    tmux = FakeTmux(sessions={"vessel": TMUX_PID})
    engine = build(cfg, tmux, RUNNING_PS, plenty_of_memory)
    assert engine.get("vessel").protected
    assert not engine.get("network").protected


def test_a_session_serialises_to_the_shape_the_api_sends(config, plenty_of_memory) -> None:
    tmux = FakeTmux(sessions={"vessel": TMUX_PID})
    body = build(config, tmux, RUNNING_PS, plenty_of_memory).get("vessel").as_dict()
    assert set(body) == {
        "name",
        "state",
        "pid",
        "ram_mb",
        "uptime_s",
        "url",
        "stopping",
        "protected",
    }
    assert body["state"] == "running"  # a string, not an enum repr
```

Add `import pytest` to the top of the file for the helper above.

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/test_engine_state.py -v`
Expected: FAIL with `ImportError: cannot import name 'Engine' from 'hitchrail.engine'`.

- [ ] **Step 4: Implement**

Replace the stub `src/hitchrail/engine.py` with:

```python
"""State derivation and session lifecycle.

No database. Everything is read from tmux and the process table when asked, so
there is nothing that can drift out of step with the machine. The single
exception is documented in Task 14: the fact that a graceful stop is in flight,
which lives in memory and is deliberately not persisted.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from hitchrail import claude_ipc, discovery, ram
from hitchrail.config import Config
from hitchrail.events import EventBus
from hitchrail.procs import ProcTable, snapshot
from hitchrail.tmux import Tmux


class State(StrEnum):
    RUNNING = "running"
    STALE = "stale"
    DETACHED = "detached"
    STOPPED = "stopped"


@dataclass(frozen=True)
class Session:
    name: str
    state: State
    pid: int | None = None
    ram_mb: int = 0
    uptime_s: int = 0
    url: str | None = None
    stopping: bool = False
    protected: bool = False

    def as_dict(self) -> dict[str, object]:
        """Serialising a session is not HTTP knowledge, and the engine needs it
        to publish events. The import contract forbids borrowing a formatter
        from the server, and a second copy of this shape would drift."""
        return {
            "name": self.name,
            "state": str(self.state),
            "pid": self.pid,
            "ram_mb": self.ram_mb,
            "uptime_s": self.uptime_s,
            "url": self.url,
            "stopping": self.stopping,
            "protected": self.protected,
        }


@dataclass(frozen=True)
class _Machine:
    """One consistent look at the machine, taken once per read.

    Two subprocess calls answer every project. The shape that asks tmux per
    project is a spawn per row, and the design draws fifty rows.
    """

    table: ProcTable
    pane_pids: dict[str, int]
    owned: frozenset[int]


class Engine:
    def __init__(
        self,
        config: Config,
        tmux: Tmux | None = None,
        procs_fn: Callable[[], ProcTable] | None = None,
        meminfo_fn: Callable[[], str] | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        bus: EventBus | None = None,
    ) -> None:
        self.config = config
        self.tmux = tmux or Tmux(prefix=config.session_prefix, socket=config.tmux_socket)
        self._procs_fn = procs_fn or snapshot
        self._meminfo_fn = meminfo_fn or ram.read_meminfo
        self._clock = clock
        self._sleep = sleep
        self._bus = bus
        self._stopping: dict[str, float] = {}

    # -- reading -------------------------------------------------------

    def _look(self) -> _Machine:
        table = self._procs_fn()
        pane_pids = self.tmux.pane_pids()
        owned: set[int] = set()
        for pid in pane_pids.values():
            owned.add(pid)
            owned.update(p.pid for p in table.descendants(pid))
        return _Machine(table=table, pane_pids=pane_pids, owned=frozenset(owned))

    def list(self) -> list[Session]:
        machine = self._look()
        return [
            self._derive(name, machine)
            for name in discovery.list_projects(self.config.root)
        ]

    def get(self, name: str) -> Session:
        return self._derive(name, self._look())

    def available_mb(self) -> int:
        return ram.available_mb(self._meminfo_fn())

    def _derive(self, name: str, machine: _Machine) -> Session:
        protected = (
            self.config.self_project is not None and name == self.config.self_project
        )
        pane_pid = machine.pane_pids.get(self.tmux.session_name(name))

        if pane_pid is not None:
            claude = machine.table.first_matching_in_tree(
                pane_pid, claude_ipc.REMOTE_CONTROL_MARKER
            )
            if claude is not None:
                return self._live(name, claude.pid, machine, State.RUNNING, protected)
            return Session(
                name=name,
                state=State.STALE,
                stopping=name in self._stopping,
                protected=protected,
            )

        orphan = self._find_detached(name, machine)
        if orphan is not None:
            return self._live(name, orphan, machine, State.DETACHED, protected)

        return Session(name=name, state=State.STOPPED, protected=protected)

    def _find_detached(self, name: str, machine: _Machine) -> int | None:
        """A Claude that outlived its terminal.

        Without this, such a session reads as stopped while it is very much
        alive, and starting again gives you two agents in one folder.
        """
        suffix = f"{claude_ipc.REMOTE_CONTROL_MARKER} {name}"
        for proc in machine.table.matching(claude_ipc.REMOTE_CONTROL_MARKER):
            if proc.pid in machine.owned:
                continue
            if proc.args.rstrip().endswith(suffix):
                return proc.pid
        return None

    def _live(
        self, name: str, pid: int, machine: _Machine, state: State, protected: bool
    ) -> Session:
        proc = machine.table.by_pid.get(pid)
        return Session(
            name=name,
            state=state,
            pid=pid,
            ram_mb=machine.table.tree_rss_mb(pid),
            uptime_s=proc.etime_s if proc else 0,
            # bridge_url reads a file. session_url would capture a pane, which
            # is a subprocess per running row on every list. The link is simply
            # absent until Claude writes it, and the /url route in the API pays
            # the expensive fallback when somebody actually asks for a link.
            url=claude_ipc.bridge_url(pid, self.config.sessions_dir),
            stopping=name in self._stopping,
            protected=protected,
        )

    # -- announcing ----------------------------------------------------

    @property
    def bus(self) -> EventBus | None:
        return self._bus

    def attach_bus(self, bus: EventBus) -> None:
        """Give the engine somewhere to announce, after construction.

        The server owns the bus's lifetime and the engine only publishes to it,
        but the CLI builds the engine first. This is the seam rather than the
        server reaching into a private attribute, which is what a first draft
        did and what a reviewer correctly objects to.
        """
        self._bus = bus

    def _announce(self, session: Session) -> None:
        if self._bus is not None:
            self._bus.publish({"kind": "session", "session": session.as_dict()})
```

- [ ] **Step 5: Run to verify passing**

Run: `uv run pytest tests/test_engine_state.py -v`
Expected: PASS, 15 tests.

- [ ] **Step 6: Gates and commit**

```bash
uv run ruff check && uv run ruff format --check && uv run mypy && uv run lint-imports
git add src/hitchrail/engine.py tests/conftest.py tests/test_engine_state.py
git commit -m "feat(engine): derive four states from two snapshots, detached included"
```

---

### Task 13: Starting, with a grace window and a per folder lock

**Files:**
- Modify: `src/hitchrail/engine.py`
- Test: `tests/test_engine_start.py`

**Interfaces:**
- Consumes: everything from Task 12.
- Produces: `Engine.start(name: str, acknowledged: bool = False) -> Session`; exceptions `EngineError`, `UnknownProject`, `AlreadyRunning`, `NotRunning`, `Protected`, `Locked`, `StartFailed(output: str)`, `MemoryRefused(available_mb, needed_mb)`, `MemoryNeedsAck(available_mb, needed_mb)`.

- [ ] **Step 1: Write the failing tests**

`tests/test_engine_start.py`:

```python
from __future__ import annotations

import threading

import pytest

from hitchrail.config import Config
from hitchrail.engine import (
    AlreadyRunning,
    Engine,
    Locked,
    MemoryNeedsAck,
    MemoryRefused,
    StartFailed,
    State,
    UnknownProject,
)

from .conftest import FakeClock, FakeTmux, ScriptedProcs, procs_from

PLENTY = "MemAvailable: 25198592 kB\n"

# FakeTmux.new_session hands out pid 1001, so the table has to describe that
# pid for the started session to read back as running.
STARTED_PS = """\
 1001     1   4096      5 tmux new-session -d -s hr-network
 1002  1001 300000      5 claude --dangerously-skip-permissions --remote-control network
"""


def build(config: Config, tmux: FakeTmux, procs, mem: str, clock: FakeClock) -> Engine:
    return Engine(
        config=config,
        tmux=tmux,
        procs_fn=procs,
        meminfo_fn=lambda: mem,
        clock=clock,
        sleep=clock.sleep,
    )


def test_start_launches_with_the_right_cwd_and_argv(config) -> None:
    tmux = FakeTmux()
    engine = build(config, tmux, procs_from(STARTED_PS), PLENTY, FakeClock())
    session = engine.start("network")
    project, cwd, argv = tmux.started[0]
    assert project == "network"
    assert cwd == str((config.root / "network").resolve())
    assert argv == [
        "claude",
        "--dangerously-skip-permissions",
        "--remote-control",
        "network",
    ]
    assert session.state is State.RUNNING


def test_start_waits_for_claude_to_appear_in_the_process_table(config) -> None:
    # THE regression this task exists for. `tmux new-session -d` returns as
    # soon as the session exists; Claude takes seconds to show up in ps. An
    # engine that reads state immediately sees a session with no Claude in it,
    # which IS the stale state, and reports StartFailed on every good start.
    clock = FakeClock()
    tmux = FakeTmux()
    procs = ScriptedProcs("", "", STARTED_PS)  # empty on the first two looks
    engine = build(config, tmux, procs, PLENTY, clock)
    session = engine.start("network")
    assert session.state is State.RUNNING
    assert clock.slept, "start must wait rather than deciding on the first look"


def test_start_gives_up_after_the_grace_window(config) -> None:
    clock = FakeClock()
    tmux = FakeTmux()
    tmux.pane_text["network"] = "Error: could not start\n"
    engine = build(config, tmux, procs_from(""), PLENTY, clock)
    with pytest.raises(StartFailed) as excinfo:
        engine.start("network")
    assert "could not start" in excinfo.value.output


def test_the_grace_window_is_bounded(config) -> None:
    clock = FakeClock()
    engine = build(config, FakeTmux(), procs_from(""), PLENTY, clock)
    with pytest.raises(StartFailed):
        engine.start("network")
    assert sum(clock.slept) <= engine.start_grace + 1


def test_start_is_idempotent_for_a_live_session(config) -> None:
    tmux = FakeTmux(sessions={"network": 1001})
    engine = build(config, tmux, procs_from(STARTED_PS), PLENTY, FakeClock())
    with pytest.raises(AlreadyRunning):
        engine.start("network")
    assert tmux.started == []


def test_start_refuses_a_detached_session_rather_than_doubling_it(config) -> None:
    detached = """\
 900     1 480000   120 claude --dangerously-skip-permissions --remote-control network
"""
    tmux = FakeTmux()
    engine = build(config, tmux, procs_from(detached), PLENTY, FakeClock())
    with pytest.raises(AlreadyRunning):
        engine.start("network")
    assert tmux.started == []


def test_unknown_project_is_refused(config) -> None:
    engine = build(config, FakeTmux(), procs_from(""), PLENTY, FakeClock())
    with pytest.raises(UnknownProject):
        engine.start("nope")


def test_traversal_name_is_refused_before_anything_spawns(config) -> None:
    tmux = FakeTmux()
    engine = build(config, tmux, procs_from(""), PLENTY, FakeClock())
    with pytest.raises(UnknownProject):
        engine.start("../../etc")
    assert tmux.started == []


def test_a_flag_shaped_name_is_refused_before_anything_spawns(config) -> None:
    # Argument injection: no shell is involved and a leading hyphen still
    # becomes a flag once it reaches an argv slot.
    tmux = FakeTmux()
    engine = build(config, tmux, procs_from(""), PLENTY, FakeClock())
    with pytest.raises(UnknownProject):
        engine.start("--dangerously-skip-permissions")
    assert tmux.started == []


def test_hard_memory_floor_refuses_and_spawns_nothing(config) -> None:
    tmux = FakeTmux()
    engine = build(config, tmux, procs_from(""), "MemAvailable: 2097152 kB\n", FakeClock())
    with pytest.raises(MemoryRefused) as excinfo:
        engine.start("network")
    assert excinfo.value.available_mb == 2048
    assert excinfo.value.needed_mb == 1536
    assert tmux.started == []


def test_soft_threshold_asks_first(config) -> None:
    tmux = FakeTmux()
    engine = build(config, tmux, procs_from(""), "MemAvailable: 4194304 kB\n", FakeClock())
    with pytest.raises(MemoryNeedsAck):
        engine.start("network")
    assert tmux.started == []


def test_soft_threshold_proceeds_once_acknowledged(config) -> None:
    tmux = FakeTmux()
    engine = build(
        config, tmux, procs_from(STARTED_PS), "MemAvailable: 4194304 kB\n", FakeClock()
    )
    engine.start("network", acknowledged=True)
    assert tmux.started != []


def test_acknowledgement_never_overrides_the_hard_floor(config) -> None:
    tmux = FakeTmux()
    engine = build(config, tmux, procs_from(""), "MemAvailable: 1048576 kB\n", FakeClock())
    with pytest.raises(MemoryRefused):
        engine.start("network", acknowledged=True)
    assert tmux.started == []


def test_a_second_start_of_the_same_folder_is_refused_immediately(config) -> None:
    # A web UI makes double submission far easier than a CLI does. The second
    # tap gets an answer now, rather than holding a connection behind a lock.
    tmux = FakeTmux()
    clock = FakeClock()
    engine = build(config, tmux, procs_from(STARTED_PS), PLENTY, clock)
    seen: list[type[BaseException] | None] = []
    entered = threading.Event()
    release = threading.Event()

    original = tmux.new_session

    def blocking_new_session(project: str, cwd: str, argv: list[str]) -> None:
        entered.set()
        release.wait(timeout=5)
        original(project, cwd, argv)

    tmux.new_session = blocking_new_session  # type: ignore[method-assign]

    first = threading.Thread(target=lambda: engine.start("network"))
    first.start()
    assert entered.wait(timeout=5)
    try:
        engine.start("network")
        seen.append(None)
    except Locked:
        seen.append(Locked)
    finally:
        release.set()
        first.join(timeout=5)

    assert seen == [Locked]
    assert len(tmux.started) == 1


def test_the_lock_is_per_folder_not_global(config) -> None:
    # One slow start must not refuse every other tap on the page.
    tmux = FakeTmux()
    engine = build(config, tmux, procs_from(STARTED_PS), PLENTY, FakeClock())
    engine._starting.add("vessel")  # simulate a start in flight elsewhere
    with pytest.raises(Locked):
        engine.start("vessel")
    assert tmux.started == []
    # network is a different folder and goes through untouched.
    engine.start("network")
    assert [p for p, _, _ in tmux.started] == ["network"]


def test_the_lock_is_released_even_when_the_start_fails(config) -> None:
    tmux = FakeTmux()
    engine = build(config, tmux, procs_from(""), PLENTY, FakeClock())
    with pytest.raises(StartFailed):
        engine.start("network")
    assert engine._starting == set()


def test_a_stale_session_is_cleaned_up_before_restarting(config) -> None:
    stale = """\
 1001     1   4096   600 tmux new-session -d -s hr-network
"""
    tmux = FakeTmux(sessions={"network": 1001})
    engine = build(config, tmux, ScriptedProcs(stale, STARTED_PS), PLENTY, FakeClock())
    engine.start("network")
    assert tmux.killed == ["network"]
    assert tmux.started != []
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_engine_start.py -v`
Expected: FAIL with `ImportError: cannot import name 'AlreadyRunning' from 'hitchrail.engine'`.

- [ ] **Step 3: Add the exceptions to `src/hitchrail/engine.py`**

Insert after the `State` enum:

```python
class EngineError(Exception):
    """Base for every refusal the engine makes."""


class UnknownProject(EngineError):
    pass


class AlreadyRunning(EngineError):
    pass


class NotRunning(EngineError):
    pass


class Protected(EngineError):
    """This session is the one Hitchrail is running inside."""


class Locked(EngineError):
    """A start is already in flight for this folder.

    Answered immediately rather than by blocking. A web interface makes double
    submission easy, and holding the second request open behind a lock ties up
    a worker thread to tell the user something we already know.
    """


class StartFailed(EngineError):
    def __init__(self, output: str) -> None:
        super().__init__("the session did not come up within the grace window")
        self.output = output


class _MemoryVerdict(EngineError):
    def __init__(self, available_mb: int, needed_mb: int) -> None:
        super().__init__(f"{available_mb} MB available, {needed_mb} MB needed")
        self.available_mb = available_mb
        self.needed_mb = needed_mb


class MemoryRefused(_MemoryVerdict):
    """Below the hard floor. Not overridable."""


class MemoryNeedsAck(_MemoryVerdict):
    """Below the soft threshold. The caller must confirm."""
```

- [ ] **Step 4: Add the start machinery to `Engine`**

Add `import threading` at the top. Add to `__init__`, after `self._stopping`:

```python
        self._starting: set[str] = set()
        self._starting_guard = threading.Lock()
        # tmux new-session -d returns before Claude is in the process table.
        # Deciding on the first look reports failure on every good start.
        self.start_grace = 8.0
        self.poll_interval = 0.25
```

Then these methods:

```python
    # -- starting ------------------------------------------------------

    def start(self, name: str, acknowledged: bool = False) -> Session:
        try:
            path = discovery.project_path(self.config.root, name)
        except (discovery.InvalidName, discovery.OutsideRoot) as exc:
            raise UnknownProject(name) from exc

        with self._starting_guard:
            if name in self._starting:
                raise Locked(name)
            self._starting.add(name)
        try:
            return self._start_locked(name, path_str=str(path), acknowledged=acknowledged)
        finally:
            with self._starting_guard:
                self._starting.discard(name)

    def _start_locked(self, name: str, path_str: str, acknowledged: bool) -> Session:
        current = self.get(name)
        if current.state in (State.RUNNING, State.DETACHED):
            raise AlreadyRunning(name)

        available = self.available_mb()
        verdict = ram.guard(
            available,
            need_mb=self.config.session_mb,
            hard_mb=self.config.hard_floor_mb,
            soft_mb=self.config.soft_floor_mb,
        )
        if verdict is ram.Verdict.HARD:
            raise MemoryRefused(available, self.config.session_mb)
        if verdict is ram.Verdict.SOFT and not acknowledged:
            raise MemoryNeedsAck(available, self.config.session_mb)

        if current.state is State.STALE:
            # A terminal with no agent in it. Reusing it would put the new
            # session in a pane that already holds somebody's scrollback.
            self.tmux.kill_session(name)

        self.tmux.new_session(
            name, path_str, claude_ipc.launch_argv(self.config.agent_binary, name)
        )
        return self._await_running(name)

    def _await_running(self, name: str) -> Session:
        """Poll until Claude appears, or until the grace window runs out.

        The window is generous because the failure mode of being too eager is
        reporting a working start as a failure, and the failure mode of being
        too patient is a slow error message.
        """
        deadline = self._clock() + self.start_grace
        while True:
            started = self.get(name)
            if started.state is State.RUNNING:
                self._announce(started)
                return started
            if self._clock() >= deadline:
                raise StartFailed(self.tmux.capture_pane(name, lines=40))
            self._sleep(self.poll_interval)
```

- [ ] **Step 5: Run to verify passing**

Run: `uv run pytest tests/test_engine_start.py -v`
Expected: PASS, 17 tests.

- [ ] **Step 6: Gates and commit**

```bash
uv run ruff check && uv run ruff format --check && uv run mypy && uv run lint-imports
git add src/hitchrail/engine.py tests/test_engine_start.py
git commit -m "feat(engine): start waits for claude to appear, and locks per folder"
```

---

### Task 14: The three step stop, the expiry, and the log tail

**Files:**
- Modify: `src/hitchrail/engine.py`
- Test: `tests/test_engine_stop.py`

**Interfaces:**
- Consumes: everything from Tasks 12 and 13.
- Produces: `Engine.stop(name: str) -> Session`; `Engine.kill(name: str) -> Session`; `Engine.stopping_since(name: str) -> float | None`; `Engine.expire_stops() -> list[str]`; `Engine.logs(name: str, lines: int = 40) -> str`; `Engine.session_url(name: str) -> str | None`.

`session_url` is the expensive lookup that listing deliberately skips: it falls
back to capturing the pane when Claude has not written its state file yet. The
API route in Phase 5 calls it, and returns the design's `url_pending` code when
it comes back empty.

- [ ] **Step 1: Write the failing tests**

`tests/test_engine_stop.py`:

```python
from __future__ import annotations

import pytest

from hitchrail import claude_ipc
from hitchrail.config import Config
from hitchrail.engine import Engine, NotRunning, Protected, State, UnknownProject
from hitchrail.events import EventBus

from .conftest import FakeClock, FakeTmux, procs_from

RUNNING_PS = """\
 500     1   4096   600 tmux new-session -d -s hr-vessel
 501   500 512000   600 claude --dangerously-skip-permissions --remote-control vessel
"""


def build(config: Config, tmux: FakeTmux, ps: str, clock: FakeClock, bus=None) -> Engine:
    return Engine(
        config=config,
        tmux=tmux,
        procs_fn=procs_from(ps),
        meminfo_fn=lambda: "MemAvailable: 25198592 kB\n",
        clock=clock,
        sleep=clock.sleep,
        bus=bus,
    )


def test_stop_asks_politely_and_kills_nothing(config) -> None:
    tmux = FakeTmux(sessions={"vessel": 500})
    engine = build(config, tmux, RUNNING_PS, FakeClock())
    session = engine.stop("vessel")
    assert tmux.killed == []
    assert session.stopping
    assert session.state is State.RUNNING


def test_stop_sends_the_sequence_the_quarantine_module_defines(config) -> None:
    # The engine must not know what to type at Claude. That is Claude Code
    # knowledge, it is undocumented, and it lives in claude_ipc so that a
    # change upstream touches one file.
    tmux = FakeTmux(sessions={"vessel": 500})
    build(config, tmux, RUNNING_PS, FakeClock()).stop("vessel")
    assert [keys for _project, keys in tmux.sent] == list(claude_ipc.GRACEFUL_STOP_KEYS)


def test_stopping_is_visible_in_list_and_get(config) -> None:
    tmux = FakeTmux(sessions={"vessel": 500})
    engine = build(config, tmux, RUNNING_PS, FakeClock())
    engine.stop("vessel")
    assert engine.get("vessel").stopping
    assert next(s for s in engine.list() if s.name == "vessel").stopping


def test_stopping_expires_after_the_timeout(config) -> None:
    clock = FakeClock()
    tmux = FakeTmux(sessions={"vessel": 500})
    engine = build(config, tmux, RUNNING_PS, clock)
    engine.stop("vessel")
    clock.advance(config.stop_timeout + 1)
    assert engine.expire_stops() == ["vessel"]
    assert not engine.get("vessel").stopping
    assert tmux.killed == []  # expiry never escalates on its own


def test_expiry_announces_itself(config) -> None:
    # The user is watching a timer. If expiry only becomes visible on the next
    # poll, the interface cannot tell them the wait ended.
    clock = FakeClock()
    bus = EventBus()
    engine = build(config, FakeTmux(sessions={"vessel": 500}), RUNNING_PS, clock, bus)
    with bus.subscribe() as queue:
        engine.stop("vessel")
        while not queue.empty():
            queue.get_nowait()
        clock.advance(config.stop_timeout + 1)
        engine.expire_stops()
        event = queue.get_nowait()
    assert event["kind"] == "session"
    assert event["session"]["stopping"] is False  # type: ignore[index]


def test_stopping_does_not_expire_early(config) -> None:
    clock = FakeClock()
    engine = build(config, FakeTmux(sessions={"vessel": 500}), RUNNING_PS, clock)
    engine.stop("vessel")
    clock.advance(config.stop_timeout - 1)
    assert engine.expire_stops() == []
    assert engine.get("vessel").stopping


def test_kill_during_the_wait_is_accepted(config) -> None:
    tmux = FakeTmux(sessions={"vessel": 500})
    engine = build(config, tmux, RUNNING_PS, FakeClock())
    engine.stop("vessel")
    engine.kill("vessel")
    assert tmux.killed == ["vessel"]
    assert engine.stopping_since("vessel") is None


def test_kill_without_a_preceding_stop_is_accepted(config) -> None:
    # The try-gently-first rule belongs to the interface, not the engine. A
    # script has a legitimate need to kill outright, and enforcing etiquette in
    # the transport would only invite working around it.
    tmux = FakeTmux(sessions={"vessel": 500})
    engine = build(config, tmux, RUNNING_PS, FakeClock())
    engine.kill("vessel")
    assert tmux.killed == ["vessel"]


def test_stopping_a_stopped_session_is_refused(config) -> None:
    engine = build(config, FakeTmux(), "", FakeClock())
    with pytest.raises(NotRunning):
        engine.stop("network")


def test_stopping_an_unknown_project_says_unknown_not_not_running(config) -> None:
    # Two different answers to two different questions. A caller that mistyped
    # a name should not be told the session is stopped.
    engine = build(config, FakeTmux(), "", FakeClock())
    with pytest.raises(UnknownProject):
        engine.stop("does-not-exist")
    with pytest.raises(UnknownProject):
        engine.logs("does-not-exist")


def test_the_protected_project_cannot_be_stopped_or_killed(root) -> None:
    cfg = Config(root=root, sessions_dir=root / ".s", self_project="vessel")
    tmux = FakeTmux(sessions={"vessel": 500})
    engine = build(cfg, tmux, RUNNING_PS, FakeClock())
    with pytest.raises(Protected):
        engine.stop("vessel")
    with pytest.raises(Protected):
        engine.kill("vessel")
    assert tmux.killed == []


def test_a_restart_forgets_that_a_stop_was_in_flight(config) -> None:
    # The stopping marker is deliberately not persisted. A marker that
    # outlived the process would be a lie waiting to be told.
    tmux = FakeTmux(sessions={"vessel": 500})
    first = build(config, tmux, RUNNING_PS, FakeClock())
    first.stop("vessel")
    second = build(config, tmux, RUNNING_PS, FakeClock())
    assert not second.get("vessel").stopping


def test_stop_and_kill_announce_themselves(config) -> None:
    bus = EventBus()
    engine = build(config, FakeTmux(sessions={"vessel": 500}), RUNNING_PS, FakeClock(), bus)
    with bus.subscribe() as queue:
        engine.stop("vessel")
        assert queue.get_nowait()["kind"] == "session"
        engine.kill("vessel")
        assert queue.get_nowait()["kind"] == "session"


def test_logs_returns_the_pane_tail(config) -> None:
    tmux = FakeTmux(sessions={"vessel": 500})
    tmux.pane_text["vessel"] = "one\ntwo\n"
    engine = build(config, tmux, RUNNING_PS, FakeClock())
    assert engine.logs("vessel") == "one\ntwo\n"


def test_session_url_falls_back_to_the_pane(config) -> None:
    # The expensive lookup listing deliberately skips.
    tmux = FakeTmux(sessions={"vessel": 500})
    tmux.pane_text["vessel"] = "https://claude.ai/code/session_from_pane\n"
    engine = build(config, tmux, RUNNING_PS, FakeClock())
    assert engine.session_url("vessel") == "https://claude.ai/code/session_from_pane"


def test_session_url_is_none_when_there_is_nothing_yet(config) -> None:
    tmux = FakeTmux(sessions={"vessel": 500})
    engine = build(config, tmux, RUNNING_PS, FakeClock())
    assert engine.session_url("vessel") is None


def test_session_url_of_a_stopped_session_is_refused(config) -> None:
    engine = build(config, FakeTmux(), "", FakeClock())
    with pytest.raises(NotRunning):
        engine.session_url("network")
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_engine_stop.py -v`
Expected: FAIL with `AttributeError: 'Engine' object has no attribute 'stop'`.

- [ ] **Step 3: Implement in `src/hitchrail/engine.py`**

```python
    # -- stopping ------------------------------------------------------

    def stopping_since(self, name: str) -> float | None:
        return self._stopping.get(name)

    def expire_stops(self) -> list[str]:
        """Drop stop markers older than the timeout, and say so.

        Expiry means "we stopped waiting", never "escalate". The session is
        still alive and the decision to kill it belongs to a person.

        It announces, because the person watching the timer has to learn that
        the wait ended. An expiry visible only on the next poll is an expiry
        the interface cannot report.
        """
        now = self._clock()
        expired = [
            name
            for name, began in self._stopping.items()
            if now - began >= self.config.stop_timeout
        ]
        for name in expired:
            self._stopping.pop(name, None)
            self._announce(self.get(name))
        return expired

    def stop(self, name: str) -> Session:
        self._require_live(name)
        self._stopping[name] = self._clock()
        # Ask, do not kill. One call, and the engine does not know what a stop
        # physically is: it does not send keys, and it is not "given" any to
        # send. It hands the quarantine module a pane and lets it decide.
        # Iterating GRACEFUL_STOP_KEYS here would put three Claude Code
        # assumptions in the engine: that stopping is keystrokes, that it is a
        # sequence of them, and that they travel through tmux. See the design's
        # sections 3.1 and 4.3. The engine owns the policy (the timeout, the in
        # flight marker, never escalating on its own); the adapter owns the
        # mechanism.
        claude_ipc.request_stop(self.tmux, name)
        updated = self.get(name)
        self._announce(updated)
        return updated

    def kill(self, name: str) -> Session:
        self._require_live(name)
        self._stopping.pop(name, None)
        self.tmux.kill_session(name)
        updated = self.get(name)
        self._announce(updated)
        return updated

    def logs(self, name: str, lines: int = 40) -> str:
        self._require_live(name)
        return self.tmux.capture_pane(name, lines=lines)

    def session_url(self, name: str) -> str | None:
        """The link, paying for the terminal fallback that listing skips.

        Called when somebody actually wants to open a session, which is rare
        enough to afford a capture-pane and specific enough to be worth one.
        """
        session = self._require_live(name)
        if session.url:
            return session.url
        if session.pid is None:
            return None
        return claude_ipc.session_url(
            session.pid,
            self.config.sessions_dir,
            self.tmux.capture_pane(name, lines=200),
        )

    def _require_live(self, name: str) -> Session:
        """Unknown, protected and stopped are three different answers.

        Telling a caller who mistyped a folder name that the session is not
        running sends them looking for a session that never existed.
        """
        try:
            discovery.project_path(self.config.root, name)
        except (discovery.InvalidName, discovery.OutsideRoot) as exc:
            raise UnknownProject(name) from exc
        session = self.get(name)
        if session.protected:
            raise Protected(name)
        if session.state is State.STOPPED:
            raise NotRunning(name)
        return session
```

- [ ] **Step 4: Run to verify passing**

Run: `uv run pytest tests/test_engine_stop.py -v`
Expected: PASS, 17 tests.

- [ ] **Step 5: Prove it against a real machine**

This is the step that makes Phase 4 done. Tests passing is not this step, and
there is still no web server involved.

```bash
mkdir -p /tmp/hitchrail-demo/demo-project
uv run python - <<'PY'
import time
from pathlib import Path
from hitchrail.config import Config
from hitchrail.engine import Engine

cfg = Config(root=Path("/tmp/hitchrail-demo"))
engine = Engine(config=cfg)

print("before:", [s.as_dict() for s in engine.list()])
started = engine.start("demo-project")
print("started:", started.as_dict())

time.sleep(5)
print("url:", engine.session_url("demo-project"))
print("logs:", engine.logs("demo-project", lines=10))

engine.stop("demo-project")
print("stopping:", engine.get("demo-project").as_dict())
time.sleep(5)
print("after asking:", engine.get("demo-project").as_dict())

engine.kill("demo-project")
print("after kill:", engine.get("demo-project").as_dict())
PY
tmux list-sessions | grep hr- || echo "no hitchrail sessions left, correct"
```

Expected: `start` returns a `running` session rather than raising `StartFailed`,
the URL appears within a few seconds, `stop` leaves the session alive and marked
`stopping`, and `kill` removes it. If `start` raises `StartFailed` on a machine
where the session is visibly running, the grace window in Task 13 is too short
for that machine and the number, not the design, is what to change.

- [ ] **Step 6: Gates and commit**

```bash
uv run ruff check && uv run ruff format --check && uv run mypy && uv run lint-imports && uv run pytest
git add src/hitchrail/engine.py tests/test_engine_stop.py
git commit -m "feat(engine): three step stop with an announced, non persisted marker"
```

---

## Test coverage for this phase

`docs/tech-guidelines.md` 7.4 and 7.5 define the tiers and say what coverage
does not tell you. What this phase specifically owes:

- **Every state in the table gets a test, `detached` included.** That state is
  the one a naive implementation gets wrong, and it is the reason derivation
  runs in two directions. A suite that covers `running` and `stopped` and calls
  it done has tested the easy half.
- **The stop sequence is tested through the ENGINE, not through the adapter.**
  `claude_ipc.request_stop` already has its own test; what this phase must
  prove is the policy around it, which is the timeout, the in flight marker,
  the kill staying reachable throughout, and the refusal to escalate on its
  own.
- **The in flight stop marker is the one piece of state that is not derived**,
  so it needs a test that a fresh `Engine` reports nothing as `stopping`. A
  marker that outlived its process would be a lie, and nothing else in the
  suite can catch that.
- **The grace window and the lock need a fake clock**, not a sleep. A test that
  waits is a test somebody deletes when the suite gets slow.
- **#34's property based tests belong on state derivation first.** Four states derived from two independent scans is an invariant
  problem: no process table and tmux listing should ever produce a session that
  is both `running` and `stopped`, and that is a property rather than an
  example.
- **A live tier for the engine is NOT required.** Phase 4's exit criteria
  already demand a real Claude session started, watched, gracefully stopped and
  killed from a Python session, which is the runtime proof 7.3 asks for.

## Phase 4 exit criteria

- [ ] All five gates green on 3.11, 3.12 and 3.13.
- [ ] All four states in the design's section 4.1 have a passing test, `detached` included, and a Claude inside one of our own panes is never also reported detached.
- [ ] `list()` issues exactly one tmux call and one `ps` call regardless of project count, and captures no pane.
- [ ] `start` succeeds against a process table that is empty on the first look, and the grace window is bounded.
- [ ] A second start of the same folder raises `Locked` immediately; a start of a different folder is unaffected; the lock is released on failure.
- [ ] The engine asks for a stop and does not know what one is: `grep -rn '"/exit"' src/` returns only `claude_ipc.py`, AND `grep -rn 'GRACEFUL_STOP_KEYS\|send_keys' src/hitchrail/engine.py` returns nothing. The first half alone passes while the engine still iterates the sequence, which is the leak the design's section 4.3 exists to prevent.
- [ ] Expiry drops the marker, announces it, and never escalates.
- [ ] A fresh `Engine` reports no session as `stopping`.
- [ ] A real Claude session has been started, watched, gracefully stopped and killed from a Python session, with no web server involved.

When these hold, start Phase 5 from `docs/roadmap.md`.
