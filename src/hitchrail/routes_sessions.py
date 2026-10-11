"""The session lifecycle routes: start, stop, restart, answer, kill and the signals.

Split out of `server.py` at #205 along what the handlers touch: every one of
these reaches the engine's mutating methods, and every one carries its own
refusal ladder. The ladders are written out at the route on purpose, never
mapped from exception type to code in one table: `docs/api.md` is checked
against them both ways, and a reader of a handler sees its refusals there.
"""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from hitchrail import discovery
from hitchrail import engine as eng
from hitchrail.routes_common import _UNPARSEABLE, _error, in_thread


def session_routes(engine: eng.Engine) -> list[Route]:
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
        except eng.OperatorDisabled as exc:
            return _error(409, "operator_disabled", str(exc))
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
        except eng.NoAgent as exc:
            # Its own code, not `stop_unsafe`, because the two lead somewhere
            # different. `stop_unsafe` means the screen could not be vouched
            # for and the answer is to go and look. This means there is nothing
            # here to ask, and for a stale session the answer is that a kill
            # clears it and loses nothing. One code for both would make a
            # client guess which it had.
            return _error(409, "no_agent", str(exc))
        except eng.StopRefused as exc:
            # 409 and not 503: nothing is broken and asking again changes
            # nothing. The session is in a state where this action is wrong,
            # which is what every other 409 on this API means.
            #
            # The agent was NOT left untouched, and an earlier comment here
            # said it was. The sequence clears the input box and interrupts
            # before it decides, so a refusal can follow an interrupted turn.
            # What did not happen is the exit command, which is why there is
            # nothing in flight and no stop to wait for.
            return _error(409, "stop_unsafe", str(exc))
        except eng.MachineUnreadable as exc:
            return _error(503, "machine_unreadable", str(exc))
        except discovery.RootUnavailable as exc:
            # #263. The stopped name's ladder lists the root, as on logs.
            return _error(503, "root_unavailable", str(exc))
        return JSONResponse(session.as_dict(), status_code=202)

    async def restart(request: Request) -> Response:
        """A stop that starts (#472). The ladder is `stop`'s, line for line,
        because the first half IS `stop`: a refusal here is a refusal there, with
        nothing marked. Written out, never mapped from `stop`'s, as the module
        says every ladder is."""
        name = request.path_params["name"]
        try:
            session = await in_thread(engine.restart, name)
        except eng.UnknownProject as exc:
            return _error(404, "unknown_project", str(exc))
        except eng.Protected as exc:
            return _error(423, "self_protected", str(exc))
        except eng.NotRunning as exc:
            return _error(409, "not_running", str(exc))
        except eng.NoAgent as exc:
            return _error(409, "no_agent", str(exc))
        except eng.StopRefused as exc:
            return _error(409, "stop_unsafe", str(exc))
        except eng.MachineUnreadable as exc:
            return _error(503, "machine_unreadable", str(exc))
        except discovery.RootUnavailable as exc:
            return _error(503, "root_unavailable", str(exc))
        return JSONResponse(session.as_dict(), status_code=202)

    async def stop_instead(request: Request) -> Response:
        """Call off a pending restart and leave the stop running (#511).

        DELETE on the restart's own path rather than a flag on the session's
        DELETE: on a `closing` row that DELETE is Exit now, which skips the
        wait, and folding "and do not start" into it would make one press mean
        two things. 200, not 202: the mark is gone by the time this answers,
        and the stop it leaves behind was already in flight.
        """
        name = request.path_params["name"]
        try:
            session = await in_thread(engine.cancel_restart, name)
        except eng.UnknownProject as exc:
            return _error(404, "unknown_project", str(exc))
        except eng.NotRestarting as exc:
            return _error(409, "not_restarting", f"no restart is pending for {exc}")
        except eng.MachineUnreadable as exc:
            return _error(503, "machine_unreadable", str(exc))
        except discovery.RootUnavailable as exc:
            return _error(503, "root_unavailable", str(exc))
        return JSONResponse(session.as_dict(), status_code=200)

    async def answer(request: Request) -> Response:
        """Carry one keypress to a prompt the operator read (#204).

        POST, not PUT, and not on the session path itself: this is not an
        update to the session, it is an event delivered to it. Same shape as
        `/kill` for the same reason.

        **The key is never taken from the path or the query string.** A body
        keeps it out of the journal, out of `Referer`, and out of any proxy log
        between a phone and this process. It is one keypress into a shell; it
        does not belong in a URL.

        409 rather than 400 when the screen no longer asks. The request was
        well formed and would have been honoured a moment earlier, which is a
        state conflict and not a client mistake, and the interface tells the
        operator to look again rather than to fix their request.
        """
        name = request.path_params["name"]
        try:
            body = await request.json()
            key = body["key"]
        except (*_UNPARSEABLE, TypeError, KeyError):
            return _error(400, "invalid_body", "a JSON body with a 'key' is required")
        if not isinstance(key, str):
            return _error(400, "invalid_body", "a JSON body with a 'key' is required")
        # 400 and not 409. A key outside the set is refused whatever the screen
        # is doing, so it is a malformed request rather than a state conflict,
        # and a client that gets 409 would reasonably retry it forever.
        #
        # The adapter checks this again before it reads any pane. Two guards on
        # purpose: this one is for the status code, that one is the guard.
        if key not in eng.ANSWER_KEYS:
            return _error(400, "invalid_key", f"{key!r} is not a key Hitchrail will send")
        try:
            session = await in_thread(engine.answer, name, key)
        except eng.UnknownProject as exc:
            return _error(404, "unknown_project", str(exc))
        except eng.Protected as exc:
            return _error(423, "self_protected", str(exc))
        except eng.NotRunning as exc:
            return _error(409, "not_running", str(exc))
        except eng.NoAgent as exc:
            return _error(409, "no_agent", str(exc))
        except eng.NotAsking as exc:
            return _error(409, "not_asking", str(exc))
        except eng.MachineUnreadable as exc:
            return _error(503, "machine_unreadable", str(exc))
        except discovery.RootUnavailable as exc:
            return _error(503, "root_unavailable", str(exc))  # #263, the fourth route
        return JSONResponse(session.as_dict(), status_code=200)

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
        except eng.NoAgent as exc:
            # A detached agent has no session for this route to kill (#83). It
            # answered 200 while the agent went on running, which a client
            # cannot tell from a kill that worked.
            return _error(409, "no_agent", str(exc))
        except eng.MachineUnreadable as exc:
            return _error(503, "machine_unreadable", str(exc))
        except discovery.RootUnavailable as exc:
            return _error(503, "root_unavailable", str(exc))  # #263, as on logs
        return JSONResponse(session.as_dict(), status_code=200)

    async def signal_detached(request: Request) -> Response:
        """SIGTERM to an agent nothing addressable owns (#107); `/force` below
        is SIGKILL, a second explicit request on its own route.

        202 rather than 200: the signal was delivered and nothing waited for
        the process to leave, because a graceful end can take as long as the
        agent needs and the listing will show the row go. Every refusal is
        its own code, since a person acts differently on each: attach there
        (`owned_elsewhere`), look again (`gone`, `not_ours`), or stop asking
        this machine (`pidfd_unavailable`).
        """
        return await _signal(request, force=False)

    async def signal_force(request: Request) -> Response:
        return await _signal(request, force=True)

    async def _signal(request: Request, *, force: bool) -> Response:
        name = request.path_params["name"]
        # #279: an OPTIONAL `{"pid": N}`, the pid the person confirmed. No
        # body is today's request, so an older page or a script keeps working;
        # a body that is there must say what it means, because a pid we could
        # not read and then ignored would be the unbound signal this exists to
        # remove.
        seen_pid: int | None = None
        if (await request.body()).strip():
            try:
                body = await request.json()
            except _UNPARSEABLE:
                return _error(400, "invalid_body", "the body, when sent, must be JSON")
            if not isinstance(body, dict):
                return _error(400, "invalid_body", "the body, when sent, must be a JSON object")
            # Any other key is refused rather than ignored (#400): `{"PID": 901}`
            # was read as no pid and sent the unbound signal. `{}` asks for no
            # binding, as no body does, so it stays today's request.
            for key in body:
                if key != "pid":
                    return _error(400, "invalid_body", f"{key!r} is not a key this body takes")
            if "pid" in body:
                seen_pid = body["pid"]
                # bool is an int subclass, and `true` is not a pid.
                if type(seen_pid) is not int or seen_pid <= 0:
                    return _error(400, "invalid_body", "'pid' must be a positive integer")
        try:
            session = await in_thread(engine.signal_detached, name, force, seen_pid)
        except eng.UnknownProject as exc:
            return _error(404, "unknown_project", str(exc))
        except eng.Protected as exc:
            return _error(423, "self_protected", str(exc))
        except eng.NotDetached as exc:
            return _error(409, "not_detached", str(exc))
        except eng.OwnedElsewhere as exc:
            return _error(
                409, "owned_elsewhere", str(exc), session=exc.session, server_pid=exc.server_pid
            )
        except eng.Gone as exc:
            return _error(409, "gone", str(exc))
        except eng.NotOurs as exc:
            return _error(409, "not_ours", str(exc))
        except eng.PidfdUnavailable as exc:
            return _error(501, "pidfd_unavailable", str(exc))
        except eng.MachineUnreadable as exc:
            return _error(503, "machine_unreadable", str(exc))
        except discovery.RootUnavailable as exc:
            return _error(503, "root_unavailable", str(exc))  # #263, as on logs
        return JSONResponse(session.as_dict(), status_code=202)

    return [
        Route("/api/sessions/{name}", start, methods=["POST"]),
        Route("/api/sessions/{name}", stop, methods=["DELETE"]),
        # Its own route, deliberately. #52 and the design's section 6.
        Route("/api/sessions/{name}/answer", answer, methods=["POST"]),
        Route("/api/sessions/{name}/kill", kill, methods=["POST"]),
        # A stop that starts (#472): its own route, never a flag on DELETE.
        Route("/api/sessions/{name}/restart", restart, methods=["POST"]),
        Route("/api/sessions/{name}/restart", stop_instead, methods=["DELETE"]),
        Route("/api/sessions/{name}/signal", signal_detached, methods=["POST"]),
        Route("/api/sessions/{name}/signal/force", signal_force, methods=["POST"]),
    ]
