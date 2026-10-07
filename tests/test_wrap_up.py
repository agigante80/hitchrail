"""#242: the wrap up prompt Stop sends first, and how its end is read.

The rows below are task 169's capture (Claude Code 2.1.286, `capture-pane -p
-J -e` every 0.4s), pasted as bytes. The input box stays drawn while the agent
works, so the only thing separating busy from idle is the ornament's colour.
"""

from __future__ import annotations

import logging

import pytest

from hitchrail.claude_ipc import GRACEFUL_STOP_KEYS, StopNotSafe, WrapUpWatch, request_wrap_up
from hitchrail.claude_ipc import screen as ipc_screen
from test_claude_ipc import (
    CLEAR_BOX,
    DRAFT_BOX,
    MODAL_BOX,
    PLACEHOLDER_BOX,
    FakePane,
    pane_text,
)

IDLE = "\x1b[39m\u276f\xa0                                        "
BUSY = "\x1b[38;5;246m\u276f\xa0\x1b[39m                              "
QUEUED = "\x1b[38;5;246m\u276f\xa0\x1b[2m\x1b[39mPress up to edit queued messages\x1b[0m      "
# A colour nobody captured: neither evidence of idle nor of busy.
UNKNOWN_COLOUR = "\x1b[38;5;99m\u276f\xa0                    "

SETTLE = ipc_screen._SETTLE_DONE_S


# -- one reading ------------------------------------------------------------


def test_the_idle_box_reads_finished() -> None:
    assert ipc_screen.wrap_up_reading(pane_text(IDLE)) is True


def test_the_idle_box_with_the_suggested_prompt_reads_finished() -> None:
    """The dim suggestion is Claude Code's, not typed, as for a stop."""
    assert ipc_screen.wrap_up_reading(pane_text(PLACEHOLDER_BOX)) is True


def test_the_busy_box_reads_not_finished() -> None:
    """The box is drawn and empty, which `shows_input_box` and `input_is_clear`
    both accept: exactly why neither may be the finished rule."""
    assert ipc_screen.wrap_up_reading(pane_text(BUSY)) is False


def test_a_queued_message_reads_not_finished() -> None:
    assert ipc_screen.wrap_up_reading(pane_text(QUEUED)) is False


@pytest.mark.parametrize(
    "pane",
    [
        pane_text(UNKNOWN_COLOUR),
        pane_text(MODAL_BOX),
        # #239's background work modal, as #101 transcribed it: the selected
        # entry carries the ornament and an ORDINARY space.
        pane_text("   \u276f 1. Exit and stop tasks\n     2. Stay"),
        "some output with no input row\n",
        "",
    ],
)
def test_what_cannot_be_read_is_unknown_rather_than_either_answer(pane: str) -> None:
    assert ipc_screen.wrap_up_reading(pane) is None


# What `capture-pane -e` wrote for the e2e shim against tmux 3.4: the idle row
# under a line that ended in the default colour carries no escape at all.
BARE = "\u276f\xa0                     "


@pytest.mark.parametrize(
    ("above", "reading"),
    [
        ("plain output", True),
        ("\x1b[39mplain output", True),
        ("\x1b[38;5;246mgrey border", False),
        ("\x1b[38;5;246mgrey \x1b[0mthen reset", True),
        ("\x1b[38;5;246;48;5;17mgrey on blue", False),
        ("\x1b[38;2;1;2;3mrgb", None),
        ("\x1b[31mred", None),
        ("\x1b[48;5;246mbackground only", True),
    ],
    ids=[
        "default",
        "explicit-default",
        "busy-inherited",
        "reset",
        "busy-with-background",
        "rgb",
        "basic",
        "background-is-not-foreground",
    ],
)
def test_a_bare_ornament_takes_the_colour_left_by_the_line_above(
    above: str, reading: bool | None
) -> None:
    """tmux writes an SGR only where the colour changes, across lines. The
    first version read only the escape touching the ornament, so this row,
    measured, read unknown and every wrap up waited out its ceiling."""
    pane = f"{above}\n{BARE}\n  bypass permissions on\n"
    assert ipc_screen.wrap_up_reading(pane) is reading


@pytest.mark.parametrize(
    "underline",
    ["\x1b[58;5;0m", "\x1b[58;2;31;32;33m"],
    ids=["256", "rgb-with-basic-colour-components"],
)
def test_an_underline_colour_after_the_busy_colour_still_reads_busy(underline: str) -> None:
    """#405: tmux writes an underline colour as its own SGR 58 after the
    foreground. Read as foreground codes, `58;5;0` became the default and
    `31;32;33` a basic colour, and the default is the dangerous answer: a busy
    agent read as idle gets the exit typed mid task."""
    assert ipc_screen._foreground_before("\x1b[38;5;246m" + underline) == "38;5;246"
    pane = f"\x1b[38;5;246m{underline}grey border\n{BARE}\n  bypass permissions on\n"
    assert ipc_screen.wrap_up_reading(pane) is False


def test_an_idle_box_holding_a_draft_is_not_finished() -> None:
    """Someone is typing in the terminal: not the agent's empty box."""
    assert ipc_screen.wrap_up_reading(pane_text(DRAFT_BOX)) is False


def test_an_idle_box_scrolled_past_is_unknown() -> None:
    """`_live_ornament_row`'s rule: output under the row means it moved on."""
    pane = IDLE + "\n" + "\n".join(f"line {i}" for i in range(6))
    assert ipc_screen.wrap_up_reading(pane) is None


# -- over time --------------------------------------------------------------


def _watch(readings: list[tuple[float, str]], sent_at: float = 0.0) -> list[bool]:
    watch = WrapUpWatch(sent_at)
    return [watch.observe(at, pane_text(row)) for at, row in readings]


def test_two_idle_reads_settle_apart_finish() -> None:
    assert _watch([(SETTLE, IDLE), (2 * SETTLE, IDLE)]) == [False, True]


def test_one_idle_read_is_never_enough() -> None:
    assert _watch([(SETTLE, IDLE)]) == [False]


def test_two_idle_reads_closer_than_settle_do_not_finish() -> None:
    assert _watch([(SETTLE, IDLE), (SETTLE + SETTLE / 2, IDLE)]) == [False, False]


def test_a_reading_before_the_turn_could_start_does_not_count() -> None:
    """Idle a moment after `Enter` looks exactly like a turn that ended."""
    early = SETTLE / 2
    assert _watch([(early, IDLE), (SETTLE, IDLE), (SETTLE + SETTLE / 2, IDLE)]) == [
        False,
        False,
        False,
    ]


def test_a_busy_read_between_two_idle_reads_resets_the_run() -> None:
    """The gap between a task's turn and the queued prompt's turn."""
    t = SETTLE
    assert _watch(
        [(t, BUSY), (t + 1, IDLE), (t + 2, BUSY), (t + 3, IDLE), (t + 3 + SETTLE, IDLE)]
    ) == [False, False, False, False, True]


def test_an_unreadable_pane_resets_the_run_and_never_finishes() -> None:
    t = SETTLE
    assert _watch([(t, IDLE), (t + 1, ""), (t + 1 + SETTLE, IDLE)]) == [False, False, False]
    assert _watch([(SETTLE * k, "") for k in range(1, 20)]) == [False] * 19


# -- typing it --------------------------------------------------------------


def _wrap_up(pane: FakePane, prompt: str = "/wrapup") -> None:
    request_wrap_up(pane, "work~site", prompt, settle=lambda _s: None)


def test_the_prompt_is_typed_as_text_after_a_clear_and_never_after_escape() -> None:
    pane = FakePane()
    _wrap_up(pane)
    assert pane.sent == [
        ("work~site", *GRACEFUL_STOP_KEYS[0]),
        ("work~site", "text", "/wrapup"),
        ("work~site", "Enter"),
    ]
    assert not any("Escape" in call for call in pane.sent), "order B: no interrupt"


def test_a_prompt_that_is_a_key_name_is_still_sent_as_text() -> None:
    pane = FakePane()
    _wrap_up(pane, prompt="Enter")
    assert ("work~site", "text", "Enter") in pane.sent


@pytest.mark.parametrize(
    "captures",
    [
        [pane_text(DRAFT_BOX)],
        [pane_text(MODAL_BOX)],
        [""],
    ],
    ids=["draft survived", "modal", "unreadable"],
)
def test_a_box_that_is_not_clear_refuses_and_types_nothing_after_the_clear(
    captures: list[str],
) -> None:
    pane = FakePane(captures)
    with pytest.raises(StopNotSafe):
        _wrap_up(pane)
    assert pane.sent == [("work~site", *GRACEFUL_STOP_KEYS[0])]


def test_a_queued_message_refuses_and_types_nothing_after_the_clear() -> None:
    """`input_is_clear` reads the placeholder as clear, which is right for a
    stop and wrong here: theirs would run first."""
    pane = FakePane([pane_text(QUEUED)])
    with pytest.raises(StopNotSafe, match="queued"):
        _wrap_up(pane)
    assert pane.sent == [("work~site", *GRACEFUL_STOP_KEYS[0])]


def test_the_prompt_never_reaches_the_journal(caplog: pytest.LogCaptureFixture) -> None:
    secretish = "/wrapup and-a-distinctive-string"
    with caplog.at_level(logging.DEBUG, logger="hitchrail.claude_ipc"):
        _wrap_up(FakePane(), prompt=secretish)
    assert "wrap up" in caplog.text
    assert "distinctive" not in caplog.text


def test_the_busy_and_idle_rows_are_both_clear_for_a_stop() -> None:
    """Pins the premise the finished rule rests on: `request_stop`'s check
    cannot tell busy from idle, so it must not be what decides finished."""
    assert ipc_screen.input_is_clear(pane_text(BUSY)) is True
    assert ipc_screen.input_is_clear(pane_text(IDLE)) is True
    assert ipc_screen.input_is_clear(pane_text(CLEAR_BOX)) is True
