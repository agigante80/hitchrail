"""Fixtures shared by the whole suite.

Phase 4 adds the engine fakes here (FakeTmux, FakeClock, ScriptedProcs). For
now it holds the one guard that keeps the hermetic tier honest.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable

import pytest

from hitchrail.claude_ipc import launch_argv
from hitchrail.procs import ProcTable, parse_ps
from hitchrail.tmux import Tmux

# What the stubbed resolver answers with. `.invalid` is reserved by RFC 2606
# precisely so it can never resolve, and 203.0.113.0/24 is TEST-NET-3, so
# neither can be confused for a real machine if one leaks into an assertion.
STUB_HOSTNAME = "test-host.invalid"
STUB_ADDRESS = "203.0.113.7"


@pytest.fixture(autouse=True)
def no_real_network(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the hermetic tier hermetic, without asking every test to remember.

    `Config(host="0.0.0.0")` with no `resolver` falls through to the real
    `local_addresses()`, which runs `gethostname`, `getaddrinfo` and a UDP
    connect. Around twenty tests did exactly that, so the tier that
    `docs/tech-guidelines.md` section 7.4 calls hermetic was doing real DNS,
    and its answers changed with the machine it ran on.

    Stubbed here rather than by passing a resolver at every call site on
    purpose: a rule that every test has to remember is a rule that decays, and
    this one had already decayed by the time it was written down. A test that
    wants a specific answer still passes `resolver=` and overrides this.

    `tests/test_live_socket.py` is the documented exception to the hermetic
    rule and is marked `live`, so it is left alone.
    """
    if request.node.get_closest_marker("live"):
        return
    monkeypatch.setattr(
        "hitchrail.config.local_addresses", lambda: (STUB_HOSTNAME, STUB_ADDRESS)
    )


# -- Phase 4 fakes ---------------------------------------------------------
#
# Every external surface the engine touches, faked behind the seams the
# adapters were built with. `args` in a scripted process table is built by
# CALLING `claude_ipc.launch_argv`, never pasted, so a change to the argument
# ORDER breaks the tests instead of silently making `detached` undetectable.


class FakeTmux(Tmux):
    """A Tmux whose server is a dict.

    Keyed by PROJECT name rather than tmux session name, because every test
    reads better that way. The real sanitising and prefixing is exercised in
    `tests/test_tmux.py`; what this stands in for is the server.
    """

    def __init__(self, prefix: str = "hr-", sessions: dict[str, int] | None = None) -> None:
        super().__init__(prefix=prefix, run=self._never)
        self.sessions: dict[str, int] = dict(sessions or {})
        self.pane_text: dict[str, str] = {}
        self.killed: list[str] = []
        self.started: list[tuple[str, str, list[str]]] = []
        self.sent: list[tuple[str, tuple[str, ...]]] = []
        self.pane_pids_calls = 0
        self.capture_calls = 0
        self.next_pid = 1000
        self.fail_pane_pids = False

    @staticmethod
    def _never(argv: list[str]) -> subprocess.CompletedProcess[str]:
        raise AssertionError(f"FakeTmux must never shell out: {argv}")

    def pane_pids(self) -> dict[str, int]:
        self.pane_pids_calls += 1
        if self.fail_pane_pids:
            # What a real one returns with no server running: legitimately
            # "no sessions", which is NOT the same as a failed ps.
            return {}
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
        self.capture_calls += 1
        return self.pane_text.get(project, "")

    def send_keys(self, project: str, *keys: str) -> None:
        self.sent.append((project, keys))


class FakeClock:
    """A movable clock, plus the sleep that moves it.

    Passing `clock=c, sleep=c.sleep` is what lets a grace window be exercised
    in microseconds. A test that really sleeps is a test somebody deletes when
    the suite gets slow.
    """

    def __init__(self, now: float = 1000.0) -> None:
        self.now = now
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds

    # An unbounded wait is a real defect, and a test that HANGS on it is
    # nearly as bad as one that passes: CI stalls until a job timeout with no
    # useful output. This turns the hang into a failure with a message.
    max_sleeps = 1000

    def sleep(self, seconds: float) -> None:
        if len(self.slept) >= self.max_sleeps:
            raise AssertionError(
                f"slept {len(self.slept)} times without finishing: the wait "
                "under test is unbounded"
            )
        self.slept.append(seconds)
        self.advance(seconds)


class ScriptedProcs:
    """A process table that CHANGES between reads, because the real one does.

    A start reads the table immediately after tmux returns and sees a session
    with no agent in it yet. A test handing the engine a table where the
    process already exists cannot see that.
    """

    def __init__(self, *stages: str) -> None:
        self.stages = list(stages)
        self.reads = 0

    def __call__(self) -> ProcTable:
        text = self.stages[min(self.reads, len(self.stages) - 1)]
        self.reads += 1
        return ProcTable(parse_ps(text))


def ps_row(
    pid: int,
    ppid: int,
    project: str | None = None,
    rss_kb: int = 1024,
    etime_s: int = 60,
    args: str | None = None,
) -> str:
    """One `ps` row.

    When `project` is given the command line is built by CALLING
    `launch_argv`, never pasted. `_find_detached` matches on the project name
    being the LAST element, so reordering that argv must break these tests
    rather than silently making every detached agent invisible.
    """
    if args is None:
        args = " ".join(launch_argv("claude", project)) if project else "sleep 60"
    return f"{pid} {ppid} {rss_kb} {etime_s} {args}\n"


def procs_from(text: str) -> Callable[[], ProcTable]:
    def _fn() -> ProcTable:
        return ProcTable(parse_ps(text))

    return _fn


def failing_procs() -> ProcTable:
    """What `snapshot` returns when `ps` itself failed: empty AND not ok."""
    return ProcTable([], ok=False)
