"""#297. One plugin run at a time, a record a phone can read at any point,
and every change to it published.

The operation is injected, so nothing here runs a subprocess. What is under
test is the in flight marker, the record, what is published, and that the
marker cannot outlive a run however the run ends.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

import pytest

from hitchrail.claude_ipc import PluginOutcome, PluginsFailed
from hitchrail.plugin_runs import EVENT_KIND, PluginRuns, RunInFlight

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


def runs(published: Published) -> PluginRuns:
    return PluginRuns(publish=published, clock=lambda: 1000.0)


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
    assert final["counts"] == {"updated": 1, "failed": 0, "skipped": 1}
    assert final["outcomes"][1] == {
        "plugin": "adapt@kit",
        "scope": "local",
        "result": "skipped",
        "detail": None,
        "approved_command": None,
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

    def fake_runner(withhold: tuple[str, ...]) -> str:
        seen["withhold"] = tuple(withhold)
        return "runner"

    def fake_update(binary: str, *, run: object, report: Report) -> list[PluginOutcome]:
        seen["binary"], seen["run"] = binary, run
        return []

    monkeypatch.setattr(claude_ipc, "plugin_runner", fake_runner)
    monkeypatch.setattr(claude_ipc, "update_plugins", fake_update)
    operation_for("/opt/agent")(lambda _o: None)
    assert seen == {"withhold": (TOKEN_ENV,), "binary": "/opt/agent", "run": "runner"}
