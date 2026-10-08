"""The list as a phone holds it: what only a measured box can see (Phase 24)."""

from __future__ import annotations

import pytest
from playwright.async_api import Page, expect

from .conftest import Harness

pytestmark = pytest.mark.e2e


async def test_the_last_row_scrolls_clear_of_the_footer_under_a_filter(
    page: Page, server: Harness
) -> None:
    """#447. A fixed 96px of clearance was measured for the unfiltered footer,
    and a filter adds a "12 of 67 shown" line that makes the footer taller, so
    the last row's name and button stayed underneath it. The unfiltered list
    scrolled clear, which is why nothing noticed: the test has to filter."""
    await page.set_viewport_size({"width": 360, "height": 740})
    server.seed_fifty()
    await page.goto(server.base)
    rows = page.locator("[data-project]")
    await expect(rows).to_have_count(50, timeout=15_000)

    await page.locator("[data-roots]").get_by_role("button", name="bravo").click()
    await page.locator("[data-search]").fill("p0")
    await expect(page.locator("[data-shown]")).to_contain_text("shown")
    await expect(rows).to_have_count(10)

    await page.evaluate("() => window.scrollTo(0, document.documentElement.scrollHeight)")
    last_bottom = await rows.last.evaluate("el => el.getBoundingClientRect().bottom")
    footer_top = await page.locator(".footer").evaluate("el => el.getBoundingClientRect().top")
    assert last_bottom <= footer_top - 10, (
        f"the last row ends at {last_bottom}px and the footer starts at {footer_top}px"
    )
