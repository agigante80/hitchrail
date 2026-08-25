"""The memory guard: a reading, and a decision that is pure given its inputs.

Split that way on purpose. `guard` is arithmetic over four integers, so every
boundary is testable with no filesystem at all, and `read_meminfo` takes its
path so nothing in this tier touches /proc.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hitchrail.ram import Verdict, available_mb, guard, read_meminfo

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
