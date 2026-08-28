"""#55: stopping escalates, it does not branch.

The flow the design argues hardest about, and the one no other tier can see:
it is a sequence over time, not a status code.
"""

from __future__ import annotations

import pytest
from playwright.async_api import Page, expect

from .conftest import Harness

pytestmark = pytest.mark.e2e


async def _open_stop(page: Page, server: Harness, name: str = "vessel") -> None:
    await page.goto(server.base)
    row = page.locator(f'[data-project="{server.project(name)}"]')
    await expect(row).to_be_visible()
    await row.get_by_role("button", name="Stop").click()


async def test_the_confirm_step_offers_only_cancel_and_stop(
    page: Page, server: Harness
) -> None:
    """It escalates, it does not branch. A kill control here puts the
    destructive path under the thumb at the same weight as the safe one,
    which section 7 forbids in those words."""
    server.seed(running=["vessel"])
    await _open_stop(page, server)

    dialog = page.locator("[data-dialog]")
    await expect(dialog).to_contain_text(f"Stop {server.project('vessel')}?")
    await expect(dialog.get_by_role("button", name="Cancel")).to_be_visible()
    await expect(dialog.get_by_role("button", name="Stop", exact=True)).to_be_visible()
    assert await dialog.get_by_role("button", name="kill").count() == 0


async def test_cancel_stops_nothing(page: Page, server: Harness) -> None:
    """The safe exit has to actually be safe."""
    server.seed(running=["vessel"])
    await _open_stop(page, server)
    await page.locator("[data-dialog]").get_by_role("button", name="Cancel").click()

    # Both halves. Asserting only that nothing stopped passes against a Cancel
    # that does nothing at all, which is exactly what happened when
    # `closeDialog` gained a parameter and was still used as a listener: the
    # click event arrived as that parameter, never matched, and every Cancel
    # and Close silently stopped closing anything.
    await expect(page.locator("[data-dialog]")).to_be_hidden()
    assert server.is_running("vessel"), "Cancel stopped the session"


async def test_kill_appears_once_the_wait_is_under_way_and_stays(
    page: Page, server: Harness
) -> None:
    """Available for the WHOLE wait, phrased as impatience rather than as an
    alternative. Asserted twice with time in between, because a control that
    appears and then vanishes passes a single check."""
    server.seed(running=["vessel"], ignores_graceful_stop=True)
    await _open_stop(page, server)
    await page.locator("[data-dialog]").get_by_role("button", name="Stop", exact=True).click()

    dialog = page.locator("[data-dialog]")
    await expect(dialog).to_contain_text(f"Stopping {server.project('vessel')}")
    kill = dialog.get_by_role("button", name="Do not wait, kill it now")
    await expect(kill).to_be_visible()
    await page.wait_for_timeout(2500)
    await expect(kill).to_be_visible()


async def test_the_wait_can_be_dismissed_without_cancelling_the_stop(
    page: Page, server: Harness
) -> None:
    """`Hide, keep stopping`. A phone user has other rows to look at, and a
    modal that owns the screen for thirty seconds is one they kill the app to
    escape. The stop must survive the dismissal."""
    server.seed(running=["vessel"], ignores_graceful_stop=True)
    await _open_stop(page, server)
    await page.locator("[data-dialog]").get_by_role("button", name="Stop", exact=True).click()
    await (
        page.locator("[data-dialog]").get_by_role("button", name="Hide, keep stopping").click()
    )

    await expect(page.locator("[data-dialog]")).to_be_hidden()
    await expect(
        page.locator(f'[data-project="{server.project("vessel")}"]')
    ).to_have_attribute("data-stopping", "true")


async def test_the_kill_control_ends_a_session_that_will_not_stop(
    page: Page, server: Harness
) -> None:
    server.seed(running=["vessel"], ignores_graceful_stop=True)
    await _open_stop(page, server)
    await page.locator("[data-dialog]").get_by_role("button", name="Stop", exact=True).click()
    await (
        page.locator("[data-dialog]")
        .get_by_role("button", name="Do not wait, kill it now")
        .click()
    )

    await expect(
        page.locator(f'[data-project="{server.project("vessel")}"]')
    ).to_have_attribute("data-state", "stopped", timeout=15_000)
    assert not server.is_running("vessel")


async def test_a_graceful_stop_that_works_needs_no_kill(page: Page, server: Harness) -> None:
    """The happy path, which the escalation exists to avoid. The shim obeys
    `/exit`, so the dialog closes on its own."""
    server.seed(running=["vessel"])
    await _open_stop(page, server)
    await page.locator("[data-dialog]").get_by_role("button", name="Stop", exact=True).click()

    await expect(
        page.locator(f'[data-project="{server.project("vessel")}"]')
    ).to_have_attribute("data-state", "stopped", timeout=20_000)
    await expect(page.locator("[data-dialog]")).to_be_hidden()


async def test_the_protected_row_offers_no_stop_at_all(page: Page, server: Harness) -> None:
    """There is no path from this interface to a 423. Refusing after the tap
    is worse than not offering the tap."""
    server.seed(running=["hitchrail"], self_project="hitchrail")
    await page.goto(server.base)
    row = page.locator(f'[data-project="{server.project("hitchrail")}"]')
    await expect(row).to_be_visible()
    assert await row.get_by_role("button", name="Stop").count() == 0
    assert await row.get_by_role("button", name="Kill").count() == 0


async def test_the_timeout_states_the_risk_before_offering_the_kill(
    page: Page, server: Harness
) -> None:
    """Section 7: this is the moment the user is most likely to reach for the
    kill and least likely to have thought about work that is not saved."""
    server.seed(running=["vessel"], ignores_graceful_stop=True)
    await page.goto(server.base)
    await page.evaluate("() => window.__hitchrail.setStopPatience(1500)")

    row = page.locator(f'[data-project="{server.project("vessel")}"]')
    await expect(row).to_be_visible()
    await row.get_by_role("button", name="Stop").click()
    await page.locator("[data-dialog]").get_by_role("button", name="Stop", exact=True).click()

    dialog = page.locator("[data-dialog]")
    await expect(dialog).to_contain_text(
        f"No answer from {server.project('vessel')}", timeout=15_000
    )
    risk = (await dialog.inner_text()).lower()
    assert "lost" in risk or "unsaved" in risk or "not written" in risk, risk
    await expect(dialog.get_by_role("button", name="Leave it")).to_be_visible()
    await expect(dialog.get_by_role("button", name="Kill it")).to_be_visible()


async def test_the_timeout_does_not_kill_by_itself(page: Page, server: Harness) -> None:
    """The engine reports and does not escalate; the interface must not do the
    escalating on its behalf. An automatic kill is a destructive action taken
    while the person was not looking, and this is the assertion that pins it."""
    server.seed(running=["vessel"], ignores_graceful_stop=True)
    await page.goto(server.base)
    await page.evaluate("() => window.__hitchrail.setStopPatience(1200)")

    row = page.locator(f'[data-project="{server.project("vessel")}"]')
    await expect(row).to_be_visible()
    await row.get_by_role("button", name="Stop").click()
    await page.locator("[data-dialog]").get_by_role("button", name="Stop", exact=True).click()
    await expect(page.locator("[data-dialog]")).to_contain_text(
        "No answer from", timeout=15_000
    )

    await page.wait_for_timeout(3000)

    assert server.is_running("vessel"), "the interface killed a session nobody told it to"


async def test_leave_it_leaves_it(page: Page, server: Harness) -> None:
    """The safe exit from the timeout screen has to actually be safe."""
    server.seed(running=["vessel"], ignores_graceful_stop=True)
    await page.goto(server.base)
    await page.evaluate("() => window.__hitchrail.setStopPatience(1200)")

    row = page.locator(f'[data-project="{server.project("vessel")}"]')
    await expect(row).to_be_visible()
    await row.get_by_role("button", name="Stop").click()
    await page.locator("[data-dialog]").get_by_role("button", name="Stop", exact=True).click()
    dialog = page.locator("[data-dialog]")
    await expect(dialog).to_contain_text("No answer from", timeout=15_000)
    await dialog.get_by_role("button", name="Leave it").click()

    await expect(dialog).to_be_hidden()
    assert server.is_running("vessel")


async def test_a_finishing_stop_does_not_close_a_dialog_opened_since(
    page: Page, server: Harness
) -> None:
    """`Hide, keep stopping` leaves the stop running, so by the time it
    completes the person may be part way through something else. Closing that
    out from under them looks like a crash.

    The New folder sheet rather than a log drawer, because it needs no second
    session: the property is about which dialog is on screen, not about what
    opened it.
    """
    server.seed(running=["vessel"])
    await page.goto(server.base)
    vessel = page.locator(f'[data-project="{server.project("vessel")}"]')
    await expect(vessel).to_be_visible()

    await vessel.get_by_role("button", name="Stop").click()
    await page.locator("[data-dialog]").get_by_role("button", name="Stop", exact=True).click()
    await (
        page.locator("[data-dialog]").get_by_role("button", name="Hide, keep stopping").click()
    )
    # A modal dialog makes the rest of the page inert, so the next click is
    # intercepted by the backdrop until it has actually closed.
    await expect(page.locator("[data-dialog]")).to_be_hidden()

    await page.get_by_role("button", name="New").click()
    dialog = page.locator("[data-dialog]")
    await expect(dialog).to_contain_text("New folder")
    await page.get_by_label("Folder name").fill("half-typed")

    # Let the background stop run to completion underneath it.
    await page.wait_for_timeout(6000)

    await expect(dialog).to_be_visible()
    await expect(dialog).to_contain_text("New folder")
    assert await page.get_by_label("Folder name").input_value() == "half-typed", (
        "the sheet was rebuilt, losing what had been typed into it"
    )


async def test_a_stop_that_never_reached_the_server_says_so(
    page: Page, server: Harness
) -> None:
    """An error rendered as a success is worse than no guard.

    `beginStop` shows "Waiting for it to finish" BEFORE the request, which is
    right: the wait is the point of the screen. It becomes a lie if the request
    never happened. `fetch` rejects when the network is gone, where a refused
    request resolves, so the rejection used to escape into the click handler
    and leave that screen up for a stop nobody had asked for.

    Reachable rather than theoretical, because #57 tells the user the page is
    up while the list is not live, which is exactly when somebody taps
    something.
    """
    server.seed(running=["vessel"])
    await page.goto(server.base)
    row = page.locator(f'[data-project="{server.project("vessel")}"]')
    await expect(row).to_have_attribute("data-state", "running")

    # The network goes, after the page has loaded.
    await page.route("**/api/sessions/**", lambda route: route.abort("failed"))

    await row.get_by_role("button", name="Stop").click()
    dialog = page.locator("[data-dialog]")
    await expect(dialog).to_contain_text("Stop hrx-vessel")
    await dialog.get_by_role("button", name="Stop", exact=True).click()

    await expect(dialog).to_contain_text("That did not work")
    await expect(dialog).to_contain_text("The connection dropped.")
    await expect(dialog).not_to_contain_text("Waiting for it to finish")
    # And the session is untouched, because nothing was ever sent.
    assert server.is_running("vessel")
