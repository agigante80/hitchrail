"""#242 review, round 1: a second look at a stopping row, and the page's
deadline against the server's expiry. Waits are on the page, never a sleep."""

from __future__ import annotations

import re

import pytest
from playwright.async_api import Page, Route, expect

from hitchrail import claude_ipc
from hitchrail.engine import StopMarker

from .conftest import Harness

pytestmark = pytest.mark.e2e


async def test_stop_on_a_wrapping_up_row_reopens_the_wait(page: Page, server: Harness) -> None:
    """A second Stop is the Exit now, which interrupts the task. Behind a
    confirmation promising a wrap up it did the opposite of what it said, so
    the row's Stop shows the wait already running instead."""
    server.seed(running=["vessel"], stop_prompt="/wrapup", wrap_up_takes=120)
    await page.goto(server.base)
    row = page.locator(f'[data-project="{server.project("vessel")}"]')
    await row.get_by_role("button", name="Stop").click()
    dialog = page.locator("[data-dialog]")
    await dialog.get_by_role("button", name="Stop", exact=True).click()
    await expect(dialog.get_by_role("button", name="Exit now")).to_be_visible()
    await dialog.get_by_role("button", name="Hide, keep stopping").click()
    await expect(dialog).to_be_hidden()

    await row.get_by_role("button", name="Stop").click()
    await expect(dialog).to_contain_text("Asking it to wrap up")
    await expect(dialog.get_by_role("button", name="Exit now")).to_be_visible()
    assert "then to exit" not in await dialog.inner_text(), "a second confirm"


async def test_the_page_waits_for_the_servers_look_at_the_pane(
    page: Page, server: Harness
) -> None:
    """No patience override, so the page's deadline and the server's expiry
    are the same 2s. The page used to win that race and say "no answer"
    before the server's one look at the pane said a question was up."""
    server.seed(running=["vessel"], prompts_after_stop=True, stop_timeout=2.0)
    await page.goto(server.base)
    row = page.locator(f'[data-project="{server.project("vessel")}"]')
    await row.get_by_role("button", name="Stop").click()
    dialog = page.locator("[data-dialog]")
    await dialog.get_by_role("button", name="Stop", exact=True).click()
    await expect(dialog).to_contain_text("is waiting for you", timeout=20_000)


async def test_a_stop_whose_reply_was_lost_is_watched_when_reopened(
    page: Page, server: Harness
) -> None:
    """#242 review round 2. The DELETE reached the server and its reply did
    not reach the page, so the row reads `stopping` while the page's wait
    never started ticking. Reopening it must start one, or the dialog is
    painted once and its count, phase and deadline never move."""
    server.seed(running=["vessel"], stop_prompt="/wrapup", wrap_up_takes=8)
    await page.goto(server.base)

    async def deliver_then_drop(route: Route) -> None:
        if route.request.method != "DELETE":
            await route.continue_()
            return
        await route.fetch()
        await route.abort()

    await page.route("**/api/sessions/*", deliver_then_drop)
    row = page.locator(f'[data-project="{server.project("vessel")}"]')
    await row.get_by_role("button", name="Stop").click()
    dialog = page.locator("[data-dialog]")
    await dialog.get_by_role("button", name="Stop", exact=True).click()
    await expect(dialog.get_by_role("button", name="Close")).to_be_visible()
    await dialog.get_by_role("button", name="Close").click()
    await page.unroute("**/api/sessions/*")
    await expect(row).to_have_attribute("data-stopping", "true")

    await row.get_by_role("button", name="Stop").click()
    await expect(dialog.get_by_role("button", name="Exit now")).to_be_visible()
    # Only the ticker repaints the count, so a wait nobody drives stays on the
    # second it was painted at.
    await expect(dialog).to_contain_text(re.compile(r"\b[3-9]s so far"))
    await expect(dialog).to_be_hidden(timeout=30_000)


def _count(text: str) -> int:
    found = re.search(r"\b(\d+)s so far", text)
    assert found, text
    return int(found.group(1))


async def test_a_wait_reopened_after_a_reload_counts_from_the_stop(
    page: Page, server: Harness
) -> None:
    """#411. The reloaded page has no wait of its own, and counted from the
    tap: "1s so far" for a wrap up that had run for longer."""
    server.seed(running=["vessel"], stop_prompt="/wrapup", wrap_up_takes=120)
    await page.goto(server.base)
    row = page.locator(f'[data-project="{server.project("vessel")}"]')
    await row.get_by_role("button", name="Stop").click()
    dialog = page.locator("[data-dialog]")
    await dialog.get_by_role("button", name="Stop", exact=True).click()
    await expect(dialog).to_contain_text(re.compile(r"\b([4-9]|\d\d+)s so far"), timeout=10_000)

    await page.reload()
    await expect(row).to_have_attribute("data-stopping", "true")
    await row.get_by_role("button", name="Stop").click()
    await expect(dialog).to_contain_text("s so far")
    assert _count(await dialog.inner_text()) >= 4


async def test_another_browser_is_offered_no_exit_now_while_the_prompt_is_typed(
    page: Page, server: Harness
) -> None:
    """#408. Only the tapping browser knew it was still sending; any other
    learned `closing` from the listing and offered an Exit now that answered
    202 and did nothing. The typing window is planted in the engine, since
    the real one is a few milliseconds wide."""
    server.seed(running=["vessel"], stop_prompt="/wrapup", wrap_up_takes=120)
    engine = server.engine
    assert engine is not None
    name = server.project("vessel")
    marker = StopMarker(engine._clock(), "closing", "ask")
    engine._stopping[name] = marker
    await page.goto(server.base)
    row = page.locator(f'[data-project="{name}"]')
    await expect(row).to_have_attribute("data-stopping", "true")
    await row.get_by_role("button", name="Stop").click()
    dialog = page.locator("[data-dialog]")
    await expect(dialog).to_contain_text("Asking it to wrap up, after its current task.")
    await expect(dialog).to_have_attribute("data-waiting", "sending")
    assert await dialog.get_by_role("button", name="Exit now").count() == 0

    # The prompt is out: the wait's own ticker moves it on, and Exit now works.
    marker.watch = claude_ipc.WrapUpWatch(sent_at=engine._clock())
    await expect(dialog.get_by_role("button", name="Exit now")).to_be_visible()
