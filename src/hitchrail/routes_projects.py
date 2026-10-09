"""The project routes: the listing, creating a folder, and what can be read of
one project (its log, its log page, its session link).

Split out of `server.py` at #205. The listing is the route the interface polls
hardest, so its one-scan argument lives here beside the others.
"""

from __future__ import annotations

from collections.abc import Callable

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from hitchrail import discovery, pages
from hitchrail import engine as eng
from hitchrail.events import EventBus
from hitchrail.routes_common import _UNPARSEABLE, _error, in_thread


def project_routes(
    engine: eng.Engine, events: EventBus, facts: Callable[[], dict[str, object]]
) -> list[Route]:
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
            listing = discovery.scan_roots(engine.prefs.active_roots())
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
                # Every root the interface shows, labelled. One root is still
                # a list, because #119 made the qualified form universal and
                # a client that special cased "one root" would be wrong the
                # day a second was added. Hidden ones are named beside it so
                # an empty page can say so (#154); the settings route is
                # where they are listed in full.
                "roots": [
                    {"label": r.label, "path": str(r.path)} for r in engine.prefs.active_roots()
                ],
                "hidden_roots": list(engine.prefs.hidden_roots()),
                # Of those, the ones a request can bring back (#256): the
                # empty state told somebody to show a root in settings that
                # the operator's file disables, where there is no checkbox.
                "hidden_roots_editable": list(engine.prefs.hidden_roots_a_request_can_show()),
                # This server rather than this machine: what a person holding
                # a phone needs before trusting the rest of the page (#147).
                "server": facts(),
            }
        )

    async def create_project(request: Request) -> Response:
        try:
            payload = await request.json()
            name = str(payload["name"])
        except (*_UNPARSEABLE, KeyError, TypeError):
            # A malformed body is a bad name, not a server fault. Returning 500
            # here would put a traceback where a client expects a code.
            return _error(400, "invalid_name", "a JSON body with a 'name' is required")
        try:
            await in_thread(discovery.create_in_root, engine.prefs.active_roots(), name)
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
        except discovery.RootUnavailable as exc:
            # #249. A stopped name's ladder lists the root to tell "unknown"
            # from "not running", and a root that has gone away raises here
            # rather than in the listing. The same answer the listing gives.
            return _error(503, "root_unavailable", str(exc))
        # No `Protected` arm, and that is not an oversight. `engine.logs`
        # deliberately does not refuse the self project: reading the log of the
        # session hosting Hitchrail is harmless and occasionally the only way
        # to see what it is doing. An arm here could never fire, and this
        # project treats a guard that cannot execute as worse than none.
        return JSONResponse({"name": name, "text": text})

    async def logs_page(request: Request) -> Response:
        """The logs page (#151). A project name in a PAGE route's path, and the
        first one, so the name is resolved by `engine.locate`, the same
        function the logs API climbs, and refused with the same envelope: a
        page that validated less strictly than the sub-route it mirrors is
        the asymmetry that gets missed. A stopped project renders, and the
        page says so; an unknown one refuses rather than rendering an empty
        tail that reads as "printed nothing"."""
        name = request.path_params["name"]
        try:
            await in_thread(engine.locate, name)
        except eng.UnknownProject as exc:
            return _error(404, "unknown_project", str(exc))
        except eng.MachineUnreadable as exc:
            return _error(503, "machine_unreadable", str(exc))
        except discovery.RootUnavailable as exc:
            return _error(503, "root_unavailable", str(exc))  # #249, as the API
        return await pages.logs_page(request)

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
        except discovery.RootUnavailable as exc:
            return _error(503, "root_unavailable", str(exc))  # #263, the fifth route
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

    return [
        Route("/api/projects", list_projects, methods=["GET"]),
        Route("/api/projects", create_project, methods=["POST"]),
        Route("/api/sessions/{name}/logs", logs, methods=["GET"]),
        Route("/api/sessions/{name}/url", session_url, methods=["GET"]),
        Route("/logs/{name}", logs_page, methods=["GET"]),
    ]
