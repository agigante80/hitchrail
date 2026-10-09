"""#475: a wrap up on a session with background work, read from a real capture.

A real Stop waited its full 300s ceiling with background work running, and the
journal could not say whether the agent worked that long or the watch could
not read the screen. The files in `tests/fixtures/claude_pane/` answer it.

**Provenance.** Captured on 2026-10-09 from Claude Code 2.1.295, started as
`claude --dangerously-skip-permissions` in a throwaway directory on a private
tmux socket (120 by 40), with `tmux capture-pane -p -J -e`. Each file is the
last rows of one capture, byte for byte, except that the status line's usage
figures (percentages, resets, cost) are zeroed: no reading looks at them.

- `idle_background_shell`: idle at an empty box, one background shell.
- `idle_background_agent`: idle at an empty box, a background subagent and a
  Monitor running. The subagent adds a panel of rows BELOW the footer, so the
  box has five rows of content under it, and `_MODAL_TAIL_ROWS` took the box
  for a modal scrolled past: every look read unknown, for as long as the
  subagent ran.
- `busy_background_agent`: the same session while a Monitor event woke a turn.
- `exit_menu_background_work`: `/exit` raising the menu #453 answers.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hitchrail.claude_ipc import WrapUpWatch
from hitchrail.claude_ipc import screen as ipc_screen
from hitchrail.claude_ipc.exit_menu import offers_exit

FIXTURES = Path(__file__).parent / "fixtures" / "claude_pane"


def fixture(name: str) -> str:
    return (FIXTURES / f"{name}.txt").read_text(encoding="utf-8")


def test_an_idle_box_over_a_background_shell_reads_finished() -> None:
    assert ipc_screen.wrap_up_reading(fixture("idle_background_shell")) is True


def test_an_idle_box_over_a_background_agent_panel_reads_finished() -> None:
    """The defect: five rows under the box, so the old rule read unknown on
    every look and the wrap up always waited out its ceiling."""
    assert ipc_screen.wrap_up_reading(fixture("idle_background_agent")) is True


def test_a_busy_box_over_a_background_agent_panel_reads_busy() -> None:
    """A False here is real busyness: the ornament is in the busy colour."""
    assert ipc_screen.wrap_up_reading(fixture("busy_background_agent")) is False


def test_the_exit_menu_is_not_a_box_and_stays_unknown() -> None:
    """The menu's ornament has no rule under it, which is what the boxed rule
    keys on, so widening the tail did not widen what reads as the box."""
    menu = fixture("exit_menu_background_work")
    assert ipc_screen.wrap_up_reading(menu) is None
    assert offers_exit(menu) is True, "and the real menu bytes are what #453 answers"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda pane: pane.replace("─", "-"),
        lambda pane: "\n".join(
            row for row in pane.split("\n") if not row.startswith("\x1b[38;5;244m")
        ),
    ],
    ids=["no-rules-drawn", "rules-removed"],
)
def test_a_tail_of_panel_rows_without_the_rules_round_the_box_stays_unknown(mutate) -> None:  # type: ignore[no-untyped-def]
    """The count rule still decides where nothing bounds the row: output under
    an ornament that is not between two rules is a screen that moved on."""
    assert ipc_screen.wrap_up_reading(mutate(fixture("idle_background_agent"))) is None


def test_only_one_rule_round_the_row_is_not_the_box() -> None:
    pane = fixture("idle_background_agent")
    rows = pane.split("\n")
    below = next(i for i, row in enumerate(rows) if "\u276f" in row) + 1
    del rows[below]
    assert ipc_screen.wrap_up_reading("\n".join(rows)) is None


# -- what the watch saw -----------------------------------------------------


def test_the_watch_counts_what_it_read_and_never_what_the_pane_said() -> None:
    watch = WrapUpWatch(0.0)
    settle = ipc_screen._SETTLE_DONE_S
    assert watch.readings() == "readings: 0 idle, 0 busy, 0 unreadable"
    watch.observe(settle / 2, fixture("idle_background_shell"))
    assert watch.readings() == "readings: 0 idle, 0 busy, 0 unreadable", "too early to count"
    watch.observe(settle, fixture("idle_background_shell"))
    watch.observe(settle + 1, fixture("busy_background_agent"))
    watch.observe(settle + 2, fixture("exit_menu_background_work"))
    watch.observe(settle + 3, "")
    assert watch.readings() == "readings: 1 idle, 1 busy, 2 unreadable"
