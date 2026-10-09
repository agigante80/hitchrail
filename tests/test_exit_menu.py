"""#453: the one dialog the stop answers, and every screen it must not.

`claude_ipc.exit_menu` reads the menu `/exit` raises over background work;
`request_stop` presses `Enter` on it. The refusals are most of this file,
because the reversal of #88 is only safe while everything that is not exactly
this menu falls back to pressing nothing.
"""

from __future__ import annotations

import logging

import pytest

from hitchrail.claude_ipc import exit_menu as ipc_exit_menu
from hitchrail.claude_ipc import request_stop
from hitchrail.claude_ipc.exit_menu import exit_menu_appeared, offers_exit
from hitchrail.tmux import TmuxUnavailable
from test_claude_ipc import CLEAR_BOX, EXIT_MODAL_SCREEN, MODAL_BOX, FakePane, pane_text

_ROW = "\x1b[39m \x1b[38;5;153m\u276f\x1b[39m \x1b[38;5;153m{}"

# The 2026-10-08 capture: three options, the first preselected.
MENU = (
    "some output\n"
    " Background work is running\n"
    " The following will stop when you exit:\n"
    "   monitor \u00b7 messages\n" + _ROW.format("1. Exit and stop tasks") + "\n"
    "   2. Move to background and exit\n"
    "   3. Stay\n"
    " Enter to confirm \u00b7 Esc to cancel\n"
)


def _menu(selected: str, *, heading: str = " Background work is running") -> str:
    return (
        f"some output\n{heading}\n"
        " The following will stop when you exit:\n"
        "   monitor \u00b7 messages\n" + _ROW.format(selected) + "\n"
        "   3. Stay\n"
        " Enter to confirm \u00b7 Esc to cancel\n"
    )


def test_the_captured_menu_offers_the_exit() -> None:
    assert offers_exit(MENU) is True
    # And #165's two option capture, which the badge tests already use.
    assert offers_exit(EXIT_MODAL_SCREEN) is True


@pytest.mark.parametrize(
    "selected",
    [
        "2. Move to background and exit",
        "3. Stay",
        "1. Exit and keep tasks",
        "1. Exit and stop tasks now",
        "1. exit and stop tasks",
        "",
    ],
    ids=["background", "stay", "reworded", "extended", "case", "empty"],
)
def test_any_other_selected_row_is_not_the_exit(selected: str) -> None:
    """By text, never position: a reordered menu with "Move to background and
    exit" selected would make the detached agent the design exists to surface,
    and a reworded one is a menu nobody has read."""
    assert offers_exit(_menu(selected)) is False


def test_without_the_heading_it_is_not_the_menu() -> None:
    """The same option under another dialog's words is another dialog."""
    assert offers_exit(_menu("1. Exit and stop tasks", heading=" Something else")) is False


def test_a_heading_from_an_earlier_dialog_does_not_lend_itself() -> None:
    """An ornament row between the heading and the selected row means the
    heading belongs to something drawn before."""
    screen = (
        " Background work is running\n"
        + MODAL_BOX
        + "\n"
        + "   later output\n" * 2
        + _ROW.format("1. Exit and stop tasks")
        + "\n"
    )
    assert offers_exit(screen) is False


def test_a_menu_scrolled_past_is_not_live() -> None:
    """#208's rule, inherited: output below the row means the agent moved on."""
    scrolled = MENU + "".join(f"  writing file {i}.py\n" for i in range(12))
    assert offers_exit(scrolled) is False


def test_an_input_box_is_not_the_menu() -> None:
    """The NBSP after the ornament is the box, even if its draft read as the option."""
    box = "\x1b[39m\u276f\xa0Exit and stop tasks"
    assert offers_exit(" Background work is running\n" + box + "\n") is False
    assert offers_exit(pane_text(CLEAR_BOX)) is False
    assert offers_exit("") is False


def test_the_menu_above_a_live_input_box_is_history() -> None:
    """The menu answered, or printed by the agent, and the box drawn after it:
    the live row is the box, so there is nothing to answer."""
    assert offers_exit(MENU + pane_text(CLEAR_BOX)) is False


def test_the_option_on_an_unselected_row_does_not_count() -> None:
    """Only the selected row is read; the option merely being offered is not
    the option being the one Enter picks."""
    screen = (
        " Background work is running\n"
        + _ROW.format("1. Stay")
        + "\n   2. Exit and stop tasks\n"
    )
    assert offers_exit(screen) is False


def test_the_trust_modal_is_never_answered() -> None:
    """#88's dialog, the one whose highlighted entry grants a folder full
    permissions. It must read as not this menu whatever surrounds it."""
    assert offers_exit(" Background work is running\n" + pane_text(MODAL_BOX)) is False


class _Looks:
    """A pane that always shows `screen`, recording each look and wait in order."""

    def __init__(self, screen: str) -> None:
        self.screen = screen
        self.order: list[str] = []

    def look(self) -> str:
        self.order.append("look")
        return self.screen

    def wait(self) -> None:
        self.order.append("wait")


def test_an_empty_look_ends_the_wait_early() -> None:
    """The session went with the agent: the ordinary exit, nothing to press."""
    pane = _Looks("")
    assert exit_menu_appeared(pane.look, pane.wait) is False
    assert pane.order.count("look") == 1


def test_a_menu_that_never_comes_is_given_up_on() -> None:
    pane = _Looks(pane_text(CLEAR_BOX))
    assert exit_menu_appeared(pane.look, pane.wait) is False
    assert pane.order.count("look") == ipc_exit_menu.MENU_TRIES


def test_the_wait_comes_before_every_look() -> None:
    """The keys went out a moment ago, so the first look can be the old frame."""
    pane = _Looks(MENU)
    assert exit_menu_appeared(pane.look, pane.wait) is True
    assert pane.order == ["wait", "look"]


def test_the_stop_answers_the_menu_with_enter_after_the_exit() -> None:
    """The scenario #453 was filed on: clear, clear, then the menu."""
    clear = pane_text(CLEAR_BOX)
    pane = FakePane([clear, clear, clear, MENU])
    request_stop(pane, "vessel", settle=lambda _s: None)
    sent = [s[1:] for s in pane.sent]
    assert sent == [("C-u",), ("Escape",), ("/exit", "Enter"), ("Enter",)]


@pytest.mark.parametrize(
    "after_exit",
    [_menu("3. Stay"), _menu("2. Move to background and exit"), pane_text(MODAL_BOX)],
    ids=["stay", "background", "trust modal"],
)
def test_the_stop_presses_nothing_on_any_other_screen(after_exit: str) -> None:
    """Failing closed: the stop is what it was before #453, and the expiry
    reports the row as waiting on a person (#101)."""
    clear = pane_text(CLEAR_BOX)
    pane = FakePane([clear, clear, after_exit])
    request_stop(pane, "vessel", settle=lambda _s: None)
    assert [s[1:] for s in pane.sent] == [("C-u",), ("Escape",), ("/exit", "Enter")]


def test_the_stop_presses_nothing_when_the_agent_simply_exits() -> None:
    clear = pane_text(CLEAR_BOX)
    pane = FakePane([clear, clear, ""])
    request_stop(pane, "vessel", settle=lambda _s: None)
    assert [s[1:] for s in pane.sent] == [("C-u",), ("Escape",), ("/exit", "Enter")]
    assert len(pane.captured) == 3, "an empty look must end the wait"


def test_the_answer_is_logged_without_the_screen(caplog: pytest.LogCaptureFixture) -> None:
    clear = pane_text(CLEAR_BOX)
    pane = FakePane([clear, clear, MENU])
    with caplog.at_level(logging.INFO, logger="hitchrail.claude_ipc"):
        request_stop(pane, "vessel", settle=lambda _s: None)
    assert "the exit asked about background work, sent Enter" in caplog.text
    assert "monitor" not in caplog.text


class _TmuxDown(FakePane):
    """A pane whose tmux fails from the Nth capture on."""

    def capture_pane(self, project: str, lines: int = 40, escapes: bool = False) -> str:
        if len(self.captured) >= 2:
            raise TmuxUnavailable("tmux went away")
        return super().capture_pane(project, lines, escapes)


def test_a_tmux_failure_while_waiting_for_the_menu_is_a_miss(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """#454: the exit already went out, so this is not an "exit refused"."""
    pane = _TmuxDown([pane_text(CLEAR_BOX)] * 2)
    with caplog.at_level(logging.WARNING, logger="hitchrail.claude_ipc"):
        request_stop(pane, "vessel", settle=lambda _s: None)
    assert [s[1:] for s in pane.sent] == [("C-u",), ("Escape",), ("/exit", "Enter")]
    assert "pressed nothing" in caplog.text


def test_a_tmux_failure_before_the_exit_still_refuses() -> None:
    """The miss is only for the wait after the exit: a failure while the box is
    being checked must still stop the sequence."""

    class Down(FakePane):
        def capture_pane(self, project: str, lines: int = 40, escapes: bool = False) -> str:
            raise TmuxUnavailable("tmux went away")

    pane = Down()
    with pytest.raises(OSError):
        request_stop(pane, "vessel", settle=lambda _s: None)
    assert ("vessel", "/exit", "Enter") not in pane.sent


@pytest.mark.parametrize(
    "frame",
    [
        " Background work is running\n The following will stop when you exit:\n",
        " The following will stop when you exit:\n"
        + _ROW.format("1. Exit and stop tasks")
        + "\n",
        " Background work is running\n" + _ROW.format("1. Exit and stop") + "\n",
        " Background work is running\n" + _ROW.format("1. Exit and stop ta") + "\n",
    ],
    ids=["heading only", "row without heading", "row cut mid text", "row cut at the end"],
)
def test_a_frame_caught_mid_draw_is_not_the_menu(frame: str) -> None:
    """Why one look is enough (#454): a partial frame lacks the heading or the
    whole text of the selected row, and either reads as not the menu."""
    assert offers_exit(frame) is False


_P = chr(0x276F)

# -- survivors of the #454 mutation run, read and judged real ----------------


@pytest.mark.parametrize(
    "row",
    [
        _ROW.format(f"1. Exit and stop tasks {_P} trailing"),
        _ROW.format(f"{_P} 1. Exit and stop tasks"),
    ],
    ids=["second prompt after", "second prompt before"],
)
def test_a_second_prompt_char_in_the_row_is_not_the_menu(row: str) -> None:
    """The text after the FIRST prompt is the whole option, so a row carrying
    another one is not exactly "Exit and stop tasks"."""
    frame = " Background work is running\n x\n" + row + "\n"
    assert offers_exit(frame) is False


def test_the_heading_may_sit_directly_above_the_selected_row() -> None:
    frame = " Background work is running\n" + _ROW.format("1. Exit and stop tasks") + "\n"
    assert offers_exit(frame) is True


def test_the_heading_is_looked_for_above_the_last_copy_of_the_row() -> None:
    """An identical row earlier on screen must not move the search up past the
    heading that belongs to the live one."""
    row = _ROW.format("1. Exit and stop tasks")
    frame = row + "\n x\n Background work is running\n" + row + "\n"
    assert offers_exit(frame) is True
