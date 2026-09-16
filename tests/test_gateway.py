"""The wrong network guard (#207): the default gateway's MAC, read from
`/proc`, and the preflight that refuses a start on another network.

Every table here is a string a test wrote and the nudge is a recorder, so
nothing reads this machine's routes or puts a packet on its network;
`conftest.no_real_gateway` makes the real reader and the real nudge fail
loudly for every test, this file included.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import FakeClock
from hitchrail import gateway
from hitchrail.cli import build_config, gateway_verdict, main, parse_args
from hitchrail.config import Config, ConfigError
from support import make_config

# A real /proc/net/route, captured 2026-09-15: the default route through a
# removable adapter, and a docker bridge that is not a gateway.
ROUTE = """\
Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\t\tMTU\tWindow\tIRTT
enx803f5df75e5f\t00000000\t0121A8C0\t0003\t0\t0\t100\t00000000\t0\t0\t0
docker0\t0000800A\t00000000\t0001\t0\t0\t0\t00F0FFFF\t0\t0\t0
"""

ARP = """\
IP address       HW type     Flags       HW address            Mask     Device
172.24.0.2       0x1         0x0         00:00:00:00:00:00     *        br-1
192.168.33.1     0x1         0x2         A4:2B:B0:11:22:33     *        enx803f5df75e5f
"""

GATEWAY = "a4:2b:b0:11:22:33"


def test_the_default_gateway_is_read_in_host_byte_order() -> None:
    """`0121A8C0` is 192.168.33.1, little endian, and the bridge line with
    RTF_UP but no RTF_GATEWAY is not a default route."""
    assert gateway.default_gateway(ROUTE) == "192.168.33.1"
    assert gateway.default_gateway(ROUTE.splitlines()[0] + "\n") is None
    assert gateway.default_gateway("") is None


def test_a_pinned_arp_entry_is_cannot_tell(tmp_path: Path) -> None:
    """`ip neigh ... nud permanent` survives a change of network on the same
    device, so at a cafe whose router shares the home address the file
    would report the home MAC. The operator's assertion is not the
    network's answer."""
    pinned = ARP.replace("0x2         A4:2B", "0x6         A4:2B")
    with pytest.raises(gateway.PinnedEntry, match="permanent"):
        gateway.mac_for("192.168.33.1", pinned)
    route, arp = _tables(tmp_path, arp=pinned)
    with pytest.raises(gateway.GatewayPinned, match="pinned by hand"):
        gateway.gateway_mac(route, arp, nudge=lambda ip: None)
    # Exit 2, not the retried 3: a retry changes nothing about a pinned entry.
    config = make_config(tmp_path, expect_gateway_mac=GATEWAY)

    def read() -> str:
        return gateway.gateway_mac(route, arp, nudge=lambda ip: None)

    verdict = gateway_verdict(config, gateway_mac=read)
    assert verdict is not None and verdict[0] == 2
    assert "Unpin it" in verdict[1]


def test_the_real_reader_is_stubbed_for_every_test(tmp_path: Path) -> None:
    """The guard's guard: an engine or a verdict built with no seam reaches
    the stub in `conftest.no_real_gateway` and nothing else."""
    with pytest.raises(AssertionError, match="real gateway reader"):
        gateway.gateway_mac()
    with pytest.raises(AssertionError, match="datagram"):
        gateway._nudge("192.0.2.1")
    # And through `gateway_mac` with tables but no nudge, which is the call a
    # default bound at definition time let through (review, round 2).
    route, arp = _tables(tmp_path, arp=ARP.splitlines()[0] + "\n")
    with pytest.raises(AssertionError, match="datagram"):
        gateway.gateway_mac(route, arp)


def test_the_arp_table_yields_the_mac_and_treats_all_zeros_as_absent() -> None:
    assert gateway.mac_for("192.168.33.1", ARP) == GATEWAY
    # Pending or failed: the kernel writes zeros, which is not an identity.
    assert gateway.mac_for("172.24.0.2", ARP) is None
    assert gateway.mac_for("10.0.0.1", ARP) is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("A4:2B:B0:11:22:33", GATEWAY),
        ("a4-2b-b0-11-22-33", GATEWAY),
        ("a42b.b011.2233", GATEWAY),
        ("a42bb0112233", GATEWAY),
        ("a4:2b:b0:11:22", None),
        ("not a mac", None),
        ("", None),
        ("a4:2b:b0:11:22:33:44", None),
    ],
)
def test_a_mac_is_one_address_however_it_is_spelled(raw: str, expected: str | None) -> None:
    assert gateway.normalise_mac(raw) == expected


def _tables(tmp_path: Path, route: str = ROUTE, arp: str = ARP) -> tuple[Path, Path]:
    (tmp_path / "route").write_text(route)
    (tmp_path / "arp").write_text(arp)
    return tmp_path / "route", tmp_path / "arp"


def test_a_resolved_gateway_needs_no_packet(tmp_path: Path) -> None:
    route, arp = _tables(tmp_path)
    sent: list[str] = []
    assert gateway.gateway_mac(route, arp, nudge=sent.append) == GATEWAY
    assert sent == []


def test_an_unresolved_gateway_is_nudged_once_and_read_again(tmp_path: Path) -> None:
    """At boot nothing has spoken to the gateway yet, so its entry is absent
    or zeros. One datagram, then the table again until it fills."""
    route, arp = _tables(tmp_path, arp=ARP.replace(GATEWAY.upper(), "00:00:00:00:00:00"))
    clock = FakeClock()
    sent: list[str] = []

    def nudge(ip: str) -> None:
        sent.append(ip)
        arp.write_text(ARP)

    assert (
        gateway.gateway_mac(route, arp, nudge=nudge, clock=clock, sleep=clock.sleep) == GATEWAY
    )
    assert sent == ["192.168.33.1"]


def test_a_gateway_that_never_answers_is_unknown_after_the_wait(tmp_path: Path) -> None:
    route, arp = _tables(tmp_path, arp=ARP.splitlines()[0] + "\n")
    clock = FakeClock()
    with pytest.raises(gateway.GatewayUnknown, match="no entry in the ARP table"):
        gateway.gateway_mac(route, arp, nudge=lambda ip: None, clock=clock, sleep=clock.sleep)
    assert clock() >= gateway.RESOLVE_WAIT_S


def test_a_refused_send_does_not_end_the_question(tmp_path: Path) -> None:
    """The nudge failing (no route to host) is evidence about the network,
    and the table is still asked once more."""
    route, arp = _tables(tmp_path, arp=ARP.splitlines()[0] + "\n")
    clock = FakeClock()

    def refuse(ip: str) -> None:
        arp.write_text(ARP)
        raise OSError("Network is unreachable")

    assert (
        gateway.gateway_mac(route, arp, nudge=refuse, clock=clock, sleep=clock.sleep) == GATEWAY
    )


@pytest.mark.parametrize("missing", ["route", "arp"])
def test_an_unreadable_table_is_unknown_and_names_the_file(
    tmp_path: Path, missing: str
) -> None:
    route, arp = _tables(tmp_path)
    (tmp_path / missing).unlink()
    with pytest.raises(gateway.GatewayUnknown, match=missing):
        gateway.gateway_mac(route, arp, nudge=lambda ip: None)


def test_no_default_route_is_unknown(tmp_path: Path) -> None:
    route, arp = _tables(tmp_path, route=ROUTE.splitlines()[0] + "\n")
    with pytest.raises(gateway.GatewayUnknown, match="no IPv4 default route"):
        gateway.gateway_mac(route, arp, nudge=lambda ip: None)


# -- the flag, the config and the preflight ----------------------------------


def test_the_flag_is_normalised_on_the_way_in(tmp_path: Path) -> None:
    (tmp_path / "root").mkdir()
    argv = ["--root", f"main={tmp_path / 'root'}", "--expect-gateway-mac", "A4-2B-B0-11-22-33"]
    config = build_config(parse_args(argv))
    assert config.expect_gateway_mac == GATEWAY
    assert config.sources["expect_gateway_mac"] == "flag"


@pytest.mark.parametrize("bad", ["", "a4:2b", "gateway", "a4:2b:b0:11:22:33:44"])
def test_a_value_that_is_not_a_mac_refuses_at_startup(tmp_path: Path, bad: str) -> None:
    with pytest.raises(ConfigError, match="is not a MAC address"):
        Config(roots=make_config(tmp_path).roots, expect_gateway_mac=bad)


def _guarded(tmp_path: Path) -> Config:
    return make_config(tmp_path, expect_gateway_mac=GATEWAY)


def test_the_expected_network_starts_unchanged(tmp_path: Path) -> None:
    assert gateway_verdict(_guarded(tmp_path), gateway_mac=lambda: GATEWAY) is None


def test_a_different_network_is_exit_2_naming_both_addresses(tmp_path: Path) -> None:
    """Exit 2 is the deliberate stop `RestartPreventExitStatus=2` keeps
    stopped: the machine is on the wrong network, and only a person can say
    otherwise."""
    verdict = gateway_verdict(_guarded(tmp_path), gateway_mac=lambda: "de:ad:be:ef:00:01")
    assert verdict is not None
    code, message = verdict
    assert code == 2
    assert "de:ad:be:ef:00:01" in message
    assert GATEWAY in message
    assert "different network" in message


def test_cannot_tell_refuses_with_the_retried_exit_code(tmp_path: Path) -> None:
    """The decided direction, sharpened by review: an unidentifiable network
    serves nothing, and it is exit 3 rather than 2 because "no default route
    yet" is what a boot looks like before the lease lands. The unit retries
    3 within its budget; 2 it never retries, and a service dead on the
    right network was the failure the retry budget exists to prevent."""

    def unknown() -> str:
        raise gateway.GatewayUnknown("this machine has no IPv4 default route")

    verdict = gateway_verdict(_guarded(tmp_path), gateway_mac=unknown)
    assert verdict is not None
    code, message = verdict
    assert code == 3
    assert "cannot be identified" in message
    assert "no IPv4 default route" in message
    assert "Refusing rather than guessing" in message


def test_without_the_flag_the_network_is_never_read(tmp_path: Path) -> None:
    def explode() -> str:
        raise AssertionError("the gateway was read with the check off")

    assert gateway_verdict(make_config(tmp_path), gateway_mac=explode) is None


@pytest.mark.parametrize(
    ("found", "code"),
    [("de:ad:be:ef:00:01", 2), (None, 3)],
    ids=["mismatch", "cannot-tell"],
)
def test_the_verdict_is_the_exit_code_from_the_command_line(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    found: str | None,
    code: int,
) -> None:
    """Exit 2 is the stop the unit never restarts, exit 3 the one it retries,
    which is the whole mechanism: a wrong network is dead until a person
    acts, and a network not yet up is tried again."""
    (tmp_path / "root").mkdir()
    monkeypatch.setattr("shutil.which", lambda _n: "/usr/bin/x")

    def read() -> str:
        if found is None:
            raise gateway.GatewayUnknown("this machine has no IPv4 default route")
        return found

    monkeypatch.setattr(gateway, "gateway_mac", read)
    argv = ["--root", f"main={tmp_path / 'root'}", "--expect-gateway-mac", GATEWAY]
    assert main(argv) == code
    err = capsys.readouterr().err
    # The FAKE's words, so this cannot pass by reading the real machine's
    # tables and happening not to match, which the first version did.
    assert ("de:ad:be:ef:00:01" in err) if found else ("no IPv4 default route" in err)
