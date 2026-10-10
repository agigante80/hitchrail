"""#290, #294, tasks 267 and 268: a root of each agent, in the browser.

The hermetic tier proves the page is handed each row's agent and the live
tmux tier that each package's keys end its own agent. Neither shows a person
which agent a row runs, or that tapping Stop on the agy row ends agy and
leaves Claude Code alone through the page, which is what this does: a real
browser, a real tmux on a private socket, and two stand ins, one drawing
Claude Code's box and one drawing agy's.
"""

from __future__ import annotations

import pytest
from playwright.async_api import Page, expect

from .conftest import Harness

pytestmark = pytest.mark.e2e

AGY_ROOT = {"personal": ["vessel"]}


async def test_each_row_names_its_agent_and_stop_ends_only_that_one(
    page: Page, server: Harness
) -> None:
    server.seed(running=["vessel"], also_in=AGY_ROOT, agy_roots=["personal"])
    await page.goto(server.base)

    claude = page.locator(f'[data-project="{server.project("vessel")}"]')
    agy = page.locator(f'[data-project="{server.project("vessel", "personal")}"]')
    await expect(claude).to_have_attribute("data-state", "running", timeout=15_000)
    await expect(agy).to_have_attribute("data-state", "running", timeout=15_000)
    await expect(claude.locator(".row-agent")).to_have_text("default")
    await expect(agy.locator(".row-agent")).to_have_text("agy")

    await agy.get_by_role("button", name="Stop").click()
    dialog = page.locator("[data-dialog]")
    await dialog.get_by_role("button", name="Stop").click()

    # agy's keys, typed after agy's screen was read: Claude Code's sequence
    # would be refused here, because Claude Code's reader finds no box in
    # agy's pane. Stopped, rather than a refusal on the row, is that working.
    await expect(agy).to_have_attribute("data-state", "stopped", timeout=30_000)
    assert server.is_running("vessel"), "stopping the agy row ended Claude Code"


async def test_one_agent_names_none(page: Page, server: Harness) -> None:
    """Two roots running the same agent: one possible answer, so no chip, for
    the reason a single root shows no root chip."""
    server.seed(running=["vessel"], also_in=AGY_ROOT)
    await page.goto(server.base)
    row = page.locator(f'[data-project="{server.project("vessel", "personal")}"]')
    await expect(row).to_have_attribute("data-state", "running", timeout=15_000)
    await expect(page.locator(".row-agent")).to_have_count(0)
    await page.goto(f"{server.base}/settings")
    await expect(page.locator("[data-settings]")).to_have_attribute("data-loaded", "")
    await expect(page.locator("[data-plugins-scope]")).to_be_hidden()


async def test_settings_says_which_agents_the_plugin_update_leaves_out(
    page: Page, server: Harness
) -> None:
    server.seed(stopped_in=AGY_ROOT, agy_roots=["personal"])
    await page.goto(f"{server.base}/settings")
    scope = page.locator("[data-plugins-scope]")
    await expect(scope).to_be_visible(timeout=15_000)
    await expect(scope).to_contain_text("default agent's plugins only")
    await expect(scope).to_contain_text("No plugins to update: agy.")
    await expect(scope).not_to_contain_text("Not updated from here")
