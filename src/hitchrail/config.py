"""Runtime configuration, and the refusals that depend on it."""

from __future__ import annotations

import contextlib
import ipaddress
import socket
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

LOOPBACK_NAMES = frozenset({"localhost", "localhost.localdomain"})
WILDCARD_HOSTS = frozenset({"0.0.0.0", "::", "*"})  # noqa: S104

Resolver = Callable[[], tuple[str, ...]]


class ConfigError(ValueError):
    """The configuration is not one Hitchrail is willing to run with."""


def is_loopback_host(host: str) -> bool:
    """Module level so the CLI can ask the same question without a second copy.

    Two copies of this rule would drift, and the one that drifts is the one
    deciding whether a token is demanded at all.
    """
    if host in LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def is_wildcard_host(host: str) -> bool:
    return host.strip() in WILDCARD_HOSTS


def local_addresses() -> tuple[str, ...]:
    """Names and addresses this machine answers to, for a wildcard bind.

    Adding these to the host allowlist is safe against the threat the allowlist
    defends. DNS rebinding turns an attacker controlled NAME into our address;
    a browser only sends `Host: 192.168.1.10` because a person typed it.

    Best effort by design. A machine with no network, or one where the hostname
    does not resolve, degrades to loopback only rather than raising.
    """
    found: list[str] = []

    hostname = socket.gethostname()
    if hostname:
        found.append(hostname)
        with contextlib.suppress(OSError):
            for info in socket.getaddrinfo(hostname, None):
                address = info[4][0]
                if isinstance(address, str):
                    found.append(address)

    # The primary outbound address, which is usually the one a phone will use.
    # Connecting a UDP socket sends no packet; it only asks the routing table.
    with (
        socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe,
        contextlib.suppress(OSError),
    ):
        probe.connect(("192.0.2.1", 1))  # TEST-NET-1, guaranteed unrouted
        found.append(str(probe.getsockname()[0]))

    return tuple(dict.fromkeys(h for h in found if h and not is_wildcard_host(h)))


@dataclass(frozen=True)
class Config:
    """Validated at construction, so an unsafe configuration cannot exist.

    Checking later, wherever somebody remembers to, is how a refusal becomes
    optional. `frozen=True` is part of that: a mutable Config could be edited
    past its own refusals after __post_init__ has run.
    """

    root: Path
    host: str = "127.0.0.1"
    port: int = 8787
    token: str | None = None
    extra_hosts: tuple[str, ...] = ()
    session_prefix: str = "hr-"
    stop_timeout: float = 30.0
    hard_floor_mb: int = 1536
    soft_floor_mb: int = 3072
    session_mb: int = 1536
    claude_binary: str = "claude"
    sessions_dir: Path = field(default_factory=lambda: Path.home() / ".claude" / "sessions")
    tmux_socket: str | None = None
    self_project: str | None = None
    resolver: Resolver | None = None

    def __post_init__(self) -> None:
        if not self.root.is_dir():
            raise ConfigError(f"root is not a directory: {self.root}")
        if any(is_wildcard_host(h) or h.strip().startswith("*") for h in self.extra_hosts):
            raise ConfigError(
                "a wildcard allowed host defeats the point of the allowlist; "
                "name the hosts explicitly"
            )
        if not self.is_loopback and not self.token:
            raise ConfigError(
                "a token is required when binding to anything but loopback: "
                "anyone who can reach this API can run code as you"
            )

    @property
    def is_loopback(self) -> bool:
        return is_loopback_host(self.host)

    @property
    def allowed_hosts(self) -> tuple[str, ...]:
        """Hosts the server will answer to. Never contains a wildcard."""
        hosts = ["localhost", "127.0.0.1", "::1", "[::1]"]

        if is_wildcard_host(self.host):
            # We are listening on every interface, so the bind string cannot
            # tell us what the phone will type. Ask the machine.
            resolve = self.resolver or local_addresses
            # A reading we could not take degrades to loopback only, which is
            # still a working allowlist. Never widen on a failed lookup.
            with contextlib.suppress(OSError):
                hosts.extend(resolve())
        else:
            hosts.append(self.host)

        hosts.extend(self.extra_hosts)
        # Filtering wildcards again on the way out, because the resolver is an
        # external surface and its output is not trusted to be well formed.
        return tuple(dict.fromkeys(h for h in hosts if h and not is_wildcard_host(h)))

    @property
    def allowed_origins(self) -> frozenset[str]:
        """Exact origins the browser may claim on a mutating request.

        Hostname alone is not enough. Another application on `localhost:3000`
        would otherwise be same origin against an API equivalent to a shell.

        The default port forms are included because behind a TLS terminating
        reverse proxy the browser sends `https://name` with no port at all,
        and that deployment is the one the README recommends.
        """
        origins: set[str] = set()
        for host in self.allowed_hosts:
            # A bare ::1 in an origin is not a URL; IPv6 literals are bracketed.
            bracketed = f"[{host}]" if ":" in host and not host.startswith("[") else host
            origins.add(f"http://{bracketed}:{self.port}")
            origins.add(f"http://{bracketed}")
            origins.add(f"https://{bracketed}")
        return frozenset(origins)
