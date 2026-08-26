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

from hitchrail.tmux import NotOurSession, Tmux, sanitize

# -- sanitize --------------------------------------------------------------


@pytest.mark.parametrize("name", ["dotted.site", "a:b", "a:b.c", "..", "a.b.c.d"])
def test_a_name_with_a_separator_becomes_addressable(name: str) -> None:
    """tmux reads '.' and ':' as window and pane separators in a target spec.

    Verified on tmux 3.4: a session created as `hr-dotted.site` is STORED as
    `hr-dotted_site`, so it exists under a name nobody looked for and
    `has-session -t =hr-dotted.site` fails while the agent is running. That
    presents as the session vanishing. Emitting neither character sidesteps the
    rewrite entirely.
    """
    out = sanitize(name)
    assert "." not in out
    assert ":" not in out


def test_an_ordinary_name_is_untouched() -> None:
    """The readability guarantee that actually matters.

    Most project names hold neither separator, and those pass through
    unchanged, so `tmux ls` stays legible for the common case. Names that must
    be encoded are less pretty, and that is the right trade: the project keeps
    the display name apart from the tmux name precisely so the tmux name can be
    optimised for correctness.
    """
    for name in ("hitchrail", "my-app", "project_2", "a-b-28b8f5"):
        assert sanitize(name) == name


def test_an_encoded_name_keeps_its_stem_recognisable() -> None:
    """Not required for correctness, but it is why the encoding is not a hash."""
    assert "dotted" in sanitize("dotted.site")


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("a.b", "a-b"),
        ("a:b", "a.b"),
        ("a.b", "a:b"),
        # The pair that broke the digest version. `a.b` mapped to
        # `a-b-<6 hex of blake2b>`, and a project literally named that string
        # was already safe so it came back unchanged and collided. The
        # colliding name is computable by anyone who can create a folder.
        ("a.b", "a-b-28b8f5"),
        ("dotted.site", "e-dotted-dit"),
        ("a-b", "e-a--b"),
    ],
)
def test_sanitize_is_injective(a: str, b: str) -> None:
    """The expensive one to leave out.

    A plain replacement maps `a.b` and `a-b` onto the same string, so two
    folders share one tmux session: one reads as running because the other is,
    and stopping one kills the other's agent. That is the same "two agents in
    one folder" outcome #11 fixed from the discovery side.
    """
    assert sanitize(a) != sanitize(b)


def test_sanitize_is_injective_over_a_generated_corpus() -> None:
    """Injectivity asserted by exhaustion, not by three hand picked pairs.

    Hand picked pairs are how the digest version passed while colliding: every
    pair somebody thought to write down was fine. This builds every string up
    to length four over an alphabet holding both separators, the escape
    character and the encoded prefix, and asserts the mapping never merges two
    of them.
    """
    from itertools import product

    alphabet = ".:-abe"
    names = ["".join(p) for n in range(1, 5) for p in product(alphabet, repeat=n)]
    seen: dict[str, str] = {}
    for name in names:
        out = sanitize(name)
        clash = seen.get(out)
        assert clash is None, f"{name!r} and {clash!r} both sanitize to {out!r}"
        seen[out] = name
    assert len(seen) == len(names)


@pytest.mark.parametrize("name", ["a.b", "e-x", "a-b", "..", "e-", "a:b.c"])
def test_a_sanitized_name_is_free_of_separators(name: str) -> None:
    """Whatever the encoding does, the output must be addressable."""
    out = sanitize(name)
    assert "." not in out
    assert ":" not in out


def test_an_already_safe_name_is_left_alone() -> None:
    """No digest on a name that needed no change, so ordinary names stay readable."""
    assert sanitize("a-b") == "a-b"
    assert sanitize("hitchrail") == "hitchrail"


def test_sanitize_is_deterministic() -> None:
    """A session has to survive a restart of Hitchrail, so this cannot be salted."""
    assert sanitize("dotted.site") == sanitize("dotted.site")


def test_sanitize_handles_an_empty_name() -> None:
    """`scan` never yields one, but a crash here would be a 500 on a listing."""
    assert sanitize("") == ""


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
    tmux.pane_pids()
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
    assert tmux.pane_pids() == {"hr-a": 1, "hr-b": 2, "hr-c": 3}
    assert len(runner.calls) == 1
    assert "-a" in runner.calls[0]


def test_a_foreign_session_is_not_in_the_pane_map() -> None:
    """Sessions we did not create are invisible to us, in both directions."""
    runner = FakeRunner(stdout={"list-panes": "work 111\nhr-vessel 4242\n"})
    assert Tmux(prefix="hr-", run=runner).pane_pids() == {"hr-vessel": 4242}


def test_a_failed_list_panes_is_an_empty_map_not_an_exception() -> None:
    """No tmux server running is the normal state, not an error."""
    runner = FakeRunner(rc={"list-panes": 1})
    assert Tmux(prefix="hr-", run=runner).pane_pids() == {}


def test_a_malformed_pane_line_is_skipped_and_the_rest_survive() -> None:
    runner = FakeRunner(stdout={"list-panes": "hr-a notapid\nhr-b 7\n\n"})
    assert Tmux(prefix="hr-", run=runner).pane_pids() == {"hr-b": 7}


def test_the_first_pane_wins_for_a_multi_pane_session() -> None:
    runner = FakeRunner(stdout={"list-panes": "hr-a 10\nhr-a 11\n"})
    assert Tmux(prefix="hr-", run=runner).pane_pids() == {"hr-a": 10}


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


def test_killing_a_session_without_our_prefix_is_refused_before_the_call() -> None:
    """The refusal must happen BEFORE the subprocess, not after it.

    An empty prefix is what makes this guard vacuous: every session name then
    starts with it. `Config` refuses one for exactly this reason, and this
    module refuses it too rather than trusting its caller went through Config.
    """
    runner = FakeRunner()
    with pytest.raises(NotOurSession):
        Tmux(prefix="", run=runner).kill_session("someone-elses-session")
    assert runner.calls == []


def test_an_empty_prefix_is_refused_at_construction() -> None:
    with pytest.raises(NotOurSession):
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
    assert argv[-2:] == ["claude", "--x"]
    # Created with the plain name; only TARGETS carry the anchor.
    assert "hr-vessel" in argv
    assert "=hr-vessel" not in argv


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
