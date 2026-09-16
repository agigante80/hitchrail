"""#56: starting, the two memory refusals, the drawer and the new folder sheet."""

from __future__ import annotations

import pytest
from playwright.async_api import Page, ViewportSize, expect
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

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

    # **One wait, and the diagnosis after it (round 2 review).**
    #
    # Round 1 flagged that `count()` after a `wait_for` is a fresh query a round
    # trip later. My fix read BOTH halves after the same wait, which did not
    # close the race and made the assertion strictly weaker: it had failed on
    # `running.count() > 0` alone, and then failed only when the row was running
    # AND no dialog had opened. `remain-on-exit` takes the row `running` to
    # `stale`, so the very transition the race produces made the premise pass.
    # The comment claimed it had been strengthened.
    #
    # There is no race here because there is only one wait. The row is read
    # after the dialog has definitively failed to appear, so what it says is
    # a diagnosis rather than a second guess at who won.
    #
    # `or_().first` is gone with it: it resolves in DOM ORDER, not in the order
    # things appeared, so it never could say which outcome arrived.
    try:
        await dialog.wait_for(state="visible", timeout=45_000)
    except PlaywrightTimeoutError:
        state = await row.get_attribute("data-state")
        pytest.fail(
            f"no refusal dialog opened and the row reads data-state={state!r}. The "
            f"fake agent outlived the engine's first poll, so the start SUCCEEDED "
            f"and this test never exercised a dead start. That is #67: the shim "
            f"must exit before `_await_running` calls `get()`, which is why it is "
            f"a `sh` script and not a Python one."
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
    await row.get_by_role("button", name="Logs").click()

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
    await page.get_by_label("Folder name").fill("has  two")
    await page.get_by_role("button", name="Create").click()
    # The message is the server's, not one the page invented.
    await expect(page.locator("[data-dialog]")).to_contain_text("two spaces in a row")


# -- #168: the pane view, sized for where it is ------------------------------

PHONE = ViewportSize(width=390, height=844)
DESKTOP = ViewportSize(width=1280, height=800)


async def _dialog_width(page: Page) -> float:
    width = await page.locator("[data-dialog]").evaluate("d => d.getBoundingClientRect().width")
    return float(width)


async def test_the_pane_view_is_wider_on_a_desktop_and_fits_eighty_columns(
    page: Page, server: Harness
) -> None:
    """#168. A 420px column of terminal output on a 1280px screen, with most
    of the window empty, and a pane drawn for an 80 column terminal folded
    into it. Sized in `ch` against the pane's own font, because the useful
    width is a column count and not a pixel count."""
    server.seed(running=["vessel"])
    await page.set_viewport_size(DESKTOP)
    await page.goto(server.base)
    row = page.locator(f'[data-project="{server.project("vessel")}"]')
    await expect(row).to_be_visible()
    await row.get_by_role("button", name="Logs").click()
    dialog = page.locator("[data-dialog]")
    await expect(dialog.locator("pre")).to_contain_text("hitchrail-shim: started")

    assert await _dialog_width(page) > 560, "the pane view is still the phone's 420px column"
    # Eighty columns on one line: the text occupies one line box, not two.
    # Counted from the range's client rects, which is what a wrap produces
    # more of; a height comparison would have to know the pane's padding.
    line_boxes = await dialog.locator("pre").evaluate(
        """(pre) => { pre.textContent = 'x'.repeat(80);
                    const range = document.createRange();
                    range.selectNodeContents(pre);
                    return range.getClientRects().length; }"""
    )
    assert line_boxes == 1, f"an 80 column line took {line_boxes} line boxes on the desktop"


async def test_the_pane_view_is_unchanged_on_a_phone(page: Page, server: Harness) -> None:
    server.seed(running=["vessel"])
    await page.set_viewport_size(PHONE)
    await page.goto(server.base)
    row = page.locator(f'[data-project="{server.project("vessel")}"]')
    await expect(row).to_be_visible()
    await row.get_by_role("button", name="Logs").click()
    await expect(page.locator("[data-dialog] pre")).to_be_visible()
    assert await _dialog_width(page) <= 390 * 0.92 + 1


async def test_the_other_dialogs_keep_their_size_at_both_widths(
    page: Page, server: Harness
) -> None:
    """The pane view and the stop confirmation are the same `<dialog>`, reused
    because the stop sequence escalates within it. Widening has to be a
    modifier the pane view sets, or the confirmation becomes a large empty
    box; this is the measurement that stops the shared rule being edited."""
    server.seed(running=["vessel"])
    for viewport, cap in ((PHONE, 390 * 0.92), (DESKTOP, 420)):
        await page.set_viewport_size(viewport)
        await page.goto(server.base)
        row = page.locator(f'[data-project="{server.project("vessel")}"]')
        await expect(row).to_be_visible()
        await row.get_by_role("button", name="Stop").click()
        await expect(page.locator("[data-dialog]")).to_contain_text("Stop ")
        assert await _dialog_width(page) <= cap + 1, viewport
        await page.locator("[data-dialog]").get_by_role("button", name="Cancel").click()


# -- #151: the logs page --------------------------------------------------------


async def test_the_drawer_opens_the_same_tail_in_a_tab(page: Page, server: Harness) -> None:
    """#151. A URL is what a popup and a docked panel are approximations of:
    a bookmark, a browser tab, and open-in-new-tab from the drawer, all from
    one route. The drawer stays for the common case."""
    server.seed(running=["vessel"])
    await page.goto(server.base)
    row = page.locator(f'[data-project="{server.project("vessel")}"]')
    await expect(row).to_be_visible()
    await row.get_by_role("button", name="Logs").click()
    link = page.locator("[data-dialog]").get_by_role("link", name="Open in a tab")
    await expect(link).to_have_attribute("href", f"/logs/{server.project('vessel')}")

    async with page.context.expect_page() as opened:
        await link.click()
    tab = await opened.value
    await expect(tab.locator("[data-pane]")).to_contain_text(
        "hitchrail-shim: started", timeout=15_000
    )
    await expect(tab.locator("[data-title]")).to_have_text(server.project("vessel"))
    await expect(page.locator("[data-dialog]")).to_be_visible()  # the drawer is still there


async def test_two_tabs_refresh_independently(page: Page, server: Harness) -> None:
    server.seed(running=["vessel", "koala"])
    await page.goto(server.base)
    await expect(page.locator("[data-project]")).to_have_count(2)
    one = await page.context.new_page()
    two = await page.context.new_page()
    await one.goto(f"{server.base}/logs/{server.project('vessel')}")
    await two.goto(f"{server.base}/logs/{server.project('koala')}")
    await expect(one.locator("[data-pane]")).to_contain_text(
        "hitchrail-shim: started", timeout=15_000
    )
    await expect(two.locator("[data-pane]")).to_contain_text(
        "hitchrail-shim: started", timeout=15_000
    )
    await expect(one.locator("[data-title]")).to_have_text(server.project("vessel"))
    await expect(two.locator("[data-title]")).to_have_text(server.project("koala"))
    # And the list in the first tab is still the list.
    await expect(page.locator("[data-project]")).to_have_count(2)


async def test_the_tab_says_so_when_the_session_ends_under_it(
    page: Page, server: Harness
) -> None:
    """A stale tail shown as if live is the lie the drawer already refuses.
    The session is killed; within a poll the tab says it is not running and
    dims the text it still shows, rather than pretending nothing changed."""
    server.seed(running=["vessel"])
    await page.goto(f"{server.base}/logs/{server.project('vessel')}")
    await expect(page.locator("[data-pane]")).to_contain_text(
        "hitchrail-shim: started", timeout=15_000
    )
    server.kill("vessel")
    await expect(page.locator("[data-note]")).to_contain_text("is not running", timeout=15_000)


async def test_the_tab_reports_an_unreadable_pane_and_never_an_empty_one(
    page: Page, server: Harness
) -> None:
    """The honest refusal rule: "cannot read" and "printed nothing" are
    different answers, and the page must give the first when the pane cannot
    be read. The harness cannot break tmux without breaking it for real, so
    the API is intercepted with the 503 the server sends when it cannot."""
    server.seed(running=["vessel"])
    await page.goto(f"{server.base}/logs/{server.project('vessel')}")
    pane = page.locator("[data-pane]")
    await expect(pane).to_contain_text("hitchrail-shim: started", timeout=15_000)

    await page.route(
        "**/api/sessions/**/logs*",
        lambda route: route.fulfill(
            status=503,
            content_type="application/json",
            body='{"code": "machine_unreadable", "message": "tmux could not be read"}',
        ),
    )
    await page.get_by_role("button", name="Refresh").click()
    await expect(page.locator("[data-note]")).to_contain_text("Cannot read the pane")
    await expect(pane).not_to_have_text("The pane has printed nothing yet.")
    await expect(pane).to_have_attribute("data-stale", "")


async def test_the_tab_sends_a_browser_whose_token_stopped_working_to_the_grant_flow(
    page: Page, server: Harness
) -> None:
    """A token revoked while the tab is open: the next poll is refused, and
    the page goes to the grant flow rather than sitting on a stale tail or
    landing on a raw JSON 401. Served fresh, the page is behind the token
    exactly as `/` is, which the token tier asserts."""
    server.seed(running=["vessel"])
    await page.goto(f"{server.base}/logs/{server.project('vessel')}")
    await expect(page.locator("[data-pane]")).to_contain_text(
        "hitchrail-shim: started", timeout=15_000
    )
    await page.route(
        "**/api/sessions/**/logs*",
        lambda route: route.fulfill(
            status=401,
            content_type="application/json",
            body='{"code": "unauthorized", "message": "a valid token is required"}',
        ),
    )
    await page.get_by_role("button", name="Refresh").click()
    await page.wait_for_url("**/grant", timeout=15_000)


async def test_the_logs_page_opens_on_the_newest_lines_and_keeps_a_readers_place(
    page: Page, server: Harness
) -> None:
    """#246. The page scrolls, not the pane, so the scroll-to-bottom line was a
    no-op and a tab opened on the oldest of two hundred lines. Opened at the
    bottom now; a refresh keeps a reader who scrolled up where they were, the
    way a terminal does, and follows the tail only while they were at it."""
    server.seed(running=["vessel"])
    await page.goto(f"{server.base}/logs/{server.project('vessel')}")
    pane = page.locator("[data-pane]")
    await expect(pane).to_contain_text("hitchrail-shim: started", timeout=15_000)
    # A render with more text than a screen holds, as two hundred lines is,
    # through the page's own render step.
    long = (
        "() => window.__logs.paint("
        "Array.from({length: 400}, (_, i) => 'line ' + i).join('\\n'))"
    )
    await page.evaluate(long)
    at_bottom = (
        "() => window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 4"
    )
    assert await page.evaluate(at_bottom), "the page did not open on the newest lines"

    # A reader who scrolled up is left where they are by the next render.
    await page.evaluate("() => window.scrollTo(0, 200)")
    await page.evaluate(long)
    assert await page.evaluate("() => window.scrollY") == 200, "a refresh moved the reader"

    # And one who scrolled back to the tail follows it again.
    await page.evaluate("() => window.scrollTo(0, document.documentElement.scrollHeight)")
    await page.evaluate(long.replace("400", "600"))
    assert await page.evaluate(at_bottom), "the tail was not followed"
