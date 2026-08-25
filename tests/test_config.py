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
)

Resolver = Callable[[], tuple[str, ...]]


def fixed_resolver(*addresses: str) -> Resolver:
    """A stand in for asking the operating system what this machine is called."""
    return lambda: tuple(addresses)


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


def test_allowed_origins_include_the_default_port_forms(tmp_path: Path) -> None:
    # Behind a TLS terminating proxy the browser sends https://name with no
    # port. Refusing that would make the documented deployment impossible.
    cfg = Config(root=tmp_path, host="192.168.1.10", token="t", port=8787)
    assert "https://192.168.1.10" in cfg.allowed_origins
    assert "http://192.168.1.10" in cfg.allowed_origins


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
