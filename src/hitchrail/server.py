"""The HTTP layer. Routing and translation only; the logic lives in the engine.

Starlette 1.x: lifespan context manager and an explicit routes list. The
on_startup, on_shutdown, add_event_handler and @app.route decorators were all
removed at 1.0, so any example using them predates this API.
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import json
import logging
from collections.abc import AsyncIterator, Callable
from typing import TypeVar

from sse_starlette.sse import EventSourceResponse
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from hitchrail import discovery, pages
from hitchrail import engine as eng
from hitchrail import security as sec
from hitchrail.config import Config
from hitchrail.events import EventBus
from hitchrail.security import middleware_stack

T = TypeVar("T")

# The message an unrouted path answers with, READ from Starlette rather than
# copied, so a route that wants to be indistinguishable from a missing one
# cannot drift apart from the real thing when Starlette rewords it.
ROUTING_404_MESSAGE = str(HTTPException(status_code=404).detail)

SWEEP_INTERVAL_S = 1.0

# The only route that reads a body takes {"name": <a project name>}, and a
# project name is capped at 64 characters, so this is three orders of magnitude
# more than the contract needs.
#
# **413 is the one failure that is not the documented envelope**, and that is a
# property of where Starlette installs the limit rather than a decision here.
# `RequestBodyLimitMiddleware` goes OUTSIDE `ExceptionMiddleware`, so it
# answers before the application exists and its `text/plain` body cannot be
# rewritten by this app's exception handlers. A draft added a `content-length`
# check inside the create route to answer in the envelope first; it is gone,
# because the middleware wins even against a client that lies about the length,
# verified, so the check could never execute. A guard that cannot run is worse
# than none.
#
# Starlette 1.x defaults `max_body_size` to None, meaning unlimited, and
# `request.json()` runs INSIDE the handler: a 50 MB body was read into memory
# in full and then refused as an invalid name. On loopback with no token
# configured, which is the documented default, any local process could do that
# in a loop. Filling the machine's memory through the API of a tool whose
# entire job is refusing to start agents when memory is short is a poor way to
# find out the limit was never set.
MAX_BODY_BYTES = 64 * 1024

logger = logging.getLogger(__name__)


async def in_thread(fn: Callable[..., T], *args: object, **kwargs: object) -> T:
    """Run a blocking engine call off the event loop.

    The engine spawns `ps` and `tmux`. Doing that on the loop stalls the SSE
    stream for every connected browser, because the stream lives on the same
    loop. A sync `def` handler would get this for free from Starlette, but a
    sync handler cannot await a request body, and the create route needs one.

    Two taps therefore land on two threads, which is what the per folder start
    lock in the engine exists to serialise.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, functools.partial(fn, *args, **kwargs))


def _error(status: int, code: str, message: str, **extra: object) -> JSONResponse:
    return JSONResponse({"code": code, "message": message, **extra}, status_code=status)


# Routing level failures, which never reach a handler. Distinct from
# `unknown_project`: that means the root has no such folder, these mean this
# server has no such ROUTE or does not accept that method there.
_ROUTING_CODES = {404: "not_found", 405: "method_not_allowed"}


async def _routing_error(request: Request, exc: Exception) -> Response:
    """Render Starlette's own 404 and 405 in the documented envelope.

    Without this the contract "every failure is {code, message}" held for every
    failure a handler produced and for none of the ones routing produced: a
    typo in a path or a wrong method returned `text/plain` saying "Not Found",
    so a client parsing JSON on any non 2xx got a parse error instead of a
    code. The interface meets this on the first mistyped URL.
    """
    # An assert rather than two `isinstance ... else` arms. Starlette types a
    # handler's second argument as `Exception`, so the narrowing has to happen
    # somewhere; written as ternaries it produced two branches that cannot run,
    # because this handler is registered for `HTTPException` and nothing else.
    # If that registration ever changes, this fails loudly instead of quietly
    # answering 500 with a code nobody documented.
    assert isinstance(exc, HTTPException), f"registered for HTTPException, got {type(exc)}"
    # `error` covers a status Starlette raises that is not in the table. It is
    # a real possibility rather than a dead default: routing raises 404 and 405
    # today, and a generic code with the right status beats a crash.
    return _error(
        exc.status_code, _ROUTING_CODES.get(exc.status_code, "error"), str(exc.detail)
    )


def create_app(engine: eng.Engine, config: Config, bus: EventBus) -> Starlette:
    """The bus is REQUIRED, and the caller owns it.

    An earlier draft took it optionally and reconciled it against `engine.bus`.
    There is no such attribute: `Engine` has a private `_bus` and
    `attach_bus()`, so that draft raised `AttributeError` on this line. Worth
    more than the typo, though, is that it was reading two sources of truth to
    decide which bus wins, which is precisely how the "published into a void"
    bug it warned about gets written. One owner, passed in, attached once.
    """
    engine.attach_bus(bus)
    events = bus

    async def list_projects(request: Request) -> Response:
        # ONE scan, one thread hop, one consistent answer.
        #
        # An earlier draft called `engine.list()` and `discovery.scan()`
        # separately. `engine.list` resolves its names through
        # `discovery.list_projects`, which IS `scan(root).projects`, so the
        # root was walked twice per request on the route the interface polls
        # hardest. Worse than the cost: the two walks can disagree, so a folder
        # created between them appeared in `unsupported` while being absent
        # from `projects`, or the reverse.
        #
        # `unsupported` is the folders under the root that cannot be projects,
        # each with the rule it broke. Dropping them silently made a folder
        # called `my app` look like one Hitchrail could not see. See issue #7.
        def read() -> tuple[discovery.Listing, list[eng.Session], tuple[int, int | None]]:
            listing = discovery.scan(config.root)
            return listing, engine.list(listing=listing), engine.machine_memory()

        try:
            listing, sessions, memory = await in_thread(read)
        except discovery.RootUnavailable as exc:
            # The root going away, an unmounted drive or a deleted directory,
            # is not "no projects". Reporting an empty list would be a lie the
            # interface cannot tell from a genuinely empty root.
            return _error(503, "root_unavailable", str(exc))
        except eng.MachineUnreadable as exc:
            # Same honesty, one layer down. Phase 4 makes an unreadable machine
            # an error rather than a fifth state precisely so this is not
            # derived as `stopped`, and answering 500 here would throw that
            # away on the one route that renders the whole table.
            return _error(503, "machine_unreadable", str(exc))
        return JSONResponse(
            {
                "projects": [s.as_dict() for s in sessions],
                "unsupported": [
                    {"name": u.name, "reason": u.reason} for u in listing.unsupported
                ],
                # The true count, because the list above is capped. The
                # interface says "50 of 1240 shown"; hiding the excess
                # silently would be the bug this whole field exists to fix.
                "unsupported_total": listing.unsupported_total,
                # The machine, not the projects. The footer draws a
                # proportion and the header names the folder, and neither is
                # derivable from the rows. See #64.
                "memory": {"available_mb": memory[0], "total_mb": memory[1]},
                "root": str(config.root),
            }
        )

    async def create_project(request: Request) -> Response:
        try:
            payload = await request.json()
            name = str(payload["name"])
        except (ValueError, KeyError, TypeError):
            # A malformed body is a bad name, not a server fault. Returning 500
            # here would put a traceback where a client expects a code.
            return _error(400, "invalid_name", "a JSON body with a 'name' is required")
        try:
            await in_thread(discovery.create_project, config.root, name)
        except discovery.AlreadyExists as exc:
            return _error(409, "already_exists", str(exc))
        except discovery.RootUnavailable as exc:
            # The root went away under us. Not the caller's fault, and not
            # something to answer by pretending there are no projects.
            return _error(503, "root_unavailable", str(exc))
        except (discovery.InvalidName, discovery.OutsideRoot) as exc:
            # Both mean "not a name we will turn into a path here". Telling the
            # caller which guard caught it describes the filesystem to them.
            return _error(400, "invalid_name", str(exc))
        session = await in_thread(engine.get, name)
        # The BARE dict, the shape `Engine._announce` publishes. An envelope
        # here left `session.name` undefined on the wire, so every client
        # refetched the whole listing instead of patching a row. It looked
        # right because a refetch IS correct for a new project.
        events.publish(session.as_dict())
        return JSONResponse(session.as_dict(), status_code=201)

    async def grant(request: Request) -> Response:
        """Trade a token the page read from a fragment for the cookie.

        Reached without authentication, by design: nothing but JavaScript in
        the browser can read a fragment, so the flow needs one door. This is
        that door and it checks the token itself.

        A POST, so `OriginCheckMiddleware` runs on it: a grant is mutating, and
        a mutating request a link can perform is the shape the origin check
        exists to stop. A GET here would be exactly that link.
        """
        if config.token is None:
            # Nothing to grant, and answering 200 would tell a caller the
            # deployment is open. Neither does the message: a first draft
            # argued exactly that and then said "no token is configured" in
            # words, a second said "no such route on this server", which no
            # other path answers. Identical to an unrouted one, asserted.
            return _error(404, "not_found", ROUTING_404_MESSAGE)
        try:
            body = await request.json()
            offered = body["token"]
        except (ValueError, KeyError, TypeError):
            return _error(400, "invalid_body", "a JSON body with a 'token' is required")
        if not isinstance(offered, str) or not sec.token_matches(offered, config.token):
            # The SAME answer a missing token gets from the middleware. A wrong
            # token and no token are already indistinguishable at the API, and
            # this route must not become the oracle the middleware refuses to
            # be.
            return _error(401, "unauthorized", "a valid token is required")
        response = JSONResponse({"ok": True})
        sec.set_token_cookie(response, config.token)
        return response

    async def start(request: Request) -> Response:
        name = request.path_params["name"]
        acknowledged = request.query_params.get("acknowledged") in {"1", "true"}
        try:
            session = await in_thread(engine.start, name, acknowledged)
        except eng.UnknownProject as exc:
            return _error(404, "unknown_project", str(exc))
        except eng.AlreadyRunning as exc:
            return _error(409, "already_running", str(exc))
        except eng.Locked as exc:
            return _error(409, "locked", f"a start is already in flight for {exc}")
        except eng.MemoryNeedsAck as exc:
            return _error(
                409,
                "ram_soft",
                "starting would leave the machine short on memory",
                available_mb=exc.available_mb,
                needed_mb=exc.needed_mb,
            )
        except eng.MemoryRefused as exc:
            return _error(
                507,
                "ram_hard",
                "not enough memory to start a session",
                available_mb=exc.available_mb,
                needed_mb=exc.needed_mb,
            )
        except eng.StartFailed as exc:
            return _error(502, "start_died", str(exc), output=exc.output)
        except eng.Protected as exc:
            # `start` raises this and an earlier draft did not catch it, so the
            # one route where the protection matters most, the one that would
            # put a SECOND agent in Hitchrail's own folder, answered 500.
            return _error(423, "self_protected", str(exc))
        except eng.MachineUnreadable as exc:
            return _error(503, "machine_unreadable", str(exc))
        return JSONResponse(session.as_dict(), status_code=201)

    async def stop(request: Request) -> Response:
        """The graceful one. NOTHING in the query string reaches `kill`.

        The two used to be one handler picking a method from `?kill=1`, which
        contradicted the design paragraph it was written next to. See #52: a
        duration is a parameter, an action is a route, and there is not even a
        duration here because the wait is `stop_timeout` in the configuration.
        """
        name = request.path_params["name"]
        try:
            session = await in_thread(engine.stop, name)
        except eng.UnknownProject as exc:
            return _error(404, "unknown_project", str(exc))
        except eng.Protected as exc:
            return _error(423, "self_protected", str(exc))
        except eng.NotRunning as exc:
            return _error(409, "not_running", str(exc))
        except eng.StopRefused as exc:
            # 409 and not 503: nothing is broken and asking again changes
            # nothing. The session is in a state where this action is wrong,
            # which is what every other 409 on this API means. The engine sent
            # no keys, so there is nothing to undo and nothing in flight.
            return _error(409, "stop_unsafe", str(exc))
        except eng.MachineUnreadable as exc:
            return _error(503, "machine_unreadable", str(exc))
        return JSONResponse(session.as_dict(), status_code=202)

    async def kill(request: Request) -> Response:
        """The destructive one, on its own path and its own method.

        Accepted whether or not a graceful stop preceded it: the requirement to
        try gently first is a property of the interface, not of the API. A CLI
        user has a legitimate need to kill outright, and enforcing etiquette in
        the transport would only invite working around it.

        200 rather than 202 because, unlike the graceful stop, this one has
        already happened by the time it answers. `engine.kill` waits a bounded
        two seconds for the process to actually leave the table, so the session
        in the body is settled rather than in flight.
        """
        name = request.path_params["name"]
        try:
            session = await in_thread(engine.kill, name)
        except eng.UnknownProject as exc:
            return _error(404, "unknown_project", str(exc))
        except eng.Protected as exc:
            return _error(423, "self_protected", str(exc))
        except eng.NotRunning as exc:
            return _error(409, "not_running", str(exc))
        except eng.MachineUnreadable as exc:
            return _error(503, "machine_unreadable", str(exc))
        return JSONResponse(session.as_dict(), status_code=200)

    async def logs(request: Request) -> Response:
        name = request.path_params["name"]
        try:
            lines = int(request.query_params.get("lines", 40))
        except ValueError:
            lines = 40
        lines = max(1, min(lines, 2000))
        try:
            text = await in_thread(engine.logs, name, lines)
        except eng.UnknownProject as exc:
            return _error(404, "unknown_project", str(exc))
        except eng.NotRunning as exc:
            return _error(409, "not_running", str(exc))
        except eng.MachineUnreadable as exc:
            return _error(503, "machine_unreadable", str(exc))
        # No `Protected` arm, and that is not an oversight. `engine.logs`
        # deliberately does not refuse the self project: reading the log of the
        # session hosting Hitchrail is harmless and occasionally the only way
        # to see what it is doing. An arm here could never fire, and this
        # project treats a guard that cannot execute as worse than none.
        return JSONResponse({"name": name, "text": text})

    async def session_url(request: Request) -> Response:
        """The link, paid for on demand.

        Listing never captures a pane, so a session whose link Claude has not
        written yet simply has none. This is where a client learns that the
        absence means "not yet" rather than "never".
        """
        name = request.path_params["name"]
        try:
            found = await in_thread(engine.session_url, name)
        except eng.UnknownProject as exc:
            return _error(404, "unknown_project", str(exc))
        except eng.NotRunning as exc:
            return _error(409, "not_running", str(exc))
        except eng.MachineUnreadable as exc:
            return _error(503, "machine_unreadable", str(exc))
        # No `Protected` arm here either, for the same reason as `logs`:
        # `engine.session_url` gates on the name only, so it cannot fire.
        if found is None:
            return _error(409, "url_pending", "the session has not published a link yet")
        # BOTH fields. `engine.session_url` returns `SessionUrl(url, source)`,
        # not a string, and handing the dataclass to `JSONResponse` unchanged
        # is a TypeError rather than a wrong answer, which is the one mercy.
        #
        # `source` travels because a scraped link can be scrollback from a
        # session that ended hours ago, while a bridge link is known good. The
        # interface has to be able to present those differently instead of
        # showing them as equals. Decided in #29.
        return JSONResponse({"name": name, "url": found.url, "source": found.source})

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

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        app.state.events = events
        app.state.engine = engine

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
            while True:
                await asyncio.sleep(SWEEP_INTERVAL_S)
                try:
                    await in_thread(engine.expire_stops)
                except Exception:
                    logger.exception("stop sweep failed; the timer continues")

        task = asyncio.create_task(sweep())
        try:
            yield
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    return Starlette(
        routes=[
            Route("/api/projects", list_projects, methods=["GET"]),
            Route("/api/projects", create_project, methods=["POST"]),
            Route("/api/sessions/{name}", start, methods=["POST"]),
            Route("/api/sessions/{name}", stop, methods=["DELETE"]),
            # Its own route, deliberately. #52 and the design's section 6.
            Route("/api/sessions/{name}/kill", kill, methods=["POST"]),
            Route("/api/sessions/{name}/logs", logs, methods=["GET"]),
            Route("/api/sessions/{name}/url", session_url, methods=["GET"]),
            Route("/api/events", event_stream, methods=["GET"]),
            Route(sec.GRANT_API_PATH, grant, methods=["POST"]),
            Route(sec.GRANT_PAGE_PATH, pages.grant_page, methods=["GET"]),
            Route("/", pages.page, methods=["GET"]),
            *[Route(p, pages.asset_route(p), methods=["GET"]) for p in pages.ASSETS],
        ],
        middleware=middleware_stack(config),
        exception_handlers={HTTPException: _routing_error},
        max_body_size=MAX_BODY_BYTES,
        lifespan=lifespan,
    )
