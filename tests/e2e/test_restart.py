"""#472: Restart, through the page, the API, the sweep and a real tmux.

Two things only this tier can see: the button fitting beside Stop on the
daily phone's 360 px, and the order of events across the real sweep (the stop,
the exit, the start) ending in a new agent under the same session name.
"""

from __future__ import annotations

import pytest
from playwright.async_api import Page, expect

from .conftest import Harness, e2e_id

pytestmark = pytest.mark.e2e

PHONE = {"width": 360, "height": 740}


def _row(page: Page, server: Harness):  # type: ignore[no-untyped-def]
    return page.locator(f'[data-project="{server.project("vessel")}"]')


def _pid(server: Harness) -> int | None:
    assert server.engine is not None
    return server.engine.get(e2e_id("vessel")).pid


async def _open(page: Page, server: Harness):  # type: ignore[no-untyped-def]
    await page.set_viewport_size(PHONE)  # type: ignore[arg-type]
    await page.goto(server.base)
    row = _row(page, server)
    await expect(row).to_be_visible()
    return row


async def test_restart_sits_beside_stop_and_fits_at_360(page: Page, server: Harness) -> None:
    server.seed(running=["vessel"])
    row = await _open(page, server)
    stop = row.get_by_role("button", name="Stop", exact=True)
    restart = row.get_by_role("button", name="Restart", exact=True)
    await expect(stop).to_be_visible()
    await expect(restart).to_be_visible()
    for button in (stop, restart):
        box = await button.bounding_box()
        assert box is not None
        assert box["x"] >= 0 and box["x"] + box["width"] <= PHONE["width"], box
        assert box["height"] >= 24, "a target a thumb can hit"
    sideways = await page.evaluate(
        "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )
    assert sideways <= 0, "the extra button made the page scroll sideways"


async def test_restart_shows_stops_confirm_and_cancel_restarts_nothing(
    page: Page, server: Harness
) -> None:
    server.seed(running=["vessel"])
    row = await _open(page, server)
    before = _pid(server)
    await row.get_by_role("button", name="Restart", exact=True).click()
    dialog = page.locator("[data-dialog]")
    await expect(dialog).to_contain_text(f"Restart {server.displayed('vessel')}?")
    await expect(dialog).to_contain_text("interrupted")
    await expect(dialog).to_contain_text("part way through may be lost")
    await expect(dialog).to_contain_text("fresh conversation")
    assert await dialog.get_by_role("button", name="kill").count() == 0
    await dialog.get_by_role("button", name="Cancel").click()
    await expect(dialog).to_be_hidden()
    assert server.is_running("vessel") and _pid(server) == before
    assert server.engine is not None and server.engine.restarts.pending == {}


async def test_a_restart_ends_with_a_new_agent_in_the_same_session(
    page: Page, server: Harness
) -> None:
    server.seed(running=["vessel"])
    row = await _open(page, server)
    before = _pid(server)
    assert before is not None
    await row.get_by_role("button", name="Restart", exact=True).click()
    await (
        page.locator("[data-dialog]").get_by_role("button", name="Restart", exact=True).click()
    )

    # The new agent: a different process, running again, the same session name.
    # Polled on the pid and not on `data-state`, which reads `running` before
    # the stop has even begun and would pass on the agent being replaced.
    async def replaced() -> int:
        for _ in range(300):
            now = _pid(server)
            if now is not None and now != before:
                return now
            await page.wait_for_timeout(100)
        raise AssertionError("no new agent within 30s")

    await replaced()
    await expect(row).to_have_attribute("data-state", "running", timeout=10_000)
    await expect(row).not_to_have_attribute("data-restarting", "true", timeout=10_000)
    await expect(page.locator("[data-dialog]")).to_be_hidden(timeout=10_000)
    after = _pid(server)
    assert after is not None and after != before, "the same process, so nothing was restarted"
    assert server.sessions_on_the_socket(server._sock) == [f"hr-{e2e_id('vessel')}"], (
        "one session under the same name"
    )


async def test_a_restart_whose_stop_times_out_starts_no_second_agent(
    page: Page, server: Harness
) -> None:
    server.seed(running=["vessel"], ignores_graceful_stop=True, stop_timeout=2.0)
    row = await _open(page, server)
    await page.evaluate("() => window.__hitchrail.setStopPatience(1500)")
    before = _pid(server)
    await row.get_by_role("button", name="Restart", exact=True).click()
    await (
        page.locator("[data-dialog]").get_by_role("button", name="Restart", exact=True).click()
    )

    dialog = page.locator("[data-dialog]")
    await expect(dialog).to_contain_text("No answer from", timeout=20_000)
    # Several sweeps after the timeout: a start that was merely late would be
    # here by now.
    await page.wait_for_timeout(3_000)
    assert server.is_running("vessel") and _pid(server) == before
    assert server.sessions_on_the_socket(server._sock) == [f"hr-{e2e_id('vessel')}"]
    assert server.engine is not None and server.engine.restarts.pending == {}
    await expect(row).not_to_have_attribute("data-restarting", "true")
