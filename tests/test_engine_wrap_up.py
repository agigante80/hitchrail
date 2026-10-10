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
from hitchrail import claude_ipc
from hitchrail.claude_ipc import GRACEFUL_STOP_KEYS
from hitchrail.engine import Engine, MachineUnreadable, Protected, StopMarker, StopRefused
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
    assert isinstance(marker.watch, claude_ipc.WrapUpWatch), "the default agent's watch"
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


def test_the_ceiling_line_counts_what_the_watch_saw_and_quotes_no_pane(
    root: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """#475: a 300s wait that could not tell its cause. The counts do, and the
    pane text, which can hold anything, stays out of the journal."""
    engine, tmux, clock = wrap_engine(root, stop_prompt_timeout=60.0)
    engine.stop(VESSEL)
    tmux.pane_text[VESSEL] = BUSY + "\nsecretish pane words"
    with caplog.at_level(logging.INFO, logger="hitchrail"):
        for _ in range(4):
            clock.advance(SETTLE)
            engine.advance_wrap_ups()
        tmux.pane_text[VESSEL] = "nothing like a box"
        clock.advance(SETTLE)
        engine.advance_wrap_ups()
        clock.advance(60)
        engine.advance_wrap_ups()
    assert "wrap up hit the ceiling after" in caplog.text
    assert "(readings: 0 idle, 4 busy, 2 unreadable)" in caplog.text
    assert "secretish" not in caplog.text


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
    clock.advance(SETTLE)
    assert engine.advance_wrap_ups() == []
    clock.advance(SETTLE)
    exit_at = clock.now
    assert engine.advance_wrap_ups() == [VESSEL]
    # From the exit, not from the return: the exit's own settles, the exit
    # menu's look among them (#453), are spent inside the timeout.
    clock.advance(exit_at + engine.prefs.stop_timeout() - 1 - clock.now)
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
    typing = StopMarker(clock(), "closing", "ask")
    engine._stopping[VESSEL] = typing
    session = engine.stop(VESSEL)
    assert tmux.sent == []
    assert engine._stopping[VESSEL] is typing
    assert session.stopping is True


def test_a_repeated_stop_on_exiting_keeps_the_ceiling_and_never_types_the_prompt(
    root: Path,
) -> None:
    engine, tmux, clock = wrap_engine(root)
    engine._stopping[VESSEL] = StopMarker(0.0, "exiting", "ask", exit_at=0.0, ceiling=True)
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
    assert engine.advance_wrap_ups() == [], "refused, so not moved on (#407)"
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
    assert engine.advance_wrap_ups() == []
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
    once more under a NEW marker, as a double tap always has, unless it lands
    while the sweep is still typing, when it claims nothing (#406). Either way
    the exit goes out once per claim and the prompt is never retyped."""
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
    typing = StopMarker(clock(), "closing", "ask")
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


# -- #406: one sequence typed into a pane at a time --------------------------


def _stop_inside_the_first_send(engine: Engine, tmux: FakeTmux) -> list[Any]:
    """A Stop arriving while the exit sequence is mid typing, on the same
    thread so the interleaving is the one under test and not a schedule."""
    answers: list[Any] = []
    real = tmux.send_keys

    def send_keys(project: str, *keys: str) -> None:
        tmux.send_keys = real  # type: ignore[method-assign]
        answers.append(engine.stop(project))
        real(project, *keys)

    tmux.send_keys = send_keys  # type: ignore[method-assign]
    return answers


def test_a_stop_while_the_sweep_types_the_exit_types_nothing(root: Path) -> None:
    """#406: the dialog still reads `closing` while the sweep types, and offers
    Exit now. Taken there, a second exit sequence interleaved with the
    sweep's C-u, Escape and `/exit`."""
    engine, tmux, clock = wrap_engine(root)
    engine.stop(VESSEL)
    clock.advance(SETTLE)
    engine.advance_wrap_ups()
    clock.advance(SETTLE)
    marker = engine._stopping[VESSEL]
    answers = _stop_inside_the_first_send(engine, tmux)
    assert engine.advance_wrap_ups() == [VESSEL]
    assert len(answers) == 1 and answers[0].stopping is True, "the no-op 202"
    assert exits_sent(tmux) == 1
    assert [keys for _p, keys in tmux.sent[-len(GRACEFUL_STOP_KEYS) :]] == list(
        GRACEFUL_STOP_KEYS
    ), "one sequence, unbroken"
    assert engine._stopping[VESSEL] is marker
    assert marker.typing is False, "cleared once the typing is over"


def test_a_stop_while_exit_now_is_typed_types_nothing(root: Path) -> None:
    """The same rule for a person's own exit: a double tap lands on a marker
    whose sequence is still going out."""
    engine, tmux, _ = wrap_engine(root, stop_prompt=None)
    answers = _stop_inside_the_first_send(engine, tmux)
    engine.stop(VESSEL)
    assert len(answers) == 1
    assert exits_sent(tmux) == 1
    assert [keys for _p, keys in tmux.sent] == list(GRACEFUL_STOP_KEYS)
    assert engine._stopping[VESSEL].typing is False


def test_a_typing_flag_is_cleared_when_the_exit_fails(root: Path) -> None:
    """A refusal raised out of the typing must not leave the marker flagged,
    or every later Stop would be a no-op for a sequence nobody is typing."""
    engine, tmux, clock = wrap_engine(root)
    engine.stop(VESSEL)
    clock.advance(SETTLE)
    engine.advance_wrap_ups()
    clock.advance(SETTLE)
    marker = engine._stopping[VESSEL]

    def send_keys(project: str, *keys: str) -> None:
        raise TmuxUnavailable("gone mid sequence")

    tmux.send_keys = send_keys  # type: ignore[method-assign]
    engine.advance_wrap_ups()
    assert marker.typing is False


# -- #407: the edges of the wrap up -----------------------------------------


def test_a_refused_exit_now_leaves_the_wrap_up_closing_with_its_watch(root: Path) -> None:
    """The person saw a refusal and reasonably assumes the wrap up still ends
    in an exit, so the queued prompt's watch has to survive it."""
    engine, tmux, clock = wrap_engine(root)
    engine.stop(VESSEL)
    marker = engine._stopping[VESSEL]
    watch = marker.watch
    tmux.pane_text[VESSEL] = DIRTY_INPUT_BOX
    with pytest.raises(StopRefused):
        engine.stop(VESSEL)
    assert engine._stopping[VESSEL] is marker, "the same object, which `_drop` compares"
    assert marker.phase == "closing"
    assert marker.watch is watch
    assert marker.exit_at is None
    assert marker.typing is False
    assert engine.get(VESSEL).stopping_phase == "closing"
    # And the sweep still ends it in an exit once the wrap up finishes.
    del tmux.pane_text[VESSEL]
    assert finish(engine, clock) == [VESSEL]
    assert exits_sent(tmux) == 1


def test_a_refused_first_exit_still_drops_its_marker(root: Path) -> None:
    """Only Exit now has a wrap up to go back to; a plain stop has none."""
    engine, tmux, _ = wrap_engine(root, stop_prompt=None)
    tmux.pane_text[VESSEL] = DIRTY_INPUT_BOX
    with pytest.raises(StopRefused):
        engine.stop(VESSEL)
    assert VESSEL not in engine._stopping


def test_an_unexpected_error_while_typing_the_prompt_drops_the_marker(root: Path) -> None:
    """Stranded `closing` with no watch, every later Stop was a no-op, the
    sweep skipped it and expiry never saw it: only Kill cleared it."""
    engine, tmux, _ = wrap_engine(root)

    def send_text(project: str, text: str) -> None:
        raise RuntimeError("something nobody planned for")

    tmux.send_text = send_text  # type: ignore[method-assign]
    with pytest.raises(RuntimeError):
        engine.stop(VESSEL)
    assert VESSEL not in engine._stopping
    del tmux.send_text
    engine.stop(VESSEL)
    assert typed(tmux) == [PROMPT], "a later Stop is a real one again"


def test_the_sweep_reports_only_the_exits_it_sent(root: Path) -> None:
    engine, tmux, clock = wrap_engine(root)
    engine.stop(VESSEL)
    clock.advance(SETTLE)
    engine.advance_wrap_ups()
    clock.advance(SETTLE)

    def send_keys(project: str, *keys: str) -> None:
        raise TmuxUnavailable("gone")

    tmux.send_keys = send_keys  # type: ignore[method-assign]
    assert engine.advance_wrap_ups() == []


# -- #387: a Kill that fails while the prompt is typed -----------------------


def _kill_fails_while_the_stop_types(
    engine: Engine, tmux: FakeTmux, prompt_raises: bool, exit_refused: bool = False
) -> None:
    """The exact interleaving: Stop claims `closing` and types; Kill takes the
    marker out; the Stop finishes (or fails) while it is out; then Kill's
    `kill-session` raises and it hands the marker back. Two threads, but one
    schedule: the kill releases the typing and joins it before raising.

    `exit_refused` is the third variant (#431): the marker is already a wrap
    up that is waiting (the caller stopped it), and the Stop is an Exit now
    whose keys block, then find a draft in the box and are refused while Kill
    holds the marker."""
    in_prompt = threading.Event()
    release = threading.Event()
    real_send_text = tmux.send_text
    real_send_keys = tmux.send_keys

    def send_keys(project: str, *keys: str) -> None:
        in_prompt.set()
        assert release.wait(timeout=5)
        real_send_keys(project, *keys)

    if exit_refused:
        # The caller has already stopped it, so the marker is a waiting wrap up.
        tmux.pane_text[VESSEL] = DIRTY_INPUT_BOX
        tmux.send_keys = send_keys  # type: ignore[method-assign]

    def send_text(project: str, text: str) -> None:
        in_prompt.set()
        assert release.wait(timeout=5)
        if prompt_raises:
            raise TmuxUnavailable("gone while the prompt was typed")
        real_send_text(project, text)

    errors: list[BaseException] = []

    def person() -> None:
        try:
            engine.stop(VESSEL)
        except BaseException as exc:  # the failing variant raises by design
            errors.append(exc)

    stopper = threading.Thread(target=person)

    def kill_session(project: str) -> None:
        release.set()
        stopper.join(timeout=5)
        assert not stopper.is_alive()
        raise TmuxUnavailable("kill-session failed")

    tmux.send_text = send_text  # type: ignore[method-assign]
    tmux.kill_session = kill_session  # type: ignore[method-assign]
    stopper.start()
    assert in_prompt.wait(timeout=5)
    with pytest.raises(MachineUnreadable):
        engine.kill(VESSEL)
    del tmux.send_text, tmux.kill_session
    if exit_refused:
        del tmux.send_keys
        assert [type(e) for e in errors] == [StopRefused]
    else:
        assert len(errors) == int(prompt_raises)


def test_a_failed_kill_while_the_prompt_is_typed_leaves_a_wrap_up_the_sweep_ends(
    root: Path,
) -> None:
    """Restored `closing` with no watch, every later Stop was the no-op 202,
    the sweep skipped it and expiry never saw it: only a Kill that worked
    cleared it."""
    engine, tmux, clock = wrap_engine(root)
    _kill_fails_while_the_stop_types(engine, tmux, prompt_raises=False)
    marker = engine._stopping[VESSEL]
    assert marker.phase == "closing"
    assert marker.watch is not None
    assert finish(engine, clock) == [VESSEL]
    assert exits_sent(tmux) == 1


def test_a_failed_kill_does_not_restore_a_stop_whose_prompt_failed(root: Path) -> None:
    """The same stranding by the other road: the Stop gave its marker up while
    the Kill held it, so handing it back resurrects a wait for nothing."""
    engine, tmux, _ = wrap_engine(root)
    _kill_fails_while_the_stop_types(engine, tmux, prompt_raises=True)
    assert VESSEL not in engine._stopping
    engine.stop(VESSEL)
    assert typed(tmux) == [PROMPT], "a later Stop is a real one again"


# -- #427: Stop clears only the typing flag it still owns --------------------


def test_a_refused_exit_now_does_not_clear_the_flag_the_sweep_set_after_it(root: Path) -> None:
    """The window is between Stop's give back and its `finally`: the refused
    Exit now has restored `closing` and released the lock, the sweep claims
    the SAME marker object and starts typing the exit, and Stop then clears
    the flag the sweep set. A third Stop reads `exiting` with nothing
    typing and types a second sequence over the sweep's (#406 again).

    Two threads, one schedule: the give back is wrapped so the sweep claims
    and blocks in its first key before Stop's frame moves on."""
    engine, tmux, clock = wrap_engine(root, stop_prompt_timeout=60.0)
    engine.stop(VESSEL)
    clock.advance(60)
    tmux.pane_text[VESSEL] = DIRTY_INPUT_BOX
    real_send_keys = tmux.send_keys
    sweep_typing = threading.Event()
    release = threading.Event()
    callers: list[str] = []

    def send_keys(project: str, *keys: str) -> None:
        callers.append(threading.current_thread().name)
        if len(callers) == 1:
            sweep_typing.set()
            assert release.wait(timeout=5)
        real_send_keys(project, *keys)

    sweep = threading.Thread(target=engine.advance_wrap_ups, name="sweep")
    real_give_back = engine._give_back

    def give_back(name: str, marker: StopMarker, resume: Any) -> None:
        real_give_back(name, marker, resume)
        # Stop has handed the marker back and holds no lock. The pane is
        # idle now, so the sweep may type, and it claims the same object.
        del tmux.pane_text[VESSEL]
        tmux.send_keys = send_keys  # type: ignore[method-assign]
        sweep.start()
        assert sweep_typing.wait(timeout=5)

    engine._give_back = give_back  # type: ignore[method-assign]
    marker = engine._stopping[VESSEL]
    with pytest.raises(StopRefused):
        engine.stop(VESSEL)
    assert engine._stopping[VESSEL] is marker
    assert marker.typing is True, "the sweep's flag, which Stop does not own"
    callers.clear()
    third = engine.stop(VESSEL)
    assert third.stopping is True, "the no-op 202"
    assert callers == [], "a third Stop typed nothing while the sweep types"
    release.set()
    sweep.join(timeout=5)
    assert not sweep.is_alive()
    assert exits_sent(tmux) == 1
    assert marker.typing is False


def test_a_failed_kill_hands_back_a_wrap_up_whose_exit_now_was_refused_meanwhile(
    root: Path,
) -> None:
    """#431. A second Stop turned `closing` into `exiting`; Kill took the
    marker out; the exit was refused and gave `closing` and the watch back to
    an object no table holds; then Kill's `kill-session` failed and restored
    it. Were the give back guarded by "is it still in the table", the marker
    would come back `exiting` with `exit_at` set: expiry would treat an exit
    never sent as sent and, under `end_anyway`, kill."""
    engine, tmux, clock = wrap_engine(root)
    engine.stop(VESSEL)
    watch = engine._stopping[VESSEL].watch
    assert watch is not None
    _kill_fails_while_the_stop_types(engine, tmux, prompt_raises=False, exit_refused=True)
    marker = engine._stopping[VESSEL]
    assert marker.phase == "closing"
    assert marker.exit_at is None
    assert marker.typing is False
    assert marker.watch is watch
    del tmux.pane_text[VESSEL]
    assert finish(engine, clock) == [VESSEL]
    assert exits_sent(tmux) == 1


def test_a_stop_during_a_failing_kill_does_not_type_over_the_first_stop(root: Path) -> None:
    """#432. Kill takes the marker out of the table before `kill-session`, so
    a second Stop in that window found no marker, claimed a fresh one and
    typed a second prompt into a pane where the first Stop is still typing
    (#406's rule, broken by #387's order). It must see a stop in flight,
    while Kill still restores the first marker when `kill-session` fails.

    One schedule: inside `kill-session` the second Stop runs on Kill's own
    thread while the first is parked in its prompt, then the first is
    released and joined, and the kill fails."""
    engine, tmux, clock = wrap_engine(root)
    in_prompt = threading.Event()
    release = threading.Event()
    real_send_text = tmux.send_text
    prompts: list[str] = []

    def send_text(project: str, text: str) -> None:
        prompts.append(text)
        if len(prompts) == 1:
            in_prompt.set()
            assert release.wait(timeout=5)
        real_send_text(project, text)

    first = threading.Thread(target=lambda: engine.stop(VESSEL))
    second: list[Any] = []

    def kill_session(project: str) -> None:
        sent_before = len(tmux.sent)
        second.append(engine.stop(VESSEL))
        assert len(tmux.sent) == sent_before, "the second Stop typed nothing"
        release.set()
        first.join(timeout=5)
        assert not first.is_alive()
        raise TmuxUnavailable("kill-session failed")

    tmux.send_text = send_text  # type: ignore[method-assign]
    tmux.kill_session = kill_session  # type: ignore[method-assign]
    first.start()
    assert in_prompt.wait(timeout=5)
    held = engine._stopping[VESSEL]
    with pytest.raises(MachineUnreadable):
        engine.kill(VESSEL)
    del tmux.send_text, tmux.kill_session
    assert len(second) == 1
    assert prompts == [PROMPT], "one prompt, typed once"
    assert exits_sent(tmux) == 0
    assert engine._stopping[VESSEL] is held, "Kill's restore still happens (#387)"
    assert held.phase == "closing" and held.watch is not None
    assert finish(engine, clock) == [VESSEL]


# -- #408, #411, #428: what another browser needs to reopen a wait ----------


def test_a_row_whose_prompt_is_being_typed_says_so(root: Path) -> None:
    """#408. Every browser but the one that tapped learns of the stop from the
    listing, and a Stop now is the no-op 202, so Exit now must not be offered."""
    engine, _, clock = wrap_engine(root)
    marker = StopMarker(clock(), "closing", "ask")
    engine._stopping[VESSEL] = marker
    session = engine.get(VESSEL)
    assert session.stopping_phase == "closing"
    assert session.stop_typing is True
    assert session.as_dict()["stop_typing"] is True
    marker.watch = claude_ipc.WrapUpWatch(sent_at=clock())
    assert engine.get(VESSEL).stop_typing is False, "the prompt is out: Exit now works"


def test_a_row_whose_exit_is_being_typed_says_so(root: Path) -> None:
    engine, _, clock = wrap_engine(root)
    engine._stopping[VESSEL] = StopMarker(
        clock(), "exiting", "ask", exit_at=clock(), typing=True
    )
    assert engine.get(VESSEL).stop_typing is True


def test_a_stop_answered_is_not_typing(root: Path) -> None:
    engine, _, _ = wrap_engine(root)
    assert engine.stop(VESSEL).stop_typing is False
    assert engine.get(VESSEL).stop_typing is False


def test_a_row_carries_its_stops_age_in_seconds(root: Path) -> None:
    """#411. An age, never the engine's monotonic instant: a browser compares
    what it is sent to its own clock, which shares no epoch with this one."""
    engine, _, clock = wrap_engine(root)
    engine.stop(VESSEL)
    began = engine._stopping[VESSEL].began
    clock.now = began + 20.0
    session = engine.get(VESSEL)
    assert session.stop_age_s == 20.0
    assert session.as_dict()["stop_age_s"] == session.stop_age_s


def test_exit_now_keeps_the_stops_age(root: Path) -> None:
    """Mutated in place (#407), so the wrap up's start survives the exit."""
    engine, _, clock = wrap_engine(root)
    engine.stop(VESSEL)
    began = engine._stopping[VESSEL].began
    clock.advance(30)
    engine.stop(VESSEL)
    assert engine._stopping[VESSEL].began == began
    assert engine.get(VESSEL).stop_age_s == round(clock() - began, 1)


def test_a_row_carries_the_policy_its_stop_was_confirmed_under(root: Path) -> None:
    """#428. A wait reopened after a reload has no wait of its own to copy the
    policy from, and the live setting may since have changed."""
    engine, _, _ = wrap_engine(root)
    engine.stop(VESSEL)
    engine.prefs.apply(stop_policy="end_anyway")
    session = engine.get(VESSEL)
    assert engine.prefs.stop_policy() == "end_anyway"
    assert session.stop_policy == "ask"
    assert session.as_dict()["stop_policy"] == "ask"


def test_with_no_stop_in_flight_the_row_carries_no_stop_fields(root: Path) -> None:
    engine, _, _ = wrap_engine(root)
    shape = engine.get(VESSEL).as_dict()
    assert shape["stop_typing"] is False
    assert shape["stop_age_s"] is None
    assert shape["stop_policy"] is None
