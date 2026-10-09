"""Command line entry point."""

from __future__ import annotations

import argparse
import logging
import os
import platform
import secrets
import shutil
import ssl
import sys
from collections.abc import Callable
from dataclasses import replace
from importlib.metadata import PackageNotFoundError, metadata
from pathlib import Path
from typing import NamedTuple
from urllib.parse import quote

import uvicorn
from starlette.applications import Starlette

from hitchrail import __version__, claude_ipc, gateway, logs, settings
from hitchrail.config import (
    TOKEN_ENV,
    Config,
    ConfigError,
    check_agent_binary,
    remote_reach,
)
from hitchrail.engine import Engine
from hitchrail.events import EventBus
from hitchrail.hostnames import is_loopback_host, origin_forms, reachable_hosts
from hitchrail.roots import Root, RootError, parse_root_argument
from hitchrail.server import create_app

# #326. `pyproject.toml`'s `description`, which is also PyPI's summary
# (#328), the GitHub About field (#328), the README's centred tagline
# (#158) and the meta description on index.html/settings.html (#331). Read
# from the installed distribution's metadata rather than retyped a sixth
# time, the same seam `installed_version()` in `hitchrail/__init__.py`
# already uses for the version. The surfaces that cannot run Python
# (`README.md` and the two HTML pages) are checked against the same
# `pyproject.toml` field instead, by `tests/test_docs_are_true.py`.
_FALLBACK_DESCRIPTION = (
    "Start and stop headless Claude Code sessions across a folder of projects, "
    "from a phone-first web UI."
)


def _one_line_description() -> str:
    try:
        summary = metadata("hitchrail")["Summary"]
    except (PackageNotFoundError, KeyError):  # pragma: no cover (only from a bare checkout)
        return _FALLBACK_DESCRIPTION
    return summary or _FALLBACK_DESCRIPTION


ONE_LINE_DESCRIPTION = _one_line_description()

# Matches pyproject.toml's [project.urls] Homepage. Kept by hand: unlike the
# description above, nothing else in this module has a reason to read
# Project-URLs, and one more metadata lookup for a string that never changes
# is not worth the indirection.
GITHUB_URL = "https://github.com/agigante80/hitchrail"


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


# #141. Two worked examples, not a fifth spelling of one: both are already
# in the README (the bare case just above "## Prerequisites", the proxied
# case in "## What it costs you to run this"), so the epilog quotes rather
# than invents. clig.dev's own strongest recommendation is examples first,
# particularly the unobvious complex case, which here is needing BOTH
# allowlist flags to sit behind a proxy.
# Built from a list and joined, rather than one string with an inline
# newline escape after each line: the leak-guard's home-root pattern stops
# at a quote, not at an escape sequence, so a root glued directly to that
# escape reads as one longer root, which no allow-file entry can name.
_EXAMPLE_LINES = (
    "  hitchrail --root main=~/projects",
    "  hitchrail --root main=~/dev --host 0.0.0.0 --allow-host box.lan "
    "--allow-origin https://box.lan",
)
_EXAMPLES = "examples:\n" + "\n".join(_EXAMPLE_LINES) + "\n"


def build_parser(*, mention_update_plugins: bool = True) -> argparse.ArgumentParser:
    """`mention_update_plugins=False` is for the "no roots configured" refusal
    (see `main`'s `except ConfigError`), which reuses this parser's help to
    stay concise (#141) rather than to introduce the unrelated subcommand.
    `test_bare_hitchrail_still_means_the_server` (#124) is the compatibility
    promise behind that: the old, root-less invocation must not read like it
    is being pointed at `update-plugins`, whatever `--help` itself goes on to
    mention.
    """
    epilog = _EXAMPLES
    if mention_update_plugins:
        epilog += (
            f"\n{UPDATE_PLUGINS}: update the agent's plugins and exit, with no server. "
            f"See `hitchrail {UPDATE_PLUGINS} --help`"
        )
    parser = argparse.ArgumentParser(
        prog="hitchrail",
        description=ONE_LINE_DESCRIPTION,
        # #238. `flags_given` reads the option strings back out of argv to
        # say where a value came from, and an abbreviation argparse would
        # accept (`--stop 60`) is a spelling that scan cannot see. Exact
        # names only, which is what every document here uses anyway.
        allow_abbrev=False,
        # Raw, so the examples above keep their line breaks: the default
        # formatter refills an epilog into one paragraph and loses them.
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=epilog,
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
    # #154. The file is the other door for roots. `--root` on the command
    # line still wins, outright: a flag beside a file does not add to it.
    parser.add_argument(
        "--config",
        default=None,
        type=Path,
        metavar="FILE",
        help="the config file; default ~/.config/hitchrail/config.toml",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="address to bind; default 127.0.0.1, the safe loopback choice",
    )
    parser.add_argument("--port", default=8787, type=int, help="port to bind; default 8787")
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
        help="the agent executable to run; must be on PATH or an absolute path; default claude",
    )
    # A documented default that cannot be changed is a constant, and this one
    # is the wait a person actually watches. The three memory floors stay fixed
    # in v1 deliberately: they are a safety net rather than a preference, and
    # an operator who wants a different one is usually asking for a machine
    # with more memory.
    # #152. TLS from the server itself, so a LAN deployment needs no second
    # daemon. Both or neither, refused in `Config` before the bind.
    parser.add_argument(
        "--tls-cert",
        default=None,
        type=Path,
        metavar="FILE",
        help="a PEM certificate; serve HTTPS with it. Needs --tls-key",
    )
    parser.add_argument(
        "--tls-key",
        default=None,
        type=Path,
        metavar="FILE",
        help="the PEM private key for --tls-cert",
    )
    # #207. The wrong network guard: the unit stays stopped when the default
    # gateway is not the one named here. Off when absent.
    parser.add_argument(
        "--expect-gateway-mac",
        default=None,
        metavar="MAC",
        help="refuse to start unless the default gateway has this MAC address: a guard "
        "against a laptop serving on a network it joined by accident. Unset, off",
    )
    parser.add_argument(
        "--session-prefix",
        # `None` rather than "hr-", so the file's value is used when the flag
        # is absent and the flag still wins when it is given (#123).
        default=None,
        metavar="PREFIX",
        help="what every tmux session this instance creates is named with, and the "
        "only sessions it will ever stop; default hr-. Two instances sharing a tmux "
        "server need two prefixes, or each can stop the other's agents",
    )
    parser.add_argument(
        "--stop-timeout",
        default=30,
        type=int,
        help="seconds to wait for a graceful stop before reporting it timed out; default 30",
    )
    # #242. `None` defaults for the same reason as `--session-prefix`: the
    # file's value is used when the flag is absent.
    parser.add_argument(
        "--stop-prompt",
        default=None,
        metavar="TEXT",
        help="one line Stop types to the agent before it exits, queued behind the "
        "task in flight, such as a slash command that commits and writes notes; "
        "unset, Stop exits at once. Kill still interrupts",
    )
    parser.add_argument(
        "--stop-prompt-timeout",
        default=None,
        type=int,
        metavar="SECONDS",
        help="how long the agent has to finish the task and the stop prompt before "
        "Stop exits anyway; default 300",
    )
    # #239. Choices are not given to argparse: `Config` is the one refusal,
    # for the flag and the file alike, in the same words.
    parser.add_argument(
        "--stop-policy",
        default=None,
        metavar="POLICY",
        help="what a stop that runs out of time on a question does: 'ask' (default) "
        "reports and offers Kill; 'end_anyway' kills the session without the tap",
    )
    # #167. Hitchrail's own lines only: uvicorn's stay at info below that,
    # since its debug is protocol tracing. `--verbose` exists so that "run it
    # with --verbose and send me the output" is a sentence, which is the
    # whole reason for the ticket.
    loudness = parser.add_mutually_exclusive_group()
    loudness.add_argument(
        "--log-level",
        choices=logs.LEVELS,
        default=logs.DEFAULT_LEVEL,
        help=f"how much Hitchrail writes to stderr; default {logs.DEFAULT_LEVEL}",
    )
    loudness.add_argument(
        "--verbose",
        dest="log_level",
        action="store_const",
        const="debug",
        help="the same as --log-level debug",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"hitchrail {__version__}",
        help="print the version and exit",
    )
    return parser


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.given = flags_given(parser, argv)
    return args


def flags_given(parser: argparse.ArgumentParser, argv: list[str]) -> frozenset[str]:
    """The destinations whose flag appears in argv, `--x v` and `--x=v` alike.

    A value equal to the default is not the same as a default: `--stop-timeout
    30` is the operator pinning it, and the settings page must say `flag` and
    refuse to write over it. argparse does not record which is which, so this
    reads the tokens. `--` ends the options, as it does for argparse.
    """
    names = {opt: action.dest for action in parser._actions for opt in action.option_strings}
    given: set[str] = set()
    for word in argv:
        if word == "--":
            break
        dest = names.get(word.split("=", 1)[0])
        if dest is not None:
            given.add(dest)
    return frozenset(given)


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
    config_path = args.config or settings.default_config_path()
    try:
        file_settings = settings.read_config_file(config_path)
    except settings.SettingsError as exc:
        raise ConfigError(str(exc)) from exc
    # The flags win outright (#154): a root the operator did not name on this
    # command line appearing anyway is the surprise that matters on a tool
    # that spawns agents.
    roots = tuple(args.roots) if args.roots else file_settings.roots
    # `is not None`, not truthiness: `--session-prefix ""` must reach the
    # blank refusal in `Config` rather than fall through to the default.
    prefix = args.session_prefix
    if prefix is None:
        prefix = file_settings.session_prefix
    if prefix is None:
        # The dataclass default stays the one place "hr-" is spelled.
        prefix = Config.session_prefix
    stop_prompt = args.stop_prompt
    if stop_prompt is None:
        stop_prompt = file_settings.stop_prompt
    stop_prompt_timeout = args.stop_prompt_timeout
    if stop_prompt_timeout is None:
        stop_prompt_timeout = file_settings.stop_prompt_timeout
    if stop_prompt_timeout is None:
        stop_prompt_timeout = Config.stop_prompt_timeout
    stop_policy = args.stop_policy
    if stop_policy is None:
        stop_policy = file_settings.stop_policy
    if stop_policy is None:
        stop_policy = Config.stop_policy
    given: frozenset[str] = getattr(args, "given", frozenset())

    def source(dest: str, from_file: bool = False) -> str:
        return "flag" if dest in given else "file" if from_file else "default"

    sources = {
        "roots": source("roots", from_file=bool(file_settings.roots)),
        "config": source("config"),
        "host": source("host"),
        "port": source("port"),
        "token": "flag" if args.token else "env" if os.environ.get(TOKEN_ENV) else "generated",
        "extra_hosts": source("allow_hosts"),
        "extra_origins": source("allow_origins"),
        "self_project": source("self_project"),
        "agent_binary": source("agent_binary"),
        "session_prefix": source("session_prefix", file_settings.session_prefix is not None),
        "stop_timeout": source("stop_timeout"),
        "stop_prompt": source("stop_prompt", file_settings.stop_prompt is not None),
        "stop_prompt_timeout": source(
            "stop_prompt_timeout", file_settings.stop_prompt_timeout is not None
        ),
        "stop_policy": source("stop_policy", file_settings.stop_policy is not None),
        "tls": source("tls_cert"),
        "expect_gateway_mac": source("expect_gateway_mac"),
    }
    return Config(
        roots=roots,
        state_path=settings.state_path_for(config_path),
        config_path=config_path,
        sources=sources,
        session_prefix=prefix,
        tls_cert=args.tls_cert,
        tls_key=args.tls_key,
        expect_gateway_mac=args.expect_gateway_mac,
        host=args.host,
        port=args.port,
        token=token,
        extra_hosts=tuple(args.allow_hosts),
        extra_origins=tuple(args.allow_origins),
        self_project=args.self_project,
        agent_binary=args.agent_binary,
        stop_timeout=args.stop_timeout,
        stop_prompt=stop_prompt,
        stop_prompt_timeout=stop_prompt_timeout,
        stop_policy=stop_policy,
    )


def identity_banner() -> str:
    """The name, the one line description, the version and the project's
    home, unconditionally (#326). Separate from `banner()` below and never
    touching it: `banner()` stays exactly what it already is, silent until
    there is a token to grant, and this one always has something to print.

    Takes no `Config`, on purpose: it carries nothing derived from one, which
    is what lets it print before `build_config()` runs and still appear when
    a later config, preflight or gateway check refuses to start, exactly the
    case a stranger's bug report needs it most.

    `flush=True` belongs to the `print` call at the call site in `main()`,
    not here: this only builds the string. The reason is #145, already
    documented at `banner()`'s own call site: stdout is block buffered under
    the unit, and an unflushed line here would never reach the journal either.
    """
    return f"hitchrail {__version__}: {ONE_LINE_DESCRIPTION}\n{GITHUB_URL}"


def banner(config: Config) -> str:
    """What to print before serving. Empty on loopback, where there is no token.

    The links matter: the token grant only helps if something hands the user a
    URL carrying it, and typing a 32 character token into a phone is not a
    thing anybody does twice.
    """
    if not config.token:
        return ""

    reachable = reachable_hosts(config.host, config.allowed_hosts, config.extra_hosts)
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
        f"    {config.scheme}://{h}:{config.port}/grant{fragment}"
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


def _stop_prompt_line(config: Config) -> str:
    if not config.stop_prompt:
        return "stop prompt none"
    if config.stop_prompt.startswith("/"):
        kind = "a slash command"
    else:
        kind = (
            "plain text: delivered at the agent's next tool boundary, inside its current task"
        )
    return f"stop prompt set ({kind}), waits up to {config.stop_prompt_timeout:g}s"


def startup_block(config: Config, found: Preflight, level: str) -> list[str]:
    """What a bug report needs to be a diagnosis, one fact per line (#167).

    Logged once, after the preflight and before the bind, so every line
    describes the configuration that is about to serve. The token's SOURCE and
    never its value: this is written to the journal, which `banner()`
    already refuses to put a token in for the reasons it gives.

    Not the account it runs as, though #148 shows it on the page: under a
    unit the journal records the uid on every entry, and in a terminal the
    person reading this is that account.
    """
    if config.token is None:
        credential = "none, so only this machine can reach it"
    else:
        credential = f"from {config.sources.get('token', 'the caller')}"
    lines = [
        f"hitchrail {__version__} on Python {platform.python_version()}, pid {os.getpid()}",
        *(f"root {root.label}={root.path}" for root in config.roots),
        f"serving {config.scheme}://{config.host}:{config.port}, "
        f"TLS {'on' if config.tls_cert else 'off'}, token {credential}",
        f"answers to Host {', '.join(config.allowed_hosts)}",
        f"agent {config.agent_binary!r} at {config.spawn_agent_binary}",
        f"tmux {found.tmux_binary}, socket {config.tmux_socket or 'the default'}",
        f"sessions prefixed {config.session_prefix!r}, stop timeout {config.stop_timeout:g}s, "
        f"stop policy {config.stop_policy}",
        # Whether a prompt is set, never the prompt: what an operator tells
        # their agent is theirs, and this line goes to the journal. #242 asked
        # for the text itself; the kind is what an operator needs to debug a
        # wrap up that ran inside the current task, and it reveals nothing.
        _stop_prompt_line(config),
        f"config file {config.config_path or 'none'}, log level {level}",
    ]
    if config.self_project:
        lines.append(f"self project {config.self_project}, never stopped from here")
    # #283: the mirror of #268's refusal. It works, so it is a line, not a
    # refusal. #394: only where rebinding to loopback would set the flag.
    if not config.tls and not config.is_loopback and config.proxied_origins_are_https:
        lines.append(
            "token cookie not Secure: every proxy origin is https but this plain http "
            "bind is off loopback; bind loopback behind the proxy to get the flag, "
            "after which the plain http LAN address is no longer served and the page is "
            "reached through the proxy"
        )
    # #391: the grant from these is now refused, and an operator on a plain
    # forwarder needs to learn that before the phone does. Not for a host
    # that is also the host of an https origin: that is phone-access.md's
    # own deployment (loopback bind, `--allow-host` and `--allow-origin
    # https://` for one name), and the advice to give the plain origin would
    # drop Secure from a working setup. The mixed case (an https proxy for
    # `box.lan` AND a plain forwarder on `box.lan:8787`) is quiet too, kept
    # deliberately (#439): the allowlist records no port to tell them apart,
    # and the forwarder's grant meets the named 403. The filter is here, not
    # in `plain_origins_withheld`, which the 403 reads.
    https_hosts = config.https_origin_hosts
    for host in config.plain_origins_withheld:
        if host in https_hosts:
            continue
        plain = min(origin_forms("http", host, config.port), key=len)
        # A loopback name here is `localhost.localdomain` (#436): the cookie
        # rule ignores loopback origins, so giving it would not turn Secure off.
        fix = (
            f"Browse http://localhost:{config.port} instead"
            if is_loopback_host(host)
            else f"Give --allow-origin {plain} to serve it, which turns Secure off"
        )
        lines.append(
            f"plain http origin not derived for {plain}: every non loopback "
            f"--allow-origin is https, so the token cookie is Secure and a browser "
            f"on plain http would drop it. {fix}"
        )
    return lines


# The prerequisites Hitchrail drives but does not install. Neither is a Python
# dependency, so every documented install route succeeds on a machine that
# cannot run a single session. See #28.
MEMINFO = Path("/proc/meminfo")


class Preflight(NamedTuple):
    """`problems` empty means good to go. `agent_binary` is the absolute path
    the lookup resolved, carried alongside `problems` rather than thrown away
    once they are empty (#196): a bare name here would still be re-resolved
    by whatever spawns it next, in that thing's own environment rather than
    this process's, which is the mismatch #298 also names."""

    problems: list[str]
    agent_binary: str | None
    # #167. Where tmux was found, for the startup block; the adapter still
    # runs the bare name, as it always has.
    tmux_binary: str | None = None


def preflight(
    config: Config,
    which: Callable[[str], str | None] | None = None,
    meminfo: Path = MEMINFO,
) -> Preflight:
    """What is missing, in the operator's words, and the agent binary's
    resolved path when there is nothing missing to report it against.

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
    tmux = look("tmux")
    if tmux is None:
        problems.append(
            "tmux is not on PATH. Hitchrail runs every session inside tmux, so "
            "there is nothing it can do without it. Install it with your "
            "package manager, for example: sudo apt install tmux"
        )
    found = look(config.agent_binary)
    # #341. A value with a directory in it is a path the operator TYPED, and
    # `shutil.which` does not search PATH for one: it checks that path where
    # it stands and never makes it absolute. So neither PATH message below is
    # true of it, and each would send the operator to fix a PATH never read.
    # `os.path.dirname` and not `Path.parent`: `Path("./claude")` normalises
    # the "./" away, and `which` decides by the same `dirname` test this is.
    typed = bool(os.path.dirname(config.agent_binary))  # noqa: PTH120
    if found is None and typed:
        # #393. Relative, it was looked for from the cwd, and `~` is not
        # expanded; saying so also saves the round trip of the relative
        # refusal below once the file is there.
        where = (
            ", looked for relative to the current directory; give an absolute path"
            if not Path(config.agent_binary).is_absolute()
            else ""
        )
        problems.append(
            f"{config.agent_binary!r} is not an executable file{where}. That is "
            "the agent Hitchrail starts, and a value containing a directory is "
            "taken as a path to that file"
        )
    elif found is None:
        # **"Install it" is the wrong first remedy, and #195 is why.** The case
        # this actually fires in is a lingering systemd unit at boot: the agent
        # IS installed, in `~/.local/bin`, and the user manager's PATH before
        # any login is systemd's fallback, which does not include it. Telling
        # somebody to install what they already installed sends them looking in
        # the wrong place, and the message is the only thing they get, because
        # this refusal happens with no terminal attached.
        problems.append(
            f"{config.agent_binary!r} is not on PATH. That is the agent "
            "Hitchrail starts. Install it, point --agent-binary at the "
            "executable, or if it is installed, put its directory on the PATH "
            "THIS process has: under a systemd unit that is the unit's own "
            "Environment=PATH rather than your login's"
        )
    elif not Path(found).is_absolute() and typed:
        # Refused for the same reason as the relative PATH entry below: the
        # child's cwd would decide which file runs. `update-plugins` accepts
        # this shape instead, resolving it at once (#298), because there the
        # check and the spawn are one command in one directory; a server
        # spawns for as long as it runs.
        problems.append(
            f"{config.agent_binary!r} is a relative path, which would be "
            "looked up from wherever each agent is started. Give "
            "--agent-binary an absolute path, or a bare name found on PATH"
        )
        found = None
    elif not Path(found).is_absolute():
        # A PATH entry given as a relative directory, "." most often, is the
        # one shape `shutil.which` will hand back unresolved: everything else
        # it finds it joins onto an absolute directory first. Spawning that
        # would be #298 again, decided by whatever the CHILD's cwd turns out
        # to be rather than by this lookup, so it is refused here instead.
        problems.append(
            f"{found!r} resolved to a relative path from a relative PATH "
            "entry. Put an absolute directory earlier on PATH, or point "
            "--agent-binary directly at the executable"
        )
        found = None
    if not meminfo.exists():
        problems.append(
            f"{meminfo} cannot be read, so the memory guard has nothing to "
            "read. Hitchrail assumes Linux for this, and refuses to start "
            "rather than run without the check that stops it filling the "
            "machine with agents"
        )
    return Preflight(problems, found if not problems else None, tmux)


EXIT_REFUSED = 2
EXIT_TRANSIENT = 3


def gateway_verdict(
    config: Config, gateway_mac: Callable[[], str] | None = None
) -> tuple[int, str] | None:
    """`None` to start; else the exit code and the sentence for the journal.

    Resolved per call, for the reason `preflight`'s `look` gives: a default
    bound at definition time is what a test's monkeypatch cannot reach, and
    the first version of the exit 2 test read this machine's real tables and
    passed because the developer's gateway happened not to match.
    """
    if config.expect_gateway_mac is None:
        return None
    read = gateway_mac if gateway_mac is not None else gateway.gateway_mac
    try:
        found = read()
    except gateway.GatewayPinned as exc:
        return (
            EXIT_REFUSED,
            f"--expect-gateway-mac is set and {exc}. Unpin it, or unset the flag",
        )
    except gateway.GatewayUnknown as exc:
        return (
            EXIT_TRANSIENT,
            f"--expect-gateway-mac is set and the network cannot be identified yet: {exc}. "
            "Refusing rather than guessing which network this is; the unit retries",
        )
    if found != config.expect_gateway_mac:
        return (
            EXIT_REFUSED,
            f"the default gateway is {found}, not the expected "
            f"{config.expect_gateway_mac}: this machine is on a different network "
            "from the one --expect-gateway-mac names, so nothing is served. If "
            "the network is right and the gateway changed, update the flag",
        )
    return None


class _KeyIsEncrypted(Exception):
    """OpenSSL asked for a passphrase, which means the key has one (#258)."""


def _refuse_to_be_asked() -> bytes:
    """The `password=` callback. Called only for an encrypted key, and it
    raises rather than returning, so the tty prompt is never reached."""
    raise _KeyIsEncrypted


def build_tls_context(config: Config) -> ssl.SSLContext | None:
    """The certificate pair, loaded ONCE, into the context uvicorn serves
    with (#267). `None` is no TLS.

    Here rather than in `Config` so a settings write never re-reads the
    private key, and handed to uvicorn as the context itself rather than as
    two paths it would read again at bind time: one read, one object, and
    the check-then-bind window the old `_serve` comment admitted to is gone.
    A pair that cannot be loaded is exit 2 with the file named, which the
    unit leaves stopped; uvicorn's own failure would be exit 1, retried.

    TLS 1.2 is the floor, set rather than inherited: uvicorn's default
    context sets none, and OpenSSL 3's security level happens to refuse 1.1
    where a 1.1.1 build would not.

    An ENCRYPTED key refuses here in words rather than prompting (#258).
    `openssl req` without `-nodes` writes one, and with no `password=`
    OpenSSL asks on the tty: interactively that is two prompts, one here and
    one inside uvicorn, and under the unit there is no tty and the start
    fails saying nothing useful. The callback below is what makes the prompt
    unreachable: OpenSSL calls it only for an encrypted key, and it refuses
    instead of answering. A way to SUPPLY the passphrase is #280; this is
    the refusal.
    """
    if config.tls_cert is None or config.tls_key is None:
        return None
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    try:
        context.load_cert_chain(
            str(config.tls_cert), str(config.tls_key), password=_refuse_to_be_asked
        )
    except _KeyIsEncrypted as exc:
        raise ConfigError(
            f"--tls-key {config.tls_key} is encrypted with a passphrase, and Hitchrail "
            f"will not ask for one: under the unit there is no terminal to ask at, so the "
            f"start would hang rather than refuse. Decrypt it "
            f"(`openssl rsa -in {config.tls_key} -out {config.tls_key}`), or serve behind "
            f"a proxy that holds the key"
        ) from exc
    except (ssl.SSLError, OSError) as exc:
        raise ConfigError(
            f"--tls-cert {config.tls_cert} with --tls-key {config.tls_key} cannot be "
            f"loaded, so nothing will be served on this port: {exc}"
        ) from exc
    return context


def _serve(app: Starlette, config: Config, tls: ssl.SSLContext | None) -> int:
    # The context, not the paths: with a factory uvicorn serves TLS from the
    # object it is handed and reads no file. `None` is plain HTTP.
    uvicorn.run(
        app,
        host=config.host,
        port=config.port,
        # #167. `None`: `logs.configure` already set up uvicorn's loggers,
        # and uvicorn's own dictConfig would replace them with a second
        # format on a second stream. The level is still applied, since
        # uvicorn sets it on its loggers after this.
        log_config=None,
        log_level=logs.uvicorn_level(),
        ssl_context_factory=None if tls is None else (lambda _config, _default: tls),
    )
    return 0


UPDATE_PLUGINS = "update-plugins"


def _grouped(
    outcomes: list[claude_ipc.PluginOutcome],
) -> list[tuple[claude_ipc.PluginOutcome, int]]:
    """Identical skipped rows as one, with how many (#312), at the first one's
    place. Only `skipped` collapses: a `failed` or `updated` row is never
    noise, and the record keeps every row."""
    counted: dict[tuple[str, str, str], int] = {}
    order: list[claude_ipc.PluginOutcome] = []
    for o in outcomes:
        key = (o.plugin, o.scope, o.result)
        if o.result == "skipped" and key in counted:
            counted[key] += 1
            continue
        counted[key] = 1
        order.append(o)
    return [(o, counted[(o.plugin, o.scope, o.result)]) for o in order]


def _outcome_line(outcome: claude_ipc.PluginOutcome, times: int = 1) -> str:
    notes = []
    if outcome.from_version and outcome.to_version:
        notes.append(f"{outcome.from_version} to {outcome.to_version}")
    if outcome.detail:
        notes.append(f"{outcome.detail}, listed {times} times" if times > 1 else outcome.detail)
    elif outcome.approved_command:
        notes.append(f"approved: {outcome.approved_command}")
    line = f"{outcome.result:<8} {outcome.plugin}"
    return f"{line} ({'; '.join(notes)})" if notes else line


def update_plugins_command(argv: list[str]) -> int:
    """`hitchrail update-plugins`: 0 when nothing failed, 1 when a plugin
    failed, 2 when the operation could not run (#124).

    **Its own parser, dispatched before the server's**, rather than a
    subparser. The server's parser has no positionals and a `flags_given`
    scan (#238) that reads its option strings back out of argv; subparsers
    would restructure both to add one verb, and bare `hitchrail` launching the
    server is the compatibility promise that keeps this MINOR. A
    `--update-plugins` flag was the other option and is worse: it makes a verb
    look like a setting, the mistake the API avoided by keeping stop and kill
    as separate routes.

    It never builds a `Config`: it needs no root, no bind and no token, and a
    machine with no config file must still be able to run it.
    """
    parser = argparse.ArgumentParser(
        prog=f"hitchrail {UPDATE_PLUGINS}",
        description="Refresh the agent's marketplaces and update every user scope "
        "plugin, one result per plugin. Running sessions keep the old versions "
        "until they are restarted.",
        allow_abbrev=False,
    )
    parser.add_argument(
        "--agent-binary",
        default="claude",
        help="the agent executable; must be on PATH or an absolute path",
    )
    args = parser.parse_args(argv)
    try:
        binary = check_agent_binary(args.agent_binary)
    except ConfigError as exc:
        print(f"hitchrail: {exc}", file=sys.stderr)
        return 2
    resolved = shutil.which(binary)
    if resolved is None:
        print(
            f"hitchrail: agent_missing: {binary!r} is not on PATH, so nothing was updated",
            file=sys.stderr,
        )
        return 2
    # #298. `shutil.which` hands a name containing a directory component back
    # still relative when it is executable, never made absolute: only a
    # bare name searched across PATH comes back joined onto an absolute
    # directory. `resolve()` against THIS process's cwd, before
    # `plugin_runner` starts the child in `Path.home()`, is what makes the
    # program checked and the program run the same file.
    #
    # **Serve's `preflight` refuses the same typed relative path, and the
    # difference is deliberate (#341).** Here the check and the spawn happen
    # in one command, from one directory, so resolving once is exact. A
    # server spawns agents for as long as it runs, and asks the operator for
    # an absolute path instead. `resolve()` also follows a symlink, which
    # `preflight` leaves alone; either names the same executable.
    resolved = str(Path(resolved).resolve())

    heard: list[claude_ipc.PluginOutcome] = []

    def progress(outcome: claude_ipc.PluginOutcome) -> None:
        # Not a result: whether an update changed anything is only known
        # after the last one (#311), so this says only that the run is alive,
        # on stderr so stdout is the final account and nothing else. The rows
        # are kept for the one run that never gets a final account: a failure
        # part way still owes the person every row it got to.
        heard.append(outcome)
        if outcome.result != "skipped":
            print(f"... {outcome.plugin}", file=sys.stderr, flush=True)

    try:
        outcomes = claude_ipc.update_plugins(
            resolved, run=claude_ipc.plugin_runner(withhold=(TOKEN_ENV,)), report=progress
        )
    except claude_ipc.PluginsFailed as exc:
        # Provisional rows, with no second listing behind them: `updated`
        # here may be a plugin that did not move, and says only that the
        # update exited cleanly.
        for outcome, times in _grouped(heard):
            print(_outcome_line(outcome, times))
        # The code first: it is the same word the route's record carries, so
        # a script or a person can match on it rather than on the prose.
        print(f"hitchrail: {exc.code}: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        # The other run with no final account, and the likelier one: a plugin
        # hanging on its timeout is when a person reaches for Ctrl-C. Since
        # rows print only at the end, letting this escape would print none,
        # and which plugins already failed is what they stopped it to learn.
        for outcome, times in _grouped(heard):
            print(_outcome_line(outcome, times))
        print(
            "hitchrail: interrupted: the rows above are every plugin it got to", file=sys.stderr
        )
        return 130
    for outcome, times in _grouped(outcomes):
        print(_outcome_line(outcome, times))
    counts = {
        r: sum(o.result == r for o in outcomes)
        for r in ("updated", "current", "failed", "skipped")
    }
    print(
        f"{counts['updated']} updated, {counts['current']} current, "
        f"{counts['failed']} failed, {counts['skipped']} skipped. "
        "An update applies when a session next starts: running sessions keep the old "
        "version until they are restarted."
    )
    return 1 if counts["failed"] else 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == [UPDATE_PLUGINS]:
        return update_plugins_command(argv[1:])
    args = parse_args(argv)
    # #167. First, before the config is built, so every module shares one
    # configuration from its first line.
    #
    # The refusals below stay `print`s to stderr rather than becoming log
    # records: they are this command's answer to a person at a terminal, in
    # the `hitchrail: ...` form the README and the CLI tier quote, and under
    # the unit stderr reaches the journal either way.
    logs.configure(args.log_level)
    # #326. Before build_config(): identity_banner() carries nothing derived
    # from a Config, so it still appears when a later config, preflight or
    # gateway check refuses to start. flush=True for the same #145 reason
    # banner()'s own print below documents.
    print(identity_banner(), flush=True)
    try:
        config = build_config(args)
        # allowed_hosts is a property, so a bad extra host only raises when it
        # is read. Read it here, inside the guard, rather than letting it
        # surface as a traceback from inside uvicorn.
        _ = config.allowed_hosts
        # The certificate pair, loaded once, before the banner and the bind:
        # a pair that cannot be loaded is a refusal like any other (#267).
        tls = build_tls_context(config)
    except ConfigError as exc:
        print(f"hitchrail: {exc}", file=sys.stderr)
        # #141. clig.dev: a program that needs arguments to function, run with
        # none, should show concise help rather than a single refusal line.
        # Scoped to the one case that IS a bare invocation, `roots.check_roots`'s
        # own message, rather than every ConfigError: a typo in an existing
        # config should not be buried under a full option dump.
        if "no roots configured" in str(exc):
            print(file=sys.stderr)
            build_parser(mention_update_plugins=False).print_help(sys.stderr)
        return 2

    # BEFORE the banner and before the bind. Printing a token and a set of
    # links, then refusing to work, would be worse than refusing plainly.
    found = preflight(config)
    if found.problems:
        print("hitchrail: cannot start.", file=sys.stderr)
        for problem in found.problems:
            print(f"  - {problem}", file=sys.stderr)
        return 2
    # #196. Threaded through rather than re-read: `spawn_agent_binary` is now
    # the absolute path this exact preflight resolved, so the engine and the
    # plugin update run the file that was just checked, not a bare name that
    # tmux's own server, with its own inherited PATH, could resolve to
    # something else.
    config = replace(config, resolved_agent_binary=found.agent_binary)
    # #207. After the preflight, before the bind, and with two exit codes
    # because the unit reads them differently. A MISMATCH is exit 2, the
    # deliberate stop `RestartPreventExitStatus=2` keeps stopped until a
    # person looks: this machine is on the wrong network. "Cannot tell", no
    # default route yet or no ARP entry, is exit 3, the transient the unit
    # retries within its budget: a boot where the DHCP lease lands after
    # the first start is the measured case, and refusing it forever would
    # leave the service dead on the right network (Phase 14 review, round
    # 1). Both serve nothing: "cannot tell" is still a refusal, retried.
    verdict = gateway_verdict(config)
    if verdict is not None:
        code, message = verdict
        print(f"hitchrail: cannot start. {message}", file=sys.stderr)
        return code

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

    log = logging.getLogger(__name__)
    for line in startup_block(config, found, args.log_level):
        log.info("%s", line)

    engine = Engine(config=config)
    # After the block rather than inside it: they are what the engine's own
    # read of the state file found, and that read happens here (#421).
    for line in engine.prefs.startup_warnings():
        log.warning("%s", line)
    # One bus, built here and owned here, because the CLI owns the process.
    app = create_app(engine=engine, config=config, bus=EventBus())
    return _serve(app, config, tls)
