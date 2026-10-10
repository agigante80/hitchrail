"""Reading an agy pane: is the box clear, is a turn running, is a message queued.

Part of the `agy_ipc` quarantine (#294). Captured on agy 1.3.3 with escapes,
2026-10-10; the rows are quoted on #294.

The live input box is a `>` row with a rule of `─` directly above it and
directly below. That pair is what tells it from the two other `>` rows a pane
holds: the echo of a sent message in the history (a rule above, text below)
and the slash menu's entries (drawn under the box's lower rule). A background
task draws its panel BETWEEN the box's lower rule and a second rule, so the
footer is not the row under the box: it is the last row with text.
"""

from __future__ import annotations

import re

_PROMPT = ">"
_RULE = "─"
_QUEUED_MARK = "▸"
_SGR = re.compile(r"\x1b\[[0-9;:]*m")

# The footer's words, one per state. `esc to cancel` is shown while a turn runs
# AND while the slash menu is open, so it means "not idle", never "busy" alone.
# A draft in the box blanks the footer.
_IDLE = "? for shortcuts"
_NOT_IDLE = "esc to cancel"
_QUEUED = "Press up to edit queued messages"

# As in `claude_ipc`: an unbroken run of idle readings this long, the first of
# them this long after the prompt went, before a wrap up counts as done. A turn
# that has not started yet reads exactly like one that has ended.
_SETTLE_DONE_S = 2.0


def _plain(row: str) -> str:
    return _SGR.sub("", row)


def _is_rule(row: str) -> bool:
    text = _plain(row).strip()
    return text != "" and set(text) == {_RULE}


def _box(rows: list[str]) -> int | None:
    """The index of the live input row, or None."""
    for i in range(len(rows) - 2, 0, -1):
        if (
            _plain(rows[i]).startswith(_PROMPT)
            and _is_rule(rows[i - 1])
            and _is_rule(rows[i + 1])
        ):
            return i
    return None


def _footer(rows: list[str], box: int) -> str:
    return next((_plain(r) for r in reversed(rows[box + 2 :]) if _plain(r).strip()), "")


def input_is_clear(pane: str) -> bool | None:
    """True when the live box holds nothing, False when it holds text, None
    when no live box can be found: a modal, a trust prompt, an empty pane."""
    rows = pane.splitlines()
    box = _box(rows)
    if box is None:
        return None
    return _plain(rows[box])[len(_PROMPT) :].strip() == ""


def queued_message(pane: str) -> bool:
    """Whether a message waits to run after the current turn: the footer says
    so, or a `▸` row sits directly above the box's upper rule."""
    rows = pane.splitlines()
    box = _box(rows)
    if box is None:
        return False
    above = _plain(rows[box - 2]).lstrip() if box >= 2 else ""
    return _QUEUED in _footer(rows, box) or above.startswith(_QUEUED_MARK)


def wrap_up_reading(pane: str) -> bool | None:
    """One look at whether agy is idle at an empty box (#242).

    True: the footer reads idle and the box is empty. False: a turn runs, a
    message is queued, or text is in the box. None: no live box, or a footer
    nobody has captured, which is not evidence either way.
    """
    rows = pane.splitlines()
    box = _box(rows)
    if box is None:
        return None
    footer = _footer(rows, box)
    if _NOT_IDLE in footer or queued_message(pane) or input_is_clear(pane) is False:
        return False
    return True if _IDLE in footer else None


class WrapUpWatch:
    """Whether a wrap up prompt has finished, from readings over time (#242).

    The same rule as `claude_ipc`'s, kept apart because the quarantine is per
    package: an unbroken run of idle readings spanning `_SETTLE_DONE_S`, the
    first at least that long after the prompt was sent. A busy or unreadable
    reading breaks the run.
    """

    def __init__(self, sent_at: float) -> None:
        self.sent_at = sent_at
        self._idle_since: float | None = None
        self._idle = self._busy = self._unreadable = 0

    def readings(self) -> str:
        return f"readings: {self._idle} idle, {self._busy} busy, {self._unreadable} unreadable"

    def observe(self, now: float, pane: str) -> bool:
        if now - self.sent_at < _SETTLE_DONE_S:
            return False
        reading = wrap_up_reading(pane)
        if reading is None:
            self._unreadable += 1
        elif reading:
            self._idle += 1
        else:
            self._busy += 1
        if reading is not True:
            self._idle_since = None
            return False
        if self._idle_since is None:
            self._idle_since = now
            return False
        return now - self._idle_since >= _SETTLE_DONE_S
