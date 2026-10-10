"""#290, task 264: the `[agents]` table, a root's `agent` key, and what reads them.

The package names are a closed set and a second real package arrives in task
266, so the tests that need two agents that LOOK different register a fake
package for the length of one test. Nothing else in the suite sees it.
"""

from __future__ import annotations

import re
import signal
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from conftest import TRUST_MODAL, FakeClock, FakePidfd, FakeTmux, procs_from, ps_row
from hitchrail import agentconfig, agents, agy_ipc, claude_ipc
from hitchrail.agent import SessionUrl
from hitchrail.agentconfig import DEFAULT_AGENT, AgentSpec
from hitchrail.cli import build_config, main, parse_args, preflight
from hitchrail.config import Config, ConfigError
from hitchrail.engine import Engine
from hitchrail.events import EventBus
from hitchrail.roots import Root
from hitchrail.server import create_app
from hitchrail.sessions import State
from hitchrail.settings import read_config_file
from test_engine import running_after
from test_settings_route import HEADERS
from test_wrap_up import SETTLE


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(text)
    path.chmod(0o644)
    return path


def _two_roots(tmp_path: Path, second_agent: str = "second") -> str:
    (tmp_path / "work").mkdir(exist_ok=True)
    (tmp_path / "home").mkdir(exist_ok=True)
    return (
        f'[[roots]]\nlabel = "work"\npath = "{tmp_path / "work"}"\n\n'
        f'[[roots]]\nlabel = "home"\npath = "{tmp_path / "home"}"\n'
        f'agent = "{second_agent}"\n\n'
    )


class _Other(claude_ipc.ClaudeCode):
    """An agent whose argv and marker are not Claude Code's, so a test can
    tell which one derivation found. The rest is inherited and not used."""

    package = "other"
    marker = "--other-agent"

    def launch_argv(self, binary: str, project: str, folder: Path) -> list[str]:
        return [binary, self.marker, f"--dir={folder}"]


@pytest.fixture
def other_package(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setitem(
        agents.PACKAGES, "other", lambda c: _Other(c.agent_config_path, c.sessions_dir)
    )
    monkeypatch.setattr(agentconfig, "PACKAGE_NAMES", agentconfig.PACKAGE_NAMES | {"other"})
    yield


def test_every_package_name_the_file_may_give_builds_an_agent() -> None:
    """Fails if a name is accepted at startup that `Agents` cannot build, the
    KeyError a first start would otherwise raise on a phone."""
    assert set(agents.PACKAGES) == agentconfig.PACKAGE_NAMES


def test_a_root_runs_the_agent_it_names_and_the_others_run_the_default(
    tmp_path: Path,
) -> None:
    path = _write(
        tmp_path,
        _two_roots(tmp_path)
        + '[agents.second]\npackage = "claude-code"\nbinary = "/opt/second/claude"\n',
    )
    config = build_config(parse_args(["--config", str(path)]))
    assert {r.label: r.agent for r in config.roots} == {"work": DEFAULT_AGENT, "home": "second"}
    assert config.agents == {"second": AgentSpec("claude-code", "/opt/second/claude")}
    registry = agents.Agents(config)
    assert [c.ident for c in registry.all()] == [DEFAULT_AGENT, "second"]
    assert registry.for_project("home~x").ident == "second"
    assert registry.for_project("home~x").binary == "/opt/second/claude"
    assert registry.for_project("work~x").ident == DEFAULT_AGENT
    assert config.sources["agents"] == "file"


def test_a_root_given_by_flag_runs_the_default(tmp_path: Path) -> None:
    config = build_config(parse_args(["--root", f"main={tmp_path}"]))
    assert config.roots[0].agent == DEFAULT_AGENT
    assert config.agents == {}
    assert config.sources["agents"] == "default"


def test_an_identifier_that_is_not_qualified_gets_the_default(tmp_path: Path) -> None:
    """`derive` is asked about names nobody configured, and a root label that
    is gone; neither may raise, and the default is what started before #290."""
    registry = agents.Agents(Config(roots=(Root("main", tmp_path.resolve()),)))
    assert registry.for_project("bare").ident == DEFAULT_AGENT
    assert registry.for_project("gone~x").ident == DEFAULT_AGENT


@pytest.mark.parametrize(
    ("table", "complaint"),
    [
        ('[agents.second]\npackage = "vim"\nbinary = "x"\n', "package 'vim' is not one"),
        ('[agents.second]\npackage = "hitchrail.cli"\nbinary = "x"\n', "is not one"),
        ('[agents.default]\npackage = "claude-code"\nbinary = "x"\n', "reserved"),
        ('[agents.Second]\npackage = "claude-code"\nbinary = "x"\n', "not usable"),
        ('[agents.second]\npackage = "claude-code"\nbinary = "-x"\n', "not an acceptable"),
        ('[agents.second]\npackage = "claude-code"\nbinary = " x"\n', "not an acceptable"),
        ('[agents.second]\npackage = "claude-code"\nbinary = ""\n', "not an acceptable"),
        ('[agents.third]\npackage = "claude-code"\nbinary = "x"\n', "'second', which is not"),
        ('[agents.second]\npackage = "claude-code"\n', "binary must be a string"),
        ('[agents.second]\nbinary = "x"\n', "package must be a string"),
        ('[agents.second]\npackage = "claude-code"\nbinary = "x"\nargs = "y"\n', "unknown key"),
        ('agents = "x"\n', "must be a table"),
        ('[agents]\nsecond = "x"\n', "is not a table"),
    ],
)
def test_an_unusable_agent_table_refuses_the_start(
    tmp_path: Path, table: str, complaint: str
) -> None:
    """Refused when the config is built, before anything listens: a typo
    must stop the start rather than the first tap on a project."""
    # The table FIRST: a bare key written after `[[roots]]` belongs to that root.
    path = _write(tmp_path, table + "\n" + _two_roots(tmp_path))
    with pytest.raises(ConfigError, match=complaint):
        build_config(parse_args(["--config", str(path)]))


def test_a_root_agent_that_is_not_a_string_is_refused(tmp_path: Path) -> None:
    (tmp_path / "w").mkdir()
    path = _write(tmp_path, f'[[roots]]\nlabel = "w"\npath = "{tmp_path / "w"}"\nagent = 1\n')
    with pytest.raises(ConfigError, match="agent must be a string"):
        build_config(parse_args(["--config", str(path)]))


def test_a_config_built_in_code_is_refused_the_same_way(tmp_path: Path) -> None:
    """`Config` refuses, not only the file reader: a second door that skipped
    the reader would otherwise build an engine that raises on its first look."""
    with pytest.raises(ConfigError, match="not configured"):
        Config(roots=(Root("main", tmp_path.resolve(), agent="nope"),))
    with pytest.raises(ConfigError, match="not absolute"):
        Config(
            roots=(Root("main", tmp_path.resolve()),),
            agents={"x": AgentSpec("claude-code", "claude", resolved_agent_binary="claude")},
        )


def test_preflight_resolves_every_agent_and_names_the_missing_one(tmp_path: Path) -> None:
    config = Config(
        roots=(Root("main", tmp_path.resolve(), agent="second"),),
        agents={"second": AgentSpec("claude-code", "second-claude")},
    )
    found = preflight(
        config,
        which=lambda n: None if n == "second-claude" else f"/usr/bin/{n}",
        meminfo=tmp_path,
    )
    assert len(found.problems) == 1
    assert "'second-claude'" in found.problems[0]
    assert "[agents.second]" in found.problems[0], "names where to fix it, not --agent-binary"
    assert "--agent-binary" not in found.problems[0]

    found = preflight(config, which=lambda n: f"/usr/bin/{n}", meminfo=tmp_path)
    assert found.problems == []
    assert found.agents == {"second": "/usr/bin/second-claude"}


def test_the_spawned_binary_is_the_one_preflight_resolved(tmp_path: Path) -> None:
    config = Config(
        roots=(Root("main", tmp_path.resolve(), agent="second"),),
        agents={
            "second": AgentSpec(
                "claude-code", "second-claude", resolved_agent_binary="/abs/second-claude"
            )
        },
    )
    assert agents.Agents(config).for_project("main~x").binary == "/abs/second-claude"


def test_a_start_spawns_the_binary_preflight_resolved_for_the_roots_agent(
    tmp_path: Path,
) -> None:
    """Round 1 of the batch 3 review: the registry answering the right path
    proves nothing about the argv tmux is handed. The spawn reads the agent
    it asks for here, and a regression to `config.spawn_agent_binary` would
    start the default agent's binary under the second root."""
    (tmp_path / "vessel").mkdir()
    (tmp_path / ".sessions").mkdir()
    tmux = FakeTmux()
    engine = Engine(
        Config(
            roots=(Root("main", tmp_path.resolve(), agent="second"),),
            agents={
                "second": AgentSpec(
                    "claude-code", "second-claude", resolved_agent_binary="/abs/second-claude"
                )
            },
            agent_binary="claude",
            resolved_agent_binary="/abs/claude",
            sessions_dir=tmp_path / ".sessions",
            agent_config_path=tmp_path / "none.json",
        ),
        tmux=tmux,
        procs_fn=running_after("main~vessel"),
        meminfo_fn=lambda: "MemAvailable: 8388608 kB\n",
        ceiling_fn=lambda pid: None,
    )
    assert engine.start("main~vessel").state is State.RUNNING
    _, _, argv = tmux.started[-1]
    assert argv[0] == "/abs/second-claude"


def test_main_threads_each_agents_resolved_binary_into_the_engine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Round 1 of the batch 3 review. `main()` replaces each `[agents.<id>]`
    spec with the path preflight resolved; without it the engine spawns the
    bare name, which tmux's server resolves on ITS PATH (#196). The
    `--agent-binary` half of this has its own test in `test_cli.py`."""
    path = _write(
        tmp_path,
        '[agents.second]\npackage = "claude-code"\nbinary = "second-claude"\n\n'
        + _two_roots(tmp_path),
    )
    monkeypatch.setattr("shutil.which", lambda name: f"/opt/{name}")
    monkeypatch.setattr("uvicorn.run", lambda *a, **k: None)
    built: list[Config] = []
    real_engine = Engine

    def spy_engine(*, config: Config) -> Engine:
        built.append(config)
        return real_engine(config=config)

    monkeypatch.setattr("hitchrail.cli.Engine", spy_engine)
    assert main(["--config", str(path)]) == 0
    assert built, "Engine was never constructed"
    assert built[0].agents["second"].spawn_agent_binary == "/opt/second-claude"
    assert agents.Agents(built[0]).for_project("home~x").binary == "/opt/second-claude"


# -- derivation asks every agent -------------------------------------------


def _engine(
    tmp_path: Path,
    table: str,
    sessions: dict[str, int] | None = None,
    root_agent: str = DEFAULT_AGENT,
) -> Engine:
    (tmp_path / "vessel").mkdir(exist_ok=True)
    (tmp_path / ".sessions").mkdir(exist_ok=True)
    config = Config(
        roots=(Root("main", tmp_path.resolve(), agent=root_agent),),
        agents={"other": AgentSpec("other", "/opt/other")},
        sessions_dir=tmp_path / ".sessions",
        agent_config_path=tmp_path / "none.json",
    )
    return Engine(
        config,
        tmux=FakeTmux(sessions=sessions),
        procs_fn=procs_from(table),
        meminfo_fn=lambda: "MemAvailable: 8388608 kB\n",
        ceiling_fn=lambda pid: None,
    )


def _other_argv(tmp_path: Path) -> str:
    return " ".join(_Other(Path(), Path()).launch_argv("/opt/other", "", tmp_path / "vessel"))


@pytest.mark.usefixtures("other_package")
def test_a_detached_agent_of_another_package_is_found(tmp_path: Path) -> None:
    """The root runs the default, and an agent of the other package still
    runs in its folder: the operator changed the root's `agent` while it ran.
    Asking only the root's agent reported `stopped` and offered a second
    agent in the same folder, which is what the two directions exist to stop."""
    engine = _engine(tmp_path, ps_row(900, 1, args=_other_argv(tmp_path.resolve())))
    session = engine.get("main~vessel")
    assert session.state is State.DETACHED
    assert session.pid == 900


@pytest.mark.usefixtures("other_package")
def test_a_pane_holding_another_packages_agent_is_running(tmp_path: Path) -> None:
    table = ps_row(500, 1) + ps_row(501, 500, args=_other_argv(tmp_path.resolve()))
    engine = _engine(tmp_path, table, sessions={"main~vessel": 500})
    session = engine.get("main~vessel")
    assert session.state is State.RUNNING
    assert session.pid == 501


@pytest.mark.usefixtures("other_package")
def test_the_root_agent_is_the_one_the_engine_asks(tmp_path: Path) -> None:
    engine = _engine(tmp_path, "", root_agent="other")
    assert engine.agent_for("main~vessel", None).package == "other"
    assert _engine(tmp_path, "").agent_for("main~vessel", None).package == "claude-code"


# -- markers overlap (#294) ------------------------------------------------


def _agy_root(
    tmp_path: Path,
    argv: list[str],
    root_agent: str = DEFAULT_AGENT,
    prompt: str | None = None,
    clock: FakeClock | None = None,
    stop_policy: str = "ask",
    pidfd: FakePidfd | None = None,
) -> Engine:
    """A root, an `agy` agent configured beside the default, and a pane
    holding `argv`. Claude Code's trust map is readable and trusts nothing,
    so `awaiting_trust` says which package derivation named the owner."""
    (tmp_path / "vessel").mkdir(exist_ok=True)
    (tmp_path / ".sessions").mkdir(exist_ok=True)
    (tmp_path / "claude.json").write_text('{"projects": {}}')
    clock = clock or FakeClock()
    config = Config(
        roots=(Root("main", tmp_path.resolve(), agent=root_agent),),
        agents={"agy": AgentSpec("antigravity", "/opt/agy")},
        sessions_dir=tmp_path / ".sessions",
        agent_config_path=tmp_path / "claude.json",
        stop_prompt=prompt,
        stop_policy=stop_policy,
    )
    # Never the real pidfd calls: an end_anyway kill would signal pid 501 on
    # the machine running the suite.
    pidfd = pidfd or FakePidfd(fail_open=AssertionError("no test here kills"))
    return Engine(
        config,
        tmux=FakeTmux(sessions={"main~vessel": 500}),
        procs_fn=procs_from(ps_row(500, 1) + ps_row(501, 500, args=" ".join(argv))),
        meminfo_fn=lambda: "MemAvailable: 8388608 kB\n",
        ceiling_fn=lambda pid: None,
        clock=clock,
        sleep=clock.sleep,
        open_pidfd=pidfd.open,
        send_signal=pidfd.send,
        close_pidfd=pidfd.close,
        owner_uid=pidfd.owner,
        cwd_of=pidfd.cwd_of,
    )


def test_a_pane_holding_agy_under_a_claude_root_is_agys(tmp_path: Path) -> None:
    """agy's argv carries `--remote-control`, which is Claude Code's marker, and
    the root's own agent is asked first. The first marker match named Claude
    Code the owner, with Claude Code's trust warning, link and stop keys; the
    whole launch tail is what tells the two apart."""
    folder = tmp_path.resolve() / "vessel"
    argv = agy_ipc.Antigravity().launch_argv("/opt/agy", "main~vessel", folder)
    agy = _agy_root(tmp_path, argv)
    session = agy.get("main~vessel")
    assert session.state is State.RUNNING
    assert session.awaiting_trust is False, "read as Claude Code's, which trusts nothing here"
    assert session.agent == "agy"
    # The positive control: the same pane holding Claude Code does warn, so
    # the False above is the owner and not a trust map nobody read.
    claude = _agy_root(tmp_path, claude_ipc.launch_argv("claude", "main~vessel"))
    assert claude.get("main~vessel").awaiting_trust is True
    assert claude.get("main~vessel").agent == DEFAULT_AGENT


@pytest.mark.integration
async def test_the_listing_names_each_rows_agent_and_each_roots(tmp_path: Path) -> None:
    """#294, task 268. The page names a row's agent from the row first and
    its root second, so both travel: the root switched to agy while Claude
    Code ran on reads `agy` on the root and `default` on the row, which is
    the one row the page must not label from its root."""
    engine = _agy_root(tmp_path, claude_ipc.launch_argv("claude", "main~vessel"), "agy")
    app = create_app(engine=engine, config=engine.config, bus=EventBus())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost"
    ) as client:
        body = (await client.get("/api/projects", headers=HEADERS)).json()
    assert [(r["label"], r["agent"]) for r in body["roots"]] == [("main", "agy")]
    assert {p["name"]: p["agent"] for p in body["projects"]} == {"main~vessel": DEFAULT_AGENT}
    stopped = _agy_root(tmp_path, ["sleep", "1"], "agy").get("main~vessel")
    assert stopped.as_dict()["agent"] is None, "a row with nothing running names no agent"


def _claude_left_running(
    tmp_path: Path,
    prompt: str | None = None,
    clock: FakeClock | None = None,
    stop_policy: str = "ask",
    pidfd: FakePidfd | None = None,
) -> tuple[Engine, FakeTmux]:
    """The root was switched to agy while Claude Code still ran in its pane."""
    argv = claude_ipc.launch_argv("claude", "main~vessel")
    engine = _agy_root(
        tmp_path,
        argv,
        root_agent="agy",
        prompt=prompt,
        clock=clock,
        stop_policy=stop_policy,
        pidfd=pidfd,
    )
    assert isinstance(engine.tmux, FakeTmux)
    engine.tmux.pane_text["main~vessel"] = "\x1b[39m\u276f\xa0                     \n"
    return engine, engine.tmux


def test_a_stop_types_the_running_agents_keys_not_the_roots(tmp_path: Path) -> None:
    """Round 1 of the #290 review. The root's agent typed agy's sequence into
    Claude Code's pane, after reading Claude Code's screen with agy's reader,
    which finds no box there and refused a Stop that would have worked."""
    engine, tmux = _claude_left_running(tmp_path)
    assert engine.get("main~vessel").agent == DEFAULT_AGENT
    engine.stop("main~vessel")
    assert [keys for _, keys in tmux.sent] == list(claude_ipc.GRACEFUL_STOP_KEYS)


def test_a_wrap_up_remembers_which_agent_it_was_sent_to(tmp_path: Path) -> None:
    """The sweep, not the Stop, types the exit after a wrap up: it reads the
    agent off the marker, since the row it would derive again is not to hand."""
    clock = FakeClock()
    engine, tmux = _claude_left_running(tmp_path, prompt="wrap up", clock=clock)
    engine.stop("main~vessel")
    marker = engine.stopping["main~vessel"]
    assert marker.phase == "closing"
    assert marker.agent == DEFAULT_AGENT
    assert isinstance(marker.watch, claude_ipc.WrapUpWatch)
    tmux.sent.clear()
    # Two idle reads a settle apart, the first a settle after the prompt.
    for _ in range(2):
        clock.advance(SETTLE)
        moved = engine.advance_wrap_ups()
    assert moved == ["main~vessel"]
    assert [keys for _, keys in tmux.sent] == list(claude_ipc.GRACEFUL_STOP_KEYS)


def test_the_sweep_reads_a_screen_with_the_running_agents_reader(tmp_path: Path) -> None:
    """agy claims no question on any screen, so reading Claude Code's modal
    with the root's agent hid a person being needed."""
    engine, tmux = _claude_left_running(tmp_path)
    tmux.pane_text["main~vessel"] = TRUST_MODAL
    assert engine.scan_for_stuck() == ["main~vessel"]


def test_a_repeated_stop_remembers_the_running_agent(tmp_path: Path) -> None:
    """A second Stop on `exiting` writes a fresh marker, and the sweep reads
    the agent off it: the root's would read Claude Code's screen with agy's
    reader when the stop runs out."""
    engine, _ = _claude_left_running(tmp_path)
    engine.stop("main~vessel")
    first = engine.stopping["main~vessel"]
    engine.stop("main~vessel")
    assert engine.stopping["main~vessel"] is not first
    assert engine.stopping["main~vessel"].agent == DEFAULT_AGENT


def test_an_answer_goes_through_the_running_agents_keys(tmp_path: Path) -> None:
    """agy refuses every key, so answering through the root's agent refused
    the key Claude Code's question was asking for."""
    engine, tmux = _claude_left_running(tmp_path)
    tmux.pane_text["main~vessel"] = TRUST_MODAL
    engine.answer("main~vessel", "1")
    assert tmux.sent == [("main~vessel", ("1",))]


def test_the_link_is_read_by_the_running_agents_package(tmp_path: Path) -> None:
    """agy under a Claude Code root. Claude Code's scrape finds no
    claude.ai link in agy's pane, so asking the root's agent says `pending`
    over a link on the screen."""
    folder = tmp_path.resolve() / "vessel"
    engine = _agy_root(tmp_path, agy_ipc.Antigravity().launch_argv("/opt/agy", "x", folder))
    assert isinstance(engine.tmux, FakeTmux)
    link = "https://antigravity.google.com/r/0123abcd-0123-4abc-8def-0123456789ab-v1"
    engine.tmux.pane_text["main~vessel"] = f"Remote session: {link}\n"
    assert engine.session_url("main~vessel") == SessionUrl(link, "scraped")


def _expire(engine: Engine, tmux: FakeTmux, clock: FakeClock) -> list[str]:
    """Stop, the pane showing a question, and the stop running out."""
    engine.stop("main~vessel")
    tmux.pane_text["main~vessel"] = TRUST_MODAL
    clock.advance(engine.prefs.stop_timeout() + 1)
    return engine.expire_stops()


def test_an_expired_stop_reads_the_running_agents_screen(tmp_path: Path) -> None:
    """agy claims no question on any screen, so the expiry read through the
    root's agent reported "no answer" over Claude Code's question."""
    clock = FakeClock()
    engine, tmux = _claude_left_running(tmp_path, clock=clock)
    assert _expire(engine, tmux, clock) == ["main~vessel"]
    assert engine.get("main~vessel").awaiting_input is True


def test_end_anyway_second_look_reads_the_running_agents_screen(tmp_path: Path) -> None:
    """The second look decides the kill (#444). Read with agy's reader it
    sees no question, and the stop the operator asked to end on one is left
    running."""
    clock = FakeClock()
    pidfd = FakePidfd()
    pidfd.runs_in(tmp_path.resolve() / "vessel")
    engine, tmux = _claude_left_running(
        tmp_path, clock=clock, stop_policy="end_anyway", pidfd=pidfd
    )
    _expire(engine, tmux, clock)
    assert pidfd.signals == [signal.SIGHUP]


def test_an_exit_refused_after_a_wrap_up_reads_the_running_agents_screen(
    tmp_path: Path,
) -> None:
    """The wrap up hit its ceiling on a question, so the exit is refused and
    the stop ends there. The one look it takes is the running agent's, or
    the row says "no answer" over the question."""
    clock = FakeClock()
    engine, tmux = _claude_left_running(tmp_path, prompt="wrap up", clock=clock)
    engine.stop("main~vessel")
    tmux.pane_text["main~vessel"] = TRUST_MODAL
    clock.advance(engine.config.stop_prompt_timeout + 1)
    assert engine.advance_wrap_ups() == []
    assert "main~vessel" not in engine.stopping
    assert engine.get("main~vessel").awaiting_input is True


# -- #295: the documents' config examples -----------------------------------

_DOCS = Path(__file__).resolve().parents[1]


def _toml_blocks() -> list[tuple[str, int, str]]:
    found = []
    for doc in ("README.md", "CONTRIBUTING.md", "docs/api.md"):
        text = (_DOCS / doc).read_text()
        for match in re.finditer(r"^```toml\n(.*?)^```", text, re.M | re.S):
            found.append((doc, text.count("\n", 0, match.start()) + 1, match.group(1)))
    return found


@pytest.mark.parametrize(("doc", "line", "block"), _toml_blocks(), ids=lambda v: str(v)[:20])
def test_every_config_example_in_the_docs_is_one_the_loader_takes(
    tmp_path: Path, doc: str, line: int, block: str
) -> None:
    """#295. An example that drifted from the loader is a startup refusal for
    whoever copies it, so each is read the way the file is, and its agents
    checked the way `Config` checks them."""
    path = _write(tmp_path, block)
    settings = read_config_file(path)
    agentconfig.check_agents(settings.agents, [(r.label, r.agent) for r in settings.roots])


def test_the_docs_hold_an_agents_example() -> None:
    """The parametrisation above passes vacuously on no blocks at all."""
    assert any("[agents." in block for _, _, block in _toml_blocks())
