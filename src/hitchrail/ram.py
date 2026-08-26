"""Memory readings, and the guard decision that is pure given its inputs.

Two functions rather than one on purpose. `guard` is arithmetic over four
integers, so every boundary is testable without a filesystem; `read_meminfo` is
the only part that touches the machine and takes its path, so a test can hand
it a fixture. Fusing them would make the interesting half untestable without
`/proc`.

Linux only, which is the position `pyproject.toml` already declares: there is
no `/proc/meminfo` on macOS and no equivalent with these semantics.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

MEMINFO_PATH = Path("/proc/meminfo")

# The kernel reports kB. Everything above this module works in MB, because
# that is the unit the operator configures floors in.
_KB_PER_MB = 1024


class Verdict(StrEnum):
    """What the guard decided. A `StrEnum` so the API contract is the NAME.

    Serialising an `IntEnum` would put the ordering in the wire format, and
    inserting a fourth verdict later would then silently change what an old
    client reads.
    """

    OK = "ok"
    SOFT = "soft"
    HARD = "hard"


def read_meminfo(path: Path = MEMINFO_PATH) -> str:
    """The one function here that touches the machine. Injected for tests."""
    return path.read_text()


def available_mb(meminfo_text: str) -> int:
    """Megabytes obtainable without swapping, from `MemAvailable`.

    `MemAvailable`, never `MemFree`. They are different numbers and the gap is
    large: `MemFree` excludes the page cache, which the kernel reclaims on
    demand, so on a healthy machine it is small and a guard built on it refuses
    to start a session that would have run fine. `MemAvailable` is the kernel's
    own estimate of what is obtainable, which is the question being asked.

    Raises `ValueError` when the field is absent or unparseable, rather than
    returning 0. Zero is indistinguishable from a machine truly out of memory,
    so guessing it would turn every start into a refusal citing memory pressure
    on a machine with plenty. A guard that cannot read its input says so.
    """
    for line in meminfo_text.splitlines():
        field, _, rest = line.partition(":")
        if field.strip() != "MemAvailable":
            continue
        parts = rest.split()
        # The unit is asserted rather than assumed. The kernel has always
        # written kB and hardcodes it, so this is belt and braces, but it is
        # one line and the failure direction matters: a value in bytes read as
        # kB over reports memory by 1024x and approves a start on an exhausted
        # machine. This function's whole argument is that it refuses rather
        # than guesses when it cannot read its input.
        if len(parts) != 2 or parts[1] != "kB":
            break
        try:
            return int(parts[0]) // _KB_PER_MB
        except ValueError:
            break
    raise ValueError("MemAvailable is missing or unreadable in /proc/meminfo")


def guard(available: int, need_mb: int, hard_mb: int, soft_mb: int) -> Verdict:
    """Decide against what would be LEFT after starting, not what is free now.

    Starting an agent consumes `need_mb`, so the question is whether the
    machine is still habitable afterwards. Comparing the available figure
    directly against the floors would approve a start that lands exactly on the
    floor and leaves nothing.

    The parameter is `available` rather than `available_mb` deliberately: the
    latter shadows the module level parser of that name, which makes it
    unreachable from this scope and sets a trap for the next edit that wants
    it.

    `Config` already refuses a soft floor below the hard floor, so the order is
    assumed here rather than revalidated. If that refusal is ever removed this
    silently loses its middle step: the SOFT band becomes unreachable and every
    confirmation gate disappears. There is a test saying so.
    """
    remaining = available - need_mb
    if remaining < hard_mb:
        return Verdict.HARD
    if remaining < soft_mb:
        return Verdict.SOFT
    return Verdict.OK
