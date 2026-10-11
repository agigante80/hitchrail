"""Typing into a Claude Code pane: the graceful stop and the answer keys.

Part of the `claude_ipc` quarantine (#368). The only module that may send keys to a
pane, and it verifies the screen between groups, because a keystroke carries the
operator's authority once it reaches the pty.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from hitchrail.agent import AnswerNotSafe, Pane, StopNotSafe
from hitchrail.claude_ipc.exit_menu import exit_menu_appeared
from hitchrail.claude_ipc.screen import awaits_answer, input_is_clear, queued_message

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


# The keys an operator may send in answer to a prompt (#204).
#
# **A literal set, asserted literally by a test.** Not a pattern, not a range,
# not "any single character". A pattern is exactly how this becomes the product
# the roadmap deferred, one commit at a time: `[0-9]` widens to `\w` widens to
# a text field, and every step of that reads like a small refactor. Widening
# this needs an edit here AND an edit to a test that spells the members out,
# which is the friction the security argument in #204 depends on.
#
# **There is no free text member, and adding one is the line.** #204 is only
# safe because the operator reads Claude Code's own words in the pane and
# presses the key those words name. A text field would let Hitchrail carry an
# instruction the pane never offered, which is a terminal, which is a different
# product.
#
# Arrows, Enter and Escape because a prompt is navigated as well as chosen. The
# digits because Claude Code numbers its options. Nothing else has a use that
# an operator reading the screen could justify.
ANSWER_KEYS: frozenset[str] = frozenset(
    {"Up", "Down", "Enter", "Escape", "1", "2", "3", "4", "5", "6", "7", "8", "9"}
)


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


def request_stop(pane: Pane, project: str, settle: Callable[[float], None]) -> None:
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

    **Relay, not impersonation** (#91). A person tapped Stop and this passes it
    on the way a keyboard would. The agent cannot tell the difference, so the
    framing holds only while what is relayed is what the person asked for.
    This module holds the only three functions that type into a pane, and a
    grep keeps it so: this one, `send_answer` (#204) and `request_wrap_up`
    (#242). The last types free text, which is the case this paragraph once
    called a different product; it stays a relay because the text is one
    fixed string the operator wrote on the machine, never one a request
    carries, and it is typed only as the first half of a Stop they confirmed.

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

    The second checkpoint guards whatever `Escape` did. After the exit, one
    `Enter` answers the background work menu, and nothing else (#453).

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

    # #95. The engine hands its own injected sleep in, and the DURATION stays
    # here. `_SETTLE_S` is a fact about how a Claude Code pane settles after a
    # keystroke, which is quarantine knowledge; how to wait is the machine seam
    # the architecture says is always injected. Splitting them that way keeps
    # both rules.
    #
    # **No default any more.** A default is what let the seam be bypassed for as
    # long as it was: the parameter existed, the unit tests passed a fake, and
    # the real path slept on a wall clock regardless. A caller that forgets now
    # fails to call rather than silently sleeping.
    def wait() -> None:
        settle(_SETTLE_S)

    # Unpacked rather than iterated, deliberately. Verification happens between
    # the groups, so a fourth one is not something this function could absorb
    # by looping: it needs a decision about where its checkpoint goes. The
    # unpack raises at the one place that has to change, which is the point.
    clear, interrupt, quit_keys = GRACEFUL_STOP_KEYS

    # #167. The keys by name, logged HERE because naming them anywhere else
    # is the quarantine breach, and every checkpoint by its verdict alone:
    # what the pane showed is never written to a log.
    pane.send_keys(project, *clear)
    logger.info("stop %s: sent %s to clear the input box", project, " ".join(clear))
    _require_clear(pane, project, wait, f"the input box in {project} did not come back empty")
    pane.send_keys(project, *interrupt)
    logger.info("stop %s: box clear, sent %s to interrupt", project, " ".join(interrupt))
    _require_clear(
        pane, project, wait, f"the input box in {project} filled after the interrupt"
    )
    pane.send_keys(project, *quit_keys)
    logger.info("stop %s: box still clear, sent %s", project, " ".join(quit_keys))
    # #453, reversing #88's line for this one menu; `exit_menu` says why. A
    # miss presses nothing, which is the behaviour before it.
    #
    # A tmux that fails during this wait is a miss, not a refusal (#454): the
    # exit already went out, so raising would report "exit refused" for an
    # exit that was sent. Nothing is pressed, as for any other screen.
    try:
        answer = exit_menu_appeared(lambda: pane.capture_pane(project, escapes=True), wait)
    except OSError:
        logger.warning("stop %s: could not look for the exit menu, pressed nothing", project)
        return
    if answer:
        # The same rule for the press: the exit is already out, so an OSError
        # here would turn a stop that was sent into an error (#479). The menu
        # stays up, and the expiry reports the row as waiting on a person.
        try:
            pane.send_keys(project, "Enter")
        except OSError:
            logger.warning("stop %s: exit menu seen, Enter not sent", project)
            return
        logger.info("stop %s: the exit asked about background work, sent Enter", project)


def request_wrap_up(
    pane: Pane, project: str, prompt: str, settle: Callable[[float], None]
) -> None:
    """Type the operator's wrap up prompt, WITHOUT interrupting (#242).

    Order B, decided on #242: "If it's close, queue, if it's kill interrupt."
    So there is no `Escape`. A busy agent queues the prompt behind its task,
    and a slash command waits for the turn to end (measured on 2.1.286).

    `C-u` first and the same clear check `request_stop` makes, so a modal or a
    box `C-u` did not clear refuses with `StopNotSafe` and the prompt is not
    typed. `C-u` spares a message the person QUEUED (measured), but this
    refuses when one shows anyway: theirs would run first, and two queued
    messages is a shape nobody has captured.

    The prompt goes through `send_text`, never `send_keys`: tmux reads each
    `send_keys` argument as a key name first, so a prompt of `C-c` would be a
    keystroke. `Enter` follows as a key, separately.
    """

    def wait() -> None:
        settle(_SETTLE_S)

    clear = GRACEFUL_STOP_KEYS[0]
    pane.send_keys(project, *clear)
    logger.info("stop %s: sent %s before the wrap up", project, " ".join(clear))
    _require_clear(pane, project, wait, f"the input box in {project} did not come back empty")
    if queued_message(pane.capture_pane(project, escapes=True)):
        raise StopNotSafe(
            f"{project} already has a message queued, which would run before the wrap up, "
            f"so {_NOT_SENT}. {_LOOK_YOURSELF}"
        )
    pane.send_text(project, prompt)
    pane.send_keys(project, "Enter")
    # Never the prompt itself: it is the operator's text, not the journal's.
    logger.info("stop %s: box clear, sent the wrap up prompt", project)


def send_answer(pane: Pane, project: str, key: str) -> None:
    """Send ONE key, having just re-read the screen that asked for it (#204).

    **The re-read is the security property and not a nicety.** The operator saw
    a capture taken at some earlier moment and pressed a button. Between those
    two events the agent may have answered its own prompt, timed out, or moved
    on to an ordinary input box. A stale screen plus a keystroke is a keystroke
    into whatever is there NOW.

    So the pane is read again here, immediately before the send, inside the
    same call. No caller can pre-authorise it and none may pass the earlier
    capture in: the parameter this function does not take is the point of it.

    The key is checked against `ANSWER_KEYS` FIRST, before the pane is read,
    so a request for a key this project will not send costs no subprocess and
    reveals nothing about the session.

    Sends exactly one key. `request_stop` sends groups because a stop is a
    sequence with checkpoints between; an answer is one keypress by a person
    who read the question, and a sequence here would be Hitchrail composing an
    instruction rather than carrying one.
    """
    if key not in ANSWER_KEYS:
        raise AnswerNotSafe(f"{key!r} is not a key Hitchrail will send")
    if awaits_answer(pane.capture_pane(project, escapes=True)) is not True:
        raise AnswerNotSafe(
            f"the pane in {project} is not showing a question, so {_NOT_SENT}. {_LOOK_YOURSELF}"
        )
    pane.send_keys(project, key)
    # After the send, so the line records a key that went out rather than
    # one that was about to. `key` is one of `ANSWER_KEYS`, checked above.
    logger.info("answer %s: the pane showed a question, sent %s", project, key)


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
        logger.debug("stop %s: looked at the input box, clear is %s", project, verdict)
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
