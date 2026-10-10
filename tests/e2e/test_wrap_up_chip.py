"""#474: a row wrapping up says so, and how long it has left.

The wait dialog already knew the phase, but a reload, another browser or a
dismissed dialog leaves only the row. The arithmetic is a pure module the
browser imports, so its table runs here: this project has no JavaScript runner
(`tests/test_web.py` says why), and the browser tier is where scripts run.
"""

from __future__ import annotations

import re

import pytest
from playwright.async_api import Locator, Page, expect

from .conftest import Harness

pytestmark = pytest.mark.e2e

VIEWPORTS = [
    pytest.param({"width": 360, "height": 800}, id="360"),
    pytest.param({"width": 1280, "height": 800}, id="1280"),
]

# The chip, as seconds, or None when it carries no time.
_LEFT = re.compile(r"wrapping up (\d+):(\d\d)$")


def _left(text: str) -> int | None:
    found = _LEFT.search(text.strip())
    return int(found[1]) * 60 + int(found[2]) if found else None


def _row(page: Page, server: Harness) -> Locator:
    return page.locator(f'[data-project="{server.project("vessel")}"]')


async def _stop_and_hide(page: Page, server: Harness) -> Locator:
    await page.goto(server.base)
    row = _row(page, server)
    await row.get_by_role("button", name="Stop").click()
    dialog = page.locator("[data-dialog]")
    await dialog.get_by_role("button", name="Stop", exact=True).click()
    await expect(dialog).to_contain_text("Asking it to wrap up")
    await dialog.get_by_role("button", name="Hide, keep stopping").click()
    return row


async def test_the_time_left_is_whole_seconds_never_negative(
    page: Page, server: Harness
) -> None:
    """The pure function, over its table. `stopBeganHere` is on the page's own
    clock and `now` is handed in, so no wall clock is involved."""
    server.seed(stopped=["vessel"])
    await page.goto(server.base)
    rows = await page.evaluate(
        """async () => {
          const { wrapUpLeft, wrapUpWords } = await import("/wrapup.js");
          const closing = (began) => ({ stopping_phase: "closing", stopBeganHere: began });
          const cases = [
            [closing(0), 0, 300],
            [closing(0), 1_000, 300],
            [closing(0), 1_001, 300],
            [closing(0), 299_000, 300],
            [closing(0), 300_000, 300],
            [closing(0), 301_000, 300],
            [closing(0), 9_000_000, 300],
            [closing(5_000), 0, 300],
            [closing(0), 0, 10],
            [{ stopping_phase: "exiting", stopBeganHere: 0 }, 0, 300],
            [{ stopping_phase: null }, 0, 300],
            [{ stopping_phase: "closing" }, 0, 300],
            [closing(0), 0, null],
          ];
          return cases.map(([s, now, ceiling]) => {
            const left = wrapUpLeft(s, now, ceiling);
            return [left, wrapUpWords(left)];
          });
        }"""
    )
    assert rows == [
        [300, "wrapping up 5:00"],
        [299, "wrapping up 4:59"],
        [299, "wrapping up 4:59"],
        [1, "wrapping up 0:01"],
        [0, "sending the exit"],
        [0, "sending the exit"],
        [0, "sending the exit"],
        [300, "wrapping up 5:00"],
        [10, "wrapping up 0:10"],
        [None, "wrapping up"],
        [None, "wrapping up"],
        [None, "wrapping up"],
        [None, "wrapping up"],
    ], rows


@pytest.mark.parametrize("viewport", VIEWPORTS)
async def test_a_closing_row_counts_down_and_its_stop_says_it_skips_the_wait(
    page: Page, server: Harness, viewport: dict[str, int]
) -> None:
    await page.set_viewport_size(viewport)  # type: ignore[arg-type]
    server.seed(running=["vessel"], stop_prompt="/wrapup", wrap_up_takes=120)
    await _stop_and_hide(page, server)
    # Reloaded, so the wait that polled and repainted the row is gone: the row
    # is now only what a second browser or a reopened page sees.
    await page.reload()
    row = _row(page, server)

    badge = row.locator(".badge")
    await expect(badge).to_have_text(_LEFT)
    first = _left(await badge.inner_text())
    assert first is not None and 0 < first <= 300, first
    # Counted down in the page with no event to repaint it: the stream is
    # closed, so only the one second tick can move the words.
    await page.evaluate("() => window.__hitchrail.stream.close()")
    await expect(badge).not_to_have_text(f"wrapping up {first // 60}:{first % 60:02d}")
    second = _left(await badge.inner_text())
    assert second is not None and second < first, (first, second)
    # The glyph and the colour are the stopping ones: only the words moved.
    await expect(badge).to_have_attribute("data-badge", "stopping")

    await expect(row.get_by_role("button", name="Exit now")).to_be_visible()
    assert await row.get_by_role("button", name="Stop", exact=True).count() == 0

    # The bar on one line: every control shares a top edge, the name keeps a
    # line of its own, and nothing pushes the page sideways.
    tops = await row.locator(".row-actions > *").evaluate_all(
        "els => els.map(e => Math.round(e.getBoundingClientRect().top))"
    )
    assert len(tops) >= 2 and max(tops) - min(tops) <= 1, tops
    lines = await row.locator(".row-name").evaluate(
        "e => Math.round(e.getBoundingClientRect().height"
        " / parseFloat(getComputedStyle(e).lineHeight))"
    )
    assert lines == 1, lines
    overflow = await page.evaluate(
        "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )
    assert overflow <= 0, overflow


@pytest.mark.parametrize("viewport", VIEWPORTS)
async def test_a_reload_resumes_the_countdown_instead_of_restarting_it(
    page: Page, server: Harness, viewport: dict[str, int]
) -> None:
    await page.set_viewport_size(viewport)  # type: ignore[arg-type]
    server.seed(
        running=["vessel"], stop_prompt="/wrapup", stop_prompt_timeout=100, wrap_up_takes=120
    )
    row = await _stop_and_hide(page, server)
    badge = row.locator(".badge")
    # Wait until at least four seconds are spent, so a restart at the full
    # ceiling (1:40) cannot be mistaken for a resume.
    await page.wait_for_function(
        """(name) => {
          const m = /wrapping up (\\d+):(\\d\\d)$/.exec(
            document.querySelector(`[data-project="${name}"] .badge`).textContent.trim());
          return m && Number(m[1]) * 60 + Number(m[2]) <= 96;
        }""",
        arg=server.project("vessel"),
        timeout=15_000,
    )
    await page.reload()
    row = _row(page, server)
    badge = row.locator(".badge")
    await expect(badge).to_have_text(_LEFT)
    resumed = _left(await badge.inner_text())
    assert resumed is not None and 40 < resumed <= 96, resumed


async def test_an_exiting_row_reads_stopping_again(page: Page, server: Harness) -> None:
    """The wrap up runs out and the exit is sent, which this agent ignores, so
    the row sits in `exiting`: the chip returns to the word it had before #474
    and Stop returns to the button."""
    server.seed(
        running=["vessel"],
        stop_prompt="/wrapup",
        stop_prompt_timeout=10,
        wrap_up_stays_busy=True,
    )
    row = await _stop_and_hide(page, server)
    badge = row.locator(".badge")
    await expect(badge).to_have_text(_LEFT)
    await expect(badge).to_have_text(re.compile(r"^\s*stopping\s*$"), timeout=30_000)
    await expect(row.get_by_role("button", name="Stop", exact=True)).to_be_visible()
    assert await row.get_by_role("button", name="Exit now").count() == 0


async def test_without_a_stop_prompt_nothing_changes(page: Page, server: Harness) -> None:
    server.seed(running=["vessel"], ignores_graceful_stop=True)
    await page.goto(server.base)
    row = _row(page, server)
    await row.get_by_role("button", name="Stop").click()
    await page.locator("[data-dialog]").get_by_role("button", name="Stop", exact=True).click()
    await (
        page.locator("[data-dialog]").get_by_role("button", name="Hide, keep stopping").click()
    )
    await expect(row.locator(".badge")).to_have_text(re.compile(r"^\s*stopping\s*$"))
    await expect(row.get_by_role("button", name="Stop", exact=True)).to_be_visible()
    assert await row.get_by_role("button", name="Exit now").count() == 0
