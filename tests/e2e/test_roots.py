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
    await expect(dialog).to_contain_text(f"Stop {server.displayed('vessel', 'main')}")
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

    Written against what a PERSON can see rather than against the markup, so it
    survived #122 changing how that happens: it passed when the row rendered
    the whole identifier and it passes now that the row renders the folder with
    the label in a chip beside it. It goes red the day a row stops naming its
    root by any means.
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


async def test_one_root_still_reads_as_it_did(page: Page, server: Harness) -> None:
    """#122 asks for this in as many words: a single root deployment should not
    pay for a feature it does not use.

    The row shows the bare folder and no root chip, which is exactly what every
    test written before #120 sees. The identifier still carries the label, so
    this is about what a person reads and not about what addresses the project.
    """
    server.seed(stopped=["vessel"])
    await page.goto(server.base)

    row = page.locator(f'[data-project="{server.project("vessel")}"]')
    await expect(row).to_have_attribute("data-state", "stopped", timeout=15_000)
    await expect(row.locator(".row-name")).to_have_text(server.displayed("vessel"))
    await expect(row.locator(".row-root")).to_have_count(0)


async def test_a_search_spans_the_roots_and_says_where_each_hit_is(
    page: Page, server: Harness
) -> None:
    """#122's scope: one query, both roots, and each result distinguishable.

    The query runs against the identifier, so `vessel` matches in both roots
    and a root label is itself a way to narrow to one of them.
    """
    server.seed(running=["vessel"], also_in=TWO_ROOTS)
    await page.goto(server.base)

    work = page.locator(f'[data-project="{server.project("vessel")}"]')
    personal = page.locator(f'[data-project="{server.project("vessel", "personal")}"]')
    await expect(work).to_have_attribute("data-state", "running", timeout=15_000)

    await page.locator("[data-search]").fill("vessel")
    await expect(work).to_be_visible()
    await expect(personal).to_be_visible()
    await expect(personal.locator(".row-root")).to_have_text("personal")

    # A label narrows to one root, which falls out of matching the identifier
    # rather than being a feature anybody had to add.
    await page.locator("[data-search]").fill("personal")
    await expect(personal).to_be_visible()
    await expect(work).to_be_hidden()
