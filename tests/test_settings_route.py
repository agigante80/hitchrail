"""`PATCH /api/config` (#154): the interface's one power over the roots.

The ticket's constraint in one line: the UI must not be able to name a path.
So the route takes labels, checked by membership in the configured set, and a
boolean each, and the last two tests here are the ones that outlive the
route: the editable subset is a literal asserted member by member (premortem
3 of the Phase 14 plan), and no route in the real route table takes a path,
in its template or in the body it parses.
"""

from __future__ import annotations

import ast
import pathlib
import re
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from starlette.routing import Route

from conftest import FakeTmux, procs_from
from hitchrail import server
from hitchrail.config import Config
from hitchrail.engine import Engine
from hitchrail.events import EventBus
from hitchrail.roots import Root
from hitchrail.server import create_app
from test_api import NO_AGENT_CONFIG, PLENTY, make_engine

pytestmark = pytest.mark.integration

HEADERS = {"host": "localhost", "origin": "http://localhost:8787"}

# `work~vessel` runs; `home~attic` is stopped. Hiding `work` must leave the
# session in `work~vessel` alive and addressable.
RUNNING_PS = """\
 500     1   4096   600 tmux new-session -d -s hr-work~vessel
 501   500 512000   600 claude --dangerously-skip-permissions --remote-control work~vessel
"""


@pytest.fixture
def config(tmp_path: pathlib.Path) -> Config:
    for folder in ("work/vessel", "home/attic", "vault/secret"):
        (tmp_path / folder).mkdir(parents=True)
    return Config(
        roots=(
            Root(label="work", path=(tmp_path / "work").resolve()),
            Root(label="home", path=(tmp_path / "home").resolve()),
            # Disabled by the operator's file: configured, hidden, and not a
            # request's to enable.
            Root(label="vault", path=(tmp_path / "vault").resolve(), enabled=False),
        ),
        state_path=tmp_path / "state" / "state.toml",
        sessions_dir=tmp_path / ".sessions",
        agent_config_path=NO_AGENT_CONFIG,
    )


@pytest.fixture
def tmux() -> FakeTmux:
    return FakeTmux(sessions={"work~vessel": 500})


@pytest.fixture
def engine(config: Config, tmux: FakeTmux) -> Engine:
    return make_engine(config, tmux, procs_from(RUNNING_PS), PLENTY)


@pytest.fixture
async def client(engine: Engine, config: Config) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(engine=engine, config=config, bus=EventBus())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as c:
        yield c


async def _listing(client: httpx.AsyncClient) -> dict[str, Any]:
    r = await client.get("/api/projects", headers=HEADERS)
    assert r.status_code == 200
    body: dict[str, Any] = r.json()
    return body


async def test_the_listing_shows_the_active_roots_and_names_the_hidden(
    client: httpx.AsyncClient,
) -> None:
    body = await _listing(client)
    assert [r["label"] for r in body["roots"]] == ["work", "home"]
    assert body["hidden_roots"] == ["vault"]
    # The listing sorts by folder, which is the name a person reads.
    assert [p["name"] for p in body["projects"]] == ["work~vessel", "home~attic"]


async def test_hiding_a_root_removes_its_projects_and_keeps_its_session(
    client: httpx.AsyncClient, tmux: FakeTmux, config: Config
) -> None:
    """The unhappy path the ticket names: a root toggled off while one of its
    projects is RUNNING. Hiding is not stopping. The agent is not killed, and
    its session still answers by name, so a person who hid the root by
    mistake can still stop the agent from the logs page."""
    r = await client.patch(
        "/api/config", json={"roots": {"work": {"enabled": False}}}, headers=HEADERS
    )
    assert r.status_code == 200
    assert [(v["label"], v["enabled"], v["editable"]) for v in r.json()["roots"]] == [
        ("work", False, True),
        ("home", True, True),
        ("vault", False, False),
    ]
    assert [v["path"] for v in r.json()["roots"]] == [str(root.path) for root in config.roots]
    body = await _listing(client)
    assert [x["label"] for x in body["roots"]] == ["home"]
    assert body["hidden_roots"] == ["work", "vault"]
    assert [p["name"] for p in body["projects"]] == ["home~attic"]
    assert tmux.killed == []
    # Still a session: the graceful stop is accepted, not "unknown project".
    r = await client.delete("/api/sessions/work~vessel", headers=HEADERS)
    assert r.status_code == 202, r.text
    # And back. The choice was reversible and nothing about the root changed.
    r = await client.patch(
        "/api/config", json={"roots": {"work": {"enabled": True}}}, headers=HEADERS
    )
    assert r.status_code == 200
    body = await _listing(client)
    assert [x["label"] for x in body["roots"]] == ["work", "home"]


async def test_the_choice_persists_to_the_state_file_and_a_new_process_reads_it(
    client: httpx.AsyncClient, config: Config, tmux: FakeTmux
) -> None:
    r = await client.patch(
        "/api/config", json={"roots": {"home": {"enabled": False}}}, headers=HEADERS
    )
    assert r.status_code == 200
    assert config.state_path is not None
    assert 'disabled = ["home"]' in config.state_path.read_text()
    fresh = make_engine(config, tmux, procs_from(RUNNING_PS), PLENTY)
    assert [x.label for x in fresh.prefs.active_roots()] == ["work"]


VAULT_PS = """\
 700     1   4096   600 tmux new-session -d -s hr-vault~secret
 701   700 512000   600 claude --dangerously-skip-permissions --remote-control vault~secret
"""


async def test_nothing_starts_in_an_operator_disabled_root_and_what_runs_there_can_stop(
    config: Config,
) -> None:
    """The security audit's reading of the README's `confidential` example:
    `enabled = false` means no agent runs there, not only that the row is
    off the list. Start is refused before anything is spawned; stop still
    resolves the name, because an agent already there must be endable."""
    tmux = FakeTmux(sessions={"vault~secret": 700})
    engine = make_engine(config, tmux, procs_from(VAULT_PS), PLENTY)
    app = create_app(engine=engine, config=config, bus=EventBus())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost"
    ) as c:
        # A folder with nothing running: refused, and nothing was started.
        (config.roots[2].path / "ledger").mkdir()
        r = await c.post("/api/sessions/vault~ledger", headers=HEADERS)
        assert r.status_code == 409, r.text
        assert r.json()["code"] == "operator_disabled"
        assert tmux.started == []
        # The one already running: stoppable by name.
        r = await c.delete("/api/sessions/vault~secret", headers=HEADERS)
        assert r.status_code == 202, r.text
        # A root the INTERFACE hid is not refused: hiding is a preference.
        r = await c.patch(
            "/api/config", json={"roots": {"home": {"enabled": False}}}, headers=HEADERS
        )
        assert r.status_code == 200
        r = await c.post("/api/sessions/home~attic", headers=HEADERS)
        assert r.status_code != 409 or r.json()["code"] != "operator_disabled", r.text


async def test_creating_a_project_in_a_hidden_root_is_refused(
    client: httpx.AsyncClient, config: Config
) -> None:
    """The sheet creates in what it shows. A hidden root is not offered, and a
    request that names one anyway is refused the way any unknown label is,
    with nothing created."""
    r = await client.patch(
        "/api/config", json={"roots": {"work": {"enabled": False}}}, headers=HEADERS
    )
    assert r.status_code == 200
    r = await client.post("/api/projects", json={"name": "work~fresh"}, headers=HEADERS)
    assert r.status_code == 400
    assert r.json()["code"] == "invalid_name"
    assert not (config.roots[0].path / "fresh").exists()


# -- the refusals -----------------------------------------------------------


@pytest.mark.parametrize(
    "label",
    [
        "nope",
        "/etc",
        "../etc",
        "..%2f..%2fetc",
        "work/../../etc",
        "/",
        "",
    ],
)
async def test_a_label_that_is_not_configured_is_a_404_and_changes_nothing(
    client: httpx.AsyncClient, config: Config, label: str
) -> None:
    """A path in the label's place is an unknown label. Membership in the
    configured set is the whole check, allowlist not pattern, so there is no
    shape a path could take that gets it past this."""
    r = await client.patch(
        "/api/config",
        json={"roots": {label: {"enabled": False}, "work": {"enabled": False}}},
        headers=HEADERS,
    )
    assert r.status_code == 404
    assert r.json()["code"] == "unknown_root"
    assert config.state_path is not None
    assert not config.state_path.exists()
    body = await _listing(client)
    assert [x["label"] for x in body["roots"]] == ["work", "home"]


async def test_a_request_cannot_enable_what_the_operator_disabled(
    client: httpx.AsyncClient,
) -> None:
    r = await client.patch(
        "/api/config", json={"roots": {"vault": {"enabled": True}}}, headers=HEADERS
    )
    assert r.status_code == 409
    assert r.json()["code"] == "operator_disabled"
    body = await _listing(client)
    assert body["hidden_roots"] == ["vault"]


@pytest.mark.parametrize(
    ("body", "code", "fragment"),
    [
        # The perimeter, by name. Each of these is what premortem 3 is about.
        ({"roots": {"work": {"path": "/etc"}}}, "not_editable", "path"),
        ({"roots": {"work": {"label": "etc"}}}, "not_editable", "label"),
        ({"roots": {"etc": {"path": "/etc", "enabled": True}}}, "not_editable", "path"),
        ({"host": "0.0.0.0"}, "not_editable", "host"),
        ({"agent_binary": "sh"}, "not_editable", "agent_binary"),
        ({"session_prefix": "x-"}, "not_editable", "session_prefix"),
        ({"token": "abc"}, "not_editable", "token"),
        ({"stop_prompt": "rm -rf"}, "not_editable", "stop_prompt"),
        ({"hard_floor_mb": 0}, "not_editable", "hard_floor_mb"),
        # One bad key beside a good one: nothing is applied.
        ({"stop_timeout": 45, "host": "0.0.0.0"}, "not_editable", "host"),
        ({"stop_timeout": "45"}, "invalid_value", "whole number"),
        ({"stop_timeout": 0}, "invalid_value", "positive"),
        ({"stop_timeout": True}, "invalid_value", "whole number"),
        ({"stop_timeout": None}, "invalid_value", "whole number"),
        # Malformed shapes, all 400 and none of them a state change.
        ({"roots": {"work": {"enabled": "false"}}}, "invalid_body", "boolean"),
        ({"roots": {"work": {"enabled": 0}}}, "invalid_body", "boolean"),
        ({"roots": {"work": False}}, "invalid_body", "object"),
        ({"roots": ["work"]}, "invalid_body", "object"),
        (["roots"], "invalid_body", "object"),
        ("roots", "invalid_body", "object"),
    ],
)
async def test_anything_but_the_editable_subset_is_refused(
    client: httpx.AsyncClient, config: Config, body: object, code: str, fragment: str
) -> None:
    r = await client.patch("/api/config", json=body, headers=HEADERS)
    assert r.status_code == 400, r.text
    assert r.json()["code"] == code
    assert fragment in r.json()["message"]
    assert config.state_path is not None
    assert not config.state_path.exists()


async def test_get_config_shows_every_value_with_its_source_and_never_the_token(
    client: httpx.AsyncClient, config: Config
) -> None:
    r = await client.get("/api/config", headers=HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert body["token"] == {"source": "none"}
    assert body["host"] == {"value": "127.0.0.1", "source": "default"}
    assert body["stop_timeout"] == {"value": 30.0, "source": "default", "editable": True}
    assert body["session_prefix"] == {"value": "hr-", "source": "default"}
    assert [(v["label"], v["enabled"], v["editable"]) for v in body["roots"]] == [
        ("work", True, True),
        ("home", True, True),
        ("vault", False, False),
    ]
    assert body["hidden_roots"] == ["vault"]
    assert body["state_file"] == {"value": str(config.state_path)}
    # Everything a flag can set is on the page, by the name the flag uses.
    for name in ("port", "allow_hosts", "allow_origins", "self_project", "agent_binary"):
        assert set(body[name]) == {"value", "source"}, name


async def test_the_sources_the_cli_computes_reach_the_page(tmp_path: pathlib.Path) -> None:
    """A value equal to its default is not a default: `--stop-timeout 30`
    given is `flag`, and the page shows it pinned. The token's source is
    reported and its value is not."""
    from hitchrail.cli import build_config, parse_args

    (tmp_path / "work").mkdir()
    argv = [
        "--root",
        f"work={tmp_path / 'work'}",
        "--stop-timeout=30",
        "--host",
        "0.0.0.0",
        "--token",
        "s3cret-token-value",
    ]
    cfg = build_config(parse_args(argv))
    assert cfg.sources["stop_timeout"] == "flag"
    assert cfg.sources["host"] == "flag"
    assert cfg.sources["token"] == "flag"
    assert cfg.sources["port"] == "default"
    assert cfg.sources["roots"] == "flag"
    engine = make_engine(cfg, FakeTmux(), procs_from(""), PLENTY)
    app = create_app(engine=engine, config=cfg, bus=EventBus())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost"
    ) as c:
        auth = {**HEADERS, "authorization": "Bearer s3cret-token-value"}
        body = (await c.get("/api/config", headers=auth)).json()
        assert body["stop_timeout"] == {"value": 30, "source": "flag", "editable": False}
        assert body["token"] == {"source": "flag"}
        assert "s3cret" not in str(body)
        r = await c.patch("/api/config", json={"stop_timeout": 45}, headers=auth)
        assert r.status_code == 409
        assert r.json()["code"] == "operator_pinned"
        assert (await c.get("/api/projects", headers=auth)).json()["server"][
            "stop_timeout"
        ] == 30


async def test_a_stop_timeout_change_reaches_the_listing_and_persists(
    client: httpx.AsyncClient, config: Config, tmux: FakeTmux
) -> None:
    """The browser reads the wait from the listing's `server` object, so a
    change here is right on the next poll and before the settings page has
    ever been opened (#238 on #147's argument)."""
    before = await _listing(client)
    assert before["server"]["stop_timeout"] == 30.0
    r = await client.patch("/api/config", json={"stop_timeout": 45}, headers=HEADERS)
    assert r.status_code == 200
    assert r.json()["stop_timeout"] == {"value": 45, "source": "state", "editable": True}
    after = await _listing(client)
    assert after["server"]["stop_timeout"] == 45
    assert config.state_path is not None
    assert "stop_timeout = 45" in config.state_path.read_text()
    fresh = make_engine(config, tmux, procs_from(RUNNING_PS), PLENTY)
    assert fresh.prefs.stop_timeout() == 45


async def test_a_valid_toggle_beside_a_refused_timeout_writes_nothing(
    client: httpx.AsyncClient, config: Config
) -> None:
    """Round 1 of the Phase 14 review: the halves were applied in sequence,
    so this body hid `work` and wrote it to disk before `stop_timeout: 0`
    was refused. One request is one write, or none."""
    r = await client.patch(
        "/api/config",
        json={"roots": {"work": {"enabled": False}}, "stop_timeout": 0},
        headers=HEADERS,
    )
    assert r.status_code == 400
    assert r.json()["code"] == "invalid_value"
    assert config.state_path is not None
    assert not config.state_path.exists()
    body = await _listing(client)
    assert [x["label"] for x in body["roots"]] == ["work", "home"]
    # And the other way round: a bad label beside a good timeout.
    r = await client.patch(
        "/api/config",
        json={"roots": {"nope": {"enabled": False}}, "stop_timeout": 45},
        headers=HEADERS,
    )
    assert r.status_code == 404
    assert not config.state_path.exists()
    assert (await _listing(client))["server"]["stop_timeout"] == 30.0


async def test_the_config_file_shown_is_the_one_that_was_read(tmp_path: pathlib.Path) -> None:
    """`--config /etc/hitchrail/prod.toml` used to show `config.toml` beside
    the state file, a path never opened (Phase 14 review, round 1)."""
    from hitchrail.cli import build_config, parse_args

    (tmp_path / "work").mkdir()
    custom = tmp_path / "prod.toml"
    custom.write_text(f'[[roots]]\nlabel = "work"\npath = "{tmp_path / "work"}"\n')
    custom.chmod(0o644)
    cfg = build_config(parse_args(["--config", str(custom)]))
    engine = make_engine(cfg, FakeTmux(), procs_from(""), PLENTY)
    app = create_app(engine=engine, config=cfg, bus=EventBus())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost"
    ) as c:
        body = (await c.get("/api/config", headers=HEADERS)).json()
    assert body["config_file"] == {"value": str(custom), "source": "flag"}
    assert body["state_file"] == {"value": str(tmp_path / "state.toml")}


async def test_a_body_that_is_not_json_is_invalid_body(client: httpx.AsyncClient) -> None:
    r = await client.patch("/api/config", content=b"{not json", headers=HEADERS)
    assert r.status_code == 400
    assert r.json()["code"] == "invalid_body"


async def test_a_state_file_that_cannot_be_written_is_a_503_and_nothing_changes(
    engine: Engine, config: Config, tmp_path: pathlib.Path
) -> None:
    assert config.state_path is not None
    config.state_path.parent.parent.mkdir(exist_ok=True)
    # A FILE where the state directory should be, so the write fails.
    config.state_path.parent.write_text("in the way")
    app = create_app(engine=engine, config=config, bus=EventBus())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost"
    ) as c:
        r = await c.patch(
            "/api/config", json={"roots": {"work": {"enabled": False}}}, headers=HEADERS
        )
        assert r.status_code == 503
        assert r.json()["code"] == "state_unwritable"
        assert "state.toml" in r.json()["message"]
        body = await _listing(c)
    assert [x["label"] for x in body["roots"]] == ["work", "home"]


async def test_the_settings_page_is_served_behind_the_token(
    client: httpx.AsyncClient, config: Config, tmux: FakeTmux
) -> None:
    """The page itself, and that it names nothing about the machine: it is
    the same bytes for every instance and fetches `/api/config` itself."""
    response = await client.get("/settings", headers=HEADERS)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "settings.js" in response.text
    assert str(config.roots[0].path) not in response.text
    remote = Config(
        roots=config.roots, host="0.0.0.0", token="s3cret-token-value", state_path=None
    )
    engine = make_engine(remote, tmux, procs_from(""), PLENTY)
    app = create_app(engine=engine, config=remote, bus=EventBus())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost"
    ) as c:
        for path in ("/settings", "/settings.js", "/api/config"):
            assert (await c.get(path, headers=HEADERS)).status_code == 401, path


# -- the perimeter controls apply to this route too --------------------------


async def test_get_config_with_a_forged_host_is_refused(client: httpx.AsyncClient) -> None:
    r = await client.get("/api/config", headers={**HEADERS, "host": "evil.example"})
    assert r.status_code == 400
    assert r.json()["code"] == "host_rejected"


async def test_the_toggle_without_an_origin_is_refused(client: httpx.AsyncClient) -> None:
    r = await client.patch(
        "/api/config",
        json={"roots": {"work": {"enabled": False}}},
        headers={"host": "localhost"},
    )
    assert r.status_code == 403
    assert r.json()["code"] == "origin_missing"


async def test_the_toggle_with_a_forged_host_is_refused(client: httpx.AsyncClient) -> None:
    r = await client.patch(
        "/api/config",
        json={"roots": {"work": {"enabled": False}}},
        headers={**HEADERS, "host": "evil.example"},
    )
    assert r.status_code == 400
    assert r.json()["code"] == "host_rejected"


async def test_the_toggle_needs_the_token_off_loopback(config: Config, tmux: FakeTmux) -> None:
    remote = Config(
        roots=config.roots,
        host="0.0.0.0",
        token="s3cret-token-value",
        state_path=config.state_path,
        sessions_dir=config.sessions_dir,
        agent_config_path=NO_AGENT_CONFIG,
    )
    engine = make_engine(remote, tmux, procs_from(RUNNING_PS), PLENTY)
    app = create_app(engine=engine, config=remote, bus=EventBus())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost"
    ) as c:
        r = await c.patch(
            "/api/config", json={"roots": {"work": {"enabled": False}}}, headers=HEADERS
        )
        assert r.status_code == 401
        r = await c.patch(
            "/api/config",
            json={"roots": {"work": {"enabled": False}}},
            headers={**HEADERS, "authorization": "Bearer s3cret-token-value"},
        )
        assert r.status_code == 200


# -- the two assertions that outlive the route ------------------------------


def test_the_editable_subset_is_exactly_the_literal() -> None:
    """Premortem 3. Member by member, so adding a key to either set fails
    here and is a decision, not a drift. The second half names every
    perimeter field #238 lists as read only and asserts none is editable."""
    assert set(server.EDITABLE_TOP_LEVEL) == {"roots", "stop_timeout"}
    assert set(server.EDITABLE_ROOT_FIELDS) == {"enabled"}
    perimeter = {
        "path",
        "label",
        "host",
        "port",
        "token",
        "extra_hosts",
        "extra_origins",
        "allow_hosts",
        "allow_origins",
        "agent_binary",
        "session_prefix",
        "self_project",
        "stop_prompt",
        "tmux_socket",
        "sessions_dir",
        "agent_config_path",
        "state_path",
    }
    assert not perimeter & server.EDITABLE_TOP_LEVEL
    assert not perimeter & server.EDITABLE_ROOT_FIELDS


# Every name a route reads out of a request body, as a literal. `name` is a
# project identifier, `key` is one of ANSWER_KEYS, `token` is the grant's
# credential, and the settings PATCH reads the two literal sets above plus
# one integer. None of them is a path, and a new one has to be added here on
# purpose.
BODY_KEYS = frozenset({"name", "key", "token", "roots", "enabled", "stop_timeout"})


def test_no_route_accepts_a_path(engine: Engine, config: Config) -> None:
    """#154's standing assertion, read from the REAL route table and the
    request bodies the routes parse, so the next route cannot take one by
    accident.

    Three surfaces a path could arrive through, each closed: a template
    parameter (only `{name}`, a project identifier), a body key (the
    literal above), and the query string (only `acknowledged` and `lines`).
    An AST walk rather than a grep, because a grep for "path" matches the
    comments explaining why there is none.
    """
    app = create_app(engine=engine, config=config, bus=EventBus())
    params: set[str] = set()
    for route in app.routes:
        assert isinstance(route, Route)
        params.update(re.findall(r"\{(\w+)(?::\w+)?\}", route.path))
    assert params == {"name"}, params

    source = pathlib.Path(server.__file__).read_text()
    tree = ast.parse(source)
    body_keys: set[str] = set()
    query_keys: set[str] = set()
    for node in ast.walk(tree):
        # body["key"] and payload["name"]
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Name)
            and node.value.id in {"body", "payload"}
            and isinstance(node.slice, ast.Constant)
        ):
            body_keys.add(str(node.slice.value))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            owner = ast.unparse(node.func.value)
            if node.func.attr == "get" and node.args and isinstance(node.args[0], ast.Constant):
                # body.get("roots") and request.query_params.get("lines")
                if owner in {"body", "payload"}:
                    body_keys.add(str(node.args[0].value))
                if owner == "request.query_params":
                    query_keys.add(str(node.args[0].value))
    assert body_keys, "the walk found no body reads, so it has stopped matching"
    assert body_keys <= BODY_KEYS, body_keys - BODY_KEYS
    assert query_keys == {"acknowledged", "lines"}, query_keys
    # The one body whose keys are data rather than literals: the PATCH walks
    # `roots` by label and the fields under each label by the literal set.
    assert "path" not in server.EDITABLE_ROOT_FIELDS
    assert "path" not in BODY_KEYS
