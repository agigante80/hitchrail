"""#242: Stop with a wrap up prompt, through pane, engine, sweep and dialog.

The shim draws the ornament rows task 169 captured, so the finished rule reads
the same bytes it reads from a real agent. Every wait is on the page or the
row, never a sleep (#70).
"""

from __future__ import annotations

import pytest
from playwright.async_api import Page, expect

from .conftest import Harness, e2e_name

pytestmark = pytest.mark.e2e

# The configuration's floor: the shortest ceiling a test can reach.
CEILING_S = 10


async def _stop(page: Page, server: Harness) -> None:
    await page.goto(server.base)
    row = page.locator(f'[data-project="{server.project("vessel")}"]')
    await expect(row).to_be_visible()
    await row.get_by_role("button", name="Stop").click()
    await page.locator("[data-dialog]").get_by_role("button", name="Stop", exact=True).click()


async def test_the_confirm_step_says_it_will_wrap_up_rather_than_interrupt(
    page: Page, server: Harness
) -> None:
    server.seed(running=["vessel"], stop_prompt="/wrapup", wrap_up_takes=3)
    await page.goto(server.base)
    row = page.locator(f'[data-project="{server.project("vessel")}"]')
    await row.get_by_role("button", name="Stop").click()
    dialog = page.locator("[data-dialog]")
    await expect(dialog).to_contain_text("wrap up after its current task")
    assert "It will be interrupted" not in await dialog.inner_text()


async def test_a_wrap_up_runs_then_the_agent_exits(page: Page, server: Harness) -> None:
    """The order the ticket decided: the prompt behind the task, the exit
    after it. The handoff file is the proof the prompt ran BEFORE the exit,
    since the shim writes it only on reading the prompt."""
    server.seed(running=["vessel"], stop_prompt="/wrapup", wrap_up_takes=3)
    await _stop(page, server)

    dialog = page.locator("[data-dialog]")
    await expect(dialog).to_contain_text("Asking it to wrap up, after its current task")
    await expect(dialog.get_by_role("button", name="Exit now")).to_be_visible()
    await expect(
        page.locator(f'[data-project="{server.project("vessel")}"]')
    ).to_have_attribute("data-state", "stopped", timeout=30_000)
    await expect(dialog).to_be_hidden()
    assert (server.root / e2e_name("vessel") / "handoff.md").exists()


async def test_the_ceiling_is_named_when_the_wrap_up_does_not_finish(
    page: Page, server: Harness
) -> None:
    """The ceiling cuts the task, and the dialog says that is why it moved on,
    from `stop_ceiling`, rather than reading as an exit it asked for."""
    server.seed(
        running=["vessel"],
        stop_prompt="/wrapup",
        stop_prompt_timeout=CEILING_S,
        wrap_up_stays_busy=True,
    )
    await _stop(page, server)

    dialog = page.locator("[data-dialog]")
    await expect(dialog).to_contain_text("Asking it to wrap up")
    await expect(dialog).to_contain_text(
        f"Wrap up did not finish in {CEILING_S}s; asked it to exit",
        timeout=(CEILING_S + 15) * 1000,
    )
    # The exit phase has no Exit now: it would send what was just sent.
    assert await dialog.get_by_role("button", name="Exit now").count() == 0
    await dialog.get_by_role("button", name="Do not wait, kill it now").click()
    await expect(
        page.locator(f'[data-project="{server.project("vessel")}"]')
    ).to_have_attribute("data-state", "stopped", timeout=15_000)


async def test_exit_now_skips_the_rest_of_the_wrap_up(page: Page, server: Harness) -> None:
    """A wrap up that would take a minute ends in seconds, gracefully: the
    Escape interrupts the task, the queued wrap up runs, then the exit."""
    server.seed(running=["vessel"], stop_prompt="/wrapup", wrap_up_takes=120)
    await _stop(page, server)

    dialog = page.locator("[data-dialog]")
    await expect(dialog).to_contain_text("Asking it to wrap up")
    await dialog.get_by_role("button", name="Exit now").click()
    await expect(
        page.locator(f'[data-project="{server.project("vessel")}"]')
    ).to_have_attribute("data-state", "stopped", timeout=20_000)
    await expect(dialog).to_be_hidden()
    assert (server.root / e2e_name("vessel") / "handoff.md").exists()
