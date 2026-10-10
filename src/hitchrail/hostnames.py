"""Host and origin vocabulary: one canonical form for each, used by every door.

Split out of `config.py` at #18, which had grown past the size the project's
guidelines allow, along a seam that was already there. These are pure functions
of their arguments with no dependency on `Config`, and they are what
`security.py` reaches for on every request; `Config` and its refusals are
startup only. A request time helper living in a module named for startup
configuration was the clearest sign the seam was real.

Nothing here imports `config`. The dependency runs one way, which is what makes
this a seam rather than a cut through a cycle, and a test asserts it.
"""

from __future__ import annotations

import contextlib
import ipaddress
import re
import socket
from collections.abc import Callable
from urllib.parse import SplitResult, urlsplit

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

    The trailing root dot of an FQDN goes too, and this reverses an earlier
    decision recorded here, so the reasoning is worth keeping. `box.lan.` and
    `box.lan` name the same machine, and a browser at `http://box.lan./` sends
    the dot in both `Host` and `Origin`. A first attempt stripped it HERE ONLY
    and made things worse: `security.parse_host` did not strip, the two sides
    stopped meeting, and no spelling of `--allow-host` served a dotted `Host`.
    It was reverted rather than patched. Both doors now strip, which is the
    only form that works, and `security.parse_host` carries the same rule.

    The strip is unconditional, not one dot. `is_valid_host` normalises before
    matching, so a single strip turned `box.lan..` into `box.lan.`, walked it
    past the pattern, and stored an entry nothing could ever match: a clean
    refusal converted into the accepted-then-never-matches shape this module
    exists to refuse. `rstrip` takes `.` and `..` to the empty string, which
    the pattern already rejects, so the refusal stays a refusal.
    """
    value = raw.strip().lower()
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    # Unconditional: see the docstring. A `len(value) > 1` guard looked like
    # safety and was the bug.
    return value.rstrip(".")


def split_origin(entry: str) -> SplitResult:
    """The one place an operator's origin string is taken apart (#439).

    Trimmed, a trailing slash dropped, lowercased, then `urlsplit`. Five call
    sites once each restated that recipe, and one of them skipped
    `normalise_host`, so the CLI's https host match could disagree with the
    allowlist about a root dot spelling. A guard in `test_config_origins.py`
    fails when `urlsplit` is called anywhere else in `src/`.

    Raises `ValueError` as `urlsplit` does (an unbalanced bracket); the
    callers decide whether that is a refusal or something to skip. The host
    comes back as `parts.hostname`, lowercased but with any root dot, so
    callers pass it through `normalise_host`.
    """
    return urlsplit(entry.strip().rstrip("/").lower())


def origin_parts(entry: str, *, loopback: bool = False) -> tuple[str, str] | None:
    """An allowed origin as `(scheme, host)`, or None when it is unparseable or
    loopback (unless `loopback` asks to keep it).

    One reader for the cookie rule, the TLS refusal and the CLI's https hosts,
    so they agree about what counts as somebody else's browser (#269). The host
    goes through `normalise_host`, as `_allowed_hosts` does (#439).
    """
    try:
        parts = split_origin(entry)
    except ValueError:
        return None
    host = normalise_host(parts.hostname) if parts.hostname else ""
    if not host or (is_loopback_host(host) and not loopback):
        return None
    return parts.scheme, host


def normalise_origin(raw: str) -> str:
    """One canonical form for an origin, host included.

    `normalise_host` canonicalises a bare host and this does the same for a
    host wrapped in an origin, so the allowlist and an `Origin` header meet in
    the middle exactly as they do for `Host`. Fixing the `Host` side alone
    would serve the page at `http://box.lan./` and then refuse every mutating
    request from it, which reads as the application being broken rather than
    misconfigured.

    Anything that is not an origin is returned unchanged rather than repaired.
    The caller compares for equality against an allowlist, so a value this
    function cannot parse simply fails to match and the request is refused.
    Repairing junk into a match is the failure mode worth avoiding here.
    """
    value = raw.strip().rstrip("/").lower()
    scheme, separator, rest = value.partition("://")
    if not separator or not rest:
        return value
    if rest.startswith("["):
        # An IPv6 literal cannot carry a root dot, and its brackets must not be
        # split on the colons inside them.
        return f"{scheme}://{rest}"
    host, colon, port = rest.partition(":")
    return f"{scheme}://{host.rstrip('.')}{colon}{port}"


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


def browse_origin(host: str, port: int | None) -> str:
    """The shortest plain http origin for `host`, the one to print for a person."""
    return min(origin_forms("http", host, port), key=len)


def served_host(bind: str) -> str:
    """The name that reaches a socket bound to `bind` from this machine (#488).

    `localhost` for the three binds it resolves to. Any other loopback address,
    `127.0.0.2` say, is not served by it: `localhost` resolves to 127.0.0.1,
    where nothing listens, so the bound address is named instead.
    """
    bare = normalise_host(bind)
    return "localhost" if bare in {"localhost", "127.0.0.1", "::1"} else bare


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


def is_loopback_host(host: str) -> bool:
    """Module level so the CLI can ask the same question without a second copy.

    Two copies of this rule would drift, and the one that drifts is the one
    deciding whether a token is demanded at all.

    `[::1]` is the form people copy out of a URL and out of some proxy
    documentation, and reading it as a network bind meant refusing to serve
    loopback without a token, with a message about anyone on the network being
    able to run code as you. Fail safe, but wrong and rude.

    The answer has to be the one the bind gets, and uvicorn's bind goes
    through `getaddrinfo`, not `ipaddress` (#283). Two spellings differ:
    `::ffff:127.0.0.1` is mapped to its IPv4 address first, because whether
    `ipaddress` calls it loopback varies by PATCH release (True on 3.11.13
    and 3.13, False on 3.12.3). That answer is for a Host header or an
    origin: as a bind it cannot serve, since uvicorn's socket is IPv6 only,
    and `Config` refuses it there (#395). And `127.1` is not an `ipaddress`
    literal at all, so a dotted decimal form is read by `inet_aton`, the
    parser the bind uses, which also gives `0177.0.0.1` its octal meaning. Digits and dots
    only: `inet_aton` would take hex too, and a spelling nobody types is not
    worth widening what reaches it.
    """
    bare = normalise_host(host)
    if bare in LOOPBACK_NAMES:
        return True
    try:
        address = ipaddress.ip_address(bare)
    except ValueError:
        if not re.fullmatch(r"[0-9]+(?:\.[0-9]+){0,3}", bare):
            return False
        try:
            return ipaddress.IPv4Address(socket.inet_aton(bare)).is_loopback
        except OSError:
            return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        return address.ipv4_mapped.is_loopback
    return address.is_loopback


def is_secure_context_host(host: str) -> bool:
    """Whether a browser treats a plain http origin on this host as a secure
    context, which is what lets it send a `Secure` cookie there (#436).

    The W3C Secure Contexts spec's "potentially trustworthy origin" rule, read
    2026-10-09 (algorithm 3.1): an IP address in 127.0.0.0/8 or `::1`, the
    host `localhost`, or a name ending in `.localhost`, a trailing root dot
    allowed. Deliberately NOT `is_loopback_host`, and not by changing
    `LOOPBACK_NAMES`: that set decides who must present a token, and
    `localhost.localdomain` belongs in it for that, since this machine's
    resolver sends it to loopback. The spec does not list it, so a browser
    drops a `Secure` cookie on it. Only `Config.plain_origins_withheld` asks.
    """
    bare = normalise_host(host)
    if bare == "localhost" or bare.endswith(".localhost"):
        return True
    if bare in LOOPBACK_NAMES:
        return False
    try:
        address = ipaddress.ip_address(bare)
    except ValueError:
        # The dotted decimal spellings `is_loopback_host` also reads; a
        # browser's URL parser canonicalises `127.1` to 127.0.0.1.
        return is_loopback_host(bare)
    if isinstance(address, ipaddress.IPv6Address):
        return address == ipaddress.IPv6Address("::1")
    return address.is_loopback


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


def reachable_hosts(
    host: str, allowed: tuple[str, ...], declared: tuple[str, ...]
) -> list[str]:
    """Of `allowed`, the hosts a socket bound to `host` actually answers on.

    **This is not the allowlist, and #202 is what happens when they are
    confused.** An allowlist says whose `Host:` header is accepted, and it
    carries the loopback names by construction. What a phone can open is a
    different question. The two coincide under a loopback or a wildcard bind,
    which is why the banner printed the allowlist for months without anybody
    noticing; with `--host` naming one address it offered `localhost` and
    `127.0.0.1` links that answered nothing, which reads as "the service is
    down" while the service is fine.

    `declared` is `--allow-host`, and its entries are kept WITHOUT resolving
    them. That flag exists for no purpose except making a name work here, so an
    entry is the operator saying the name arrives. `remote_reach` reads the
    allowlist the same way, as a declaration rather than a hint. The
    alternative is a DNS lookup inside the line that reports the server
    started, which is a network call that can hang or time out.

    The loopback names are the ones nobody declared, so they go, unless the
    bind is itself loopback where they do reach it.
    """
    if is_wildcard_host(host):
        # Every interface, so anything the allowlist accepts is reachable.
        return list(allowed)
    bound = normalise_host(host)
    spoken_for = {normalise_host(h) for h in declared}
    return [
        h
        for h in allowed
        if h == bound or h in spoken_for or (is_loopback_host(h) and is_loopback_host(host))
    ]
