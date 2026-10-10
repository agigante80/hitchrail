"""Task 267: a root of each agent on one engine, on a private tmux server.

The hermetic tier proves which package derivation names and whose keys a
stop types, against fakes. This proves what a fake cannot: that each
package's argv really starts a pane, that the process table derivation reads
tells the two agents apart by their real command lines, and that each
package's keys and screen reader really end the agent they were written for.

The two agents are stand ins drawing the screens each package reads, as
captured and quoted on #294 (agy) and in `claude_ipc.screen` (Claude Code).
Same isolation as `test_live_tmux`: `env -u TMUX`, an explicit socket,
prefixed sessions only, and no `kill-server` anywhere.
"""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Callable
from pathlib import Path

import pytest

import test_live_tmux as live
from conftest import REAL_CWD_OF, REAL_PIDFD
from hitchrail import agy_ipc, claude_ipc
from hitchrail.agentconfig import DEFAULT_AGENT, AgentSpec
from hitchrail.config import Config
from hitchrail.engine import Engine
from hitchrail.roots import Root
from hitchrail.sessions import State
from hitchrail.tmux import Tmux
from support import Orphan
from test_live_tmux import PLENTY, PREFIX, PrivateTmux, live_project

pytestmark = pytest.mark.live_tmux

server = live.server

# The idle and busy input rows `claude_ipc.screen` reads. On a line it draws
# the busy row, "works", writes `handoff.md`, and draws the idle row LAST,
# because the tty's echo of the typed line lands under the previous one. The
# 0x1b of the Escape the stop sequence leads with arrives at the head of the
# `/exit` line, so the line is read after its last Escape.
CLAUDE = f"""#!{sys.executable}
import sys, time
IDLE = "\\x1b[39m\\u276f\\u00a0                     "
BUSY = "\\x1b[38;5;246m\\u276f\\u00a0\\x1b[39m                     "
print(IDLE, flush=True)
while True:
    line = sys.stdin.readline()
    if line == "":
        time.sleep(0.2)
        continue
    line = line.rsplit("\\x1b", 1)[-1].strip()
    if line == "/exit":
        sys.exit(0)
    if not line:
        continue
    print(BUSY, flush=True)
    time.sleep(1)
    open("handoff.md", "w").write("claude\\n")
    print(IDLE, flush=True)
"""

# agy 1.3.3's box as quoted on #294: a `>` row between two grey rules, and a
# footer that says `? for shortcuts` when idle and `esc to cancel` while a
# turn runs. The whole box is redrawn under the echo for the same reason as
# above. agy's stop sends no Escape, so `/exit` arrives as a plain line, and a
# line still carrying Claude Code's Escape is not an exit: typing the other
# package's keys was seen failing the polite stop below.
AGY = f"""#!{sys.executable}
import sys, time
RULE = "\\x1b[90m" + "\\u2500" * 40 + "\\x1b[39m"
def draw(footer):
    print(RULE, flush=True)
    print("\\x1b[94m>\\x1b[39m ", flush=True)
    print(RULE, flush=True)
    print("  " + footer, flush=True)
draw("? for shortcuts")
while True:
    line = sys.stdin.readline()
    if line == "":
        time.sleep(0.2)
        continue
    line = line.strip()
    if line == "/exit":
        sys.exit(0)
    if not line:
        continue
    draw("esc to cancel")
    time.sleep(1)
    open("handoff.md", "w").write("agy\\n")
    draw("? for shortcuts")
"""

CLAUDE_ROOT = "cc"
AGY_ROOT = "ag"
_BOX = {CLAUDE_ROOT: "\u276f", AGY_ROOT: "? for shortcuts"}


class TwoRoots:
    """One engine over a root of each agent, one project in each."""

    def __init__(
        self, server: PrivateTmux, tmp_path: Path, stop_prompt: str | None = None
    ) -> None:
        self.project = live_project("vessel")
        self.folders: dict[str, Path] = {}
        roots = []
        for label, agent in ((CLAUDE_ROOT, DEFAULT_AGENT), (AGY_ROOT, "agy")):
            path = (tmp_path / label).resolve()
            (path / self.project).mkdir(parents=True)
            self.folders[label] = path / self.project
            roots.append(Root(label, path, agent=agent))
        sessions = tmp_path / "sessions"
        sessions.mkdir()
        self.binaries = {
            DEFAULT_AGENT: self._shim(server, "claude-shim", CLAUDE),
            "agy": self._shim(server, "agy-shim", AGY),
        }
        # Claude Code's trust map, trusting both folders, so no row carries a
        # warning this test is not about.
        trust = tmp_path / "claude.json"
        projects = {str(f): {"hasTrustDialogAccepted": True} for f in self.folders.values()}
        trust.write_text(json.dumps({"projects": projects}))
        self.engine = Engine(
            config=Config(
                roots=tuple(roots),
                agents={"agy": AgentSpec("antigravity", str(self.binaries["agy"]))},
                agent_binary=str(self.binaries[DEFAULT_AGENT]),
                session_prefix=PREFIX,
                sessions_dir=sessions,
                agent_config_path=trust,
                stop_prompt=stop_prompt,
            ),
            tmux=Tmux(prefix=PREFIX, socket=server.socket),
            meminfo_fn=lambda: PLENTY,
            cwd_of=REAL_CWD_OF,
            **REAL_PIDFD,
        )
        self.server = server

    @staticmethod
    def _shim(server: PrivateTmux, name: str, body: str) -> Path:
        shim = Path(server._dir) / name
        shim.write_text(body)
        shim.chmod(0o755)
        return shim

    def name(self, label: str) -> str:
        return f"{label}~{self.project}"

    def drawn(self, label: str) -> bool:
        """Whether the stand in has drawn its box, so a stop is not typed at
        a pane whose agent is not up yet."""
        target = f"={PREFIX}{self.name(label)}:"
        text = _BOX[label]
        return _until(
            lambda: text in self.server.run("capture-pane", "-p", "-t", target).stdout
        )

    def reaches(self, label: str, state: State, seconds: float = 15.0) -> bool:
        name = self.name(label)
        return _until(lambda: self.engine.get(name).state is state, seconds)

    def start(self, label: str) -> None:
        name = self.name(label)
        self.engine.start(name)
        self.server.created.append(f"{PREFIX}{name}")


def _until(predicate: Callable[[], bool], seconds: float = 15.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.1)
    return False


def _start_both(machine: TwoRoots) -> None:
    for label in (CLAUDE_ROOT, AGY_ROOT):
        machine.start(label)
    for label, agent in ((CLAUDE_ROOT, DEFAULT_AGENT), (AGY_ROOT, "agy")):
        name = machine.name(label)
        assert machine.reaches(label, State.RUNNING), label
        row = machine.engine.get(name)
        assert row.agent == agent and row.awaiting_trust is False, row
        assert machine.drawn(label), label


def test_a_root_of_each_agent_starts_and_stops_politely(
    server: PrivateTmux, tmp_path: Path
) -> None:
    """Each pane runs its own root's binary with its own package's argv, and
    each Stop ends its agent through that package's keys: Claude Code's
    sequence sends an Escape before `/exit`, agy's does not, and agy's stand
    in does not exit on Claude Code's."""
    machine = TwoRoots(server, tmp_path)
    _start_both(machine)
    for label, binary, argv in (
        (CLAUDE_ROOT, DEFAULT_AGENT, "--remote-control"),
        (AGY_ROOT, "agy", f"--add-dir={machine.folders[AGY_ROOT]}"),
    ):
        pid = machine.engine.get(machine.name(label)).pid
        cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
        assert str(machine.binaries[binary]).encode() in cmdline, label
        assert argv.encode() in cmdline, label

    for label in (CLAUDE_ROOT, AGY_ROOT):
        machine.engine.stop(machine.name(label))
    for label in (CLAUDE_ROOT, AGY_ROOT):
        assert machine.reaches(label, State.STOPPED), (
            f"{label} never exited on its own package's keys"
        )
    assert machine.engine.expire_stops() == []


def test_a_root_of_each_agent_wraps_up_before_it_exits(
    server: PrivateTmux, tmp_path: Path
) -> None:
    """With a closing message, each Stop types it, each package's watch reads
    its own agent's screen to see the turn end, and only then is the exit
    sent. `handoff.md` is the turn having run before the exit."""
    machine = TwoRoots(server, tmp_path, stop_prompt="/wrapup")
    _start_both(machine)
    for label in (CLAUDE_ROOT, AGY_ROOT):
        machine.engine.stop(machine.name(label))

    moved: list[str] = []

    def both_moved() -> bool:
        moved.extend(machine.engine.advance_wrap_ups())
        return len(moved) == 2

    assert _until(both_moved, seconds=30), f"only {moved} reached the exit"
    assert sorted(moved) == sorted(machine.name(label) for label in (CLAUDE_ROOT, AGY_ROOT))
    for label, wrote in ((CLAUDE_ROOT, "claude"), (AGY_ROOT, "agy")):
        assert machine.reaches(label, State.STOPPED), label
        assert (machine.folders[label] / "handoff.md").read_text() == f"{wrote}\n"


def test_a_root_of_each_agent_is_derived_stale_and_detached(
    server: PrivateTmux, tmp_path: Path
) -> None:
    """Stale: a prefixed session with no agent in it, under each root.
    Detached: each agent's real command line with no pane above it, and each
    row names the agent whose argv it is, which is what a Kill asks."""
    machine = TwoRoots(server, tmp_path)
    for label in (CLAUDE_ROOT, AGY_ROOT):
        machine.server.new_session(f"{PREFIX}{machine.name(label)}")
    for label in (CLAUDE_ROOT, AGY_ROOT):
        assert machine.reaches(label, State.STALE), label
    for label in (CLAUDE_ROOT, AGY_ROOT):
        session = f"{PREFIX}{machine.name(label)}"
        assert machine.server.run("kill-session", "-t", f"={session}").returncode == 0
        machine.server.created.remove(session)

    argv = {
        CLAUDE_ROOT: claude_ipc.launch_argv(
            str(machine.binaries[DEFAULT_AGENT]), machine.name(CLAUDE_ROOT)
        ),
        AGY_ROOT: agy_ipc.Antigravity().launch_argv(
            str(machine.binaries["agy"]), machine.name(AGY_ROOT), machine.folders[AGY_ROOT]
        ),
    }
    orphans = {label: Orphan(argv[label], cwd=machine.folders[label]) for label in argv}
    try:
        for label, agent in ((CLAUDE_ROOT, DEFAULT_AGENT), (AGY_ROOT, "agy")):
            name = machine.name(label)
            assert machine.reaches(label, State.DETACHED), label
            row = machine.engine.get(name)
            assert row.pid == orphans[label].pid, f"{label} took the other root's orphan"
            assert row.agent == agent
            machine.engine.signal_detached(name)
            assert orphans[label].wait(timeout=5) == 0, f"{label} is still running"
            assert machine.reaches(label, State.STOPPED), label
    finally:
        for orphan in orphans.values():
            orphan.close()
