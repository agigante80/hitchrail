"""#239: a stop that ends on a prompt, and the operator's answer given ahead.

Design 4.3 step 4 forbids escalation by DEFAULT. `stop_policy = end_anyway`
is escalation chosen once, in configuration, and it is the kill the dialog
already offers at expiry, never a key typed into the prompt.
"""

from __future__ import annotations

import errno
import logging
import os
import signal
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from conftest import (
    CLEAR_INPUT_BOX,
    TRUST_MODAL,
    FakeClock,
    FakePidfd,
    FakeTmux,
    failing_procs,
    procs_from,
    ps_row,
)
from hitchrail import settings
from hitchrail.config import Config, ConfigError
from hitchrail.engine import Engine, StopMarker
from hitchrail.sessions import InvalidValue, OperatorPinned, State
from hitchrail.tmux import TmuxUnavailable
from support import DEFAULT_LABEL, make_config
from test_engine import MODAL_PANE
from test_wrap_up import SETTLE

PANE = 500
VESSEL = f"{DEFAULT_LABEL}~vessel"


@pytest.fixture
def root(tmp_path: Path) -> Path:
    (tmp_path / "vessel").mkdir()
    return tmp_path


class AgentEnder(FakePidfd):
    """The pidfd seam for these tests (#418): a signal sent through a handle
    ends that agent, and its pane and session with it, as a real agent that
    is the pane's own process does. `ended` names the rows it ended.

    Never the real syscalls: without this the engine would `pidfd_open` the
    fake pid 501 on the machine running the suite and signal whatever it is.
    """

    def __init__(self, tmux: FakeTmux, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.tmux = tmux
        self.handles: dict[int, int] = {}
        self.ended: list[str] = []

    def open(self, pid: int) -> int:
        pidfd = super().open(pid)
        self.handles[pidfd] = pid
        return pidfd

    def send(self, pidfd: int, sig: int) -> None:
        super().send(pidfd, sig)
        pid = self.handles[pidfd]
        for name, pane in list(self.tmux.sessions.items()):
            if pane + 1 == pid:
                self.ended.append(name)
                self.tmux.sessions.pop(name)
                self.tmux.pane_text.pop(name, None)


def ender(engine: Engine) -> AgentEnder:
    seam = engine._pidfd.open_pidfd
    assert isinstance(seam.__self__, AgentEnder)  # type: ignore[attr-defined]
    return seam.__self__  # type: ignore[attr-defined]


def killed(engine: Engine, tmux: FakeTmux) -> list[str]:
    """The rows `end_anyway` ended. Always through a handle on the agent it
    looked at, never `kill-session` by name (#418)."""
    assert tmux.killed == [], "end_anyway never kills a session by name"
    return ender(engine).ended


def policy_engine(
    root: Path, projects: tuple[str, ...] = (VESSEL,), **config: Any
) -> tuple[Engine, FakeTmux, FakeClock]:
    """An engine with `vessel` running whose process leaves when its tmux
    session does, so a kill reads `stopped` rather than `detached`. Each
    agent is its pane's pid plus one, read from the live session map, so a
    test restarts a row by giving it a new pane."""
    panes = {name: PANE + 10 * i for i, name in enumerate(projects)}
    tmux = FakeTmux(sessions=dict(panes))
    for name in projects:
        tmux.pane_text[name] = CLEAR_INPUT_BOX
    pidfd = AgentEnder(tmux)

    def procs() -> Any:
        return procs_from(
            "".join(
                ps_row(pane, 1) + ps_row(pane + 1, pane, project=name)
                for name, pane in tmux.sessions.items()
            )
        )()

    clock = FakeClock()
    sessions_dir = root / ".sessions"
    sessions_dir.mkdir(exist_ok=True)
    engine = Engine(
        make_config(
            root, sessions_dir=sessions_dir, agent_config_path=root / "none.json", **config
        ),
        tmux=tmux,
        procs_fn=procs,
        meminfo_fn=lambda: "MemAvailable: 8388608 kB\n",
        clock=clock,
        sleep=clock.sleep,
        open_pidfd=pidfd.open,
        send_signal=pidfd.send,
        close_pidfd=pidfd.close,
        owner_uid=pidfd.owner,
        cwd_of=pidfd.cwd_of,
    )
    return engine, tmux, clock


def expire_on(engine: Engine, tmux: FakeTmux, clock: FakeClock, pane: str) -> list[str]:
    engine.stop(VESSEL)
    sent = list(tmux.sent)
    tmux.pane_text[VESSEL] = pane
    clock.advance(engine.prefs.stop_timeout() + 1)
    expired = engine.expire_stops()
    assert tmux.sent == sent, "nothing is ever typed into the prompt"
    return expired


def test_the_default_is_ask() -> None:
    assert Config.stop_policy == "ask"


@pytest.mark.parametrize("value", ["whatever", "", "END_ANYWAY", "kill"])
def test_an_unknown_policy_is_refused_naming_the_two(root: Path, value: str) -> None:
    with pytest.raises(ConfigError, match="ask, end_anyway"):
        make_config(root, stop_policy=value)


def test_end_anyway_kills_a_stop_that_ended_on_a_prompt(root: Path) -> None:
    engine, tmux, clock = policy_engine(root, stop_policy="end_anyway")
    published: list[dict[str, object]] = []

    class Recorder:
        def publish(self, event: dict[str, object]) -> None:
            published.append(event)

    engine.attach_bus(Recorder())  # type: ignore[arg-type]
    assert expire_on(engine, tmux, clock, MODAL_PANE) == [VESSEL]
    assert killed(engine, tmux) == [VESSEL]
    assert engine.get(VESSEL).state is State.STOPPED
    assert [e["state"] for e in published if e["name"] == VESSEL][-1] == "stopped"


def test_end_anyway_kills_nothing_when_the_pane_shows_no_prompt(root: Path) -> None:
    """The request was about a prompt. A slow agent finishing a write is not
    one, and killing every slow stop is the option the ticket rejected."""
    engine, tmux, clock = policy_engine(root, stop_policy="end_anyway")
    assert expire_on(engine, tmux, clock, CLEAR_INPUT_BOX) == [VESSEL]
    assert killed(engine, tmux) == []
    assert engine.get(VESSEL).state is State.RUNNING


def test_ask_kills_nothing_on_a_prompt(root: Path) -> None:
    engine, tmux, clock = policy_engine(root)
    assert expire_on(engine, tmux, clock, MODAL_PANE) == [VESSEL]
    assert killed(engine, tmux) == []
    assert engine.get(VESSEL).awaiting_input is True, "reported, as before #239"


def test_the_pane_is_read_at_expiry_not_the_sweeps_overlay(root: Path) -> None:
    """A claim about a screen that outlives the thing watching it is a claim
    nobody has checked: the overlay says waiting, the pane says clear."""
    engine, tmux, clock = policy_engine(root, stop_policy="end_anyway")
    engine.stop(VESSEL)
    engine._awaiting_input.add(VESSEL)
    engine._stuck[VESSEL] = clock()
    clock.advance(engine.prefs.stop_timeout() + 1)
    engine.expire_stops()
    assert killed(engine, tmux) == []


@pytest.mark.parametrize("unreadable", ["tmux_gone", "no_box_drawn"])
def test_an_unreadable_pane_at_expiry_kills_nothing(root: Path, unreadable: str) -> None:
    """The unknown case does the thing that destroys nothing.

    Both ways a look can fail to say anything: the capture raises, or it
    returns a screen with no input box to read (#239 review: an earlier
    version popped the pane text, and the fake answers that with a clear box,
    so the test checked a clear pane twice and an unreadable one never).
    """
    engine, tmux, clock = policy_engine(root, stop_policy="end_anyway")
    engine.stop(VESSEL)
    if unreadable == "tmux_gone":

        def gone(project: str, lines: int = 40, escapes: bool = False) -> str:
            raise TmuxUnavailable("no server")

        tmux.capture_pane = gone  # type: ignore[method-assign]
    else:
        tmux.pane_text[VESSEL] = ""
    clock.advance(engine.prefs.stop_timeout() + 1)
    engine.expire_stops()
    assert killed(engine, tmux) == []


def test_a_row_restarted_during_another_rows_kill_is_not_killed(root: Path) -> None:
    """Look then act, one name at a time (#239 review). Each kill waits for its
    session to go; a look taken before that wait is stale by its own kill, and
    a row a person restarted in between holds a fresh agent that never asked."""
    (root / "other").mkdir()
    other = f"{DEFAULT_LABEL}~other"
    engine, tmux, clock = policy_engine(root, (VESSEL, other), stop_policy="end_anyway")
    engine.stop(VESSEL)
    engine.stop(other)
    tmux.pane_text[VESSEL] = MODAL_PANE
    tmux.pane_text[other] = MODAL_PANE
    agents = ender(engine)
    send = agents.send

    def kill_then_restart_the_other(pidfd: int, sig: int) -> None:
        send(pidfd, sig)
        if agents.ended == [VESSEL]:
            tmux.pane_text[other] = CLEAR_INPUT_BOX

    engine._pidfd = replace(engine._pidfd, send_signal=kill_then_restart_the_other)
    clock.advance(engine.prefs.stop_timeout() + 1)
    assert sorted(engine.expire_stops()) == sorted([VESSEL, other])
    assert killed(engine, tmux) == [VESSEL]


def test_the_self_project_is_never_killed_by_this_path(root: Path) -> None:
    """A protected row cannot be stopped, so it can only carry a marker by a
    path nobody has written yet; this asserts the kill refuses it then too."""
    engine, tmux, clock = policy_engine(root, stop_policy="end_anyway", self_project=VESSEL)
    assert engine.get(VESSEL).protected
    engine._stopping[VESSEL] = StopMarker(clock(), "exiting", exit_at=clock())
    tmux.pane_text[VESSEL] = MODAL_PANE
    clock.advance(engine.prefs.stop_timeout() + 1)
    assert engine.expire_stops() == [VESSEL]
    assert killed(engine, tmux) == []
    assert engine.get(VESSEL).state is State.RUNNING


# -- #418, #412: bound to the agent looked at, and every way it can refuse --


RESTARTED_PANE = PANE + 100


def restart(tmux: FakeTmux) -> None:
    """A person's Kill and Start: a fresh agent for the same row, on a new
    pane, showing the startup modal the old one's question looked like."""
    tmux.sessions[VESSEL] = RESTARTED_PANE
    tmux.pane_text[VESSEL] = MODAL_PANE


def test_end_anyway_signals_the_agent_it_looked_at_through_a_handle(root: Path) -> None:
    engine, tmux, clock = policy_engine(root, stop_policy="end_anyway")
    expire_on(engine, tmux, clock, MODAL_PANE)
    events = ender(engine).events
    assert [kind for kind, _ in events] == ["open", "send", "close"]
    assert events[0] == ("open", PANE + 1)
    assert ender(engine).signals == [signal.SIGHUP]


def test_a_row_restarted_between_the_look_and_the_kill_is_not_killed(
    root: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """#418. The pid is read before the screen, so a restart after it shows
    the fresh agent's modal under the old agent's pid. Read after the
    screen, the fresh pid would carry the old question and be killed."""
    engine, tmux, clock = policy_engine(root, stop_policy="end_anyway")
    engine.stop(VESSEL)
    tmux.pane_text[VESSEL] = MODAL_PANE
    capture = tmux.capture_pane

    def restarted_while_looking(project: str, lines: int = 40, escapes: bool = False) -> str:
        restart(tmux)
        return capture(project, lines, escapes)

    tmux.capture_pane = restarted_while_looking  # type: ignore[method-assign]
    clock.advance(engine.prefs.stop_timeout() + 1)
    with caplog.at_level(logging.INFO, logger="hitchrail"):
        assert engine.expire_stops() == [VESSEL]
    assert killed(engine, tmux) == []
    assert ender(engine).signals == []
    row = engine.get(VESSEL)
    assert row.state is State.RUNNING
    assert row.pid == RESTARTED_PANE + 1
    assert "end_anyway did not kill it: Gone" in caplog.text


def test_a_row_restarted_after_the_handle_opens_is_not_signalled(root: Path) -> None:
    """The verification is AFTER the handle: a pid that is still open but no
    longer the row's agent is refused, and nothing goes through the handle."""
    engine, tmux, clock = policy_engine(root, stop_policy="end_anyway")
    agents = ender(engine)
    opened = agents.open

    def restarted_after_opening(pid: int) -> int:
        pidfd = opened(pid)
        tmux.sessions[VESSEL] = RESTARTED_PANE
        # The old agent still runs, outside any session: alive, not the row's.
        return pidfd

    engine._pidfd = replace(engine._pidfd, open_pidfd=restarted_after_opening)
    expire_on(engine, tmux, clock, MODAL_PANE)
    assert agents.signals == []
    assert [kind for kind, _ in agents.events] == ["open", "close"]
    assert engine.get(VESSEL).pid == RESTARTED_PANE + 1


def test_an_agent_in_this_servers_process_tree_is_never_signalled(
    root: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The same refusal `signal_detached` gives, before any handle: a row
    whose agent is this server or an ancestor of it would end the interface."""
    engine, tmux, clock = policy_engine(root, stop_policy="end_anyway")
    tmux.sessions[VESSEL] = os.getpid() - 1
    with caplog.at_level(logging.INFO, logger="hitchrail"):
        assert expire_on(engine, tmux, clock, MODAL_PANE) == [VESSEL]
    assert ender(engine).events == []
    assert "end_anyway did not kill it: Protected" in caplog.text


@pytest.mark.parametrize(
    ("fail_open", "fail_send", "refusal"),
    [
        (OSError(errno.ESRCH, "gone"), None, "Gone"),
        (OSError(errno.EPERM, "seccomp"), None, "PidfdUnavailable"),
        (AttributeError("no pidfd_open"), None, "PidfdUnavailable"),
        (OSError(errno.EMFILE, "too many"), None, "MachineUnreadable"),
        (None, OSError(errno.EPERM, "not yours"), "NotOurs"),
        (None, OSError(errno.ESRCH, "gone"), "Gone"),
        (None, AttributeError("no pidfd_send_signal"), "PidfdUnavailable"),
    ],
)
def test_every_refusal_of_the_kill_reports_the_expiry_as_ask_does(
    root: Path,
    caplog: pytest.LogCaptureFixture,
    fail_open: BaseException | None,
    fail_send: BaseException | None,
    refusal: str,
) -> None:
    """#412. Whatever the handle refuses, the ticker returns, the row is
    marked waiting and the journal says the policy did not kill it."""
    engine, tmux, clock = policy_engine(root, stop_policy="end_anyway")
    agents = ender(engine)
    agents.fail_open, agents.fail_send = fail_open, fail_send
    with caplog.at_level(logging.INFO, logger="hitchrail"):
        assert expire_on(engine, tmux, clock, MODAL_PANE) == [VESSEL]
    assert agents.ended == []
    row = engine.get(VESSEL)
    assert row.state is State.RUNNING
    assert row.awaiting_input is True
    assert f"end_anyway did not kill it: {refusal}" in caplog.text
    if fail_send is not None:
        assert agents.events[-1][0] == "close", "the handle is closed on a refusal too"


@pytest.mark.parametrize("unreadable", ["ps", "tmux"])
def test_a_machine_unreadable_after_the_handle_kills_nothing(
    root: Path, caplog: pytest.LogCaptureFixture, unreadable: str
) -> None:
    """#412. The verification cannot look, so it cannot verify, so nothing is
    sent (control 7), and the ticker survives either way the look fails."""
    engine, tmux, clock = policy_engine(root, stop_policy="end_anyway")
    agents = ender(engine)
    opened = agents.open
    procs = engine._procs_fn
    broken = {"now": False}

    def unreadable_after_opening(pid: int) -> int:
        broken["now"] = True
        return opened(pid)

    def ps() -> Any:
        return failing_procs() if broken["now"] and unreadable == "ps" else procs()

    def panes() -> Any:
        if broken["now"]:
            raise TmuxUnavailable("no server")
        return FakeTmux.panes(tmux)

    engine._procs_fn = ps
    if unreadable == "tmux":
        tmux.panes = panes  # type: ignore[method-assign]
    engine._pidfd = replace(engine._pidfd, open_pidfd=unreadable_after_opening)
    with caplog.at_level(logging.INFO, logger="hitchrail"):
        assert expire_on(engine, tmux, clock, MODAL_PANE) == [VESSEL]
    assert agents.signals == []
    assert "end_anyway did not kill it: MachineUnreadable" in caplog.text


def test_the_kill_is_journalled_before_a_read_that_fails(
    root: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """#412. The signal went; then the machine could not be read. The journal
    still says the policy killed it, and the ticker returns."""
    engine, tmux, clock = policy_engine(root, stop_policy="end_anyway")
    agents = ender(engine)
    send = agents.send
    procs = engine._procs_fn
    sent = {"yet": False}

    def send_then_break(pidfd: int, sig: int) -> None:
        send(pidfd, sig)
        sent["yet"] = True

    engine._procs_fn = lambda: failing_procs() if sent["yet"] else procs()
    engine._pidfd = replace(engine._pidfd, send_signal=send_then_break)
    with caplog.at_level(logging.INFO, logger="hitchrail"):
        assert expire_on(engine, tmux, clock, MODAL_PANE) == [VESSEL]
    assert agents.ended == [VESSEL]
    kill_lines = [r.getMessage() for r in caplog.records if "killed pid" in r.getMessage()]
    assert kill_lines == [
        f"stop {VESSEL}: ended on a prompt after {engine.prefs.stop_timeout():g}s; "
        f"killed pid {PANE + 1}, as stop_policy end_anyway says"
    ]
    assert "expired but the machine could not be read" not in caplog.text


# -- #409: chosen on the settings page, kept in the state file ------------


def test_a_policy_set_by_a_request_is_the_one_the_expiry_acts_on(root: Path) -> None:
    """The engine reads the preference, not the frozen `Config`: a policy
    chosen on the page and read nowhere would be a control that lies."""
    engine, tmux, clock = policy_engine(root, state_path=root / "state" / "state.toml")
    engine.prefs.apply(stop_policy="end_anyway")
    assert expire_on(engine, tmux, clock, MODAL_PANE) == [VESSEL]
    assert killed(engine, tmux) == [VESSEL]


def test_a_policy_set_back_to_ask_kills_nothing(root: Path) -> None:
    engine, tmux, clock = policy_engine(root, state_path=root / "state" / "state.toml")
    engine.prefs.apply(stop_policy="end_anyway")
    engine.prefs.apply(stop_policy="ask")
    assert expire_on(engine, tmux, clock, MODAL_PANE) == [VESSEL]
    assert killed(engine, tmux) == []


def test_the_policy_persists_and_a_new_process_reads_it(root: Path) -> None:
    state = root / "state" / "state.toml"
    prefs = settings.Preferences(make_config(root, state_path=state))
    assert (prefs.stop_policy(), prefs.stop_policy_source()) == ("ask", "default")
    prefs.apply(stop_policy="end_anyway")
    assert 'stop_policy = "end_anyway"' in state.read_text()
    fresh = settings.Preferences(make_config(root, state_path=state))
    assert (fresh.stop_policy(), fresh.stop_policy_source()) == ("end_anyway", "state")
    assert fresh.stop_policy_editable()


@pytest.mark.parametrize("bad", ["kill", "", "END_ANYWAY", 1, True, ["end_anyway"]])
def test_a_request_for_an_unknown_policy_writes_nothing(root: Path, bad: object) -> None:
    state = root / "state.toml"
    prefs = settings.Preferences(make_config(root, state_path=state))
    with pytest.raises(InvalidValue, match="ask, end_anyway"):
        prefs.apply(stop_policy=bad)
    assert not state.exists()
    assert prefs.stop_policy() == "ask"


@pytest.mark.parametrize(
    ("source", "where"), [("flag", "command line"), ("file", "config file")]
)
def test_the_flag_and_the_file_both_pin_the_policy(root: Path, source: str, where: str) -> None:
    """Unlike the wait, the file pins it too: a line in the operator's file
    is a choice made on the machine, and the page does not outrank it. A
    state file left from before the pin is not read either."""
    state = root / "state.toml"
    state.write_text('stop_policy = "end_anyway"\n')
    state.chmod(0o600)
    prefs = settings.Preferences(
        make_config(root, state_path=state, stop_policy="ask", sources={"stop_policy": source})
    )
    assert (prefs.stop_policy(), prefs.stop_policy_source()) == ("ask", source)
    assert not prefs.stop_policy_editable()
    with pytest.raises(OperatorPinned, match=where):
        prefs.apply(stop_policy="end_anyway")
    assert prefs.stop_policy() == "ask"


@pytest.mark.parametrize(
    "line", ['stop_policy = "kill"', "stop_policy = true", "stop_policy = 1"]
)
def test_an_unknown_policy_in_the_state_file_is_ask_and_loses_nothing_beside_it(
    root: Path, line: str
) -> None:
    """An unreadable choice chooses nothing, and nothing is `ask`: a state
    file is never how an unknown word, or a kill, reaches the engine."""
    state = root / "state.toml"
    state.write_text(f'disabled = ["home"]\n{line}\n')
    state.chmod(0o600)
    read = settings.read_state(state)
    assert read.stop_policy is None
    assert read.hidden == {"home"}
    assert settings.Preferences(make_config(root, state_path=state)).stop_policy() == "ask"


def test_a_state_file_others_can_write_ends_nothing(root: Path) -> None:
    """#281's rule, which matters more here than for a hidden root: a state
    file anybody could have written must not be how a kill is switched on."""
    state = root / "state.toml"
    state.write_text('stop_policy = "end_anyway"\n')
    state.chmod(0o666)
    assert settings.Preferences(make_config(root, state_path=state)).stop_policy() == "ask"


def test_every_field_survives_a_round_trip(root: Path) -> None:
    state = root / "state.toml"
    written = settings.State(
        hidden=frozenset({"home"}), stop_timeout=45, stop_policy="end_anyway"
    )
    settings.write_state(state, written, configured={"home"})
    assert settings.read_state(state) == written


# -- #410: an overlay added from a look a restart has since overtaken ------


def restart_after_the_look(engine: Engine, tmux: FakeTmux) -> None:
    """Kill and Start `vessel` straight after the first pane capture taken
    once its stop has ended, which is the one look both paths take before
    adding the overlay, as a person can between that look and the add. The
    fresh agent's screen is a clear box."""
    real = tmux.capture_pane

    def capture(project: str, lines: int = 40, escapes: bool = False) -> str:
        pane = real(project, lines, escapes)
        if VESSEL not in engine._stopping:
            tmux.capture_pane = real  # type: ignore[method-assign]
            engine.kill(VESSEL)
            tmux.pane_text[VESSEL] = CLEAR_INPUT_BOX
            engine.start(VESSEL)
        return pane

    tmux.capture_pane = capture  # type: ignore[method-assign]


def test_an_expiry_whose_look_predates_a_restart_flags_nothing(root: Path) -> None:
    engine, tmux, clock = policy_engine(root)
    engine.stop(VESSEL)
    tmux.pane_text[VESSEL] = MODAL_PANE
    clock.advance(engine.prefs.stop_timeout() + 1)
    restart_after_the_look(engine, tmux)
    assert engine.expire_stops() == [VESSEL]
    restarted = engine.get(VESSEL)
    assert restarted.state is State.RUNNING
    assert restarted.pid != PANE + 1, "the restart happened"
    assert restarted.awaiting_input is False, "the old agent's question"


def test_a_refused_exit_whose_look_predates_a_restart_flags_nothing(root: Path) -> None:
    engine, tmux, clock = policy_engine(root, stop_prompt="/wrapup")
    engine.stop(VESSEL)
    clock.advance(SETTLE)
    engine.advance_wrap_ups()
    clock.advance(SETTLE)
    # The watch's read finds it idle; the exit's checks and the one look
    # after its refusal find a modal.
    tmux.pane_text[VESSEL] = TRUST_MODAL
    restart_after_the_look(engine, tmux)
    real = tmux.capture_pane

    def capture(project: str, lines: int = 40, escapes: bool = False) -> str:
        tmux.capture_pane = real  # type: ignore[method-assign]
        return CLEAR_INPUT_BOX

    tmux.capture_pane = capture  # type: ignore[method-assign]
    assert engine.advance_wrap_ups() == []
    restarted = engine.get(VESSEL)
    assert restarted.state is State.RUNNING
    assert restarted.pid != PANE + 1, "the restart happened"
    assert restarted.awaiting_input is False, "the old agent's question"
