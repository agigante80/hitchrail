"""#472: a real Restart on a private tmux, ending with a new pane pid.

The hermetic tier proves the order of events against fakes. This proves the
two premises a fake cannot: that the exit really reaches a pty and ends the
agent, and that a start after it makes a NEW pane under the SAME session name,
which only works because the dead pane, window and session are really gone by
then. The sweep is driven by hand, so nothing here waits on a timer.

Same isolation as `test_live_tmux`: `env -u TMUX`, an explicit socket, prefixed
sessions only, and no `kill-server` anywhere.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

import test_live_tmux as live
from hitchrail.engine import Engine
from hitchrail.sessions import State
from hitchrail.tmux import Tmux
from support import DEFAULT_LABEL, make_config
from test_live_tmux import PLENTY, PREFIX, PrivateTmux, live_project

pytestmark = pytest.mark.live_tmux

# The fixture, shared with the file whose premises these are.
server = live.server

# A stand in for the agent that draws the empty input row the stop sequence
# insists on seeing, and exits on `/exit` read from its pty. Python, because
# the e2e shim's reasons for it (a documented EOF, no shell dependence) hold.
AGENT = f"""#!{sys.executable}
import sys, time
print("\\x1b[39m\\u276f\\u00a0                     ", flush=True)
while True:
    line = sys.stdin.readline()
    if line == "":
        time.sleep(0.2)
        continue
    if line.rsplit("\\x1b", 1)[-1].strip() == "/exit":
        sys.exit(0)
"""


def _pane_pids(server: PrivateTmux) -> dict[str, int]:
    out = server.run("list-panes", "-a", "-F", "#{session_name} #{pane_pid}").stdout
    return {line.rsplit(" ", 1)[0]: int(line.rsplit(" ", 1)[1]) for line in out.splitlines()}


def _until(predicate, seconds: float = 15.0) -> bool:  # type: ignore[no-untyped-def]
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.1)
    return False


def test_a_real_restart_ends_with_a_new_pane_under_the_same_session_name(
    server: PrivateTmux,
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    project = live_project("vessel")
    (root / project).mkdir(parents=True)
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    agent = Path(server._dir) / "agent"
    agent.write_text(AGENT)
    agent.chmod(0o755)
    engine = Engine(
        config=make_config(
            root, agent_binary=str(agent), session_prefix=PREFIX, sessions_dir=sessions
        ),
        tmux=Tmux(prefix=PREFIX, socket=server.socket),
        meminfo_fn=lambda: PLENTY,
    )
    name = f"{DEFAULT_LABEL}~{project}"

    engine.start(name)
    assert _until(lambda: engine.get(name).state is State.RUNNING), "the agent never ran"
    # Give the agent time to draw the input row the stop sequence reads.
    assert _until(
        lambda: "\u276f" in server.run("capture-pane", "-p", "-t", f"={PREFIX}{name}:").stdout
    )
    before = _pane_pids(server)
    assert list(before) == [f"{PREFIX}{name}"]
    old_pid = engine.get(name).pid

    session = engine.restart(name)
    # The stop may already have ended the agent by the time it returns.
    assert session.restarting is True

    started: list[str] = []

    def tick() -> bool:
        started.extend(engine.advance_restarts())
        return bool(started)

    assert _until(tick), "the sweep never started the successor"
    assert started == [name], "started exactly once"
    assert _until(lambda: engine.get(name).state is State.RUNNING)
    # A few more ticks: a second start would be refused or double up here.
    for _ in range(5):
        assert engine.advance_restarts() == []
        time.sleep(0.1)

    after = _pane_pids(server)
    assert list(after) == list(before), "the same session name, and only one session"
    assert after[f"{PREFIX}{name}"] != before[f"{PREFIX}{name}"], "a new pane pid"
    new = engine.get(name)
    assert new.pid != old_pid and new.restarting is False and new.restart_refused is None
    assert engine.restarts.pending == {}
