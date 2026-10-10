"""#294, task 266: the agy package, against screens rebuilt from agy 1.3.3's rows.

Every screen below is the captured escapes and characters, quoted on #294,
with the transcript cut and the link id replaced. Nothing here starts an agy.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hitchrail import agy_ipc
from hitchrail.agent import AnswerNotSafe, StopNotSafe
from hitchrail.agy_ipc import screen
from test_claude_ipc import FakePane

RULE = "\x1b[90m" + "─" * 60
BOX = "\x1b[94m>\x1b[39m"
IDLE_FOOTER = "? for shortcuts\x1b[39m          \x1b[2mGemini 3.8 Flash · high"
BUSY_FOOTER = "esc to cancel\x1b[39m            \x1b[2mGemini 3.8 Flash · high"
QUEUED_FOOTER = "  Press up to edit queued messages\x1b[39m   \x1b[2mGemini 3.8 Flash · high"
HISTORY = [RULE, "\x1b[1m\x1b[34m> say BANANA\x1b[0m", "  BANANA"]
SPINNER = "⣟  \x1b[90mG\x1b[94menera\x1b[90mting...\x1b[39m"
LINK_ID = "00000000-1111-2222-3333-444444444444-v2"


def _screen(*rows: str) -> str:
    # A pane is captured to its full height, so blank rows follow the footer.
    return "\n".join([*rows, "", "", ""])


IDLE = _screen(*HISTORY, RULE, BOX, RULE, IDLE_FOOTER)
DRAFT = _screen(*HISTORY, RULE, BOX + " draft text here", RULE, "\x1b[39m   \x1b[2mGemini")
BUSY = _screen(*HISTORY, SPINNER, RULE, BOX, RULE, BUSY_FOOTER)
QUEUED = _screen(
    *HISTORY, SPINNER, "\x1b[90m▸ say BANANA\x1b[39m", RULE, BOX, RULE, QUEUED_FOOTER
)
# A background task's panel sits under the box, between its own rules.
TASK_PANEL = _screen(
    *HISTORY,
    RULE,
    BOX,
    RULE,
    "\x1b[39m  \x1b[33m●\x1b[39m [15:23:24] \x1b[94msleep 20\x1b[39m \x1b[33mrunning\x1b[39m",
    RULE,
    IDLE_FOOTER + " · 1 task(s) · /tasks",
)
SLASH_MENU = _screen(
    *HISTORY,
    RULE,
    BOX + " \x1b[94m/exit\x1b[39m",
    RULE,
    "\x1b[94m> /exit\x1b[39m  \x1b[2mExit the CLI\x1b[0m",
    "\x1b[90mesc to cancel\x1b[39m",
)
TRUST_PROMPT = _screen(
    "Do you trust the contents of this project?", "> Yes, I trust this folder", "  No, exit"
)


@pytest.mark.parametrize(
    ("pane", "clear"),
    [
        (IDLE, True),
        (BUSY, True),
        (QUEUED, True),
        (TASK_PANEL, True),
        (DRAFT, False),
        (SLASH_MENU, False),
        (TRUST_PROMPT, None),
        ("", None),
        # The history echo alone has a rule above and text below: not a box.
        (_screen(*HISTORY), None),
    ],
)
def test_the_live_box_is_the_last_prompt_row_between_two_rules(
    pane: str, clear: bool | None
) -> None:
    assert screen.input_is_clear(pane) is clear


@pytest.mark.parametrize(
    ("pane", "reading"),
    [
        (IDLE, True),
        (TASK_PANEL, True),
        (BUSY, False),
        (QUEUED, False),
        (DRAFT, False),
        (SLASH_MENU, False),
        (TRUST_PROMPT, None),
        (_screen(*HISTORY, RULE, BOX, RULE, "a footer nobody captured"), None),
    ],
)
def test_a_wrap_up_reads_idle_only_from_the_idle_footer_at_an_empty_box(
    pane: str, reading: bool | None
) -> None:
    assert screen.wrap_up_reading(pane) is reading


def test_a_queued_message_is_seen_by_its_row_or_its_footer() -> None:
    assert screen.queued_message(QUEUED)
    assert screen.queued_message(QUEUED.replace(QUEUED_FOOTER, BUSY_FOOTER))
    assert screen.queued_message(QUEUED.replace("▸ say BANANA", "Tip"))
    assert not screen.queued_message(BUSY)
    assert not screen.queued_message(TRUST_PROMPT)


def test_the_stop_clears_checks_and_exits_with_no_interrupt() -> None:
    """agy's `/exit` is not queued behind a turn, so there is no `Escape`."""
    pane = FakePane([IDLE])
    agy_ipc.Antigravity().request_stop(pane, "main~p", lambda s: None)
    assert pane.sent == [("main~p", "C-u"), ("main~p", "/exit", "Enter")]


@pytest.mark.parametrize(
    ("captures", "complaint"),
    [
        ([DRAFT], "did not come back empty"),
        ([TRUST_PROMPT], "could not be found"),
        ([""], "could not be read"),
        # A box seen dirty is not forgotten because a later look failed.
        ([DRAFT, DRAFT, DRAFT, ""], "did not come back empty"),
    ],
)
def test_the_stop_refuses_unless_the_box_is_certainly_clear(
    captures: list[str], complaint: str
) -> None:
    pane = FakePane(captures)
    with pytest.raises(StopNotSafe, match=complaint):
        agy_ipc.Antigravity().request_stop(pane, "main~p", lambda s: None)
    assert pane.sent == [("main~p", "C-u")], "the exit was never typed"


def test_the_stop_settles_before_every_look() -> None:
    waits: list[float] = []
    pane = FakePane([DRAFT, DRAFT, IDLE])
    agy_ipc.Antigravity().request_stop(pane, "p", waits.append)
    assert len(waits) == len(pane.captured) == 3


def test_the_wrap_up_types_the_prompt_as_text_behind_a_busy_turn() -> None:
    pane = FakePane([BUSY])
    agy_ipc.Antigravity().request_wrap_up(pane, "p", "C-c", lambda s: None)
    assert pane.sent == [("p", "C-u"), ("p", "text", "C-c"), ("p", "Enter")]


def test_the_wrap_up_refuses_behind_a_message_already_queued() -> None:
    pane = FakePane([QUEUED])
    with pytest.raises(StopNotSafe, match="already has a message queued"):
        agy_ipc.Antigravity().request_wrap_up(pane, "p", "wrap up", lambda s: None)
    assert pane.sent == [("p", "C-u")]


def test_no_answer_is_ever_sent_and_no_question_is_claimed() -> None:
    """Not captured, so unknown: never a guess at which key a question wants."""
    agy = agy_ipc.Antigravity()
    assert agy.answer_keys == frozenset()
    assert agy.has_plugins is False, "the settings page would offer agy an update"
    assert agy.awaits_answer(IDLE) is None
    pane = FakePane([IDLE])
    with pytest.raises(AnswerNotSafe):
        agy.send_answer(pane, "p", "1")
    assert pane.sent == []
    assert pane.captured == [], "the pane is not read for a key that will not be sent"


def test_the_argv_tail_names_the_folder_and_never_the_tag(tmp_path: Path) -> None:
    """agy refuses a trailing positional; the folder makes the tail unique."""
    argv = agy_ipc.Antigravity().launch_argv("/opt/agy", "main~proj", tmp_path / "a b")
    assert argv == [
        "/opt/agy",
        "--dangerously-skip-permissions",
        "--remote-control",
        f"--add-dir={tmp_path / 'a b'}",
    ]
    assert agy_ipc.MARKER in argv[-1]
    assert "main~proj" not in " ".join(argv)


def test_its_marker_is_not_claude_codes() -> None:
    """Both argvs carry `--remote-control`; a shared marker would read a pane
    holding agy as Claude Code's, with Claude Code's link and stop."""
    from hitchrail import claude_ipc

    claude_argv = " ".join(claude_ipc.launch_argv("claude", "main~proj"))
    assert agy_ipc.MARKER not in claude_argv


def test_every_folder_is_trusted_because_the_argv_skips_the_prompt(tmp_path: Path) -> None:
    agy = agy_ipc.Antigravity()
    trusted = agy.trusted()
    assert trusted is not None
    assert agy.folder_is_trusted(tmp_path, trusted)


@pytest.mark.parametrize(
    ("pane", "link"),
    [
        (f"Open {agy_ipc.URL_BASE}{LINK_ID} on another", f"{agy_ipc.URL_BASE}{LINK_ID}"),
        (f"Open {agy_ipc.URL_BASE}{LINK_ID}\ndevice", f"{agy_ipc.URL_BASE}{LINK_ID}"),
        # Wrapped at the pane's edge: the id on the row is cut, so no link.
        (f"Open {agy_ipc.URL_BASE}{LINK_ID[:20]}\n{LINK_ID[20:]} on", None),
        (f"Open {agy_ipc.URL_BASE}{LINK_ID[:-3]} on another", None),
        (f"Open {agy_ipc.URL_BASE}../../evil on another", None),
        (f"Open https://evil.example/r/{LINK_ID} on another", None),
        ("", None),
    ],
)
def test_the_link_is_scraped_only_in_its_captured_shape(pane: str, link: str | None) -> None:
    found = agy_ipc.Antigravity().session_url(1, pane)
    assert (found.url if found else None) == link
    assert found is None or found.source == "scraped"


def test_the_last_link_wins_over_an_earlier_agy_in_the_same_pane() -> None:
    older = LINK_ID.replace("0000", "9999")
    pane = f"{agy_ipc.URL_BASE}{older} on\n...\n{agy_ipc.URL_BASE}{LINK_ID} on"
    found = agy_ipc.Antigravity().session_url(1, pane)
    assert found is not None
    assert found.url.endswith(LINK_ID)
    assert agy_ipc.Antigravity().bridge_url(1) is None


def test_a_wrap_up_finishes_only_after_an_unbroken_idle_run() -> None:
    watch = agy_ipc.Antigravity().wrap_up_watch(sent_at=0.0)
    assert not watch.observe(1.0, IDLE), "too soon after the prompt"
    assert not watch.observe(2.0, IDLE)
    assert not watch.observe(3.0, BUSY)
    assert not watch.observe(4.0, IDLE)
    assert watch.observe(6.0, IDLE)
    assert watch.readings() == "readings: 3 idle, 1 busy, 0 unreadable"
