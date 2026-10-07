"""#239: a stop that ends on a prompt, under `stop_policy = end_anyway`.

The shim answers the exit with the background work modal, which is what a
real agent with work running does. Waits are on the page and the row, never
a sleep (#70).
"""

from __future__ import annotations

import pytest
from playwright.async_api import Page, expect

from .conftest import Harness

pytestmark = pytest.mark.e2e

NOTE = "If it stops on a question once asked to exit, it will be ended"


async def _confirm(page: Page, server: Harness) -> None:
    await page.goto(server.base)
    # Longer than the server's wait, so it is the server's kill under test and
    # not the browser giving up first.
    await page.evaluate("() => window.__hitchrail.setStopPatience(20000)")
    row = page.locator(f'[data-project="{server.project("vessel")}"]')
    await expect(row).to_be_visible()
    await row.get_by_role("button", name="Stop").click()


async def test_end_anyway_says_so_and_ends_a_stop_that_asks(
    page: Page, server: Harness
) -> None:
    server.seed(
        running=["vessel"], prompts_after_stop=True, stop_timeout=2.0, stop_policy="end_anyway"
    )
    await _confirm(page, server)
    dialog = page.locator("[data-dialog]")
    await expect(dialog).to_contain_text(NOTE)
    await dialog.get_by_role("button", name="Stop", exact=True).click()
    await expect(dialog).to_contain_text(NOTE)

    # No tap: the server kills at its own expiry, and the row says so.
    await expect(
        page.locator(f'[data-project="{server.project("vessel")}"]')
    ).to_have_attribute("data-state", "stopped", timeout=20_000)
    await expect(dialog).to_be_hidden()


async def test_ask_says_nothing_of_the_kind(page: Page, server: Harness) -> None:
    """The default is today's dialog, word for word."""
    server.seed(running=["vessel"], prompts_after_stop=True, stop_timeout=2.0)
    await _confirm(page, server)
    dialog = page.locator("[data-dialog]")
    await expect(dialog).to_contain_text("It will be interrupted")
    assert NOTE not in await dialog.inner_text()


async def test_end_anyway_chosen_on_the_settings_page_is_the_one_the_server_acts_on(
    page: Page, server: Harness
) -> None:
    """#409. Chosen here rather than in the file: the page says what it does
    under the Save, the list's dialog then warns, and the server ends the
    stop with no tap."""
    server.seed(running=["vessel"], prompts_after_stop=True, stop_timeout=2.0)
    await page.goto(f"{server.base}/settings")
    source = page.locator("[data-policy-source]")
    await expect(source).to_contain_text("waits for you. Currently the default.")
    await page.locator("[data-stop-policy]").select_option("end_anyway")
    await page.locator("[data-policy-save]").click()
    await expect(source).to_contain_text("is ended without a tap. Currently set here.")

    await _confirm(page, server)
    dialog = page.locator("[data-dialog]")
    await expect(dialog).to_contain_text(NOTE)
    await dialog.get_by_role("button", name="Stop", exact=True).click()
    await expect(
        page.locator(f'[data-project="{server.project("vessel")}"]')
    ).to_have_attribute("data-state", "stopped", timeout=20_000)


@pytest.mark.parametrize(
    ("source", "where"), [("flag", "command line"), ("file", "config file")]
)
async def test_a_policy_the_operator_set_is_text_on_the_settings_page(
    page: Page, server: Harness, source: str, where: str
) -> None:
    server.seed(stopped=["vessel"], stop_policy="end_anyway", stop_policy_source=source)
    await page.goto(f"{server.base}/settings")
    await expect(page.locator("[data-policy-source]")).to_contain_text(
        f"is ended without a tap. Set {'on' if source == 'flag' else 'in'} the {where}"
    )
    assert await page.locator("[data-stop-policy]").is_hidden()
    assert await page.locator("[data-policy-save]").is_hidden()


async def test_a_policy_changed_during_the_wait_does_not_change_its_words(
    page: Page, server: Harness
) -> None:
    """#419. The stop keeps the policy it was confirmed under, so its wait
    must keep saying what that policy does, whatever the listing now says.
    A wrap up, because only a `closing` row's Stop reopens the wait, which
    paints the words afresh from the listing."""
    server.seed(running=["vessel"], stop_prompt="/wrapup", wrap_up_takes=120)
    await _confirm(page, server)
    dialog = page.locator("[data-dialog]")
    await dialog.get_by_role("button", name="Stop", exact=True).click()
    await expect(dialog.get_by_role("button", name="Exit now")).to_be_visible()
    assert server.engine is not None
    server.engine.prefs.apply(stop_policy="end_anyway")
    await page.evaluate("() => window.__hitchrail.refresh()")
    assert await page.evaluate("() => window.__hitchrail.state.server.stop_policy") == (
        "end_anyway"
    )
    await dialog.get_by_role("button", name="Hide, keep stopping").click()
    await expect(dialog).to_be_hidden()

    row = page.locator(f'[data-project="{server.project("vessel")}"]')
    await row.get_by_role("button", name="Stop").click()
    await expect(dialog).to_contain_text("Asking it to wrap up")
    assert NOTE not in await dialog.inner_text()


async def test_a_wait_reopened_after_leaving_the_page_keeps_its_stops_policy(
    page: Page, server: Harness
) -> None:
    """#428, on one phone: Stop under `end_anyway`, follow the link to the
    settings page, choose `ask`, come back. The page that returns has no wait
    to copy the policy from, and the live setting says `ask`, while the
    server will still end this stop at its expiry. The reopened wait has to
    warn of that kill, so it reads the policy from the row."""
    server.seed(running=["vessel"], stop_prompt="/wrapup", wrap_up_takes=120)
    await page.goto(f"{server.base}/settings")
    await page.locator("[data-stop-policy]").select_option("end_anyway")
    await page.locator("[data-policy-save]").click()
    source = page.locator("[data-policy-source]")
    await expect(source).to_contain_text("is ended without a tap. Currently set here.")

    await _confirm(page, server)
    dialog = page.locator("[data-dialog]")
    await dialog.get_by_role("button", name="Stop", exact=True).click()
    await expect(dialog.get_by_role("button", name="Exit now")).to_be_visible()
    await expect(dialog).to_contain_text(NOTE)

    await page.goto(f"{server.base}/settings")
    await page.locator("[data-stop-policy]").select_option("ask")
    await page.locator("[data-policy-save]").click()
    await expect(source).to_contain_text("waits for you. Currently set here.")

    await page.goto(server.base)
    assert await page.evaluate("() => window.__hitchrail.state.server.stop_policy") == "ask"
    row = page.locator(f'[data-project="{server.project("vessel")}"]')
    await expect(row).to_have_attribute("data-stopping", "true")
    await row.get_by_role("button", name="Stop").click()
    await expect(dialog).to_contain_text("Asking it to wrap up")
    await expect(dialog).to_contain_text(NOTE)
