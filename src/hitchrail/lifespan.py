"""The app's lifespan: the sweep that expires stops, scans for rows waiting on
a person and advances the wrap up watch, and the teardown that must not hang.

Split out of `server.py` at #205.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager

from starlette.applications import Starlette

from hitchrail import engine as eng
from hitchrail.events import EventBus
from hitchrail.plugin_runs import PluginRuns
from hitchrail.routes_common import in_thread, logger

SWEEP_INTERVAL_S = 1.0


def make_lifespan(
    engine: eng.Engine, events: EventBus, plugin_updates: PluginRuns
) -> Callable[[Starlette], AbstractAsyncContextManager[None]]:
    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        app.state.events = events
        app.state.engine = engine

        # #180. At most one scan in flight, tracked so the expiry loop never
        # waits behind it and so teardown can cancel it.
        scanning: asyncio.Task[list[str]] | None = None
        # #242. The same shape for the wrap up watch, for the same reason.
        wrapping: asyncio.Task[list[str]] | None = None

        def scan_finished(task: asyncio.Task[list[str]]) -> None:
            """A task nobody awaits swallows its exception, and this one is the
            reason the interface can say a person is needed. Logged with the
            same argument `sweep` makes for not suppressing silently: "the scan
            stopped working" must not be unfalsifiable."""
            if task.cancelled():
                # Cancelled at teardown, which is ordinary. But the THREAD may
                # still have raised: `run_in_executor`'s future is cancelled
                # from the awaiting side, so an exception in the worker lands
                # nowhere. Nothing can be done about that here, and pretending
                # otherwise is what an early return without this note does.
                return
            if task.exception() is not None:
                logger.error(
                    "attention scan failed; the sweep continues",
                    exc_info=task.exception(),
                )

        def wrap_up_finished(task: asyncio.Task[list[str]]) -> None:
            """`scan_finished`'s argument, for the wrap up watch (#242)."""
            if not task.cancelled() and task.exception() is not None:
                logger.error(
                    "wrap up watch failed; the sweep continues",
                    exc_info=task.exception(),
                )

        async def sweep() -> None:
            """Expire stop markers on a timer, so a timeout the user is
            watching resolves without waiting for the next poll.

            The loop must outlive any single failure, because if this task
            ends no stop expires again for the life of the process, and the
            interface shows a timer that never resolves. It must NOT do that
            silently, though: a bare suppress here makes "expiry stopped
            working" unfalsifiable, and this ran for a whole phase before
            anybody would notice. The engine already logs the expected
            operational case (a machine it cannot read); this catches the
            unexpected one and says so.
            """
            nonlocal scanning, wrapping
            while True:
                await asyncio.sleep(SWEEP_INTERVAL_S)
                try:
                    # #472. BEFORE the expiry: an agent that exited a moment
                    # before its stop's timeout is started from, where after it
                    # the expiry would clear the restart that had worked.
                    # Awaited, as the expiry is; with nothing pending it is one
                    # dict read.
                    await in_thread(engine.advance_restarts)
                except Exception:
                    logger.exception("restart sweep failed; the timer continues")
                try:
                    await in_thread(engine.expire_stops)
                    # #100. Here rather than on the listing route, which is the
                    # decision `scan_for_stuck` documents: the cost then scales
                    # with the state of the machine rather than with how often
                    # a browser polls, and no capture lands on the executor that
                    # serves the operator's stop.
                    #
                    # **Started, not awaited (#180).** `attention.BUDGET_S`
                    # bounds when a capture may BEGIN; one starting a
                    # millisecond inside it still runs to `_CALL_TIMEOUT_S`, so
                    # a tick's worst case is about 33 seconds. Awaited in
                    # sequence that delayed the next EXPIRY by as much, and
                    # `stop_timeout` defaults to 30, so the browser's own timer
                    # won and said "it has not finished" before the server had
                    # noticed its own expiry.
                    #
                    # At most one in flight: a second would put two captures on
                    # the executor serving the operator's stop, which is the
                    # cost this scan moved off the request path to avoid.
                    if scanning is None or scanning.done():
                        scanning = asyncio.create_task(in_thread(engine.scan_for_stuck))
                        scanning.add_done_callback(scan_finished)
                    # #242. Started, not awaited, at most one in flight, as the
                    # scan above and for its reason: it captures a pane per
                    # wrapping row and may type the exit sequence with its
                    # settles. Unlike the scan it runs with nobody watching.
                    if wrapping is None or wrapping.done():
                        wrapping = asyncio.create_task(in_thread(engine.advance_wrap_ups))
                        wrapping.add_done_callback(wrap_up_finished)
                except Exception:
                    logger.exception("stop sweep failed; the timer continues")

        task = asyncio.create_task(sweep())
        try:
            yield
        finally:
            # #361. A plugin update runs on `PluginRuns`'s own daemon thread,
            # which never receives `KeyboardInterrupt`: Python delivers it to
            # the main thread only, and this coroutine, running on the main
            # thread's event loop, is that thread. Since #299 the child is
            # also its own process group leader, so it no longer shares the
            # terminal's group either; Ctrl-C on the terminal reaches neither.
            # `kill()` is a single `os.killpg`, synchronous and immediate: it
            # does not itself need bounding. What follows it is bounded
            # already, inside `plugin_runner`'s own `communicate()`, on the
            # daemon thread this call does not wait for.
            # #365. `kill()` is an `os.killpg`, and a group that has become
            # another user's, or a kernel refusing it, raises. Everything
            # after it is in the `finally` so that raise cannot leave the
            # sweep ticking, or a scan awaited by nobody, while the error
            # goes up: the error is still reported, just not instead.
            try:
                plugin_updates.handle.kill()
            finally:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
                # #180. **This cancels the AWAIT, not the thread, and the
                # difference matters.** `in_thread` is `run_in_executor`, so
                # `scan_for_stuck` goes on running in its worker whatever happens
                # here. Measured: teardown returns in about 3ms with the thread
                # still working, and the process then blocks for the rest of the
                # capture at `shutdown_default_executor()`.
                #
                # So what this buys is that the lifespan does not HANG, not that the
                # scan stops. An earlier version of this note claimed the second and
                # was wrong, which is the defect #178 in this same commit is about:
                # a comment contradicted by its own code.
                #
                # A capture bounded at `_CALL_TIMEOUT_S` is the worst case, so the
                # process waits up to ten seconds on shutdown. That is the cost of
                # not being able to cancel a thread, and it is bounded.
                #
                # #392. `Exception` too: a task that already finished by
                # raising ignores `cancel()`, and awaiting it raised that error
                # a second time, out of a clean shutdown or in place of the
                # kill's own. Its done callback has logged it, so nothing is
                # silenced here.
                for pending in (scanning, wrapping):
                    if pending is not None:
                        pending.cancel()
                        with contextlib.suppress(asyncio.CancelledError, Exception):
                            await pending

    return lifespan
