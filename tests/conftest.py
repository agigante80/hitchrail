"""Fixtures shared by the whole suite.

Phase 4 adds the engine fakes here (FakeTmux, FakeClock, ScriptedProcs). For
now it holds the one guard that keeps the hermetic tier honest.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable

import pytest

from hitchrail.claude_ipc import launch_argv
from hitchrail.cli import JOURNAL_ENV
from hitchrail.config import TOKEN_ENV
from hitchrail.procs import ProcTable, parse_ps
from hitchrail.tmux import Panes, Tmux

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


#: Every variable `src/hitchrail/` reads from the environment. The autouse
#: fixture below removes all of them, and
#: `test_every_environment_variable_the_product_reads_is_scrubbed` fails if a
#: new read appears that is not named here.
#:
#: Naming the CONSTANTS rather than the strings, so a rename moves both ends at
#: once instead of leaving a scrub for a variable nothing reads any more.
AMBIENT_ENV = (JOURNAL_ENV, TOKEN_ENV)


@pytest.fixture(autouse=True)
def no_ambient_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """The suite must not care whether the developer runs it under systemd, or
    runs Hitchrail at all.

    #110 made `banner()` degrade when `JOURNAL_STREAM` is set, which systemd
    puts in the environment of any service whose stdout it connected to the
    journal. That variable is inherited, so a shell started from a user unit
    has it, and three banner tests written years before #110 went red on a
    machine where nothing about them had changed.

    #203 is the same failure one variable over, and it is the one that showed
    what a partial scrub costs. `HITCHRAIL_TOKEN` is what an operator sets to
    keep a phone's saved link working across restarts, so it is exported on
    exactly the machines where this project is developed. Four `test_cli.py`
    tests asserting the generated-nothing default failed there and passed in
    CI, which is the wrong way round: the control was tested where nobody was
    looking and untested where the work happens.

    It did not fail the person who introduced it. It failed a first time
    contributor on PR #187, who met a red suite, could not tell whether it was
    their change, and deselected six tests to get a clean run.

    This is the same rule as `no_real_network` above and the same rule the
    tiers already follow: the fixtures describe an EMPTY machine, and a test
    that wants one of these set sets it itself.
    """
    for name in AMBIENT_ENV:
        monkeypatch.delenv(name, raising=False)


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

    def __init__(
        self,
        prefix: str = "hr-",
        sessions: dict[str, int] | None = None,
        foreign: dict[str, int] | None = None,
    ) -> None:
        super().__init__(prefix=prefix, run=self._never)
        self.sessions: dict[str, int] = dict(sessions or {})
        # #85. Sessions on the same server that are not ours, keyed by session
        # NAME here because a test reads better that way, and inverted to
        # pid -> name on the way out because that is the question derivation
        # asks. A real `list-panes -a` returns both halves in one call, so the
        # fake returns both from one method for the same reason.
        self.foreign: dict[str, int] = dict(foreign or {})
        self.pane_text: dict[str, str] = {}
        self.killed: list[str] = []
        self.started: list[tuple[str, str, list[str]]] = []
        self.pane_kept: list[tuple[str, bool]] = []
        self.capture_lines: list[int] = []
        self.capture_escapes: list[bool] = []
        self.dead_panes: set[str] = set()
        self.sent: list[tuple[str, tuple[str, ...]]] = []
        self.panes_calls = 0
        self.capture_calls = 0
        self.next_pid = 1000
        self.fail_panes = False
        # #102. A `new_session` that reports unavailable may have created the
        # session anyway: `subprocess`'s timeout kills the tmux CLIENT and
        # undoes nothing the server already did. `fail_new_session` models that
        # by raising AFTER recording the session, which is the only shape the
        # defect has. `fail_has_session` models tmux still being unreachable
        # when the cleanup asks.
        self.fail_new_session: Exception | None = None
        self.fail_has_session: Exception | None = None
        # Whether the server got far enough to create the session before the
        # client was killed. Both outcomes are real and they need different
        # handling, so the fake expresses both rather than one.
        self.new_session_creates = True

    @staticmethod
    def _never(argv: list[str]) -> subprocess.CompletedProcess[str]:
        raise AssertionError(f"FakeTmux must never shell out: {argv}")

    def panes(self) -> Panes:
        self.panes_calls += 1
        if self.fail_panes:
            # What a real one returns with no server running: legitimately
            # "no sessions", which is NOT the same as a failed ps.
            return Panes(ours={}, foreign={})
        return Panes(
            ours={self.session_name(project): pid for project, pid in self.sessions.items()},
            foreign={pid: name for name, pid in self.foreign.items()},
        )

    def has_session(self, project: str) -> bool:
        if self.fail_has_session is not None:
            raise self.fail_has_session
        return project in self.sessions

    def pane_pid(self, project: str) -> int | None:
        return self.sessions.get(project)

    def new_session(self, project: str, cwd: str, argv: list[str]) -> None:
        self.started.append((project, cwd, argv))
        if self.new_session_creates:
            self.next_pid += 1
            self.sessions[project] = self.next_pid
        # AFTER the session exists, deliberately. A fake that raised first
        # could not express #102 at all, and a test written against it would
        # prove the cleanup never runs.
        if self.fail_new_session is not None:
            raise self.fail_new_session

    def kill_session(self, project: str) -> None:
        self.killed.append(project)
        self.sessions.pop(project, None)
        # A killed session takes its pane text with it, the way a real one
        # does. Without this a test could capture output from a session that
        # no longer exists and never notice, which is exactly the mistake #66
        # is about.
        self.pane_text.pop(project, None)

    def pane_is_dead(self, project: str) -> bool:
        """Defaults to ALIVE, which is the safe answer: the caller kills on
        True, and a fake that guessed dead would let a test pass while the
        real code ended a healthy agent."""
        return project in self.dead_panes

    def keep_pane_on_exit(self, project: str, keep: bool) -> None:
        """#66's `remain-on-exit`, recorded rather than performed.

        Recorded as a LIST rather than a flag, because the property that
        matters is that it is cleared once per successful start: a fake that
        stored only the latest value cannot tell "set then cleared" from
        "never set".
        """
        self.pane_kept.append((project, keep))

    def capture_pane(self, project: str, lines: int = 40, escapes: bool = False) -> str:
        self.capture_calls += 1
        # Recorded, because #66 turns on WHICH read was asked for: a dead
        # start needs the whole scrollback and a log tail does not.
        self.capture_lines.append(lines)
        self.capture_escapes.append(escapes)
        if escapes and project not in self.pane_text:
            # The graceful stop verifies the input box before it types (#89),
            # and a fake with nothing to say would refuse every stop in the
            # suite. A test that cares what the box holds sets `pane_text`;
            # every other one is about the lifecycle around the stop rather
            # than about the box, and gets a clear one.
            #
            # ONLY where a session exists. A real `capture-pane` against a
            # project with no tmux session returns nothing, and handing back a
            # tidy empty box there made a detached agent look stoppable by
            # keystroke when it has no pane to type into at all.
            #
            # A session existing is still not the same as an AGENT being in it.
            # A `stale` pane holds a shell and draws no agent input box at all,
            # and this fake cannot tell the two apart because staleness is
            # derived from the process table, which it never sees. A test about
            # a pane that is not an agent has to say so through `pane_text`,
            # and `test_stopping_a_stale_session_is_refused_by_state_not_by_
            # screen` is what that looks like.
            return CLEAR_INPUT_BOX if project in self.sessions else ""
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


# A real Claude Code input box with nothing typed in it, captured on
# 2026-09-02. The prompt is U+276F plus U+00A0. `tests/
# test_claude_ipc.py` holds the other two states and the argument for them.
CLEAR_INPUT_BOX = "\x1b[39m\u276f\xa0                     \n"

# The same row with something a person typed in it. Bright, which is the only
# thing that distinguishes it from the agent's own dim suggestion.
DIRTY_INPUT_BOX = "\x1b[39m\u276f\xa0half a sentence\n"

# #88's trust modal, the state #204 exists to answer. The ornament is the same
# U+276F, and what follows it is a colour reset and an ORDINARY space where the
# input box has U+00A0. That one character is the whole distinction, which is
# why this is a captured row rather than a description of one.
# A STALE pane, on a developer's machine. The agent is gone and a shell has the
# terminal, and that shell's prompt is U+276F because Starship, Pure and
# Powerlevel10k all use it by default.
#
# **Byte for byte the modal shape**: the ornament followed by an ordinary space.
# So `claude_ipc.awaits_answer` returns True about a SHELL, correctly by its own
# definition, and the refusal for this case has to live in the engine where the
# state is known. A fixture using `user@host:/tmp$ ` cannot show that, which is
# why the older stale test passed against code that would type here.
SHELL_PROMPT_STALE = "\x1b[39m\u276f\x1b[39m \n"

TRUST_MODAL = (
    "\x1b[39m \x1b[38;5;153m\u276f\x1b[39m \x1b[38;5;153mNo,\x1b[39m \x1b[38;5;153mexit\n"
)


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
