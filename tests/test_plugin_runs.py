"""#297. One plugin run at a time, a record a phone can read at any point,
and every change to it published.

The operation is injected, so nothing here runs a subprocess. What is under
test is the in flight marker, the record, what is published, and that the
marker cannot outlive a run however the run ends.
"""

from __future__ import annotations

import itertools
import re
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import get_args

import pytest

from hitchrail import plugin_runs as plugin_runs_module
from hitchrail.claude_ipc import PluginFailure, PluginOutcome, PluginResult, PluginsFailed
from hitchrail.plugin_runs import EVENT_KIND, PluginRuns, RunInFlight, read_boot_id

Report = Callable[[PluginOutcome], None]


def outcome(plugin: str, result: str = "updated", scope: str = "user") -> PluginOutcome:
    return PluginOutcome(plugin, scope, result)  # type: ignore[arg-type]


class Held:
    """An operation that reports what it is given, one outcome per `release`,
    so a test can look at the record between two outcomes."""

    def __init__(self, *outcomes: PluginOutcome, fail: PluginsFailed | None = None) -> None:
        self.outcomes = outcomes
        self.fail = fail
        self.gates = [threading.Event() for _ in range(len(outcomes) + 1)]
        self.calls = 0

    def __call__(self, report: Report) -> list[PluginOutcome]:
        self.calls += 1
        for i, o in enumerate(self.outcomes):
            assert self.gates[i].wait(5), "the test never released this outcome"
            report(o)
        assert self.gates[-1].wait(5), "the test never released the end"
        if self.fail is not None:
            raise self.fail
        return list(self.outcomes)

    def release(self, n: int) -> None:
        self.gates[n].set()


class Published:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []
        self.changed = threading.Condition()

    def __call__(self, event: dict[str, object]) -> None:
        with self.changed:
            self.events.append(event)
            self.changed.notify_all()

    def wait_for(self, n: int) -> None:
        with self.changed:
            assert self.changed.wait_for(lambda: len(self.events) >= n, 5), self.events


# Every instance a later start on the boot clock than the one before, as
# successive server processes are; the boot id is fixed, so the real
# /proc is never read here.
_boot_clock = itertools.count(1_000_000, 1_000)


def runs(published: Published) -> PluginRuns:
    return PluginRuns(
        publish=published,
        clock=lambda: 1000.0,
        boot=lambda: "test-boot",
        boot_clock=lambda: next(_boot_clock),
    )


def test_before_any_run_the_record_says_idle() -> None:
    record = runs(Published()).snapshot()
    assert record["state"] == "idle"
    assert record["outcomes"] == []
    assert record["code"] is None


def test_a_run_is_recorded_and_published_as_each_plugin_finishes() -> None:
    published = Published()
    plugin_runs = runs(published)
    held = Held(outcome("a@m"), outcome("adapt@kit", "skipped", "local"))
    thread = plugin_runs.start(held)

    published.wait_for(1)
    assert plugin_runs.snapshot()["state"] == "running"
    assert plugin_runs.snapshot()["outcomes"] == []

    held.release(0)
    published.wait_for(2)
    middle = plugin_runs.snapshot()
    assert middle["state"] == "running"
    assert [o["plugin"] for o in middle["outcomes"]] == ["a@m"]

    held.release(1)
    held.release(2)
    thread.join(5)
    final = plugin_runs.snapshot()
    assert final["state"] == "done"
    assert final["counts"] == {
        "updated": 1,
        "current": 0,
        "failed": 0,
        "skipped": 1,
        "abandoned": 0,
    }
    assert final["outcomes"][1] == {
        "plugin": "adapt@kit",
        "scope": "local",
        "result": "skipped",
        "detail": None,
        "approved_command": None,
        "from_version": None,
        "to_version": None,
    }
    # One event on start, one per outcome, one at the end, each the whole
    # record, so a page renders every event the same way it renders the GET.
    assert [e["run"]["state"] for e in published.events] == [  # type: ignore[index]
        "running",
        "running",
        "running",
        "done",
    ]
    assert {e["kind"] for e in published.events} == {EVENT_KIND}


def test_the_returned_outcomes_are_the_final_record() -> None:
    """#311. What is reported as it happens is provisional; the list the
    operation returns, after the second listing, is what the finished record
    holds and what `counts` counts."""
    published = Published()
    plugin_runs = runs(published)

    def operation(report: Report) -> list[PluginOutcome]:
        report(outcome("a@m"))
        report(outcome("b@m"))
        return [
            PluginOutcome("a@m", "user", "updated", from_version="1.0.0", to_version="2.0.0"),
            PluginOutcome("b@m", "user", "current"),
        ]

    plugin_runs.start(operation).join(5)
    final = plugin_runs.snapshot()
    assert [o["result"] for o in final["outcomes"]] == ["updated", "current"]
    assert final["outcomes"][0]["from_version"] == "1.0.0"
    assert final["outcomes"][0]["to_version"] == "2.0.0"
    assert final["counts"] is not None
    assert (final["counts"]["updated"], final["counts"]["current"]) == (1, 1)


def test_a_second_start_while_one_runs_is_refused_and_changes_nothing() -> None:
    published = Published()
    plugin_runs = runs(published)
    held = Held(outcome("a@m"))
    thread = plugin_runs.start(held)
    second = Held()
    with pytest.raises(RunInFlight):
        plugin_runs.start(second)
    assert second.calls == 0
    held.release(0)
    held.release(1)
    thread.join(5)
    assert plugin_runs.snapshot()["state"] == "done"


def test_a_failed_operation_records_its_code_and_no_count() -> None:
    """Fails if 1 in the plan: a failure is never shown as a count."""
    published = Published()
    plugin_runs = runs(published)
    held = Held(fail=PluginsFailed("plugins_unreadable", "could not be understood"))
    thread = plugin_runs.start(held)
    held.release(0)
    thread.join(5)
    record = plugin_runs.snapshot()
    assert record["state"] == "failed"
    assert record["code"] == "plugins_unreadable"
    assert record["message"] == "could not be understood"
    assert record["counts"] is None


def test_a_thread_that_cannot_start_leaves_the_run_failed_not_stuck_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#307, premortem 2 in the plan. `Thread.start` can raise on its own,
    `RuntimeError` on a machine out of threads being the documented case, and
    `_run`'s `finally` never fires when `_run` itself never starts. Without
    the fix, `running` sticks and every later request reads
    `update_in_flight` until a restart; this asserts the marker clears and
    the outcome is published instead.
    """
    published = Published()
    plugin_runs = runs(published)

    def cannot_start(self: threading.Thread) -> None:
        raise RuntimeError("can't start new thread")

    monkeypatch.setattr(threading.Thread, "start", cannot_start)
    with pytest.raises(RuntimeError):
        plugin_runs.start(Held())

    record = plugin_runs.snapshot()
    assert record["state"] == "failed"
    assert record["code"] == "internal_error"
    assert published.events[-1]["run"] == record

    # Restore the real `Thread.start` before proving the marker does not
    # stick: this run's own thread must actually run to complete.
    monkeypatch.undo()
    again = Held()
    thread = plugin_runs.start(again)
    again.release(0)
    thread.join(5)
    assert plugin_runs.snapshot()["state"] == "done"


def test_the_marker_is_cleared_when_the_operation_raises_anything() -> None:
    """Fails if 2 in the plan: a marker that outlives its run refuses every
    later update until a restart."""
    published = Published()
    plugin_runs = runs(published)

    def explodes(_report: Report) -> list[PluginOutcome]:
        raise RuntimeError("a bug, not a vendor refusal")

    plugin_runs.start(explodes).join(5)
    record = plugin_runs.snapshot()
    assert record["state"] == "failed"
    assert record["code"] == "internal_error"
    # And the next run is accepted.
    again = Held()
    thread = plugin_runs.start(again)
    again.release(0)
    thread.join(5)
    assert plugin_runs.snapshot()["state"] == "done"


def test_a_later_run_replaces_the_earlier_record() -> None:
    published = Published()
    plugin_runs = runs(published)
    first = Held(outcome("a@m"))
    t = plugin_runs.start(first)
    first.release(0)
    first.release(1)
    t.join(5)
    second = Held()
    t = plugin_runs.start(second)
    assert plugin_runs.snapshot()["outcomes"] == []
    second.release(0)
    t.join(5)


def test_the_snapshot_is_a_copy() -> None:
    """The route serialises it on another thread while the run appends."""
    published = Published()
    plugin_runs = runs(published)
    held = Held(outcome("a@m"))
    t = plugin_runs.start(held)
    before = plugin_runs.snapshot()
    held.release(0)
    held.release(1)
    t.join(5)
    assert before["outcomes"] == []


def test_the_run_is_a_daemon_thread() -> None:
    """Shutdown must not wait on a vendor call bounded at five minutes: the
    unit's stop timeout is shorter, and the kill that follows would take the
    server down harder than leaving the run behind does."""
    held = Held()
    thread = runs(Published()).start(held)
    assert thread.daemon
    held.release(0)
    thread.join(5)


def test_the_default_operation_is_the_quarantined_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """Built from the configured binary, withholding the token."""
    from hitchrail import claude_ipc
    from hitchrail.config import TOKEN_ENV
    from hitchrail.plugin_runs import operation_for

    seen: dict[str, object] = {}

    def fake_runner(withhold: tuple[str, ...], *, handle: object = None) -> str:
        seen["withhold"] = tuple(withhold)
        seen["handle"] = handle
        return "runner"

    def fake_update(binary: str, *, run: object, report: Report) -> list[PluginOutcome]:
        seen["binary"], seen["run"] = binary, run
        return []

    monkeypatch.setattr(claude_ipc, "plugin_runner", fake_runner)
    monkeypatch.setattr(claude_ipc, "update_plugins", fake_update)
    operation_for("/opt/agent")(lambda _o: None)
    assert seen == {
        "withhold": (TOKEN_ENV,),
        "handle": None,
        "binary": "/opt/agent",
        "run": "runner",
    }


def test_operation_for_threads_a_handle_into_the_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#361. `PluginRuns.handle` has to reach `plugin_runner` unchanged, or
    the server's lifespan kills nothing: this is the seam the wiring goes
    through, one call outside `create_app`'s own machinery."""
    from hitchrail import claude_ipc
    from hitchrail.plugin_runs import operation_for

    seen: dict[str, object] = {}
    sentinel = claude_ipc.RunningChild()

    def fake_runner(withhold: tuple[str, ...], *, handle: object = None) -> str:
        seen["handle"] = handle
        return "runner"

    monkeypatch.setattr(claude_ipc, "plugin_runner", fake_runner)
    monkeypatch.setattr(claude_ipc, "update_plugins", lambda *a, **k: [])
    operation_for("/opt/agent", handle=sentinel)(lambda _o: None)
    assert seen["handle"] is sentinel


def test_every_change_carries_a_larger_seq_across_runs() -> None:
    """Round 1 of batch 2's review, the high: a GET answered before the last
    event and delivered after it painted the older record over the newer one
    and left the page on "running". A page can only drop a stale record if it
    can tell which is newer, and a run's state cannot say that across two
    runs; a counter that only goes up can."""
    published = Published()
    plugin_runs = runs(published)
    assert plugin_runs.snapshot()["seq"] == 0
    first = Held(outcome("a@m"))
    t = plugin_runs.start(first)
    first.release(0)
    first.release(1)
    t.join(5)
    second = Held()
    t = plugin_runs.start(second)
    second.release(0)
    t.join(5)
    seqs = [e["run"]["seq"] for e in published.events]  # type: ignore[index]
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == len(seqs), "two different records shared a seq"
    assert plugin_runs.snapshot()["seq"] == seqs[-1]


def test_the_epoch_names_the_process_and_holds_for_its_life() -> None:
    """Round 2 of batch 2's review: `seq` restarts with the process, so a
    page compares it only within one epoch. The epoch must therefore stay
    fixed across runs in one process, or every record looks like a restart,
    and differ between two, or a restart looks like nothing happened."""
    published = Published()
    plugin_runs = runs(published)
    before = plugin_runs.snapshot()["epoch"]
    held = Held()
    t = plugin_runs.start(held)
    held.release(0)
    t.join(5)
    epochs = {e["run"]["epoch"] for e in published.events}  # type: ignore[index]
    assert epochs == {before}
    assert runs(Published()).snapshot()["epoch"] != before


def test_the_boot_fields_order_two_processes_and_hold_for_each_life() -> None:
    """#348. The page orders two processes by `boot` and `since_boot_us`, so
    both must stay fixed for one process's life, and a later process of the
    same boot must carry the larger `since_boot_us`."""
    published = Published()
    first = runs(published)
    before = first.snapshot()
    held = Held()
    t = first.start(held)
    held.release(0)
    t.join(5)
    for event in published.events:
        run = event["run"]
        assert run["boot"] == before["boot"]  # type: ignore[index]
        assert run["since_boot_us"] == before["since_boot_us"]  # type: ignore[index]
    later = runs(Published()).snapshot()
    assert later["boot"] == before["boot"]
    assert later["since_boot_us"] > before["since_boot_us"]


def test_the_default_order_survives_the_wall_clock_stepping_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#348. A unit started at boot runs before NTP has synced, so the wall
    clock can step back between two starts. Were the order read from it, the
    new process would look older and the page would drop everything it
    sends. Fails if `since_boot_us` is ever taken from `time.time` or
    `time.time_ns`."""
    wall = iter(range(10**18, 0, -(10**15)))
    monkeypatch.setattr(time, "time", lambda: next(wall) / 1e9)
    monkeypatch.setattr(time, "time_ns", lambda: next(wall))
    older = PluginRuns(publish=Published(), boot=lambda: "b").snapshot()["since_boot_us"]
    deadline = time.monotonic() + 1
    while plugin_runs_module.since_boot_us() <= older and time.monotonic() < deadline:
        pass
    newer = PluginRuns(publish=Published(), boot=lambda: "b").snapshot()["since_boot_us"]
    assert newer > older


def test_the_boot_id_is_the_kernels(tmp_path: Path) -> None:
    boot_id = tmp_path / "boot_id"
    boot_id.write_text("0f3c1a2e-9b7d-4c1e-8a55-3d2f6e7b9c01\n", encoding="ascii")
    assert read_boot_id(boot_id) == "0f3c1a2e-9b7d-4c1e-8a55-3d2f6e7b9c01"


@pytest.mark.parametrize("content", [None, b"", b"\xff\xfe"])
def test_an_unreadable_boot_id_is_a_fresh_token_each_time(
    tmp_path: Path, content: bytes | None
) -> None:
    """Missing, empty or garbled: a random token, never a shared constant.
    A constant would put every process in one "boot" with nothing ordering
    them but the boot clock of whatever machine it is; a fresh token makes
    each process its own boot, which the page orders by arrival."""
    boot_id = tmp_path / "boot_id"
    if content is not None:
        boot_id.write_bytes(content)
    first, second = read_boot_id(boot_id), read_boot_id(boot_id)
    assert first and second and first != second


# -- every reader knows every literal (#370) ---------------------------------

_ROOT = Path(__file__).resolve().parent.parent


def _record_codes() -> set[str]:
    """Every `code` a failed record can carry: the operation's own, plus the
    one this module adds for a defect."""
    return {*get_args(PluginFailure), "internal_error"}


def test_the_page_names_every_failure_code() -> None:
    """#370. `shutting_down` reached the page with no entry, and the fallback
    to the server's message doubled the "so nothing was updated" clause. A
    code the page has no words for, or words for a code that cannot arrive,
    fails here."""
    js = (_ROOT / "src/hitchrail/web/plugins.js").read_text(encoding="utf-8")
    table = re.search(r"const PLUGIN_FAILURES = \{(.*?)\};", js, re.S)
    assert table is not None, "PLUGIN_FAILURES not found in plugins.js"
    keys = set(re.findall(r"^\s*(\w+):", table.group(1), re.M))
    assert keys == _record_codes()


def test_the_api_reference_names_every_failure_code_and_result() -> None:
    """#370. `docs/api.md`'s both ways guard covers HTTP statuses, not record
    codes, so nothing tied this table to the literal."""
    doc = (_ROOT / "docs/api.md").read_text(encoding="utf-8")
    start = doc.index("| Record `code` | When |")
    table = doc[start : doc.index("\n\n", start)]
    assert set(re.findall(r"^\| `(\w+)` \|", table, re.M)) == _record_codes()
    results_line = next(line for line in doc.splitlines() if line.startswith("| `outcomes` |"))
    named = set(re.findall(r"`(\w+)`", results_line.split("`result` one of", 1)[1]))
    assert named == set(get_args(PluginResult))
