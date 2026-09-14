"""#154 and #238: the settings page, on a real browser at a phone width.

The hermetic tier proves the routes. What only this tier can prove is the
page: that the perimeter is text and not a disabled input, that a checkbox
row is a 44px target at 390px, that hiding a root removes its rows from the
list without ending its agent, and that a stop wait the SERVER chose is the
one the wait dialog actually keeps, which is the bug the ticket opened with.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from playwright.async_api import Page, expect

from .conftest import Harness

pytestmark = pytest.mark.e2e

TWO_ROOTS = {"personal": ["vessel"]}


async def test_the_page_holds_at_a_phone_width_and_shows_the_perimeter_as_text(
    page: Page, server: Harness
) -> None:
    server.seed(running=["vessel"], also_in=TWO_ROOTS)
    await page.goto(server.base)
    await page.get_by_role("link", name="settings").click()
    await expect(page.locator("[data-settings]")).to_have_attribute("data-loaded", "")

    # No horizontal scroll: the page fits the viewport it was designed for.
    assert await page.evaluate(
        "() => document.documentElement.scrollWidth <= document.documentElement.clientWidth"
    )
    # Every root is a row with a checkbox, and the row is the tap target.
    rows = page.locator("[data-roots] li")
    await expect(rows).to_have_count(2)
    for i in range(2):
        box = await rows.nth(i).locator("label").bounding_box()
        assert box is not None and box["height"] >= 44, box
    # The perimeter: text with a source, and not one input among it.
    facts = page.locator("[data-facts]")
    await expect(facts.locator('[data-fact="host"] .settings-value')).to_have_text("127.0.0.1")
    await expect(facts.locator('[data-fact="host"] .settings-source')).to_have_text(
        "the default"
    )
    assert await facts.locator("input, select, textarea, button").count() == 0
    # The token is its source alone; on a loopback bind there is none, and
    # the page says that rather than showing an empty value.
    await expect(facts.locator('[data-fact="token"] .settings-value')).to_have_text("")
    await expect(facts.locator('[data-fact="token"] .settings-source')).to_have_text(
        "none: loopback only"
    )


async def test_hiding_a_root_removes_its_rows_and_leaves_its_agent_running(
    page: Page, server: Harness, tmp_path: Path
) -> None:
    """The unhappy path #154 names, on the machine rather than on a fake: the
    root toggled off holds a RUNNING project, and after the toggle its agent
    is still alive and the list simply no longer shows it. Then a reload,
    and then a restart, because "persists" means both."""
    server.seed(running=["vessel"], also_in=TWO_ROOTS, state_path=tmp_path / "s" / "state.toml")
    await page.goto(server.base)
    personal = page.locator(f'[data-project="{server.project("vessel", "personal")}"]')
    await expect(personal).to_have_attribute("data-state", "running", timeout=15_000)

    await page.goto(f"{server.base}/settings")
    box = page.locator('[data-root-toggle="personal"]')
    await expect(box).to_be_checked()
    await box.click()
    await expect(box).not_to_be_checked()
    await expect(
        page.locator('[data-roots] li[data-label="personal"] .settings-source')
    ).to_have_text("hidden here")

    await page.goto(server.base)
    work = page.locator(f'[data-project="{server.project("vessel")}"]')
    await expect(work).to_be_visible()
    await expect(personal).to_have_count(0)
    # One root shown means no chips, as one root configured never had them.
    assert await page.locator("[data-roots] button").count() == 0
    assert server.is_running("vessel", "personal"), "hiding the root ended its agent"

    await page.reload()
    await expect(work).to_be_visible()
    await expect(personal).to_have_count(0)

    server.restart()
    await page.goto(server.base)
    await expect(work).to_be_visible()
    await expect(personal).to_have_count(0)
    assert server.is_running("vessel", "personal")

    # And back, from the page.
    await page.goto(f"{server.base}/settings")
    await page.locator('[data-root-toggle="personal"]').click()
    await page.goto(server.base)
    await expect(personal).to_have_attribute("data-state", "running", timeout=15_000)


async def test_every_root_hidden_says_so_rather_than_no_folder(
    page: Page, server: Harness
) -> None:
    server.seed(stopped=["vessel"])
    await page.goto(f"{server.base}/settings")
    await page.locator('[data-root-toggle="main"]').click()
    await expect(page.locator('[data-root-toggle="main"]')).not_to_be_checked()
    await page.goto(server.base)
    await expect(page.locator("[data-empty-reason]")).to_contain_text(
        "Every root is hidden (main)"
    )


async def test_the_wait_dialog_keeps_the_servers_stop_timeout(
    page: Page, server: Harness
) -> None:
    """The bug #238 opened with: the page gave up at thirty seconds whatever
    the server was told. Here the server waits two seconds and the page is
    NOT told through the test seam, so what the dialog does after two
    seconds is what the server's figure did."""
    server.seed(running=["vessel"], ignores_graceful_stop=True, stop_timeout=2)
    await page.goto(server.base)
    row = page.locator(f'[data-project="{server.project("vessel")}"]')
    await expect(row).to_have_attribute("data-state", "running", timeout=15_000)
    await row.get_by_role("button", name="Stop").click()
    await page.locator("[data-dialog]").get_by_role("button", name="Stop", exact=True).click()
    await expect(page.locator("[data-dialog]")).to_contain_text(
        f"No answer from {server.project('vessel')}", timeout=8_000
    )


async def test_the_stop_wait_is_edited_here_and_a_flag_pins_it(
    page: Page, server: Harness, tmp_path: Path
) -> None:
    server.seed(stopped=["vessel"], state_path=tmp_path / "s" / "state.toml")
    await page.goto(f"{server.base}/settings")
    field = page.locator("[data-stop-timeout]")
    await expect(field).to_have_value("30")
    await field.fill("45")
    await page.locator("[data-stop-save]").click()
    await expect(page.locator("[data-stop-source]")).to_contain_text("Currently 45s, set here")
    server.restart()
    await page.reload()
    await expect(page.locator("[data-stop-timeout]")).to_have_value("45")
    # The page reads the server's figure, not its own memory of it: once the
    # listing has landed, the wait it would keep is the one set above.
    await page.goto(server.base)
    await expect(page.locator(f'[data-project="{server.project("vessel")}"]')).to_be_visible()
    patience = await page.evaluate("() => window.__hitchrail.stopTimeoutMs()")
    assert patience == 45_000


async def test_a_flag_pins_the_stop_wait_as_text(page: Page, server: Harness) -> None:
    server.seed(stopped=["vessel"], stop_timeout=60, pinned_stop_timeout=True)
    await page.goto(f"{server.base}/settings")
    await expect(page.locator("[data-stop-source]")).to_contain_text(
        "60s, from the command line"
    )
    assert await page.locator("[data-stop-timeout]").is_hidden()
    assert await page.locator("[data-stop-save]").is_hidden()
