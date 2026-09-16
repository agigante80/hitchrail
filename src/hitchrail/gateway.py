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

**"Cannot tell" refuses, and is retried.** No default route, no ARP entry
for the gateway, an unreadable table, a pinned entry: each serves nothing
rather than starting on a guess, because a start that guesses is the
direction the unit already refuses. It is exit 3, the status the unit
retries within its budget, because "no default route" is what a boot looks
like before the DHCP lease lands; a MISMATCH is exit 2 and stays stopped
until a person looks. The cost is a boot on a machine whose network is
merely unusual, and the operator chose that cost by setting the flag.

**Checked once, at start.** The unit runs the check before it binds and
never again: a laptop that sleeps at home with the unit running and wakes
at a cafe is not noticed until the next start. A periodic re-check is a
design change for its own ticket, and every document that offers the flag
says this.

Read from `/proc`, not from `ip`: two files, no subprocess, no dependency on
iproute2 being on a PATH the unit controls. The ARP table can be empty for
the gateway at boot, before anything has spoken to it, so one UDP datagram
to the discard port is sent to make the kernel resolve it. That is the one
packet this module puts on the wire; a test injects the sender.

**The ARP table is a cache, and `/proc/net/arp` does not say how old an
entry is** (#260). It prints a STALE neighbour and a REACHABLE one
identically, `0x2` and the address, so behind a switch whose link never
drops, a router replaced and the unit restarted inside the kernel's relearn
window (a few tens of seconds by default) reads the old router's MAC and
passes. Reading the neighbour state needs netlink (`RTM_GETNEIGH`, some
forty lines of stdlib `AF_NETLINK`), which is a design choice this module
declines: the window is narrow, the case is a router swapped without a link
flap, and the guard is documented as one against carrying the machine
somewhere by accident, which a swapped router is not.
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
    """The gateway's MAC could not be determined, and why, for the operator.
    A transient: the unit retries it."""


class GatewayPinned(GatewayUnknown):
    """The operator pinned the gateway's entry, so the answer will not change
    on a retry; the unit stays stopped until they look."""


# The spellings a MAC is written in: colons, hyphens, Cisco's dotted quads,
# and the bare twelve digits. Nothing else (#260): the first version stripped
# every non hex character before counting, so `zz:a4:2b:b0:11:22:33` and
# `a4:2b:b0:11:22:33 router` passed a check whose refusal said "six pairs of
# hex digits". A check should match its own message.
_MAC_SPELLINGS = re.compile(
    r"\A(?:"
    r"(?:[0-9a-f]{2}:){5}[0-9a-f]{2}"
    r"|(?:[0-9a-f]{2}-){5}[0-9a-f]{2}"
    r"|[0-9a-f]{4}\.[0-9a-f]{4}\.[0-9a-f]{4}"
    r"|[0-9a-f]{12}"
    r")\Z",
    re.IGNORECASE,
)


def normalise_mac(raw: str) -> str | None:
    """`AA-BB-CC-DD-EE-FF`, `aa:bb:cc:dd:ee:ff`, `aabb.ccdd.eeff` and
    `aabbccddeeff` are one address. Lower case with colons, or None for
    anything that is not one of those four spellings of six octets."""
    if not _MAC_SPELLINGS.match(raw):
        return None
    digits = re.sub(r"[^0-9a-fA-F]", "", raw)
    return ":".join(digits[i : i + 2] for i in range(0, 12, 2)).lower()


def default_gateway(route_text: str) -> tuple[str, str] | None:
    """The IPv4 default gateway from `/proc/net/route`, as `(interface,
    dotted address)`, or None.

    The kernel writes each address as eight hex digits in HOST byte order,
    which on every machine this runs on is little endian: `0121A8C0` is
    192.168.33.1. The default route is the line whose destination is all
    zeros and whose flags carry RTF_GATEWAY (0x2).

    The FIRST such line is the preferred default. The file is the main
    table's trie, and within one prefix the kernel keeps aliases in metric
    ascending order (`fib_find_alias` in `net/ipv4/fib_trie.c` inserts a
    new route before the first whose priority is not below its own), so two
    defaults, wifi at 600 and ethernet at 100, list ethernet first.

    The interface rides along (#260): the ARP table is matched by address
    AND device, because two interfaces on one prefix (ethernet and wifi on
    the same LAN) hold two entries for one gateway address, and by address
    alone the answer was whichever the file listed first.
    """
    for line in route_text.splitlines()[1:]:
        fields = line.split()
        if len(fields) < 4:
            continue
        iface, destination, gateway, flags = fields[:4]
        try:
            if destination != "00000000" or not int(flags, 16) & 0x2:
                continue
            octets = bytes.fromhex(gateway)[::-1]
        except ValueError:
            continue
        if len(octets) == 4:
            return iface, ".".join(str(b) for b in octets)
    return None


# `/proc/net/arp` flags: ATF_COM (0x2) is a completed entry, ATF_PERM (0x4)
# one somebody pinned with `ip neigh ... nud permanent`.
_ATF_PERM = 0x4


class PinnedEntry(RuntimeError):
    """The gateway's ARP entry is permanent: the operator's assertion about
    the network, not the network's answer."""


def mac_for(ip: str, arp_text: str, iface: str | None = None) -> str | None:
    """The hardware address `/proc/net/arp` holds for an IP on an interface,
    or None when the entry is absent or incomplete (all zeros, which the
    kernel writes while a resolution is pending or failed). With `iface`
    None any device's entry answers, which only a test wants.

    A PERMANENT entry raises rather than answers (security audit of #207).
    The audience that sets this flag is the audience that pins the gateway
    against ARP spoofing, and a pinned entry survives carrier down and up on
    the same device: at a cafe whose router is also 192.168.1.1, the file
    would report the home MAC and the guard would pass on the operator's
    own assertion. "Cannot tell" is the honest answer there.
    """
    for line in arp_text.splitlines()[1:]:
        fields = line.split()
        if len(fields) >= 6 and fields[0] == ip and iface in (None, fields[5]):
            try:
                if int(fields[2], 16) & _ATF_PERM:
                    raise PinnedEntry(
                        f"the ARP entry for the gateway {ip} is permanent (pinned by "
                        f"hand), so it says what the operator asserted rather than "
                        f"what the network answered"
                    )
            except ValueError:
                pass
            mac = normalise_mac(fields[3])
            return None if mac in (None, "00:00:00:00:00:00") else mac
    return None


def _read_table(path: Path) -> str:
    """Bytes, decoded with replacement (#260). An interface name is any
    bytes but `/` and whitespace, so `read_text` could raise `ValueError`
    on one that is not UTF-8, and a traceback out of a preflight is not a
    refusal. Both tables go through the same decoding, so a replaced byte in
    a name still matches itself across the two files."""
    return path.read_bytes().decode("utf-8", "replace")


def _nudge(ip: str) -> None:
    """Make the kernel resolve the gateway: one empty datagram to the discard
    port. Nothing listens and nothing answers; the ARP exchange is the whole
    effect."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.sendto(b"", (ip, 9))


def gateway_mac(
    route: Path = ROUTE,
    arp: Path = ARP,
    nudge: Callable[[str], None] | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    """The default gateway's MAC, or `GatewayUnknown` saying what was missing.

    Every external surface is a parameter, so the unit tests never read this
    machine's tables or put a packet on its network. `nudge` is resolved per
    call rather than bound as a default: a default binds at definition time,
    which is what the suite's stub of `_nudge` could not reach (Phase 14
    review, round 2).
    """
    send = nudge if nudge is not None else _nudge
    try:
        route_text = _read_table(route)
    except OSError as exc:
        raise GatewayUnknown(f"{route} cannot be read: {exc}") from exc
    found = default_gateway(route_text)
    if found is None:
        raise GatewayUnknown("this machine has no IPv4 default route")
    iface, ip = found

    def read_arp() -> str | None:
        try:
            return mac_for(ip, _read_table(arp), iface)
        except OSError as exc:
            raise GatewayUnknown(f"{arp} cannot be read: {exc}") from exc
        except PinnedEntry as exc:
            # Exit 2, not 3: nothing about a pinned entry changes between
            # retries, and twelve refusals landing in start-limit-hit would
            # hide the one line that says what to do (review, round 2).
            raise GatewayPinned(str(exc)) from exc

    mac = read_arp()
    if mac is not None:
        return mac
    # A refused send is itself evidence about the network; the table is
    # still asked again below, in case it filled meanwhile.
    with contextlib.suppress(OSError):
        send(ip)
    deadline = clock() + RESOLVE_WAIT_S
    while True:
        mac = read_arp()
        if mac is not None:
            return mac
        if clock() >= deadline:
            raise GatewayUnknown(
                f"the default gateway {ip} has no entry in the ARP table for "
                f"{iface}, so this network cannot be identified"
            )
        sleep(_POLL_S)
