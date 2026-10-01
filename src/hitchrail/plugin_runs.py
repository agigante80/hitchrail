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
`seq`, `epoch`, `boot` and `since_boot_us` below.

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
from pathlib import Path
from typing import Literal, TypedDict, get_args

from hitchrail import claude_ipc
from hitchrail.claude_ipc import PluginOutcome, PluginResult, PluginsFailed
from hitchrail.config import TOKEN_ENV

logger = logging.getLogger(__name__)

# What the server's stream uses to tell these events from a session's. The
# session payload is the stream's original contract and carries no such key.
EVENT_KIND = "plugins"

Operation = Callable[[Callable[[PluginOutcome], None]], list[PluginOutcome]]
State = Literal["idle", "running", "done", "failed"]

# Shared with `start`'s own failure path (#307), so the two can never drift
# into reporting the same code with a different sentence.
_INTERNAL_ERROR_MESSAGE = "the update stopped on an internal error"


class RunRecord(TypedDict):
    """What `GET /api/plugins/update` returns and every event carries."""

    epoch: str
    boot: str
    since_boot_us: int
    seq: int
    state: State
    started_at: float | None
    finished_at: float | None
    outcomes: list[dict[str, str | None]]
    counts: dict[str, int] | None
    code: str | None
    message: str | None


BOOT_ID = Path("/proc/sys/kernel/random/boot_id")


def read_boot_id(path: Path = BOOT_ID) -> str:
    """The kernel's id for this boot, or a random stand in (#348).

    The stand in makes every process look like its own boot, which the page
    orders by arrival instead: weaker than the boot clock, never wrong in a
    way that locks the page.
    """
    try:
        return path.read_text(encoding="ascii").strip() or secrets.token_hex(16)
    except (OSError, UnicodeDecodeError):
        return secrets.token_hex(16)


def since_boot_us() -> int:
    """`CLOCK_BOOTTIME` in microseconds (#348).

    Not the wall clock: NTP or `date` can step that backwards between two
    starts, and a unit started at boot does so before NTP has synced, so a
    new process would read as the OLDER one and the page would lock out
    again. Microseconds because a JavaScript number is exact only to 2^53:
    285 years of these, 104 days of nanoseconds.
    """
    return time.clock_gettime_ns(time.CLOCK_BOOTTIME) // 1000


class RunInFlight(Exception):
    """A run is already going; the request changed nothing."""


def operation_for(
    agent_binary: str, *, handle: claude_ipc.RunningChild | None = None
) -> Operation:
    """The real operation, withholding the token from every child (#113).

    `handle`, when given, is `PluginRuns`'s own (#361): threaded into the
    runner so the server's lifespan can kill whatever this operation is
    running, from outside, on shutdown. `None` for every caller that has no
    lifespan to tear down, `hitchrail update-plugins` foremost: there, the
    operator's own Ctrl-C already reaches this thread directly, so nothing
    needs to reach in from outside it.
    """
    runner = claude_ipc.plugin_runner(withhold=(TOKEN_ENV,), handle=handle)

    def operation(report: Callable[[PluginOutcome], None]) -> list[PluginOutcome]:
        return claude_ipc.update_plugins(agent_binary, run=runner, report=report)

    return operation


class PluginRuns:
    def __init__(
        self,
        publish: Callable[[dict[str, object]], None],
        clock: Callable[[], float] = time.time,
        boot: Callable[[], str] = read_boot_id,
        boot_clock: Callable[[], int] = since_boot_us,
    ) -> None:
        self._publish = publish
        self._clock = clock
        # #361. Public: the server's lifespan kills whatever this instance is
        # running, from outside the daemon thread `start` puts it on, since
        # that thread never sees the shutdown's `KeyboardInterrupt` (Python
        # delivers it to the main thread only). `operation_for` is the other
        # end, threading this same object into `plugin_runner` so the pid it
        # sets is the one this `kill()` reaches. A no-op when idle: `kill()`
        # itself is where that is decided, not here.
        self.handle = claude_ipc.RunningChild()
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
        # within one epoch.
        self._epoch = secrets.token_hex(8)
        # #348. Which of two processes is newer. A random epoch cannot say,
        # and the page guessed wrong four times trying; these two let it
        # compare instead: within one boot the later start wins, and across
        # boots the page falls back to arrival order.
        self._boot = boot()
        self._since_boot_us = boot_clock()

    def start(self, operation: Operation) -> threading.Thread:
        """Begin a run on its own thread, or raise `RunInFlight`.

        **A daemon thread, not the executor.** The interpreter joins executor
        threads at exit, and one plugin update is bounded at five minutes, so
        a stop during a run would sit past the unit's stop timeout and end in
        a SIGKILL. A daemon thread is abandoned at exit instead, and the
        vendor's child process is killed by the server's lifespan through
        `RunningChild.kill()` (#361), never left to finish on its own.
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
        try:
            thread.start()
        except Exception:
            # #307. `_run`'s `finally` is what normally clears the marker, and
            # it never runs if `_run` itself never starts: `Thread.start` can
            # raise on its own, `RuntimeError` on a machine out of threads
            # being the documented case. Without this, `running` sticks and
            # every later request reads `update_in_flight` until a restart.
            with self._lock:
                self._state = "failed"
                self._code, self._message = "internal_error", _INTERNAL_ERROR_MESSAGE
                self._finished_at = self._clock()
                record = self._changed()
            self._publish({"kind": EVENT_KIND, "run": record})
            raise
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
            code, message = "internal_error", _INTERNAL_ERROR_MESSAGE
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
                # #370: from the literal, so a new result is counted here
                # without a second list to remember.
                for result in get_args(PluginResult)
            }
        return {
            "epoch": self._epoch,
            "boot": self._boot,
            "since_boot_us": self._since_boot_us,
            "seq": self._seq,
            "state": self._state,
            "started_at": self._started_at,
            "finished_at": self._finished_at,
            "outcomes": [asdict(o) for o in self._outcomes],
            "counts": counts,
            "code": self._code,
            "message": self._message,
        }
