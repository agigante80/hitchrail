"""Starting an agent and finding its session link: the launch argv, folder trust, the bridge id.

Part of the `claude_ipc` quarantine (#368). `launch_argv` holds the literal
permission skipping argv, which is why this module is on the security rules' list.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)


# How the agent is found in the process table. State derivation matches this as
# a substring of a command line, so it has to be something no other process on
# the machine carries by accident.
#
# The project name we pass after it is a TAG, not a name Claude Code uses.
# Checked against a live session on 2026-08-28, with both `--remote-control X`
# and `--remote-control=X`: the session file came back `nameSource: derived`
# and a name built from the working directory in each case, so the argument is
# ignored. That costs us nothing, because what the derivation needs is a unique
# argv tail per project and this gives it one, but somebody will eventually
# read this flag as naming the session and it does not.
REMOTE_CONTROL_MARKER = "--remote-control"

# Where a session link points. The bridge id is appended verbatim.
URL_BASE = "https://claude.ai/code/"

# What a bridge id is allowed to look like. An ALLOWLIST of shape, not a
# denylist of bad strings: the value comes from a file another process wrote
# and ends up in a link the interface renders, so anything not obviously a
# single path segment is refused rather than sanitised into one.
_BRIDGE_ID = re.compile(r"\A[A-Za-z0-9._~-]{1,128}\Z")


# Where Claude Code records which folders it has been trusted with, and the one
# key we read out of it.
#
# Confirmed against a real file on 2026-09-02: `projects` is a map keyed by
# ABSOLUTE PATH, and each entry carries `hasTrustDialogAccepted`. That machine
# had 69 entries, 50 of them accepted, which is why every real project started
# cleanly and why #88 was invisible until Hitchrail met a fresh root.
_PROJECTS_KEY = "projects"
_TRUST_KEY = "hasTrustDialogAccepted"


# The last file we parsed, keyed by what would make it different. That file is
# 248KB on the development machine and `look()` runs on every listing AND on
# every tick of the start poll, which is roughly 32 reads in the eight seconds
# after a start, none of which consults the answer. Cached on (mtime, size)
# rather than on a timer: it changes when the operator accepts a folder, which
# is exactly when we want to notice, and a stat is cheap where a parse is not.
_trust_cache: tuple[tuple[str, int, int], frozenset[str] | None] | None = None


def trusted_folders(config_path: Path) -> frozenset[str] | None:
    """Absolute paths whose entry says trusted, or `None`. A folder under one
    is trusted too: ask `folder_is_trusted`, never this set directly (#456).

    `None` means we could not tell, and it is deliberately not an empty set.
    Empty would say every folder is untrusted, which would put a warning on
    every running row at once the first time this file changes shape. Unknown
    says nothing, which is what the quarantine promises when Claude Code moves.

    **Only the trust flag is read.** That file holds a great deal more, 248KB
    of it on the development machine: MCP server definitions, per project token
    counts and costs, session ids, an account email. Returning a set of paths
    rather than the parsed document is what keeps any of it from reaching a
    row, a log or an event.

    A file rather than a pane, and that is the point (#88). Reading the screen
    would cost a `capture-pane` per running row on every listing, which is the
    cost the design refused for the session link. This is one file read per
    look, and it answers the question exactly rather than by recognising a
    wording that is Claude Code's to change.

    Present and false is not the same as absent, and both mean the prompt will
    appear, so only an explicit true counts.
    """
    global _trust_cache
    try:
        stat = config_path.stat()
    except OSError:
        return None
    key = (str(config_path), stat.st_mtime_ns, stat.st_size)
    if _trust_cache is not None and _trust_cache[0] == key:
        return _trust_cache[1]
    try:
        raw = json.loads(config_path.read_text())
    except (OSError, ValueError, RecursionError):
        # RecursionError: nesting past the parser's stack is as unreadable as
        # malformed JSON, and is not a ValueError (#356).
        _trust_cache = (key, None)
        return None
    answer = _read_trust(raw)
    _trust_cache = (key, answer)
    return answer


def _read_trust(raw: object) -> frozenset[str] | None:
    """The parsing, separated so the caching above has one place to store."""
    if not isinstance(raw, dict):
        return None
    projects = raw.get(_PROJECTS_KEY)
    if not isinstance(projects, dict):
        return None
    entries = {p: e for p, e in projects.items() if isinstance(e, dict)}
    if projects and not entries:
        # A POPULATED map in which nothing is a recognisable entry is a shape
        # change, not a machine with odd projects, and the answer to a shape
        # change is that we do not know. One strange entry among many is the
        # other case and is simply skipped: an empty set there would be a claim.
        #
        # An EMPTY map is neither, and it deliberately answers "nothing is
        # trusted" rather than "cannot tell". A fresh install really has
        # accepted no folders, so every row warning is the truth about it.
        return None
    return frozenset(p for p, e in entries.items() if e.get(_TRUST_KEY) is True)


def folder_is_trusted(folder: Path, trusted: frozenset[str]) -> bool:
    """Whether Claude Code starts in `folder` without its trust prompt.

    **An ancestor's trust is inherited** (#456). Observed on Claude Code
    2.1.296, 2026-10-10, on a private tmux server: a fresh folder under `/tmp`,
    whose entry is true, started with no prompt, and so did one whose own
    entry read false; a fresh folder under `~/.cache`, with no trusted
    ancestor, showed the prompt. `--dangerously-skip-permissions` changed
    neither, so the flag is not what skips it.

    Exact match only was the first rule, and it put a permanent false warning
    on every row under a root somebody trusted once as a whole. `folder` must
    be the resolved path the agent was started in, which is the form the
    map's keys take.
    """
    return any(str(p) in trusted for p in (folder, *folder.parents))


def launch_argv(binary: str, project: str) -> list[str]:
    """The argv that starts an agent. A LIST, never a string.

    The no shell rule has to survive the handoff to whatever runs this, so the
    type is the guarantee rather than a convention.

    `--dangerously-skip-permissions` is what makes unattended operation
    possible and is also the whole of this project's threat model. It belongs
    in this module and nowhere else.
    """
    return [binary, "--dangerously-skip-permissions", REMOTE_CONTROL_MARKER, project]


@dataclass(frozen=True)
class SessionUrl:
    """A session link and WHERE IT CAME FROM.

    The source is carried rather than a confidence score. We know exactly why a
    scraped URL is uncertain, so naming the mechanism lets the interface say
    "found in the terminal output, may be from an earlier session" instead of
    "low confidence", which tells the user nothing they can act on.
    """

    url: str
    source: Literal["bridge", "scraped"]


def _valid_bridge_id(value: object) -> str | None:
    """A bridge id, or None. Every refusal here is deliberate.

    The file is written by another process and its contents are guaranteed to
    be nothing in particular, while the value ends up in a link somebody taps.
    A separator would let it climb out of the path segment it belongs in; a
    scheme would point it at another host entirely, which is an open redirect
    rendered by our own interface.

    The pattern refuses both without enumerating them, along with control
    characters, empty strings and anything absurdly long.
    """
    # No bool guard here on purpose: bool subclasses int, not str, so `True`
    # is already refused by the str check. Adding one reads as defensive and
    # is unreachable, which mypy says out loud.
    if not isinstance(value, str):
        return None
    return value if _BRIDGE_ID.match(value) else None


def bridge_url(pid: int, sessions_dir: Path) -> str | None:
    """The session link from `<sessions_dir>/<pid>.json`, or None.

    `bridgeSessionId` is an undocumented internal, it is not written for every
    session, and it may be caught mid write. Every one of those is None rather
    than an exception, because the interface shows `pending` for None and a
    missing link is honest while a wrong one is not.

    `pid` is an `int`, so the filename cannot traverse. Keep it that way:
    accepting a `str` for convenience reintroduces that through the filename.
    """
    path = sessions_dir / f"{pid}.json"
    try:
        payload = json.loads(path.read_text())
    except (OSError, ValueError, RecursionError):  # #356, as above
        return None
    if not isinstance(payload, dict):
        return None
    bridge_id = _valid_bridge_id(payload.get("bridgeSessionId"))
    if bridge_id is None:
        return None
    # Verbatim, including the session_ prefix. The value IS the path segment.
    return f"{URL_BASE}{bridge_id}"


def _scrape(pane_text: str) -> str | None:
    """A claude.ai/code URL from terminal output, validated the same way.

    Pane text is attacker influenceable: anybody who can write to the pane can
    put a URL in the scrollback, so the segment gets the same allowlist the
    JSON value does.
    """
    match = re.search(rf"{re.escape(URL_BASE)}(\S+)", pane_text)
    if match is None:
        return None
    bridge_id = _valid_bridge_id(match.group(1))
    return None if bridge_id is None else f"{URL_BASE}{bridge_id}"


def session_url(
    pid: int, sessions_dir: Path, pane_text: str | None = None
) -> SessionUrl | None:
    """The best link available, saying which it is, or None for `pending`.

    **The bridge value always wins**, following the ordinary treatment of an
    observed fact against a self reported one: the authoritative source
    decides, and the disagreement is itself a signal.

    The scrape exists because the JSON is not written for every session, and it
    cannot be trusted because three things produce a match and only one is
    right. The nastiest is scrollback from a PREVIOUS session in the same pane:
    a perfectly well formed URL pointing at a session that ended hours ago.
    Nothing about the string looks wrong, so no amount of parsing separates it
    from a good one and the only honest response is to say where it came from.
    """
    from_bridge = bridge_url(pid, sessions_dir)
    from_pane = _scrape(pane_text) if pane_text else None

    if from_bridge is not None:
        if from_pane is not None and from_pane != from_bridge:
            # Good evidence the pane is showing stale scrollback, and exactly
            # the diagnostic somebody wants when a link misbehaves.
            logger.debug(
                "session %s: pane URL %s differs from the bridge URL %s, "
                "the pane is probably showing an earlier session",
                pid,
                from_pane,
                from_bridge,
            )
        return SessionUrl(from_bridge, "bridge")

    return SessionUrl(from_pane, "scraped") if from_pane is not None else None
