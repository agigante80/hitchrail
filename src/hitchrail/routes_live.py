"""The routes that carry events: the SSE stream and the plugin update, whose
record arrives on that stream as a named event.

Split out of `server.py` at #205.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from sse_starlette.sse import EventSourceResponse
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from hitchrail.events import EventBus
from hitchrail.plugin_runs import EVENT_KIND, Operation, PluginRuns, RunInFlight
from hitchrail.routes_common import _error


def live_routes(
    events: EventBus, plugin_updates: PluginRuns, run_plugins: Operation
) -> list[Route]:
    async def start_plugin_update(request: Request) -> Response:
        """Begin the plugin update and answer at once, with the record (#297).

        202 because the work has only begun: a run is minutes on a slow
        marketplace, and a phone waiting on one request for that long loses
        it to the first network change. The record then arrives on the stream
        as a named `plugins` event, and `GET` below answers a page that opens
        or reconnects in the middle. A failure of the operation itself
        (`agent_missing`, `marketplace_refresh_failed`, `plugins_unreadable`,
        `shutting_down`, or `internal_error`) is in the record, not in a
        status: by then this 202 has been sent.

        `update_in_flight` rather than `locked`: `locked` is documented as a
        start in flight for a PROJECT, and this is machine wide.
        """
        try:
            plugin_updates.start(run_plugins)
        except RunInFlight:
            return _error(
                409,
                "update_in_flight",
                "a plugin update is already running; this request changed nothing",
            )
        return JSONResponse(plugin_updates.snapshot(), status_code=202)

    async def plugin_update(request: Request) -> Response:
        """The current or last run, `state: idle` when there has been none."""
        return JSONResponse(plugin_updates.snapshot())

    async def event_stream(request: Request) -> Response:
        """The one route `EventSource` can actually reach.

        A GET, because `EventSource` cannot set headers: no `Authorization`,
        no custom anything. That is why the token has a cookie carrier, and
        why this route is exempt from the Origin check while every mutating
        route is not.
        """

        async def publisher() -> AsyncIterator[dict[str, str]]:
            with events.subscribe() as queue:
                while True:
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=1.0)
                    except TimeoutError:
                        # Not an error, and it fires constantly on a healthy
                        # idle stream, which is this system's normal state.
                        # The bounded wait exists so the loop stays cancellable
                        # rather than parked forever inside `queue.get()`.
                        continue
                    # #297. The plugin record is a NAMED event, so the page's
                    # `message` listener, which renders every frame as a
                    # session, never sees it; only a listener that asks for
                    # `plugins` does. The session payload is unchanged.
                    if event.get("kind") == EVENT_KIND:
                        yield {"event": EVENT_KIND, "data": json.dumps(event["run"])}
                        continue
                    yield {"event": "message", "data": json.dumps(event)}

        # No `request.is_disconnected()` poll in the loop above, deliberately.
        # It duplicated a job the comment below already assigns to
        # sse-starlette, and the live tier proves the library does it: removing
        # the check leaves `test_the_subscriber_slot_is_released_when_a_reader_goes_away`
        # passing. It was also a second consumer of the same `receive()`
        # channel sse-starlette listens on for the disconnect, so the two could
        # race for the message that ends the stream. An unreachable guard is
        # worse than none; one that can steal another's input is worse again.
        #
        # sse-starlette handles ping keepalive, disconnect detection and
        # generator shutdown, which are the parts of SSE that are awkward to
        # get right. Note its documented caveat: SSE and GZipMiddleware do not
        # mix, which is why no gzip middleware appears anywhere in this app.
        #
        # This route CANNOT be tested through `httpx.ASGITransport`, and that
        # is a property of the transport rather than of this code.
        # `ASGITransport.handle_async_request` awaits the app to COMPLETION and
        # accumulates the body, so a stream that never ends never returns
        # headers. An endless generator hangs it forever.
        #
        # A draft of this function yielded a `ready` event first, on the
        # reading that headers were being withheld until the first yield. That
        # was the transport, not sse-starlette: verified on a real socket that
        # headers arrive immediately with no such event. The event is gone
        # rather than kept as a harmless extra, because it would have been a
        # permanent addition to a documented contract bought by a wrong
        # diagnosis. The stream's tests live in the `live` tier for the same
        # reason, which is what `.claude/CLAUDE.md` already says about SSE.
        return EventSourceResponse(publisher())

    return [
        Route("/api/events", event_stream, methods=["GET"]),
        Route("/api/plugins/update", start_plugin_update, methods=["POST"]),
        Route("/api/plugins/update", plugin_update, methods=["GET"]),
    ]
