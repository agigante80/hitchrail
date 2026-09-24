"""One plugin update at a time, and a record of it a phone can read (#297).

The operation itself is `claude_ipc.update_plugins`, and nothing here knows
what a plugin update physically is: this module holds the in flight marker,
the record of the current or last run, and the events that announce each
change to it. It is its own module rather than a part of `engine.py` because
it shares nothing with a session: no project, no tmux, no derivation.

**The record is the whole of what a client needs, on every channel.** The GET
returns it, and every event carries it entire rather than a delta, because
the event stream has no replay: a phone that opens the page or reconnects in
the middle of a run reads the GET, and from then on renders each event the
same way. A delta protocol would need replay to be correct across a
reconnect, and a list of at most a few dozen outcomes does not earn one.
Records do still arrive out of order, so each says which is newer: see
`seq` and `epoch` below.

**Memory only, like the graceful stop overlay.** If Hitchrail restarts
mid run the knowledge is gone and the next request is accepted, which is the
truth about this process. A persisted marker would refuse updates forever on
the strength of a run nobody is performing.

This module is in the engine layer and imports nothing from the web layer.
"""

from __future__ import annotations

import logging
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import asdict
from typing import Literal, TypedDict

from hitchrail import claude_ipc
from hitchrail.claude_ipc import PluginOutcome, PluginsFailed
from hitchrail.config import TOKEN_ENV

logger = logging.getLogger(__name__)

# What the server's stream uses to tell these events from a session's. The
# session payload is the stream's original contract and carries no such key.
EVENT_KIND = "plugins"

Operation = Callable[[Callable[[PluginOutcome], None]], list[PluginOutcome]]
State = Literal["idle", "running", "done", "failed"]


class RunRecord(TypedDict):
    """What `GET /api/plugins/update` returns and every event carries."""

    epoch: str
    seq: int
    state: State
    started_at: float | None
    finished_at: float | None
    outcomes: list[dict[str, str | None]]
    counts: dict[str, int] | None
    code: str | None
    message: str | None


class RunInFlight(Exception):
    """A run is already going; the request changed nothing."""


def operation_for(agent_binary: str) -> Operation:
    """The real operation, withholding the token from every child (#113)."""
    runner = claude_ipc.plugin_runner(withhold=(TOKEN_ENV,))

    def operation(report: Callable[[PluginOutcome], None]) -> list[PluginOutcome]:
        return claude_ipc.update_plugins(agent_binary, run=runner, report=report)

    return operation


class PluginRuns:
    def __init__(
        self,
        publish: Callable[[dict[str, object]], None],
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._publish = publish
        self._clock = clock
        self._lock = threading.Lock()
        self._state: State = "idle"
        self._started_at: float | None = None
        self._finished_at: float | None = None
        self._outcomes: list[PluginOutcome] = []
        self._code: str | None = None
        self._message: str | None = None
        # Bumped under the lock on every change, never reset, so any two
        # records say which is newer even across runs. The page drops a record
        # older than the one it shows: a GET answered before the last event
        # and delivered after it would otherwise repaint "running" over
        # "done", and no later event would come to correct it.
        self._seq = 0
        # Which process's `seq` this is. A restart starts `seq` at 0 again,
        # and a page left open across it held a larger one, so it dropped
        # every record of the new process as older and sat with the button
        # disabled (round 2 of batch 2's review). `seq` is compared only
        # within one epoch; a different epoch always wins, since the process
        # that minted the old one is gone and can send nothing later.
        self._epoch = secrets.token_hex(8)

    def start(self, operation: Operation) -> threading.Thread:
        """Begin a run on its own thread, or raise `RunInFlight`.

        **A daemon thread, not the executor.** The interpreter joins executor
        threads at exit, and one plugin update is bounded at five minutes, so
        a stop during a run would sit past the unit's stop timeout and end in
        a SIGKILL. A daemon thread is abandoned at exit instead; the vendor's
        child process is then ended with the unit's cgroup, or, from a
        terminal, finishes on its own.
        """
        with self._lock:
            if self._state == "running":
                raise RunInFlight
            self._state = "running"
            self._started_at = self._clock()
            self._finished_at = None
            self._outcomes = []
            self._code = self._message = None
            record = self._changed()
        self._publish({"kind": EVENT_KIND, "run": record})
        thread = threading.Thread(
            target=self._run, args=(operation,), name="plugin-run", daemon=True
        )
        thread.start()
        return thread

    def snapshot(self) -> RunRecord:
        with self._lock:
            return self._record()

    def _run(self, operation: Operation) -> None:
        """Every exit clears the marker. The `except Exception` is the
        premortem's second failure: a bug here that escaped would leave the
        state `running` and refuse every update until a restart."""
        state: State = "failed"
        code: str | None = None
        message: str | None = None
        try:
            operation(self._report)
            state = "done"
        except PluginsFailed as exc:
            code, message = exc.code, str(exc)
        except Exception:
            logger.exception("plugin run failed unexpectedly")
            code, message = "internal_error", "the update stopped on an internal error"
        finally:
            with self._lock:
                self._state = state
                self._code, self._message = code, message
                self._finished_at = self._clock()
                record = self._changed()
            self._publish({"kind": EVENT_KIND, "run": record})

    def _report(self, outcome: PluginOutcome) -> None:
        with self._lock:
            self._outcomes.append(outcome)
            record = self._changed()
        self._publish({"kind": EVENT_KIND, "run": record})

    def _changed(self) -> RunRecord:
        """Under the lock: the record after a change, with the next seq."""
        self._seq += 1
        return self._record()

    def _record(self) -> RunRecord:
        """Under the lock. `counts` is None unless the run finished, so a
        failure can never be rendered as a count."""
        counts = None
        if self._state == "done":
            counts = {
                result: sum(o.result == result for o in self._outcomes)
                for result in ("updated", "failed", "skipped")
            }
        return {
            "epoch": self._epoch,
            "seq": self._seq,
            "state": self._state,
            "started_at": self._started_at,
            "finished_at": self._finished_at,
            "outcomes": [asdict(o) for o in self._outcomes],
            "counts": counts,
            "code": self._code,
            "message": self._message,
        }
