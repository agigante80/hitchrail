"""Typing into an agy pane: the graceful stop and the wrap up.

Part of the `agy_ipc` quarantine (#294). The only module in this package that
may send keys to a pane, and it verifies the box before the exit is typed, for
the reason `claude_ipc/keys.py` gives at length (#89, #91): a keystroke
carries the operator's authority once it reaches the pty.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from hitchrail.agent import AnswerNotSafe, Pane, StopNotSafe
from hitchrail.agy_ipc.screen import input_is_clear, queued_message

logger = logging.getLogger(__name__)

# Two groups, measured on agy 1.2.14 and 1.3.3: `C-u` clears a draft, then
# `/exit` and Enter quit. There is no `Escape` group as Claude Code has,
# because agy's `/exit` is not queued behind a turn: typed during one, it
# exits at once. So a Stop without a wrap up interrupts agy's turn, and a wrap
# up is unaffected, because the sweep sends the exit only once the turn ended.
STOP_KEYS: tuple[tuple[str, ...], ...] = (("C-u",), ("/exit", "Enter"))

# Empty, so every answer is refused. A question waiting on a person was not
# captured: permissions are skipped and none could be raised on demand. A key
# sent at a screen nobody has read is the one thing #204 refuses.
ANSWER_KEYS: frozenset[str] = frozenset()

_SETTLE_S = 0.15
_SETTLE_TRIES = 4
_LOOK_YOURSELF = "Open the session in a terminal to see what it is waiting on."
_NOT_SENT = "it was never asked to exit"


def request_stop(pane: Pane, project: str, settle: Callable[[float], None]) -> None:
    """Ask agy to exit, having checked the box is clear. Raises `StopNotSafe`."""
    clear, quit_keys = STOP_KEYS
    pane.send_keys(project, *clear)
    logger.info("stop %s: sent %s to clear the input box", project, " ".join(clear))
    _require_clear(pane, project, settle)
    pane.send_keys(project, *quit_keys)
    logger.info("stop %s: box clear, sent %s", project, " ".join(quit_keys))


def request_wrap_up(
    pane: Pane, project: str, prompt: str, settle: Callable[[float], None]
) -> None:
    """Type the operator's wrap up prompt without interrupting (#242).

    agy queues text typed during a turn (`▸`) and runs it when the turn ends,
    measured. A message the person already queued would run first, so that
    refuses, as for Claude Code. The prompt goes through `send_text`, never
    `send_keys`, which would read it as key names.
    """
    clear = STOP_KEYS[0]
    pane.send_keys(project, *clear)
    logger.info("stop %s: sent %s before the wrap up", project, " ".join(clear))
    _require_clear(pane, project, settle)
    if queued_message(pane.capture_pane(project, escapes=True)):
        raise StopNotSafe(
            f"{project} already has a message queued, which would run before the wrap up, "
            f"so {_NOT_SENT}. {_LOOK_YOURSELF}"
        )
    pane.send_text(project, prompt)
    pane.send_keys(project, "Enter")
    logger.info("stop %s: box clear, sent the wrap up prompt", project)


def send_answer(pane: Pane, project: str, key: str) -> None:
    """Always refused: see `ANSWER_KEYS`. The pane is never read."""
    raise AnswerNotSafe(f"{key!r} is not a key Hitchrail will send to this agent")


def _require_clear(pane: Pane, project: str, settle: Callable[[float], None]) -> None:
    """Refuse unless the box is certainly clear, after a settle each look.

    The same rule as `claude_ipc`'s: a box read dirty on any look refuses even
    if a later look is unreadable, and a pane with text but no box refuses,
    because that is a prompt or a modal and Enter would answer it.
    """
    saw_a_box = saw_a_pane = False
    for _ in range(_SETTLE_TRIES):
        settle(_SETTLE_S)
        text = pane.capture_pane(project, escapes=True)
        verdict = input_is_clear(text)
        if verdict is True:
            return
        saw_a_box = saw_a_box or verdict is False
        saw_a_pane = saw_a_pane or bool(text.strip())
    if saw_a_box:
        raise StopNotSafe(
            f"the input box in {project} did not come back empty, so {_NOT_SENT}. "
            f"{_LOOK_YOURSELF}"
        )
    if saw_a_pane:
        raise StopNotSafe(
            f"the input box in {project} could not be found, so {_NOT_SENT}. "
            f"Something is on screen that this version does not recognise. {_LOOK_YOURSELF}"
        )
    raise StopNotSafe(
        f"the pane for {project} could not be read, so {_NOT_SENT}. {_LOOK_YOURSELF}"
    )
