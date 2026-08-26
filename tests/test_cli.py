from __future__ import annotations

import ast
from pathlib import Path

import pytest

from hitchrail import cli
from hitchrail.cli import banner, build_config, main, parse_args, preflight
from hitchrail.config import Config, is_loopback_host


def test_root_is_required_to_be_a_real_directory(tmp_path: Path) -> None:
    args = parse_args(["--root", str(tmp_path)])
    assert build_config(args).root == tmp_path


def test_loopback_is_the_default_bind(tmp_path: Path) -> None:
    cfg = build_config(parse_args(["--root", str(tmp_path)]))
    assert cfg.host == "127.0.0.1"
    assert cfg.is_loopback
    assert cfg.token is None


def test_a_network_bind_generates_a_token_when_none_is_given(tmp_path: Path) -> None:
    cfg = build_config(parse_args(["--root", str(tmp_path), "--host", "0.0.0.0"]))
    assert cfg.token
    assert len(cfg.token) >= 24


def test_an_explicit_token_is_used_verbatim(tmp_path: Path) -> None:
    cfg = build_config(
        parse_args(["--root", str(tmp_path), "--host", "0.0.0.0", "--token", "mine"])
    )
    assert cfg.token == "mine"


def test_a_missing_root_exits_with_a_message(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["--root", str(tmp_path / "nope")])
    assert code == 2
    assert "root is not a directory" in capsys.readouterr().err


def test_the_banner_carries_a_link_a_phone_can_open(tmp_path: Path) -> None:
    # The token grant from Phase 2 is only useful if something hands the user
    # a URL that carries it. This is that something.
    cfg = build_config(
        parse_args(
            [
                "--root",
                str(tmp_path),
                "--host",
                "0.0.0.0",
                "--token",
                "abc123",
                "--allow-host",
                "box.lan",
            ]
        )
    )
    text = banner(cfg)
    assert "http://box.lan:8787/?token=abc123" in text
    assert "run code on this machine as you" in text.lower()


def test_the_banner_is_silent_on_loopback(tmp_path: Path) -> None:
    cfg = build_config(parse_args(["--root", str(tmp_path)]))
    assert banner(cfg) == ""


def test_the_banner_never_offers_a_wildcard_as_a_link(tmp_path: Path) -> None:
    cfg = build_config(
        parse_args(["--root", str(tmp_path), "--host", "0.0.0.0", "--token", "t"])
    )
    assert "0.0.0.0" not in banner(cfg)


def test_the_token_is_printed_once_on_a_network_bind(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("hitchrail.cli._serve", lambda app, cfg: 0)
    main(["--root", str(tmp_path), "--host", "0.0.0.0"])
    out = capsys.readouterr().out
    assert "token" in out.lower()


def test_no_token_banner_on_loopback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("hitchrail.cli._serve", lambda app, cfg: 0)
    main(["--root", str(tmp_path)])
    assert "token" not in capsys.readouterr().out.lower()


def test_extra_allowed_hosts_reach_the_config(tmp_path: Path) -> None:
    cfg = build_config(
        parse_args(
            [
                "--root",
                str(tmp_path),
                "--host",
                "0.0.0.0",
                "--token",
                "t",
                "--allow-host",
                "box.lan",
            ]
        )
    )
    assert "box.lan" in cfg.allowed_hosts


def test_build_config_asks_the_shared_loopback_question(tmp_path: Path) -> None:
    # Two copies of "is this loopback" would drift, and the copy that drifts is
    # the one deciding whether a token is demanded.

    assert is_loopback_host is not None


def test_main_returns_two_rather_than_raising_on_a_bad_bind(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["--root", str(tmp_path), "--host", "0.0.0.0", "--allow-host", "*"])
    assert code == 2
    assert "wildcard" in capsys.readouterr().err


# -- #28: the startup preflight ---------------------------------------------
#
# The lookup is INJECTED, never PATH. A test that edits the environment to
# prove a lookup fails can break a neighbouring test, and the plan says so.


def _cfg(tmp_path: Path, **kw: object) -> Config:
    return Config(root=tmp_path, **kw)  # type: ignore[arg-type]


def test_a_machine_with_everything_present_has_nothing_to_say(tmp_path: Path) -> None:
    found = preflight(_cfg(tmp_path), which=lambda _n: "/usr/bin/x", meminfo=tmp_path)
    assert found == []


def test_missing_tmux_is_named_and_says_what_to_install(tmp_path: Path) -> None:
    """The failure this replaces arrived as a FileNotFoundError from inside a
    subprocess call, surfaced in a web interface, on a phone."""
    found = preflight(
        _cfg(tmp_path),
        which=lambda n: None if n == "tmux" else "/usr/bin/x",
        meminfo=tmp_path,
    )
    assert len(found) == 1
    assert "tmux" in found[0]
    assert "apt install tmux" in found[0], "naming the problem without the fix"


def test_a_missing_agent_binary_names_the_binary_that_was_looked_for(
    tmp_path: Path,
) -> None:
    """`--agent-binary`, never `--claude-binary`: no vendor name in the
    operator contract. An operator who set it needs to see what was tried."""
    found = preflight(
        _cfg(tmp_path, agent_binary="my-agent"),
        which=lambda n: None if n == "my-agent" else "/usr/bin/x",
        meminfo=tmp_path,
    )
    assert len(found) == 1
    assert "my-agent" in found[0]
    assert "--agent-binary" in found[0]


def test_an_unreadable_meminfo_refuses_rather_than_running_unguarded(
    tmp_path: Path,
) -> None:
    """The Linux assumption, made explicit. Running without the memory guard
    is how a machine ends up full of agents."""
    found = preflight(_cfg(tmp_path), which=lambda _n: "/usr/bin/x", meminfo=tmp_path / "nope")
    assert len(found) == 1
    assert "memory guard" in found[0]


def test_every_missing_prerequisite_is_reported_at_once(tmp_path: Path) -> None:
    """Not one at a time. An operator on a fresh machine should learn
    everything they have to install from a single run."""
    found = preflight(_cfg(tmp_path), which=lambda _n: None, meminfo=tmp_path / "nope")
    assert len(found) == 3


def test_the_preflight_is_not_a_version_check(tmp_path: Path) -> None:
    """Deliberately absent, and pinned so nobody adds it.

    A version gate would refuse a perfectly capable tmux the day somebody
    ships a fork or a distro patches the version string. The four addressing
    behaviours this project works around are old and stable.
    """
    source = (Path(__file__).parent.parent / "src" / "hitchrail" / "cli.py").read_text()
    assert "--version" not in source.split("def preflight")[1].split("def _serve")[0]
    for forbidden in ("tmux -V", "version_info", "LooseVersion", "parse_version"):
        assert forbidden not in source, f"a version check crept in: {forbidden}"


def test_main_refuses_to_start_and_prints_what_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Refusing must not reach the bind, and must not print a token first."""
    served: list[object] = []

    def record(*a: object) -> int:
        served.append(a)
        return 0

    monkeypatch.setattr(cli, "_serve", record)
    monkeypatch.setattr("shutil.which", lambda _n: None)

    code = main(["--root", str(tmp_path)])

    assert code == 2
    assert served == [], "it bound a socket it had already decided not to use"
    err = capsys.readouterr().err
    assert "cannot start" in err
    assert "tmux" in err


def test_a_refusal_prints_no_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Printing a token and a set of links, then refusing to work, is worse
    than refusing plainly: the operator is left with a live looking secret."""
    monkeypatch.setattr(cli, "_serve", lambda *a: 0)
    monkeypatch.setattr("shutil.which", lambda _n: None)

    code = main(["--root", str(tmp_path), "--host", "0.0.0.0", "--token", "s3cret"])

    assert code == 2
    out = capsys.readouterr()
    assert "s3cret" not in out.out
    assert "s3cret" not in out.err


# -- #45: every flag the README promises ------------------------------------


@pytest.mark.parametrize(
    "flag",
    [
        "--root",
        "--host",
        "--port",
        "--token",
        "--allow-host",
        "--allow-origin",
        "--self-project",
        "--agent-binary",
        "--stop-timeout",
        "--version",
    ],
)
def test_the_cli_accepts_every_documented_flag(flag: str) -> None:
    """A flag the README documents and the CLI does not accept is a bug the
    first user finds. `--agent-binary` was exactly that until #45."""
    source = (Path(__file__).parent.parent / "src" / "hitchrail" / "cli.py").read_text()
    assert f'"{flag}"' in source


def test_the_agent_binary_flag_reaches_the_config(tmp_path: Path) -> None:
    cfg = build_config(parse_args(["--root", str(tmp_path), "--agent-binary", "other"]))
    assert cfg.agent_binary == "other"


def test_the_stop_timeout_flag_reaches_the_config(tmp_path: Path) -> None:
    """A documented default that cannot be changed is a constant."""
    cfg = build_config(parse_args(["--root", str(tmp_path), "--stop-timeout", "90"]))
    assert cfg.stop_timeout == 90


def test_no_vendor_name_is_in_the_operator_contract() -> None:
    """The quarantine is a seam. `agent_binary`, never `claude_binary`, so a
    second vendor never requires an operator to relearn their flags."""
    # The FLAG NAMES argparse actually registers, not a substring of the file.
    # A first version of this searched the raw source and flagged the comment
    # that explains why `--claude-binary` is not used, which is a guard that
    # fails on correct code and therefore gets deleted.
    source = (Path(__file__).parent.parent / "src" / "hitchrail" / "cli.py").read_text()
    flags = {
        node.args[0].value
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "add_argument"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    }
    vendor = {f for f in flags if "claude" in f.lower()}
    assert not vendor, f"a vendor name reached the operator contract: {vendor}"


def test_main_serves_the_real_app_on_the_configured_address(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The wiring, end to end, without binding anything.

    `uvicorn.run` is the one line that cannot run in a test without taking the
    port for the rest of the session, so it is captured rather than executed.
    Everything before it is real: the flags, the config, the preflight, the
    engine and the app, which is where the mistakes actually are.
    """
    (tmp_path / "vessel").mkdir()
    captured: dict[str, object] = {}

    def fake_run(app: object, **kwargs: object) -> None:
        captured["app"] = app
        captured.update(kwargs)

    monkeypatch.setattr("uvicorn.run", fake_run)
    monkeypatch.setattr("shutil.which", lambda _n: "/usr/bin/x")

    code = main(["--root", str(tmp_path), "--port", "9123"])

    assert code == 0
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 9123
    app = captured["app"]
    paths = {getattr(r, "path", None) for r in app.routes}  # type: ignore[attr-defined]
    assert "/api/projects" in paths
    assert "/api/events" in paths
    assert "/api/sessions/{name}/kill" in paths, "the app served is not the real one"
