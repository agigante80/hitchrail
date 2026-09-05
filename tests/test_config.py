"""Configuration, and the two refusals that depend on it.

Hermetic: every test that exercises a wildcard bind injects a resolver, so no
test asks the operating system what this machine is called and none opens a
socket.
"""

from __future__ import annotations

import tomllib
from collections.abc import Callable
from pathlib import Path

import pytest

from hitchrail.config import (
    Config,
    ConfigError,
    is_loopback_host,
    is_valid_host,
    is_wildcard_host,
    local_addresses,
    normalise_host,
    normalise_origin,
)
from hitchrail.roots import Root


def _r(path: Path, label: str = "main") -> tuple[Root, ...]:
    """One root, labelled, as `Config` now takes them.

    Local to this file on purpose. Everything else goes through
    `support.make_config`; Config is the unit under test here, so the
    construction stays visible.
    """
    return (Root(label=label, path=path.resolve()),)


Resolver = Callable[[], tuple[str, ...]]


def fixed_resolver(*addresses: str) -> Resolver:
    """A stand in for asking the operating system what this machine is called."""
    return lambda: tuple(addresses)


def no_socket(*args: object, **kwargs: object) -> object:
    """Refuse to make a socket.

    Three tests here patched gethostname and getaddrinfo and then fell straight
    through to the UDP routing table probe, so they opened a real socket and
    the wildcard filter test asserted over whatever address this developer's
    machine happened to have. Hermetic means every surface, not the two that
    were obvious.
    """
    raise OSError("tests must not open a socket")


def test_loopback_bind_needs_no_token(tmp_path: Path) -> None:
    cfg = Config(roots=_r(tmp_path))
    assert cfg.is_loopback
    assert cfg.token is None


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1", "127.0.0.5"])
def test_loopback_forms_are_recognised(tmp_path: Path, host: str) -> None:
    assert Config(roots=_r(tmp_path), host=host).is_loopback


@pytest.mark.parametrize("host", ["0.0.0.0", "::"])
def test_wildcard_forms_are_recognised(host: str) -> None:
    assert is_wildcard_host(host)
    assert not is_loopback_host(host)


def test_network_bind_without_a_token_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="token"):
        Config(roots=_r(tmp_path), host="0.0.0.0", token=None)


def test_network_bind_with_a_token_is_allowed(tmp_path: Path) -> None:
    cfg = Config(roots=_r(tmp_path), host="0.0.0.0", token="s3cret")
    assert not cfg.is_loopback


def test_missing_root_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="root"):
        Config(roots=_r(tmp_path / "nope"))


def test_a_file_as_root_is_refused(tmp_path: Path) -> None:
    target = tmp_path / "notes.txt"
    target.write_text("x")
    with pytest.raises(ConfigError, match="root"):
        Config(roots=_r(target))


def test_allowed_hosts_covers_loopback_and_a_concrete_bind(tmp_path: Path) -> None:
    cfg = Config(roots=_r(tmp_path), host="192.168.1.10", token="t")
    assert "192.168.1.10" in cfg.allowed_hosts
    assert "localhost" in cfg.allowed_hosts


def test_a_wildcard_bind_allows_the_machines_own_address(tmp_path: Path) -> None:
    # The regression this task exists for. Without it the phone that the whole
    # design is aimed at gets a 400 from its own machine.
    cfg = Config(
        roots=_r(tmp_path),
        host="0.0.0.0",
        token="t",
        resolver=fixed_resolver("192.168.1.10", "box.lan"),
    )
    assert "192.168.1.10" in cfg.allowed_hosts
    assert "box.lan" in cfg.allowed_hosts


def test_a_wildcard_bind_never_allows_the_wildcard_itself(tmp_path: Path) -> None:
    cfg = Config(
        roots=_r(tmp_path),
        host="0.0.0.0",
        token="t",
        resolver=fixed_resolver("10.0.0.2", "0.0.0.0", "::", "*"),
    )
    hosts = cfg.allowed_hosts
    assert "10.0.0.2" in hosts
    assert "0.0.0.0" not in hosts
    assert "::" not in hosts
    assert "*" not in hosts


def test_a_concrete_bind_does_not_ask_the_resolver(tmp_path: Path) -> None:
    calls: list[int] = []

    def counting_resolver() -> tuple[str, ...]:
        calls.append(1)
        return ("10.0.0.2",)

    hosts = Config(
        roots=_r(tmp_path), host="127.0.0.1", resolver=counting_resolver
    ).allowed_hosts
    assert "127.0.0.1" in hosts
    assert calls == []


def test_a_resolver_that_fails_does_not_break_the_config(tmp_path: Path) -> None:
    # Degraded, not crashed, and narrower rather than wider. A reading we could
    # not take must never widen what the server answers to.
    def broken_resolver() -> tuple[str, ...]:
        raise OSError("no network")

    cfg = Config(roots=_r(tmp_path), host="0.0.0.0", token="t", resolver=broken_resolver)
    assert "localhost" in cfg.allowed_hosts


def test_extra_allowed_hosts_are_included(tmp_path: Path) -> None:
    cfg = Config(roots=_r(tmp_path), host="0.0.0.0", token="t", extra_hosts=("box.lan",))
    assert "box.lan" in cfg.allowed_hosts


@pytest.mark.parametrize("bad", ["*", "*.example", " * "])
def test_wildcard_allowed_host_is_refused(tmp_path: Path, bad: str) -> None:
    with pytest.raises(ConfigError, match="wildcard"):
        Config(roots=_r(tmp_path), host="0.0.0.0", token="t", extra_hosts=(bad,))


def test_allowed_hosts_are_deduplicated_and_ordered(tmp_path: Path) -> None:
    # A token because box.lan is not loopback, and #108 now demands one for
    # any declared remote reach. The subject here is ordering, not auth.
    cfg = Config(
        roots=_r(tmp_path), host="localhost", token="t", extra_hosts=("localhost", "box.lan")
    )
    hosts = cfg.allowed_hosts
    assert len(hosts) == len(set(hosts))
    assert hosts[0] == "localhost"


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


def test_a_padded_extra_host_is_usable(tmp_path: Path) -> None:
    # A stray space from a comma split was accepted and then could never match
    # a Host header, which reads as the allowlist ignoring the operator.
    cfg = Config(roots=_r(tmp_path), host="0.0.0.0", token="t", extra_hosts=(" phone.lan ",))
    assert "phone.lan" in cfg.allowed_hosts
    assert " phone.lan " not in cfg.allowed_hosts


def test_local_addresses_survives_a_machine_that_cannot_make_a_socket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Named regression: the socket was built before the suppress was entered.

    `with socket.socket(...) as p, contextlib.suppress(OSError):` evaluates the
    constructor before suppress is active, so a machine that cannot make a UDP
    socket raised out of a function documented as best effort, and the caller's
    own suppress then discarded the hostnames already collected.
    """

    def no_sockets(*args: object, **kwargs: object) -> object:
        raise OSError("EMFILE")

    monkeypatch.setattr("hitchrail.hostnames.socket.gethostname", lambda: "box")
    monkeypatch.setattr("hitchrail.hostnames.socket.getaddrinfo", lambda *a, **k: [])
    monkeypatch.setattr("hitchrail.hostnames.socket.socket", no_sockets)
    assert local_addresses() == ("box",)


def test_allowed_origins_bracket_an_ipv6_host(tmp_path: Path) -> None:
    # A bare ::1 in an origin is not a URL. Getting this wrong makes the check
    # reject a legitimate loopback browser rather than an attacker.
    cfg = Config(roots=_r(tmp_path), port=8787)
    assert "http://[::1]:8787" in cfg.allowed_origins
    assert "http://::1:8787" not in cfg.allowed_origins


def test_the_config_is_frozen(tmp_path: Path) -> None:
    # Validation happens once, in __post_init__. A mutable Config could be
    # edited past its own refusals after construction.
    cfg = Config(roots=_r(tmp_path))
    with pytest.raises(AttributeError):
        cfg.token = "sneaked in"  # type: ignore[misc]


@pytest.mark.parametrize("host", ["box.lan", "example.com", "not-an-ip", "localhos"])
def test_a_hostname_that_is_not_an_ip_is_not_loopback(host: str) -> None:
    # The ValueError path in is_loopback_host. If this ever answered True, a
    # bind to a named host would skip the token requirement entirely, so it
    # gets an assertion rather than being left to the type checker.
    assert not is_loopback_host(host)


def test_a_named_bind_still_demands_a_token(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="token"):
        Config(roots=_r(tmp_path), host="box.lan")


def test_local_addresses_survives_a_machine_with_no_hostname(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse(*args: object, **kwargs: object) -> object:
        raise AssertionError("getaddrinfo must not be asked without a hostname")

    monkeypatch.setattr("hitchrail.hostnames.socket.gethostname", lambda: "")
    monkeypatch.setattr("hitchrail.hostnames.socket.getaddrinfo", refuse)
    monkeypatch.setattr("hitchrail.hostnames.socket.socket", no_socket)
    assert local_addresses() == ()


def test_local_addresses_survives_a_failing_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A machine with no DNS is a machine Hitchrail still has to run on.
    def boom(*args: object, **kwargs: object) -> object:
        raise OSError("no resolver")

    monkeypatch.setattr("hitchrail.hostnames.socket.gethostname", lambda: "box")
    monkeypatch.setattr("hitchrail.hostnames.socket.getaddrinfo", boom)
    monkeypatch.setattr("hitchrail.hostnames.socket.socket", no_socket)
    assert local_addresses() == ("box",)


def test_local_addresses_never_returns_a_wildcard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The one output that would turn the allowlist into no allowlist at all.
    monkeypatch.setattr("hitchrail.hostnames.socket.gethostname", lambda: "0.0.0.0")
    monkeypatch.setattr(
        "hitchrail.hostnames.socket.getaddrinfo",
        lambda *a, **k: [(0, 0, 0, "", ("::", 0))],
    )
    monkeypatch.setattr("hitchrail.hostnames.socket.socket", no_socket)
    assert local_addresses() == ()


@pytest.mark.parametrize(
    "bad",
    ["box.lan:8787", "http://box.lan", "box.lan/path", "user@box.lan", "box.lan?x=1"],
    ids=["port", "scheme", "path", "userinfo", "query"],
)
def test_an_extra_host_that_is_not_a_bare_hostname_is_refused(tmp_path: Path, bad: str) -> None:
    """Named regression: a configured host that can never match is worse than a refusal.

    `box.lan:8787` was accepted, landed in allowed_hosts verbatim, and never
    matched a Host header because the middleware compares with the port already
    stripped. It also misfired the IPv6 bracketing and produced an allowed
    origin of `http://[box.lan:8787]:8787`.
    """
    with pytest.raises(ConfigError, match="bare hostname"):
        Config(roots=_r(tmp_path), host="0.0.0.0", token="t", extra_hosts=(bad,))


def test_a_bracketed_ipv6_extra_host_is_stored_bare(tmp_path: Path) -> None:
    """One canonical form. Brackets belong to the URL, not to the host.

    A Host header brackets an IPv6 literal and a config file usually does not,
    so the matcher normalises the header and both meet on the bare form.
    Storing both spellings was a workaround for a matcher that could not strip
    brackets, and two spellings of one host can disagree with each other.
    """
    cfg = Config(roots=_r(tmp_path), host="0.0.0.0", token="t", extra_hosts=("[fe80::1]",))
    assert "fe80::1" in cfg.allowed_hosts
    assert "[fe80::1]" not in cfg.allowed_hosts
    # Bracketed again on the way into an origin, because that is what a browser
    # puts in the Origin header.
    assert f"http://[fe80::1]:{cfg.port}" in cfg.allowed_origins


@pytest.mark.parametrize("prefix", ["", "   ", " hr-", "hr- ", "hr.", "hr:", "h r-"])
def test_a_prefix_that_would_make_the_kill_guard_vacuous_is_refused(
    tmp_path: Path, prefix: str
) -> None:
    """Named regression: "never kill a session without the prefix" needs a prefix.

    Every tmux session name satisfies startswith(""), so an empty prefix turns
    the guard that protects the developer's own sessions into a no-op. Dots and
    colons are refused for the separate reason that tmux reads them as window
    and pane separators.
    """
    with pytest.raises(ConfigError, match="session prefix"):
        Config(roots=_r(tmp_path), session_prefix=prefix)


@pytest.mark.parametrize("binary", ["", "  ", "-rf", "--dangerously-skip-permissions"])
def test_a_flag_shaped_agent_binary_is_refused(tmp_path: Path, binary: str) -> None:
    # argv[0] starting with a hyphen is read as an option by whatever parses it,
    # and no shell being involved does not help.
    with pytest.raises(ConfigError, match="agent binary"):
        Config(roots=_r(tmp_path), agent_binary=binary)


@pytest.mark.parametrize("port", [0, -1, 65536, 99999])
def test_a_port_out_of_range_is_refused(tmp_path: Path, port: int) -> None:
    with pytest.raises(ConfigError, match="port"):
        Config(roots=_r(tmp_path), port=port)


def test_a_non_positive_stop_timeout_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="stop timeout"):
        Config(roots=_r(tmp_path), stop_timeout=0)


def test_an_inverted_pair_of_memory_floors_is_refused(tmp_path: Path) -> None:
    # The soft floor is the "ask first" threshold and the hard floor is the
    # refusal. Inverted, the confirmation gate can never fire and the guard
    # loses a step without saying so.
    with pytest.raises(ConfigError, match="soft floor"):
        Config(roots=_r(tmp_path), hard_floor_mb=3072, soft_floor_mb=1536)


@pytest.mark.parametrize("host", ["[::1]", " ::1 ", "[::1] "])
def test_a_bracketed_loopback_bind_is_recognised(tmp_path: Path, host: str) -> None:
    """Named regression: [::1] is the form people copy out of a URL.

    Reading it as a network bind meant refusing to serve loopback without a
    token, with a message about anyone on the network running code as you.
    """
    cfg = Config(roots=_r(tmp_path), host=host)
    assert cfg.is_loopback
    assert cfg.token is None


def test_the_allowlist_is_resolved_once_not_on_every_read(tmp_path: Path) -> None:
    """Named regression: the middleware reads this per request.

    As a plain property it ran gethostname, getaddrinfo and a UDP connect on
    every access, on the event loop, and two reads inside one request could
    disagree with each other.
    """
    calls: list[int] = []

    def counting() -> tuple[str, ...]:
        calls.append(1)
        return ("10.0.0.2",)

    cfg = Config(roots=_r(tmp_path), host="0.0.0.0", token="t", resolver=counting)
    for _ in range(5):
        _ = cfg.allowed_hosts
        _ = cfg.allowed_origins
    assert calls == [1]


def test_a_failing_gethostname_does_not_discard_the_probe_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Named regression: gethostname sat outside any suppress.

    A container with an unreadable UTS name aborted local_addresses before the
    routing table probe, so a wildcard bind never learned its LAN address and
    degraded to loopback only.
    """

    class FakeSocket:
        def __enter__(self) -> FakeSocket:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def connect(self, address: tuple[str, int]) -> None:
            return None

        def getsockname(self) -> tuple[str, int]:
            return ("192.168.5.5", 0)

    def boom(*args: object, **kwargs: object) -> object:
        raise OSError("no UTS name")

    monkeypatch.setattr("hitchrail.hostnames.socket.gethostname", boom)
    monkeypatch.setattr("hitchrail.hostnames.socket.socket", lambda *a, **k: FakeSocket())
    assert local_addresses() == ("192.168.5.5",)


@pytest.mark.parametrize(
    "spelling", ["0.0.0.0", "::", "::0", "0:0:0:0:0:0:0:0", "[::]", " :: "]
)
def test_every_spelling_of_the_unspecified_address_is_a_wildcard(
    tmp_path: Path, spelling: str
) -> None:
    """Named regression: a three element set called `::0` a concrete bind.

    The resolver was then never consulted, so a wildcard bind written that way
    was reachable on loopback only, which is the regression the resolver exists
    to prevent. `ipaddress` already knows what an unspecified address is.
    """
    assert is_wildcard_host(spelling)
    cfg = Config(
        roots=_r(tmp_path), host=spelling, token="t", resolver=fixed_resolver("10.0.0.2")
    )
    assert "10.0.0.2" in cfg.allowed_hosts
    assert spelling.strip() not in cfg.allowed_hosts


@pytest.mark.parametrize(
    "bad",
    [
        "box.lan:8787",
        "http://box.lan",
        "box.lan/path",
        "user@box.lan",
        "[...]",
        "[::1:::2]",
        "a b",
    ],
)
def test_the_bind_host_is_validated_like_everything_else(tmp_path: Path, bad: str) -> None:
    """Named regression: the bind address skipped the validation extra_hosts got.

    `--host box.lan:8787` was accepted, landed in the allowlist where it could
    never match, and its colon misfired the IPv6 bracketing into an allowed
    origin of `http://[box.lan:8787]:8787`.
    """
    with pytest.raises(ConfigError, match="bare host"):
        Config(roots=_r(tmp_path), host=bad, token="t")


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


def test_a_resolver_returning_junk_cannot_widen_the_allowlist(tmp_path: Path) -> None:
    # The resolver is an external surface. Its output is filtered on the way
    # out, not trusted because it came from the operating system.
    cfg = Config(
        roots=_r(tmp_path),
        host="0.0.0.0",
        token="t",
        resolver=fixed_resolver(
            "10.0.0.2", "0.0.0.0", "::", "*", "not a host", "", "box.lan:1"
        ),
    )
    assert cfg.allowed_hosts == ("localhost", "127.0.0.1", "::1", "10.0.0.2")


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


def test_a_resolver_raising_unicodeerror_does_not_break_startup(tmp_path: Path) -> None:
    """Named regression: getaddrinfo raises UnicodeError, not OSError.

        socket.getaddrinfo("a" * 70 + ".example", None)
        UnicodeError: label empty or too long

    UnicodeError is a ValueError, so `suppress(OSError)` did not catch it and
    Config() died with a raw UnicodeError on any machine, a container or a pod,
    whose hostname has a label over 63 characters or one that will not encode
    to IDNA.
    """

    def bad_label() -> tuple[str, ...]:
        raise UnicodeError("label empty or too long")

    cfg = Config(roots=_r(tmp_path), host="0.0.0.0", token="t", resolver=bad_label)
    assert "localhost" in cfg.allowed_hosts


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


@pytest.mark.parametrize("bad", ["", "   ", "\t"])
def test_an_empty_token_is_refused(tmp_path: Path, bad: str) -> None:
    """Named regression: `""` is not None, so it switched authentication ON
    with a secret that an empty cookie matches.

    `compare_digest(b"", b"")` is True, so `Cookie: hitchrail_token=` was
    served. An operator reaches this with `--token "$UNSET_VARIABLE"` and
    believes they configured authentication.
    """
    with pytest.raises(ConfigError, match="empty token"):
        Config(roots=_r(tmp_path), token=bad)


def test_no_token_at_all_is_still_allowed_on_loopback(tmp_path: Path) -> None:
    # None means "no authentication", which is a legitimate loopback choice.
    # Only the empty string, which looks like a token and is not, is refused.
    assert Config(roots=_r(tmp_path), token=None).token is None


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


@pytest.mark.parametrize("hostname", ["dev_box", "my_host.local", "a_b_c"])
def test_an_underscore_in_a_hostname_is_accepted(tmp_path: Path, hostname: str) -> None:
    """Named regression: tightening to RFC 1123 locked real machines out.

    DNS does not permit an underscore in a hostname, and containers and
    machines are named `dev_box` regardless, and `gethostname()` reports it. The
    stricter pattern silently filtered such a host out of its own allowlist, so
    `http://dev_box:8787/` answered 400, and `--allow-host dev_box` was a
    startup refusal with no way around it.
    """
    cfg = Config(roots=_r(tmp_path), host="0.0.0.0", token="t", extra_hosts=(hostname,))
    assert hostname in cfg.allowed_hosts


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


def test_a_wildcard_is_not_an_address_to_bind_to(tmp_path: Path) -> None:
    """Named regression: `*` is an allowlist spelling, not a bindable address.

    `is_wildcard_host` counts it as a wildcard, so `_check_bind_host` returned
    early and `Config(host="*")` constructed. The CLI hands this straight to
    uvicorn, where it dies at bind time with a message about getaddrinfo rather
    than a ConfigError saying what to write instead.
    """
    with pytest.raises(ConfigError, match="not an address to bind to"):
        Config(roots=_r(tmp_path), host="*", token="t")
    # The real wildcards still work, which is what makes this a narrow fix.
    for bindable in ("0.0.0.0", "::"):
        assert Config(roots=_r(tmp_path), host=bindable, token="t").allowed_hosts


@pytest.mark.parametrize(
    ("given", "stored"),
    [("[::1]", "::1"), (" 127.0.0.1 ", "127.0.0.1"), ("[::]", "::"), (" BOX.lan ", "box.lan")],
)
def test_the_bind_address_is_stored_in_the_form_uvicorn_can_bind(
    tmp_path: Path, given: str, stored: str
) -> None:
    """Named regression: validated normalised, then handed over raw.

    `is_valid_host` strips brackets and whitespace before matching, so all of
    these passed validation, and `Config.host` kept the spelling as typed.
    The CLI hands that field straight to uvicorn.run(host=...) once phase 5
    builds it, where
    socket.bind raises gaierror on `[::1]`. Accepted at startup and dead at
    bind time is the worst of both.
    """
    cfg = Config(roots=_r(tmp_path), host=given, token="tok", extra_hosts=("box.lan",))
    assert cfg.host == stored


# -- #19: the FQDN root dot, on every door ---------------------------------


@pytest.mark.parametrize("door", ["bind", "extra_hosts", "resolver"])
def test_a_root_dot_is_stripped_from_every_door(tmp_path: Path, door: str) -> None:
    """`box.lan.` and `box.lan` name the same machine, so one form is stored.

    Every door into the allowlist goes through `normalise_host`, and this
    asserts all three rather than the one that happened to be fixed.
    """
    kwargs: dict[str, object] = {"roots": _r(tmp_path), "token": "t"}
    if door == "bind":
        kwargs["host"] = "box.lan."
        kwargs["resolver"] = lambda: ()
    elif door == "extra_hosts":
        kwargs["host"] = "0.0.0.0"
        kwargs["extra_hosts"] = ("box.lan.",)
        kwargs["resolver"] = lambda: ()
    else:
        kwargs["host"] = "0.0.0.0"
        kwargs["resolver"] = lambda: ("box.lan.",)
    cfg = Config(**kwargs)  # type: ignore[arg-type]
    assert "box.lan" in cfg.allowed_hosts
    assert "box.lan." not in cfg.allowed_hosts


@pytest.mark.parametrize("bad", [".", "..", "...", "box..lan", "box.lan:8787"])
def test_a_host_with_no_valid_reading_is_a_startup_refusal(tmp_path: Path, bad: str) -> None:
    """Dots that leave nothing behind, or that are not root dots at all.

    `.` and `..` normalise to the empty string and `box..lan` has an empty
    label in the middle, which is a different thing from a trailing root dot
    and stays refused.
    """
    with pytest.raises(ConfigError):
        Config(
            roots=_r(tmp_path),
            host="0.0.0.0",
            token="t",
            extra_hosts=(bad,),
            resolver=lambda: (),
        )


@pytest.mark.parametrize("given", ["box.lan.", "box.lan..", "box.lan..."])
def test_a_repeated_root_dot_normalises_rather_than_lingering(
    tmp_path: Path, given: str
) -> None:
    """Named regression for the reverted first attempt at #19.

    That attempt stripped ONE dot. Because `is_valid_host` normalises before
    matching, `box.lan..` became `box.lan.`, passed the pattern, and landed in
    the allowlist in a spelling nothing could ever match. That is the defect,
    and this asserts the property rather than a policy: whatever goes in, what
    comes out is a spelling a browser can actually send.

    An earlier draft of #19 specified refusing `box.lan..` instead. That was
    over specified before the code existed. A doubled root dot has exactly one
    possible reading, unlike `box.lan:8787` where the port is meaningful and
    wrong, so normalising loses nothing and widens nothing.
    """
    cfg = Config(
        roots=_r(tmp_path), host="0.0.0.0", token="t", extra_hosts=(given,), resolver=lambda: ()
    )
    assert "box.lan" in cfg.allowed_hosts
    assert not any(h.endswith(".") for h in cfg.allowed_hosts)


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


# -- #18: the seam holds ---------------------------------------------------


def test_hostnames_does_not_import_config() -> None:
    """The dependency runs one way, which is what makes this a seam.

    `config` imports `hostnames`. If `hostnames` ever imports `config` back,
    the split stops being a seam and becomes a cut through a cycle, and the
    next person to tidy up will reasonably merge them again.
    """
    source = (Path(__file__).parent.parent / "src" / "hitchrail" / "hostnames.py").read_text()
    assert "import config" not in source
    assert "from hitchrail.config" not in source
    assert "from .config" not in source


def test_every_module_is_under_the_size_guideline() -> None:
    """The reason #18 existed. Asserted so it does not silently regress.

    `.claude/CLAUDE.md` says a file past roughly 400 lines is doing more than
    one thing. config.py reached 502 before its split.

    Every module, not the two that #18 touched. Naming those two let
    discovery.py drift past 400 unnoticed while this test passed, which is the
    same shape of gap as testing three hand picked pairs for injectivity.
    """
    # One known exception, tracked as #33, recorded rather than excused by
    # loosening the threshold for everybody.
    #
    # A CAP, not an exact size. An earlier version pinned 403 exactly and so
    # went red when discovery.py got SMALLER, reporting "past the guideline"
    # about a file that had just moved towards it. Failing on the improvement
    # you asked for is how a number gets bumped instead of fixed.
    # Empty, and that is the point: #33 landed, discovery.py came under the
    # guideline, and this test failed until the entry was removed. The
    # mechanism retires its own exceptions.
    # Tracked, not excused. #50 splits derivation out of engine.py; the
    # vocabulary already moved to sessions.py, which took it from 555 to 466.
    # engine.py holds the lifecycle and nothing else since #50 took the
    # derivation out into `derive.py`, which is the one real seam in it.
    #
    # An earlier version of this note said to cut the graceful stop overlay
    # next rather than raise the number again. Measured rather than guessed,
    # that cut moves 64 lines and leaves the file at 412: still over the
    # guideline, and now with one stop sequence split across two files to buy
    # nothing. The note was wrong, so it is corrected here rather than
    # followed. What is left is a lifecycle with unusually dense comments,
    # because most of it is footguns that cost real debugging to find, and
    # those comments are the reason the file is long. Deleting them to satisfy
    # a line count would be the worst available trade.
    #
    # Raise this only for a change that adds behaviour, and say what in the
    # commit. If it passes roughly 550, look for a seam again with fresh eyes.
    caps = {
        # 476, and this one does NOT want splitting, which is why it is here
        # rather than in a ticket like #93. The whole value of `claude_ipc` is
        # that it is ONE module: when Claude Code moves, exactly one file
        # changes and the interface degrades rather than reporting something
        # false. Two quarantine modules is two places to look and two places to
        # forget, and the seam anyone would cut on, "talking to a running
        # agent" against "finding its session link", puts undocumented vendor
        # knowledge on both sides of it.
        #
        # The growth is #89: the stop sequence now reads the input box and
        # verifies it between steps, and most of the added length is the three
        # captured rows and why each is what it is. Those captures are the
        # reason the check is right, and a description of them is what was
        # wrong twice.
        #
        # The growth from 419 is review reversing decisions inside
        # `_require_clear` and leaving each reason behind: why the read settles
        # before the FIRST look rather than only between retries, why an
        # unrecognised pane refuses where it used to proceed, and why the
        # escape stripper went back to the narrower pattern after the wider one
        # introduced a worse defect than it fixed. Those are the comments a
        # further round would otherwise re-litigate.
        # 563 to 571 for #91: the relay framing, written at the one call site
        # that types into a pane. Documentation rather than behaviour, and the
        # note above allows the exception to be argued rather than assumed.
        # This is the module whose whole value is being the one place that
        # knows how an agent is talked to, so what that costs the operator
        # belongs in it.
        # 571 to 581 for #95. The settle seam lost its default and gained the
        # split that keeps two rules at once: the DURATION is quarantine
        # knowledge about how a Claude Code pane settles, the WAITING is the
        # machine seam the architecture injects. Both reasons are at the code.
        # 583 to 649 for #97. The regex became a parser, and the growth is
        # mostly the reason: two regexes failed in OPPOSITE directions, one
        # refusing every stop and one eating a draft character, and a third
        # regex would have been the same bet a third time.
        "claude_ipc.py": 649,
        # +_await_gone, +list(...), +#47 split, +#64, +#66, and +#89's one
        # `except` arm: the adapter can now decline to type, and the marker has
        # to come back the same way a vanished tmux takes it back.
        # 785 to 792 for #120. The name guard splits a qualified identifier
        # before validating its folder half, and the comment says why: `~` is
        # exactly the character the folder allowlist forbids, so validating the
        # whole identifier read the separator as the thing it protects against
        # and rejected every real name. That was a live defect, so its reason
        # stays in the code.
        # 792 to 826 for #102. The addition is a cleanup path plus the reason
        # it asks rather than guesses, which is the distinction the ticket drew
        # and the one a future reader would otherwise re-litigate: assuming the
        # session exists kills something that may not, assuming it does not
        # leaves the defect.
        "engine.py": 826,
        # tmux.py is the module that encodes what tmux actually does
        # rather than what its manual implies, and every entry is a footgun
        # that cost real debugging: prefix matching targets, the colon
        # `list-panes` and `set-option` both need, a rewritten dot, a pane that
        # vanishes before it can be read, and now a server that keeps the argv
        # of whatever started it (#84). The length is those explanations.
        # Deleting them to reclaim lines would delete the reason the
        # workarounds look wrong, which is the one thing a reader needs.
        #
        # Raised from 425 for #84's `is_tmux_argv`, again for #89's `-e`
        # capture option, and again for #67's call bound and the note about
        # what a timeout leaves behind. All added behaviour rather than growth,
        # which the note above permits with a reason.
        #
        # The number is not repeated in this comment any more. It was written
        # as "466." while the cap said 485, which is the same decay the
        # security.py note below warns about and this file's own test forbids
        # in the documents.
        # **There IS a seam here now**, and it is #93 rather than a bump next
        # time: `sanitize`, `_needs_encoding` and their two constants are the
        # name vocabulary, pure and subprocess free, sitting beside an adapter
        # that spawns things. That is the same split #18 already made when it
        # took the host vocabulary out of config.py into hostnames.py.
        # **#93 landed and this entry loses its argument with it.** Every note
        # here defended a length caused by a module doing two jobs: the name
        # vocabulary and the adapter that spawns processes. The vocabulary is
        # `tmuxnames.py` now, and 522 became 438 without a line of explanation
        # being deleted, which is the outcome the old notes kept insisting was
        # not available. Recorded rather than silently reset, because the
        # previous entries argued in good faith from a premise that a split
        # removed.
        "tmux.py": 439,
        # 413, and thirteen lines over the guideline is not a second job. #18
        # already took the host vocabulary out of this file, and what is left
        # is one dataclass and its startup refusals, which is one thing. The
        # growth is #48's `_check_self_project`, whose comment is longer than
        # its code on purpose: a filesystem read in a config constructor looks
        # wrong, and the reason it is not belongs next to it. Split only if a
        # NEW responsibility arrives, never to reclaim these lines.
        #
        # Raised from 418 for #108's `remote_reach`, which adds behaviour: the
        # token refusal now follows what can reach this server rather than what
        # it binds. Most of the addition is the argument for why a proxied
        # loopback bind is not local, which is the thing that was wrong.
        # 468 to 488 for #120. `roots` replaces `root`, and the growth is the
        # qualified `--self-project` check: it now splits an identifier, finds
        # the root that label names, and refuses if there is none. Three
        # refusals where there was one, because with several roots there are
        # three ways to name a folder that is not there.
        "config.py": 488,
        # 409, nine lines over, down from 542. #115 deleted the `?token=`
        # carrier: 135 lines once the two blocks inside `TokenMiddleware`
        # that only served it are counted.
        #
        # Nine over is not a second job, the same judgement config.py's entry
        # makes at thirteen. What is gone is the long exception this entry used
        # to carry, arguing that a boundary should not be split.
        #
        # **#80 could not have reached even this**, which is why it was closed
        # rather than done: the unit it proposed moving was 101 lines against a
        # 542 line file, landing near 435 with the exception intact. The query
        # grant was never what made this file long.
        #
        # If it grows again the seam is `TokenMiddleware`, still the largest
        # thing here. Look there before raising this number.
        # 359 to 440 for #120, and this one is on notice. The plural layer,
        # "which root does this identifier name", sits on top of the per root
        # functions rather than inside them, which is what keeps `resolve_child`
        # unchanged: proving a path is a direct child of ONE root is the
        # property the security argument rests on and it is not improved by
        # teaching it about labels. The seam is therefore real and the file is
        # two layers deep rather than two jobs wide, so it is tracked here
        # instead of split mid migration. #127 carries the split.
        "discovery.py": 440,
        "security.py": 409,
        # rather than one. A refusal handler is the shape this file is made of.
        # 513 to 517 for #120. The listing payload reports every configured
        # root as a labelled list rather than one path string, and the comment
        # says why one root is still a list.
        "server.py": 517,
    }

    src = Path(__file__).parent.parent / "src" / "hitchrail"
    sizes = {p.name: len(p.read_text().splitlines()) for p in sorted(src.glob("*.py"))}

    over = {n: c for n, c in sizes.items() if c >= 400 and c > caps.get(n, 399)}
    assert not over, (
        f"past the guideline: {over}. Split it, or track it in `caps` with a ticket."
    )

    # And the exception cannot outlive its reason: once #33 brings discovery.py
    # under the guideline, this fails and the entry must go.
    settled = {n for n in caps if sizes.get(n, 0) < 400}
    assert not settled, f"no longer oversize, remove from `caps`: {sorted(settled)}"


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


# -- #36: refusals nobody exercised ----------------------------------------


@pytest.mark.parametrize("field", ["hard_floor_mb", "soft_floor_mb", "session_mb"])
def test_a_negative_memory_figure_is_refused(tmp_path: Path, field: str) -> None:
    """Every field, not the one that happened to be tested.

    A negative floor makes the guard's arithmetic meaningless: `remaining <
    hard_mb` is true for any remaining when the floor is below zero, so the
    guard either refuses everything or approves everything depending on which
    figure went negative.
    """
    with pytest.raises(ConfigError, match=f"{field} must not be negative"):
        Config(roots=_r(tmp_path), **{field: -1})  # type: ignore[arg-type]


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


def test_the_import_contract_covers_every_engine_layer_module() -> None:
    """A new module is unguarded until somebody remembers to list it.

    `lint-imports` checks the modules it is given and says nothing about the
    ones it is not, so it passes just as loudly with a gap in it. Splitting
    `derive` out of `engine` at #50 opened exactly that gap: the new module
    could have imported Starlette and the contract would still have reported
    "1 kept, 0 broken".

    The web layer is the exception list below, and it is spelled out rather
    than inferred, so adding a module to it is a deliberate act.
    """
    web = {"server.py", "pages.py", "cli.py", "security.py", "headers.py", "__init__.py"}
    src = Path(__file__).resolve().parents[1] / "src" / "hitchrail"
    engine_layer = {f"hitchrail.{p.stem}" for p in src.glob("*.py") if p.name not in web}
    contract = tomllib.loads(
        (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text()
    )["tool"]["importlinter"]["contracts"][0]
    missing = engine_layer - set(contract["source_modules"])
    assert not missing, (
        f"engine layer modules outside the import contract: {sorted(missing)}. "
        "Add them to `source_modules` in pyproject.toml, or to `web` here if "
        "they are genuinely part of the web layer."
    )


# -- #48: a protection that cannot match is not a protection ----------------


@pytest.mark.parametrize(
    "value",
    ["./hitchrail", "hitchrail/", "../hitchrail", ".hidden", "-flag", "", "a b", "a" * 300],
)
def test_a_self_project_that_could_never_be_a_project_is_refused(
    tmp_path: Path, value: str
) -> None:
    """Shape. Each of these is accepted by string equality and matches nothing."""
    with pytest.raises(ConfigError) as exc:
        Config(roots=_r(tmp_path), self_project=value)
    assert "--self-project" in str(exc.value)


@pytest.mark.parametrize("value", ["main~Hitchrail", "main~hitchrai", "main~hitchrail2"])
def test_a_well_shaped_self_project_that_is_not_there_is_refused(
    tmp_path: Path, value: str
) -> None:
    """The half a shape check cannot reach, and the likelier mistake.

    A capital letter and a typo are what a person actually gets wrong, and both
    pass every pattern. Without the existence check this ticket would have
    closed while the guard stayed broken for its two commonest failures.
    """
    (tmp_path / "hitchrail").mkdir()
    with pytest.raises(ConfigError) as exc:
        Config(roots=_r(tmp_path), self_project=value)
    assert "is not a folder in" in str(exc.value)


def test_a_self_project_that_is_really_there_is_accepted(tmp_path: Path) -> None:
    (tmp_path / "hitchrail").mkdir()
    cfg = Config(roots=_r(tmp_path), self_project="main~hitchrail")
    assert cfg.self_project == "main~hitchrail"


def test_no_self_project_protects_nothing_and_that_is_fine(tmp_path: Path) -> None:
    """Optional. Absence must not become a startup failure."""
    assert Config(roots=_r(tmp_path)).self_project is None


def test_a_file_is_not_a_self_project(tmp_path: Path) -> None:
    """`is_dir`, not `exists`: Hitchrail cannot be running inside a file."""
    (tmp_path / "hitchrail").write_text("not a folder")
    with pytest.raises(ConfigError):
        Config(roots=_r(tmp_path), self_project="main~hitchrail")


def test_the_refusal_names_the_flag_and_the_root(tmp_path: Path) -> None:
    """The operator has to be able to act on it without reading the source."""
    (tmp_path / "real").mkdir()
    with pytest.raises(ConfigError) as exc:
        Config(roots=_r(tmp_path), self_project="main~typo")
    message = str(exc.value)
    assert "--self-project" in message and "typo" in message and str(tmp_path) in message


def test_tmuxnames_does_not_import_the_adapter() -> None:
    """#93. The dependency runs one way, the third time this seam is cut.

    `tmux` imports `tmuxnames` for `sanitize` and `BINARY`. If the vocabulary
    ever imports the adapter back, the split stops being a seam and becomes a
    cut through a cycle, and the next person to tidy up will reasonably merge
    them again.

    **The point is not tidiness.** `tmuxnames` holds pure functions over strings
    and `lint-imports` cannot express "and no subprocess", so this is what stops
    the vocabulary acquiring one: a module that cannot import the adapter cannot
    borrow its runner.
    """
    import ast

    source = (Path(__file__).parent.parent / "src" / "hitchrail" / "tmuxnames.py").read_text()
    # **Parsed imports, never the file text.** The first version of this asserted
    # `"subprocess" not in source` and failed on the module docstring, which says
    # "No subprocess, no state, no server". That is the fourth time in this
    # repository that a guard has matched the sentence explaining the thing it
    # forbids, and the only way to make the text version pass is to delete the
    # explanation. Read what the module IMPORTS.
    imported = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[-1] if node.level == 0 else node.module)
    assert "tmux" not in imported, "the vocabulary imports the adapter, so the seam is a cycle"
    assert "subprocess" not in imported, (
        "the name vocabulary imports subprocess, which is the thing the split exists to prevent"
    )


def test_projectnames_does_not_import_config() -> None:
    """The dependency runs one way, the same seam `hostnames` has.

    `config` imports `projectnames` for #48. If `projectnames` ever imports
    `config` back, the split stops being a seam and becomes a cut through a
    cycle, and the next person to tidy up will reasonably merge them.
    """
    source = (
        Path(__file__).parent.parent / "src" / "hitchrail" / "projectnames.py"
    ).read_text()
    assert "import config" not in source
    assert "from hitchrail.config" not in source
    assert "from .config" not in source


# -- #108: the token demand follows reach, not the bind ----------------------
#
# The refusal used to ask `is_loopback`, which reads the BIND address. Behind a
# reverse proxy the bind stops being the truth: `tailscale serve` or an nginx
# forwards to 127.0.0.1, so Hitchrail saw a loopback socket, concluded it was
# local only, and demanded no token, while the whole tailnet could reach it.
#
# The operator declares that reach in the only place they can: `--allow-host`
# and `--allow-origin` exist for no other purpose than making a non local name
# work, so nobody passes one by accident. That is a better statement of intent
# than the bind, which anything can forward to.


def test_a_remote_allow_host_demands_a_token(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as excinfo:
        Config(
            roots=_r(tmp_path),
            host="127.0.0.1",
            token=None,
            extra_hosts=("box.tailnet.ts.net",),
        )
    assert "box.tailnet.ts.net" in str(excinfo.value)
    assert "--allow-host" in str(excinfo.value)


def test_a_remote_allow_origin_demands_a_token(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as excinfo:
        Config(
            roots=_r(tmp_path),
            host="127.0.0.1",
            token=None,
            extra_origins=("https://box.tailnet.ts.net",),
        )
    assert "box.tailnet.ts.net" in str(excinfo.value)
    assert "--allow-origin" in str(excinfo.value)


def test_a_remote_allow_host_with_a_token_is_accepted(tmp_path: Path) -> None:
    """The proxied deployment this refusal is meant to make safe, not refuse."""
    config = Config(
        roots=_r(tmp_path), host="127.0.0.1", token="t", extra_hosts=("box.tailnet.ts.net",)
    )
    assert "box.tailnet.ts.net" in config.allowed_hosts


@pytest.mark.parametrize("entry", ["localhost", "127.0.0.1", "::1", "[::1]", "127.0.0.2"])
def test_a_loopback_allow_host_still_needs_no_token(tmp_path: Path, entry: str) -> None:
    """A loopback name in the allowlist declares no reach, so refusing it would
    punish the harmless case and teach operators to pass --token reflexively."""
    assert (
        Config(roots=_r(tmp_path), host="127.0.0.1", token=None, extra_hosts=(entry,)).token
        is None
    )


@pytest.mark.parametrize(
    "entry", ["http://127.0.0.1:9000", "https://localhost", "http://[::1]:80"]
)
def test_a_loopback_allow_origin_still_needs_no_token(tmp_path: Path, entry: str) -> None:
    assert (
        Config(roots=_r(tmp_path), host="127.0.0.1", token=None, extra_origins=(entry,)).token
        is None
    )


def test_a_bare_loopback_bind_still_needs_no_token(tmp_path: Path) -> None:
    """How nearly everybody runs it. The change must not break this."""
    assert Config(roots=_r(tmp_path), host="127.0.0.1", token=None).token is None


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.1.10"])
def test_a_non_loopback_bind_still_demands_a_token(tmp_path: Path, host: str) -> None:
    """Regression guard: the new predicate must not weaken the old rule."""
    with pytest.raises(ConfigError, match="token"):
        Config(roots=_r(tmp_path), host=host, token=None)


# -- #131: the mutation config has to be able to assemble a tree that imports -

# Local to this section: this file resolves the repository root inline at each
# use rather than through a module constant, so the section brings its own.
_REPO = Path(__file__).resolve().parents[1]


def _mutmut_config() -> dict[str, list[str]]:
    """`[tool.mutmut]`, or a failure.

    **Fails rather than skips when the section is missing or unparseable.** A
    configuration guard that passes when it cannot find its configuration is
    the exact failure mode this exists to prevent, and it is how the
    `AGENTS.md` guards used to pass quietly on a clone.
    """
    import tomllib

    raw = (_REPO / "pyproject.toml").read_bytes()
    parsed: object = tomllib.loads(raw.decode()).get("tool", {}).get("mutmut")
    assert isinstance(parsed, dict), (
        "pyproject.toml has no usable [tool.mutmut]; the sweep cannot be configured"
    )
    section: dict[str, list[str]] = parsed
    assert section.get("source_paths"), "[tool.mutmut] names no source_paths to mutate"
    return section


def _first_party_imports(path: Path) -> set[str]:
    """Every `hitchrail` module this file imports, by module name.

    `ast.walk`, not `tree.body`: an import inside a function fails a mutmut run
    just as hard as a top level one, and later.
    """
    import ast

    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("hitchrail"):
            parts = (node.module or "").split(".")
            if len(parts) > 1:
                found.add(parts[1] + ".py")
            # `from hitchrail import claude_ipc, discovery`
            found |= {a.name + ".py" for a in node.names if len(parts) == 1}
        elif isinstance(node, ast.Import):
            for alias in node.names:
                bits = alias.name.split(".")
                if bits[0] == "hitchrail" and len(bits) > 1:
                    found.add(bits[1] + ".py")
    return found


def test_every_mutated_module_can_be_imported_from_the_mutants_tree() -> None:
    """#131. mutmut copies `source_paths` mutated plus `also_copy` verbatim, and
    nothing else. A mutated module importing something in neither list produces
    a tree that cannot import, and the run dies before scoring one mutant.

    **This has broken twice.** Once on `tests/conftest.py`, because `also_copy`
    does not create parent directories, and once on `roots.py` (#130), where
    `config` and `discovery` both import a module the config never copied.

    The check is a `tomllib` read and an `ast` walk, so it costs milliseconds
    and needs no mutation run. That shape is the point: the expensive sweep
    stays on demand, per `AGENTS.md`, and the cheap invariant that keeps it
    RUNNABLE becomes a gate. A check exempt from CI is a check that can rot
    without anybody learning.

    Structure, never file text. A guard that grepped `pyproject.toml` for a
    module name would match this docstring, which is the trap this repository
    has now hit three times.
    """
    section = _mutmut_config()
    copied = {Path(p).name for p in section["source_paths"] + section.get("also_copy", [])}

    missing: dict[str, set[str]] = {}
    for rel in section["source_paths"]:
        module = _REPO / rel
        gaps = {i for i in _first_party_imports(module) if i not in copied}
        if gaps:
            missing[Path(rel).name] = gaps

    assert not missing, (
        "the mutants tree cannot import: "
        + "; ".join(f"{m} imports {sorted(g)}" for m, g in sorted(missing.items()))
        + ". Add each to [tool.mutmut] source_paths or also_copy, or `uv run mutmut run` "
        "dies before it scores a single mutant."
    )
