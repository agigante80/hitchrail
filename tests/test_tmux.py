"""Session naming and target addressing: the four tmux footguns.

Every behaviour asserted here was verified against a real tmux 3.4 on a private
socket before the code was written, because the whole module rests on target
specs not meaning what they look like. #27 pins those premises with a live
tmux; this tier pins that the adapter builds what it believes it builds.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from hitchrail.procs import _default_runner as procs_runner
from hitchrail.tmux import NotOurSession, Tmux, TmuxUnavailable
from hitchrail.tmux import _default_runner as tmux_runner
from hitchrail.tmuxnames import sanitize

# -- sanitize --------------------------------------------------------------


# -- target addressing -----------------------------------------------------


def test_the_session_name_carries_the_prefix() -> None:
    assert Tmux(prefix="hr-").session_name("vessel") == "hr-vessel"


def test_the_session_target_is_anchored() -> None:
    """Named regression, footgun 2.

    Verified on tmux 3.4: `has-session -t hr-vessel` SUCCEEDS against a session
    called `hr-vessel-social`, because the target prefix matches. The `=`
    forces an exact match. Remove it and a stopped project reports a sibling as
    running.
    """
    assert Tmux(prefix="hr-").session_target("vessel") == "=hr-vessel"


def test_the_pane_target_is_anchored_and_colon_terminated() -> None:
    """Named regression, footgun 3, and the colon is the load bearing half.

    Verified on tmux 3.4: `list-panes -t "=hr-vessel"` ignores the anchor and
    prefix matches, returning a NONEXISTENT session's sibling's pane pid. The
    trailing ':' qualifies the string as a session target, after which the
    anchor is honoured. Both characters are required and neither is decoration.
    """
    assert Tmux(prefix="hr-").pane_target("vessel") == "=hr-vessel:"


def test_targets_are_built_from_the_sanitized_name() -> None:
    """Or the adapter addresses a name tmux never stored."""
    tmux = Tmux(prefix="hr-")
    assert tmux.session_target("dotted.site") == f"=hr-{sanitize('dotted.site')}"
    assert "." not in tmux.session_target("dotted.site")


def test_a_custom_prefix_is_honoured() -> None:
    assert Tmux(prefix="test-").session_target("x") == "=test-x"


# -- the operations (#23) --------------------------------------------------


class FakeRunner:
    """Records argv and returns scripted output, so no tmux is executed."""

    def __init__(
        self,
        stdout: dict[str, str] | None = None,
        rc: dict[str, int] | None = None,
    ) -> None:
        self.calls: list[list[str]] = []
        self._stdout = stdout or {}
        self._rc = rc or {}

    def __call__(self, argv: list[str]) -> subprocess.CompletedProcess[str]:
        self.calls.append(argv)
        verb = next((a for a in argv if a in _VERBS), "")
        return subprocess.CompletedProcess(
            argv, self._rc.get(verb, 0), self._stdout.get(verb, ""), ""
        )


_VERBS = {
    "has-session",
    "list-panes",
    "new-session",
    "kill-session",
    "capture-pane",
    "send-keys",
}


def drive_every_method(tmux: Tmux) -> None:
    """Exercise the whole public surface, for the sweeps below."""
    tmux.has_session("p")
    tmux.panes()
    tmux.pane_pid("p")
    tmux.capture_pane("p")
    tmux.new_session("p", "/srv/p", ["claude"])
    tmux.send_keys("p", "C-c")
    tmux.kill_session("p")


def test_has_session_uses_the_anchored_target() -> None:
    runner = FakeRunner()
    assert Tmux(prefix="hr-", run=runner).has_session("vessel") is True
    assert runner.calls[-1] == ["tmux", "has-session", "-t", "=hr-vessel"]


def test_the_pane_map_is_one_call_whatever_the_session_count() -> None:
    """The performance contract, asserted rather than hoped for.

    The engine calls this once per list, not once per project. A call per
    project is a subprocess spawn per row.
    """
    runner = FakeRunner(stdout={"list-panes": "hr-a 1\nhr-b 2\nhr-c 3\n"})
    tmux = Tmux(prefix="hr-", run=runner)
    assert tmux.panes().ours == {"hr-a": 1, "hr-b": 2, "hr-c": 3}
    assert len(runner.calls) == 1
    assert "-a" in runner.calls[0]


def test_both_halves_of_the_pane_map_come_from_the_same_call() -> None:
    """#85. Reading who else is on the server must not cost a second call.

    The whole reason foreign panes are affordable is that `list-panes -a`
    already returned them and this adapter threw them away. A version that
    asked twice would be the per row spawn the budget forbids, arrived at from
    a different direction.
    """
    runner = FakeRunner(stdout={"list-panes": "cc-vessel 111\nhr-vessel 4242\n"})
    panes = Tmux(prefix="hr-", run=runner).panes()
    assert panes.ours == {"hr-vessel": 4242}
    assert panes.foreign == {111: "cc-vessel"}
    assert len(runner.calls) == 1


def test_a_foreign_session_is_named_but_never_ours() -> None:
    """#85 changed this test's meaning, deliberately, and it is kept for that.

    It asserted that sessions we did not create are invisible in BOTH
    directions, which is what made an agent inside one of them read as an
    orphan. Foreign sessions are now visible to the READ path and still absent
    from `ours`, which is what every write path builds its target from.
    """
    runner = FakeRunner(stdout={"list-panes": "work 111\nhr-vessel 4242\n"})
    panes = Tmux(prefix="hr-", run=runner).panes()
    assert panes.ours == {"hr-vessel": 4242}
    assert "work" not in panes.ours
    assert panes.foreign == {111: "work"}


def test_a_prefixed_name_with_a_space_is_not_ours() -> None:
    """Found in review of #85, and it is the parser making things worse.

    `rpartition` fixed a foreign name with a space being DROPPED. For one
    input it made the outcome worse instead: `hr-my project` classifies as
    ours, its pane pid lands in `owned`, the agent underneath is hidden, and
    the row derives `stopped`. `stopped` offers Start, and Start on a folder
    that already has an agent is the second agent in one folder the whole
    derivation exists to prevent.

    A space is what disqualifies it: `session_name` is `prefix + sanitize(...)`
    and both halves of a qualified identifier go through `NAME_PATTERN`, which
    forbids one, so we could not have created this session.
    """
    runner = FakeRunner(stdout={"list-panes": "hr-my project 5000\nhr-vessel 4242\n"})
    panes = Tmux(prefix="hr-", run=runner).panes()
    assert panes.ours == {"hr-vessel": 4242}
    assert panes.foreign == {5000: "hr-my project"}


def test_a_foreign_session_name_with_a_space_survives_the_parse() -> None:
    """#85, and the reason the split is `rpartition`.

    Our own names cannot hold a space, because `NAME_PATTERN` refuses one
    (#173). A foreign name is chosen by whoever made that session. Splitting on
    the FIRST space read the pid as `work 111`, dropped the line, and left the
    agent inside that session looking unowned: the defect this ticket removes,
    reintroduced by the parser.
    """
    runner = FakeRunner(stdout={"list-panes": "my work 111\nhr-vessel 4242\n"})
    panes = Tmux(prefix="hr-", run=runner).panes()
    assert panes.foreign == {111: "my work"}
    assert panes.ours == {"hr-vessel": 4242}


def test_a_foreign_session_name_is_escaped_on_the_way_in() -> None:
    """It reaches a screen, and nothing downstream would know to escape it.

    A session name is chosen by whoever created it, so it can carry the control
    sequences `display_name` exists to defuse. Escaped here, at the boundary
    where untrusted output enters, rather than at each of the places that
    render it.
    """
    runner = FakeRunner(stdout={"list-panes": "ev\x1b[2Jil 111\n"})
    # The ESC is escaped and the rest is left alone, which is exactly enough:
    # `[2J` without an ESC in front of it is four printable characters.
    assert Tmux(prefix="hr-", run=runner).panes().foreign == {111: "ev\\u001b[2Jil"}


def test_a_failed_list_panes_is_an_empty_map_not_an_exception() -> None:
    """No tmux server running is the normal state, not an error."""
    runner = FakeRunner(rc={"list-panes": 1})
    panes = Tmux(prefix="hr-", run=runner).panes()
    assert panes.ours == {}
    assert panes.foreign == {}


def test_a_malformed_pane_line_is_skipped_and_the_rest_survive() -> None:
    runner = FakeRunner(stdout={"list-panes": "hr-a notapid\nhr-b 7\n\n"})
    assert Tmux(prefix="hr-", run=runner).panes().ours == {"hr-b": 7}


def test_the_first_pane_wins_for_a_multi_pane_session() -> None:
    runner = FakeRunner(stdout={"list-panes": "hr-a 10\nhr-a 11\n"})
    assert Tmux(prefix="hr-", run=runner).panes().ours == {"hr-a": 10}


def test_the_first_pane_wins_for_a_multi_pane_foreign_session() -> None:
    """The same rule on the other half. Two panes in one foreign session must
    not make the second one overwrite the first, or which pid maps to which
    name depends on tmux's output order."""
    runner = FakeRunner(stdout={"list-panes": "cc-a 10\ncc-a 11\n"})
    assert Tmux(prefix="hr-", run=runner).panes().foreign == {10: "cc-a", 11: "cc-a"}


def test_pane_pid_uses_the_colon_terminated_target() -> None:
    """Named regression, footgun 3, at the call site rather than the builder."""
    runner = FakeRunner(stdout={"list-panes": "4242\n"})
    assert Tmux(prefix="hr-", run=runner).pane_pid("vessel") == 4242
    assert "=hr-vessel:" in runner.calls[-1]


@pytest.mark.parametrize(
    ("stdout", "rc"), [("", 1), ("", 0), ("notapid\n", 0)], ids=["failed", "empty", "junk"]
)
def test_pane_pid_is_none_when_it_cannot_be_read(stdout: str, rc: int) -> None:
    runner = FakeRunner(stdout={"list-panes": stdout}, rc={"list-panes": rc})
    assert Tmux(prefix="hr-", run=runner).pane_pid("vessel") is None


def test_an_empty_prefix_is_refused_at_construction() -> None:
    """The scoping guard, and it lives HERE rather than in `kill_session`.

    An empty prefix is the case that matters: every session name then starts
    with it, so every session on the server looks like ours. `Config` refuses
    one for exactly this reason, and this module refuses it too rather than
    trusting its caller came through Config.

    There was a second test named for `kill_session` refusing an unprefixed
    name. It constructed `Tmux(prefix="")` inside `pytest.raises`, so the
    refusal came from here anyway and its `runner.calls == []` was trivially
    true because no object was ever built. It duplicated this one under a name
    asserting a defence that does not exist, which is the exact failure
    `kill_session`'s docstring cites as the reason its tautological guard was
    removed.
    """
    with pytest.raises(NotOurSession, match="prefix is required"):
        Tmux(prefix="")


def test_kill_session_targets_only_the_anchored_name() -> None:
    runner = FakeRunner()
    Tmux(prefix="hr-", run=runner).kill_session("vessel")
    assert runner.calls[-1] == ["tmux", "kill-session", "-t", "=hr-vessel"]


def test_no_method_can_reach_kill_server() -> None:
    """The rule that protects the developer's own tmux server.

    A bare `tmux` honours $TMUX over $TMUX_TMPDIR, so from inside a session
    `kill-server` destroys the real one and every window in it.
    """
    runner = FakeRunner()
    drive_every_method(Tmux(prefix="hr-", run=runner))
    assert runner.calls, "the sweep drove nothing, so it proves nothing"
    assert not any("kill-server" in argv for argv in runner.calls)


def test_the_socket_is_carried_on_every_call() -> None:
    """A method that builds argv by hand and forgets -S talks to another server."""
    runner = FakeRunner()
    drive_every_method(Tmux(prefix="hr-", socket="/run/hr/hr.sock", run=runner))
    for argv in runner.calls:
        assert argv[:3] == ["tmux", "-S", "/run/hr/hr.sock"], argv


def test_no_socket_means_no_socket_flag() -> None:
    """`-S` is two different flags in tmux, told apart only by position.

    Before the verb it is the socket path; after it, `capture-pane -S -40` is
    where the history starts. So this asserts the SLOT, not the absence of the
    string: a blanket "-S not in argv" fails on a correct capture-pane call,
    which is how this test was wrong the first time.
    """
    runner = FakeRunner()
    drive_every_method(Tmux(prefix="hr-", run=runner))
    assert runner.calls
    for argv in runner.calls:
        assert argv[1] != "-S", argv


def test_new_session_is_detached_and_carries_the_working_directory() -> None:
    runner = FakeRunner()
    Tmux(prefix="hr-", run=runner).new_session("vessel", "/srv/vessel", ["claude", "--x"])
    argv = runner.calls[-1]
    assert argv[:4] == ["tmux", "new-session", "-d", "-s"]
    assert "-c" in argv and "/srv/vessel" in argv

    # The agent argv is no longer last: #66 chains a `set-option` after it.
    # Asserted as a contiguous run rather than by position, so the test says
    # "these arguments arrive together and in this order" and stays true
    # whatever is appended next.
    split = argv.index(";")
    assert argv[split - 2 : split] == ["claude", "--x"]

    # Created with the plain name. Only TARGETS carry the anchor, and the
    # chained option is a target, so both spellings appear and each is in the
    # right place.
    assert argv[argv.index("-s") + 1] == "hr-vessel"
    assert argv[split + 1 :] == [
        "set-option",
        "-t",
        "=hr-vessel:",
        "remain-on-exit",
        "on",
    ]


def test_send_keys_passes_each_key_as_its_own_argument() -> None:
    """tmux tells `C-c` the key from `C-c` the text by argument position.

    Joining them into one string sends the literal characters instead.
    """
    runner = FakeRunner()
    Tmux(prefix="hr-", run=runner).send_keys("vessel", "/exit", "Enter")
    assert runner.calls[-1][-2:] == ["/exit", "Enter"]


def test_capture_pane_joins_wrapped_lines_and_bounds_the_history() -> None:
    runner = FakeRunner(stdout={"capture-pane": "output\n"})
    tmux = Tmux(prefix="hr-", run=runner)
    assert tmux.capture_pane("vessel", lines=10) == "output\n"
    argv = runner.calls[-1]
    assert "-p" in argv and "-J" in argv
    assert "-10" in argv


def test_capture_pane_is_empty_rather_than_raising_when_the_session_is_gone() -> None:
    runner = FakeRunner(rc={"capture-pane": 1})
    assert Tmux(prefix="hr-", run=runner).capture_pane("vessel") == ""


def test_no_claude_literal_leaks_into_this_module() -> None:
    """The quarantine is a usage rule, and `lint-imports` cannot see a string."""
    source = (Path(__file__).parent.parent / "src" / "hitchrail" / "tmux.py").read_text()
    assert "/exit" not in source
    assert "--remote-control" not in source


# -- tmux that cannot be run at all ----------------------------------------


def missing_tmux(argv: list[str]) -> subprocess.CompletedProcess[str]:
    raise FileNotFoundError(2, "No such file or directory", "tmux")


@pytest.mark.parametrize(
    "call",
    [
        lambda t: t.panes(),
        lambda t: t.has_session("p"),
        lambda t: t.pane_pid("p"),
        lambda t: t.capture_pane("p"),
        lambda t: t.new_session("p", "/srv/p", ["claude"]),
        lambda t: t.kill_session("p"),
        lambda t: t.send_keys("p", "C-c"),
    ],
    ids=["panes", "has_session", "pane_pid", "capture", "new", "kill", "keys"],
)
def test_a_tmux_that_cannot_be_run_raises_rather_than_lying(call: object) -> None:
    """ "Could not look" must not collapse into "nothing is there".

    An earlier version returned a synthetic non zero code, on the reasoning
    that every caller treats non zero as "no". That was wrong twice: the write
    methods discard the return entirely, so a failed start read as a successful
    one; and for the reads it made a LIVE agent derive as `detached`, which
    refuses to start and whose kill has no session to kill. The project became
    unstartable, which is the same outcome `_find_detached` was fixed for.
    """
    tmux = Tmux(prefix="hr-", run=missing_tmux)
    with pytest.raises(TmuxUnavailable):
        call(tmux)  # type: ignore[operator]


def test_a_tmux_that_runs_and_says_no_is_still_just_no() -> None:
    """The other half. A non zero return is an ANSWER, not a failure, and must
    keep meaning what it meant: no server running is the ordinary state of a
    machine with nothing started."""
    runner = FakeRunner(rc=dict.fromkeys(_VERBS, 1))
    tmux = Tmux(prefix="hr-", run=runner)
    assert tmux.panes().ours == {}
    assert tmux.has_session("p") is False
    assert tmux.pane_pid("p") is None
    assert tmux.capture_pane("p") == ""


# -- #67: an unbounded subprocess call in a request path is a hang ---------


@pytest.mark.parametrize(
    "runner",
    [tmux_runner, procs_runner],
    ids=["tmux", "process table"],
)
def test_both_default_runners_pass_a_bound_to_subprocess(
    runner: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#67's third candidate, and a defect whatever CI is doing.

    Both of these run inside an HTTP handler. `subprocess.run` with no timeout
    waits forever, so a tmux that blocks, on a loaded machine, an NFS home, a
    server part way through a restart, does not make the listing slow: it makes
    the request never answer and the browser wait with it.

    Asserted on the CALL rather than by spawning something slow. This tier is
    hermetic with every external surface faked, per `.claude/CLAUDE.md`, and a
    real `sleep 30` in it is exactly the kind of thing that tier exists not to
    have. That the bound then WORKS is `subprocess`'s business and is checked
    where a real process is already allowed, in `test_live_tmux.py`.
    """
    seen: dict[str, object] = {}

    def fake_run(argv: list[str], **kw: object) -> object:
        seen.update(kw)
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    runner(["tmux", "list-panes"])  # type: ignore[operator]
    bound = seen.get("timeout")
    assert isinstance(bound, float), "no bound reached subprocess.run"
    assert 0 < bound <= 30, "the bound is not a bound"


def test_a_tmux_that_never_answers_becomes_an_honest_refusal() -> None:
    """#67. The bound is half of it; what happens when it fires is the rest.

    `TimeoutExpired` is a `SubprocessError` and not an `OSError`, so before
    this it left the adapter unhandled and reached the client as a 500 with a
    traceback. "We did not get an answer" is exactly what `TmuxUnavailable`
    exists to say, and the engine turns that into the honest 503 rather than
    into "nothing is running".
    """
    import subprocess

    def wedged(argv: list[str]) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(argv, 10.0)

    with pytest.raises(TmuxUnavailable):
        Tmux(prefix="hr-", run=wedged).panes()


def test_the_spawn_does_not_hand_the_agent_the_api_token() -> None:
    """#113. An agent Hitchrail starts inherited `HITCHRAIL_TOKEN`.

    The agent runs as the same user with `--dangerously-skip-permissions`, so it
    could read the operator's `EnvironmentFile` anyway and the variable grants no
    capability it did not have. What it changes is how easy the token is to
    stumble INTO: "print your environment" is an ordinary thing to ask an agent,
    prompt injection from a repository it reads is an ordinary thing to worry
    about, the result lands in a pane, and the log drawer shows panes.

    Measured on tmux 3.4 rather than chosen from the manual, because the ticket
    warns each option "silently does nothing" in the wrong case:

    - a pane inherits the variable from the SERVER, which took it when the
      server started, so filtering one client invocation changes nothing;
    - `new-session -e HITCHRAIL_TOKEN=` works even on a pre existing server, and
      leaves the variable SET AND EMPTY rather than absent;
    - `env -u` in the argv we already control leaves it genuinely UNSET
      (`printenv` exits 1), works whatever the server's state, mutates nothing
      belonging to tmux or to anybody else's sessions, and does not survive into
      `ps`, so argv tail matching is untouched.
    """
    run = FakeRunner()
    tmux = Tmux(prefix="hr-", run=run, scrub_env=("HITCHRAIL_TOKEN",))
    tmux.new_session("vessel", "/srv/vessel", ["claude", "--remote-control", "vessel"])

    spawn = next(c for c in run.calls if "new-session" in c)
    assert "env" in spawn and "-u" in spawn and "HITCHRAIL_TOKEN" in spawn
    assert spawn.index("env") < spawn.index("claude"), "the scrub must come before the agent"


def test_the_scrub_does_not_disturb_the_argv_tail_detection_matches_on() -> None:
    """`env` execs the agent and is replaced by it, so the prefix never reaches
    `ps`, verified on a real machine. The tail is what `find_detached` matches,
    and it is unchanged.

    The tail is read up to the `;` rather than off the end of the list, because
    #66 chains `set-option ... remain-on-exit on` after the agent's argv: the
    command does not END with what the agent runs, and asserting on `[-3:]`
    tests the chaining instead. Reading to the separator is also what makes
    this a real guard: the scrub goes in FRONT, so any implementation that put
    it behind, or that split an argument, moves these three elements.
    """
    run = FakeRunner()
    tmux = Tmux(prefix="hr-", run=run, scrub_env=("HITCHRAIL_TOKEN",))
    tmux.new_session("vessel", "/srv/vessel", ["claude", "--remote-control", "vessel"])

    spawn = next(c for c in run.calls if "new-session" in c)
    chained = spawn.index(";")
    assert spawn[chained - 3 : chained] == ["claude", "--remote-control", "vessel"]


def test_nothing_is_scrubbed_when_nothing_is_named() -> None:
    """The default. A `Tmux` built without the list spawns exactly what it was
    given, so this cannot quietly change what an unrelated caller runs."""
    run = FakeRunner()
    tmux = Tmux(prefix="hr-", run=run)
    tmux.new_session("vessel", "/srv/vessel", ["claude", "--remote-control", "vessel"])

    spawn = next(c for c in run.calls if "new-session" in c)
    assert "env" not in spawn
