r"""Reading the menu `/exit` raises while background work runs (#453).

Part of the `claude_ipc` quarantine; it reads a pane and types nothing. `keys.py`
asks it one question after the exit command and presses the one key itself.

Captured from a real session on 2026-10-08, Claude Code with a Monitor running,
the ornament written as its escape for the reason `screen._PROMPT` gives:

    Background work is running
    The following will stop when you exit:
    monitor \u00b7 <its description>
    \u276f 1. Exit and stop tasks
      2. Move to background and exit
      3. Stay
    Enter to confirm \u00b7 Esc to cancel

**This reverses a standing decision, deliberately.** #88 declined the power to
answer a dialog, #101 and #239 built on that (report the prompt, then kill), and
#165 is this very menu, left for a person. The argument was that the options
decide what happens to work the operator did not ask to end. For THIS menu that
is not true: the operator tapped Stop on the session that owns the work, and
"Exit and stop tasks" is what Stop means. The alternative cost every Stop on
such a session 30 seconds and a second tap on a key the row does not explain.
Every other dialog, the trust prompt above all, stays unanswered.

**Matched by text, never by position, and failing closed.** Only the SELECTED
row reading exactly "Exit and stop tasks", under the heading, counts. A reworded
option, a reordered menu with "Stay" or "Move to background and exit" selected,
or a vendor that draws something else reads as not this menu, and the stop goes
on exactly as before #453: nothing pressed, the row reported as waiting on a
person. "Move to background and exit" is never chosen: it makes the `detached`
agent the design exists to surface.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from hitchrail.claude_ipc.screen import _PROMPT, _live_ornament_row, _without_escapes

_HEADING = "Background work is running"
_EXIT_AND_STOP = "Exit and stop tasks"
_NUMBERING = re.compile(r"^\d+\.\s*")

# How long after `/exit` the menu may take to draw. NOT measured yet: the one
# real sighting saw it only at the 30 second expiry, so its draw time is unknown
# and the real session watch that closes #453 times it. 8 looks a settle apart
# is about 1.2 seconds; a slower draw is missed and falls back to the pre #453
# behaviour, never worse. The cost is that latency on every stop whose agent
# neither exits nor shows the menu, serially in the sweep's wrap up advance.
MENU_TRIES = 8


def offers_exit(pane: str) -> bool:
    """Whether the live UI is the exit menu with "Exit and stop tasks" selected.

    The selected row is `_live_ornament_row`, so a menu scrolled past (#208) is
    not live. An ordinary input box is excluded by the NBSP after the ornament,
    which only the box draws (`shows_input_box`). The heading must be above the
    row with no other ornament row between, so a heading printed by an earlier
    turn does not lend itself to a later dialog.

    An agent can print these rows itself (#181), and a spoof is bounded rather
    than harmless: it needs the input box NOT drawn, the exact heading and the
    exact row as the last ornament on screen, and any real dialog drawn with
    the ornament would itself be that last row and fail the text. A real dialog
    drawn WITHOUT one, under spoofed rows, is the narrow case left. What a spoof wins
    is one `Enter`, sent to an agent that has just been told to exit.
    """
    row = _live_ornament_row(pane)
    if row is None:
        return False
    after = row.split(_PROMPT, 1)[1]
    if after.startswith("\xa0"):
        return False
    if _NUMBERING.sub("", _without_escapes(after).strip()) != _EXIT_AND_STOP:
        return False
    rows = pane.splitlines()
    above = rows[: len(rows) - 1 - rows[::-1].index(row)]
    for line in reversed(above):
        if _PROMPT in line:
            return False
        if _without_escapes(line).strip() == _HEADING:
            return True
    return False


def exit_menu_appeared(look: Callable[[], str], wait: Callable[[], None]) -> bool:
    """Whether the exit menu came up after `/exit`, looking up to `MENU_TRIES` times.

    An empty look ends it early: the session went with the agent, which is the
    ordinary exit and needs nothing pressed.
    """
    for _ in range(MENU_TRIES):
        wait()
        text = look()
        if not text.strip():
            return False
        if offers_exit(text):
            return True
    return False
