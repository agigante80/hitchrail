"""Command line entry point."""

from __future__ import annotations

import argparse
import os
import secrets
import shutil
import sys
from collections.abc import Callable
from pathlib import Path
from urllib.parse import quote

import uvicorn
from starlette.applications import Starlette

from hitchrail import __version__
from hitchrail.config import (
    TOKEN_ENV,
    Config,
    ConfigError,
    is_wildcard_host,
    remote_reach,
)
from hitchrail.engine import Engine
from hitchrail.events import EventBus
from hitchrail.roots import Root, RootError, parse_root_argument
from hitchrail.server import create_app


def _root_argument(raw: str) -> Root:
    """`parse_root_argument`, with argparse's error rendering fixed.

    argparse renders a `ValueError` from a `type=` callable as
    `invalid <function name> value: '...'`, which shows the operator
    `parse_root_argument` and swallows the sentence saying what to type. An
    `ArgumentTypeError` is printed verbatim instead.

    The wrapper lives HERE rather than in `roots.py` because knowing about
    argparse is the command line's job, and `roots` is engine layer vocabulary
    that stays testable without one.
    """
    try:
        return parse_root_argument(raw)
    except RootError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="hitchrail",
        description="Start and stop headless Claude Code sessions across a folder of projects.",
    )
    # **`label=path`, repeatable, and there is no default.** #119 made a
    # project's identifier `<root-label>~<folder>`, so a root without a label
    # has no name to contribute and a label guessed from the directory name
    # would change when the directory moved, renaming every project on the
    # wire. `default=[]` rather than `default=["main=."]`: an implicit root is
    # how somebody serves their home directory by accident.
    parser.add_argument(
        "--root",
        dest="roots",
        action="append",
        default=[],
        type=_root_argument,
        metavar="LABEL=PATH",
        help="a labelled folder holding projects, as label=path; repeatable",
    )
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


# systemd sets this in a spawned service's environment when it has connected
# that stream to the journal, and it is absent in a terminal. Documented in
# systemd.exec(5) under "Environment Variables in Spawned Processes", so this
# is an interface rather than a guess at a parent process name.
JOURNAL_ENV = "JOURNAL_STREAM"


def token_from_env() -> str | None:
    """The token the environment supplies, or None if it supplies none.

    **Unset and set-but-empty are different, and conflating them is the bug
    this function exists to avoid.** Unset means "not supplied" and the caller
    falls through to generating one. Set to empty or blank means the operator
    believes they configured authentication and did not, which is the trap
    `Config._check_token` already documents, reached there by
    `--token "$HITCHRAIL_TOKEN"` with the variable unset. Generating a token
    here would hide it a second way, so this refuses instead.

    An `EnvironmentFile` line reading `HITCHRAIL_TOKEN=` produces exactly the
    blank case, which is why whitespace counts as empty rather than as a token.
    """
    raw = os.environ.get(TOKEN_ENV)
    if raw is None:
        return None
    if not raw.strip():
        raise ConfigError(
            f"{TOKEN_ENV} is set but empty, which is not a token. Give it a "
            f"real value, or unset it entirely to let Hitchrail generate one"
        )
    return raw


def build_config(args: argparse.Namespace) -> Config:
    # Precedence: the flag, then the environment, then generated. An explicit
    # argument overriding an ambient one is the usual rule, and it keeps a one
    # off run possible without editing a unit file.
    token = args.token or token_from_env()
    # `remote_reach` is imported rather than reimplemented. Two copies of this
    # rule would drift, and the one that drifts is the one deciding whether a
    # token is demanded at all.
    #
    # It asks about reach and not about the bind (#108): behind a proxy a
    # loopback bind is still reachable from a network, and the operator says so
    # with --allow-host or --allow-origin. Generating here under the same
    # predicate that refuses in Config is what stops the CLI producing a config
    # its own constructor then rejects.
    if not token and remote_reach(
        args.host, tuple(args.allow_hosts), tuple(args.allow_origins)
    ):
        token = secrets.token_urlsafe(24)
    return Config(
        roots=tuple(args.roots),
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
    # #110, decided with the unit in hand. Under a service stdout IS journald,
    # so every line here lands in a persistent log readable by root and by the
    # `systemd-journal` group. A token printed to a terminal scrolls away with
    # the operator sitting in front of it; one printed here is kept.
    #
    # So the banner degrades rather than documenting the exposure and printing
    # anyway. The cost of degrading is nearly nil: an operator running a unit
    # supplied `HITCHRAIL_TOKEN` themselves, so withholding it tells them
    # nothing they do not already know. The cost of printing is a stable secret
    # written somewhere permanent.
    in_journal = JOURNAL_ENV in os.environ
    # Only a token the operator does not already have. A generated one is
    # unknowable any other way, so not printing it would make the server
    # unusable; one they put in the environment they can already read.
    generated = config.token != token_from_env()
    lines = ["", "  Anyone with this token can run code on this machine as you."]
    if generated and not in_journal:
        lines.insert(1, f"  token: {config.token}")
    lines += ["", "  Open one of these on your phone:"]
    # Percent encoded, because `--token` takes anything non blank while the
    # page parses the fragment with `URLSearchParams`. `--token 'a&b'` printed a
    # link the page read as `a`, and `--token 'a+b'` one it read as `a b`: a
    # link that silently carries the wrong key, which reads as "the token is
    # wrong" rather than as "the link is wrong". The generated token is
    # `token_urlsafe`, so this only ever shows up for an operator's own.
    #
    # A FRAGMENT, not a query string. Everything after `#` stays in the browser
    # and is never sent to any server, so the token reaches no access log, no
    # reverse proxy log, and no `Referer` header. That is why the link is
    # generated here rather than typed: `/grant#token=` is longer to paste and
    # costs nobody anything, which is the argument #21 settled the design on.
    fragment = "" if in_journal else f"#token={quote(config.token, safe='')}"
    lines += [
        f"    http://{h}:{config.port}/grant{fragment}"
        for h in reachable
        if h not in {"::1", "[::1]"}
    ]
    if in_journal:
        lines += [
            "",
            "  The link is incomplete on purpose. Append the fragment carrying",
            f"  your {TOKEN_ENV} value to open it. It is withheld here because",
            "  this output is the journal: persistent, and readable by root and",
            "  by the systemd-journal group.",
        ]
        if generated:
            lines += [
                "",
                "  This token was GENERATED, which is the wrong shape for a",
                "  service: it changes on every restart, so the link saved on",
                f"  your phone dies with each one. Set {TOKEN_ENV} in the unit's",
                "  EnvironmentFile, at mode 600.",
            ]
    lines += [
        "",
        "  The token stays in the browser: everything after the # is never sent",
        "  to a server. The page trades it for a cookie and clears the address",
        "  bar. Over plain HTTP the cookie still crosses the network in",
        "  cleartext; put a TLS terminating proxy in front of this if that",
        "  matters to you.",
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
        # **`flush=True`, and #145 is why it is not decoration.** Python block
        # buffers stdout when it is not a terminal. Under a systemd unit stdout
        # IS the journal, so this print landed in an 8 KB buffer and stayed
        # there: a server does not exit, so nothing ever flushed it. Observed on
        # a real unit, where the entire log was uvicorn's four lines, which
        # appear only because uvicorn logs to stderr.
        #
        # What that lost is the whole of `banner`'s reason to exist under a
        # service. It is the only statement of which addresses this server will
        # answer to, `allowed_hosts` being derived rather than configured, and
        # it carries the warning that fires when a service has no
        # `HITCHRAIL_TOKEN` and is therefore invalidating the phone's link on
        # every restart. Both are exactly the deployment where you cannot look
        # at a terminal instead.
        #
        # `packaging/hitchrail.service` also sets `PYTHONUNBUFFERED=1`, and that
        # is not belt and braces. This fixes OUR line; that covers everything
        # else the process writes to stdout for a unit whose only output surface
        # is the journal.
        print(text, flush=True)

    engine = Engine(config=config)
    # One bus, built here and owned here, because the CLI owns the process.
    return _serve(create_app(engine=engine, config=config, bus=EventBus()), config)
