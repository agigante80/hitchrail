"""What does `local_addresses` ask the machine, and does it survive a machine
that answers badly or not at all?

None of these open a socket or ask the real resolver: each patches every
surface it reaches.
"""

from __future__ import annotations

import socket

import pytest

from config_support import no_socket
from hitchrail.config import (
    local_addresses,
)

# **Patching `hitchrail.hostnames.socket.*` patches the STDLIB (#235 L8).**
#
# `hitchrail.hostnames` does `import socket`, so `hitchrail.hostnames.socket` IS
# the module object, and `monkeypatch.setattr("hitchrail.hostnames.socket.socket",
# ...)` replaces `socket.socket` for every importer in the process, not just for
# the module under test. Verified: `hitchrail.hostnames.socket is socket`.
#
# **Recorded rather than fixed, and the reason is a rule this project already
# has.** The fix would be to import the three names into `hostnames` so tests
# could patch module-local bindings, and that is a production change made for a
# test's benefit: the move #216 refused when it declined to add a `--tmux-socket`
# flag so the CLI tier could isolate itself.
#
# What contains it: `monkeypatch` is function scoped and restores on teardown, so
# nothing survives the test, and this suite runs in one process without xdist, so
# no other test is executing while the fake is installed. Both halves have to
# hold. If either changes, this is a hazard rather than a note.
#
# The tests below and their siblings all inherit this. It is written once here
# rather than at each of the ten patch sites.


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


# -- #233: local_addresses' happy path, which no test pinned ------------------


def test_local_addresses_asks_the_machine_exactly_these_questions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#233. Seventeen mutants lived in this function and every one survived.

    Three tests cover it and all three are FAILURE paths: no socket, no
    hostname, a failing lookup. Nothing asserted what it asks for when the
    machine answers, so the arguments were free: `getaddrinfo(None, None)`,
    `socket.socket(socket.AF_INET, None)`, `probe.connect(None)` and a dropped
    second argument all passed.

    **The arguments are the behaviour here.** `AF_INET` with `SOCK_DGRAM` is
    what makes the probe ask the routing table without sending a packet, and
    `192.0.2.1` is TEST-NET-1 precisely because it is guaranteed unrouted: a
    mutant that connects somewhere real turns a config read into traffic.
    """
    asked: dict[str, object] = {}

    class Probe:
        def __enter__(self) -> Probe:
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        def connect(self, address: tuple[str, int]) -> None:
            asked["connect"] = address

        def getsockname(self) -> tuple[str, int]:
            return ("10.0.0.7", 0)

    monkeypatch.setattr("hitchrail.hostnames.socket.gethostname", lambda: "box")

    def record_lookup(*args: object) -> list[tuple[object, ...]]:
        asked["getaddrinfo"] = args
        return [(0, 0, 0, "", ("192.168.1.10", 0))]

    def record_socket(*args: object) -> Probe:
        asked["socket"] = args
        return Probe()

    monkeypatch.setattr("hitchrail.hostnames.socket.getaddrinfo", record_lookup)
    monkeypatch.setattr("hitchrail.hostnames.socket.socket", record_socket)

    result = local_addresses()

    assert asked["getaddrinfo"] == ("box", None), (
        "the hostname lookup asks for the name this machine reported, with no service filter"
    )
    assert asked["socket"] == (socket.AF_INET, socket.SOCK_DGRAM), (
        "a UDP socket is what asks the routing table without sending a packet"
    )
    assert asked["connect"] == ("192.0.2.1", 1), (
        "TEST-NET-1 is guaranteed unrouted; connecting anywhere else turns "
        "reading the config into real traffic"
    )
    assert result == ("box", "192.168.1.10", "10.0.0.7"), (
        f"the three sources are the hostname, its lookup and the routing "
        f"probe, in that order and deduplicated: {result}"
    )


@pytest.mark.parametrize(
    ("failing", "raised", "expected", "why"),
    [
        # The OUTER suppress, around gethostname. Both types, because the
        # mutants drop each one independently.
        ("gethostname", OSError("no UTS"), (), "an unreadable hostname is survivable"),
        (
            "gethostname",
            UnicodeError("bad label"),
            (),
            "UnicodeError is a ValueError, NOT an OSError, and getaddrinfo "
            "raises it for a label over 63 characters",
        ),
        # The INNER suppress, around the lookup. The hostname already found
        # must survive the lookup failing.
        ("getaddrinfo", OSError("EAI_NONAME"), ("box",), "a failed lookup keeps the hostname"),
        (
            "getaddrinfo",
            UnicodeError("idna"),
            ("box",),
            "a name that will not encode to IDNA keeps the hostname",
        ),
    ],
)
def test_local_addresses_suppresses_both_types_at_both_call_sites(
    monkeypatch: pytest.MonkeyPatch,
    failing: str,
    raised: Exception,
    expected: tuple[str, ...],
    why: str,
) -> None:
    """#233. Five survivors lived in the `contextlib.suppress` arguments:
    `suppress(OSError, None)`, `suppress(OSError,)` and `suppress(UnicodeError)`
    at both call sites.

    Three tests covered this function and all three were failure paths, but each
    raised only ONE type from ONE site, so dropping the other type from either
    tuple changed nothing any test could see.

    **The `UnicodeError` half is not decoration.** It is a `ValueError` and not
    an `OSError`, and `getaddrinfo` raises it for a hostname with a label over
    63 characters or one that will not encode to IDNA. A container or a pod can
    easily have such a name, and suppressing only `OSError` made `Config()` die
    with a raw `UnicodeError` on that machine. The function is documented as
    best effort and that has to hold for every lookup in it.
    """

    def boom(*args: object, **kwargs: object) -> object:
        raise raised

    monkeypatch.setattr("hitchrail.hostnames.socket.gethostname", lambda: "box")
    monkeypatch.setattr("hitchrail.hostnames.socket.getaddrinfo", lambda *a, **k: [])
    monkeypatch.setattr("hitchrail.hostnames.socket.socket", no_socket)
    monkeypatch.setattr(f"hitchrail.hostnames.socket.{failing}", boom)

    assert local_addresses() == expected, why


def test_the_inner_suppress_in_local_addresses_is_defensive_not_observable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#233. Two survivors narrow the INNER `contextlib.suppress` in
    `local_addresses`, dropping one type from its tuple. Neither can be killed.

    The inner block sits inside the outer one, which suppresses the same two
    types, and `found` has already been appended to by the time the lookup runs.
    So whatever the inner tuple drops, the outer catches, `found` is unchanged,
    and the routing table probe after the outer block still runs.

    **Driven through the REAL function, not a hand model (round 1 review).**
    The first version built its own `with_inner` and never referenced
    `local_addresses` at all, so it would have gone on asserting an equivalence
    after it stopped being true. Here the production function is called with
    each exception raised from `getaddrinfo`, which is the only call the inner
    suppress wraps.

    **What this does NOT detect, corrected in round 2 (#236 F2).** An earlier
    version of this paragraph claimed it catches the edit that moves code after
    the inner block. It does not: `outcome()` patches `socket.socket` to
    `no_socket`, so the routing table probe raises and contributes nothing in
    all three cases, and that probe is the only code after the inner block.
    Falsified by making the edit and watching this pass.

    The codebase is covered anyway, by
    `test_a_failing_gethostname_does_not_discard_the_probe_address`, which is
    what pins the probe's position. Two tests, two properties, and this one
    should not claim the other's.
    """

    def outcome(raising: Exception | None) -> tuple[str, ...]:
        def lookup(*args: object, **kwargs: object) -> object:
            if raising is not None:
                raise raising
            return [(0, 0, 0, "", ("192.168.1.10", 0))]

        monkeypatch.setattr("hitchrail.hostnames.socket.gethostname", lambda: "box")
        monkeypatch.setattr("hitchrail.hostnames.socket.getaddrinfo", lookup)
        monkeypatch.setattr("hitchrail.hostnames.socket.socket", no_socket)
        return local_addresses()

    # Whatever the lookup raises, the hostname already found survives it. That
    # is the property the inner suppress appears to provide and the outer one
    # actually provides, which is why narrowing the inner one changes nothing.
    assert outcome(OSError("EAI")) == ("box",)
    assert outcome(UnicodeError("idna")) == ("box",)
    assert outcome(None) == ("box", "192.168.1.10")
