"""Which Host headers does the allowlist accept, and does every door into it
normalise and refuse the same way?

Hermetic: every test that exercises a wildcard bind injects a resolver, so no
test asks the operating system what this machine is called and none opens a
socket.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from config_support import _r, fixed_resolver
from hitchrail.config import (
    Config,
    ConfigError,
    is_wildcard_host,
)


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


def test_a_padded_extra_host_is_usable(tmp_path: Path) -> None:
    # A stray space from a comma split was accepted and then could never match
    # a Host header, which reads as the allowlist ignoring the operator.
    cfg = Config(roots=_r(tmp_path), host="0.0.0.0", token="t", extra_hosts=(" phone.lan ",))
    assert "phone.lan" in cfg.allowed_hosts
    assert " phone.lan " not in cfg.allowed_hosts


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
