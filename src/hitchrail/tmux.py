"""A thin tmux adapter, carrying the target addressing footguns.

Everything here exists because a tmux target spec does not mean what it looks
like. Each behaviour below was verified against a real tmux 3.4 on a private
socket rather than recalled, and #27 keeps that honest with a live tier: the
tests in this layer prove the adapter builds the target it believes in, which
is a different and weaker claim than the target doing what we believe.

This module is in the engine layer and imports nothing from the web layer;
`lint-imports` enforces it.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable

# What a subprocess call looks like from here. Injected so the whole engine can
# be tested without a machine, which is the single seam the architecture rests
# on. `procs` consumes this alias too.
Runner = Callable[[list[str]], "subprocess.CompletedProcess[str]"]

# tmux reads both of these as target separators, so neither may appear in a
# session name. `-` is the escape character, which is why it is escaped too.
_SEPARATORS = (".", ":")

# Marks a name that went through the encoding below. A name that would
# otherwise start with it is encoded as well, which is what keeps the encoded
# and unencoded forms disjoint and therefore the whole mapping injective.
_ENCODED_PREFIX = "e-"


class NotOurSession(ValueError):
    """Refusing to touch a session that does not carry the configured prefix."""


class TmuxUnavailable(OSError):
    """tmux could not be EXECUTED, so nothing about sessions can be known.

    Distinct from tmux running and reporting nothing, which is the ordinary
    state of a machine with nothing started. `procs.ProcTable.ok` draws the
    same line for the process table, and for the same reason: collapsing the
    two makes a live agent read as `detached`, which refuses to start and whose
    kill has no session to kill, so the project becomes unstartable.

    #28's preflight refuses to start at all when tmux is missing. This is what
    happens if it disappears while running.
    """


def sanitize(name: str) -> str:
    """Make a project name addressable as a tmux session, ONE TO ONE.

    tmux reads '.' and ':' as window and pane separators in a target spec.
    Verified on 3.4: a session created as `hr-dotted.site` is stored as
    `hr-dotted_site`, so it exists under a name nobody looked for and
    `has-session -t =hr-dotted.site` fails while the agent is running, which
    presents as the session having vanished. Emitting neither character
    sidesteps the rewrite rather than trying to predict it.

    Injectivity is the hard requirement here, not a nicety. If two project
    names collide onto one session name, one project reads as running because
    the other is, and stopping one kills the other's agent. That is the "two
    agents in one folder" outcome #11 fixed from the discovery side, reached
    from this one.

    **A digest suffix does not deliver it, which is why this is an escape
    encoding.** An earlier version returned `a-b-<6 hex of blake2b>` for `a.b`
    and returned already safe names unchanged. A project named literally
    `a-b-28b8f5` is already safe, so it came back unchanged and collided with
    `a.b`, and the colliding name is trivially computable by anyone who can
    create a folder. Widening the digest only raises the price: 6 hex is 24
    bits, so distinct names also birthday collide by accident somewhere around
    four thousand projects. Injective by construction beats injective by hash.

    The encoding is the usual escape and escape-the-escape:

        -  ->  --      .  ->  -d      :  ->  -c

    and the whole thing gets an `e-` prefix so encoded and unencoded names
    occupy disjoint spaces. A name that already starts with `e-` is encoded for
    the same reason. Names with neither separator are returned untouched, so
    the common case still reads plainly in `tmux ls`, and readability is the
    right thing to trade away here anyway: the project already keeps the
    display name apart from the tmux name.
    """
    if not _needs_encoding(name):
        return name
    body = name.replace("-", "--").replace(".", "-d").replace(":", "-c")
    return f"{_ENCODED_PREFIX}{body}"


def _needs_encoding(name: str) -> bool:
    """A name is encoded if it holds a separator, or could be mistaken for one
    that was. The second half is what keeps the two spaces disjoint."""
    return any(sep in name for sep in _SEPARATORS) or name.startswith(_ENCODED_PREFIX)


def _default_runner(argv: list[str]) -> subprocess.CompletedProcess[str]:
    """The real one. An argument list, never a shell, and never checked.

    `check=False` because a non zero return is normal here: `has-session` says
    no that way, and `list-panes` fails when no server is running at all. The
    callers below decide what each failure means.
    """
    # S603 is ignored for this module in pyproject.toml, not inline: every
    # call here is an argument list built by `_argv`, and there is no shell.
    return subprocess.run(argv, capture_output=True, text=True, check=False)


class Tmux:
    """One prefix, one optional socket, and every tmux call this project makes.

    The display name and the tmux name are deliberately different things. A
    caller passes the project name it got from `discovery`; everything sent to
    tmux goes through `sanitize` first, so nothing outside this class needs to
    know the two can differ.

    The runner is injected and defaults to the real one, which is the seam that
    lets the whole engine be tested without a machine.
    """

    def __init__(
        self,
        prefix: str,
        socket: str | None = None,
        run: Runner | None = None,
    ) -> None:
        if not prefix:
            # Refused here, not only in `Config`. Every guard in this class is
            # "does the name carry our prefix", and an empty prefix makes every
            # name on the server carry it, including the developer's own. The
            # module holding the dangerous operation enforces its own
            # precondition rather than trusting the caller came through Config.
            raise NotOurSession(
                "a tmux session prefix is required: without one, every session "
                "on the server looks like ours and the kill guard is vacuous"
            )
        self.prefix = prefix
        self.socket = socket
        self._run: Runner = run or _default_runner

    def _argv(self, *args: str) -> list[str]:
        """Every call goes through here, which is what keeps the socket on.

        A method that assembles its own argv and forgets `-S` talks to a
        different server than the rest of the class, which presents as a
        session that exists and does not.
        """
        base = ["tmux"]
        if self.socket:
            base += ["-S", self.socket]
        return [*base, *args]

    def session_name(self, project: str) -> str:
        """The name a session is CREATED with. Not a target: see below."""
        return f"{self.prefix}{sanitize(project)}"

    def session_target(self, project: str) -> str:
        """A session target, anchored.

        Without the '=', `has-session -t hr-vessel` prefix matches and resolves
        `hr-vessel-social`. Verified on tmux 3.4. A stopped project then reports
        a sibling's session as its own, which the interface renders as running.
        """
        return f"={self.session_name(project)}"

    def pane_target(self, project: str) -> str:
        """A pane target, anchored AND colon terminated. Both are required.

        `list-panes` takes a pane target, and on a bare `=hr-vessel` it ignores
        the anchor and falls back to prefix matching: verified on tmux 3.4, a
        session that does not exist returned its sibling's pane pid. The
        trailing ':' qualifies the string as a session target, after which the
        anchor is honoured and a missing session is correctly refused.

        The colon looks like a typo and is load bearing. There is a named
        regression test for it.
        """
        return f"={self.session_name(project)}:"

    # -- reading -------------------------------------------------------

    def _try(self, argv: list[str]) -> subprocess.CompletedProcess[str]:
        """Run, turning "could not be executed" into a distinct failure.

        `subprocess.run` raises before there is a returncode when tmux is
        absent or not executable. An earlier version of this method turned that
        into a non zero return, on the reasoning that every caller already
        treats non zero as "no".

        **That reasoning was wrong twice.** `new_session`, `kill_session` and
        `send_keys` discard the return entirely, so they do not treat it as
        anything. And for the read methods it collapses "we could not look"
        into "nothing is there", which made a live agent derive as `detached`
        when tmux went missing. That is the guard failing open that control 7
        forbids, and it is the same unstartable outcome `_find_detached` was
        just fixed for.

        So it raises instead, and the engine turns it into an honest refusal.
        A tmux that RUNS and says no still returns non zero, unchanged: that is
        an answer, not a failure.

        **This closes only the "could not execute" half.** A tmux that ran and
        FAILED still returns non zero, and the three write methods still
        discard it: a duplicate session name, or a `-c` directory that does not
        exist, is silently nothing. That is pre existing and belongs to the
        ticket that owns start failures, because reporting it needs somewhere
        for the output to go.
        """
        try:
            return self._run(argv)
        except OSError as exc:
            raise TmuxUnavailable(
                f"tmux could not be run ({exc}), so no session state can be "
                "determined; this is not the same as no sessions existing"
            ) from exc

    def has_session(self, project: str) -> bool:
        return (
            self._try(self._argv("has-session", "-t", self.session_target(project))).returncode
            == 0
        )

    def pane_pids(self) -> dict[str, int]:
        """Every session we own, mapped to its first pane's pid, in ONE call.

        The engine asks this once per list, not once per project. A call per
        project is a subprocess spawn per row, and at the row counts the design
        draws that is the difference between a page load and a stall. There is
        a test asserting the single call, because the cost of losing it is
        invisible until the folder is large.

        A non zero return means no server is running, which is the ordinary
        state of a machine with nothing started, not an error.
        """
        result = self._try(self._argv("list-panes", "-a", "-F", "#{session_name} #{pane_pid}"))
        if result.returncode != 0:
            return {}
        found: dict[str, int] = {}
        for line in result.stdout.splitlines():
            name, _, raw_pid = line.partition(" ")
            # Sessions we did not create are none of our business, and a
            # session already seen keeps its FIRST pane: a window split must
            # not change which pid a project reports.
            if not name.startswith(self.prefix) or name in found:
                continue
            try:
                found[name] = int(raw_pid)
            except ValueError:
                # One malformed line must not lose the well formed ones.
                continue
        return found

    def pane_pid(self, project: str) -> int | None:
        """One session's pane pid. For detail paths; `pane_pids` for lists."""
        result = self._try(
            self._argv("list-panes", "-t", self.pane_target(project), "-F", "#{pane_pid}")
        )
        if result.returncode != 0:
            return None
        fields = result.stdout.split()
        if not fields:
            return None
        try:
            return int(fields[0])
        except ValueError:
            return None

    def capture_pane(self, project: str, lines: int = 40) -> str:
        """The tail of a pane. Empty when it cannot be read, never an exception.

        `-J` joins wrapped lines, so a long line reads as one line rather than
        as the terminal's arbitrary column count. `-S -<lines>` bounds the
        history: without it this returns the whole scrollback.
        """
        result = self._try(
            self._argv(
                "capture-pane",
                "-p",
                "-J",
                "-S",
                f"-{lines}",
                "-t",
                self.pane_target(project),
            )
        )
        return result.stdout if result.returncode == 0 else ""

    # -- writing -------------------------------------------------------

    def new_session(self, project: str, cwd: str, argv: list[str]) -> None:
        """Detached, in the project's directory, running the given argv.

        Created with the plain session NAME. Only targets carry the `=` anchor;
        passing an anchored string to `-s` would create a session whose name
        begins with an equals sign.
        """
        self._try(
            self._argv("new-session", "-d", "-s", self.session_name(project), "-c", cwd, *argv)
        )

    def kill_session(self, project: str) -> None:
        """Scoped, always. No code path here reaches `kill-server`.

        **The scoping is enforced in `__init__`, not here**, and that is worth
        stating because the obvious guard in this method is a tautology. A
        version of this read:

            name = self.session_name(project)
            if not name.startswith(self.prefix):
                raise NotOurSession(project)

        `session_name` builds the name FROM `self.prefix`, so the condition can
        never be true. Mutating `.prefix` after construction does not reach it
        either, because both sides read the same attribute. It was removed
        rather than left as decoration: a guard that looks meaningful and
        cannot execute is worse than none, because a reader concludes this
        method is defended and stops looking.

        What actually protects the developer's tmux server is the empty prefix
        refusal in `__init__`, which fires, is tested, and is the case that
        would otherwise make every session on the server look like ours.
        """
        self._try(self._argv("kill-session", "-t", self.session_target(project)))

    def send_keys(self, project: str, *keys: str) -> None:
        """Each key is its own argument, deliberately.

        tmux distinguishes `C-c` the key from `C-c` the literal text by
        argument position, never by quoting, so joining them sends the
        characters instead of the keystroke.

        This method knows nothing about what it is sending. What to send in
        order to stop an agent is Claude Code's business and lives in
        `claude_ipc`; a `stop()` convenience here would put the agent's
        semantics in the tmux adapter, where a second agent could not replace
        them.
        """
        self._try(self._argv("send-keys", "-t", self.pane_target(project), *keys))
