"""Runtime configuration, and the refusals that depend on it."""

from __future__ import annotations

import contextlib
import ipaddress
import re
import socket
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

LOOPBACK_NAMES = frozenset({"localhost", "localhost.localdomain"})
WILDCARD_HOSTS = frozenset({"0.0.0.0", "::", "*"})  # noqa: S104

# A bare hostname, or an IPv6 literal in brackets. Deliberately excludes a
# port, a scheme, a path and userinfo: `--allow-host box.lan:8787` used to be
# accepted and then never matched anything, because the Host header is compared
# with the port already stripped. It also misfired the IPv6 bracketing below
# and produced `http://[box.lan:8787]:8787` as an allowed origin. Silently
# ignoring what the operator configured is worse than refusing it.
HOST_PATTERN = re.compile(
    r"\A(?:\[[0-9A-Fa-f:.]+\]|[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)\Z"
)

Resolver = Callable[[], tuple[str, ...]]


class ConfigError(ValueError):
    """The configuration is not one Hitchrail is willing to run with."""


def is_loopback_host(host: str) -> bool:
    """Module level so the CLI can ask the same question without a second copy.

    Two copies of this rule would drift, and the one that drifts is the one
    deciding whether a token is demanded at all.

    Brackets are stripped first. `[::1]` is the form people copy out of a URL
    and out of some proxy documentation, and reading it as a network bind meant
    refusing to serve loopback without a token, with a message about anyone on
    the network being able to run code as you. Fail safe, but wrong and rude.
    """
    bare = host.strip().strip("[]")
    if bare in LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(bare).is_loopback
    except ValueError:
        return False


def is_wildcard_host(host: str) -> bool:
    return host.strip().strip("[]") in WILDCARD_HOSTS


def local_addresses() -> tuple[str, ...]:
    """Names and addresses this machine answers to, for a wildcard bind.

    Adding these to the host allowlist is safe against the threat the allowlist
    defends. DNS rebinding turns an attacker controlled NAME into our address;
    a browser only sends `Host: 192.168.1.10` because a person typed it.

    Best effort, and that has to hold for every lookup in here rather than most
    of them. Each is guarded separately so one failure cannot discard what the
    others already found: `gethostname` sat outside any suppress, so a
    container with an unreadable UTS name aborted the function before the
    routing table probe and left a wildcard bind reachable on loopback only.
    """
    found: list[str] = []

    with contextlib.suppress(OSError):
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
    #
    # suppress FIRST: `with a, b:` enters a before it evaluates b, so this also
    # covers a socket() that fails outright.
    with (
        contextlib.suppress(OSError),
        socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe,
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

    The allowlist is resolved once here rather than on every read. It was a
    plain property, which meant `gethostname`, `getaddrinfo` and a UDP socket
    on every access, and the middleware reads it once per request on the event
    loop. It also meant two reads inside one request could disagree, which is
    not a property an allowlist is allowed to have.
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

    _allowed_hosts: tuple[str, ...] = field(init=False, repr=False, default=())
    _allowed_origins: frozenset[str] = field(init=False, repr=False, default=frozenset())

    def __post_init__(self) -> None:
        if not self.root.is_dir():
            raise ConfigError(f"root is not a directory: {self.root}")

        self._check_session_prefix()
        self._check_claude_binary()
        self._check_numbers()
        self._check_extra_hosts()

        if not self.is_loopback and not self.token:
            raise ConfigError(
                "a token is required when binding to anything but loopback: "
                "anyone who can reach this API can run code as you"
            )

        object.__setattr__(self, "_allowed_hosts", self._resolve_allowed_hosts())
        object.__setattr__(self, "_allowed_origins", self._derive_allowed_origins())

    def _check_session_prefix(self) -> None:
        """An empty prefix makes the tmux kill guard vacuous.

        "Never kill a session whose name does not carry the configured prefix"
        is what stands between a stop and the developer's own tmux sessions,
        and every session name satisfies `startswith("")`. The guard is only
        worth what its prefix is worth, so the prefix cannot be nothing.
        """
        prefix = self.session_prefix
        if not prefix.strip() or prefix != prefix.strip():
            raise ConfigError(f"session prefix must be non blank and unpadded: {prefix!r}")
        if any(c in prefix for c in ".:") or any(c.isspace() for c in prefix):
            raise ConfigError(
                f"session prefix must not contain whitespace, '.' or ':': {prefix!r}. "
                "tmux reads '.' and ':' as window and pane separators, so a session "
                "named with one can be created and then never addressed"
            )

    def _check_claude_binary(self) -> None:
        """A binary name beginning with '-' becomes a flag in an argv slot.

        There is no shell anywhere in this project and that does not help here:
        argv[0] starting with a hyphen is read as an option by whatever ends up
        parsing it.
        """
        binary = self.claude_binary.strip()
        if not binary or binary.startswith("-"):
            raise ConfigError(f"not an acceptable claude binary: {self.claude_binary!r}")

    def _check_numbers(self) -> None:
        if not (1 <= self.port <= 65535):
            raise ConfigError(f"port out of range: {self.port}")
        if self.stop_timeout <= 0:
            raise ConfigError(f"stop timeout must be positive: {self.stop_timeout}")
        for name in ("hard_floor_mb", "soft_floor_mb", "session_mb"):
            value = getattr(self, name)
            if value < 0:
                raise ConfigError(f"{name} must not be negative: {value}")
        if self.soft_floor_mb < self.hard_floor_mb:
            # The soft floor is the "ask first" threshold and the hard floor is
            # the refusal. Inverted, the confirmation gate can never fire and
            # the guard silently loses a step.
            raise ConfigError(
                f"soft floor {self.soft_floor_mb} is below hard floor "
                f"{self.hard_floor_mb}, which makes the confirmation gate unreachable"
            )

    def _check_extra_hosts(self) -> None:
        for entry in self.extra_hosts:
            candidate = entry.strip()
            if is_wildcard_host(candidate) or candidate.startswith("*"):
                raise ConfigError(
                    "a wildcard allowed host defeats the point of the allowlist; "
                    "name the hosts explicitly"
                )
            if not HOST_PATTERN.match(candidate):
                raise ConfigError(
                    f"not a bare hostname: {entry!r}. Give the host on its own, with "
                    "no port, scheme or path, because the Host header is compared "
                    "with the port already stripped"
                )

    @property
    def is_loopback(self) -> bool:
        return is_loopback_host(self.host)

    @property
    def allowed_hosts(self) -> tuple[str, ...]:
        """Hosts the server will answer to. Never contains a wildcard."""
        return self._allowed_hosts

    @property
    def allowed_origins(self) -> frozenset[str]:
        """Exact origins the browser may claim on a mutating request."""
        return self._allowed_origins

    def _resolve_allowed_hosts(self) -> tuple[str, ...]:
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

        # Stripped: a padded entry (a stray space from a comma split) would be
        # accepted here and then never match a Host header, which reads as the
        # allowlist silently ignoring what the operator configured.
        hosts.extend(h.strip() for h in self.extra_hosts)
        # Filtering wildcards again on the way out, because the resolver is an
        # external surface and its output is not trusted to be well formed.
        return tuple(dict.fromkeys(h for h in hosts if h and not is_wildcard_host(h)))

    def _derive_allowed_origins(self) -> frozenset[str]:
        """Hostname alone is not enough.

        Another application on `localhost:3000` would otherwise be same origin
        against an API equivalent to a shell.

        `https://name` with no port is included because behind a TLS
        terminating reverse proxy, the deployment the README recommends, that
        is exactly what the browser sends.

        `http://name` with no port is NOT included, and that omission is the
        point. Port 80 is a port like any other, so accepting the bare form
        would make any plain HTTP page anywhere on the same host or LAN address
        a same origin caller, which is the hole the port pinning exists to
        close.

        Known limitation: a TLS proxy on a port other than 443 sends
        `https://name:8443` and is refused. There is no way to derive that port
        from our own bind, so it needs configuration rather than a guess. See
        https://github.com/agigante80/hitchrail/issues/6.
        """
        origins: set[str] = set()
        for host in self._allowed_hosts:
            # A bare ::1 in an origin is not a URL; IPv6 literals are bracketed.
            bracketed = f"[{host}]" if ":" in host and not host.startswith("[") else host
            origins.add(f"http://{bracketed}:{self.port}")
            origins.add(f"https://{bracketed}")
        return frozenset(origins)
