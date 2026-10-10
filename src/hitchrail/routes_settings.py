"""The configuration routes: what the interface may read of the instance, and
the little of it a request may change.

Split out of `server.py` at #205. `EDITABLE_TOP_LEVEL` and
`EDITABLE_ROOT_FIELDS` moved with the handler that walks them, so the literal
and its only reader stay in one file.
"""

from __future__ import annotations

from pathlib import Path

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from hitchrail import engine as eng
from hitchrail.agents import Agents
from hitchrail.config import Config
from hitchrail.routes_common import _UNPARSEABLE, _error, in_thread, logger

# #154, #238. WHAT A REQUEST MAY CHANGE, as a literal. `PATCH /api/config`
# walks a body of `{"roots": {"<label>": {"enabled": bool}}, "stop_timeout":
# int}` and refuses any key that is not named here, so the perimeter (a
# root's path, the bind, the allowlists, the token, `agent_binary`,
# `session_prefix`, `self_project`, and #242's `stop_prompt`, which a
# request setting would make a route that types arbitrary text) cannot
# become editable by an edit elsewhere: adding a name to either set is the
# only way, and `tests/test_settings_route.py` asserts both sets member by
# member. The test for membership is #238's: does changing this let a request
# do anything a request with the token cannot already do? A longer wait does
# not; hiding a configured root does not. `stop_policy` (#409) passes it
# too, and was held back from #239 for a while because it is the closest
# call: `end_anyway` is a kill nobody tapped, but only of a session a request
# already asked to stop, which the same token could Kill outright. Andrea
# decided it on 2026-10-01; the file and the flag still pin it, in
# `Preferences`. The label between the two levels is validated by membership
# in the configured set, in the engine.
EDITABLE_TOP_LEVEL = frozenset({"roots", "stop_timeout", "stop_policy"})
EDITABLE_ROOT_FIELDS = frozenset({"enabled"})


def settings_routes(engine: eng.Engine, config: Config) -> list[Route]:
    async def get_config(request: Request) -> Response:
        """The effective configuration, every value with its source, and
        never the token (#238). What a person on a phone needs to answer
        "what is this instance pointed at" without SSH."""
        return JSONResponse(_config_view())

    async def patch_config(request: Request) -> Response:
        """Change what the interface may change, and nothing else (#154, #238).

        The ticket's argument in one line: a route that added a root would
        turn a shell equivalent API into a shell equivalent API with no
        directory restriction. So the body carries LABELS, checked by
        membership in the configured set, and a boolean each, plus the one
        policy value. There is no field a path could travel in, and
        `EDITABLE_TOP_LEVEL` and `EDITABLE_ROOT_FIELDS` are the whole of what
        is accepted.

        PATCH rather than POST because it is a partial update to one
        resource, the configuration, and the response is that resource as it
        now stands. Every key is checked before anything is applied, so a
        body with one bad key changes nothing.
        """
        try:
            body = await request.json()
        except _UNPARSEABLE:
            return _error(400, "invalid_body", "a JSON object is required")
        if not isinstance(body, dict):
            return _error(400, "invalid_body", "a JSON object is required")
        for key in body:
            if key not in EDITABLE_TOP_LEVEL:
                return _error(400, "not_editable", f"{key!r} is not editable")
        roots = body.get("roots", {})
        if not isinstance(roots, dict):
            return _error(400, "invalid_body", "'roots' must be an object keyed by label")
        changes: dict[str, bool] = {}
        for label, fields in roots.items():
            if not isinstance(fields, dict):
                return _error(400, "invalid_body", f"roots[{label!r}] must be an object")
            for key, value in fields.items():
                field = f"roots[{label!r}].{key}"
                if key not in EDITABLE_ROOT_FIELDS:
                    return _error(400, "not_editable", f"{field} is not editable")
                if not isinstance(value, bool):
                    return _error(400, "invalid_body", f"{field} must be a boolean")
                changes[label] = value
        if "stop_timeout" in body and body["stop_timeout"] is None:
            # `None` is "not in this request" one layer down, so a JSON null
            # is refused here rather than read as no change and answered 200.
            return _error(
                400, "invalid_value", "stop_timeout must be a whole number of seconds"
            )
        if "stop_policy" in body and body["stop_policy"] is None:
            return _error(400, "invalid_value", "stop_policy must be ask or end_anyway")
        try:
            # Both halves in ONE call, checked together before either is
            # written: applied in sequence, a refused timeout left the roots
            # half already on disk (Phase 14 review, round 1).
            await in_thread(
                engine.prefs.apply, changes, body.get("stop_timeout"), body.get("stop_policy")
            )
        except eng.UnknownRoot as exc:
            return _error(404, "unknown_root", str(exc))
        except eng.OperatorDisabled as exc:
            return _error(409, "operator_disabled", str(exc))
        except eng.OperatorPinned as exc:
            return _error(409, "operator_pinned", str(exc))
        except eng.InvalidValue as exc:
            return _error(400, "invalid_value", str(exc))
        except eng.StateUnwritable as exc:
            return _error(503, "state_unwritable", str(exc))
        if "stop_policy" in body:
            # The startup block names the policy it started with; a kill
            # nobody tapped later needs the journal to say when that changed.
            logger.info("stop policy is %s, set by a request", engine.prefs.stop_policy())
        return JSONResponse(_config_view())

    def _text(path: Path | None) -> str | None:
        return None if path is None else str(path)

    def _config_view() -> dict[str, object]:
        """Read only values as `{value, source}`; the two a request may write
        carry `editable` too. The token is its source alone."""
        src = config.sources
        agents = {c.ident: c for c in Agents(config).all()}

        def shown(name: str, value: object) -> dict[str, object]:
            return {"value": value, "source": src.get(name, "default")}

        prefs = engine.prefs
        agent_of = {root.label: root.agent for root in config.roots}
        return {
            "roots": [
                {
                    "label": v.label,
                    "path": str(v.path),
                    "enabled": v.enabled,
                    "editable": v.editable,
                    "source": src.get("roots", "default"),
                    # #290. The operator's identifier, never a vendor's.
                    "agent": agent_of[v.label],
                }
                for v in prefs.root_views()
            ],
            # #290. Read only, like the roots that name them: which agents
            # exist is the operator's file, never a request's.
            "agents": {
                "value": {
                    ident: {
                        "package": spec.package,
                        "binary": spec.agent_binary,
                        # #294. The plugin update runs the default agent's
                        # binary only, so the page names what it leaves out.
                        "plugins": agents[ident].agent.has_plugins,
                    }
                    for ident, spec in config.agents.items()
                },
                "source": src.get("agents", "default"),
            },
            "hidden_roots": list(prefs.hidden_roots()),
            "stop_timeout": {
                "value": prefs.stop_timeout(),
                "source": prefs.stop_timeout_source(),
                "editable": prefs.stop_timeout_editable(),
            },
            "host": shown("host", config.host),
            "port": shown("port", config.port),
            "allow_hosts": shown("extra_hosts", list(config.extra_hosts)),
            "allow_origins": shown("extra_origins", list(config.extra_origins)),
            "self_project": shown("self_project", config.self_project),
            "agent_binary": shown("agent_binary", config.agent_binary),
            "session_prefix": shown("session_prefix", config.session_prefix),
            # #242. Read only: a request that could set what Stop TYPES would
            # be the free text input the roadmap defers.
            "stop_prompt": shown("stop_prompt", config.stop_prompt),
            "stop_prompt_timeout": shown("stop_prompt_timeout", config.stop_prompt_timeout),
            # #409. Editable unless the flag or the config file set it.
            "stop_policy": {
                "value": prefs.stop_policy(),
                "source": prefs.stop_policy_source(),
                "editable": prefs.stop_policy_editable(),
            },
            # The certificate's path, or none: what "is this HTTPS" needs.
            "tls": shown("tls", _text(config.tls_cert)),
            "expect_gateway_mac": shown("expect_gateway_mac", config.expect_gateway_mac),
            "hard_floor_mb": shown("hard_floor_mb", config.hard_floor_mb),
            "soft_floor_mb": shown("soft_floor_mb", config.soft_floor_mb),
            "session_mb": shown("session_mb", config.session_mb),
            # Never the value. Its source says whether a token exists at all
            # ("none" on a loopback bind) and where it came from.
            "token": {"source": src.get("token", "none") if config.token else "none"},
            # The path that was READ, carried on Config, not derived back
            # from `state_path`: `--config /etc/hitchrail/prod.toml` showed
            # `/etc/hitchrail/config.toml`, a file never opened.
            "config_file": shown("config", _text(config.config_path)),
            "state_file": {"value": _text(config.state_path)},
        }

    return [
        Route("/api/config", get_config, methods=["GET"]),
        Route("/api/config", patch_config, methods=["PATCH"]),
    ]
