"""#242 review, round 1: a second look at a stopping row, and the page's
deadline against the server's expiry. Waits are on the page, never a sleep."""

from __future__ import annotations

import pytest
from playwright.async_api import Page, expect

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
