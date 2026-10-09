"""The HTTP layer. Routing and translation only; the logic lives in the engine.

Starlette 1.x: lifespan context manager and an explicit routes list. The
on_startup, on_shutdown, add_event_handler and @app.route decorators were all
removed at 1.0, so any example using them predates this API.

The handlers live in the `routes_*` modules, split at #205 by what they touch,
and the lifespan in `lifespan.py`. This file wires them to one app and keeps
the grant, the one route that is answered without a token.
"""

from __future__ import annotations

import getpass
import os
import time
from collections.abc import Callable

from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

import hitchrail
from hitchrail import engine as eng
from hitchrail import pages
from hitchrail import security as sec
from hitchrail.config import Config
from hitchrail.events import EventBus
from hitchrail.headers import SecurityHeadersMiddleware
from hitchrail.lifespan import make_lifespan
from hitchrail.plugin_runs import Operation, PluginRuns, operation_for
from hitchrail.routes_common import _UNPARSEABLE, _error
from hitchrail.routes_live import live_routes
from hitchrail.routes_projects import project_routes
from hitchrail.routes_sessions import session_routes
from hitchrail.routes_settings import settings_routes
from hitchrail.security import middleware_stack

# The message an unrouted path answers with, READ from Starlette rather than
# copied, so a route that wants to be indistinguishable from a missing one
# cannot drift apart from the real thing when Starlette rewords it.
ROUTING_404_MESSAGE = str(HTTPException(status_code=404).detail)

# Three routes read a body: create takes {"name": <a project name>}, answer
# takes {"key": <one of ANSWER_KEYS>} and the settings PATCH takes the shape
# above, a boolean per configured label. A project name is capped at 64
# characters and a key is shorter still, so this is three orders of magnitude
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


def create_app(
    engine: eng.Engine,
    config: Config,
    bus: EventBus,
    *,
    now: Callable[[], float] = time.time,
    user: Callable[[], str] = getpass.getuser,
    plugin_operation: Operation | None = None,
) -> Starlette:
    """The bus is REQUIRED, and the caller owns it.

    `now` and `user` are the two seams #148 added, wall clock and account,
    read once below. Wall clock rather than the engine's monotonic one,
    because the value is shown to a person beside a journal timestamp.

    An earlier draft took it optionally and reconciled it against `engine.bus`.
    There is no such attribute: `Engine` has a private `_bus` and
    `attach_bus()`, so that draft raised `AttributeError` on this line. Worth
    more than the typo, though, is that it was reading two sources of truth to
    decide which bus wins, which is precisely how the "published into a void"
    bug it warned about gets written. One owner, passed in, attached once.
    """
    engine.attach_bus(bus)
    events = bus
    # #297. The plugin update, one at a time. `plugin_operation` is the seam
    # the tests fill; unset, it is the quarantined operation for the binary
    # this server starts agents with.
    plugin_updates = PluginRuns(publish=events.publish, clock=now)
    # #196, #298: the resolved absolute path, so this update runs the same
    # file `cli.preflight` checked rather than a bare name resolved again.
    #
    # #361. `plugin_updates.handle` rides along so the lifespan below can kill
    # whatever this operation is running when the server shuts down. A caller
    # that passes its own `plugin_operation` (every test in this file) built
    # that operation itself and is not wired to this handle, which is why the
    # required regression test goes through the real `operation_for`.
    run_plugins = plugin_operation or operation_for(
        config.spawn_agent_binary, handle=plugin_updates.handle
    )
    # #147. Per server constants, read ONCE here and sent on the listing the
    # page already fetches, never on a route of their own: a second round trip
    # for a string is a round trip on a phone. `None` for the version is a
    # bare checkout, and the page omits it rather than rendering a guess.
    #
    # #148. Since when, as whom. Both are constant for the life of the
    # process, so a per request syscall for either is the shape this codebase
    # already refuses for the pane map. `getpass.getuser` consults passwd,
    # where `$USER` is inherited and lies under sudo, a unit and su; it raises
    # for a uid with no entry, the ordinary case in a container, and the
    # number is then the honest answer. Never a guessed name.
    try:
        account: str = user()
    except (KeyError, OSError, ImportError):
        account = str(os.getuid())
    server_facts = {
        "version": hitchrail.installed_version(),
        "user": account,
        "started_at": now(),
    }

    def facts() -> dict[str, object]:
        # `stop_timeout` rides here (#238) on #147's argument: the wait has
        # to be right before the settings page has ever been opened, and
        # this is the payload the page already fetches first. Read per
        # request because the settings route can change it.
        return {
            **server_facts,
            "stop_timeout": engine.prefs.stop_timeout(),
            # #242. Whether Stop wraps up first, and for how long, so the
            # dialog's deadline is right. Never the prompt itself: that is in
            # `/api/config`, behind the same token, and not in every listing.
            "stop_prompt_set": config.stop_prompt is not None,
            "stop_prompt_timeout": config.stop_prompt_timeout,
            # #239. So the wait dialog says a kill is coming before it does.
            "stop_policy": engine.prefs.stop_policy(),
        }

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
        except (*_UNPARSEABLE, KeyError, TypeError):
            return _error(400, "invalid_body", "a JSON body with a 'token' is required")
        if not isinstance(offered, str) or not sec.token_matches(offered, config.token):
            # The SAME answer a missing token gets from the middleware. A wrong
            # token and no token are already indistinguishable at the API, and
            # this route must not become the oracle the middleware refuses to
            # be.
            return _error(401, "unauthorized", "a valid token is required")
        response = JSONResponse({"ok": True})
        sec.set_token_cookie(response, config.token, secure=config.cookie_is_secure)
        return response

    return Starlette(
        routes=[
            *project_routes(engine, events, facts),
            *settings_routes(engine, config),
            *session_routes(engine),
            *live_routes(events, plugin_updates, run_plugins),
            Route(sec.GRANT_API_PATH, grant, methods=["POST"]),
            Route(sec.GRANT_PAGE_PATH, pages.grant_page, methods=["GET"]),
            Route("/", pages.page, methods=["GET"]),
            Route("/settings", pages.settings_page, methods=["GET"]),
            *[Route(p, pages.asset_route(p), methods=["GET"]) for p in pages.ASSETS],
        ],
        # OUTSIDE the three access controls, so a refusal carries the
        # headers too. A 400 host_rejected rendered without `nosniff` is the
        # same hole as a 200 without one, and refusals are the responses most
        # likely to be shown somewhere unexpected. It is separate from
        # `middleware_stack` rather than a fourth entry in it, because that
        # list answers "may this proceed" and this one refuses nothing (#77).
        middleware=[Middleware(SecurityHeadersMiddleware), *middleware_stack(config)],
        exception_handlers={HTTPException: _routing_error},
        max_body_size=MAX_BODY_BYTES,
        lifespan=make_lifespan(engine, events, plugin_updates),
    )
