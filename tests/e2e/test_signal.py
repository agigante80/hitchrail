"""#107 on a real browser: the End control on a detached row, its
confirmation, and the refusal that is not a dead end.

The detached agent is a real process the harness spawned outside tmux, so
the SIGTERM the route sends through a real pidfd is observed on the
machine, not on the row.
"""

from __future__ import annotations

import pytest
from playwright.async_api import Page, expect

from .conftest import Harness

pytestmark = pytest.mark.e2e


async def test_a_detached_row_offers_end_and_the_confirmation_says_what_is_known(
    page: Page, server: Harness
) -> None:
    server.seed(detached=["forge-kit"])
    await page.goto(server.base)
    row = page.locator(f'[data-project="{server.project("forge-kit")}"]')
    await expect(row).to_have_attribute("data-state", "detached")

    end = row.get_by_role("button", name="End")
    await expect(end).to_be_visible()
    assert "danger" in (await end.get_attribute("class") or "")
    assert await row.get_by_role("button").count() == 1
    await end.click()

    dialog = page.locator("[data-dialog]")
    await expect(dialog).to_contain_text("Hitchrail can see no session that owns this agent")
    await expect(dialog).to_contain_text("this will end it there too")
    buttons = dialog.get_by_role("button")
    # Cancel first, the destructive action second and styled as such.
    await expect(buttons.nth(0)).to_have_text("Cancel")
    await expect(buttons.nth(1)).to_have_text("End it")
    assert "danger" in (await buttons.nth(1).get_attribute("class") or "")
    await buttons.nth(0).click()
    await expect(dialog).not_to_be_visible()
    assert not server.orphans_exited(timeout=0.5), "Cancel ended the agent"


async def test_confirming_end_sends_sigterm_to_the_real_process(
    page: Page, server: Harness
) -> None:
    server.seed(detached=["forge-kit"])
    await page.goto(server.base)
    row = page.locator(f'[data-project="{server.project("forge-kit")}"]')
    await expect(row).to_have_attribute("data-state", "detached")
    await row.get_by_role("button", name="End").click()
    await page.locator("[data-dialog]").get_by_role("button", name="End it").click()

    assert server.orphans_exited(), "the signal did not reach the process"
    await expect(row).to_have_attribute("data-state", "stopped", timeout=15_000)


async def test_kill_is_offered_only_after_end_was_sent(page: Page, server: Harness) -> None:
    """#169's rule at this row: SIGKILL is a second explicit request. The
    shim ignores SIGTERM here, so the row stays detached and the control
    becomes Kill, which is then confirmed on its own."""
    server.seed(detached=["forge-kit"], ignores_sigterm=True)
    await page.goto(server.base)
    row = page.locator(f'[data-project="{server.project("forge-kit")}"]')
    await expect(row).to_have_attribute("data-state", "detached")
    assert await row.get_by_role("button", name="Kill").count() == 0
    await row.get_by_role("button", name="End").click()
    await page.locator("[data-dialog]").get_by_role("button", name="End it").click()

    kill = row.get_by_role("button", name="Kill")
    await expect(kill).to_be_visible(timeout=10_000)
    assert not server.orphans_exited(timeout=0.5), "SIGTERM ended a shim that ignores it"
    await kill.click()
    dialog = page.locator("[data-dialog]")
    await expect(dialog).to_contain_text("not written to disk is lost")
    await dialog.get_by_role("button", name="Kill it").click()
    assert server.orphans_exited()
    await expect(row).to_have_attribute("data-state", "stopped", timeout=15_000)


async def test_a_later_agent_under_the_same_name_starts_from_end_again(
    page: Page, server: Harness
) -> None:
    """Review round 1: keyed by name alone, a page left open offered Kill as
    the FIRST control to a later agent under the same name. The escalation
    is per pid."""
    server.seed(detached=["forge-kit"])
    await page.goto(server.base)
    row = page.locator(f'[data-project="{server.project("forge-kit")}"]')
    await expect(row).to_have_attribute("data-state", "detached")
    await row.get_by_role("button", name="End").click()
    await page.locator("[data-dialog]").get_by_role("button", name="End it").click()
    assert server.orphans_exited()
    await expect(row).to_have_attribute("data-state", "stopped", timeout=15_000)

    server.reseed_detached("forge-kit")
    # The SAME page, refreshed rather than reloaded: a reload would empty
    # the page's memory of what it sent and prove nothing.
    for _ in range(50):
        await page.evaluate("() => window.__hitchrail.refresh()")
        if await row.get_attribute("data-state") == "detached":
            break
        await page.wait_for_timeout(200)
    await expect(row).to_have_attribute("data-state", "detached")
    await expect(row.get_by_role("button", name="End")).to_be_visible()
    assert await row.get_by_role("button", name="Kill").count() == 0


async def test_the_memory_of_what_was_sent_does_not_grow_for_the_life_of_the_tab(
    page: Page, server: Harness
) -> None:
    """#272. `state.signalled` is keyed `name:pid` and was never pruned, so
    a page left open for a day held a key per row it had ever ended. On a
    box with a small `pid_max` a reused pid under the same name would find
    its key already there and be offered Kill as its FIRST control, which is
    the escalation rule inverted. A key now survives only while its row is
    still detached at that pid, which is the state the escalation is about.
    """
    server.seed(detached=["forge-kit"])
    await page.goto(server.base)
    name = server.project("forge-kit")
    row = page.locator(f'[data-project="{name}"]')
    await expect(row).to_have_attribute("data-state", "detached")

    # Driven through the page's own state rather than by ending a row,
    # because the fake agent exits on the SIGTERM and its row is stopped by
    # the next listing: the key is then correctly gone, which proves the
    # pruning and not that a LIVE row keeps its escalation. Both directions
    # in one render: a key for the row on screen, and one for a row the
    # listing does not carry.
    kept = await page.evaluate(
        """() => {
          const hr = window.__hitchrail;
          const live = hr.state.projects.find((p) => p.state === "detached");
          hr.state.signalled.add(`${live.name}:${live.pid}`);
          hr.state.signalled.add(`${live.name}:999999`);
          hr.state.signalled.add("main~a-name-no-listing-carries:4242");
          hr.render();
          return [...hr.state.signalled];
        }"""
    )
    pid = await page.evaluate(
        """(n) => window.__hitchrail.state.projects.find((p) => p.name === n).pid""", name
    )
    assert kept == [f"{name}:{pid}"], kept
    # And the row still offers the escalation its surviving key is about.
    await expect(row.get_by_role("button", name="Kill")).to_be_visible()

    await row.get_by_role("button", name="Kill").click()
    await page.locator("[data-dialog]").get_by_role("button", name="Kill it").click()
    assert server.orphans_exited()
    await expect(row).to_have_attribute("data-state", "stopped", timeout=15_000)
    assert await page.evaluate("() => window.__hitchrail.state.signalled.size") == 0


async def test_an_agent_gone_before_the_tap_is_a_refusal_with_a_next_step(
    page: Page, server: Harness
) -> None:
    """The unhappy path: the agent left after the render. The server re-reads
    the machine before it opens anything and refuses, nothing was signalled,
    and the dialog offers Refresh rather than only Close, because a terminal
    dialog offers a decision (#169). The code is `not_detached` here, since
    the row had already become stopped by the time of the tap; `gone` is
    the same refusal one step later, when the process leaves between the
    re-read and the handle, and the page treats both as "look again"."""
    server.seed(detached=["forge-kit"])
    await page.goto(server.base)
    row = page.locator(f'[data-project="{server.project("forge-kit")}"]')
    await expect(row).to_have_attribute("data-state", "detached")
    await row.get_by_role("button", name="End").click()
    # Out from under the page, between the render and the confirmation.
    server.end_orphans_now()
    await page.locator("[data-dialog]").get_by_role("button", name="End it").click()

    dialog = page.locator("[data-dialog]")
    await expect(dialog).to_contain_text("Nothing was signalled")
    await expect(dialog.get_by_role("button", name="Refresh")).to_be_visible()
    await dialog.get_by_role("button", name="Refresh").click()
    await expect(row).to_have_attribute("data-state", "stopped", timeout=15_000)


async def test_a_row_another_session_owns_offers_no_end(page: Page, server: Harness) -> None:
    server.seed(foreign=["forge-kit"])
    await page.goto(server.base)
    row = page.locator(f'[data-project="{server.project("forge-kit")}"]')
    await expect(row).to_have_attribute("data-state", "detached")
    assert await row.get_by_role("button").count() == 0
