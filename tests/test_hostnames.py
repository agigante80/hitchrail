"""What does `hostnames` call loopback, a wildcard, a valid host, and the one
canonical form of each? The vocabulary, asked without building a `Config`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from config_support import _r
from hitchrail.config import (
    Config,
    is_loopback_host,
    is_valid_host,
    is_wildcard_host,
    normalise_host,
)


@pytest.mark.parametrize(
    "host",
    [
        "127.0.0.1",
        "localhost",
        "::1",
        "127.0.0.5",
        # #283: what the bind makes of these is loopback, so the answer is too.
        "127.1",
        "0177.0.0.1",
    ],
)
def test_loopback_forms_are_recognised(tmp_path: Path, host: str) -> None:
    assert Config(roots=_r(tmp_path), host=host).is_loopback


@pytest.mark.parametrize("host", ["::ffff:127.0.0.1", "[::ffff:127.0.0.1]"])
def test_the_ipv4_mapped_loopback_is_loopback_as_a_host_but_not_a_bind(
    tmp_path: Path, host: str
) -> None:
    """#283 made the mapped spelling loopback, which holds for a Host header
    and an origin. It never binds (#395), so `Config` refuses it as `host`
    and the token rule meets it only as an allowlist entry."""
    assert is_loopback_host(host)
    assert Config(roots=_r(tmp_path), extra_hosts=(host,)).token is None


@pytest.mark.parametrize("host", ["0.0.0.0", "::"])
def test_wildcard_forms_are_recognised(host: str) -> None:
    assert is_wildcard_host(host)
    assert not is_loopback_host(host)


@pytest.mark.parametrize(
    "host",
    [
        "box.lan",
        "example.com",
        "not-an-ip",
        "localhos",
        # #283's short forms, each a spelling that must NOT come out loopback:
        # 0.0.0.127, octal 8.0.0.1, a mapped LAN address, hex refused outright,
        # and a number too large for `inet_aton`.
        "127",
        "010.1",
        "::ffff:10.0.0.1",
        "0x7f.1",
        "99999999999",
    ],
)
def test_a_hostname_that_is_not_an_ip_is_not_loopback(host: str) -> None:
    # The ValueError path in is_loopback_host. If this ever answered True, a
    # bind to a named host would skip the token requirement entirely, so it
    # gets an assertion rather than being left to the type checker.
    assert not is_loopback_host(host)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  BOX.LAN  ", "box.lan"),
        ("[::1]", "::1"),
        ("[2001:DB8::5]", "2001:db8::5"),
        ("127.0.0.1", "127.0.0.1"),
        ("", ""),
    ],
)
def test_normalise_host_produces_one_form(raw: str, expected: str) -> None:
    assert normalise_host(raw) == expected


@pytest.mark.parametrize(
    ("value", "valid"),
    [
        ("box.lan", True),
        ("a.b.c.example", True),
        ("[::1]", True),
        ("2001:db8::5", True),
        ("127.0.0.1", True),
        ("[...]", False),
        ("[::1:::2]", False),
        ("box.lan:8787", False),
        ("-lead.example", False),
        ("trail-.example", False),
        ("a" * 254, False),
        ("", False),
    ],
)
def test_is_valid_host_defers_to_ipaddress_for_literals(value: str, valid: bool) -> None:
    # A character class does not know what an IPv6 literal is: `[...]` and
    # `[::1:::2]` both satisfied the pattern this replaces.
    assert is_valid_host(value) is valid
