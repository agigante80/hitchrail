"""#472: Restart is a stop that starts, and starts exactly once, and only after
a stop that ended by the agent exiting.

The scenarios are the ticket's. Every one in which the stop does not end
cleanly asserts that `Engine.start` was NEVER CALLED, through `starts`, rather
than that no agent is found afterwards: an agent could be absent because the
start was refused, or because it died, and neither is "no start was attempted".
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

import pytest

from conftest import CLEAR_INPUT_BOX, FakeClock, FakeTmux, failing_procs, procs_from, ps_row
from hitchrail import claude_ipc
from hitchrail.engine import Engine
from hitchrail.sessions import NoAgent, NotRunning, Session, State, StopRefused, UnknownProject
from support import DEFAULT_LABEL
from test_stop_policy import VESSEL, ender, policy_engine


@pytest.fixture
def root(tmp_path: Path) -> Path:
    (tmp_path / "vessel").mkdir()
    return tmp_path


class Starts:
    """Every call to `Engine.start`, made or refused, in order."""

    def __init__(self, engine: Engine) -> None:
        self.calls: list[tuple[str, bool]] = []
        real = engine.start

        def recording(name: str, acknowledged: bool = False) -> Session:
            self.calls.append((name, acknowledged))
            return real(name, acknowledged)

        engine.start = recording  # type: ignore[method-assign]

    def __len__(self) -> int:
        return len(self.calls)


def restartable(root: Path, **config: Any) -> tuple[Engine, FakeTmux, FakeClock, Starts]:
    engine, tmux, clock = policy_engine(root, **config)
    return engine, tmux, clock, Starts(engine)


def agent_exits(tmux: FakeTmux) -> None:
    """The agent honoured the exit: its pane, window and session go with it."""
    tmux.sessions.pop(VESSEL)
    tmux.pane_text.pop(VESSEL, None)


# -- the route's half: a stop, and a mark ----------------------------------


def test_restart_asks_the_agent_to_exit_as_stop_does_and_marks_the_row(root: Path) -> None:
    engine, tmux, _, starts = restartable(root)
    session = engine.restart(VESSEL)
    assert session.stopping is True and session.restarting is True
    assert engine.get(VESSEL).restarting is True, "the mark survives a derivation"
    assert tmux.sent, "the graceful sequence went out"
    assert len(starts) == 0, "nothing starts until the agent has gone"
    again, tmux2, _, _ = restartable(root)
    again.stop(VESSEL)
    assert tmux.sent == tmux2.sent, "the stop half is Stop's, key for key"


def test_with_a_stop_prompt_the_closing_phase_runs_first_as_for_stop(root: Path) -> None:
    engine, _, _, starts = restartable(root, stop_prompt="/wrapup")
    session = engine.restart(VESSEL)
    assert session.stopping_phase == "closing"
    assert session.restarting is True
    assert len(starts) == 0


def test_a_clean_restart_starts_once_from_the_stopped_it_derived(root: Path) -> None:
    engine, tmux, _, starts = restartable(root)
    old_pane = tmux.sessions[VESSEL]
    engine.restart(VESSEL)
    assert engine.advance_restarts() == [], "the agent has not gone"
    assert len(starts) == 0
    agent_exits(tmux)
    assert engine.advance_restarts() == [VESSEL]
    assert starts.calls == [(VESSEL, False)]
    row = engine.get(VESSEL)
    assert row.state is State.RUNNING
    assert row.restarting is False and row.stopping is False
    assert tmux.sessions[VESSEL] != old_pane, "a new pane under the same session name"


def test_the_new_run_is_a_fresh_conversation(root: Path) -> None:
    engine, tmux, _, _ = restartable(root)
    engine.restart(VESSEL)
    agent_exits(tmux)
    engine.advance_restarts()
    ((name, _cwd, argv),) = tmux.started
    assert name == VESSEL
    assert argv == claude_ipc.launch_argv(engine.config.spawn_agent_binary, VESSEL)


# -- exactly once ------------------------------------------------------------


def test_two_sweep_ticks_after_the_exit_start_one_agent(root: Path) -> None:
    engine, tmux, _, starts = restartable(root)
    engine.restart(VESSEL)
    agent_exits(tmux)
    assert engine.advance_restarts() == [VESSEL]
    assert engine.advance_restarts() == []
    assert len(starts) == 1 and len(tmux.started) == 1


def test_two_ticks_racing_on_two_threads_start_one_agent(root: Path) -> None:
    engine, tmux, _, starts = restartable(root)
    engine.restart(VESSEL)
    agent_exits(tmux)
    gate = threading.Barrier(6)
    results: list[list[str]] = []

    def tick() -> None:
        gate.wait()
        results.append(engine.advance_restarts())

    threads = [threading.Thread(target=tick) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(name for r in results for name in r) == [VESSEL]
    assert len(starts) == 1


def test_two_restart_presses_hold_one_pending_start(root: Path) -> None:
    engine, tmux, _, starts = restartable(root)
    first = engine.restart(VESSEL)
    second = engine.restart(VESSEL)
    assert second.stopping is True and second.restarting is True, (
        "answers as a second Stop does"
    )
    assert list(engine.restarts.pending) == [VESSEL]
    assert first.restarting is True
    agent_exits(tmux)
    engine.advance_restarts()
    engine.advance_restarts()
    assert len(starts) == 1


def test_a_second_restart_that_stop_refuses_does_not_cancel_the_first(root: Path) -> None:
    engine, tmux, _, starts = restartable(root)
    engine.restart(VESSEL)
    tmux.pane_text[VESSEL] = "\x1b[39m\u276f\xa0half a sentence\n"  # a dirty box: StopRefused
    with pytest.raises(StopRefused):
        engine.restart(VESSEL)
    assert VESSEL in engine.restarts.pending, "the first press still holds its start"
    agent_exits(tmux)
    engine.advance_restarts()
    assert len(starts) == 1


# -- the stop does not end cleanly: nothing starts, ever --------------------


def test_a_timed_out_stop_starts_nothing_even_when_the_agent_goes_later(root: Path) -> None:
    engine, tmux, clock, starts = restartable(root)
    engine.restart(VESSEL)
    clock.advance(engine.prefs.stop_timeout() + 1)
    assert engine.expire_stops() == [VESSEL]
    assert engine.restarts.pending == {}
    assert engine.get(VESSEL).restarting is False
    assert engine.get(VESSEL).state is State.RUNNING, "it reports the timeout as Stop does"
    engine.advance_restarts()
    agent_exits(tmux)
    engine.advance_restarts()
    assert starts.calls == [], "start was never called"
    assert tmux.started == []


def test_a_kill_cancels_the_restart_and_start_is_never_called(root: Path) -> None:
    engine, tmux, _, starts = restartable(root)
    engine.restart(VESSEL)
    session = engine.kill(VESSEL)
    assert session.state is State.STOPPED and session.restarting is False
    assert engine.advance_restarts() == []
    assert starts.calls == []
    assert tmux.started == []


def test_the_kill_clears_the_restart_before_it_kills_the_session(root: Path) -> None:
    """A sweep landing between `kill-session` and the end of the Kill reads
    `stopped`. The mark must be gone by then, or it starts what was just
    killed."""
    engine, tmux, _, starts = restartable(root)
    engine.restart(VESSEL)
    seen: list[bool] = []
    real_kill = tmux.kill_session

    def kill_and_tick(project: str) -> None:
        seen.append(VESSEL in engine.restarts.pending)
        real_kill(project)
        engine.advance_restarts()

    tmux.kill_session = kill_and_tick  # type: ignore[method-assign]
    engine.kill(VESSEL)
    assert seen == [False]
    assert starts.calls == []


def test_end_anyway_ending_the_agent_starts_nothing(root: Path) -> None:
    from test_engine import MODAL_PANE

    engine, tmux, clock, starts = restartable(root, stop_policy="end_anyway")
    engine.restart(VESSEL)
    tmux.pane_text[VESSEL] = MODAL_PANE
    clock.advance(engine.prefs.stop_timeout() + 1)
    assert engine.expire_stops() == [VESSEL]
    assert ender(engine).ended == [VESSEL], "the agent really was ended"
    assert engine.get(VESSEL).state is State.STOPPED
    assert engine.advance_restarts() == []
    assert starts.calls == []
    assert tmux.started == []


def test_a_stop_that_ends_with_the_agent_still_there_starts_nothing_later(root: Path) -> None:
    """A marker that goes without the agent exiting (a refused exit given back,
    a dropped claim) leaves a mark with nothing to wait for. It is cleared when
    found, so a stop the person makes next week does not start an agent."""
    engine, tmux, _, starts = restartable(root)
    engine.restart(VESSEL)
    engine._drop(VESSEL, engine._stopping[VESSEL])
    assert engine.advance_restarts() == []
    assert engine.restarts.pending == {}
    agent_exits(tmux)
    assert engine.advance_restarts() == []
    assert starts.calls == []


def test_an_agent_started_by_hand_meanwhile_is_not_started_over(root: Path) -> None:
    engine, tmux, _, starts = restartable(root)
    engine.restart(VESSEL)
    agent_exits(tmux)
    engine.start(VESSEL)
    starts.calls.clear()
    assert engine.advance_restarts() == []
    assert starts.calls == [], "the mark was cleared by a row that is running again"


def test_an_unreadable_machine_starts_nothing_and_keeps_the_mark(
    root: Path, caplog: pytest.LogCaptureFixture
) -> None:
    engine, tmux, _, starts = restartable(root)
    engine.restart(VESSEL)
    agent_exits(tmux)
    good = engine._procs_fn
    engine._procs_fn = failing_procs
    with caplog.at_level(logging.WARNING, logger="hitchrail.engine"):
        assert engine.advance_restarts() == []
    assert starts.calls == []
    assert VESSEL in engine.restarts.pending
    engine._procs_fn = good
    assert engine.advance_restarts() == [VESSEL], "read again, it starts once"


def test_a_stop_still_typing_its_exit_is_not_yet_a_stop_that_ended(root: Path) -> None:
    engine, tmux, _, starts = restartable(root)
    engine.restart(VESSEL)
    marker = engine._stopping[VESSEL]
    marker.typing = True
    agent_exits(tmux)
    assert engine.advance_restarts() == []
    assert VESSEL in engine.restarts.pending, "decided by a later tick"
    marker.typing = False
    assert engine.advance_restarts() == [VESSEL]
    assert len(starts) == 1


# -- a start that is refused ---------------------------------------------------


def test_a_memory_refusal_is_on_the_row_and_is_not_retried(root: Path) -> None:
    engine, tmux, _, starts = restartable(root)
    engine.restart(VESSEL)
    agent_exits(tmux)
    engine._meminfo_fn = lambda: "MemAvailable: 1024 kB\n"
    assert engine.advance_restarts() == []
    assert len(starts) == 1
    row = engine.get(VESSEL)
    assert row.state is State.STOPPED
    assert row.restarting is False
    assert row.restart_refused is not None and "MB available" in row.restart_refused
    engine._meminfo_fn = lambda: "MemAvailable: 8388608 kB\n"
    engine.advance_restarts()
    assert len(starts) == 1, "not retried, even when memory has come back"
    assert engine.get(VESSEL).state is State.STOPPED
    assert engine.get(VESSEL).restart_refused is not None


def test_the_refusal_is_announced_and_goes_with_the_next_run(root: Path) -> None:
    engine, tmux, _, _ = restartable(root)
    published: list[dict[str, object]] = []

    class Bus:
        def publish(self, event: dict[str, object]) -> None:
            published.append(event)

    engine.attach_bus(Bus())  # type: ignore[arg-type]
    engine.restart(VESSEL)
    agent_exits(tmux)
    engine._meminfo_fn = lambda: "MemAvailable: 1024 kB\n"
    engine.advance_restarts()
    assert published[-1]["restart_refused"]
    engine._meminfo_fn = lambda: "MemAvailable: 8388608 kB\n"
    engine.start(VESSEL)
    assert engine.get(VESSEL).restart_refused is None
    agent_exits(tmux)
    assert engine.get(VESSEL).restart_refused is None, "a new stop does not inherit it"


def test_a_start_that_raises_unexpectedly_is_still_on_the_row(root: Path) -> None:
    engine, tmux, _, starts = restartable(root)
    engine.restart(VESSEL)
    agent_exits(tmux)

    def boom(name: str, acknowledged: bool = False) -> Session:
        starts.calls.append((name, acknowledged))
        raise RuntimeError("disk on fire")

    engine.start = boom  # type: ignore[method-assign]
    assert engine.advance_restarts() == []
    assert engine.get(VESSEL).restart_refused == "disk on fire"
    engine.advance_restarts()
    assert len(starts) == 1


# -- refusals match DELETE's ----------------------------------------------------


def test_restart_on_a_stopped_row_is_not_running_and_marks_nothing(root: Path) -> None:
    engine, tmux, _, starts = restartable(root)
    agent_exits(tmux)
    with pytest.raises(NotRunning):
        engine.restart(VESSEL)
    assert engine.restarts.pending == {}
    assert engine.advance_restarts() == []
    assert starts.calls == [], "Start is the button for a stopped row"


def test_restart_on_a_stale_row_is_no_agent_and_marks_nothing(root: Path) -> None:
    engine, tmux, _, starts = restartable(root)
    pane = tmux.sessions[VESSEL]
    engine._procs_fn = procs_from(ps_row(pane, 1))  # a pane with no agent in it
    assert engine.get(VESSEL).state is State.STALE
    with pytest.raises(NoAgent):
        engine.restart(VESSEL)
    assert engine.restarts.pending == {}
    assert starts.calls == []


def test_restart_on_a_detached_row_is_no_agent_and_marks_nothing(root: Path) -> None:
    engine, tmux, _, starts = restartable(root)
    pane = tmux.sessions.pop(VESSEL)
    engine._procs_fn = procs_from(ps_row(pane + 1, 1, project=VESSEL))
    assert engine.get(VESSEL).state is State.DETACHED
    with pytest.raises(NoAgent):
        engine.restart(VESSEL)
    assert engine.restarts.pending == {}
    assert starts.calls == []


def test_restart_on_an_unknown_project_is_refused(root: Path) -> None:
    engine, _, _, starts = restartable(root)
    with pytest.raises(UnknownProject):
        engine.restart(f"{DEFAULT_LABEL}~nowhere")
    assert engine.restarts.pending == {}
    assert starts.calls == []


def test_the_mark_is_not_persisted(root: Path) -> None:
    """A Hitchrail that restarts mid stop starts nothing, which is what two
    presses do today: the engine is the only holder."""
    engine, _, _, _ = restartable(root)
    engine.restart(VESSEL)
    fresh, _, _, starts = restartable(root)
    assert fresh.restarts.pending == {}
    assert fresh.advance_restarts() == []
    assert starts.calls == []


def test_the_screen_is_never_the_input_to_a_restart(root: Path) -> None:
    engine, tmux, _, starts = restartable(root)
    engine.restart(VESSEL)
    tmux.pane_text[VESSEL] = CLEAR_INPUT_BOX
    engine.advance_restarts()
    assert starts.calls == []


def test_a_restart_pressed_while_a_kill_is_typing_marks_nothing(root: Path) -> None:
    """Stop is a no-op there, since a Kill holds its marker out of the table.
    The person has said "end this", so no start may follow it."""
    from hitchrail.stopmarker import StopMarker

    engine, _, _, starts = restartable(root)
    engine._kill_held[VESSEL] = StopMarker(
        0.0, "exiting", engine.prefs.stop_policy(), exit_at=0.0, typing=True
    )
    session = engine.restart(VESSEL)
    assert session.restarting is False
    assert engine.restarts.pending == {}
    assert starts.calls == []
