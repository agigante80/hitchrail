"""#239: a stop that ends on a prompt, and the operator's answer given ahead.

Design 4.3 step 4 forbids escalation by DEFAULT. `stop_policy = end_anyway`
is escalation chosen once, in configuration, and it is the kill the dialog
already offers at expiry, never a key typed into the prompt.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from conftest import CLEAR_INPUT_BOX, FakeClock, FakeTmux, procs_from, ps_row
from hitchrail import settings
from hitchrail.config import Config, ConfigError
from hitchrail.engine import Engine, StopMarker
from hitchrail.sessions import InvalidValue, OperatorPinned, State
from hitchrail.tmux import TmuxUnavailable
from support import DEFAULT_LABEL, make_config
from test_engine import MODAL_PANE

PANE = 500
VESSEL = f"{DEFAULT_LABEL}~vessel"


@pytest.fixture
def root(tmp_path: Path) -> Path:
    (tmp_path / "vessel").mkdir()
    return tmp_path


def policy_engine(
    root: Path, projects: tuple[str, ...] = (VESSEL,), **config: Any
) -> tuple[Engine, FakeTmux, FakeClock]:
    """An engine with `vessel` running whose process leaves when its tmux
    session does, so a kill reads `stopped` rather than `detached`."""
    panes = {name: PANE + 10 * i for i, name in enumerate(projects)}
    tmux = FakeTmux(sessions=dict(panes))
    for name in projects:
        tmux.pane_text[name] = CLEAR_INPUT_BOX

    def procs() -> Any:
        return procs_from(
            "".join(
                ps_row(pane, 1) + ps_row(pane + 1, pane, project=name)
                for name, pane in panes.items()
                if name in tmux.sessions
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
    assert tmux.killed == [VESSEL]
    assert engine.get(VESSEL).state is State.STOPPED
    assert [e["state"] for e in published if e["name"] == VESSEL][-1] == "stopped"


def test_end_anyway_kills_nothing_when_the_pane_shows_no_prompt(root: Path) -> None:
    """The request was about a prompt. A slow agent finishing a write is not
    one, and killing every slow stop is the option the ticket rejected."""
    engine, tmux, clock = policy_engine(root, stop_policy="end_anyway")
    assert expire_on(engine, tmux, clock, CLEAR_INPUT_BOX) == [VESSEL]
    assert tmux.killed == []
    assert engine.get(VESSEL).state is State.RUNNING


def test_ask_kills_nothing_on_a_prompt(root: Path) -> None:
    engine, tmux, clock = policy_engine(root)
    assert expire_on(engine, tmux, clock, MODAL_PANE) == [VESSEL]
    assert tmux.killed == []
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
    assert tmux.killed == []


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
    assert tmux.killed == []


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
    kill = tmux.kill_session

    def kill_then_restart_the_other(project: str) -> None:
        kill(project)
        if project == VESSEL:
            tmux.pane_text[other] = CLEAR_INPUT_BOX

    tmux.kill_session = kill_then_restart_the_other  # type: ignore[method-assign]
    clock.advance(engine.prefs.stop_timeout() + 1)
    assert sorted(engine.expire_stops()) == sorted([VESSEL, other])
    assert tmux.killed == [VESSEL]


def test_the_self_project_is_never_killed_by_this_path(root: Path) -> None:
    """A protected row cannot be stopped, so it can only carry a marker by a
    path nobody has written yet; this asserts the kill refuses it then too."""
    engine, tmux, clock = policy_engine(root, stop_policy="end_anyway", self_project=VESSEL)
    assert engine.get(VESSEL).protected
    engine._stopping[VESSEL] = StopMarker(clock(), "exiting", exit_at=clock())
    tmux.pane_text[VESSEL] = MODAL_PANE
    clock.advance(engine.prefs.stop_timeout() + 1)
    assert engine.expire_stops() == [VESSEL]
    assert tmux.killed == []
    assert engine.get(VESSEL).state is State.RUNNING


# -- #409: chosen on the settings page, kept in the state file ------------


def test_a_policy_set_by_a_request_is_the_one_the_expiry_acts_on(root: Path) -> None:
    """The engine reads the preference, not the frozen `Config`: a policy
    chosen on the page and read nowhere would be a control that lies."""
    engine, tmux, clock = policy_engine(root, state_path=root / "state" / "state.toml")
    engine.prefs.apply(stop_policy="end_anyway")
    assert expire_on(engine, tmux, clock, MODAL_PANE) == [VESSEL]
    assert tmux.killed == [VESSEL]


def test_a_policy_set_back_to_ask_kills_nothing(root: Path) -> None:
    engine, tmux, clock = policy_engine(root, state_path=root / "state" / "state.toml")
    engine.prefs.apply(stop_policy="end_anyway")
    engine.prefs.apply(stop_policy="ask")
    assert expire_on(engine, tmux, clock, MODAL_PANE) == [VESSEL]
    assert tmux.killed == []


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
