"""#120 and #121: the defect the whole phase exists for, proved on real things.

**Only this tier can prove it.** The claim is that two projects sharing a
folder name in two roots are two agents, and that stopping one leaves the other
alone. A faked tmux would show only that the fake was keyed by two strings; a
faked process table would show only that the fake was. Here the tmux server is
real, the process table is real, and the agents are real processes, so the
assertion is about the machine rather than about a double.

Before the qualified identifier, both projects derived `hr-vessel`. The second
read as `running` on the first one's session, and tapping Stop on it stopped
the other one's agent. That is the failure being ruled out, and it was silent.
"""

from __future__ import annotations

import pytest
from playwright.async_api import Page, expect

from .conftest import Harness

pytestmark = pytest.mark.e2e

TWO_ROOTS = {"personal": ["vessel"]}


async def test_the_same_folder_name_in_two_roots_is_two_rows(
    page: Page, server: Harness
) -> None:
    """The listing half. One name, two roots, two rows with distinct
    identifiers, and both of them running."""
    server.seed(running=["vessel"], also_in=TWO_ROOTS)
    await page.goto(server.base)

    work = page.locator(f'[data-project="{server.project("vessel")}"]')
    personal = page.locator(f'[data-project="{server.project("vessel", "personal")}"]')

    await expect(work).to_have_attribute("data-state", "running", timeout=15_000)
    await expect(personal).to_have_attribute("data-state", "running", timeout=15_000)
    assert server.project("vessel") != server.project("vessel", "personal")


async def test_stopping_one_root_s_project_leaves_the_other_agent_alone(
    page: Page, server: Harness
) -> None:
    """**The assertion the phase exists for.**

    Driven through the interface rather than the engine, because the bug this
    replaces was reachable by tapping Stop on a row: the identifier the page
    sent resolved to the other project's tmux session.
    """
    server.seed(running=["vessel"], also_in=TWO_ROOTS)
    await page.goto(server.base)

    work = page.locator(f'[data-project="{server.project("vessel")}"]')
    personal = page.locator(f'[data-project="{server.project("vessel", "personal")}"]')
    await expect(work).to_have_attribute("data-state", "running", timeout=15_000)
    await expect(personal).to_have_attribute("data-state", "running", timeout=15_000)

    await work.get_by_role("button", name="Stop").click()
    dialog = page.locator("[data-dialog]")
    # The confirmation names the QUALIFIED project, which is the one place the
    # full identifier is worth showing: this is where naming the wrong one is
    # destructive.
    await expect(dialog).to_contain_text(f"Stop {server.project('vessel')}")
    await dialog.get_by_role("button", name="Stop").click()

    await expect(work).not_to_have_attribute("data-state", "running", timeout=30_000)
    # Read from the real machine, not from the page: the page could be right
    # about the row and wrong about the world, and it is the world that matters
    # here.
    assert server.is_running("vessel", "personal"), (
        "stopping the project in one root killed the agent in the other, which "
        "is the exact defect #119 and #121 exist to prevent"
    )


async def test_each_row_says_which_root_it_is_in(page: Page, server: Harness) -> None:
    """Two identically named rows are indistinguishable to the person tapping
    Stop, which is #122's whole argument.

    **This is weaker than it looks today, and saying so is the point.** The
    root is visible because the row currently renders the whole identifier,
    `personal~hrx-vessel`, so a person can read it off the name. That is not
    the design: #122 puts the folder in the name and the label in a badge
    beside it.

    The assertion is written against what a PERSON can see rather than against
    the markup, so it survives that change instead of being deleted by it. It
    goes red the day a row stops naming its root by any means, which is the
    only thing worth guarding here until #122 lands.
    """
    server.seed(running=["vessel"], also_in=TWO_ROOTS)
    await page.goto(server.base)

    work = page.locator(f'[data-project="{server.project("vessel")}"]')
    personal = page.locator(f'[data-project="{server.project("vessel", "personal")}"]')
    await expect(work).to_have_attribute("data-state", "running", timeout=15_000)

    assert "personal" in (await personal.inner_text()), (
        "the row does not name its root, so two identically named projects are "
        "indistinguishable to somebody about to stop one"
    )
