"""Assertions written because a mutant survived (#35).

Every test here exists because mutation testing flipped one operator, one
boundary or one slice in the five modules between a web page and a shell, and
the whole suite stayed green. Coverage had already executed all of these lines.

They live together rather than scattered into the per module files because what
they have in common is worth seeing: each names a specific mutation and would
fail against it, and that mutation is written into the docstring so a later
reader can re run it rather than trusting this file.

Re run with `uv sync --group mutation && uv run mutmut run`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hitchrail import discovery, projectnames
from hitchrail.config import ConfigError, remote_reach
from hitchrail.hostnames import (
    MAX_HOSTNAME_LENGTH,
    is_valid_host,
    is_wildcard_host,
)
from hitchrail.security import parse_host
from support import make_config

# -- the one that was an open redirect ---------------------------------------


# -- boundaries, where > and >= are one character apart ----------------------


def test_a_hostname_of_exactly_the_maximum_length_is_valid() -> None:
    """Mutant killed: `len(bare) > MAX_HOSTNAME_LENGTH` to `>=`.

    253 is the limit, not the first refusal. With `>=` a host of exactly the
    legal maximum is locked out of its own allowlist, which is the shape of the
    RFC 1123 tightening that #18 already had to undo once.
    """
    label = "a" * 63
    exact = ".".join([label, label, label, "a" * (MAX_HOSTNAME_LENGTH - 3 * 64)])
    assert len(exact) == MAX_HOSTNAME_LENGTH
    assert is_valid_host(exact) is True
    assert is_valid_host(exact + "a") is False


def test_a_name_at_the_length_limit_is_explained_by_its_real_fault() -> None:
    """Mutant killed: `len(name) > MAX_NAME_LENGTH` to `>=`.

    Note where the boundary actually is, because the obvious test does not
    reach it: `explain_name` returns None immediately when `NAME_PATTERN`
    matches, so a VALID name of exactly 255 characters never gets as far as the
    length check and the mutant is invisible to it. That is why the first
    version of this test passed against the mutation.

    The reachable case is a name of exactly the limit that fails the pattern
    for another reason. With `>=` it is explained as being over a limit it is
    exactly at, and the character that is really wrong is never mentioned.
    """
    exact_but_invalid = "a" * (projectnames.MAX_NAME_LENGTH - 1) + "!"
    assert len(exact_but_invalid) == projectnames.MAX_NAME_LENGTH
    reason = projectnames.explain_name(exact_but_invalid) or ""
    assert "over the" not in reason, reason
    assert "'!'" in reason, reason

    too_long = "a" * (projectnames.MAX_NAME_LENGTH + 1)
    assert "over the" in (projectnames.explain_name(too_long) or "")

    assert projectnames.explain_name("a" * projectnames.MAX_NAME_LENGTH) is None


def test_a_host_with_one_colon_is_a_port_and_two_is_ipv6() -> None:
    """Mutant killed: `value.count(":") > 1` to `> 2`.

    One colon is `host:port` and the port is stripped. Two or more means an
    unbracketed IPv6 literal, which is not a legal Host header, and the
    docstring says such a value is REFUSED rather than guessed at. With `> 2` a
    two colon value falls through to the split and `fe80::1` becomes `fe80`,
    which is a host somebody could then put in an allowlist.

    An unbracketed literal is refused; the bracketed form a browser really
    sends is not, and both halves are asserted so a fix in either direction
    fails.
    """
    assert parse_host("box.lan:8787") == "box.lan"
    assert parse_host("fe80::1") == "", "an unbracketed literal is refused, not split"
    assert parse_host("a:b:c") == ""
    assert parse_host("[fe80::1]:8787") == "fe80::1", "the form a browser sends still works"


def test_the_wildcard_spelling_is_recognised() -> None:
    """Mutant killed: the `bare == "*"` branch returning False.

    Nothing exercised it, and `Config._check_bind_host` relies on it to refuse
    `--host '*'` with a message naming 0.0.0.0. Flip it and that refusal turns
    into a getaddrinfo failure from uvicorn.
    """
    assert is_wildcard_host("*") is True
    assert is_wildcard_host("0.0.0.0") is True
    assert is_wildcard_host("::") is True
    assert is_wildcard_host("box.lan") is False


# -- the tie break the guidelines already name as a shipped defect -----------


def test_a_real_directory_wins_the_tie_against_a_symlink(tmp_path: Path) -> None:
    """Mutants killed: `is_link = False` to `True`, and `1 if is_link else 0`
    to `2 if is_link else 0`.

    This is the deduplication tie break that `docs/tech-guidelines.md` 7.5
    cites as one of the three defects that shipped green at 98% coverage: a
    running `zebra` lost the tie the moment somebody added `alpha -> zebra`, so
    it vanished from the list, came back under a name with no session, read as
    stopped, and a tap would have put a second agent in the same directory.

    The ordering function had no direct test. Coverage said the line ran.
    """
    (tmp_path / "zebra").mkdir()
    (tmp_path / "alpha").symlink_to(tmp_path / "zebra", target_is_directory=True)

    ordered = sorted([tmp_path / "alpha", tmp_path / "zebra"], key=discovery._dedup_order)

    assert [p.name for p in ordered] == ["zebra", "alpha"], (
        "the real directory must sort first, or a link renames a running project"
    )
    assert discovery._dedup_order(tmp_path / "zebra")[0] == 0
    assert discovery._dedup_order(tmp_path / "alpha")[0] == 1


def test_an_unreadable_entry_sorts_as_a_real_directory(tmp_path: Path) -> None:
    """Mutant killed: `is_link = False` to `True` in the `except OSError` arm.

    The other `_dedup_order` mutant, and a different case: this is the fallback
    when `is_symlink()` itself raises, which the docstring says is EACCES in
    practice. Nothing exercised it, so the value chosen for the failure case
    was free to be either.

    It matters which. Treating an unreadable entry as a symlink makes it lose
    every tie, so a directory Hitchrail cannot stat disappears behind any link
    that shares its resolved target.
    """
    locked = tmp_path / "locked"
    locked.mkdir()
    (locked / "inner").mkdir()
    locked.chmod(0o000)
    try:
        entry = locked / "inner"
        try:
            entry.is_symlink()
        except OSError:
            pass
        else:  # pragma: no cover - root, or a filesystem ignoring the mode
            pytest.skip("is_symlink did not raise, so the except arm is unreachable here")
        assert discovery._dedup_order(entry) == (0, "inner")
    finally:
        locked.chmod(0o755)


# -- #108's own code, which arrived with the same gaps ----------------------


def test_a_malformed_origin_does_not_end_the_reach_scan(tmp_path: Path) -> None:
    """Mutant killed: `continue` to `break` in `remote_reach`.

    An unparseable origin makes the loop skip that entry. With `break` it stops
    the scan, so a remote origin listed AFTER a bad one is never seen and the
    token is not demanded. The CLI calls this before `Config` validates the
    origins, so a bad entry really can be sitting in front of a good one.
    """
    assert (
        remote_reach("127.0.0.1", (), ("http://[::1", "https://box.tailnet.ts.net")) is not None
    )


def test_a_trailing_slash_is_stripped_from_an_origin() -> None:
    """Mutant NOT killed, and recorded as equivalent rather than claimed.

    `rstrip("/")` to `lstrip("/")` survives, and it survives for a real reason:
    every well formed origin starts with `h`, so `lstrip("/")` removes nothing
    and `urlsplit` parses the trailing slash correctly either way. There is no
    input that distinguishes them, which is the definition of an equivalent
    mutant.

    An earlier version of this docstring said the mutant was killed. It was
    not, and the verification run said so. Claiming a kill that did not happen
    is the exact defect this whole ticket is about, so the claim is corrected
    here rather than quietly dropped.

    The assertions stay: they pin the behaviour that the next edit to this line
    could break, even though no mutation operator can express that edit.
    """
    assert remote_reach("127.0.0.1", (), ("https://box.tailnet.ts.net/",)) is not None
    assert remote_reach("127.0.0.1", (), ("https://localhost/",)) is None


def test_the_reach_refusal_names_the_flag_it_came_from(tmp_path: Path) -> None:
    """Mutant killed: the reason string uppercased or replaced.

    The message is the whole value of the refusal: "a token is required" on a
    127.0.0.1 bind reads as a bug unless it says which flag asked for it.
    """
    with pytest.raises(ConfigError) as excinfo:
        make_config(tmp_path, host="127.0.0.1", token=None, extra_hosts=("box.lan",))
    message = str(excinfo.value)
    assert "--allow-host" in message and "box.lan" in message
    assert message == message.lower() or "--allow-host" in message


# -- a second batch: the boolean operators in the boundary's own helpers -----


def test_a_non_bearer_scheme_never_yields_a_credential() -> None:
    """Mutant killed: `not separator or scheme.lower() != "bearer"` to `and`.

    The distinguishing input is not the one that looks obvious. `Bearer` alone
    and `""` give the same answer under both, because each satisfies both
    halves. What separates them is a header that HAS a separator and a wrong
    scheme: `Basic abc`. Under `or` it is refused for the scheme; under `and`
    the first half is False, the guard never fires, and `abc` is returned as a
    bearer credential.

    So the mutation turns "Authorization: Basic <token>" into a working
    carrier. `compare_digest` still has to match, but a scheme check that
    accepts any scheme is not a scheme check.

    Refusal is the empty string here, not None: `_bearer` returns str.
    """
    from hitchrail.security import _bearer

    assert _bearer("Basic abc") == "", "a non bearer scheme must yield nothing"
    assert _bearer("Digest abc") == ""
    assert _bearer("Bearer") == ""
    assert _bearer("") == ""
    assert _bearer("Bearer abc") == "abc"


def test_a_bearer_credential_containing_a_space_keeps_its_tail() -> None:
    """Mutant killed: `partition(" ")` to `rpartition(" ")`.

    `rpartition` splits at the LAST space, so `Bearer a b` yields a scheme of
    `Bearer a`, which fails the scheme check and returns None. The real one
    yields the credential `a b`, which then fails to match. Both refuse, and
    they refuse for different reasons: one says the header was malformed, the
    other says the token was wrong.
    """
    from hitchrail.security import _bearer

    assert _bearer("Bearer a b") == "a b"


def test_an_origin_with_a_separator_and_no_host_is_left_alone() -> None:
    """Mutant killed: `not separator or not rest` to `and`.

    `normalise_origin` deliberately returns anything it cannot parse UNCHANGED,
    so the caller's equality test simply fails to match. Repairing junk into a
    match is the failure it avoids, which is why the obvious assertion, that a
    bad origin comes back empty, is wrong: `normalise_origin("box.lan")` is
    `"box.lan"` by design.

    The input that separates the two is `https://`, which has a separator and
    no rest. Under `or` it returns early as `https:`, the value after the
    trailing slashes are stripped. Under `and` it falls through to the host
    split, `"".partition(":")` yields three empty strings, and it rebuilds
    `https://`. Two spellings of one unparseable value is exactly the drift
    that made the allowlist disagree with itself in Phase 2.
    """
    from hitchrail.hostnames import normalise_origin

    assert normalise_origin("https://") == "https:"
    assert normalise_origin("box.lan") == "box.lan", "junk is returned, never repaired"
    assert normalise_origin("https://box.lan") == "https://box.lan"
    assert normalise_origin("https://BOX.lan./") == "https://box.lan"


def test_a_root_path_that_does_not_prefix_the_path_is_ignored() -> None:
    """Mutant killed: `if not root_path or not path.startswith(root_path)` to
    `and`.

    `route_path` strips the mount prefix so the exempt path comparison is
    exact. With `and`, an empty `root_path` no longer short circuits, and the
    function goes on to slice by a prefix length of zero, which is harmless,
    while a NON prefixing root_path is now stripped anyway and the exempt set
    is compared against a mangled path. The exempt set is what decides which
    routes are reachable without a token.
    """
    from hitchrail.security import route_path

    assert route_path({"path": "/grant", "root_path": ""}) == "/grant"
    assert route_path({"path": "/grant", "root_path": "/elsewhere"}) == "/grant"
    assert route_path({"path": "/app/grant", "root_path": "/app"}) == "/grant"


def test_the_allowlist_drops_an_empty_entry_and_a_wildcard() -> None:
    """Mutant killed: `if h and h != "*"` to `if h or h != "*"`.

    With `or`, `"*"` is truthy so it is kept, and the middleware then holds a
    literal asterisk in its allowed set. `Config` refuses a wildcard entry, but
    this class takes a frozenset directly and its docstring says it honours no
    wildcards, which is a claim about THIS constructor.
    """
    from hitchrail.security import HostAllowlistMiddleware

    async def app(scope: object, receive: object, send: object) -> None:  # pragma: no cover
        raise AssertionError("not called")

    middleware = HostAllowlistMiddleware(app, frozenset({"box.lan", "*", ""}))
    assert middleware.allowed == frozenset({"box.lan"})


def test_a_circular_symlink_is_explained_by_its_errno(tmp_path: Path) -> None:
    """Mutant killed: `if exc.errno == errno.ELOOP` to `!=`.

    The reason string is what the interface shows for a folder it will not
    offer, and a circular link explained as a missing target sends somebody
    looking for a file that was never supposed to exist.

    **The first version of this test could not fail, and the way it could not
    is worth keeping.** It asserted `"loop" in reason`, and the reason for the
    mutated code embeds the link target, which is under `tmp_path`, which
    pytest names after the test function. The function was called
    `test_a_symlink_loop_is_explained_as_a_loop`, so the directory was
    `test_a_symlink_loop_is_explain0` and the substring matched the PATH. The
    mutation was applied, the wrong branch ran, and the assertion passed.

    Hence the equality below rather than a substring, and hence the rename: a
    test whose own name appears in the data it asserts on is a trap that will
    be walked into again.
    """
    a, b = tmp_path / "a", tmp_path / "b"
    a.symlink_to(b)
    b.symlink_to(a)
    assert discovery._broken_link_reason(a) == "is a symlink loop, so it has no target to open"
