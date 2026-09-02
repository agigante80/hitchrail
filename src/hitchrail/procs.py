"""One process table snapshot, and the queries the engine asks of it.

A snapshot rather than live queries, because the engine derives every session's
state from one table. Asking the operating system per project means the answers
can disagree inside a single refresh: a process alive for one question and dead
for the next, so a session reads as both running and stopped.

Verified against procps-ng 4.0.4 on this machine before the parser was written:
`ps -eww -o pid,ppid,rss,etimes,args --no-headers` yields those five columns in
that order. `etimes` is seconds; `etime` is `[[dd-]hh:]mm:ss` and parsing a
duration format is a bug farm, so the numeric column is the one to ask for.

This module is in the engine layer and imports nothing from the web layer;
`lint-imports` enforces it.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field

from hitchrail.tmux import Runner

# `-ww` is unlimited width, and it is load bearing rather than tidy.
#
# `ps` truncates the command line to the TERMINAL WIDTH, and the part it cuts
# is the end of the argv, which is exactly where the agent's own marker and
# the project name live. Without this, a live agent under a long path derives as `stale` and a
# detached one is never found at all, so its row reads `stopped` and offers to
# Start: a second agent in a folder that already has one, which is the failure
# section 4.1 exists to prevent.
#
# Measured on a real machine at 80 columns: eight agents visible without it,
# twelve with. Four running sessions were absent, not mislabelled.
#
# Doubled deliberately. A single `-w` widens to 132 columns, which moves the
# cliff rather than removing it. See #65.
PS_ARGV = ["ps", "-eww", "-o", "pid,ppid,rss,etimes,args", "--no-headers"]

# ps reports rss in kilobytes. Everything above this module works in MB.
_KB_PER_MB = 1024

# pid, ppid, rss, etimes, then the command line, which holds spaces and is
# therefore never tokenised.
_FIXED_COLUMNS = 4


@dataclass(frozen=True)
class Proc:
    """One row. `args` is the untokenised command line, spaces and all."""

    pid: int
    ppid: int
    rss_kb: int
    etime_s: int
    args: str


def parse_ps(text: str) -> list[Proc]:
    """Rows to `Proc`, skipping anything that does not parse.

    A malformed row is dropped rather than fatal: `ps` output is read from a
    table changing under it, and one unreadable line must not lose the rest.

    `maxsplit` keeps the command line intact. Tokenising it would lose the
    spaces and quoting that the marker match depends on.
    """
    procs: list[Proc] = []
    for line in text.splitlines():
        parts = line.split(maxsplit=_FIXED_COLUMNS)
        if len(parts) <= _FIXED_COLUMNS:
            continue
        try:
            pid, ppid, rss, etimes = (int(p) for p in parts[:_FIXED_COLUMNS])
        except ValueError:
            continue
        procs.append(
            Proc(pid=pid, ppid=ppid, rss_kb=rss, etime_s=etimes, args=parts[_FIXED_COLUMNS])
        )
    return procs


# The same bound as the tmux adapter, for the same reason (#67): this runs in
# an HTTP handler, and `ps` blocks on a wedged filesystem the way tmux blocks on
# a busy server. Kept here rather than imported so each adapter states its own
# reason; they are the same today and need not stay so.
_CALL_TIMEOUT_S = 10.0


def _default_runner(
    argv: list[str], timeout: float = _CALL_TIMEOUT_S
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, capture_output=True, text=True, check=False, timeout=timeout)


@dataclass
class ProcTable:
    """A parsed snapshot with the lookups the engine needs, indexed once.

    `ok` is the difference between "nothing is running" and "we could not
    look". Collapsing them is a guard failing open, which
    `docs/tech-guidelines.md` control 7 forbids: rendering "no agents" when the
    truth is "ps failed" tells the user something false about their machine.
    A caller that shows an empty list must check `ok` first.
    """

    procs: list[Proc]
    ok: bool = True
    by_pid: dict[int, Proc] = field(init=False)
    _by_ppid: dict[int, list[Proc]] = field(init=False)

    def __post_init__(self) -> None:
        self.by_pid = {p.pid: p for p in self.procs}
        self._by_ppid = {}
        for proc in self.procs:
            self._by_ppid.setdefault(proc.ppid, []).append(proc)

    def children(self, pid: int) -> list[Proc]:
        return list(self._by_ppid.get(pid, ()))

    def descendants(self, pid: int) -> list[Proc]:
        """The subtree below `pid`, guarded against cycles.

        A snapshot of a moving table can hold one: `ps` reads rows over time,
        and pid reuse can produce a row whose ppid points back into its own
        subtree. An unguarded walk spins forever, and it does it on the event
        loop inside an HTTP request.

        The starting pid seeds `seen`, so a process that is its own parent
        terminates too.
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
        """Resident memory of a process and everything under it, in MB.

        The agent spawns helpers, so charging a session only its own rss
        under reports what stopping it would release.
        """
        root = self.by_pid.get(pid)
        if root is None:
            return 0
        total_kb = root.rss_kb + sum(p.rss_kb for p in self.descendants(pid))
        return total_kb // _KB_PER_MB

    def matching(self, marker: str) -> list[Proc]:
        """Every process whose command line carries the marker.

        The marker itself is Claude Code knowledge and lives in `claude_ipc`;
        this module only knows how to look for a substring.
        """
        return [p for p in self.procs if marker in p.args]

    def first_matching_in_tree(self, pid: int, marker: str) -> Proc | None:
        """The marked process at or below `pid`, or `None`.

        `None` rather than a falsy `Proc`: an object with a truthy type and
        empty fields is how a "not found" becomes a pid of 0 downstream.
        """
        root = self.by_pid.get(pid)
        if root is not None and marker in root.args:
            return root
        for proc in self.descendants(pid):
            if marker in proc.args:
                return proc
        return None


def snapshot(run: Runner | None = None) -> ProcTable:
    """One `ps` call, parsed. Never raises for a failed call.

    A failed `ps` yields an empty table with `ok=False` rather than an
    exception, so one bad call does not take the whole listing with it, and the
    caller can still tell that apart from an idle machine. That includes a `ps`
    that could not be EXECUTED, which raises rather than returning a code.
    """
    runner = run or _default_runner
    try:
        result = runner(PS_ARGV)
    except (OSError, subprocess.TimeoutExpired):
        # `subprocess.run` raises before there is a returncode when the binary
        # is absent or not executable: a container without procps, a broken
        # PATH. The docstring promises this never raises for a failed call, and
        # "could not be executed" is the most failed a call gets.
        #
        # A timeout joins it (#67). "It never answered" is as failed as "it
        # could not start", and both have to become `ok=False` rather than an
        # exception, or one wedged `ps` takes the whole listing with it.
        return ProcTable([], ok=False)
    if result.returncode != 0:
        return ProcTable([], ok=False)
    return ProcTable(parse_ps(result.stdout))
