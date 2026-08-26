"""Command line entry point."""

from __future__ import annotations

import argparse
import secrets
import shutil
import sys
from collections.abc import Callable
from pathlib import Path

import uvicorn
from starlette.applications import Starlette

from hitchrail import __version__
from hitchrail.config import Config, ConfigError, is_loopback_host, is_wildcard_host
from hitchrail.engine import Engine
from hitchrail.events import EventBus
from hitchrail.server import create_app


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="hitchrail",
        description="Start and stop headless Claude Code sessions across a folder of projects.",
    )
    parser.add_argument("--root", default=".", type=Path, help="folder holding the projects")
    parser.add_argument("--host", default="127.0.0.1", help="address to bind")
    parser.add_argument("--port", default=8787, type=int)
    parser.add_argument(
        "--token", default=None, help="required off loopback; generated if omitted"
    )
    parser.add_argument(
        "--allow-host",
        dest="allow_hosts",
        action="append",
        default=[],
        help="an extra hostname this server will answer to; repeatable",
    )
    parser.add_argument(
        "--allow-origin",
        dest="allow_origins",
        action="append",
        default=[],
        help=(
            "an exact origin a browser may claim, scheme://host[:port]; "
            "repeatable. Needed behind a TLS terminating proxy, whose scheme "
            "and port cannot be derived from our own bind"
        ),
    )
    parser.add_argument(
        "--self-project", default=None, help="a project that must never be stopped"
    )
    # Promised by the README's prerequisites table and required by #28, which
    # refuses to start when this binary is missing and names it in the message.
    # A flag the README documents and the CLI does not accept is a bug the
    # first user finds.
    #
    # `--agent-binary`, never `--claude-binary`: no vendor name enters the
    # operator contract. The quarantine is a seam, not an abstraction.
    parser.add_argument(
        "--agent-binary",
        default="claude",
        help="the agent executable to run; must be on PATH or an absolute path",
    )
    # A documented default that cannot be changed is a constant, and this one
    # is the wait a person actually watches. The three memory floors stay fixed
    # in v1 deliberately: they are a safety net rather than a preference, and
    # an operator who wants a different one is usually asking for a machine
    # with more memory.
    parser.add_argument(
        "--stop-timeout",
        default=30,
        type=int,
        help="seconds to wait for a graceful stop before reporting it timed out",
    )
    parser.add_argument("--version", action="version", version=f"hitchrail {__version__}")
    return parser.parse_args(argv)


def build_config(args: argparse.Namespace) -> Config:
    token = args.token
    # is_loopback_host is imported rather than reimplemented. Two copies of
    # this rule would drift, and the one that drifts is the one deciding
    # whether a token is demanded at all.
    if not is_loopback_host(args.host) and not token:
        token = secrets.token_urlsafe(24)
    return Config(
        root=args.root,
        host=args.host,
        port=args.port,
        token=token,
        extra_hosts=tuple(args.allow_hosts),
        extra_origins=tuple(args.allow_origins),
        self_project=args.self_project,
        agent_binary=args.agent_binary,
        stop_timeout=args.stop_timeout,
    )


def banner(config: Config) -> str:
    """What to print before serving. Empty on loopback, where there is no token.

    The links matter: the token grant only helps if something hands the user a
    URL carrying it, and typing a 32 character token into a phone is not a
    thing anybody does twice.
    """
    if not config.token:
        return ""

    reachable = [h for h in config.allowed_hosts if not is_wildcard_host(h)]
    lines = [
        "",
        f"  token: {config.token}",
        "  Anyone with this token can run code on this machine as you.",
        "",
        "  Open one of these on your phone:",
    ]
    lines += [
        f"    http://{h}:{config.port}/?token={config.token}"
        for h in reachable
        if h not in {"::1", "[::1]"}
    ]
    lines += [
        "",
        "  The link sets a cookie and drops the token from the address bar.",
        "  Over plain HTTP the token crosses the network in cleartext; put a",
        "  TLS terminating proxy in front of this if that matters to you.",
        "",
    ]
    return "\n".join(lines)


# The prerequisites Hitchrail drives but does not install. Neither is a Python
# dependency, so every documented install route succeeds on a machine that
# cannot run a single session. See #28.
MEMINFO = Path("/proc/meminfo")


def preflight(
    config: Config,
    which: Callable[[str], str | None] | None = None,
    meminfo: Path = MEMINFO,
) -> list[str]:
    """What is missing, in the operator's words. Empty means good to go.

    Hitchrail is a launcher, and its two prerequisites are binaries rather than
    packages. Without this the failure arrives at the first tap on a project,
    from inside the engine, as a FileNotFoundError on a subprocess call: a
    failed start with no explanation, in a web interface, on a phone, which is
    the worst place there is to discover a missing package.

    `which` and `meminfo` are injected so the tests never touch PATH. A test
    that edits the environment to prove a lookup fails is a test that can break
    a neighbouring one, and PATH manipulation is not hermetic.

    **Deliberately not a version check.** The tmux addressing behaviours this
    project works around are old and stable, and a version gate would refuse a
    perfectly capable tmux the day somebody ships a fork or a distro patches
    the version string. Check the binary is there, never what it claims to be.
    """
    # Resolved HERE rather than as a default argument. `which=shutil.which` in
    # the signature binds at definition time, so a test monkeypatching
    # `shutil.which` afterwards changes nothing and passes against a preflight
    # that never runs. Looked up per call, the patch lands.
    look = which if which is not None else shutil.which
    problems = []
    if look("tmux") is None:
        problems.append(
            "tmux is not on PATH. Hitchrail runs every session inside tmux, so "
            "there is nothing it can do without it. Install it with your "
            "package manager, for example: sudo apt install tmux"
        )
    if look(config.agent_binary) is None:
        problems.append(
            f"{config.agent_binary!r} is not on PATH. That is the agent "
            "Hitchrail starts. Install it, or point --agent-binary at the "
            "executable you meant"
        )
    if not meminfo.exists():
        problems.append(
            f"{meminfo} cannot be read, so the memory guard has nothing to "
            "read. Hitchrail assumes Linux for this, and refuses to start "
            "rather than run without the check that stops it filling the "
            "machine with agents"
        )
    return problems


def _serve(app: Starlette, config: Config) -> int:
    uvicorn.run(app, host=config.host, port=config.port, log_level="info")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        config = build_config(args)
        # allowed_hosts is a property, so a bad extra host only raises when it
        # is read. Read it here, inside the guard, rather than letting it
        # surface as a traceback from inside uvicorn.
        _ = config.allowed_hosts
    except ConfigError as exc:
        print(f"hitchrail: {exc}", file=sys.stderr)
        return 2

    # BEFORE the banner and before the bind. Printing a token and a set of
    # links, then refusing to work, would be worse than refusing plainly.
    problems = preflight(config)
    if problems:
        print("hitchrail: cannot start.", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 2

    text = banner(config)
    if text:
        print(text)

    engine = Engine(config=config)
    # One bus, built here and owned here, because the CLI owns the process.
    return _serve(create_app(engine=engine, config=config, bus=EventBus()), config)
