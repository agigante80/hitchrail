"""Configuration, and the two refusals that depend on it.

Hermetic: every test that exercises a wildcard bind injects a resolver, so no
test asks the operating system what this machine is called and none opens a
socket.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from hitchrail.config import (
    Config,
    ConfigError,
    is_loopback_host,
    is_wildcard_host,
    local_addresses,
)

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
    cfg = Config(root=tmp_path)
    assert cfg.is_loopback
    assert cfg.token is None


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1", "127.0.0.5"])
def test_loopback_forms_are_recognised(tmp_path: Path, host: str) -> None:
    assert Config(root=tmp_path, host=host).is_loopback


@pytest.mark.parametrize("host", ["0.0.0.0", "::"])
def test_wildcard_forms_are_recognised(host: str) -> None:
    assert is_wildcard_host(host)
    assert not is_loopback_host(host)


def test_network_bind_without_a_token_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="token"):
        Config(root=tmp_path, host="0.0.0.0", token=None)


def test_network_bind_with_a_token_is_allowed(tmp_path: Path) -> None:
    cfg = Config(root=tmp_path, host="0.0.0.0", token="s3cret")
    assert not cfg.is_loopback


def test_missing_root_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="root"):
        Config(root=tmp_path / "nope")


def test_a_file_as_root_is_refused(tmp_path: Path) -> None:
    target = tmp_path / "notes.txt"
    target.write_text("x")
    with pytest.raises(ConfigError, match="root"):
        Config(root=target)


def test_allowed_hosts_covers_loopback_and_a_concrete_bind(tmp_path: Path) -> None:
    cfg = Config(root=tmp_path, host="192.168.1.10", token="t")
    assert "192.168.1.10" in cfg.allowed_hosts
    assert "localhost" in cfg.allowed_hosts


def test_a_wildcard_bind_allows_the_machines_own_address(tmp_path: Path) -> None:
    # The regression this task exists for. Without it the phone that the whole
    # design is aimed at gets a 400 from its own machine.
    cfg = Config(
        root=tmp_path,
        host="0.0.0.0",
        token="t",
        resolver=fixed_resolver("192.168.1.10", "box.lan"),
    )
    assert "192.168.1.10" in cfg.allowed_hosts
    assert "box.lan" in cfg.allowed_hosts


def test_a_wildcard_bind_never_allows_the_wildcard_itself(tmp_path: Path) -> None:
    cfg = Config(
        root=tmp_path,
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

    hosts = Config(root=tmp_path, host="127.0.0.1", resolver=counting_resolver).allowed_hosts
    assert "127.0.0.1" in hosts
    assert calls == []


def test_a_resolver_that_fails_does_not_break_the_config(tmp_path: Path) -> None:
    # Degraded, not crashed, and narrower rather than wider. A reading we could
    # not take must never widen what the server answers to.
    def broken_resolver() -> tuple[str, ...]:
        raise OSError("no network")

    cfg = Config(root=tmp_path, host="0.0.0.0", token="t", resolver=broken_resolver)
    assert "localhost" in cfg.allowed_hosts


def test_extra_allowed_hosts_are_included(tmp_path: Path) -> None:
    cfg = Config(root=tmp_path, host="0.0.0.0", token="t", extra_hosts=("box.lan",))
    assert "box.lan" in cfg.allowed_hosts


@pytest.mark.parametrize("bad", ["*", "*.example", " * "])
def test_wildcard_allowed_host_is_refused(tmp_path: Path, bad: str) -> None:
    with pytest.raises(ConfigError, match="wildcard"):
        Config(root=tmp_path, host="0.0.0.0", token="t", extra_hosts=(bad,))


def test_allowed_hosts_are_deduplicated_and_ordered(tmp_path: Path) -> None:
    cfg = Config(root=tmp_path, host="localhost", extra_hosts=("localhost", "box.lan"))
    hosts = cfg.allowed_hosts
    assert len(hosts) == len(set(hosts))
    assert hosts[0] == "localhost"


def test_allowed_origins_pin_the_port(tmp_path: Path) -> None:
    # Hostname alone is not enough: another app on localhost:3000 would
    # otherwise be same origin against an API equivalent to a shell.
    cfg = Config(root=tmp_path, port=8787)
    assert "http://localhost:8787" in cfg.allowed_origins
    assert "http://localhost:3000" not in cfg.allowed_origins


def test_the_proxy_origin_form_is_accepted(tmp_path: Path) -> None:
    # Behind a TLS terminating proxy the browser sends https://name with no
    # port. Refusing that would make the documented deployment impossible.
    cfg = Config(root=tmp_path, host="192.168.1.10", token="t", port=8787)
    assert "https://192.168.1.10" in cfg.allowed_origins


def test_the_bare_http_origin_is_not_accepted(tmp_path: Path) -> None:
    """Named regression: port 80 is a port like any other.

    An earlier version added `http://{host}` alongside the proxy form, which
    made any plain HTTP page on port 80 of the same host or LAN address a same
    origin caller against an API equivalent to a shell. That is precisely the
    hole the port pinning is written to close, reopened one line below the
    docstring claiming it was closed.
    """
    cfg = Config(root=tmp_path, host="192.168.1.10", token="t", port=8787)
    assert "http://192.168.1.10" not in cfg.allowed_origins
    assert "http://localhost" not in cfg.allowed_origins


def test_a_padded_extra_host_is_usable(tmp_path: Path) -> None:
    # A stray space from a comma split was accepted and then could never match
    # a Host header, which reads as the allowlist ignoring the operator.
    cfg = Config(root=tmp_path, host="0.0.0.0", token="t", extra_hosts=(" phone.lan ",))
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

    monkeypatch.setattr("hitchrail.config.socket.gethostname", lambda: "box")
    monkeypatch.setattr("hitchrail.config.socket.getaddrinfo", lambda *a, **k: [])
    monkeypatch.setattr("hitchrail.config.socket.socket", no_sockets)
    assert local_addresses() == ("box",)


def test_allowed_origins_bracket_an_ipv6_host(tmp_path: Path) -> None:
    # A bare ::1 in an origin is not a URL. Getting this wrong makes the check
    # reject a legitimate loopback browser rather than an attacker.
    cfg = Config(root=tmp_path, port=8787)
    assert "http://[::1]:8787" in cfg.allowed_origins
    assert "http://::1:8787" not in cfg.allowed_origins


def test_the_config_is_frozen(tmp_path: Path) -> None:
    # Validation happens once, in __post_init__. A mutable Config could be
    # edited past its own refusals after construction.
    cfg = Config(root=tmp_path)
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
        Config(root=tmp_path, host="box.lan")


def test_local_addresses_survives_a_machine_with_no_hostname(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse(*args: object, **kwargs: object) -> object:
        raise AssertionError("getaddrinfo must not be asked without a hostname")

    monkeypatch.setattr("hitchrail.config.socket.gethostname", lambda: "")
    monkeypatch.setattr("hitchrail.config.socket.getaddrinfo", refuse)
    monkeypatch.setattr("hitchrail.config.socket.socket", no_socket)
    assert local_addresses() == ()


def test_local_addresses_survives_a_failing_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A machine with no DNS is a machine Hitchrail still has to run on.
    def boom(*args: object, **kwargs: object) -> object:
        raise OSError("no resolver")

    monkeypatch.setattr("hitchrail.config.socket.gethostname", lambda: "box")
    monkeypatch.setattr("hitchrail.config.socket.getaddrinfo", boom)
    monkeypatch.setattr("hitchrail.config.socket.socket", no_socket)
    assert local_addresses() == ("box",)


def test_local_addresses_never_returns_a_wildcard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The one output that would turn the allowlist into no allowlist at all.
    monkeypatch.setattr("hitchrail.config.socket.gethostname", lambda: "0.0.0.0")
    monkeypatch.setattr(
        "hitchrail.config.socket.getaddrinfo",
        lambda *a, **k: [(0, 0, 0, "", ("::", 0))],
    )
    monkeypatch.setattr("hitchrail.config.socket.socket", no_socket)
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
        Config(root=tmp_path, host="0.0.0.0", token="t", extra_hosts=(bad,))


def test_a_bracketed_ipv6_extra_host_is_accepted(tmp_path: Path) -> None:
    cfg = Config(root=tmp_path, host="0.0.0.0", token="t", extra_hosts=("[fe80::1]",))
    assert "[fe80::1]" in cfg.allowed_hosts


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
        Config(root=tmp_path, session_prefix=prefix)


@pytest.mark.parametrize("binary", ["", "  ", "-rf", "--dangerously-skip-permissions"])
def test_a_flag_shaped_claude_binary_is_refused(tmp_path: Path, binary: str) -> None:
    # argv[0] starting with a hyphen is read as an option by whatever parses it,
    # and no shell being involved does not help.
    with pytest.raises(ConfigError, match="claude binary"):
        Config(root=tmp_path, claude_binary=binary)


@pytest.mark.parametrize("port", [0, -1, 65536, 99999])
def test_a_port_out_of_range_is_refused(tmp_path: Path, port: int) -> None:
    with pytest.raises(ConfigError, match="port"):
        Config(root=tmp_path, port=port)


def test_a_non_positive_stop_timeout_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="stop timeout"):
        Config(root=tmp_path, stop_timeout=0)


def test_an_inverted_pair_of_memory_floors_is_refused(tmp_path: Path) -> None:
    # The soft floor is the "ask first" threshold and the hard floor is the
    # refusal. Inverted, the confirmation gate can never fire and the guard
    # loses a step without saying so.
    with pytest.raises(ConfigError, match="soft floor"):
        Config(root=tmp_path, hard_floor_mb=3072, soft_floor_mb=1536)


@pytest.mark.parametrize("host", ["[::1]", " ::1 ", "[::1] "])
def test_a_bracketed_loopback_bind_is_recognised(tmp_path: Path, host: str) -> None:
    """Named regression: [::1] is the form people copy out of a URL.

    Reading it as a network bind meant refusing to serve loopback without a
    token, with a message about anyone on the network running code as you.
    """
    cfg = Config(root=tmp_path, host=host)
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

    cfg = Config(root=tmp_path, host="0.0.0.0", token="t", resolver=counting)
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

    monkeypatch.setattr("hitchrail.config.socket.gethostname", boom)
    monkeypatch.setattr("hitchrail.config.socket.socket", lambda *a, **k: FakeSocket())
    assert local_addresses() == ("192.168.5.5",)
