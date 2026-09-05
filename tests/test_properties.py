"""Invariants, as properties rather than examples.

Example based tests assert the cases their author thought of, and the defect
lives in the case they did not. Three defects in this project shipped green at
98% branch coverage, and one of them, `sanitize` not being injective, is the
textbook case for this file: an encoding whose inverse must exist.

These do not replace the example tests. An example names the case somebody
cared about and reads as documentation; a property covers the ones nobody
enumerated. `docs/tech-guidelines.md` 7.5 has the argument.

Determinism: the profile below fixes the seed, so a green CI run is
reproducible and a failure can be replayed rather than being a coin toss.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from hypothesis import example, given, settings
from hypothesis import strategies as st

from hitchrail.claude_ipc import URL_BASE, _valid_bridge_id
from hitchrail.config import ConfigError
from hitchrail.hostnames import is_valid_host, normalise_host, normalise_origin
from hitchrail.procs import ProcTable, parse_ps
from hitchrail.security import parse_host
from hitchrail.tmuxnames import sanitize
from support import make_config

settings.register_profile("hitchrail", derandomize=True, max_examples=400)
settings.load_profile("hitchrail")

# Names as `discovery` would produce them, plus the characters that make tmux
# targets ambiguous, so generation is biased toward the interesting cases
# rather than random unicode.
# Not a fresh directory at all. `Config` only calls `root.is_dir()` and nothing
# here writes, so the system temp directory serves and leaks nothing.
#
# This started as `mkdtemp()` inside the test body, which left four hundred
# empty directories per invocation. Hoisting it to module scope cut that to
# one, but module scope runs at COLLECTION, so even `pytest -k something_else`
# leaked a directory. Needing no directory of our own is the version with no
# leak to trade off.
_SHARED_ROOT = Path(tempfile.gettempdir())

names = st.text(alphabet="abcxyz.:-_0129", min_size=0, max_size=12)
hosts = st.text(alphabet="abcx.-_0129:[]", min_size=0, max_size=16)


# -- sanitize: an encoding, so its inverse must exist ----------------------


# Deliberately TINY and separator heavy. Collisions live where the separators
# and the escape character meet, and a broad alphabet with long strings almost
# never draws a colliding pair: the first version of this test used `names` and
# passed against a naive replacement. Density beats breadth for injectivity.
collidable = st.text(alphabet=".:-ae", min_size=0, max_size=4)


@given(batch=st.lists(collidable, min_size=2, max_size=12))
# The historical collision, pinned. Random search over a dense alphabet finds
# naive replacements immediately, but NOT this one: the digest version needed a
# name ending in six specific hex characters, which no strategy dense enough to
# find ordinary collisions will ever draw. `@example` is how a known case rides
# along with the generated ones instead of being traded against them.
@example(batch=["a.b", "a-b-28b8f5"])
def test_sanitize_is_injective(batch: list[str]) -> None:
    """The property the digest version failed while its examples passed.

    Two distinct project names must never produce one tmux session name. If
    they do, one project reads as running because the other is, and stopping
    one kills the other's agent.

    Formulated over a SET rather than a pair, deliberately. A first version
    generated two independent strings and asserted they differ after
    sanitizing, and it passed against a naive replacement, because Hypothesis
    almost never draws `a.b` and `a-b` in the same pair. Mapping a whole batch
    and comparing cardinalities finds a collision as soon as any two members
    of one draw collide, which is enormously more likely.
    """
    unique = set(batch)
    assert len({sanitize(n) for n in unique}) == len(unique)


@given(name=names)
def test_a_sanitized_name_is_addressable(name: str) -> None:
    """tmux reads `.` and `:` as target separators, so neither may survive."""
    out = sanitize(name)
    assert "." not in out
    assert ":" not in out


@given(name=names)
def test_sanitize_is_deterministic(name: str) -> None:
    """A session must survive a restart of Hitchrail, so this cannot be salted."""
    assert sanitize(name) == sanitize(name)


@given(name=names)
def test_sanitize_is_idempotent_on_its_own_output_being_safe(name: str) -> None:
    """Sanitizing twice must not keep escaping.

    Not the same as idempotence: an encoded name is deliberately encoded again,
    because that is what keeps the two spaces disjoint. What must hold is that
    the result stays addressable however many times it is applied.
    """
    once = sanitize(name)
    twice = sanitize(once)
    assert "." not in twice
    assert ":" not in twice


# -- host normalisation: every door must agree -----------------------------


@given(host=hosts)
def test_normalise_host_is_idempotent(host: str) -> None:
    """Two doors that normalise differently is the defect shape Phase 2
    shipped five times. Idempotence is the minimum guarantee that a value
    passed through twice cannot differ from one passed through once."""
    once = normalise_host(host)
    assert normalise_host(once) == once


@given(host=hosts)
def test_a_valid_host_survives_normalisation(host: str) -> None:
    """If it validates, its canonical form validates too. Otherwise an entry
    can be accepted and then stored in a spelling that fails its own check."""
    if is_valid_host(host):
        assert is_valid_host(normalise_host(host))


@given(host=st.text(alphabet="abcx.-_0129", min_size=1, max_size=16))
def test_both_doors_reach_the_same_canonical_form(host: str) -> None:
    """The header side and the config side must agree, or nothing matches.

    This is #19 as a property. `--allow-host box.lan.` stored one spelling
    while a browser sent another, and no flag value served both. Restricted to
    inputs with no colon, since a port is refused by config rather than
    normalised, and a bracketed IPv6 is only legal on the header side.

    A first version of this file had three host properties and NONE of them
    caught a one sided strip: idempotence, validity preservation and
    round tripping all survive it. Verified to fail when either
    `normalise_host` or `parse_host` stops stripping.
    """
    parsed = parse_host(host)
    if parsed:
        assert normalise_host(host) == parsed


@given(host=hosts)
def test_parse_host_never_invents_a_host(host: str) -> None:
    """A `Host` header either parses to something normalised, or to nothing.

    Anything else means the header side and the config side can disagree, which
    is how `--allow-host box.lan.` came to serve nothing at all.
    """
    parsed = parse_host(host)
    assert parsed == normalise_host(parsed)


@given(origin=st.text(alphabet="abcx.-:/[]0129", min_size=0, max_size=20))
def test_normalise_origin_is_idempotent(origin: str) -> None:
    once = normalise_origin(origin)
    assert normalise_origin(once) == once


# -- the bridge id: an allowlist over an infinite set ----------------------


@given(value=st.text(min_size=0, max_size=40))
def test_an_accepted_bridge_id_can_never_escape_its_url(value: str) -> None:
    """The claim is about every string, and was tested with about fifteen.

    An accepted value is interpolated into a URL the interface renders as a
    link. A separator would climb out of the path segment; a scheme would point
    it at another host, which is an open redirect in our own UI.
    """
    accepted = _valid_bridge_id(value)
    if accepted is not None:
        assert "/" not in accepted
        assert "\\" not in accepted
        assert ":" not in accepted
        assert accepted.strip() == accepted
        assert accepted
        # And the URL it builds has exactly one segment after the base.
        assert (URL_BASE + accepted).count("/") == URL_BASE.count("/")


# -- the process table: termination is a property --------------------------


@given(
    rows=st.lists(
        st.tuples(
            st.integers(min_value=1, max_value=20),
            st.integers(min_value=0, max_value=20),
        ),
        max_size=25,
    )
)
def test_descendants_terminates_on_any_parent_map(rows: list[tuple[int, int]]) -> None:
    """`ps` reads a table changing under it, and pid reuse can point a ppid
    back into its own subtree. An unguarded walk spins forever, on the event
    loop, inside an HTTP request. Generated cycles are the point."""
    text = "".join(f"{pid} {ppid} 1 1 cmd\n" for pid, ppid in rows)
    table = ProcTable(parse_ps(text))
    for pid, _ in rows:
        found = table.descendants(pid)
        assert len({p.pid for p in found}) == len(found)
        assert pid not in {p.pid for p in found}


# -- Config: an accepted allowlist entry must be matchable -----------------


@given(extra=st.lists(hosts, max_size=4))
def test_every_accepted_host_is_stored_matchable(extra: list[str]) -> None:
    """The accepted-then-never-matches shape, as a property.

    Whatever `Config` accepts must be stored in a form a browser's `Host`
    header can equal after `parse_host`. An entry that cannot be matched is
    worse than a refusal, because the operator believes it took effect.
    """
    # One directory for the whole property, not one per example. A first
    # version called mkdtemp inside the body with no cleanup and leaked 400
    # empty directories into /tmp per invocation.
    try:
        cfg = make_config(
            _SHARED_ROOT,
            host="0.0.0.0",
            token="t",
            extra_hosts=tuple(extra),
            resolver=lambda: (),
        )
    except ConfigError:
        # Narrow on purpose. A bare `except Exception` would hide a TypeError
        # or AttributeError as though it were an ordinary refusal, and this
        # property is about what ACCEPTANCE guarantees.
        return
    for entry in cfg.allowed_hosts:
        # The stored form is CANONICAL, which for IPv6 is bare. A bare IPv6 is
        # not a legal Host header, so the invariant is not that the entry is
        # itself a header, but that SOME header spelling normalises to it: a
        # browser sends `[::1]` and both doors meet on `::1`.
        #
        # Hypothesis found this on its first run, against a property asserting
        # the stronger and wrong thing. The code was right; the invariant was
        # sloppy, which is most of what a property test is for.
        spellings = [entry, f"[{entry}]"] if ":" in entry else [entry]
        assert any(parse_host(s) == entry for s in spellings), (
            f"{entry!r} is in the allowlist but no Host header spelling reaches it"
        )
