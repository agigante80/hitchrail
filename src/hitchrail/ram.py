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


def _field_mb(meminfo_text: str, field_name: str) -> int:
    """One field from `/proc/meminfo`, in megabytes, or `ValueError`.

    Shared by `available_mb` and `total_mb` so the two cannot drift in how
    strictly they read the file. The unit assertion below is the reason that
    matters: it was written for `MemAvailable` and is worth exactly as much to
    `MemTotal`, and a second hand rolled copy is where it would be dropped.
    """
    for line in meminfo_text.splitlines():
        field, _, rest = line.partition(":")
        if field.strip() != field_name:
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
    raise ValueError(f"{field_name} is missing or unreadable in /proc/meminfo")


def total_mb(meminfo_text: str) -> int:
    """Megabytes the machine has, from `MemTotal`.

    Only ever used to turn `available_mb` into a proportion for the interface.
    Nothing decides anything on it: the memory guard reads what is OBTAINABLE,
    and a total tells you nothing about that on a machine whose cache is full.

    Refuses the same way `available_mb` does, and for a sharper reason. A total
    guessed as zero renders a full bar on an empty machine, which is the exact
    opposite of the truth at the moment somebody is deciding whether to start
    another session.
    """
    return _field_mb(meminfo_text, "MemTotal")


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
    return _field_mb(meminfo_text, "MemAvailable")


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


# -- #243: what bounds one process ------------------------------------------

PROC_PATH = Path("/proc")
CGROUP_ROOT = Path("/sys/fs/cgroup")
_BYTES_PER_MB = 1024 * 1024
# How long the engine may reuse one ceiling reading for a pid. See the cost
# paragraph on `memory_ceiling_mb`.
CEILING_TTL_S = 30.0


def memory_ceiling_mb(
    pid: int, *, proc: Path = PROC_PATH, cgroup_root: Path = CGROUP_ROOT
) -> int | None:
    """The tightest memory ceiling on a process, or `None` when nothing bounds
    it that this can see.

    Read from the process's cgroup and every ancestor up to the root: the
    smallest finite `memory.max` or `memory.high` on the way. **The ancestry
    and not the leaf**, because #172 measured that cgroups are inherited
    across fork, so a session's pid can sit in the scope of the shell that
    started the tmux server, with `max` on its own line and the real limit on
    a slice above it. A reader of the leaf would be wrong in the direction of
    reassurance. `memory.high` counts: it throttles rather than kills, it is
    what `MemoryHigh=` sets, and it is what the machine that reported #90 had
    set; a reader of `max` alone would have said "no limit" there.

    Unknown is `None` and never a number: no `0::` line (cgroup v1, or a pid
    that exited between the table and this read), a path that leaves the
    root, an unreadable file. Every case above is ordinary.

    **Cost, measured rather than guessed, on the development machine with a
    five level ancestry: 665 microseconds per call**, ten sysfs reads. Fifty
    running rows would add 35 ms to every listing, which is the class of per
    row cost the design refuses on the route the page polls hardest, so the
    engine caches the answer per pid for `CEILING_TTL_S` rather than calling
    this per listing. A limit changed with `systemctl set-property` shows up
    within that window, and a pid reused inside it is a different process
    whose ceiling is read afresh on the next expiry, which is the same bound
    the attention overlay accepts for the same reason. The first measurement
    on this machine also found an 8 GiB `memory.high` that a walk of
    `memory.max` alone had reported as no limit.

    Linux and cgroup v2 only, which is the position the module already takes
    for `/proc/meminfo`; the unified `0::` line is the v2 signature.
    """
    try:
        lines = (proc / str(pid) / "cgroup").read_text().splitlines()
    except OSError:
        return None
    unified = next((line[3:] for line in lines if line.startswith("0::")), None)
    if unified is None:
        return None
    leaf = (cgroup_root / unified.lstrip("/")).resolve()
    root = cgroup_root.resolve()
    if leaf != root and root not in leaf.parents:
        return None
    ceiling: int | None = None
    node = leaf
    while node != root:
        for name in ("memory.max", "memory.high"):
            value = _limit_bytes(node / name)
            if value is not None and (ceiling is None or value < ceiling):
                ceiling = value
        node = node.parent
    return None if ceiling is None else ceiling // _BYTES_PER_MB


def _limit_bytes(path: Path) -> int | None:
    """`max` is no limit; anything else is bytes. A missing or unreadable file
    is treated as no limit at that level, which is what the kernel means when
    it does not expose one."""
    try:
        text = path.read_text().strip()
    except OSError:
        return None
    if text == "max":
        return None
    try:
        return int(text)
    except ValueError:
        return None
