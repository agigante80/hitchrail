"""One process table snapshot, and the queries the engine asks of it.

The `ps` invocation and its column order were verified against procps-ng 4.0.4
on this machine before the parser was written. Everything here drives literal
text or a fake runner, so no test reads the real process table.
"""

from __future__ import annotations

import subprocess

import pytest

from hitchrail.procs import Proc, ProcTable, parse_ps, snapshot

# Real shape, five columns, `args` last and unbounded.
TABLE = """\
    1     0 11108 55078 /sbin/init splash
  100     1  2048  1200 /usr/bin/claude --remote-control
  101   100  1024   900 /usr/bin/node /opt/helper.js --flag "a b"
  102   100   512   800 sleep 30
  200     1  4096  4000 /usr/bin/unrelated
"""


class FakeRunner:
    def __init__(self, stdout: str = "", rc: int = 0) -> None:
        self.calls: list[list[str]] = []
        self._stdout, self._rc = stdout, rc

    def __call__(self, argv: list[str]) -> subprocess.CompletedProcess[str]:
        self.calls.append(argv)
        return subprocess.CompletedProcess(argv, self._rc, self._stdout, "")


# -- parsing ---------------------------------------------------------------


def test_a_well_formed_table_parses() -> None:
    procs = parse_ps(TABLE)
    assert len(procs) == 5
    assert procs[0] == Proc(
        pid=1, ppid=0, rss_kb=11108, etime_s=55078, args="/sbin/init splash"
    )


def test_args_containing_spaces_and_quotes_survive_intact() -> None:
    """`args` is the last column and is split off with maxsplit, not tokenised.

    A command line holds spaces and quotes, and losing them would break the
    marker match that the whole state derivation depends on.
    """
    procs = {p.pid: p for p in parse_ps(TABLE)}
    assert procs[101].args == '/usr/bin/node /opt/helper.js --flag "a b"'


@pytest.mark.parametrize(
    "line",
    [
        "notapid 0 1 1 cmd",
        "1 notappid 1 1 cmd",
        "1 0 1 1",  # no args column at all
        "",
        "   ",
        "1 0 1",
    ],
)
def test_a_malformed_row_is_skipped_and_the_others_survive(line: str) -> None:
    procs = parse_ps(TABLE + line + "\n")
    assert len(procs) == 5


def test_an_empty_table_parses_to_nothing() -> None:
    assert parse_ps("") == []


# -- the snapshot ----------------------------------------------------------


def test_snapshot_issues_one_call_with_the_verified_columns() -> None:
    runner = FakeRunner(TABLE)
    snapshot(runner)
    assert runner.calls == [["ps", "-eo", "pid,ppid,rss,etimes,args", "--no-headers"]]


def test_a_failed_ps_is_an_empty_table_rather_than_an_exception() -> None:
    """One bad call must not 500 the whole listing."""
    assert snapshot(FakeRunner("", rc=1)).procs == []


def test_an_empty_table_is_distinguishable_from_a_failure() -> None:
    """Documented by test, because collapsing the two is a guard failing open.

    "We could not look" rendered as "nothing is running" is exactly what
    control 7 forbids, and the two paths are one refactor away from merging.
    """
    failed = snapshot(FakeRunner("", rc=1))
    idle = snapshot(FakeRunner("", rc=0))
    assert failed.procs == idle.procs == []
    assert failed.ok is False
    assert idle.ok is True


# -- the queries -----------------------------------------------------------


def test_children_are_direct_only() -> None:
    table = ProcTable(parse_ps(TABLE))
    assert {p.pid for p in table.children(100)} == {101, 102}
    assert table.children(999) == []


def test_descendants_walk_the_whole_subtree() -> None:
    table = ProcTable(parse_ps(TABLE))
    assert {p.pid for p in table.descendants(1)} == {100, 101, 102, 200}


def test_a_cyclic_table_terminates() -> None:
    """Named regression. `ps` reads a table changing under it, and pid reuse
    can produce a row whose ppid points back into its own subtree. An unguarded
    walk spins forever, and it does it inside an HTTP request.

    A hang fails this by timeout; the set assertion is what makes it precise.
    """
    cyclic = parse_ps("  2   3  10  10 a\n  3   2  10  10 b\n")
    table = ProcTable(cyclic)
    assert {p.pid for p in table.descendants(2)} == {3}
    assert {p.pid for p in table.descendants(3)} == {2}


def test_a_process_that_is_its_own_parent_terminates() -> None:
    table = ProcTable(parse_ps("  5   5  10  10 self\n"))
    assert table.descendants(5) == []


def test_tree_rss_sums_the_subtree_in_megabytes() -> None:
    table = ProcTable(parse_ps(TABLE))
    # 2048 + 1024 + 512 kB, floor divided.
    assert table.tree_rss_mb(100) == (2048 + 1024 + 512) // 1024


def test_tree_rss_of_an_unknown_pid_is_zero() -> None:
    assert ProcTable(parse_ps(TABLE)).tree_rss_mb(999) == 0


def test_matching_finds_every_process_carrying_the_marker() -> None:
    table = ProcTable(parse_ps(TABLE))
    assert [p.pid for p in table.matching("--remote-control")] == [100]


def test_first_matching_in_tree_checks_the_root_itself() -> None:
    table = ProcTable(parse_ps(TABLE))
    found = table.first_matching_in_tree(100, "--remote-control")
    assert found is not None and found.pid == 100


def test_first_matching_in_tree_is_none_when_absent() -> None:
    """`None`, never a falsy Proc: a truthy type with empty fields is how a
    "not found" becomes a pid of 0 somewhere downstream."""
    assert ProcTable(parse_ps(TABLE)).first_matching_in_tree(200, "--remote-control") is None


def test_first_matching_in_tree_finds_a_descendant() -> None:
    table = ProcTable(parse_ps(TABLE))
    found = table.first_matching_in_tree(1, "helper.js")
    assert found is not None and found.pid == 101
