"""The list as a phone holds it: what only a measured box can see (Phase 24)."""

from __future__ import annotations

from itertools import pairwise

import pytest
from playwright.async_api import Page, expect

from .conftest import Harness, e2e_name

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


# What a row's name measures. The "natural" height is the same text in a box as
# wide as it likes, so the line count it implies is the name's own and not a
# number the test had to assume.
_NAME = """el => {
  const row = el.closest('.row');
  const cs = getComputedStyle(row);
  const inner = row.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
  const lineHeight = parseFloat(getComputedStyle(el).lineHeight);
  const clone = el.cloneNode(true);
  clone.style.position = 'absolute';
  clone.style.visibility = 'hidden';
  clone.style.width = 'max-content';
  document.body.append(clone);
  const natural = clone.getBoundingClientRect().height / lineHeight;
  clone.remove();
  const box = el.getBoundingClientRect();
  return {
    width: box.width, inner, lines: box.height / lineHeight, natural,
    row: row.getBoundingClientRect().height,
  };
}"""


def _sixteen(tag: str) -> str:
    """A folder name 16 characters long once the harness prefix is on it, which
    is what the ticket's `a-sixteen-letter` is and what the phone showed
    crushed. The prefix carries the test run's pid, so its length varies."""
    room = 16 - len(e2e_name(""))
    return f"{tag}-sixteen-letter"[:room]


async def _sixteen_letter_rows(server: Harness, page: Page) -> dict[str, dict[str, float]]:
    """One row per state, each named to 16 characters, among five roots so the
    root chip is drawn: the conditions the guard before #449 never had."""
    names = {state: _sixteen(state) for state in ("stopped", "running", "stale", "detached")}
    filler = [f"p{i:02d}" for i in range(8)]
    server.seed(
        running=[names["running"]],
        stopped=[names["stopped"], *filler],
        stale=[names["stale"]],
        detached=[names["detached"]],
        stopped_in=dict.fromkeys(LONG_ROOTS, filler),
    )
    await page.goto(server.base)
    await expect(page.locator("[data-project]")).to_have_count(
        4 + 8 + 8 * len(LONG_ROOTS), timeout=15_000
    )
    measured = {}
    for state, name in names.items():
        row = page.locator(f'[data-project="{server.project(name)}"]')
        await expect(row).to_have_attribute("data-state", state)
        measured[state] = await row.locator(".row-name").evaluate(_NAME)
    return measured


@pytest.mark.parametrize("state", ["stopped", "running", "stale", "detached"])
async def test_a_name_has_its_own_line_in_every_state(
    page: Page, server: Harness, state: str
) -> None:
    """#449, and #179 again. A stopped row put the name, the root chip, the
    badge and Start on one line and the name took all of the squeeze: sixteen
    characters became six lines of two or three. The running-row guard checked
    one state at one width with no root chip, so it could not see it.

    The line count is compared with the name's own, and the width with the
    row's, because a name on one line that is 40px wide in a crushed box would
    pass the first alone."""
    await page.set_viewport_size({"width": 360, "height": 740})
    got = (await _sixteen_letter_rows(server, page))[state]
    assert round(got["lines"]) == round(got["natural"]) == 1, f"the {state} name wraps: {got}"
    assert got["width"] >= 0.6 * got["inner"], f"the {state} name is crushed: {got}"


async def test_a_stopped_row_stays_shorter_than_a_running_one(
    page: Page, server: Harness
) -> None:
    """#449. The name on its own line must not turn the stopped row into the
    running one: the design keeps the asymmetry so forty rows stay scannable."""
    await page.set_viewport_size({"width": 360, "height": 740})
    got = await _sixteen_letter_rows(server, page)
    assert got["stopped"]["row"] < got["running"]["row"], got


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
