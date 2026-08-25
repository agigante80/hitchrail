"""Runtime configuration, and the refusals that depend on it."""

from __future__ import annotations

import contextlib
import ipaddress
import re
import socket
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

LOOPBACK_NAMES = frozenset({"localhost", "localhost.localdomain"})

# A DNS hostname, one label or several. Deliberately excludes a port, a scheme,
# a path and userinfo: `--allow-host box.lan:8787` was once accepted and then
# never matched anything, because a Host header is compared with the port
# already stripped. IP literals are validated by `ipaddress` instead, which is
# the only thing that actually knows what one looks like: an earlier character
# class accepted `[...]` and `[::1:::2]` as IPv6.
# Underscores are allowed. RFC 1123 does not permit them in a DNS hostname,
# and real machines and containers are named `dev_box` anyway, and
# `gethostname()` reports it. Tightening this to the RFC silently filtered
# such a host out of its own allowlist and made `--allow-host dev_box` a
# startup refusal with no way around it.
HOSTNAME_PATTERN = re.compile(
    r"\A(?!-)[A-Za-z0-9_-]{1,63}(?<!-)(?:\.(?!-)[A-Za-z0-9_-]{1,63}(?<!-))*\.?\Z"
)
MAX_HOSTNAME_LENGTH = 253
DEFAULT_PORTS = {"http": 80, "https": 443}

Resolver = Callable[[], tuple[str, ...]]


def normalise_host(raw: str) -> str:
    """One canonical form for a host: trimmed, lowercased, brackets stripped.

    Every host reaching the allowlist goes through here, whatever door it came
    in by: the bind address, `extra_hosts`, and whatever the resolver returned.

    Each of those grew its own partial normalisation, and every one of the five
    defects this function replaces was the same shape. The bind address skipped
    the validation `extra_hosts` got. The resolver's output skipped both.
    IPv6 was stored bare from one door and bracketed from another, so the
    allowlist held two spellings of one host and could disagree with itself.

    Brackets are stripped rather than kept. A `Host` header brackets an IPv6
    literal and a config file usually does not, so the matcher normalises the
    header the same way and both meet in the middle on the bare form. Storing
    both was a workaround for a matcher that could not strip them.

    A trailing root dot goes too. `box.lan.` and `box.lan` name the same
    machine and HOSTNAME_PATTERN accepts both, but a browser's Host header
    never carries the dot, so an allowlist entry written in FQDN root form was
    stored in a spelling nothing could ever match and answered 400 to the very
    host it was added for.
    """
    value = raw.strip().lower()
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    if len(value) > 1 and value.endswith("."):
        value = value[:-1]
    return value


def origin_forms(scheme: str, host: str, port: int | None) -> set[str]:
    """Every spelling a browser might send for one origin.

    Two things a naive f-string gets wrong, and both were shipped once:

    - An IPv6 literal is bracketed in a URL even though it is stored bare,
      because that is what a browser puts in an Origin header.
    - The URL spec serialises an origin WITHOUT the default port for its
      scheme, so a browser on port 80 sends `Origin: http://box.lan` and never
      `http://box.lan:80`. Both forms are emitted when the port is the default
      for the scheme, so whichever the browser chose matches.

    Used for the derived origins AND the configured ones. They had separate
    code, the default port rule was applied to one of them, and
    `--allow-origin https://box.lan:443` was then accepted and never matched.
    """
    bracketed = f"[{host}]" if ":" in host and not host.startswith("[") else host
    forms = set()
    if port is None:
        forms.add(f"{scheme}://{bracketed}")
        default = DEFAULT_PORTS.get(scheme)
        if default is not None:
            forms.add(f"{scheme}://{bracketed}:{default}")
    else:
        forms.add(f"{scheme}://{bracketed}:{port}")
        if DEFAULT_PORTS.get(scheme) == port:
            forms.add(f"{scheme}://{bracketed}")
    return forms


def is_valid_host(value: str) -> bool:
    """A bare hostname or IP literal, and nothing else.

    `ipaddress` decides what an IP literal is, because a character class does
    not: `[...]` and `[::1:::2]` both satisfied the pattern this replaces, so
    an entry the operator got wrong was accepted and then never matched.
    """
    bare = normalise_host(value)
    if not bare or len(bare) > MAX_HOSTNAME_LENGTH:
        return False
    try:
        ipaddress.ip_address(bare)
    except ValueError:
        return bool(HOSTNAME_PATTERN.match(bare))
    return True


class ConfigError(ValueError):
    """The configuration is not one Hitchrail is willing to run with."""


def is_loopback_host(host: str) -> bool:
    """Module level so the CLI can ask the same question without a second copy.

    Two copies of this rule would drift, and the one that drifts is the one
    deciding whether a token is demanded at all.

    `[::1]` is the form people copy out of a URL and out of some proxy
    documentation, and reading it as a network bind meant refusing to serve
    loopback without a token, with a message about anyone on the network being
    able to run code as you. Fail safe, but wrong and rude.
    """
    bare = normalise_host(host)
    if bare in LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(bare).is_loopback
    except ValueError:
        return False


def is_wildcard_host(host: str) -> bool:
    """Every spelling of "bind to everything", not a list of three.

    `is_unspecified` is what `ipaddress` calls this, and it covers `0.0.0.0`,
    `::`, `::0` and `0:0:0:0:0:0:0:0` alike. A membership test against a
    three element set called `::0` a concrete bind, so the resolver was never
    consulted and a wildcard bind written that way was reachable on loopback
    only, which is the regression the whole resolver exists to prevent.
    """
    bare = normalise_host(host)
    if bare == "*":
        return True
    try:
        return ipaddress.ip_address(bare).is_unspecified
    except ValueError:
        return False


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

    # UnicodeError as well as OSError. getaddrinfo raises UnicodeError, which
    # is a ValueError and NOT an OSError, for a hostname with a label over 63
    # characters or one that will not encode to IDNA. A container or a pod can
    # easily have such a name, and suppressing only OSError let Config() die
    # with a raw UnicodeError on that machine.
    with contextlib.suppress(OSError, UnicodeError):
        hostname = socket.gethostname()
        if hostname:
            found.append(hostname)
            with contextlib.suppress(OSError, UnicodeError):
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
    extra_origins: tuple[str, ...] = ()
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

        # The bind address is stored canonical, not as it was typed. It is
        # validated through is_valid_host, which normalises before matching, so
        # `[::1]` and ` 127.0.0.1 ` passed validation and were then handed to
        # uvicorn verbatim by cli._serve, where socket.bind raises gaierror.
        # `[::1]` is the spelling people copy out of a browser's address bar,
        # so it is worth accepting rather than refusing; it just has to be
        # written down in the form that can be bound.
        object.__setattr__(self, "host", normalise_host(self.host) or self.host)

        self._check_token()
        self._check_session_prefix()
        self._check_claude_binary()
        self._check_numbers()
        self._check_bind_host()
        self._check_extra_hosts()
        self._check_extra_origins()

        if not self.is_loopback and not self.token:
            raise ConfigError(
                "a token is required when binding to anything but loopback: "
                "anyone who can reach this API can run code as you"
            )

        object.__setattr__(self, "_allowed_hosts", self._resolve_allowed_hosts())
        object.__setattr__(self, "_allowed_origins", self._derive_allowed_origins())

    def _check_token(self) -> None:
        """`None` means no token. `""` is a token that matches nothing safely.

        An empty string is not None, so it switched the middleware ON with a
        secret that `compare_digest(b"", b"")` answers True for: a request
        carrying `Cookie: hitchrail_token=` was served. An operator reaches
        this by passing an unset shell variable, `--token "$HITCHRAIL_TOKEN"`,
        and believes they configured authentication.

        The floor is deliberately low rather than a policy. The CLI generates
        24 bytes; this only has to catch the empty and blank cases that mean
        "the operator thinks there is a token and there is not".
        """
        if self.token is None:
            return
        if not self.token.strip():
            raise ConfigError(
                "an empty token is not a token: pass a real one, or omit it "
                "entirely to run on loopback with no authentication"
            )

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

    def _check_bind_host(self) -> None:
        """The bind address goes through the same door as everything else.

        It used to skip this entirely, so `--host box.lan:8787` was accepted,
        landed in the allowlist verbatim where it could never match a Host
        header, and produced `http://[box.lan:8787]:8787` as an allowed origin
        because the port's colon misfired the IPv6 bracketing.
        """
        if self.host.strip() == "*":
            # `*` is a spelling of "any host" for an ALLOWLIST, and
            # is_wildcard_host counts it as one. It is not an address, and the
            # CLI hands this field straight to uvicorn, where it dies at bind
            # time with a message about getaddrinfo.
            raise ConfigError(
                "'*' is not an address to bind to: use 0.0.0.0 for every IPv4 "
                "interface, or :: for every interface"
            )
        if is_wildcard_host(self.host):
            return
        if not is_valid_host(self.host):
            raise ConfigError(
                f"not a bare host to bind to: {self.host!r}. Give the host on its "
                "own, with no port, scheme or path; the port is --port"
            )

    def _check_extra_hosts(self) -> None:
        for entry in self.extra_hosts:
            if is_wildcard_host(entry) or entry.strip().startswith("*"):
                raise ConfigError(
                    "a wildcard allowed host defeats the point of the allowlist; "
                    "name the hosts explicitly"
                )
            if not is_valid_host(entry):
                raise ConfigError(
                    f"not a bare hostname: {entry!r}. Give the host on its own, with "
                    "no port, scheme or path, because the Host header is compared "
                    "with the port already stripped"
                )

    def _check_extra_origins(self) -> None:
        """An origin is a scheme, a host and a port, and nothing else.

        Configured rather than guessed, because a TLS terminating proxy's
        origin cannot be derived from our own bind: the scheme is the proxy's,
        the port is the proxy's, and only the operator knows either.
        """
        for entry in self.extra_origins:
            candidate = entry.strip().rstrip("/")
            if "*" in candidate:
                raise ConfigError(
                    f"a wildcard origin defeats the point of the check: {entry!r}"
                )
            parts = urlsplit(candidate)
            if parts.scheme not in {"http", "https"} or not parts.hostname:
                raise ConfigError(
                    f"not an origin: {entry!r}. Give scheme://host[:port], "
                    "for example https://box.lan:8443"
                )
            # `username` alone is not enough: for `http://:pass@box.lan`,
            # urlsplit gives username='' which is falsy, and the entry was
            # accepted and then could never match anything.
            if parts.path or parts.query or parts.fragment or parts.username or parts.password:
                raise ConfigError(
                    f"an origin carries no path, query, fragment or userinfo: {entry!r}"
                )
            if parts.netloc.endswith(":"):
                # urlsplit reads `http://box.lan:` as port None rather than an
                # error, so it was accepted and then could never match: a
                # browser sends `http://box.lan`, never a bare trailing colon.
                #
                # Checked on the netloc, not the whole string. An earlier
                # version stripped a trailing `]` first, which made every IPv6
                # literal ending in `::` look like an empty port and refused
                # `http://[2001:db8::]` with a message about something the
                # operator never wrote.
                raise ConfigError(f"origin has an empty port: {entry!r}")
            try:
                port = parts.port
            except ValueError as exc:
                # urlsplit defers parsing the port until it is read, so a
                # non numeric one only surfaces here.
                raise ConfigError(f"not a valid port in origin {entry!r}") from exc
            if port is not None and not (1 <= port <= 65535):
                raise ConfigError(f"port out of range in origin {entry!r}")
            if not is_valid_host(parts.hostname):
                raise ConfigError(f"not a valid host in origin {entry!r}")

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
        """One canonical form per host, whatever door it came in by.

        `::1` appears once, bare. It used to appear twice, bare and bracketed,
        which was a workaround for a matcher that could not strip brackets. The
        matcher normalises now, so two spellings of one host would only be a
        thing that can disagree with itself.
        """
        hosts = ["localhost", "127.0.0.1", "::1"]

        if is_wildcard_host(self.host):
            # We are listening on every interface, so the bind string cannot
            # tell us what the phone will type. Ask the machine.
            resolve = self.resolver or local_addresses
            # A reading we could not take degrades to loopback only, which is
            # still a working allowlist. Never widen on a failed lookup.
            with contextlib.suppress(OSError, UnicodeError):
                hosts.extend(resolve())
        else:
            hosts.append(self.host)

        hosts.extend(self.extra_hosts)
        # The resolver is an external surface, so its output is filtered on the
        # way out too: a wildcard or an unparseable name from it must never
        # reach the allowlist just because it arrived from the operating system.
        normalised = (normalise_host(h) for h in hosts)
        return tuple(
            dict.fromkeys(
                h for h in normalised if h and not is_wildcard_host(h) and is_valid_host(h)
            )
        )

    def _derive_allowed_origins(self) -> frozenset[str]:
        """Exactly the origins we can know, plus exactly the ones configured.

        We know our own bind: scheme http, the hosts we answer to, our port.
        That is derived.

        Everything else is configured, and that is the change. An earlier
        version guessed `https://{host}` for every allowed host, which made any
        HTTPS service on port 443 of the same machine a same origin caller
        against an API equivalent to a shell. The module's own argument for
        refusing `http://{host}` is that port 80 is a port like any other, and
        that applies to 443 unchanged.

        A TLS terminating reverse proxy is the case the guess was for, and it
        is precisely the case we cannot derive: the scheme is the proxy's, the
        port is the proxy's, and only the operator knows either. So it is
        `extra_origins`, and the README says so.
        """
        origins: set[str] = set()
        for host in self._allowed_hosts:
            origins.update(origin_forms("http", host, self.port))
        for entry in self.extra_origins:
            parts = urlsplit(entry.strip().rstrip("/").lower())
            assert parts.hostname is not None  # validated in _check_extra_origins
            origins.update(origin_forms(parts.scheme, parts.hostname, parts.port))
        return frozenset(origins)
