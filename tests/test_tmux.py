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
