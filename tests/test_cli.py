from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

from hitchrail import cli
from hitchrail.cli import JOURNAL_ENV, banner, build_config, main, parse_args, preflight
from hitchrail.config import ConfigError, is_loopback_host
from support import make_config


@pytest.fixture(autouse=True)
def _prerequisites_are_present(monkeypatch: pytest.MonkeyPatch) -> None:
    """The unit tier must not depend on what is installed on this machine.

    #28 put a preflight in front of the bind, so every test that calls `main`
    started depending on whether tmux and the agent binary happen to be on the
    developer's PATH. They are on mine and they are not on CI, which installs
    tmux and has no reason to install Claude Code: the whole suite passed here
    and every interpreter failed there, on a test about a token banner that
    had nothing to do with the preflight.

    Tests that are ABOUT the preflight override this, either by injecting
    `which` directly or by patching it again inside the test, which runs after
    an autouse fixture and therefore wins.
    """
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")


def test_root_is_required_to_be_a_real_directory(tmp_path: Path) -> None:
    args = parse_args(["--root", f"main={tmp_path}"])
    assert [r.path for r in build_config(args).roots] == [tmp_path.resolve()]


def test_loopback_is_the_default_bind(tmp_path: Path) -> None:
    cfg = build_config(parse_args(["--root", f"main={tmp_path}"]))
    assert cfg.host == "127.0.0.1"
    assert cfg.is_loopback
    assert cfg.token is None


def test_a_network_bind_generates_a_token_when_none_is_given(tmp_path: Path) -> None:
    cfg = build_config(parse_args(["--root", f"main={tmp_path}", "--host", "0.0.0.0"]))
    assert cfg.token
    assert len(cfg.token) >= 24


def test_an_explicit_token_is_used_verbatim(tmp_path: Path) -> None:
    cfg = build_config(
        parse_args(["--root", f"main={tmp_path}", "--host", "0.0.0.0", "--token", "mine"])
    )
    assert cfg.token == "mine"


def test_a_missing_root_exits_with_a_message(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["--root", f"main={tmp_path / 'nope'}"])
    assert code == 2
    # The message names WHICH root now, which is the point of labels:
    # "root is not a directory" was unactionable with three configured.
    assert "is not a directory" in capsys.readouterr().err


def test_the_banner_carries_a_link_a_phone_can_open(tmp_path: Path) -> None:
    # The token grant from Phase 2 is only useful if something hands the user
    # a URL that carries it. This is that something.
    cfg = build_config(
        parse_args(
            [
                "--root",
                f"main={tmp_path}",
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
    assert "http://box.lan:8787/grant#token=abc123" in text
    assert "run code on this machine as you" in text.lower()


def test_the_banner_never_offers_the_token_as_a_query_string(tmp_path: Path) -> None:
    """#21. A query string is written down by everything it passes through: the
    reverse proxy the README recommends for TLS logs `$request`, the `Referer`
    header carries it outbound, and history sync carries it to every signed in
    device. A fragment is sent to no server at all.

    The query grant still WORKS, so an already pasted link keeps working, but
    nothing this program prints may create another one.
    """
    cfg = build_config(
        parse_args(
            [
                "--root",
                f"main={tmp_path}",
                "--host",
                "0.0.0.0",
                "--token",
                "abc123",
                "--allow-host",
                "box.lan",
            ]
        )
    )
    assert "?token=" not in banner(cfg)


def test_the_banner_is_silent_on_loopback(tmp_path: Path) -> None:
    cfg = build_config(parse_args(["--root", f"main={tmp_path}"]))
    assert banner(cfg) == ""


def test_the_banner_never_offers_a_wildcard_as_a_link(tmp_path: Path) -> None:
    cfg = build_config(
        parse_args(["--root", f"main={tmp_path}", "--host", "0.0.0.0", "--token", "t"])
    )
    assert "0.0.0.0" not in banner(cfg)


def test_the_token_is_printed_once_on_a_network_bind(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("hitchrail.cli._serve", lambda app, cfg: 0)
    main(["--root", f"main={tmp_path}", "--host", "0.0.0.0"])
    out = capsys.readouterr().out
    assert "token" in out.lower()


def test_no_token_banner_on_loopback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("hitchrail.cli._serve", lambda app, cfg: 0)
    main(["--root", f"main={tmp_path}"])
    assert "token" not in capsys.readouterr().out.lower()


def test_extra_allowed_hosts_reach_the_config(tmp_path: Path) -> None:
    cfg = build_config(
        parse_args(
            [
                "--root",
                f"main={tmp_path}",
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
    code = main(["--root", f"main={tmp_path}", "--host", "0.0.0.0", "--allow-host", "*"])
    assert code == 2
    assert "wildcard" in capsys.readouterr().err


# -- #28: the startup preflight ---------------------------------------------
#
# The lookup is INJECTED, never PATH. A test that edits the environment to
# prove a lookup fails can break a neighbouring test, and the plan says so.


def test_a_machine_with_everything_present_has_nothing_to_say(tmp_path: Path) -> None:
    found = preflight(make_config(tmp_path), which=lambda _n: "/usr/bin/x", meminfo=tmp_path)
    assert found == []


def test_missing_tmux_is_named_and_says_what_to_install(tmp_path: Path) -> None:
    """The failure this replaces arrived as a FileNotFoundError from inside a
    subprocess call, surfaced in a web interface, on a phone."""
    found = preflight(
        make_config(tmp_path),
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
        make_config(tmp_path, agent_binary="my-agent"),
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
    found = preflight(
        make_config(tmp_path), which=lambda _n: "/usr/bin/x", meminfo=tmp_path / "nope"
    )
    assert len(found) == 1
    assert "memory guard" in found[0]


def test_every_missing_prerequisite_is_reported_at_once(tmp_path: Path) -> None:
    """Not one at a time. An operator on a fresh machine should learn
    everything they have to install from a single run."""
    found = preflight(make_config(tmp_path), which=lambda _n: None, meminfo=tmp_path / "nope")
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

    code = main(["--root", f"main={tmp_path}"])

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

    code = main(["--root", f"main={tmp_path}", "--host", "0.0.0.0", "--token", "s3cret"])

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
    cfg = build_config(parse_args(["--root", f"main={tmp_path}", "--agent-binary", "other"]))
    assert cfg.agent_binary == "other"


def test_the_stop_timeout_flag_reaches_the_config(tmp_path: Path) -> None:
    """A documented default that cannot be changed is a constant."""
    cfg = build_config(parse_args(["--root", f"main={tmp_path}", "--stop-timeout", "90"]))
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

    code = main(["--root", f"main={tmp_path}", "--port", "9123"])

    assert code == 0
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 9123
    app = captured["app"]
    paths = {getattr(r, "path", None) for r in app.routes}  # type: ignore[attr-defined]
    assert "/api/projects" in paths
    assert "/api/events" in paths
    assert "/api/sessions/{name}/kill" in paths, "the app served is not the real one"


# -- #108: the CLI and Config ask the same question --------------------------


def test_a_remote_allow_host_generates_a_token(tmp_path: Path) -> None:
    """The convenience path and the refusal have to agree.

    `build_config` used to generate only for a non loopback bind, so a loopback
    bind with a remote allowed host produced no token and `Config` would now
    refuse the CLI's own output: an operator would see a startup failure for a
    flag combination the CLI itself assembled.
    """
    cfg = build_config(
        parse_args(["--root", f"main={tmp_path}", "--allow-host", "box.tailnet.ts.net"])
    )
    assert cfg.token, "no token was generated for a declared remote reach"


def test_a_remote_allow_origin_generates_a_token(tmp_path: Path) -> None:
    cfg = build_config(
        parse_args(
            ["--root", f"main={tmp_path}", "--allow-origin", "https://box.tailnet.ts.net"]
        )
    )
    assert cfg.token


def test_a_loopback_allow_host_generates_nothing(tmp_path: Path) -> None:
    """The default stays what it was: no token, no banner, nothing to copy."""
    cfg = build_config(parse_args(["--root", f"main={tmp_path}", "--allow-host", "localhost"]))
    assert cfg.token is None


def test_an_explicit_token_still_wins_over_a_generated_one(tmp_path: Path) -> None:
    cfg = build_config(
        parse_args(
            [
                "--root",
                f"main={tmp_path}",
                "--allow-host",
                "box.tailnet.ts.net",
                "--token",
                "mine",
            ]
        )
    )
    assert cfg.token == "mine"


# -- #109: the token can arrive in the environment ---------------------------
#
# `--token` puts the secret in argv, and argv is world readable. Measured
# rather than assumed:
#
#   -r--r--r--  /proc/<pid>/cmdline
#   -r--------  /proc/<pid>/environ
#   proc /proc proc rw,nosuid,nodev,noexec,relatime   (no hidepid)
#
# So any local user can read the token out of a running Hitchrail's argv, and
# `ps` shows it to them without trying. The environment is owner only. That is
# the reason this exists, ahead of the daemon convenience.

ENV_VAR = "HITCHRAIL_TOKEN"


def test_an_env_token_is_used(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_VAR, "abc123")
    cfg = build_config(parse_args(["--root", f"main={tmp_path}", "--host", "0.0.0.0"]))
    assert cfg.token == "abc123"


def test_the_flag_beats_the_env_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An explicit argument overrides an ambient one, so a one off run does not
    need the unit edited. It is also the worse carrier, and choosing it has to
    stay possible."""
    monkeypatch.setenv(ENV_VAR, "abc123")
    cfg = build_config(
        parse_args(["--root", f"main={tmp_path}", "--host", "0.0.0.0", "--token", "xyz789"])
    )
    assert cfg.token == "xyz789"


def test_an_unset_env_still_generates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_VAR, raising=False)
    cfg = build_config(parse_args(["--root", f"main={tmp_path}", "--host", "0.0.0.0"]))
    assert cfg.token and cfg.token != "abc123"


@pytest.mark.parametrize("value", ["", "   ", "\t\n"])
def test_a_blank_env_token_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    """Set and empty is not the same as unset.

    Unset means "not supplied" and falls through to generation. Set to nothing
    means the operator believes they configured authentication and did not,
    which is the trap `Config._check_token` was written about. Generating a
    token here would hide it, and an `EnvironmentFile` line reading
    `HITCHRAIL_TOKEN=` produces exactly this.
    """
    monkeypatch.setenv(ENV_VAR, value)
    with pytest.raises(ConfigError) as excinfo:
        build_config(parse_args(["--root", f"main={tmp_path}", "--host", "0.0.0.0"]))
    assert ENV_VAR in str(excinfo.value), "the message must name where to look"


def test_an_env_token_switches_auth_on_at_loopback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Supplying a token always switches authentication on, whatever the bind.
    This is the case a proxied deployment needs."""
    monkeypatch.setenv(ENV_VAR, "abc123")
    assert build_config(parse_args(["--root", f"main={tmp_path}"])).token == "abc123"


def test_the_banner_does_not_reprint_an_env_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Under a service the banner is journald, and a stable token in a
    persistent log is worse than today's per start one. The operator supplied
    this, so they have it; printing it again only writes it somewhere new."""
    monkeypatch.setenv(ENV_VAR, "abc123")
    text = banner(build_config(parse_args(["--root", f"main={tmp_path}", "--host", "0.0.0.0"])))
    assert "/grant#token=abc123" in text, "the tappable link is still the point"
    assert not any(line.strip().startswith("token:") for line in text.splitlines())


def test_the_banner_still_prints_a_generated_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The case that must not change. A generated token is unknowable any other
    way, so not printing it would make the server unusable."""
    monkeypatch.delenv(ENV_VAR, raising=False)
    text = banner(build_config(parse_args(["--root", f"main={tmp_path}", "--host", "0.0.0.0"])))
    assert any(line.strip().startswith("token:") for line in text.splitlines())


# -- #110: the journal question, decided ------------------------------------
#
# `banner()` writes the grant link, token and all, to stdout. Under a systemd
# unit stdout IS journald, so the link lands in a persistent system log
# readable by root and by every member of `systemd-journal`. That is a
# different exposure from a line scrolling past in a terminal the operator is
# sitting at, and it is the one #110 was told to settle rather than leave.
#
# **The decision: the banner degrades under a service.** The alternative was to
# document the exposure and print anyway. It was rejected because the operator
# running a unit already supplied `HITCHRAIL_TOKEN` themselves, so suppressing
# the link's fragment costs them nothing they do not already have, while
# printing it writes a stable secret somewhere new and permanent.
#
# systemd sets `JOURNAL_STREAM` in the service environment when it has
# connected stdout to the journal. That is a documented interface, systemd.exec
# section "Environment Variables in Spawned Processes", not a guess at a parent
# process name, and it is false in a terminal.


def test_the_banner_keeps_the_token_out_of_the_journal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole point. Under a unit, no token value reaches stdout, in the
    token line or in a link fragment."""
    monkeypatch.setenv(ENV_VAR, "abc123")
    monkeypatch.setenv(JOURNAL_ENV, "8:12345")
    text = banner(build_config(parse_args(["--root", f"main={tmp_path}", "--host", "0.0.0.0"])))
    assert "abc123" not in text
    # `/grant#` rather than `#token=`: the claim is that no LINK carries a
    # fragment. Banning the string outright would also stop the banner naming
    # the format the operator has to append by hand, which is the next test.
    assert "/grant#" not in text


def test_the_banner_still_names_the_address_under_a_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Degrading is not going silent. The operator still needs to know which
    address to open and that a fragment has to be appended by hand, or the
    suppression reads as the server having failed to print anything."""
    monkeypatch.setenv(ENV_VAR, "abc123")
    monkeypatch.setenv(JOURNAL_ENV, "8:12345")
    text = banner(
        build_config(
            parse_args(
                ["--root", f"main={tmp_path}", "--host", "0.0.0.0", "--allow-host", "box.lan"]
            )
        )
    )
    assert "http://box.lan:8787/grant" in text
    assert ENV_VAR in text, "the operator is not told where to get the missing half"


def test_the_banner_tells_a_service_to_supply_a_stable_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A generated token under a unit is doubly wrong: it is a secret in a
    permanent log, and it changes on every restart, so the link saved on the
    phone dies with each one. Suppressing it and saying nothing would look like
    a bug, so the banner names the fix."""
    monkeypatch.delenv(ENV_VAR, raising=False)
    monkeypatch.setenv(JOURNAL_ENV, "8:12345")
    text = banner(build_config(parse_args(["--root", f"main={tmp_path}", "--host", "0.0.0.0"])))
    assert not any(line.strip().startswith("token:") for line in text.splitlines())
    assert ENV_VAR in text
    assert "restart" in text.lower()


def test_the_banner_is_unchanged_in_a_terminal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The degradation is keyed on the journal, not on a token being present.
    Without `JOURNAL_STREAM` nothing about the existing behaviour moves."""
    monkeypatch.setenv(ENV_VAR, "abc123")
    monkeypatch.delenv(JOURNAL_ENV, raising=False)
    text = banner(build_config(parse_args(["--root", f"main={tmp_path}", "--host", "0.0.0.0"])))
    assert "/grant#token=abc123" in text


def test_a_bare_root_says_what_to_do_instead_of_naming_a_function(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """#120. `--root` now needs a label, so a person upgrading from 0.1.0 meets
    this refusal first, and it has to tell them what to type.

    argparse renders a `ValueError` from a `type=` callable as
    `invalid <function name> value`, which leaks `parse_root_argument` at the
    operator and hides the sentence explaining the change. Found by running the
    documented command rather than by reading the code.
    """
    with pytest.raises(SystemExit):
        parse_args(["--root", str(tmp_path)])
    err = capsys.readouterr().err
    assert "parse_root_argument" not in err, "the operator was shown a function name"
    assert "label=path" in err, "the refusal does not say what to type instead"


# -- #145: the banner has to LEAVE the process ------------------------------


class BlockBuffered:
    """A stdout that only becomes readable when it is flushed.

    Which is what Python's own stdout is under a systemd unit: not a terminal,
    therefore block buffered, therefore a `print` that is never flushed sits in
    an 8 KB buffer until the process exits. A server does not exit, so the
    banner written for the journal never reached it.

    `capsys` cannot see this, and that is why the fake exists: pytest's capture
    reads what was WRITTEN, so an unflushed banner looks identical to a flushed
    one and every existing banner test passes against the defect.
    """

    def __init__(self) -> None:
        self.pending: list[str] = []
        self.visible = ""

    def write(self, text: str) -> int:
        self.pending.append(text)
        return len(text)

    def flush(self) -> None:
        self.visible += "".join(self.pending)
        self.pending.clear()


def test_the_banner_reaches_the_journal_before_the_server_starts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#145. Observed on a real unit: the whole log was four uvicorn lines.

    uvicorn logs to stderr and appeared; the banner went to a block buffered
    stdout and did not. What is lost is the only statement of which addresses
    this server answers to, in the one deployment where you cannot look at a
    terminal, plus the warning that fires when a service has no
    `HITCHRAIL_TOKEN` and is silently invalidating the phone's link on every
    restart.

    Asserted at the moment the server is constructed rather than after `main`
    returns, because a buffer flushed at exit is no use to a process that does
    not exit.
    """
    (tmp_path / "vessel").mkdir()
    monkeypatch.setenv(JOURNAL_ENV, "9:1234")
    stdout = BlockBuffered()
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr("shutil.which", lambda _n: "/usr/bin/x")
    at_serve_time: dict[str, str] = {}

    def fake_run(_app: object, **_kwargs: object) -> None:
        at_serve_time["visible"] = stdout.visible

    monkeypatch.setattr("uvicorn.run", fake_run)

    main(["--root", f"main={tmp_path}", "--host", "0.0.0.0", "--token", "x" * 16])

    assert "Open one of these on your phone" in at_serve_time["visible"]
