"""What does `hostnames` call loopback, a wildcard, a valid host, and the one
canonical form of each? The vocabulary, asked without building a `Config`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from config_support import _r
from hitchrail import hostnames
from hitchrail.config import (
    Config,
    is_loopback_host,
    is_valid_host,
    is_wildcard_host,
    normalise_host,
    remote_reach,
)
from hitchrail.hostnames import is_secure_context_host
from support import make_certificate


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


@pytest.mark.parametrize(
    ("host", "secure"),
    [
        ("localhost", True),
        ("localhost.", True),
        ("LOCALHOST", True),
        ("app.localhost", True),
        ("app.localhost.", True),
        ("127.0.0.1", True),
        ("127.5.5.5", True),
        ("::1", True),
        ("[::1]", True),
        # Not on the Secure Contexts spec's list (algorithm 3.1, read
        # 2026-10-09): a browser does not treat it as a potentially
        # trustworthy origin, though it is loopback to this program.
        ("localhost.localdomain", False),
        ("localhost.localdomain.", False),
        ("notlocalhost", False),
        ("localhost.example.com", False),
        ("box.lan", False),
        ("192.168.1.5", False),
        ("::ffff:127.0.0.1", False),
    ],
)
def test_which_hosts_a_browser_treats_as_a_secure_context(host: str, secure: bool) -> None:
    """#436, from the W3C Secure Contexts spec's potentially trustworthy
    origin rule. A `Secure` cookie is only returned on such an origin."""
    assert is_secure_context_host(host) is secure


def test_localhost_localdomain_stays_loopback_for_every_other_rule(tmp_path: Path) -> None:
    """#436 narrowed one question and left `LOOPBACK_NAMES` alone: that set
    also decides who must present a token and which plain origins TLS
    refuses, and neither answer changes for this name."""
    assert is_loopback_host("localhost.localdomain")
    assert remote_reach("127.0.0.1", ("localhost.localdomain",), ()) is None
    assert Config(roots=_r(tmp_path), extra_hosts=("localhost.localdomain",)).token is None
    cert, key = make_certificate(tmp_path)
    Config(  # the TLS refusal of a plain off loopback origin does not apply
        roots=_r(tmp_path),
        tls_cert=cert,
        tls_key=key,
        extra_origins=("http://localhost.localdomain:8787",),
    )


@pytest.mark.parametrize(
    ("bind", "browse"),
    [
        ("127.0.0.1", "http://localhost:8787"),
        ("localhost", "http://localhost:8787"),
        ("[::1]", "http://localhost:8787"),
        ("127.0.0.2", "http://127.0.0.2:8787"),
        ("::2", "http://[::2]:8787"),
    ],
)
def test_the_address_advised_is_one_the_bind_serves(bind: str, browse: str) -> None:
    """#488. `localhost` resolves to 127.0.0.1, so it is named only for a bind
    that serves it, and an IPv6 literal is bracketed for a URL."""
    assert hostnames.browse_origin(hostnames.served_host(bind), 8787) == browse
