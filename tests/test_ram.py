"""The memory guard: a reading, and a decision that is pure given its inputs.

Split that way on purpose. `guard` is arithmetic over four integers, so every
boundary is testable with no filesystem at all, and `read_meminfo` takes its
path so nothing in this tier touches /proc.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hitchrail.ram import (
    Verdict,
    available_mb,
    guard,
    memory_ceiling_mb,
    read_meminfo,
    total_mb,
)

# A real fragment, copied from this machine's /proc/meminfo, so the parser is
# tested against the format it will actually meet rather than an idealised one.
MEMINFO = """\
MemTotal:       32729384 kB
MemFree:         6316728 kB
MemAvailable:   17541964 kB
Buffers:          812344 kB
Cached:         10221492 kB
"""

HARD = 1536
SOFT = 3072
NEED = 1536


# -- reading ---------------------------------------------------------------


def test_available_mb_converts_from_kb() -> None:
    assert available_mb(MEMINFO) == 17541964 // 1024


def test_available_mb_reads_memavailable_not_memfree() -> None:
    """Named regression: they are different numbers and the gap is large.

    MemFree excludes the page cache, which the kernel reclaims on demand, so on
    a healthy machine it is small. A guard built on it refuses to start a
    session that would have run fine. MemAvailable is the kernel's own estimate
    of what is obtainable without swapping, which is the question being asked.
    Here MemFree is 6.3 GB and MemAvailable is 17.5 GB.
    """
    assert available_mb(MEMINFO) != 6316728 // 1024


@pytest.mark.parametrize(
    "text",
    ["", "MemTotal: 32729384 kB\n", "MemAvailable:\n", "MemAvailable: notanumber kB\n"],
)
def test_a_missing_or_unreadable_memavailable_is_not_silently_zero(text: str) -> None:
    """Zero is indistinguishable from a machine truly out of memory.

    Returning 0 here would make `guard` a permanent HARD, so every start would
    be refused with a message about memory pressure on a machine that has
    plenty. Refusing to answer is honest; guessing zero is a guard failing in
    the direction that looks safe and is simply wrong.
    """
    with pytest.raises(ValueError, match="MemAvailable"):
        available_mb(text)


def test_read_meminfo_reads_the_injected_path(tmp_path: Path) -> None:
    """Proves the seam exists, and that this tier never reaches /proc."""
    fake = tmp_path / "meminfo"
    fake.write_text(MEMINFO)
    assert "MemAvailable" in read_meminfo(fake)


# -- the decision ----------------------------------------------------------


def test_no_memory_at_all_is_hard() -> None:
    """The exit criterion, asserted directly.

    A machine reporting nothing available is where starting another agent is
    most likely to invoke the OOM killer.
    """
    assert guard(0, NEED, HARD, SOFT) is Verdict.HARD


@pytest.mark.parametrize(
    ("available", "expected"),
    [
        # The decision is on what is LEFT after starting, not what is free now,
        # so every boundary below is need_mb above the floor it names.
        (NEED + HARD - 1, Verdict.HARD),
        (NEED + HARD, Verdict.SOFT),
        (NEED + HARD + 1, Verdict.SOFT),
        (NEED + SOFT - 1, Verdict.SOFT),
        (NEED + SOFT, Verdict.OK),
        (NEED + SOFT + 1, Verdict.OK),
    ],
    ids=["below-hard", "at-hard", "above-hard", "below-soft", "at-soft", "above-soft"],
)
def test_the_boundaries_are_pinned_at_the_exact_value(
    available: int, expected: Verdict
) -> None:
    """Each comparison is a `<` versus `<=` decision, pinned rather than approximated.

    An off by one here does not fail loudly. It silently moves the threshold by
    one megabyte and the guard still looks like it works, which is why the
    cases sit ON the boundary rather than near it.
    """
    assert guard(available, NEED, HARD, SOFT) is expected


def test_plenty_of_memory_is_ok() -> None:
    assert guard(16000, NEED, HARD, SOFT) is Verdict.OK


def test_an_inverted_pair_of_floors_is_the_configs_problem() -> None:
    """`Config` already refuses soft < hard, so `guard` may assume the order.

    Asserted rather than left implicit: if that refusal is ever removed, this
    documents that `guard` will silently lose its middle step rather than
    detect it.
    """
    # soft below hard: the SOFT band is unreachable and everything under the
    # hard floor is still refused, which is the safe direction to fail.
    assert guard(NEED + 100, NEED, HARD, 10) is Verdict.HARD


def test_verdict_serialises_as_its_name() -> None:
    """The API contract must not depend on enum ordering."""
    assert Verdict.OK.value == "ok"
    assert Verdict.SOFT.value == "soft"
    assert Verdict.HARD.value == "hard"
    assert f"{Verdict.HARD}" == "hard"


@pytest.mark.parametrize(
    "text",
    [
        "MemAvailable: 2097152 B\n",
        "MemAvailable: 2097152\n",
        "MemAvailable: 2097152 mB\n",
        "MemAvailable: 2097152 kB extra\n",
    ],
)
def test_a_value_in_the_wrong_unit_is_refused(text: str) -> None:
    """Belt and braces, and the failure direction is why it is worth a line.

    A value in bytes read as kB over reports memory by 1024x, which approves a
    start on a machine that is already exhausted. The kernel has always written
    kB, so this should never fire; if it ever does, refusing is the behaviour
    this module argues for everywhere else.
    """
    with pytest.raises(ValueError, match="MemAvailable"):
        available_mb(text)


def test_guard_does_not_shadow_the_parser() -> None:
    """The parameter was named `available_mb`, same as the module function.

    Harmless while `guard` does not call it, and a trap for the next edit that
    wants to. Asserted by calling both in one expression.
    """
    assert guard(available_mb(MEMINFO), NEED, HARD, SOFT) is Verdict.OK


# -- #64: the total, for the interface rather than for the guard ------------

REAL_MEMINFO = """\
MemTotal:       32791244 kB
MemFree:         1234567 kB
MemAvailable:   24608000 kB
Buffers:          123456 kB
"""


def test_total_mb_reads_memtotal() -> None:
    assert total_mb(REAL_MEMINFO) == 32022


def test_total_and_available_come_from_the_same_text() -> None:
    """One read, so the figure and the proportion drawn from it describe the
    same instant. `total >= available` on any real file."""
    assert total_mb(REAL_MEMINFO) >= available_mb(REAL_MEMINFO)


@pytest.mark.parametrize(
    "text",
    [
        "MemAvailable:   24608000 kB\n",  # the field is absent
        "MemTotal:\n",  # present and empty
        "MemTotal:       notanumber kB\n",  # present and not a number
        "MemTotal:       32791244 MB\n",  # the wrong unit
        "MemTotal:       32791244\n",  # no unit at all
        "",  # an empty file
    ],
)
def test_an_unreadable_total_refuses_rather_than_guessing(text: str) -> None:
    """Same refusal as `available_mb`, and for a sharper reason: a total
    guessed as zero renders a full bar on an empty machine, which is the exact
    opposite of the truth at the moment somebody is deciding to start one."""
    with pytest.raises(ValueError, match="MemTotal"):
        total_mb(text)


def test_the_two_readers_share_one_parser() -> None:
    """Not style. The unit assertion was written for `MemAvailable` and is
    worth exactly as much to `MemTotal`; a second hand rolled copy is where it
    would be dropped. Asserted by behaviour: both reject the wrong unit."""
    with pytest.raises(ValueError):
        available_mb("MemAvailable: 100 MB\n")
    with pytest.raises(ValueError):
        total_mb("MemTotal: 100 MB\n")


# -- #243: what bounds a session, read from its cgroup ancestry --------------

# The shape captured on the development machine on 2026-09-12: cgroup v2, one
# `0::` line, a tmux spawn scope five levels under the root, `memory.max`
# reading `max` at every level and no file at the root at all. The fixture
# below is built from that, never from a description of it.
CGROUP_LINE = (
    "0::/user.slice/user-1000.slice/user@1000.service/app.slice/"
    "tmux-spawn-26b41d0e-4470-4829-af97-8bced67d713e.scope\n"
)
LEAF = "user.slice/user-1000.slice/user@1000.service/app.slice/tmux-spawn-26b41d0e.scope"


def _tree(
    tmp_path: Path, *, limits: dict[str, str], high: dict[str, str] | None = None
) -> tuple[Path, Path]:
    """A fake `/proc` and `/sys/fs/cgroup` for pid 4242, with `memory.max`
    (and optionally `memory.high`) written at the named levels."""
    proc = tmp_path / "proc"
    (proc / "4242").mkdir(parents=True)
    (proc / "4242" / "cgroup").write_text(
        CGROUP_LINE.replace("26b41d0e-4470-4829-af97-8bced67d713e", "26b41d0e")
    )
    root = tmp_path / "cgroup"
    (root / LEAF).mkdir(parents=True)
    for rel, value in limits.items():
        (root / rel / "memory.max").write_text(value + "\n")
    for rel, value in (high or {}).items():
        (root / rel / "memory.high").write_text(value + "\n")
    return proc, root


GIB = 1024**3


def test_the_tightest_ceiling_along_the_ancestry_wins(tmp_path: Path) -> None:
    """#172 measured that cgroups are inherited across fork, so a session's pid
    can sit in the scope of the shell that started the tmux server. The leaf's
    own `memory.max` is then `max` while a parent slice carries the limit that
    actually bounds it, and a reader that reported the leaf would be wrong in
    the direction of reassurance."""
    proc, root = _tree(
        tmp_path,
        limits={
            LEAF: "max",
            "user.slice/user-1000.slice": str(4 * GIB),
            "user.slice": str(8 * GIB),
        },
    )
    assert memory_ceiling_mb(4242, proc=proc, cgroup_root=root) == 4096


def test_two_finite_levels_give_the_smaller(tmp_path: Path) -> None:
    proc, root = _tree(
        tmp_path,
        limits={LEAF: str(2 * GIB), "user.slice/user-1000.slice": str(4 * GIB)},
    )
    assert memory_ceiling_mb(4242, proc=proc, cgroup_root=root) == 2048


def test_memory_high_counts_as_a_ceiling(tmp_path: Path) -> None:
    """`MemoryHigh=` is what the reporting machine set, and it lands in
    `memory.high`, not `memory.max`. It throttles rather than kills, and it is
    still the number the process is held to; a reader of `max` alone would
    have said "no limit" on the machine that motivated this."""
    proc, root = _tree(
        tmp_path,
        limits={LEAF: "max"},
        high={"user.slice/user-1000.slice/user@1000.service/app.slice": str(6 * GIB)},
    )
    assert memory_ceiling_mb(4242, proc=proc, cgroup_root=root) == 6144


def test_max_at_every_level_is_no_ceiling(tmp_path: Path) -> None:
    proc, root = _tree(tmp_path, limits={LEAF: "max", "user.slice": "max"})
    assert memory_ceiling_mb(4242, proc=proc, cgroup_root=root) is None


def test_an_unreadable_cgroup_is_no_ceiling_and_no_error(tmp_path: Path) -> None:
    """Unknown is `None`, never a number and never an exception: this runs
    per row on the listing route, and a pid that exited between the table
    and this read is the ordinary case."""
    proc = tmp_path / "proc"
    proc.mkdir()
    assert memory_ceiling_mb(4242, proc=proc, cgroup_root=tmp_path / "cgroup") is None


def test_cgroup_v1_is_no_ceiling_rather_than_a_parse_of_the_wrong_file(tmp_path: Path) -> None:
    """v1 lists one line per controller (`4:memory:/...`) and has no `0::`
    unified line. The reader declines rather than reading a controller path it
    does not understand."""
    proc = tmp_path / "proc"
    (proc / "4242").mkdir(parents=True)
    (proc / "4242" / "cgroup").write_text("4:memory:/user.slice\n1:name=systemd:/user.slice\n")
    root = tmp_path / "cgroup"
    (root / "user.slice").mkdir(parents=True)
    (root / "user.slice" / "memory.max").write_text(str(GIB) + "\n")
    assert memory_ceiling_mb(4242, proc=proc, cgroup_root=root) is None


def test_the_leaf_path_cannot_escape_the_cgroup_root(tmp_path: Path) -> None:
    """The path comes from a file a process can influence in principle. A
    `..` in it must not walk the reader above the root it was given."""
    proc = tmp_path / "proc"
    (proc / "4242").mkdir(parents=True)
    (proc / "4242" / "cgroup").write_text("0::/../../etc\n")
    assert memory_ceiling_mb(4242, proc=proc, cgroup_root=tmp_path / "cgroup") is None
