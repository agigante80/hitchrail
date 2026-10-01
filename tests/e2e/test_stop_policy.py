"""#239: a stop that ends on a prompt, under `stop_policy = end_anyway`.

The shim answers the exit with the background work modal, which is what a
real agent with work running does. Waits are on the page and the row, never
a sleep (#70).
"""

from __future__ import annotations

import pytest
from playwright.async_api import Page, expect

from .conftest import Harness

pytestmark = pytest.mark.e2e

NOTE = "If it stops on a question it will be ended"


async def _confirm(page: Page, server: Harness) -> None:
    await page.goto(server.base)
    # Longer than the server's wait, so it is the server's kill under test and
    # not the browser giving up first.
    await page.evaluate("() => window.__hitchrail.setStopPatience(20000)")
    row = page.locator(f'[data-project="{server.project("vessel")}"]')
    await expect(row).to_be_visible()
    await row.get_by_role("button", name="Stop").click()


async def test_end_anyway_says_so_and_ends_a_stop_that_asks(
    page: Page, server: Harness
) -> None:
    server.seed(
        running=["vessel"], prompts_after_stop=True, stop_timeout=2.0, stop_policy="end_anyway"
    )
    await _confirm(page, server)
    dialog = page.locator("[data-dialog]")
    await expect(dialog).to_contain_text(NOTE)
    await dialog.get_by_role("button", name="Stop", exact=True).click()
    await expect(dialog).to_contain_text(NOTE)

    # No tap: the server kills at its own expiry, and the row says so.
    await expect(
        page.locator(f'[data-project="{server.project("vessel")}"]')
    ).to_have_attribute("data-state", "stopped", timeout=20_000)
    await expect(dialog).to_be_hidden()


async def test_ask_says_nothing_of_the_kind(page: Page, server: Harness) -> None:
    """The default is today's dialog, word for word."""
    server.seed(running=["vessel"], prompts_after_stop=True, stop_timeout=2.0)
    await _confirm(page, server)
    dialog = page.locator("[data-dialog]")
    await expect(dialog).to_contain_text("It will be interrupted")
    assert NOTE not in await dialog.inner_text()
