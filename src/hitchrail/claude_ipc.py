"""Everything that knows Claude Code internals, and the only place that may.

Every constant and every parsing rule below depends on UNDOCUMENTED Claude Code
behaviour that will change without notice. That is the whole reason this module
exists: when it breaks, exactly one file changes and the interface degrades to
`pending` rather than reporting something false.

Written against Claude Code as of 2026-08. If a session link stops resolving or
an agent stops being found in the process table, look here first and expect the
cause to be upstream rather than a bug in Hitchrail.

This module is also the vendor seam. Multi agent is an explicit v1 non goal
(design section 3.1); what is kept open is the seam, not an abstraction.
Nothing outside this module may name a Claude Code behaviour, file or key
sequence, and "name" includes iterating one: `lint-imports` cannot see a string
literal, so the quarantine has grep tests instead.

This module is in the engine layer and imports nothing from the web layer.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

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

logger = logging.getLogger(__name__)

# What to type at a running agent to ask it to finish, as a sequence of key
# GROUPS. Each group is one send_keys call, because tmux distinguishes a key
# from literal text by argument position.
#
# **This was `C-c`, `C-c`, `/exit` and that was wrong twice** (#89). Measured
# against a real session: `C-c C-c` alone exits an idle agent in about one
# second, so the `/exit` group never ran and the sequence was a double
# interrupt quit rather than the request the interface described. Stopped mid
# task, a forty second job lost thirteen seconds of work.
#
# `C-u` is FIRST, and it is the step that matters most. `Escape` interrupts a
# turn but does NOT clear an unsent draft (tested live, sentinel typed, draft
# still there), so an `/exit` sent after it appends to whatever the person had
# half typed, and the `Enter` submits the pair. `send-keys` writes to the pty
# and nothing marks those characters as ours, so that submission carries the
# operator's authority (#91). `C-u` removes the hazard and is safe whatever
# state the pane is in, which is why it cannot be second.
#
# Verification runs BETWEEN these groups; see `request_stop`. The constant is
# still the sequence, and nothing outside this module may iterate it.
GRACEFUL_STOP_KEYS: tuple[tuple[str, ...], ...] = (
    ("C-u",),
    ("Escape",),
    ("/exit", "Enter"),
)

# The prompt ornament, captured from a real session rather than described.
# Written as an escape rather than pasted: U+276F is confusable with a plain
# `>` in every editor.
#
# **The ornament ALONE, deliberately.** The input box renders it followed by a
# non breaking space, and the first version of this anchor included that NBSP.
# The trust modal (#88) renders the same ornament with a colour reset and an
# ORDINARY space after it, so the longer anchor matched nothing on a modal, the
# row came back unjudged, and the sequence would have typed into a prompt whose
# entries are actionable. That is the case this check most needs to catch, so
# the anchor is the part both rows share.
_PROMPT = "\u276f"

# Dim. Claude Code renders its own suggested prompt with this and a person's
# draft without it, which is the only thing that tells the two apart.
_DIM = "\x1b[2m"

# CSI and OSC sequences, for deciding whether what is left is only padding.
#
# **Narrower than it looks like it should be, on purpose.** Round 2 of #89's
# review widened this to strip any two character escape as well, because an
# `ESC ( B` charset designator surviving into an otherwise empty box makes the
# box read as dirty and refuses every graceful stop on that terminal.
#
# That widening introduced something worse than the problem. `\x1b[@-Z\\-_]`
# followed by an optional trailing character ate one PRINTABLE character after
# a two character escape, so a one character draft read as an empty box and the
# exit command would have been appended to it and submitted with the
# operator's authority: the guard producing the exact failure it exists to
# prevent (#91).
#
# Round 3 found that, which put two consecutive review rounds on defects inside
# the previous round's fix. The project's own rule is to stop there rather than
# patch again, so this went BACK to the narrower pattern instead of being
# adjusted a third time. The `ESC ( B` case is still open, as #97, and it fails
# CLOSED: such a terminal refuses stops rather than mistyping into them, which
# is the direction to be wrong in.
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")

# A keystroke reaches the pty at once and the agent repaints when it gets
# round to it, and nothing tells us when that was. So the box is read after a
# pause, and re-read after another if it does not look clear yet.
#
# An earlier version of this comment said the read came FIRST and that a pane
# which had already repainted therefore cost nothing. That stopped being true
# when the settle moved ahead of the first read: a stale read after `Escape`
# returned True immediately and made the second checkpoint vacuous. One settle
# on the happy path is what that checkpoint costs, and it is worth it.
_SETTLE_S = 0.15
_SETTLE_TRIES = 4

# Ends every refusal. The person can see the pane and we cannot, so the useful
# instruction is always the same one.
_LOOK_YOURSELF = "Open the session in a terminal to see what it is waiting on."

# What every refusal claims, and the precision is the point. Keys have already
# gone out by the time any check runs: the box was cleared, and at the second
# checkpoint a turn was interrupted. "Nothing was sent" was the first wording
# and it was false, which is the exact untruth #89 exists to remove.
_NOT_SENT = "it was never asked to exit"


class StopNotSafe(RuntimeError):
    """The graceful stop was abandoned before anything was typed.

    Raised rather than returned, because every caller's correct response is the
    same: do not continue, and tell the person. A boolean return invites a
    caller to carry on with a warning, and carrying on here means submitting
    text into somebody else's session.
    """


def input_is_clear(pane: str) -> bool | None:
    """Whether the agent's input box holds nothing the operator typed.

    `None` means the question could not be answered, and it is deliberately not
    `False`: a capture that failed, a pane still painting, or a layout we have
    not seen is not evidence of a draft, and reporting one would refuse a stop
    on no evidence. What the caller does with `None` depends on whether it saw
    a pane at all, and `_require_clear` is where that is decided; this function
    only reports what it can and cannot see.

    The three states, captured from a real session on 2026-09-02:

        clear        '\x1b[39m\u276f\xa0                     '
        placeholder  '\x1b[39m\u276f\xa0\x1b[2mTry "how does <filepath> work?"'
        draft        '\x1b[39m\u276f\xa0draft text here          '

    **The placeholder is transient**, which is the part every description of
    this row has missed. It appeared about nine seconds after start and was
    gone on the next sample, and a box cleared with `C-u` comes back with no
    placeholder at all. A check written as "the dim placeholder came back"
    therefore fails on the ordinary resting state of an idle session, which is
    most stops, and it fails closed so it would have looked like the mechanism
    working.

    The last matching row is the input box, because that box is at the bottom
    of the screen and agent output above it may say anything.

    #88's trust modal renders its selected entry with the same ornament and
    bright colour, so it reads as not clear and the stop is refused. That is
    the right answer arrived at without a list of modal wordings to maintain,
    and there is a test for it built from the captured row rather than from a
    description of it, which is what caught the anchor being too long.
    """
    row = next((line for line in reversed(pane.splitlines()) if _PROMPT in line), None)
    if row is None:
        return None
    after = row.split(_PROMPT, 1)[1]
    if after.lstrip().startswith(_DIM):
        return True
    return _ANSI.sub("", after).strip() == ""


class Pane(Protocol):
    """The narrow surface `request_stop` needs from whatever hosts the session.

    Declared HERE, next to its consumer, and deliberately NOT `Tmux`. Naming
    the concrete class would contradict the phase's rule that no adapter
    imports another, contradict this module's "consumes nothing", and defeat
    the point: it puts "the stop channel is tmux" back into the function
    written to remove channel assumptions. An adapter that wanted to send a
    signal would need the process table; one that wanted an HTTP call would
    need neither.

    `Tmux` satisfies this structurally, without either module importing the
    other, and mypy checks it.
    """

    def send_keys(self, project: str, *keys: str) -> None: ...  # pragma: no cover

    def capture_pane(  # pragma: no cover
        self, project: str, lines: int = 40, escapes: bool = False
    ) -> str: ...


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
    """Absolute paths Claude Code will not show a trust prompt for, or `None`.

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
    except (OSError, ValueError):
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


def launch_argv(binary: str, project: str) -> list[str]:
    """The argv that starts an agent. A LIST, never a string.

    The no shell rule has to survive the handoff to whatever runs this, so the
    type is the guarantee rather than a convention.

    `--dangerously-skip-permissions` is what makes unattended operation
    possible and is also the whole of this project's threat model. It belongs
    in this module and nowhere else.
    """
    return [binary, "--dangerously-skip-permissions", REMOTE_CONTROL_MARKER, project]


def request_stop(pane: Pane, project: str, settle: Callable[[], None] | None = None) -> None:
    """Ask the agent to exit, verifying between steps. Raises `StopNotSafe`.

    The engine calls this and learns nothing more. Iterating GRACEFUL_STOP_KEYS
    at the call site instead would teach the engine three Claude Code facts:
    that stopping is keystrokes, that it is a sequence of them, and that they
    travel through a pane. None of those is true of an agent that wants a
    signal, a subcommand or an HTTP call. It would now also have to know what a
    cleared input box looks like, which is the most volatile fact here.

    **Request by keystroke, confirm by observation** (#89). There is no reply
    channel: nothing the agent sends back could be distinguished from output it
    was already printing, so every check is a look at the pane.

    The box is verified TWICE, and both times before the exit command is typed.

    **The first checkpoint cannot catch an ordinary draft**, and saying that it
    does was wrong: `C-u` runs before it and erases one. What it catches is a
    box `C-u` did NOT clear, which is the interesting case rather than a lesser
    one. A modal is exactly that: the trust prompt at #88 keeps its bright
    selected row whatever is typed at it, so it arrives here still dirty.

    So `C-u` destroys an unsent draft as a matter of course. That is the trade
    the sequence makes on purpose, because the alternative is appending an exit
    command to that draft and submitting the pair with the operator's authority
    (#91), and a draft in a session somebody is stopping is being discarded
    either way. Every refusal below says the EXIT COMMAND was not sent rather
    than that nothing was, because keys have already gone out by then and
    saying otherwise is the untruth #89 exists to remove, one layer down.

    The second checkpoint guards whatever `Escape` did.

    **The second check is not "did the pane change".** That was the agreed
    sequence on #89 and it cannot work: an idle agent has nothing to interrupt,
    so `Escape` changes nothing, and the most ordinary stop there is would be
    refused. Asking the same question twice catches a pane that `Escape` put
    somewhere unexpected without punishing a session that was merely idle. The
    modal case that check was reaching for is already refused by the first one,
    because a modal's selected row is bright text on this same prompt.

    GRACEFUL_STOP_KEYS stays public because the test asserting the exact
    sequence needs it. The rule is that nothing outside this module ITERATES
    it, and there is a grep test for that, because no import contract can see
    a `for` loop.
    """
    wait = settle or (lambda: time.sleep(_SETTLE_S))
    # Unpacked rather than iterated, deliberately. Verification happens between
    # the groups, so a fourth one is not something this function could absorb
    # by looping: it needs a decision about where its checkpoint goes. The
    # unpack raises at the one place that has to change, which is the point.
    clear, interrupt, quit_keys = GRACEFUL_STOP_KEYS

    pane.send_keys(project, *clear)
    _require_clear(pane, project, wait, f"the input box in {project} did not come back empty")
    pane.send_keys(project, *interrupt)
    _require_clear(
        pane, project, wait, f"the input box in {project} filled after the interrupt"
    )
    pane.send_keys(project, *quit_keys)


def _require_clear(pane: Pane, project: str, wait: Callable[[], None], complaint: str) -> None:
    """Look at the box, and refuse unless it is certainly clear.

    `escapes=True` is load bearing: without it the placeholder and a draft are
    the same characters and the distinction this function exists to make cannot
    be made.

    `complaint` names the project itself rather than taking it as a suffix, so
    each refusal reads as a sentence about a session instead of a fragment with
    a name appended.
    """
    saw_a_box = False
    saw_a_pane = False
    for _ in range(_SETTLE_TRIES):
        # BEFORE the first read, not only between retries. The keys were sent
        # a moment ago and the agent has not necessarily repainted, so attempt
        # zero can judge the frame from before them.
        #
        # That is harmless at the first checkpoint and vacuous at the second.
        # A stale read after `C-u` still shows the draft, so the box reads
        # dirty and we retry: it fails safe. A stale read after `Escape` shows
        # the box that was clear a moment ago, so it returns True at once and
        # the check never sees what `Escape` did: it fails OPEN, and the guard
        # is worth nothing. Waiting first costs one settle on the happy path
        # and is what makes the second checkpoint mean anything.
        wait()
        text = pane.capture_pane(project, escapes=True)
        verdict = input_is_clear(text)
        if verdict is True:
            return
        # STICKY, both of them. An earlier version kept only the last attempt's
        # verdict while "did we see a pane" accumulated, so a box read as dirty
        # three times and unreadable on the fourth fell through to the "layout
        # we do not know" branch below and was typed into. Evidence of a box
        # does not expire because a later read failed.
        saw_a_box = saw_a_box or verdict is False
        saw_a_pane = saw_a_pane or bool(text.strip())

    if saw_a_box:
        raise StopNotSafe(f"{complaint}, so {_NOT_SENT}. {_LOOK_YOURSELF}")

    # **This branch used to PROCEED, and that was wrong.** The argument for it
    # was graceful degradation: a pane with output and no input row is a vendor
    # we have not seen or this one after a redesign, and the hazard being
    # guarded is text the OPERATOR left in a box we are about to append to, so
    # no box meant no such text.
    #
    # The hole is #88. A modal that does not draw the prompt ornament lands
    # here, and what gets typed is not only an exit command: it is that command
    # followed by ENTER, which accepts whatever entry a dialog has highlighted.
    # On the trust prompt the highlighted entry is the one that grants a folder
    # full permissions. The trade was argued against the ONE modal that had
    # been captured, and #88 is about any of them.
    #
    # So an unrecognised pane refuses. The cost is real and is the smaller one:
    # a redesign of that row turns the graceful stop into an honest refusal
    # that names itself, with Kill still on the row, rather than into a stop
    # that silently answers dialogs.
    if saw_a_pane:
        raise StopNotSafe(
            f"the input box in {project} could not be found, so {_NOT_SENT}. "
            "Something is on screen that this version does not recognise. "
            f"{_LOOK_YOURSELF}"
        )

    # Nothing readable at all, on any attempt, and it gets its OWN words. An
    # empty capture is not an empty box.
    #
    # It does NOT say why. An earlier version asserted the pane was gone
    # because the agent had outlived its terminal, which is one cause among
    # several: `capture_pane` returns "" for ANY non zero tmux exit, so a live
    # session whose capture failed once was told something false about itself
    # and lost the one instruction it could act on.
    #
    # The engine refuses the states that have no pane before calling this
    # (#98), and that is not the same as them being impossible here: the state
    # was derived a moment earlier, so an agent that exits in between arrives
    # with no pane after all. One more reason for this branch to describe what
    # it saw rather than to name a cause.
    raise StopNotSafe(
        f"the pane for {project} could not be read, so {_NOT_SENT}. {_LOOK_YOURSELF}"
    )


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
    except (OSError, ValueError):
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
