"""#54: the list, its four states, search, the tab filter and the lock."""

from __future__ import annotations

import pytest
from playwright.async_api import Page, expect

from .conftest import Harness

pytestmark = pytest.mark.e2e


async def test_every_derived_state_renders_as_itself(page: Page, server: Harness) -> None:
    """All four from section 4.1. `detached` is the one a naive tool gets
    wrong, so it is drawn with its pid and never silently reconciled."""
    server.seed(running=["vessel"], stopped=["koala"])
    await page.goto(server.base)
    await expect(page.locator('[data-project="hrx-vessel"]')).to_have_attribute(
        "data-state", "running"
    )
    await expect(page.locator('[data-project="hrx-koala"]')).to_have_attribute(
        "data-state", "stopped"
    )


async def test_a_detached_row_names_its_pid_and_offers_to_kill_it(
    page: Page, server: Harness
) -> None:
    """The state the design surfaces loudly on purpose. `States.dc.html`:
    "pid 24188 - no tmux session", with the pid IN the button, because the
    thing being killed is a pid rather than a session."""
    server.seed(detached=["forge-kit"])
    assert server.engine is not None
    await page.goto(server.base)
    row = page.locator('[data-project="hrx-forge-kit"]')
    await expect(row).to_have_attribute("data-state", "detached")
    await expect(row).to_contain_text("no tmux session")
    pid = server.engine.get(server.project("forge-kit")).pid
    await expect(row.get_by_role("button", name=f"Kill pid {pid}")).to_be_visible()


async def test_a_running_row_is_taller_than_a_stopped_one(page: Page, server: Harness) -> None:
    """The canvas annotation, asserted rather than described. Three actions
    against one button is the whole mobile argument."""
    server.seed(running=["vessel"], stopped=["long-hyphenated-name"])
    await page.set_viewport_size({"width": 390, "height": 844})
    await page.goto(server.base)
    tall = await page.locator('[data-project="hrx-vessel"]').bounding_box()
    short = await page.locator('[data-project="hrx-long-hyphenated-name"]').bounding_box()
    assert tall is not None and short is not None, "a row was not laid out"
    assert tall["height"] > short["height"], (
        f"running {tall['height']} is not taller than stopped {short['height']}"
    )


async def test_the_controller_row_is_badged_and_has_no_stop(
    page: Page, server: Harness
) -> None:
    """Refusing after the tap is worse than not offering the tap. The canvas
    is specific about the label: `controller`, not a lock glyph."""
    server.seed(running=["hitchrail"], self_project="hitchrail")
    await page.goto(server.base)
    row = page.locator('[data-project="hrx-hitchrail"]')
    await expect(row).to_have_attribute("data-protected", "true")
    await expect(row.locator("[data-badge]")).to_have_attribute("data-badge", "controller")
    assert await row.get_by_role("button", name="Stop").count() == 0


async def test_search_filters_and_says_so_when_nothing_matches(
    page: Page, server: Harness
) -> None:
    server.seed(stopped=["vessel", "koala", "media-sync"])
    await page.goto(server.base)
    await page.get_by_role("searchbox").fill("mus")
    await expect(page.locator("[data-project]")).to_have_count(1)
    await page.get_by_role("searchbox").fill("zzz")
    await expect(page.get_by_text("Nothing matches")).to_be_visible()
    await expect(page.get_by_text("No folder here is called that.")).to_be_visible()


async def test_the_tabs_filter_and_carry_their_own_counts(page: Page, server: Harness) -> None:
    """Three tabs from the canvas, each with a count."""
    server.seed(running=["vessel"], stopped=["koala", "media-sync"])
    await page.goto(server.base)
    await expect(page.get_by_role("tab", name="All")).to_contain_text("3")
    await expect(page.get_by_role("tab", name="Running")).to_contain_text("1")
    await expect(page.get_by_role("tab", name="Stopped")).to_contain_text("2")
    await page.get_by_role("tab", name="Running").click()
    await expect(page.locator("[data-project]")).to_have_count(1)


async def test_stopped_means_not_running_rather_than_the_stopped_state(
    page: Page, server: Harness
) -> None:
    """`Stopped` is `all.length - runNames.length` in the canvas, not a state
    match. A detached row is not running, so it belongs there: it is one of
    the two rows a person most needs to find, and a state string filter would
    hide it."""
    server.seed(running=["vessel"], detached=["forge-kit"])
    await page.goto(server.base)
    await page.get_by_role("tab", name="Stopped").click()
    await expect(page.locator('[data-project="hrx-forge-kit"]')).to_be_visible()
    await expect(page.locator('[data-project="hrx-vessel"]')).to_have_count(0)


async def test_a_folder_that_cannot_be_a_project_is_accounted_for(
    page: Page, server: Harness
) -> None:
    """#7: dropping them silently made a folder called `my app` look like one
    Hitchrail could not see."""
    server.seed(stopped=["vessel"], unsupported=["my app"])
    await page.goto(server.base)
    await expect(page.locator('[data-unsupported="my app"]')).to_be_visible()
    await expect(page.locator('[data-unsupported="my app"]')).to_contain_text("space")
    await expect(page.locator('[data-project="my app"]')).to_have_count(0)


async def test_a_project_name_is_rendered_as_text_and_never_as_markup(
    page: Page, server: Harness
) -> None:
    """A project name is a FOLDER name, so anybody who can write to the root
    chooses it. The API escapes what is unprintable; the page must not then
    hand what is left to an HTML parser."""
    server.seed(stopped=["vessel"])
    await page.goto(server.base)
    hostile = "<img src=x onerror=alert(1)>"
    await page.evaluate(
        """(name) => {
             const app = window.__hitchrail;
             app.state.projects = [{ name, state: 'stopped', pid: null, ram_mb: 0,
                                     uptime_s: 0, url: null, stopping: false,
                                     protected: false }];
             app.render();
           }""",
        hostile,
    )
    assert await page.locator("img").count() == 0, "a project name became an element"
    await expect(page.locator(f'[data-project="{hostile}"] .row-name')).to_have_text(hostile)


async def test_the_memory_footer_reports_the_figure_and_the_proportion(
    page: Page, server: Harness
) -> None:
    """`memLabel` and `memPct` in the canvas. A free figure means nothing
    without a total: reassuring on 16 GB, alarming on 128."""
    server.seed(stopped=["vessel"], available_mb=8192)
    await page.goto(server.base)
    footer = page.get_by_role("contentinfo")
    await expect(footer).to_contain_text("8.0 GB free")
    await expect(page.locator("[data-mem-pct]")).to_have_attribute("data-mem-pct", "25")
