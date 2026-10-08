"""The list as a phone holds it: what only a measured box can see (Phase 24)."""

from __future__ import annotations

from itertools import pairwise

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


LONG_ROOTS = ("northwind", "greenhouse", "scratchpad", "experiments")


def _seed_long_roots(server: Harness) -> None:
    """Five roots, the primary one included, with two digit counts."""
    names = [f"p{i:02d}" for i in range(12)]
    server.seed(stopped=names, stopped_in=dict.fromkeys(LONG_ROOTS, names))


_BOXES = (
    "els => els.map(e => { const r = e.getBoundingClientRect();"
    " return { left: r.left, right: r.right, over: e.scrollWidth - e.clientWidth }; })"
)


async def test_root_chips_keep_their_width_and_the_strip_scrolls(
    page: Page, server: Harness
) -> None:
    """#448. `.chips button` kept the default `flex-shrink: 1`, so five roots
    were squeezed into the width and `nowrap` ran each label out past its pill
    and over the next one. Three assertions, because each alone passes a
    different half of the broken layout."""
    await page.set_viewport_size({"width": 360, "height": 740})
    _seed_long_roots(server)
    await page.goto(server.base)
    await expect(page.locator("[data-project]")).to_have_count(60, timeout=15_000)
    strip = page.locator("[data-roots]")
    chips = strip.get_by_role("button")
    assert await chips.count() == 5

    boxes = await chips.evaluate_all(_BOXES)
    for before, after in pairwise(boxes):
        assert before["right"] <= after["left"], f"chips overlap: {before} and {after}"
    assert all(box["over"] <= 0 for box in boxes), f"a label outruns its pill: {boxes}"
    assert await strip.evaluate("el => el.scrollWidth > el.clientWidth"), (
        "five long roots fit one screen, so this test no longer proves the strip scrolls"
    )


async def test_tabs_keep_their_width_when_the_strip_is_too_narrow(
    page: Page, server: Harness
) -> None:
    """#448, the same shape on `.tabs button`, which only survived because
    three tabs fit. The viewport is the narrowest the Reflow criterion names,
    and the counts are three digits so the strip is genuinely too narrow."""
    await page.set_viewport_size({"width": 320, "height": 640})
    server.seed(stopped=[f"p{i:03d}" for i in range(120)])
    await page.goto(server.base)
    await expect(page.locator("[data-project]")).to_have_count(120, timeout=15_000)
    boxes = await page.get_by_role("tab").evaluate_all(_BOXES)
    for before, after in pairwise(boxes):
        assert before["right"] <= after["left"], f"tabs overlap: {before} and {after}"
    assert all(box["over"] <= 0 for box in boxes), f"a label outruns its tab: {boxes}"
