"""Which Origin headers does the allowlist accept, and is every configured
origin one that could ever match a browser's?

Hermetic: every test that exercises a wildcard bind injects a resolver, so no
test asks the operating system what this machine is called and none opens a
socket.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from config_support import _r
from hitchrail.config import (
    Config,
    ConfigError,
    normalise_host,
    normalise_origin,
    origin_forms,
)
from support import make_certificate


def test_allowed_origins_pin_the_port(tmp_path: Path) -> None:
    # Hostname alone is not enough: another app on localhost:3000 would
    # otherwise be same origin against an API equivalent to a shell.
    cfg = Config(roots=_r(tmp_path), port=8787)
    assert "http://localhost:8787" in cfg.allowed_origins
    assert "http://localhost:3000" not in cfg.allowed_origins


def test_a_proxy_origin_is_configured_rather_than_guessed(tmp_path: Path) -> None:
    """Named regression: `https://{host}` used to be derived for every host.

    That made any HTTPS service on port 443 of the same machine a same origin
    caller. The module's own argument for refusing `http://{host}` is that port
    80 is a port like any other, and it applies to 443 unchanged. A TLS
    terminating proxy is exactly the case that cannot be derived, because the
    scheme and the port are both the proxy's.
    """
    guessed = Config(roots=_r(tmp_path), host="192.168.1.10", token="t", port=8787)
    assert "https://192.168.1.10" not in guessed.allowed_origins
    assert "https://localhost" not in guessed.allowed_origins

    configured = Config(
        roots=_r(tmp_path),
        host="192.168.1.10",
        token="t",
        port=8787,
        extra_origins=("https://box.lan:8443",),
    )
    assert "https://box.lan:8443" in configured.allowed_origins


@pytest.mark.parametrize(
    "bad",
    [
        "box.lan",
        "https://x/path",
        "https://x?q=1",
        "https://x#f",
        "https://u@x",
        "https://*",
        "ftp://x",
    ],
    ids=["no-scheme", "path", "query", "fragment", "userinfo", "wildcard", "wrong-scheme"],
)
def test_a_configured_origin_that_is_not_an_origin_is_refused(tmp_path: Path, bad: str) -> None:
    with pytest.raises(ConfigError):
        Config(roots=_r(tmp_path), extra_origins=(bad,))


def test_the_bare_http_origin_is_not_accepted(tmp_path: Path) -> None:
    """Named regression: port 80 is a port like any other.

    An earlier version added `http://{host}` alongside the proxy form, which
    made any plain HTTP page on port 80 of the same host or LAN address a same
    origin caller against an API equivalent to a shell. That is precisely the
    hole the port pinning is written to close, reopened one line below the
    docstring claiming it was closed.
    """
    cfg = Config(roots=_r(tmp_path), host="192.168.1.10", token="t", port=8787)
    assert "http://192.168.1.10" not in cfg.allowed_origins
    assert "http://localhost" not in cfg.allowed_origins


def test_allowed_origins_bracket_an_ipv6_host(tmp_path: Path) -> None:
    # A bare ::1 in an origin is not a URL. Getting this wrong makes the check
    # reject a legitimate loopback browser rather than an attacker.
    cfg = Config(roots=_r(tmp_path), port=8787)
    assert "http://[::1]:8787" in cfg.allowed_origins
    assert "http://::1:8787" not in cfg.allowed_origins


def test_on_port_80_the_portless_origin_is_accepted(tmp_path: Path) -> None:
    """Named regression: the URL spec omits the default port from an origin.

    A browser on `http://box.lan/` sends `Origin: http://box.lan`, with no
    port, so an allowlist holding only `http://box.lan:80` matched nothing and
    every mutating request was refused while GETs kept working.
    """
    cfg = Config(roots=_r(tmp_path), host="box.lan", port=80, token="t")
    assert "http://box.lan" in cfg.allowed_origins
    assert "http://box.lan:80" in cfg.allowed_origins


def test_the_portless_form_appears_only_on_port_80(tmp_path: Path) -> None:
    # Not the unconditional guess that made any local HTTPS service a same
    # origin caller: emitted only when we are actually serving that port.
    cfg = Config(roots=_r(tmp_path), host="box.lan", port=8787, token="t")
    assert "http://box.lan" not in cfg.allowed_origins
    assert "http://box.lan:8787" in cfg.allowed_origins


@pytest.mark.parametrize(
    "bad",
    [
        "http://:pass@box.lan",
        "http://user:pass@box.lan",
        "http://box.lan:",
        "https://box.lan:99999",
        "https://box.lan:0",
        "https://box.lan:notaport",
    ],
    ids=[
        "password-only",
        "userinfo",
        "empty-port",
        "port-too-high",
        "port-zero",
        "port-not-numeric",
    ],
)
def test_an_origin_that_could_never_match_is_refused(tmp_path: Path, bad: str) -> None:
    """Named regression: silently ignoring operator config is the failure mode
    this module says it refuses to have.

    `http://:pass@box.lan` slipped through because urlsplit reports
    `username=''`, which is falsy, and the port was never read at all so an
    out of range or non numeric one was accepted too.
    """
    with pytest.raises(ConfigError):
        Config(roots=_r(tmp_path), extra_origins=(bad,))


@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        ("https://box.lan:443", {"https://box.lan", "https://box.lan:443"}),
        ("https://box.lan", {"https://box.lan", "https://box.lan:443"}),
        ("http://box.lan:80", {"http://box.lan", "http://box.lan:80"}),
        ("https://box.lan:8443", {"https://box.lan:8443"}),
    ],
    ids=["https-explicit-443", "https-implicit", "http-explicit-80", "non-default-port"],
)
def test_a_configured_origin_covers_both_default_port_spellings(
    tmp_path: Path, configured: str, expected: set[str]
) -> None:
    """Named regression: the default port rule reached derived origins only.

    `--allow-origin https://box.lan:443` was stored verbatim and never matched
    the `Origin: https://box.lan` a browser actually sends, because the URL
    spec elides the default port. The TLS proxy deployment is the entire reason
    `extra_origins` exists, so it failing there is the worst place for it.

    Both paths go through `origin_forms` now, so they cannot drift apart again.
    """
    cfg = Config(roots=_r(tmp_path), token="t", extra_origins=(configured,))
    assert expected <= cfg.allowed_origins


@pytest.mark.parametrize("origin", ["http://[2001:db8::]", "http://[::1]", "http://[fe80::]"])
def test_an_ipv6_origin_ending_in_a_double_colon_is_not_an_empty_port(
    tmp_path: Path, origin: str
) -> None:
    """Named regression: the empty port guard stripped a trailing bracket first.

    That made every IPv6 literal ending in `::` look like a trailing colon, so
    a valid origin was refused with a message about something the operator
    never wrote. The check belongs on the netloc, where `[2001:db8::]` ends
    with `]` and `box.lan:` ends with `:`.
    """
    # token="t" for the two non loopback literals: #108 demands one once an
    # origin names something outside this machine. `http://[::1]` would not
    # need it, and passing one changes nothing about what is asserted.
    cfg = Config(roots=_r(tmp_path), token="t", extra_origins=(origin,))
    assert any("2001:db8" in o or "::1" in o or "fe80" in o for o in cfg.allowed_origins)


def test_a_configured_origin_with_a_root_dot_normalises(tmp_path: Path) -> None:
    cfg = Config(
        roots=_r(tmp_path),
        host="0.0.0.0",
        token="t",
        extra_hosts=("box.lan",),
        extra_origins=("https://box.lan.:8443",),
        resolver=lambda: (),
    )
    assert "https://box.lan:8443" in cfg.allowed_origins
    assert "https://box.lan.:8443" not in cfg.allowed_origins


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("http://box.lan.:8787", "http://box.lan:8787"),
        ("http://box.lan.", "http://box.lan"),
        ("HTTPS://BOX.LAN./", "https://box.lan"),
        ("http://[::1]:8787", "http://[::1]:8787"),
        ("http://10.0.0.2.:80", "http://10.0.0.2:80"),
        # Not an origin: returned unchanged so the caller's equality fails and
        # the request is refused, rather than being repaired into a match.
        ("box.lan.", "box.lan."),
        ("", ""),
    ],
)
def test_normalise_origin_canonicalises_only_the_host(raw: str, expected: str) -> None:
    assert normalise_origin(raw) == expected


@pytest.mark.parametrize(
    "bad",
    ["http://[::1].", "http://[::1", "http://[", "http://[::1]]", "http://[::1].:8787"],
)
def test_a_malformed_bracketed_origin_is_a_config_error(tmp_path: Path, bad: str) -> None:
    """`urlsplit` validates bracketed netlocs itself and raises before we do.

    So these came out as a bare `ValueError: Invalid IPv6 URL` with no mention
    of which entry caused it. `http://[::1].` is the first thing somebody
    testing the new trailing dot behaviour on IPv6 would type, and a startup
    refusal has to name what it refused.
    """
    with pytest.raises(ConfigError, match="not an origin"):
        Config(roots=_r(tmp_path), extra_origins=(bad,))


@pytest.mark.parametrize("origin", ["http://-bad-.example", "http://a..b", "http://x-.y"])
def test_an_origin_whose_host_is_not_a_host_is_refused(tmp_path: Path, origin: str) -> None:
    """`urlsplit` is happy to hand back a hostname that is not one.

    A leading or trailing hyphen in a label and an empty label are both refused
    by HOSTNAME_PATTERN, and without this check the entry lands in the
    allowlist and can never match: the accepted-then-never-matches shape this
    module exists to refuse.
    """
    with pytest.raises(ConfigError, match="not a valid host in origin"):
        Config(roots=_r(tmp_path), extra_origins=(origin,))


# -- #233: the origin normaliser's parts, each of which was free to move ------


@pytest.mark.parametrize(
    ("raw", "expected", "why"),
    [
        # `partition`, not `rpartition`. Both find `://` in an ordinary origin,
        # so every existing test agreed with either. They differ when the value
        # carries a second `://`, where `rpartition` splits on the LAST one.
        # `partition`, not `rpartition`: with a second `://` in the value,
        # rpartition splits on the LAST and the root dot is then stripped
        # from a different string. The obvious case, `http://box.lan/x://y`,
        # does NOT distinguish them, which is why the first version of this
        # test left the mutant alive: a trailing dot is needed to show it.
        ("http://a://b.lan.", "http://a://b.lan.", "partition takes the FIRST separator"),
        # `rstrip("/")` mutated to `rstrip("XX/XX")` strips a trailing `X` too,
        # and it runs BEFORE `.lower()`, so the capital is what shows it.
        ("http://box.lanX/", "http://box.lanx", "only the slash is stripped, not a trailing X"),
        # The bracket guard, and the root-dot strip it protects.
        ("http://[::1]:8787", "http://[::1]:8787", "an IPv6 literal keeps its brackets"),
        ("http://box.lan.:8787", "http://box.lan:8787", "the root dot goes, the port stays"),
        # NOT the widened `rstrip` at `hostnames.py:109` (#235 L3): `value` is
        # lowercased before it, so `rstrip("XX.XX")` and `rstrip(".")` agree
        # here and that mutant is equivalent, recorded below. What this pins is
        # that the host is lowercased at all while the PORT is left alone.
        (
            "http://box.lanX:8787",
            "http://box.lanx:8787",
            "the host lowercases, the port survives",
        ),
    ],
)
def test_normalise_origin_keeps_each_of_its_parts(raw: str, expected: str, why: str) -> None:
    """#233. Six mutants lived in this function and every one survived.

    It is four decisions in five lines, and the tests exercised only origins
    where all four happen to agree: `rpartition` for `partition`, a widened
    `rstrip` set and a dropped bracket check all passed.

    **This is the origin check's own input.** A value normalised differently
    here does not fail loudly; it fails to match the allowlist and the request
    is refused. Repairing junk INTO a match is the failure worth avoiding.

    **One of the six is not a gap.** See the test below.
    """
    assert normalise_origin(raw) == expected, why


def test_the_or_in_normalise_origins_guard_is_equivalent_to_and() -> None:
    """#233. `if not separator or not rest:` mutated to `and` survives, and no
    test can kill it. Recorded rather than chased.

    `rstrip("/")` runs FIRST, so the value can never end in `://`, so
    "separator present and rest empty" is unreachable. And `str.partition` with
    no match returns `(value, "", "")`, so "no separator" always comes with an
    empty rest. The two operands are therefore never in disagreement, and `or`
    and `and` agree on every input.

    **Asserted rather than argued**, because "these are equivalent" is the claim
    that gets written into a triage log and is occasionally wrong. Exhaustive
    over an alphabet holding the separator, the slash, the dot and brackets.
    """
    from itertools import product

    def with_and(raw: str) -> str:
        value = raw.strip().rstrip("/").lower()
        scheme, separator, rest = value.partition("://")
        if not separator and not rest:
            return value
        if rest.startswith("["):
            return f"{scheme}://{rest}"
        host, colon, port = rest.partition(":")
        return f"{scheme}://{host.rstrip('.')}{colon}{port}"

    for length in range(1, 6):
        for parts in product(":/.abc[] ", repeat=length):
            raw = "".join(parts)
            assert normalise_origin(raw) == with_and(raw), (
                f"{raw!r} distinguishes `or` from `and`, so the mutant is a real "
                f"gap after all and this test is what found it"
            )


def test_the_widened_rstrip_sets_are_equivalent_because_lower_runs_first() -> None:
    """#233. Two survivors widen a `rstrip(".")` to `rstrip("XX.XX")`, in
    `normalise_host` and in `normalise_origin`. Neither can be killed.

    The widened set is `{X, .}`, so it differs from `{.}` only on a trailing
    UPPERCASE `X`. Both functions lowercase before they strip, so no uppercase
    survives to reach it.

    **I wrote a killing test for these first and it passed against the mutant**,
    asserting `normalise_host("linux") == "linux"`. `rstrip` is case sensitive
    and the lowercase `x` was never in the set, so the test agreed with the
    mutation. Verified exhaustively instead, over an alphabet holding both
    cases of `x`, the dot, the brackets and the separator.
    """
    from itertools import product

    def host_with_widened_strip(raw: str) -> str:
        value = raw.strip().lower()
        if value.startswith("[") and value.endswith("]"):
            value = value[1:-1]
        # B005 is exactly what the mutation looks like: ruff would refuse this
        # shape in production, which is a second reason the mutant is not a
        # gap in the tests.
        return value.rstrip("XX.XX")  # noqa: B005

    # **The SECOND site, which the first version of this test claimed and did
    # not model (#235 L3).** It said "in `normalise_host` and in
    # `normalise_origin`" and then exhaustively checked only the former, so half
    # its own claim rested on the argument rather than on the corpus.
    def origin_with_widened_strip(raw: str) -> str:
        value = raw.strip().rstrip("/").lower()
        scheme, separator, rest = value.partition("://")
        if not separator or not rest:
            return value
        if rest.startswith("["):
            return f"{scheme}://{rest}"
        host, colon, port = rest.partition(":")
        return f"{scheme}://{host.rstrip('XX.XX')}{colon}{port}"  # noqa: B005

    for length in range(1, 6):
        for parts in product(".xX[]:/ab ", repeat=length):
            raw = "".join(parts)
            assert normalise_host(raw) == host_with_widened_strip(raw), (
                f"{raw!r} distinguishes the two strip sets in normalise_host, so "
                f"that one is a real gap"
            )
            assert normalise_origin(raw) == origin_with_widened_strip(raw), (
                f"{raw!r} distinguishes them in normalise_origin, so that one is a real gap"
            )

    # And the ordinary behaviour, which is what the strip is FOR.
    assert normalise_host("box.lan.") == "box.lan"
    assert normalise_host("box.lan..") == "box.lan"
    assert normalise_origin("http://box.lan.:8787") == "http://box.lan:8787"


def test_origin_forms_brackets_only_a_bare_ipv6_literal() -> None:
    """`host.startswith("[")` mutated to `startswith("XX[XX")` survived: no host
    starts with the literal three characters `XX[`, so the guard never fires and
    an already bracketed literal is bracketed twice.
    """
    assert "http://[::1]:8787" in origin_forms("http", "::1", 8787)
    assert "http://[[::1]]:8787" not in origin_forms("http", "[::1]", 8787), (
        "an already bracketed literal was bracketed again"
    )


# -- #391: no plain http origin a Secure cookie cannot come back on ----------


def _proxied(tmp_path: Path, origins: tuple[str, ...], **kw: object) -> Config:
    kw.setdefault("host", "127.0.0.1")
    return Config(
        roots=_r(tmp_path),
        token="t",
        extra_hosts=("box.lan",),
        extra_origins=origins,
        **kw,  # type: ignore[arg-type]
    )


def test_a_secure_cookie_loopback_bind_derives_no_plain_origin_for_a_declared_host(
    tmp_path: Path,
) -> None:
    """#391, decided 2026-10-07. Every non loopback origin is https on a
    loopback bind, so the cookie is `Secure`, and a browser on
    `http://box.lan:8787` drops it: deriving that origin answered its grant
    200 and every request after it 401. Not derived, the grant is refused by
    the origin check instead, which names the origin. Loopback origins stay:
    `http://localhost` keeps a `Secure` cookie in Chrome and Firefox."""
    cfg = _proxied(tmp_path, ("https://box.lan",))
    assert cfg.cookie_is_secure, "the premise: this is the Secure cookie deployment"
    assert "http://box.lan:8787" not in cfg.allowed_origins
    assert "https://box.lan" in cfg.allowed_origins
    assert {"http://localhost:8787", "http://127.0.0.1:8787", "http://[::1]:8787"} <= (
        cfg.allowed_origins
    )
    assert cfg.plain_origins_withheld == ("box.lan",)


@pytest.mark.parametrize(
    ("overrides", "origins"),
    [
        ({}, ()),
        ({}, ("https://box.lan", "http://other.lan")),
        ({}, ("http://box.lan:8787",)),
        ({"host": "0.0.0.0", "resolver": lambda: ()}, ("https://box.lan",)),
    ],
    ids=["no-proxy-origin", "one-plain-origin", "plain-origin-given", "lan-bind"],
)
def test_the_plain_origin_is_still_derived_wherever_the_cookie_is_not_secure(
    tmp_path: Path, overrides: dict[str, object], origins: tuple[str, ...]
) -> None:
    """The narrowing is exactly the `Secure` cookie's reach. Without the
    flag, a browser on plain http keeps the cookie, so the derived origin
    works and removing it would only break a working deployment."""
    cfg = _proxied(tmp_path, origins, **overrides)
    assert not cfg.cookie_is_secure
    assert "http://box.lan:8787" in cfg.allowed_origins
    assert cfg.plain_origins_withheld == ()


def test_our_own_tls_still_derives_its_https_origin_for_a_declared_host(
    tmp_path: Path,
) -> None:
    """Under `--tls-cert` the derived origin is https, which a `Secure`
    cookie survives, so there is nothing to withhold."""
    cert, key = make_certificate(tmp_path)
    cfg = _proxied(tmp_path, ("https://box.lan",), tls_cert=cert, tls_key=key)
    assert "https://box.lan:8787" in cfg.allowed_origins
    assert cfg.plain_origins_withheld == ()
