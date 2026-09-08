"""#56: starting, the two memory refusals, the drawer and the new folder sheet."""

from __future__ import annotations

import pytest
from playwright.async_api import Page, expect

from support import DEFAULT_LABEL

from .conftest import Harness, e2e_name

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
    assert await dialog.get_by_role("button", name=f"Stop {e2e_name('hitchrail')}").count() == 0


async def test_a_start_that_dies_says_so_and_offers_the_output(
    page: Page, server: Harness
) -> None:
    """ "Started, then exited" is a sentence somebody can act on. "Failed to
    start" is not.

    **Restored 2026-09-07, #67, after the weakened form was measured.** From
    2026-08-28 this asserted only `not_to_have_attribute("data-state",
    "running")`, with a comment claiming it "still fails if the dead start
    reports nothing at all, which is the thing #56 was written to notice".

    That claim was false. The row is already `stopped` when the button is
    clicked, so the assertion was satisfied before the start had done anything
    and the call took 0.26s where this one takes 8.65. Falsified twice: with
    `_dead_start_output` returning "" it passed, and with `Engine.start` replaced
    by `return self.get(name)`, so that nothing was ever started, it passed
    again. A weakened assertion that still costs a browser is worse than none,
    because it reads as coverage.
    """
    server.seed(stopped=["koala"], agent_exits_immediately=True)
    await page.goto(server.base)
    row = page.locator(f'[data-project="{server.project("koala")}"]')
    await expect(row).to_be_visible()
    await row.get_by_role("button", name="Start").click()

    # **Assert the PREMISE before the behaviour (#67).** This test needs the
    # agent to be gone before the engine's first look. If it is not, the start
    # legitimately SUCCEEDS, no refusal is produced, and the dialog below can
    # never open: the test then spends its whole timeout on an event that cannot
    # happen and fails as "Locator expected to be visible", which says nothing
    # about why.
    #
    # That is exactly what happened on CI from 2026-08-28 to 2026-09-07 and cost
    # a ticket, two wrong hypotheses and a CI round trip to name. The fixture now
    # uses `/bin/sh` so it is fast enough, and this races the two outcomes so
    # that if it ever is not, the failure says so in one line.
    dialog = page.locator("[data-dialog]")
    running = page.locator(f'[data-project="{server.project("koala")}"][data-state="running"]')

    # **Capture which outcome won, rather than re-querying (round 1 review).**
    # `count()` after the wait is a fresh query a round trip later, and
    # `remain-on-exit` keeps the pane, so a shim that outlived the first poll
    # gives exactly the transition `running` to `stale`. If that lands between
    # the two calls, the premise assertion passes and the test then spends 45
    # seconds on a dialog that can never open, which is the opaque failure this
    # was written to remove.
    #
    # `.or_().first` is `nth(0)` over the union in DOM ORDER, not in
    # resolution order, so it does not say which one appeared. The dialog is
    # after the list in `index.html`, so `first` is the row today; moving the
    # dialog above the list would make `first` always the dialog and quietly
    # restore the 45 second timeout. Both halves are therefore read explicitly.
    await dialog.or_(running).first.wait_for(state="visible", timeout=45_000)
    started_running = await running.count() > 0
    dialog_open = await dialog.is_visible()
    assert not (started_running and not dialog_open), (
        "the fake agent outlived the engine's first poll, so the start SUCCEEDED "
        "and this test never exercised a dead start. That is #67: the shim must "
        "exit before `_await_running` calls `get()`, which is why it is a `sh` "
        "script and not a Python one."
    )

    # A closed `<dialog>` is display:none, so `to_contain_text` on it reports an
    # empty string and says nothing about why: on CI this failed with "Actual
    # value: (blank)" and no indication that the request was still in flight.
    #
    # The generous timeout is the engine's, not this test's. `start` polls for
    # `start_grace` seconds before it can report a dead start, and every poll
    # spawns `ps` and `tmux`, which on a shared runner is far slower than here.
    await expect(dialog).to_be_visible(timeout=45_000)
    await expect(dialog).to_contain_text("died")
    await expect(dialog).to_contain_text("exited almost immediately")
    await dialog.get_by_role("button", name="Read what it printed").click()

    # #66 landed, so this asserts what the agent actually printed rather than
    # only that something is there. `new_session` keeps the pane alive past
    # its process, so the capture has something to find: without it the pane,
    # the window, the session and the tmux server are gone inside fifty
    # milliseconds and this control has nothing behind it.
    printed = await dialog.locator("pre").inner_text()
    assert "hitchrail-shim" in printed, printed
    assert "status 3" in printed, (
        f"the exit status is the diagnostic and it was lost: {printed!r}"
    )


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
    # `server.project` would add the run's collision prefix, and this folder
    # was typed into the interface rather than seeded, so it is literally
    # `new-thing`. What it gains is the ROOT LABEL, which the page supplies on
    # the person's behalf because they typed a folder name, not an identifier.
    await expect(page.locator(f'[data-project="{DEFAULT_LABEL}~new-thing"]')).to_be_visible(
        timeout=15_000
    )


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
