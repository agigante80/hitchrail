"""#56: starting, the two memory refusals, the drawer and the new folder sheet."""

from __future__ import annotations

import pytest
from playwright.async_api import Page, expect

from .conftest import Harness

pytestmark = pytest.mark.e2e


async def test_a_start_shows_the_session_without_a_reload(page: Page, server: Harness) -> None:
    server.seed(stopped=["long-hyphenated-name"])
    await page.goto(server.base)
    row = page.locator(f'[data-project="{server.project("long-hyphenated-name")}"]')
    await expect(row).to_be_visible()
    await row.get_by_role("button", name="Start").click()
    await expect(row).to_have_attribute("data-state", "running", timeout=20_000)


async def test_the_soft_floor_asks_and_can_be_overridden(page: Page, server: Harness) -> None:
    """`ram_soft` is a confirmation gate. The sheet states what would be LEFT
    rather than what is needed, because that is the number the decision turns
    on."""
    server.seed(stopped=["vessel"], available_mb=3600)
    await page.goto(server.base)
    row = page.locator(f'[data-project="{server.project("vessel")}"]')
    await expect(row).to_be_visible()
    await row.get_by_role("button", name="Start").click()

    dialog = page.locator("[data-dialog]")
    await expect(dialog).to_contain_text("Tight on memory")
    await expect(dialog.get_by_role("button", name="Cancel")).to_be_visible()
    await dialog.get_by_role("button", name="Start anyway").click()
    await expect(row).to_have_attribute("data-state", "running", timeout=20_000)


async def test_the_hard_floor_refuses_and_offers_a_way_out(page: Page, server: Harness) -> None:
    """No `Start anyway` anywhere on this screen: 507 is not overridable, and
    a control that cannot work is worse than no control."""
    server.seed(running=["media-sync"], stopped=["vessel"], available_mb=1200)
    await page.goto(server.base)
    row = page.locator(f'[data-project="{server.project("vessel")}"]')
    await expect(row).to_be_visible()
    await row.get_by_role("button", name="Start").click()

    dialog = page.locator("[data-dialog]")
    await expect(dialog).to_contain_text("Not enough memory")
    assert await dialog.get_by_role("button", name="Start anyway").count() == 0
    await expect(dialog).to_contain_text(server.project("media-sync"))
    await expect(
        dialog.get_by_role("button", name=f"Stop {server.project('media-sync')}")
    ).to_be_visible()


async def test_the_hard_floor_never_offers_to_stop_the_controller(
    page: Page, server: Harness
) -> None:
    """The way out must not be a door into a 423. The controller is excluded
    from the candidates, not filtered after the fact."""
    server.seed(
        running=["hitchrail"], stopped=["vessel"], self_project="hitchrail", available_mb=1200
    )
    await page.goto(server.base)
    row = page.locator(f'[data-project="{server.project("vessel")}"]')
    await expect(row).to_be_visible()
    await row.get_by_role("button", name="Start").click()

    dialog = page.locator("[data-dialog]")
    await expect(dialog).to_contain_text("Not enough memory")
    assert await dialog.get_by_role("button", name="Stop hrx-hitchrail").count() == 0


async def test_a_start_that_dies_says_so_and_offers_the_output(
    page: Page, server: Harness
) -> None:
    """ "Started, then exited" is a sentence somebody can act on. "Failed to
    start" is not."""
    server.seed(stopped=["koala"], agent_exits_immediately=True)
    await page.goto(server.base)
    row = page.locator(f'[data-project="{server.project("koala")}"]')
    await expect(row).to_be_visible()
    await row.get_by_role("button", name="Start").click()

    # Wait for the dialog to OPEN before asserting on its text. A closed
    # `<dialog>` is display:none, so `to_contain_text` on it reports an empty
    # string and says nothing about why: on CI this failed with "Actual value:
    # (blank)" and no indication that the request was simply still in flight.
    #
    # The generous timeout is the engine's, not this test's. `start` polls for
    # `start_grace` seconds before it can report a dead start, and every poll
    # spawns `ps` and `tmux`, which on a shared runner is far slower than here.
    dialog = page.locator("[data-dialog]")
    await expect(dialog).to_be_visible(timeout=45_000)
    await expect(dialog).to_contain_text("died")
    await expect(dialog).to_contain_text("exited almost immediately")
    await dialog.get_by_role("button", name="Read what it printed").click()

    # Deliberately weak, and #66 is why. When the agent exits tmux destroys the
    # pane, so `_safe_capture` runs after the grace window with nothing left to
    # read and `output` arrives empty. The interface says so honestly, which is
    # the correct behaviour for an empty capture and a useless answer for the
    # person who wanted to know why it died. Strengthen this to assert the
    # shim's own line once #66 captures during the window.
    printed = await dialog.locator("pre").inner_text()
    assert printed.strip(), "the control was offered with nothing behind it at all"


async def test_the_log_drawer_shows_the_pane_tail(page: Page, server: Harness) -> None:
    server.seed(running=["vessel"])
    await page.goto(server.base)
    row = page.locator(f'[data-project="{server.project("vessel")}"]')
    await expect(row).to_be_visible()
    await row.get_by_role("button", name="Open").click()

    dialog = page.locator("[data-dialog]")
    await expect(dialog).to_contain_text("last 40 lines of the pane")
    await expect(dialog.locator("pre")).to_contain_text("hitchrail-shim: started")


async def test_the_new_folder_sheet_creates(page: Page, server: Harness) -> None:
    server.seed(stopped=["vessel"])
    await page.goto(server.base)
    await page.get_by_role("button", name="New").click()
    await page.get_by_label("Folder name").fill("new-thing")
    await page.get_by_role("button", name="Create").click()
    await expect(page.locator('[data-project="new-thing"]')).to_be_visible(timeout=15_000)


async def test_a_refused_creation_reports_it_and_leaves_nothing_on_disk(
    page: Page, server: Harness
) -> None:
    """ "A refused creation leaves nothing on disk" is a Phase 1 exit criterion,
    and the interface is now a second way to reach that path."""
    server.seed(stopped=["vessel"])
    await page.goto(server.base)
    await page.get_by_role("button", name="New").click()
    await page.get_by_label("Folder name").fill("../escape")
    await page.get_by_role("button", name="Create").click()

    await expect(page.locator("[data-dialog]")).to_contain_text("name")
    assert not (server.root.parent / "escape").exists(), "a refused creation escaped"
    assert not (server.root / "escape").exists()


async def test_the_sheet_does_not_reimplement_the_name_rule(
    page: Page, server: Harness
) -> None:
    """The API decides what a name is. A client side copy of that rule drifts
    from it, and the copy that drifts is the one a person sees, so the sheet
    must SEND a bad name and report what came back."""
    server.seed(stopped=["vessel"])
    await page.goto(server.base)
    await page.get_by_role("button", name="New").click()
    await page.get_by_label("Folder name").fill("has a space")
    await page.get_by_role("button", name="Create").click()
    # The message is the server's, not one the page invented.
    await expect(page.locator("[data-dialog]")).to_contain_text("space")
