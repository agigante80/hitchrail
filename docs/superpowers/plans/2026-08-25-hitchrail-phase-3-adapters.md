# Hitchrail Phase 3: The Adapters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One module per external surface, each pure, injectable, and testable without a real machine, so the engine in Phase 4 can be built and tested without touching tmux, the process table, Claude Code or `/proc`.

**Architecture:** Every adapter takes its subprocess runner as a constructor argument defaulting to the real one. That single seam is what makes the whole engine hermetic later. No adapter holds state beyond its configuration, and none of them import each other except for the shared `Runner` type alias.

**Tech Stack:** Python 3.11+, stdlib `subprocess`, `re`, `json`, `hashlib`. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-25-hitchrail-design.md` sections 4.2 and 4.4

**Roadmap:** `docs/roadmap.md` (this plan is Phase 3 of 7)

## Global Constraints

Copied verbatim from the spec. Every task inherits these.

- **Python `>=3.11`.** CI runs 3.11, 3.12 and 3.13. All blocking.
- **Exactly three runtime dependencies:** `starlette>=1.6,<2`, `uvicorn>=0.52,<1`, `sse-starlette>=3.4,<4`. A fourth requires a written justification in the pull request.
- **No shell, ever.** Every subprocess call takes an argument list. `shell=True` is forbidden with no exceptions.
- **The engine layer must not import** `hitchrail.server`, `hitchrail.cli`, `starlette`, `uvicorn` or `sse_starlette`. Every module in this phase is in that layer.
- **Never a bare `tmux kill-server`.** Never kill a session whose name does not carry the configured prefix.
- **`claude_ipc.py` is quarantine.** It is the only module allowed to know Claude Code internals.
- **The root stays lean.** Every tool is configured from `pyproject.toml`.
- **No em dashes or en dashes** anywhere, including commit messages. A hook enforces it.
- Defaults: session prefix `hr-`, hard memory floor 1536 MB, soft floor 3072 MB, per session estimate 1536 MB.
- Tests are hermetic. No test touches a real tmux server, a real Claude process, the network, or the filesystem outside a temporary root.

## Phase 3 file structure

| File | Responsibility |
|---|---|
| `src/hitchrail/tmux.py` | target addressing, and the five footguns that make it non obvious |
| `src/hitchrail/procs.py` | one process table snapshot and the queries the engine asks of it |
| `src/hitchrail/claude_ipc.py` | everything that knows Claude Code internals, and nothing else does |
| `src/hitchrail/ram.py` | memory readings and the guard decision, pure given its inputs |

Task order within the phase is dependency order: `procs` reuses the `Runner`
type alias from `tmux`, and `claude_ipc` and `ram` are leaves that depend on
nothing. `claude_ipc` comes third rather than last only because Phase 4 Task 12
needs its marker constant on the first line of state derivation, so putting it
next to the two adapters it will be used with keeps the reading order sensible.

---

### Task 7: The tmux adapter and its four addressing footguns

**Verified against tmux 3.4 on a private socket before writing this task**, per
the project's "verify, do not recall" rule, because the whole task rests on
these being true:

| Claim | Result |
|---|---|
| `has-session -t hr-vessel` prefix matches `hr-vessel-social` | confirmed, it matched |
| `=` anchors it to an exact session | confirmed, `=hr-vessel` refused |
| `list-panes -t "=name"` ignores the anchor and prefix matches | confirmed: a NONEXISTENT session returned its sibling's pane pid, which is the "stopped project reads as running" symptom exactly |
| a trailing `:` makes `list-panes` read the target as a session | confirmed, `=name:` then refuses correctly and still resolves a real session |

One correction to the design's wording. Footgun 1 says a session named
`dotted.site` "can be created but never addressed", which is true, but the
mechanism is sharper than that: tmux 3.4 does not reject the name, it silently
stores it as `dotted_site`. So the session exists under a name nobody looked
for, and `has-session -t "=hr-dotted.site"` fails while the agent is running,
which presents as the session vanishing. `sanitize` sidesteps this entirely by
emitting no `.` or `:` at all, so tmux never rewrites anything.

**Files:**
- Modify: `src/hitchrail/tmux.py`
- Test: `tests/test_tmux.py`

**Interfaces:**
- Consumes: nothing.
- Produces: type alias `Runner = Callable[[list[str]], subprocess.CompletedProcess[str]]`; `sanitize(name: str) -> str`; exception `NotOurSession`; class `Tmux(prefix: str, socket: str | None = None, run: Runner | None = None)` with methods `session_name(project: str) -> str`, `session_target(project: str) -> str`, `pane_target(project: str) -> str`, `has_session(project: str) -> bool`, `pane_pids() -> dict[str, int]`, `pane_pid(project: str) -> int | None`, `new_session(project: str, cwd: str, argv: list[str]) -> None`, `kill_session(project: str) -> None`, `capture_pane(project: str, lines: int = 40) -> str`, `send_keys(project: str, *keys: str) -> None`.

Two things here are new relative to a naive adapter, and both come out of
review rather than out of tmux's manual.

**`sanitize` must be injective.** Replacing `.` and `:` with `-` makes a name
addressable, and it also makes `a.b` and `a-b` the same tmux session. Two
folders then share one agent: one reads as running because of the other, and
stopping one kills the other's work. Appending a short digest of the original
name whenever the replacement changed anything keeps the mapping one to one.

**`pane_pids` reads every session in one call.** The obvious shape is
`list_sessions()` followed by a `pane_pid()` per session, which the engine then
runs once per project while deriving state. At the fifty rows the design draws,
that is hundreds of subprocess spawns per page load. `list-panes -a` answers
the whole question once.

- [ ] **Step 1: Write the failing tests**

`tests/test_tmux.py`:

```python
from __future__ import annotations

import subprocess

import pytest

from hitchrail.tmux import NotOurSession, Tmux, sanitize


class FakeRunner:
    """Records argv and replays canned stdout per tmux subcommand."""

    def __init__(
        self, stdout: dict[str, str] | None = None, rc: dict[str, int] | None = None
    ) -> None:
        self.calls: list[list[str]] = []
        self.stdout = stdout or {}
        self.rc = rc or {}

    def __call__(self, argv: list[str]) -> subprocess.CompletedProcess[str]:
        self.calls.append(argv)
        sub = next((a for a in argv if a in self.stdout or a in self.rc), "")
        return subprocess.CompletedProcess(argv, self.rc.get(sub, 0), self.stdout.get(sub, ""), "")


def test_dots_and_colons_are_sanitised() -> None:
    # Footgun 1: tmux reads . and : as window and pane separators, so a session
    # named dotted.site can be created and then never addressed again.
    assert sanitize("dotted.site").startswith("dotted-it")
    assert "." not in sanitize("dotted.site")
    assert ":" not in sanitize("a:b.c")


def test_sanitising_is_injective() -> None:
    # The collision the naive version has. Without the digest suffix, `a.b` and
    # `a-b` become one tmux session: two folders sharing one agent, where
    # stopping one kills the other's work.
    assert sanitize("a.b") != sanitize("a-b")
    assert sanitize("a:b") != sanitize("a.b")
    assert sanitize("a-b") == "a-b"  # an already safe name is left alone


def test_sanitising_is_deterministic() -> None:
    # It has to survive a restart, or a session started before the restart
    # becomes unaddressable after it.
    assert sanitize("dotted.site") == sanitize("dotted.site")


def test_session_target_is_anchored_for_exact_matching() -> None:
    # Footgun 2: without the = prefix, has-session prefix matches, so
    # hr-vessel resolves hr-vessel-social.
    t = Tmux(prefix="hr-")
    assert t.session_target("vessel") == "=hr-vessel"


def test_pane_target_carries_a_trailing_colon() -> None:
    # Footgun 3: list-panes takes a pane target, ignores the = anchor, and
    # falls back to prefix matching. The trailing colon qualifies the string as
    # a session, which is what makes the anchor mean anything.
    t = Tmux(prefix="hr-")
    assert t.pane_target("vessel") == "=hr-vessel:"


def test_has_session_uses_the_anchored_target() -> None:
    runner = FakeRunner()
    Tmux(prefix="hr-", run=runner).has_session("vessel")
    assert runner.calls[-1] == ["tmux", "has-session", "-t", "=hr-vessel"]


def test_pane_pids_reads_every_session_in_one_call() -> None:
    # The performance fix. One call, not one per session, because the engine
    # asks this question once per project on every list.
    runner = FakeRunner(
        stdout={"list-panes": "hr-vessel 4242\nhr-network 4343\nsomeone-else 999\n"}
    )
    pids = Tmux(prefix="hr-", run=runner).pane_pids()
    assert pids == {"hr-vessel": 4242, "hr-network": 4343}
    assert len(runner.calls) == 1
    assert "-a" in runner.calls[0]


def test_pane_pids_keeps_the_first_pane_of_each_session() -> None:
    runner = FakeRunner(stdout={"list-panes": "hr-vessel 4242\nhr-vessel 4250\n"})
    assert Tmux(prefix="hr-", run=runner).pane_pids() == {"hr-vessel": 4242}


def test_pane_pids_ignores_sessions_that_are_not_ours() -> None:
    runner = FakeRunner(stdout={"list-panes": "work 111\nhr-vessel 4242\n"})
    assert Tmux(prefix="hr-", run=runner).pane_pids() == {"hr-vessel": 4242}


def test_pane_pids_is_empty_when_no_server_is_running() -> None:
    runner = FakeRunner(stdout={"list-panes": ""}, rc={"list-panes": 1})
    assert Tmux(prefix="hr-", run=runner).pane_pids() == {}


def test_pane_pids_skips_malformed_rows_without_raising() -> None:
    runner = FakeRunner(stdout={"list-panes": "hr-a notapid\nhr-b 7\n\n"})
    assert Tmux(prefix="hr-", run=runner).pane_pids() == {"hr-b": 7}


def test_pane_pid_uses_the_pane_target() -> None:
    runner = FakeRunner(stdout={"list-panes": "4242\n"})
    assert Tmux(prefix="hr-", run=runner).pane_pid("vessel") == 4242
    assert "=hr-vessel:" in runner.calls[-1]


def test_pane_pid_is_none_when_there_is_no_pane() -> None:
    runner = FakeRunner(stdout={"list-panes": ""}, rc={"list-panes": 1})
    assert Tmux(prefix="hr-", run=runner).pane_pid("gone") is None


def test_new_session_passes_argv_as_a_list_and_never_a_shell_string() -> None:
    runner = FakeRunner()
    Tmux(prefix="hr-", run=runner).new_session("vessel", "/tmp/x", ["claude", "--flag"])
    argv = runner.calls[-1]
    assert argv[:5] == ["tmux", "new-session", "-d", "-s", "hr-vessel"]
    assert "-c" in argv and "/tmp/x" in argv
    assert argv[-2:] == ["claude", "--flag"]
    assert all(isinstance(a, str) for a in argv)


def test_kill_session_refuses_a_name_that_is_not_ours() -> None:
    # Footgun 5: never kill a session we did not create.
    runner = FakeRunner()
    with pytest.raises(NotOurSession):
        Tmux(prefix="hr-", run=runner).kill_session("../someone-else")
    assert runner.calls == []


def test_kill_session_targets_only_the_named_session() -> None:
    runner = FakeRunner()
    Tmux(prefix="hr-", run=runner).kill_session("vessel")
    assert runner.calls[-1] == ["tmux", "kill-session", "-t", "=hr-vessel"]


def test_no_method_ever_issues_kill_server() -> None:
    runner = FakeRunner()
    t = Tmux(prefix="hr-", run=runner)
    t.has_session("a")
    t.pane_pids()
    t.pane_pid("a")
    t.kill_session("a")
    t.capture_pane("a")
    t.send_keys("a", "C-c")
    t.new_session("a", "/tmp", ["true"])
    assert not any("kill-server" in argv for argv in runner.calls)


def test_every_call_carries_the_socket_when_one_is_configured() -> None:
    # The E2E tier depends on this: a bare tmux honours $TMUX over $TMUX_TMPDIR,
    # so a suite run from inside tmux would talk to the developer's real server.
    runner = FakeRunner()
    t = Tmux(prefix="hr-", socket="/tmp/hr.sock", run=runner)
    t.has_session("a")
    t.pane_pids()
    t.kill_session("a")
    t.capture_pane("a")
    assert all(argv[:3] == ["tmux", "-S", "/tmp/hr.sock"] for argv in runner.calls)


def test_capture_pane_asks_for_the_requested_scrollback() -> None:
    runner = FakeRunner(stdout={"capture-pane": "line one\nline two\n"})
    text = Tmux(prefix="hr-", run=runner).capture_pane("vessel", lines=40)
    assert text == "line one\nline two\n"
    assert "-40" in runner.calls[-1]


def test_send_keys_passes_each_key_as_its_own_argument() -> None:
    runner = FakeRunner()
    Tmux(prefix="hr-", run=runner).send_keys("vessel", "/exit", "Enter")
    assert runner.calls[-1] == [
        "tmux",
        "send-keys",
        "-t",
        "=hr-vessel:",
        "/exit",
        "Enter",
    ]
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_tmux.py -v`
Expected: FAIL with `ImportError: cannot import name 'NotOurSession' from 'hitchrail.tmux'`.

- [ ] **Step 3: Implement**

Replace the stub `src/hitchrail/tmux.py` with:

```python
"""A thin tmux adapter.

Every method here exists to encode one non obvious tmux behaviour. Read the
comments before changing any of the target string construction: each one cost
real debugging to find and is invisible from the outside.
"""

from __future__ import annotations

import hashlib
import subprocess
from collections.abc import Callable

Runner = Callable[[list[str]], "subprocess.CompletedProcess[str]"]

_UNSAFE = str.maketrans({".": "-", ":": "-"})


class NotOurSession(ValueError):
    """Refusing to touch a session this instance did not create."""


def sanitize(name: str) -> str:
    """Make a project name addressable as a tmux session, one to one.

    tmux reads '.' and ':' as window and pane separators in a target spec, so a
    session called `dotted.site` can be created and then never addressed again,
    which reads as the session vanishing.

    The digest suffix is the part that is easy to leave out and expensive to
    leave out. A plain replacement maps both `a.b` and `a-b` onto `a-b`, so two
    folders share one tmux session: one reads as running because the other is,
    and stopping one kills the other's agent. Six hex characters of blake2b
    over the original name keeps the mapping injective, and it is deterministic
    so a session survives a restart of Hitchrail.
    """
    safe = name.translate(_UNSAFE)
    if safe == name:
        return safe
    digest = hashlib.blake2b(name.encode(), digest_size=3).hexdigest()
    return f"{safe}-{digest}"


def _default_runner(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, capture_output=True, text=True, check=False)


class Tmux:
    def __init__(
        self,
        prefix: str,
        socket: str | None = None,
        run: Runner | None = None,
    ) -> None:
        self.prefix = prefix
        self.socket = socket
        self._run: Runner = run or _default_runner

    def _argv(self, *args: str) -> list[str]:
        base = ["tmux"]
        if self.socket:
            base += ["-S", self.socket]
        return base + list(args)

    # -- naming --------------------------------------------------------

    def session_name(self, project: str) -> str:
        return f"{self.prefix}{sanitize(project)}"

    def session_target(self, project: str) -> str:
        """'=' anchors an exact match. Without it `hr-vessel` prefix matches
        `hr-vessel-social`, and a stopped project reads as running."""
        return f"={self.session_name(project)}"

    def pane_target(self, project: str) -> str:
        """list-panes takes a PANE target, ignores a leading '=', and falls
        back to prefix matching. The trailing ':' qualifies the string as a
        session, which is what makes the anchor take effect."""
        return f"={self.session_name(project)}:"

    # -- reading -------------------------------------------------------

    def has_session(self, project: str) -> bool:
        argv = self._argv("has-session", "-t", self.session_target(project))
        return self._run(argv).returncode == 0

    def pane_pids(self) -> dict[str, int]:
        """Every session we own, mapped to its first pane's pid, in ONE call.

        The engine asks this once per list, not once per project. Doing it per
        project is a subprocess spawn per row, which at the row counts the
        design draws is the difference between a page load and a stall.
        """
        result = self._run(
            self._argv("list-panes", "-a", "-F", "#{session_name} #{pane_pid}")
        )
        if result.returncode != 0:
            return {}  # no server running is normal, not an error
        found: dict[str, int] = {}
        for line in result.stdout.splitlines():
            name, _, raw_pid = line.partition(" ")
            if not name.startswith(self.prefix) or name in found:
                continue
            try:
                found[name] = int(raw_pid)
            except ValueError:
                continue
        return found

    def pane_pid(self, project: str) -> int | None:
        """One session's pane pid. For the detail paths; `pane_pids` for lists."""
        result = self._run(
            self._argv("list-panes", "-t", self.pane_target(project), "-F", "#{pane_pid}")
        )
        if result.returncode != 0:
            return None
        first = result.stdout.split()
        if not first:
            return None
        try:
            return int(first[0])
        except ValueError:
            return None

    def capture_pane(self, project: str, lines: int = 40) -> str:
        result = self._run(
            self._argv(
                "capture-pane", "-p", "-J", "-S", f"-{lines}", "-t", self.pane_target(project)
            )
        )
        return result.stdout if result.returncode == 0 else ""

    # -- writing -------------------------------------------------------

    def new_session(self, project: str, cwd: str, argv: list[str]) -> None:
        self._run(
            self._argv("new-session", "-d", "-s", self.session_name(project), "-c", cwd, *argv)
        )

    def kill_session(self, project: str) -> None:
        """Scoped, always. There is no code path here that reaches kill-server."""
        name = self.session_name(project)
        if not name.startswith(self.prefix) or "/" in project:
            raise NotOurSession(project)
        self._run(self._argv("kill-session", "-t", self.session_target(project)))

    def send_keys(self, project: str, *keys: str) -> None:
        """Each key is its own argument, because tmux distinguishes `C-c` the
        key from `C-c` the literal text by argument position, never by quoting.
        What to send is Claude Code's business and lives in claude_ipc."""
        self._run(self._argv("send-keys", "-t", self.pane_target(project), *keys))
```

- [ ] **Step 4: Run to verify passing**

Run: `uv run pytest tests/test_tmux.py -v`
Expected: PASS, 20 tests. Count them from the output rather than trusting this line.

- [ ] **Step 5: Gates and commit**

```bash
uv run ruff check && uv run ruff format --check && uv run mypy && uv run lint-imports
git add src/hitchrail/tmux.py tests/test_tmux.py
git commit -m "feat(tmux): adapter with injective naming and a one call pane map"
```

---

### Task 8: The process table adapter

**Files:**
- Modify: `src/hitchrail/procs.py`
- Test: `tests/test_procs.py`

**Interfaces:**
- Consumes: `Runner` from `hitchrail.tmux` (Task 7).
- Produces: frozen dataclass `Proc(pid: int, ppid: int, rss_kb: int, etime_s: int, args: str)`; `parse_ps(text: str) -> list[Proc]`; `snapshot(run: Runner | None = None) -> ProcTable`; class `ProcTable(procs: list[Proc])` with `by_pid: dict[int, Proc]`, `children(pid: int) -> list[Proc]`, `descendants(pid: int) -> list[Proc]`, `tree_rss_mb(pid: int) -> int`, `matching(marker: str) -> list[Proc]`, `first_matching_in_tree(pid: int, marker: str) -> Proc | None`.

- [ ] **Step 1: Write the failing tests**

`tests/test_procs.py`:

```python
from __future__ import annotations

import subprocess

from hitchrail.procs import Proc, ProcTable, parse_ps, snapshot

PS_OUTPUT = """\
  100     1  4096      600 /usr/bin/tmux new-session -d -s hr-a
  101   100 512000      600 claude --dangerously-skip-permissions --remote-control a
  102   101  20480      590 python3 helper.py
  200     1 480000      120 claude --dangerously-skip-permissions --remote-control orphan
  300     1   2048      999 /usr/bin/gedit notes.txt
"""


def table() -> ProcTable:
    return ProcTable(parse_ps(PS_OUTPUT))


def test_parses_every_row() -> None:
    procs = parse_ps(PS_OUTPUT)
    assert len(procs) == 5
    assert procs[1] == Proc(
        pid=101,
        ppid=100,
        rss_kb=512000,
        etime_s=600,
        args="claude --dangerously-skip-permissions --remote-control a",
    )


def test_args_containing_spaces_survive() -> None:
    assert parse_ps(PS_OUTPUT)[4].args == "/usr/bin/gedit notes.txt"


def test_blank_and_malformed_rows_are_skipped() -> None:
    assert parse_ps("\n  oops\n  1 2 3 4 ok\n") == [
        Proc(pid=1, ppid=2, rss_kb=3, etime_s=4, args="ok")
    ]


def test_a_row_with_no_args_is_skipped_rather_than_crashing() -> None:
    assert parse_ps("  1 2 3 4\n") == []


def test_children_and_descendants() -> None:
    t = table()
    assert [p.pid for p in t.children(100)] == [101]
    assert sorted(p.pid for p in t.descendants(100)) == [101, 102]


def test_tree_rss_sums_the_whole_subtree_in_megabytes() -> None:
    # 4096 + 512000 + 20480 kB is 524 MB after integer division.
    assert table().tree_rss_mb(100) == 524


def test_tree_rss_of_an_unknown_pid_is_zero() -> None:
    assert table().tree_rss_mb(9999) == 0


def test_a_cycle_in_the_table_does_not_hang() -> None:
    # ps is a snapshot of a moving target, and pid reuse can produce a row
    # whose ppid points back into its own subtree. An unguarded walk spins
    # forever, and it spins inside an HTTP request.
    cyclic = ProcTable(
        [
            Proc(pid=1, ppid=2, rss_kb=1, etime_s=1, args="a"),
            Proc(pid=2, ppid=1, rss_kb=1, etime_s=1, args="b"),
        ]
    )
    assert sorted(p.pid for p in cyclic.descendants(1)) == [1, 2]


def test_matching_finds_every_claude_anywhere() -> None:
    assert sorted(p.pid for p in table().matching("--remote-control")) == [101, 200]


def test_first_matching_in_tree_finds_a_child_not_just_the_root() -> None:
    found = table().first_matching_in_tree(100, "--remote-control")
    assert found is not None
    assert found.pid == 101


def test_first_matching_in_tree_returns_none_when_absent() -> None:
    assert table().first_matching_in_tree(300, "--remote-control") is None


def test_snapshot_asks_ps_for_etimes_not_etime() -> None:
    calls: list[list[str]] = []

    def runner(argv: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, PS_OUTPUT, "")

    assert len(snapshot(run=runner).by_pid) == 5
    # etimes is whole seconds. etime is a "1-02:03:04" string nobody should
    # be parsing, and the difference is invisible until a session runs a day.
    assert "pid,ppid,rss,etimes,args" in " ".join(calls[0])


def test_snapshot_of_a_failing_ps_is_empty_not_an_exception() -> None:
    def runner(argv: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 1, "", "ps: command not found")

    assert snapshot(run=runner).procs == []
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_procs.py -v`
Expected: FAIL with `ImportError: cannot import name 'Proc' from 'hitchrail.procs'`.

- [ ] **Step 3: Implement**

Replace the stub `src/hitchrail/procs.py` with:

```python
"""One snapshot of the process table, and the queries the engine asks of it."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field

from hitchrail.tmux import Runner


@dataclass(frozen=True)
class Proc:
    pid: int
    ppid: int
    rss_kb: int
    etime_s: int
    args: str


def parse_ps(text: str) -> list[Proc]:
    procs: list[Proc] = []
    for line in text.splitlines():
        parts = line.split(maxsplit=4)
        if len(parts) < 5:
            continue
        try:
            pid, ppid, rss, etimes = (int(p) for p in parts[:4])
        except ValueError:
            continue
        procs.append(Proc(pid=pid, ppid=ppid, rss_kb=rss, etime_s=etimes, args=parts[4]))
    return procs


def _default_runner(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, capture_output=True, text=True, check=False)


@dataclass
class ProcTable:
    procs: list[Proc]
    by_pid: dict[int, Proc] = field(init=False)
    _by_ppid: dict[int, list[Proc]] = field(init=False)

    def __post_init__(self) -> None:
        self.by_pid = {p.pid: p for p in self.procs}
        self._by_ppid = {}
        for p in self.procs:
            self._by_ppid.setdefault(p.ppid, []).append(p)

    def children(self, pid: int) -> list[Proc]:
        return list(self._by_ppid.get(pid, ()))

    def descendants(self, pid: int) -> list[Proc]:
        """Guarded against cycles, which a snapshot of a moving table can hold.

        ps reads a table that is changing under it, and pid reuse can produce a
        row whose ppid points back into its own subtree. An unguarded walk spins
        forever, and it does it inside an HTTP request.
        """
        out: list[Proc] = []
        seen: set[int] = {pid}
        stack = self.children(pid)
        while stack:
            proc = stack.pop()
            if proc.pid in seen:
                continue
            seen.add(proc.pid)
            out.append(proc)
            stack.extend(self.children(proc.pid))
        return out

    def tree_rss_mb(self, pid: int) -> int:
        root = self.by_pid.get(pid)
        if root is None:
            return 0
        total_kb = root.rss_kb + sum(p.rss_kb for p in self.descendants(pid))
        return total_kb // 1024

    def matching(self, marker: str) -> list[Proc]:
        return [p for p in self.procs if marker in p.args]

    def first_matching_in_tree(self, pid: int, marker: str) -> Proc | None:
        root = self.by_pid.get(pid)
        if root is not None and marker in root.args:
            return root
        for proc in self.descendants(pid):
            if marker in proc.args:
                return proc
        return None


def snapshot(run: Runner | None = None) -> ProcTable:
    runner = run or _default_runner
    result = runner(["ps", "-eo", "pid,ppid,rss,etimes,args", "--no-headers"])
    if result.returncode != 0:
        # No process table is a state we can report honestly. Guessing "nothing
        # is running" from a failed ps would say every session is stopped.
        return ProcTable([])
    return ProcTable(parse_ps(result.stdout))
```

The cycle guard adds `pid` itself to `seen` before walking, which is why the
cyclic test expects the walk to return both rows once and then stop.

- [ ] **Step 4: Run to verify passing**

Run: `uv run pytest tests/test_procs.py -v`
Expected: PASS, 13 tests.

- [ ] **Step 5: Gates and commit**

```bash
uv run ruff check && uv run ruff format --check && uv run mypy && uv run lint-imports
git add src/hitchrail/procs.py tests/test_procs.py
git commit -m "feat(procs): process table snapshot with a cycle safe subtree walk"
```

---

### Task 9: The Claude Code quarantine

**Files:**
- Modify: `src/hitchrail/claude_ipc.py`
- Test: `tests/test_claude_ipc.py`

**Interfaces:**
- Consumes: nothing.
- Produces: constant `REMOTE_CONTROL_MARKER = "--remote-control"`; constant `GRACEFUL_STOP_KEYS: tuple[tuple[str, ...], ...]`; `launch_argv(binary: str, project: str) -> list[str]`; `bridge_url(pid: int, sessions_dir: Path) -> str | None`; `session_url(pid: int, sessions_dir: Path, pane_text: str | None = None) -> str | None`.

Everything in this module depends on undocumented Claude Code internals. It is
the only module allowed to know about them, so a breaking change upstream
touches one file and the interface degrades to `pending` rather than reporting
something false.

`GRACEFUL_STOP_KEYS` belongs here and not in the engine. The first draft put the
literal `"/exit"` in `engine.py`, which is exactly the boundary this module
exists to hold, and the import contract cannot catch it because it is a string
rather than an import.

- [ ] **Step 1: Write the failing tests**

`tests/test_claude_ipc.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from hitchrail.claude_ipc import (
    GRACEFUL_STOP_KEYS,
    REMOTE_CONTROL_MARKER,
    bridge_url,
    launch_argv,
    session_url,
)


def test_launch_argv_carries_the_marker_we_identify_sessions_by() -> None:
    argv = launch_argv("claude", "vessel")
    assert argv[0] == "claude"
    assert REMOTE_CONTROL_MARKER in argv
    assert argv[-1] == "vessel"


def test_launch_argv_is_a_list_of_separate_arguments() -> None:
    # Not "no spaces in any element": a future argument may legitimately hold
    # one. What matters is that nothing is a joined command string, so there is
    # nothing for a shell to reinterpret even if one were reintroduced.
    argv = launch_argv("claude", "vessel")
    assert isinstance(argv, list)
    assert all(isinstance(a, str) for a in argv)
    assert "--dangerously-skip-permissions" in argv


def test_the_graceful_stop_sequence_is_what_a_person_would_type() -> None:
    # Two interrupts, then the exit command. Each tuple is one send-keys call,
    # because tmux distinguishes the key C-c from the literal text C-c by
    # argument position.
    assert GRACEFUL_STOP_KEYS == (("C-c",), ("C-c",), ("/exit", "Enter"))


def test_state_file_supplies_the_url_verbatim(tmp_path: Path) -> None:
    (tmp_path / "42.json").write_text(
        json.dumps({"bridgeSessionId": "session_01Kx2c8zfkvZsKR1kZjpTX1G"})
    )
    assert session_url(42, tmp_path) == (
        "https://claude.ai/code/session_01Kx2c8zfkvZsKR1kZjpTX1G"
    )


def test_the_session_prefix_is_not_added_twice(tmp_path: Path) -> None:
    (tmp_path / "42.json").write_text(json.dumps({"bridgeSessionId": "session_abc"}))
    assert session_url(42, tmp_path, None) == "https://claude.ai/code/session_abc"


def test_missing_state_file_falls_back_to_the_pane(tmp_path: Path) -> None:
    pane = "welcome\nhttps://claude.ai/code/session_fallback\n$ "
    assert session_url(9, tmp_path, pane) == "https://claude.ai/code/session_fallback"


def test_pane_fallback_takes_the_last_url(tmp_path: Path) -> None:
    pane = "https://claude.ai/code/session_old\nhttps://claude.ai/code/session_new\n"
    assert session_url(9, tmp_path, pane) == "https://claude.ai/code/session_new"


def test_unreadable_state_file_does_not_raise(tmp_path: Path) -> None:
    (tmp_path / "7.json").write_text("{not json")
    assert session_url(7, tmp_path, None) is None


def test_a_state_file_that_is_not_an_object_does_not_raise(tmp_path: Path) -> None:
    (tmp_path / "8.json").write_text('["a list"]')
    assert session_url(8, tmp_path, None) is None


def test_a_non_string_session_id_is_refused(tmp_path: Path) -> None:
    (tmp_path / "9.json").write_text(json.dumps({"bridgeSessionId": 12345}))
    assert bridge_url(9, tmp_path) is None


def test_a_session_id_with_a_separator_is_refused(tmp_path: Path) -> None:
    # This value is interpolated into a URL. It is an undocumented internal
    # read off disk, which makes it untrusted input no matter who wrote it.
    (tmp_path / "10.json").write_text(json.dumps({"bridgeSessionId": "../../evil"}))
    assert bridge_url(10, tmp_path) is None


def test_a_session_id_carrying_a_scheme_is_refused(tmp_path: Path) -> None:
    (tmp_path / "11.json").write_text(
        json.dumps({"bridgeSessionId": "https://evil.example/x"})
    )
    assert bridge_url(11, tmp_path) is None


def test_bridge_url_refuses_the_pane_fallback(tmp_path: Path) -> None:
    # bridge_url answers "is there a live bridge", so a URL that merely
    # appeared as text in the terminal must not count.
    assert bridge_url(9, tmp_path) is None


def test_no_url_anywhere_is_none(tmp_path: Path) -> None:
    assert session_url(9, tmp_path, "nothing here") is None
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_claude_ipc.py -v`
Expected: FAIL with `ImportError: cannot import name 'GRACEFUL_STOP_KEYS' from 'hitchrail.claude_ipc'`.

- [ ] **Step 3: Implement**

Replace the stub `src/hitchrail/claude_ipc.py` with:

```python
"""Everything that knows about Claude Code's internals.

UNSTABLE. None of this is a documented interface. `~/.claude/sessions/<pid>.json`
and its `bridgeSessionId` key are implementation details that can change or
disappear in any Claude Code release. They are quarantined here so that when
they do, exactly one module needs fixing and the rest of Hitchrail degrades to
reporting "pending" rather than reporting something false.

Verified against claude 2.1.205: the state file held
  "bridgeSessionId":"session_01Kx2c8zfkvZsKR1kZjpTX1G"
and the terminal printed
  https://claude.ai/code/session_01Kx2c8zfkvZsKR1kZjpTX1G
so the value is the URL path segment verbatim, `session_` prefix included. Do
not add one.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REMOTE_CONTROL_MARKER = "--remote-control"
URL_BASE = "https://claude.ai/code/"

# What a person would type to end a session politely: interrupt whatever is
# running, twice, then ask it to exit. Each tuple is ONE send-keys invocation,
# because tmux distinguishes the key `C-c` from the literal text `C-c` by
# argument position rather than by quoting.
#
# This lives here rather than in the engine even though it looks like engine
# logic. It is knowledge about how Claude Code behaves at a terminal, and the
# import contract cannot catch a string that wanders out of this module.
GRACEFUL_STOP_KEYS: tuple[tuple[str, ...], ...] = (("C-c",), ("C-c",), ("/exit", "Enter"))

_URL_RE = re.compile(r"https://claude\.ai/code/[A-Za-z0-9_-]+")
# The session id becomes a URL path segment. Anything outside this alphabet is
# refused rather than escaped: we are reading an undocumented file off disk, so
# the value is untrusted input regardless of who is expected to have written it.
_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def launch_argv(binary: str, project: str) -> list[str]:
    return [binary, "--dangerously-skip-permissions", REMOTE_CONTROL_MARKER, project]


def bridge_url(pid: int, sessions_dir: Path) -> str | None:
    """The URL according to Claude's own state file, or nothing.

    Stricter than session_url on purpose: this answers "is there a live
    bridge", so the terminal fallback is not acceptable here. It is also the
    cheap one, because it reads a file rather than capturing a pane, which is
    why list rendering uses this and not session_url.
    """
    state = sessions_dir / f"{pid}.json"
    try:
        data = json.loads(state.read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    session_id = data.get("bridgeSessionId")
    if not isinstance(session_id, str) or not _SESSION_ID_RE.match(session_id):
        return None
    return f"{URL_BASE}{session_id}"


def session_url(pid: int, sessions_dir: Path, pane_text: str | None = None) -> str | None:
    """Good enough for a status column, and more expensive than it looks.

    Falls back to scraping the terminal, which can pick up a URL that merely
    arrived as message text rather than one belonging to a live bridge. Fine
    for display, useless for deciding anything. Use bridge_url for decisions,
    and for anything rendered per row in a list.
    """
    from_state = bridge_url(pid, sessions_dir)
    if from_state:
        return from_state
    if not pane_text:
        return None
    found = _URL_RE.findall(pane_text)
    return found[-1] if found else None
```

- [ ] **Step 4: Run to verify passing**

Run: `uv run pytest tests/test_claude_ipc.py -v`
Expected: PASS, 14 tests.

- [ ] **Step 5: Gates and commit**

```bash
uv run ruff check && uv run ruff format --check && uv run mypy && uv run lint-imports
git add src/hitchrail/claude_ipc.py tests/test_claude_ipc.py
git commit -m "feat(claude-ipc): quarantine the bridge lookup and the stop sequence"
```

---

### Task 10: The memory guard

**Files:**
- Modify: `src/hitchrail/ram.py`
- Test: `tests/test_ram.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `read_meminfo(path: Path = Path("/proc/meminfo")) -> str`; `available_mb(meminfo_text: str) -> int`; `StrEnum Verdict` with members `OK`, `SOFT`, `HARD`; `guard(available_mb: int, need_mb: int, hard_mb: int, soft_mb: int) -> Verdict`.

- [ ] **Step 1: Write the failing tests**

`tests/test_ram.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from hitchrail.ram import Verdict, available_mb, guard, read_meminfo

MEMINFO = """\
MemTotal:       32729088 kB
MemFree:        16868352 kB
MemAvailable:   25198592 kB
Buffers:          123456 kB
"""


def test_reads_mem_available_not_mem_free() -> None:
    # MemFree is not the number a person means by "free memory": it excludes
    # reclaimable cache, so it reads far lower and would refuse starts on a
    # machine with plenty of room.
    assert available_mb(MEMINFO) == 24608


def test_missing_mem_available_is_zero_not_a_crash() -> None:
    assert available_mb("MemTotal: 100 kB\n") == 0


def test_read_meminfo_of_a_missing_file_is_empty(tmp_path: Path) -> None:
    assert read_meminfo(tmp_path / "nope") == ""


@pytest.mark.parametrize(
    ("available", "expected"),
    [
        (24608, Verdict.OK),
        (5000, Verdict.OK),
        (4608, Verdict.OK),
        (4607, Verdict.SOFT),
        (3072, Verdict.SOFT),
        (3071, Verdict.HARD),
        (0, Verdict.HARD),
    ],
)
def test_guard_thresholds(available: int, expected: Verdict) -> None:
    # Starting costs 1536 MB. The decision is about what is LEFT afterwards:
    # below 1536 MB remaining we refuse outright, below 3072 MB we ask first.
    assert guard(available, need_mb=1536, hard_mb=1536, soft_mb=3072) is expected


def test_hard_floor_is_about_what_is_left_after_starting() -> None:
    # 3000 free, 1536 needed, leaves 1464, which is under the 1536 hard floor.
    assert guard(3000, need_mb=1536, hard_mb=1536, soft_mb=0) is Verdict.HARD


def test_a_zero_reading_refuses_rather_than_permitting() -> None:
    # available_mb returns 0 when it cannot read /proc/meminfo. Failing open
    # here would mean an unreadable machine always permits a start.
    assert guard(0, need_mb=1536, hard_mb=1536, soft_mb=3072) is Verdict.HARD


def test_verdict_serialises_as_its_name() -> None:
    assert str(Verdict.SOFT) == "soft"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_ram.py -v`
Expected: FAIL with `ImportError: cannot import name 'Verdict' from 'hitchrail.ram'`.

- [ ] **Step 3: Implement**

Replace the stub `src/hitchrail/ram.py` with:

```python
"""Memory readings, and the decision about whether starting is wise.

The thresholds are not academic. A machine that runs out of memory here does
not degrade: the kernel reaps a whole tmux scope and a live agent disappears
mid task. A web interface makes starting one tap, so the guard matters more
here than it does behind a CLI.
"""

from __future__ import annotations

import re
from enum import StrEnum
from pathlib import Path

_AVAILABLE_RE = re.compile(r"^MemAvailable:\s+(\d+)\s+kB", re.MULTILINE)


class Verdict(StrEnum):
    OK = "ok"
    SOFT = "soft"
    HARD = "hard"


def read_meminfo(path: Path = Path("/proc/meminfo")) -> str:
    try:
        return path.read_text()
    except OSError:
        return ""


def available_mb(meminfo_text: str) -> int:
    """MemAvailable, not MemFree.

    MemFree excludes reclaimable page cache, so on a healthy machine it reads
    far lower than the memory actually obtainable, and a guard built on it
    refuses starts that would have been fine. Returns 0 when the field is
    absent, which the guard reads as a refusal rather than as permission.
    """
    match = _AVAILABLE_RE.search(meminfo_text)
    return int(match.group(1)) // 1024 if match else 0


def guard(available_mb: int, need_mb: int, hard_mb: int, soft_mb: int) -> Verdict:
    """Decide against what would be LEFT after starting, not what is free now."""
    remaining = available_mb - need_mb
    if remaining < hard_mb:
        return Verdict.HARD
    if remaining < soft_mb:
        return Verdict.SOFT
    return Verdict.OK
```

- [ ] **Step 4: Run to verify passing**

Run: `uv run pytest tests/test_ram.py -v`
Expected: PASS, 13 tests (6 plain plus one parametrised case with 7 values).

- [ ] **Step 5: Gates and commit**

```bash
uv run ruff check && uv run ruff format --check && uv run mypy && uv run lint-imports
git add src/hitchrail/ram.py tests/test_ram.py
git commit -m "feat(ram): memory guard deciding on what is left after starting"
```

---

## Phase 3 exit criteria

- [ ] All five gates green on 3.11, 3.12 and 3.13.
- [ ] Each of the four ADDRESSING footguns in the design's section 4.2 (1, 2, 3 and 5) has a named regression test that fails if its workaround is removed, and `sanitize` is proven injective. Footgun 4, serialising concurrent starts, is deliberately not this phase's: there is nothing here to serialise, because starting is an engine operation. It is Phase 4 Task 13 and carries its own exit criterion there. This criterion used to say "every footgun in section 4.2", which no Phase 3 implementation could satisfy.
- [ ] `Tmux.pane_pids()` issues exactly one subprocess call regardless of session count.
- [ ] No method on `Tmux` can reach `kill-server`, and every call carries the configured socket when one is set.
- [ ] A cyclic process table does not hang `descendants`.
- [ ] A failed `ps` yields an empty table rather than an exception, and never reads as "nothing is running".
- [ ] `bridge_url` refuses a non string, a separator, and a scheme in `bridgeSessionId`.
- [ ] `GRACEFUL_STOP_KEYS` lives in `claude_ipc` and nowhere else. `grep -rn '"/exit"' src/` returns one file.
- [ ] `guard(0, ...)` is `HARD`.

When these hold, start Phase 4 from `docs/roadmap.md`.
