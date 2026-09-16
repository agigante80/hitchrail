"""Which network this machine is on, answered by the default gateway's MAC.

#207. A unit that binds a named address on a removable adapter serves on
whatever network later hands the machine that address, and the unit's own
header says nothing will tell you when that happens. This is the "nothing":
`--expect-gateway-mac` names the gateway of the network the operator meant,
`cli.preflight` reads the gateway's MAC at every start, and a mismatch is a
refusal with exit 2, which `RestartPreventExitStatus=2` keeps stopped until a
person looks. Unset, the check is off.

**A guard against joining the wrong network by accident, and not against an
attacker.** A MAC is spoofable by anyone already on the LAN, so somebody who
has chosen to target this machine can present the expected one. What this
catches is the laptop taken to a cafe, the hotel wifi, the home router
replaced: the ordinary ways a trusted network silently stops being the one
the decision was made on.

**"Cannot tell" refuses.** No default route, no ARP entry for the gateway,
an unreadable table: each stays stopped rather than starting on a guess,
because a start that guesses is the direction the unit already refuses. The
cost is a boot on a machine whose network is merely unusual, and the
operator chose that cost by setting the flag.

Read from `/proc`, not from `ip`: two files, no subprocess, no dependency on
iproute2 being on a PATH the unit controls. The ARP table can be empty for
the gateway at boot, before anything has spoken to it, so one UDP datagram
to the discard port is sent to make the kernel resolve it. That is the one
packet this module puts on the wire; a test injects the sender.
"""

from __future__ import annotations

import contextlib
import re
import socket
import time
from collections.abc import Callable
from pathlib import Path

ROUTE = Path("/proc/net/route")
ARP = Path("/proc/net/arp")

# How long to give the kernel to resolve the gateway after the nudge. ARP on
# a LAN answers in milliseconds; a second is generous and bounds the boot.
RESOLVE_WAIT_S = 1.0
_POLL_S = 0.05


class GatewayUnknown(RuntimeError):
    """The gateway's MAC could not be determined, and why, for the operator."""


def normalise_mac(raw: str) -> str | None:
    """`AA-BB-CC-DD-EE-FF`, `aa:bb:cc:dd:ee:ff` and `aabb.ccdd.eeff` are one
    address. Lower case with colons, or None for anything that is not six
    octets."""
    digits = re.sub(r"[^0-9a-fA-F]", "", raw)
    if len(digits) != 12:
        return None
    return ":".join(digits[i : i + 2] for i in range(0, 12, 2)).lower()


def default_gateway(route_text: str) -> str | None:
    """The IPv4 default gateway from `/proc/net/route`, dotted, or None.

    The kernel writes each address as eight hex digits in HOST byte order,
    which on every machine this runs on is little endian: `0121A8C0` is
    192.168.33.1. The default route is the line whose destination is all
    zeros and whose flags carry RTF_GATEWAY (0x2).
    """
    for line in route_text.splitlines()[1:]:
        fields = line.split()
        if len(fields) < 4:
            continue
        _, destination, gateway, flags = fields[:4]
        try:
            if destination != "00000000" or not int(flags, 16) & 0x2:
                continue
            octets = bytes.fromhex(gateway)[::-1]
        except ValueError:
            continue
        if len(octets) == 4:
            return ".".join(str(b) for b in octets)
    return None


def mac_for(ip: str, arp_text: str) -> str | None:
    """The hardware address `/proc/net/arp` holds for an IP, or None when the
    entry is absent or incomplete (all zeros, which the kernel writes while a
    resolution is pending or failed)."""
    for line in arp_text.splitlines()[1:]:
        fields = line.split()
        if len(fields) >= 4 and fields[0] == ip:
            mac = normalise_mac(fields[3])
            return None if mac in (None, "00:00:00:00:00:00") else mac
    return None


def _nudge(ip: str) -> None:
    """Make the kernel resolve the gateway: one empty datagram to the discard
    port. Nothing listens and nothing answers; the ARP exchange is the whole
    effect."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.sendto(b"", (ip, 9))


def gateway_mac(
    route: Path = ROUTE,
    arp: Path = ARP,
    nudge: Callable[[str], None] = _nudge,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    """The default gateway's MAC, or `GatewayUnknown` saying what was missing.

    Every external surface is a parameter, so the unit tests never read this
    machine's tables or put a packet on its network.
    """
    try:
        route_text = route.read_text()
    except OSError as exc:
        raise GatewayUnknown(f"{route} cannot be read: {exc}") from exc
    ip = default_gateway(route_text)
    if ip is None:
        raise GatewayUnknown("this machine has no IPv4 default route")

    def read_arp() -> str | None:
        try:
            return mac_for(ip, arp.read_text())
        except OSError as exc:
            raise GatewayUnknown(f"{arp} cannot be read: {exc}") from exc

    mac = read_arp()
    if mac is not None:
        return mac
    # A refused send is itself evidence about the network; the table is
    # still asked again below, in case it filled meanwhile.
    with contextlib.suppress(OSError):
        nudge(ip)
    deadline = clock() + RESOLVE_WAIT_S
    while True:
        mac = read_arp()
        if mac is not None:
            return mac
        if clock() >= deadline:
            raise GatewayUnknown(
                f"the default gateway {ip} has no entry in the ARP table, so this "
                f"network cannot be identified"
            )
        sleep(_POLL_S)
