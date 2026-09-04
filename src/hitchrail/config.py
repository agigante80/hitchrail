"""Runtime configuration, and the refusals that depend on it.

The host and origin vocabulary these refusals are built from lives in
`hostnames.py`, split out at #18. This module owns the dataclass, its checks
and the derived allowlists; that one owns what a valid host or origin IS.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from hitchrail.hostnames import (
    DEFAULT_PORTS,
    HOSTNAME_PATTERN,
    LOOPBACK_NAMES,
    MAX_HOSTNAME_LENGTH,
    Resolver,
    is_loopback_host,
    is_valid_host,
    is_wildcard_host,
    local_addresses,
    normalise_host,
    normalise_origin,
    origin_forms,
)
from hitchrail.projectnames import explain_name
from hitchrail.roots import Root, RootError, check_roots, split_identifier

# Re exported for the modules and tests that already import these from here.
# The owner is `hostnames`; this keeps one import site working rather than
# hiding which module defines what.
__all__ = [
    "DEFAULT_PORTS",
    "HOSTNAME_PATTERN",
    "LOOPBACK_NAMES",
    "MAX_HOSTNAME_LENGTH",
    "Config",
    "ConfigError",
    "Resolver",
    "is_loopback_host",
    "is_valid_host",
    "is_wildcard_host",
    "local_addresses",
    "normalise_host",
    "normalise_origin",
    "origin_forms",
]


class ConfigError(ValueError):
    """The configuration is not one Hitchrail is willing to run with."""


def remote_reach(
    host: str,
    extra_hosts: tuple[str, ...] = (),
    extra_origins: tuple[str, ...] = (),
) -> str | None:
    """Can anything outside this machine reach a server configured like this?

    Returns the reason, phrased for an error message, or None.

    **The bind address is not the whole answer, which is what #108 fixed.** It
    used to be: the token refusal asked `is_loopback` and nothing else. Behind a
    reverse proxy that is false. `tailscale serve`, an nginx or an SSH forward
    all hand a request to 127.0.0.1, so Hitchrail saw a loopback socket,
    concluded it was local only and demanded no token while a whole network
    could reach it. `--allow-origin`'s own help text names that deployment, so
    the project already knew proxies exist.

    An allowlist entry is a declaration, not a hint. `--allow-host` and
    `--allow-origin` exist for no purpose except making a non local name work,
    so a non loopback entry in either is the operator saying that something
    beyond this machine will arrive. That is a better source of truth than the
    bind, which anything in front of it can forward to.

    Module level, and the CLI calls it rather than restating the rule, for the
    reason `is_loopback_host` gives: two copies of this would drift, and the one
    that drifts is the one deciding whether a token is demanded at all. The CLI
    also has to ask before a Config exists, so this cannot be a property.
    """
    if not is_loopback_host(host):
        return "binding to anything but loopback"
    for entry in extra_hosts:
        if not is_loopback_host(entry):
            return f"--allow-host {entry} says something outside this machine can reach it"
    for entry in extra_origins:
        # Parsed rather than pattern matched, and failures are ignored here:
        # `_check_extra_origins` owns rejecting a malformed origin and runs
        # first, so anything unparseable has already raised by the time this
        # is consulted from `__post_init__`. The CLI calls this BEFORE
        # constructing a Config, though, so a bad entry must not crash here on
        # its way to that refusal.
        try:
            hostname = urlsplit(entry.strip().rstrip("/")).hostname
        except ValueError:
            continue
        if hostname and not is_loopback_host(hostname):
            return f"--allow-origin {entry} says something outside this machine can reach it"
    return None


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

    roots: tuple[Root, ...]
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
    # Named for the role, not the vendor. Hitchrail launches one agent today and
    # the default below says which. The name is operator facing, and
    # docs/versioning.md makes renaming an operator facing name a MAJOR, so it
    # is worth costing nothing now rather than a major version later. See the
    # multi agent note in the design's section 3.
    agent_binary: str = "claude"
    # The default is Claude Code's state directory. The field name is neutral
    # because the directory is the agent adapter's business, not the server's.
    sessions_dir: Path = field(default_factory=lambda: Path.home() / ".claude" / "sessions")
    # Where the agent records which folders it has been trusted with (#88).
    # A seam like `sessions_dir` beside it, for the same reason: the engine has
    # to be testable without the developer's own home directory deciding what
    # a row says.
    agent_config_path: Path = field(default_factory=lambda: Path.home() / ".claude.json")
    tmux_socket: str | None = None
    self_project: str | None = None
    resolver: Resolver | None = None

    _allowed_hosts: tuple[str, ...] = field(init=False, repr=False, default=())
    _allowed_origins: frozenset[str] = field(init=False, repr=False, default=frozenset())

    def __post_init__(self) -> None:
        # #120. Every refusal a set of roots can earn lives in `roots.py`,
        # beside what a root IS, for the same reason the host vocabulary lives
        # in `hostnames.py` rather than here. Re-raised as ConfigError so a
        # caller still catches one type for "this configuration will not run".
        try:
            check_roots(self.roots)
        except RootError as exc:
            raise ConfigError(str(exc)) from exc

        # The bind address is stored canonical, not as it was typed. It is
        # validated through is_valid_host, which normalises before matching, so
        # `[::1]` and ` 127.0.0.1 ` passed validation and were then handed to
        # uvicorn verbatim by the CLI (phase 5), where socket.bind raises
        # gaierror.
        # `[::1]` is the spelling people copy out of a browser's address bar,
        # so it is worth accepting rather than refusing; it just has to be
        # written down in the form that can be bound.
        object.__setattr__(self, "host", normalise_host(self.host) or self.host)

        self._check_token()
        self._check_session_prefix()
        self._check_agent_binary()
        self._check_numbers()
        self._check_bind_host()
        self._check_extra_hosts()
        self._check_extra_origins()
        self._check_self_project()

        reach = remote_reach(self.host, self.extra_hosts, self.extra_origins)
        if reach and not self.token:
            raise ConfigError(
                f"a token is required when {reach}: anyone who can reach this "
                "API can run code as you"
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

    def _check_agent_binary(self) -> None:
        """A binary name beginning with '-' becomes a flag in an argv slot.

        There is no shell anywhere in this project and that does not help here:
        argv[0] starting with a hyphen is read as an option by whatever ends up
        parsing it.
        """
        binary = self.agent_binary.strip()
        if not binary or binary.startswith("-"):
            raise ConfigError(f"not an acceptable agent binary: {self.agent_binary!r}")

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

    def _check_self_project(self) -> None:
        """A protection that silently does not apply is worse than none.

        `protected` is plain string equality, so a value that can never match
        disables the lock with nothing said anywhere: the operator believes the
        session hosting Hitchrail cannot be stopped, and its stop control
        behaves like any other. There is no undo, and it takes the interface
        down with it.

        Shape AND existence, because shape alone leaves the likeliest mistakes
        in place. `./hitchrail` and `hitchrail/` are refused by shape;
        `Hitchrail` and `hitchrai` are well shaped and still never match, and a
        capital letter and a typo are exactly what a person gets wrong.

        Existence costs a filesystem read at construction, which this class
        otherwise avoids. The argument for paying it: this flag cannot be
        satisfied by a folder that is not there, because it names the project
        Hitchrail runs in. If it is absent, the flag was meaningless whatever
        we do, and refusing says so where accepting hides it.

        Reached through `projectnames`, not `discovery`, so the rule is the one
        the rest of the project uses and the dependency stays one way, exactly
        as `config` reaches for `hostnames`. Past `explain_name` a name holds
        no separator and no leading dot, so `root / name` is a direct child by
        construction.
        """
        if self.self_project is None:
            return
        # #119: it names a folder in a specific root, so it is a qualified
        # identifier. A bare name would be ambiguous exactly where being wrong
        # is worst, which is the one project that must never be stopped.
        try:
            label, name = split_identifier(self.self_project)
        except RootError as exc:
            raise ConfigError(f"--self-project {self.self_project!r}: {exc}") from exc
        reason = explain_name(name)
        if reason is not None:
            raise ConfigError(
                f"--self-project {self.self_project!r} is not a project name: {reason}"
            )
        matches = [r for r in self.roots if r.label == label]
        if not matches:
            raise ConfigError(
                f"--self-project {self.self_project!r} names root {label!r}, "
                "which is not configured"
            )
        if not (matches[0].path / name).is_dir():
            raise ConfigError(
                f"--self-project {self.self_project!r} is not a folder in "
                f"{matches[0].path}. The protection is a name comparison, so a "
                "name that is not there never matches and the session hosting "
                "Hitchrail would be stoppable with nothing to say so"
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
            try:
                parts = urlsplit(candidate)
            except ValueError as exc:
                # urlsplit validates bracketed netlocs itself and raises before
                # any refusal in this function runs, so `http://[::1].` came
                # out as a bare `Invalid IPv6 URL` rather than a ConfigError
                # naming the entry. The port is already wrapped below for the
                # same class of deferred failure; this is the other half.
                raise ConfigError(
                    f"not an origin: {entry!r}. Give scheme://host[:port], "
                    "for example https://box.lan:8443"
                ) from exc
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
            # normalise_host, not parts.hostname raw: urlsplit lowercases but
            # keeps a trailing root dot, so `--allow-origin https://box.lan.`
            # would be stored in a spelling no browser sends.
            origins.update(
                origin_forms(parts.scheme, normalise_host(parts.hostname), parts.port)
            )
        return frozenset(origins)
