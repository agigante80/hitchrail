"""The list as a phone holds it: what only a measured box can see (Phase 24).

Every test here runs on `busy.seed_busy`, at the daily phone's width and at the
narrowest WCAG 1.4.10 Reflow names. Until #450 these defects were invisible
because the tier used one root, short names and 390px, and the phone had five
roots, sixty folders and 360.
"""

from __future__ import annotations

from itertools import pairwise

import pytest
from playwright.async_api import Page, expect

from .busy import EXTRA_ROOTS, PHONE_VIEWPORTS, Busy, seed_busy
from .conftest import Harness

pytestmark = pytest.mark.e2e

phone = pytest.mark.parametrize(
    "viewport", PHONE_VIEWPORTS, ids=[f"{v['width']}x{v['height']}" for v in PHONE_VIEWPORTS]
)

_STATES = ("stopped", "running", "stale", "detached")


async def _busy_list(page: Page, server: Harness, viewport: dict[str, int]) -> Busy:
    await page.set_viewport_size(viewport)  # type: ignore[arg-type]
    busy = seed_busy(server)
    await page.goto(server.base)
    await expect(page.locator("[data-project]")).to_have_count(busy.total, timeout=15_000)
    return busy


@phone
async def test_the_busy_list_does_not_scroll_sideways(
    page: Page, server: Harness, viewport: dict[str, int]
) -> None:
    """The Reflow criterion: no two dimensional scrolling at 320px. The chip
    strip scrolls inside itself (#448), which is not the page scrolling."""
    await _busy_list(page, server, viewport)
    overflow = await page.evaluate(
        "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )
    assert overflow <= 0, f"the page scrolls sideways by {overflow}px at {viewport['width']}px"


@phone
async def test_the_last_row_scrolls_clear_of_the_footer_under_a_filter(
    page: Page, server: Harness, viewport: dict[str, int]
) -> None:
    """#447. A fixed 96px of clearance was measured for the unfiltered footer,
    and a filter adds a "12 of 67 shown" line that makes the footer taller, so
    the last row's name and button stayed underneath it. The unfiltered list
    scrolled clear, which is why nothing noticed: the test has to filter."""
    await _busy_list(page, server, viewport)
    await page.locator("[data-roots]").get_by_role("button", name=EXTRA_ROOTS[-1]).click()
    await page.locator("[data-search]").fill("a")
    await expect(page.locator("[data-shown]")).to_contain_text("shown")
    rows = page.locator("[data-project]")
    assert await rows.count() >= 5, "the filter left too few rows to need a scroll"

    await page.evaluate("() => window.scrollTo(0, document.documentElement.scrollHeight)")
    last_bottom = await rows.last.evaluate("el => el.getBoundingClientRect().bottom")
    footer_top = await page.locator(".footer").evaluate("el => el.getBoundingClientRect().top")
    assert last_bottom <= footer_top - 10, (
        f"the last row ends at {last_bottom}px and the footer starts at {footer_top}px"
    )


_BOXES = (
    "els => els.map(e => { const r = e.getBoundingClientRect();"
    " return { left: r.left, right: r.right, over: e.scrollWidth - e.clientWidth }; })"
)


@phone
async def test_root_chips_keep_their_width_and_the_strip_scrolls(
    page: Page, server: Harness, viewport: dict[str, int]
) -> None:
    """#448. `.chips button` kept the default `flex-shrink: 1`, so five roots
    were squeezed into the width and `nowrap` ran each label out past its pill
    and over the next one. Three assertions, because each alone passes a
    different half of the broken layout."""
    await _busy_list(page, server, viewport)
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
    three tabs fit. The counts are three digits so the strip is genuinely too
    narrow at the narrowest width, which the busy list's two digits are not."""
    await page.set_viewport_size({"width": 320, "height": 640})
    server.seed(stopped=[f"p{i:03d}" for i in range(120)])
    await page.goto(server.base)
    await expect(page.locator("[data-project]")).to_have_count(120, timeout=15_000)
    boxes = await page.get_by_role("tab").evaluate_all(_BOXES)
    for before, after in pairwise(boxes):
        assert before["right"] <= after["left"], f"tabs overlap: {before} and {after}"
    assert all(box["over"] <= 0 for box in boxes), f"a label outruns its tab: {boxes}"


# What a row's name measures. `natural` is the same text in a box as wide as it
# likes, so the line count it implies is the name's own and not a number the
# test had to assume; `atRow` is the text at the row's inner width.
_NAME = """el => {
  const row = el.closest('.row');
  const cs = getComputedStyle(row);
  const inner = row.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
  const lineHeight = parseFloat(getComputedStyle(el).lineHeight);
  const lines = (width) => {
    const clone = el.cloneNode(true);
    clone.style.position = 'absolute';
    clone.style.visibility = 'hidden';
    clone.style.flex = 'none';
    clone.style.width = width;
    document.body.append(clone);
    const count = clone.getBoundingClientRect().height / lineHeight;
    clone.remove();
    return Math.round(count);
  };
  const box = el.getBoundingClientRect();
  return {
    width: box.width, inner, lines: Math.round(box.height / lineHeight),
    natural: lines('max-content'), atRow: lines(inner + 'px'),
    row: row.getBoundingClientRect().height,
  };
}"""


@phone
@pytest.mark.parametrize("state", _STATES)
async def test_a_name_has_its_own_line_in_every_state(
    page: Page, server: Harness, viewport: dict[str, int], state: str
) -> None:
    """#449, and #179 again. A stopped row put the name, the root chip, the
    badge and Start on one line and the name took all of the squeeze: sixteen
    characters became six lines of two or three. The running-row guard checked
    one state at one width with no root chip, so it could not see it.

    The line count is compared with the name's own, and the width with the
    row's, because a name on one line that is 40px wide in a crushed box would
    pass the first alone."""
    busy = await _busy_list(page, server, viewport)
    row = page.locator(f'[data-project="{server.project(busy.sixteen[state])}"]')
    await expect(row).to_have_attribute("data-state", state)
    got = await row.locator(".row-name").evaluate(_NAME)
    assert got["lines"] == got["natural"] == 1, f"the {state} name wraps: {got}"
    assert got["width"] >= 0.6 * got["inner"], f"the {state} name is crushed: {got}"


@phone
async def test_no_name_on_the_busy_list_is_crushed(
    page: Page, server: Harness, viewport: dict[str, int]
) -> None:
    """#449 for all sixty rows rather than the four named ones: names from short
    to a full line, hyphens and underscores, each wrapping only as its own
    length makes it, never because something beside it took the room."""
    await _busy_list(page, server, viewport)
    for name in await page.locator(".row-name").all():
        got = await name.evaluate(_NAME)
        assert got["lines"] == got["atRow"], f"{await name.inner_text()!r} is crushed: {got}"


@phone
async def test_a_stopped_row_stays_shorter_than_a_running_one(
    page: Page, server: Harness, viewport: dict[str, int]
) -> None:
    """#449. The name on its own line must not turn the stopped row into the
    running one: the design keeps the asymmetry so forty rows stay scannable."""
    busy = await _busy_list(page, server, viewport)
    heights: dict[str, float] = {}
    for state in ("stopped", "running"):
        row = page.locator(f'[data-project="{server.project(busy.sixteen[state])}"]')
        await expect(row).to_have_attribute("data-state", state)
        box = await row.bounding_box()
        assert box is not None
        heights[state] = box["height"]
    assert heights["stopped"] < heights["running"], heights


@phone
async def test_the_widest_running_row_does_not_crush_its_name(
    page: Page, server: Harness, viewport: dict[str, int]
) -> None:
    """The #75 guard from `test_list.py`, on the busy list: a running row with
    no session link carries a badge and every control, and the name must still
    occupy one line without the page scrolling sideways."""
    busy = await _busy_list(page, server, viewport)
    row = page.locator(f'[data-project="{server.project(busy.widest)}"]')
    await expect(row.get_by_role("button", name="Open session")).to_be_visible()
    got = await row.locator(".row-name").evaluate(_NAME)
    assert got["lines"] == got["natural"] == 1, got
    overflow = await page.evaluate(
        "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )
    assert overflow <= 0, f"the page scrolls sideways by {overflow}px"


# -- #450: the type scale ------------------------------------------------------

_TYPE = """el => {
  const cs = getComputedStyle(el);
  return { size: parseFloat(cs.fontSize), weight: parseInt(cs.fontWeight, 10) };
}"""


@phone
async def test_the_type_scale_is_material_threes(
    page: Page, server: Harness, viewport: dict[str, int]
) -> None:
    """#450's decision: controls are label large (14px, weight 500 or 600),
    body and row names are body large (16px), meta is label medium (12 to
    13px), and the search input is never under 16px, because iOS Safari zooms
    on focus into anything smaller and the answer is not `maximum-scale=1`.
    Read from computed styles, so a rule overridden further down the cascade
    cannot hide behind the one that was edited."""
    busy = await _busy_list(page, server, viewport)
    stopped = page.locator(f'[data-project="{server.project(busy.sixteen["stopped"])}"]')
    running = page.locator(f'[data-project="{server.project(busy.sixteen["running"])}"]')

    controls = {
        "button": stopped.get_by_role("button", name="Start"),
        "tab": page.get_by_role("tab").first,
        "chip": page.locator("[data-roots]").get_by_role("button").first,
    }
    for label, control in controls.items():
        got = await control.evaluate(_TYPE)
        assert got["size"] == 14, f"a {label} computes to {got['size']}px, not 14"
        assert got["weight"] in (500, 600), f"a {label} has weight {got['weight']}"

    assert (await page.locator("body").evaluate(_TYPE))["size"] == 16
    assert (await stopped.locator(".row-name").evaluate(_TYPE))["size"] == 16
    assert (await page.locator("[data-search]").evaluate(_TYPE))["size"] >= 16
    meta = (await running.locator(".meta").evaluate(_TYPE))["size"]
    assert 12 <= meta <= 13, f"meta computes to {meta}px"

    # Never the zoom lock. Pinch zoom is how somebody with poor sight reads this.
    viewport_meta = await page.locator('meta[name="viewport"]').get_attribute("content")
    assert viewport_meta is not None
    assert "maximum-scale" not in viewport_meta
    assert "user-scalable" not in viewport_meta


@phone
async def test_every_tap_target_is_still_44px(
    page: Page, server: Harness, viewport: dict[str, int]
) -> None:
    """Shrinking the label must not shrink the target around it."""
    await _busy_list(page, server, viewport)
    targets = await page.locator("button:visible, .btn:visible, [data-search]").evaluate_all(
        "els => els.map(e => { const r = e.getBoundingClientRect();"
        " return { what: e.textContent.trim().slice(0, 20) || e.getAttribute('aria-label'),"
        " width: r.width, height: r.height }; })"
    )
    assert targets, "nothing to measure"
    small = [t for t in targets if t["height"] < 43.99 or t["width"] < 43.99]
    assert not small, f"tap targets under 44px: {small}"
