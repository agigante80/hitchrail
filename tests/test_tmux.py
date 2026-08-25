"""Session naming and target addressing: the four tmux footguns.

Every behaviour asserted here was verified against a real tmux 3.4 on a private
socket before the code was written, because the whole module rests on target
specs not meaning what they look like. #27 pins those premises with a live
tmux; this tier pins that the adapter builds what it believes it builds.
"""

from __future__ import annotations

import pytest

from hitchrail.tmux import Tmux, sanitize

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


def test_sanitize_keeps_the_readable_part() -> None:
    assert sanitize("dotted.site").startswith("dotted-it")


@pytest.mark.parametrize(("a", "b"), [("a.b", "a-b"), ("a:b", "a.b"), ("a.b", "a:b")])
def test_sanitize_is_injective(a: str, b: str) -> None:
    """The expensive one to leave out.

    A plain replacement maps `a.b` and `a-b` onto the same string, so two
    folders share one tmux session: one reads as running because the other is,
    and stopping one kills the other's agent. That is the same "two agents in
    one folder" outcome #11 fixed from the discovery side.
    """
    assert sanitize(a) != sanitize(b)


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
