"""What a valid tmux name IS, tested apart from the thing that spawns.

Moved out of `tests/test_tmux.py` at #93, following the source. A suite that
tests a vocabulary from inside the adapter's test file makes the same mistake
the module did, one layer up: the adapter's tests are read under
`.claude/rules/security.md` because they exercise a spawn path, and these
exercise no such thing.

`sanitize`'s injectivity is the property to guard hardest. Two projects reaching
one session name means one reads as running because the other is, and stopping
one kills the other's agent. Since #119 that carries the multi root guarantee
too: the identifier `sanitize` receives is now `<root-label>~<folder>`.
"""

from __future__ import annotations

import pytest

from hitchrail.tmuxnames import BINARY, is_tmux_argv, sanitize


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


def test_a_tmux_server_argv_is_recognised_as_tmux() -> None:
    """#84's defect, from the vocabulary's side.

    A tmux server keeps the argv of the invocation that started it, for life,
    and that argv ends with the command the first session was asked to run. So
    a scan looking for an agent by its argv TAIL finds the server too, and
    invents a detached agent that is really a tmux.
    """
    assert is_tmux_argv(
        "tmux -S /tmp/s new-session -d -s hr-vessel claude --remote-control vessel"
    )


def test_only_argv_zero_counts_not_a_substring_anywhere() -> None:
    """The argument after `-c` is a path nobody controls, so a search of the
    whole line refuses anything running under a directory called tmux."""
    assert not is_tmux_argv("/bin/sh -c /opt/tmux/run.sh")


def test_the_basename_is_what_matches_because_argv_zero_is_however_it_was_spelled() -> None:
    assert is_tmux_argv("/usr/bin/tmux -S /tmp/s ls")


def test_an_empty_command_line_is_not_tmux() -> None:
    """`ps` can hand back a blank row, and `head[0]` on an empty split raises."""
    assert not is_tmux_argv("")


def test_a_versioned_or_suffixed_tmux_is_recognised() -> None:
    """#96. A server started as `tmux-3.4`, or as `tmux3`, is a tmux.

    #84 returns for that machine otherwise: the server's argv still ends with
    the agent's command line, orphan attribution claims it, and the row shows
    the SERVER's pid, RSS and uptime, with `ram_mb` feeding the memory guard.

    Argv captured from `ps -eww -o args` shapes rather than described: the tail
    is a real `new-session` invocation, because that tail is the whole reason
    the server is mistaken for an agent.
    """
    for spelling in ("tmux", "tmux3", "tmux-3.4", "tmux_next", "/usr/local/bin/tmux-3.5a"):
        assert is_tmux_argv(
            f"{spelling} -S /tmp/s new-session -d -s hr-vessel claude --remote-control vessel"
        ), spelling


def test_the_wider_tmux_family_is_not_claimed() -> None:
    """The obvious fix, `startswith("tmux")`, trades a narrow false negative for
    a broad false positive.

    `tmuxinator`, `tmuxp` and `tmuxifier` are real programs that SPAWN tmux, and
    a process of theirs is not a tmux server. Claiming one would hide a genuine
    agent rather than reveal a false one, which is the worse direction.

    The rule that separates them: a version or build suffix never starts with a
    letter, and a different program's name always does.
    """
    for other in ("tmuxinator", "tmuxp", "tmuxifier", "tmuxinatord"):
        assert not is_tmux_argv(f"{other} start myproject"), other


def test_the_binary_constant_is_still_the_stem_everything_matches_on() -> None:
    assert BINARY == "tmux"
