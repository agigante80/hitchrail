"""#242 in the engine: who types the wrap up, when it moves on, and the table.

What the screen means is `test_wrap_up.py`'s. This file is the claim under
the lock, the watch the sweep drives, the ceiling, and the promise that with
no prompt configured a stop is byte for byte what it was before #242.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

import pytest

from conftest import (
    DIRTY_INPUT_BOX,
    TRUST_MODAL,
    TYPED,
    FakeClock,
    FakeTmux,
    procs_from,
    ps_row,
)
from hitchrail.claude_ipc import GRACEFUL_STOP_KEYS
from hitchrail.engine import Engine, Protected, StopMarker, StopRefused
from hitchrail.tmux import TmuxUnavailable
from support import DEFAULT_LABEL, make_config
from test_wrap_up import BUSY, QUEUED, SETTLE

PANE = 500
AGENT = 501
PROMPT = "/wrapup"


def proj(folder: str) -> str:
    return f"{DEFAULT_LABEL}~{folder}"


VESSEL = proj("vessel")


def wrap_engine(root: Path, **config: Any) -> tuple[Engine, FakeTmux, FakeClock]:
    """`test_engine.live_engine`, with the #242 settings named."""
    config.setdefault("stop_prompt", PROMPT)
    table = ps_row(PANE, 1) + ps_row(AGENT, PANE, project=VESSEL)
    tmux = FakeTmux(sessions={VESSEL: PANE})
    clock = FakeClock()
    sessions_dir = root / ".sessions"
    sessions_dir.mkdir(exist_ok=True)
    engine = Engine(
        make_config(root, sessions_dir=sessions_dir, **config),
        tmux=tmux,
        procs_fn=procs_from(table),
        meminfo_fn=lambda: "MemAvailable: 8388608 kB\n",
        clock=clock,
        sleep=clock.sleep,
    )
    return engine, tmux, clock


@pytest.fixture
def root(tmp_path: Path) -> Path:
    (tmp_path / "vessel").mkdir()
    return tmp_path


def typed(tmux: FakeTmux) -> list[str]:
    return [keys[1] for _p, keys in tmux.sent if keys[0] == TYPED]


def exits_sent(tmux: FakeTmux) -> int:
    """How many times the exit sequence's quit command went out."""
    return sum(1 for _p, keys in tmux.sent if keys == GRACEFUL_STOP_KEYS[-1])


def finish(engine: Engine, clock: FakeClock) -> list[str]:
    """Two idle reads `SETTLE` apart, the first `SETTLE` after sending."""
    clock.advance(SETTLE)
    assert engine.advance_wrap_ups() == []
    clock.advance(SETTLE)
    return engine.advance_wrap_ups()


# -- the first Stop ---------------------------------------------------------


def test_a_prompt_is_typed_after_a_clear_then_entered_and_never_interrupts(root: Path) -> None:
    engine, tmux, _ = wrap_engine(root)
    session = engine.stop(VESSEL)
    assert [keys for _p, keys in tmux.sent] == [
        GRACEFUL_STOP_KEYS[0],
        (TYPED, PROMPT),
        ("Enter",),
    ]
    assert not any("Escape" in keys for _p, keys in tmux.sent), "order B: queue, no interrupt"
    assert session.stopping is True
    assert session.stopping_phase == "closing"
    assert session.stop_ceiling is False


def test_the_watch_is_installed_once_the_prompt_is_sent(root: Path) -> None:
    engine, _, clock = wrap_engine(root)
    engine.stop(VESSEL)
    marker = engine._stopping[VESSEL]
    assert marker.phase == "closing"
    assert marker.watch is not None
    assert marker.watch.sent_at == clock()
    assert marker.exit_at is None


def test_a_finished_wrap_up_sends_the_exit_once(root: Path) -> None:
    engine, tmux, clock = wrap_engine(root)
    engine.stop(VESSEL)
    assert exits_sent(tmux) == 0, "the prompt alone, no exit yet"
    clock.advance(SETTLE)
    assert engine.advance_wrap_ups() == []
    clock.advance(SETTLE)
    # Measured before the exit sequence, whose settles move this clock.
    asked_at = clock()
    assert engine.advance_wrap_ups() == [VESSEL]
    assert exits_sent(tmux) == 1
    marker = engine._stopping[VESSEL]
    assert marker.phase == "exiting"
    assert marker.ceiling is False
    assert marker.exit_at == asked_at
    assert engine.advance_wrap_ups() == [], "an exiting marker is not the sweep's"
    assert exits_sent(tmux) == 1


def test_a_busy_pane_keeps_the_wrap_up_waiting(root: Path) -> None:
    engine, tmux, clock = wrap_engine(root)
    engine.stop(VESSEL)
    tmux.pane_text[VESSEL] = BUSY
    for _ in range(5):
        clock.advance(SETTLE)
        assert engine.advance_wrap_ups() == []
    assert engine._stopping[VESSEL].phase == "closing"
    assert exits_sent(tmux) == 0


def test_the_ceiling_moves_on_and_says_so(root: Path) -> None:
    engine, tmux, clock = wrap_engine(root, stop_prompt_timeout=60.0)
    engine.stop(VESSEL)
    tmux.pane_text[VESSEL] = BUSY
    clock.advance(59)
    assert engine.advance_wrap_ups() == []
    clock.advance(1)
    # The exit's clear check reads the box, and a busy box is clear.
    assert engine.advance_wrap_ups() == [VESSEL]
    assert exits_sent(tmux) == 1
    session = engine.get(VESSEL)
    assert session.stopping_phase == "exiting"
    assert session.stop_ceiling is True


def test_an_unreadable_pane_waits_to_the_ceiling_rather_than_reading_done(root: Path) -> None:
    engine, tmux, clock = wrap_engine(root, stop_prompt_timeout=60.0)
    engine.stop(VESSEL)

    def gone(*_a: object, **_k: object) -> str:
        raise TmuxUnavailable("no server")

    tmux.capture_pane = gone  # type: ignore[method-assign]
    for _ in range(10):
        clock.advance(SETTLE)
        assert engine.advance_wrap_ups() == []
    assert engine._stopping[VESSEL].phase == "closing"


def test_expiry_skips_a_closing_marker_and_measures_from_the_exit(root: Path) -> None:
    engine, tmux, clock = wrap_engine(root)
    engine.stop(VESSEL)
    tmux.pane_text[VESSEL] = BUSY
    clock.advance(engine.prefs.stop_timeout() + 100)
    assert engine.expire_stops() == [], "the wait before the exit is the agent's task"
    assert VESSEL in engine._stopping
    tmux.pane_text.pop(VESSEL)
    assert finish(engine, clock) == [VESSEL]
    clock.advance(engine.prefs.stop_timeout() - 1)
    assert engine.expire_stops() == []
    clock.advance(1)
    assert engine.expire_stops() == [VESSEL]


# -- the second Stop: the claim table ---------------------------------------


def test_a_second_stop_while_closing_is_exit_now_and_never_retypes(root: Path) -> None:
    engine, tmux, clock = wrap_engine(root)
    engine.stop(VESSEL)
    clock.advance(5)
    asked_at = clock()
    session = engine.stop(VESSEL)
    assert typed(tmux) == [PROMPT], "the prompt is typed once"
    assert exits_sent(tmux) == 1
    assert session.stopping_phase == "exiting"
    assert session.stop_ceiling is False
    assert engine._stopping[VESSEL].exit_at == asked_at


def test_a_stop_while_the_prompt_is_being_typed_types_nothing(root: Path) -> None:
    """No watch yet means another request is between its claim and its send."""
    engine, tmux, clock = wrap_engine(root)
    typing = StopMarker(clock(), "closing")
    engine._stopping[VESSEL] = typing
    session = engine.stop(VESSEL)
    assert tmux.sent == []
    assert engine._stopping[VESSEL] is typing
    assert session.stopping is True


def test_a_repeated_stop_on_exiting_keeps_the_ceiling_and_never_types_the_prompt(
    root: Path,
) -> None:
    engine, tmux, clock = wrap_engine(root)
    engine._stopping[VESSEL] = StopMarker(0.0, "exiting", exit_at=0.0, ceiling=True)
    asked_at = clock()
    session = engine.stop(VESSEL)
    assert typed(tmux) == []
    assert exits_sent(tmux) == 1
    assert session.stop_ceiling is True
    assert engine._stopping[VESSEL].exit_at == asked_at


def test_a_refused_wrap_up_drops_its_marker_and_types_nothing_more(root: Path) -> None:
    engine, tmux, _ = wrap_engine(root)
    tmux.pane_text[VESSEL] = QUEUED
    with pytest.raises(StopRefused, match="queued"):
        engine.stop(VESSEL)
    assert VESSEL not in engine._stopping
    assert typed(tmux) == []


def test_a_refused_exit_after_the_wrap_up_drops_the_marker(root: Path) -> None:
    engine, tmux, clock = wrap_engine(root)
    engine.stop(VESSEL)
    clock.advance(SETTLE)
    engine.advance_wrap_ups()
    clock.advance(SETTLE)
    marker = engine._stopping[VESSEL]
    real = tmux.capture_pane
    reads = iter(["idle", "modal"])

    def capture(project: str, lines: int = 40, escapes: bool = False) -> str:
        # The watch's read finds it idle; the exit's clear check finds a modal.
        if next(reads, "modal") == "idle":
            return real(project, lines, escapes)
        return TRUST_MODAL

    tmux.capture_pane = capture  # type: ignore[method-assign]
    assert engine.advance_wrap_ups() == [VESSEL]
    assert engine._stopping.get(VESSEL) is not marker
    assert VESSEL not in engine._stopping
    # The stop ended on a screen only a person can answer, and the row says
    # so, or the page reports "no answer" over a question it never showed.
    assert engine.get(VESSEL).awaiting_input is True


def test_a_refused_exit_over_a_draft_is_not_waiting_on_a_person(root: Path) -> None:
    """Text in an ordinary box is somebody's draft, which refuses the exit and
    is not a question: the pane look is `expire_stops`' one, not a new one."""
    engine, tmux, clock = wrap_engine(root)
    engine.stop(VESSEL)
    clock.advance(SETTLE)
    engine.advance_wrap_ups()
    clock.advance(SETTLE)
    real = tmux.capture_pane
    reads = iter(["idle"])

    def capture(project: str, lines: int = 40, escapes: bool = False) -> str:
        if next(reads, "draft") == "idle":
            return real(project, lines, escapes)
        return DIRTY_INPUT_BOX

    tmux.capture_pane = capture  # type: ignore[method-assign]
    assert engine.advance_wrap_ups() == [VESSEL]
    assert VESSEL not in engine._stopping
    assert VESSEL not in engine._awaiting_input


def test_a_kill_during_the_wrap_up_ends_it(root: Path) -> None:
    engine, tmux, clock = wrap_engine(root)
    engine.stop(VESSEL)
    engine.kill(VESSEL)
    assert VESSEL not in engine._stopping
    assert tmux.killed == [VESSEL]
    clock.advance(10 * SETTLE)
    assert engine.advance_wrap_ups() == []
    assert exits_sent(tmux) == 0


def test_a_second_stop_during_the_read_wins_over_the_sweep(root: Path) -> None:
    """The sweep reads outside the lock, so the claim it makes after has to
    check the marker is still the closing one it read."""
    engine, tmux, clock = wrap_engine(root)
    engine.stop(VESSEL)
    clock.advance(SETTLE)
    engine.advance_wrap_ups()
    clock.advance(SETTLE)
    real = tmux.capture_pane

    def capture(project: str, lines: int = 40, escapes: bool = False) -> str:
        tmux.capture_pane = real  # type: ignore[method-assign]
        engine.stop(VESSEL)
        return real(project, lines, escapes)

    tmux.capture_pane = capture  # type: ignore[method-assign]
    assert engine.advance_wrap_ups() == []
    assert exits_sent(tmux) == 1, "the person's Exit now, and only that"


def test_the_sweep_and_a_second_stop_racing_type_the_exit_once_per_claim(root: Path) -> None:
    """Two threads released together at the read. The ticket's table decides
    both orders: if the person's Stop claims first, the sweep finds the marker
    no longer `closing` and types nothing; if the sweep claims first, the Stop
    arrives on `exiting`, which is today's repeated Stop and types the exit
    once more under a NEW marker, as a double tap always has. Either way the
    exit goes out once per claim and the prompt is never retyped."""
    engine, tmux, clock = wrap_engine(root)
    engine.stop(VESSEL)
    clock.advance(SETTLE)
    engine.advance_wrap_ups()
    clock.advance(SETTLE)
    original = engine._stopping[VESSEL]
    barrier = threading.Barrier(2, timeout=5)
    real = tmux.capture_pane

    def capture(project: str, lines: int = 40, escapes: bool = False) -> str:
        tmux.capture_pane = real  # type: ignore[method-assign]
        barrier.wait()
        return real(project, lines, escapes)

    tmux.capture_pane = capture  # type: ignore[method-assign]
    person = threading.Thread(target=lambda: (barrier.wait(), engine.stop(VESSEL)))
    person.start()
    engine.advance_wrap_ups()
    person.join(timeout=5)
    assert not person.is_alive()
    claims = 1 if engine._stopping[VESSEL] is original else 2
    assert exits_sent(tmux) == claims
    assert typed(tmux) == [PROMPT]


def test_a_marker_replaced_during_the_read_is_not_advanced_by_it(root: Path) -> None:
    """Kill then a fresh Stop while the sweep reads: its idle reading belongs
    to the old stop, and the new one has only just typed its prompt."""
    engine, tmux, clock = wrap_engine(root)
    engine.stop(VESSEL)
    clock.advance(SETTLE)
    engine.advance_wrap_ups()
    clock.advance(SETTLE)
    real = tmux.capture_pane

    def capture(project: str, lines: int = 40, escapes: bool = False) -> str:
        tmux.capture_pane = real  # type: ignore[method-assign]
        engine.kill(VESSEL)
        tmux.sessions[VESSEL] = PANE
        engine.stop(VESSEL)
        return real(project, lines, escapes)

    tmux.capture_pane = capture  # type: ignore[method-assign]
    assert engine.advance_wrap_ups() == []
    assert exits_sent(tmux) == 0
    assert typed(tmux) == [PROMPT, PROMPT]
    assert engine._stopping[VESSEL].phase == "closing"


def test_the_ceiling_does_not_touch_a_prompt_still_being_typed(root: Path) -> None:
    engine, tmux, clock = wrap_engine(root, stop_prompt_timeout=10.0)
    typing = StopMarker(clock(), "closing")
    engine._stopping[VESSEL] = typing
    clock.advance(1000)
    assert engine.advance_wrap_ups() == []
    assert engine.expire_stops() == []
    assert tmux.sent == []
    assert engine._stopping[VESSEL] is typing
    assert typing.phase == "closing"


def test_the_self_project_refuses_a_stop_with_a_prompt_too(root: Path) -> None:
    engine, tmux, _ = wrap_engine(root, self_project=VESSEL)
    with pytest.raises(Protected):
        engine.stop(VESSEL)
    assert tmux.sent == []
    assert VESSEL not in engine._stopping


# -- the journal and the default --------------------------------------------


def test_the_prompt_never_reaches_the_engine_log(
    root: Path, caplog: pytest.LogCaptureFixture
) -> None:
    secretish = "/wrapup and-a-distinctive-string"
    engine, _, clock = wrap_engine(root, stop_prompt=secretish)
    with caplog.at_level(logging.DEBUG, logger="hitchrail"):
        engine.stop(VESSEL)
        finish(engine, clock)
    assert "wrap up sent" in caplog.text
    assert "wrap up finished" in caplog.text
    assert "distinctive" not in caplog.text


def test_with_no_prompt_a_stop_is_what_it_was_before(root: Path) -> None:
    engine, tmux, clock = wrap_engine(root, stop_prompt=None)
    asked_at = clock()
    session = engine.stop(VESSEL)
    assert [keys for _p, keys in tmux.sent] == list(GRACEFUL_STOP_KEYS)
    assert session.stopping_phase == "exiting"
    assert session.stop_ceiling is False
    assert engine._stopping[VESSEL].exit_at == asked_at
    assert engine.advance_wrap_ups() == []
    clock.now = asked_at + engine.prefs.stop_timeout()
    assert engine.expire_stops() == [VESSEL]


def test_with_no_stop_in_flight_the_row_carries_no_phase(root: Path) -> None:
    engine, _, _ = wrap_engine(root)
    session = engine.get(VESSEL)
    assert session.stopping is False
    assert session.stopping_phase is None
    assert session.as_dict()["stopping_phase"] is None
    assert session.as_dict()["stop_ceiling"] is False
