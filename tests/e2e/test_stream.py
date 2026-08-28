"""#57: live updates, and a list that is right after a reconnect.

The reconnection case is the reason this tier exists. A phone suspends a
backgrounded tab, the stream drops, and the list must be CORRECT afterwards
rather than merely reconnected.
"""

from __future__ import annotations

import pytest
from playwright.async_api import Page, expect

from .conftest import Harness

pytestmark = pytest.mark.e2e


async def test_a_change_made_elsewhere_arrives_without_a_reload(
    page: Page, server: Harness
) -> None:
    """Two clients, or one client and a CLI. The design's whole reason for a
    stream is that the list is right without anybody refreshing it."""
    server.seed(running=["vessel"])
    await page.goto(server.base)
    row = page.locator(f'[data-project="{server.project("vessel")}"]')
    await expect(row).to_have_attribute("data-state", "running")

    server.kill("vessel")

    await expect(row).to_have_attribute("data-state", "stopped", timeout=20_000)


async def test_the_list_is_correct_after_the_tab_comes_back(
    page: Page, server: Harness
) -> None:
    """The one no other tier can see.

    The change happens while the stream is DOWN, so a page that only applies
    events and never re-fetches shows a row that has been wrong since the tab
    was suspended. `EventSource` reconnects on its own; what it cannot do is
    tell you what it missed.
    """
    server.seed(running=["vessel"])
    await page.goto(server.base)
    row = page.locator(f'[data-project="{server.project("vessel")}"]')
    await expect(row).to_have_attribute("data-state", "running")

    # Suspend the stream the way a backgrounded tab does, then change the
    # world underneath it.
    await page.evaluate("() => window.__hitchrail.stream.close()")
    server.kill("vessel")
    await page.wait_for_timeout(400)

    # The row is still stale at this point: nothing has told the page.
    assert await row.get_attribute("data-state") == "running"

    await page.evaluate("() => document.dispatchEvent(new Event('visibilitychange'))")

    await expect(row).to_have_attribute("data-state", "stopped", timeout=20_000)


async def test_a_live_stream_says_nothing_at_all(page: Page, server: Harness) -> None:
    """A permanent "live" badge would be noise on a phone. The only state worth
    a person's attention is the one where the list has stopped being true."""
    server.seed(stopped=["vessel"])
    await page.goto(server.base)
    await expect(page.locator("html")).to_have_attribute("data-stream", "open", timeout=15_000)
    await expect(page.locator("[data-stream-note]")).to_be_hidden()


async def test_a_readable_stream_over_an_unreadable_machine_is_its_own_state(
    page: Page, server: Harness
) -> None:
    """`blind`, the third state.

    Connected and the machine cannot be read. Collapsing it into `down` would
    report a network problem for a root that went away, and send somebody
    looking at their wifi instead of their mount.
    """
    server.seed(stopped=["vessel"])
    await page.goto(server.base)
    await expect(page.locator("html")).to_have_attribute("data-stream", "open", timeout=15_000)

    gone = server.root.with_name(server.root.name + "-gone")
    server.root.rename(gone)
    await page.evaluate("() => window.__hitchrail.refresh()")

    await expect(page.locator("html")).to_have_attribute("data-stream", "blind")
    await expect(page.locator("[data-stream-note]")).to_contain_text("cannot be read")

    gone.rename(server.root)
    await page.evaluate("() => window.__hitchrail.refresh()")

    await expect(page.locator("html")).to_have_attribute("data-stream", "open")
    await expect(page.locator("[data-stream-note]")).to_be_hidden()


async def test_a_dropped_stream_is_visible_rather_than_silent(
    page: Page, server: Harness
) -> None:
    """A list that has quietly stopped updating looks exactly like a list where
    nothing is happening, and nothing happening is this tool's normal state."""
    server.seed(running=["vessel"])
    await page.goto(server.base)
    await expect(page.locator("html")).to_have_attribute("data-stream", "open", timeout=15_000)

    server.drop_connections()

    await expect(page.locator("html")).to_have_attribute("data-stream", "down", timeout=15_000)
    # The attribute is the mechanism; a person reads the strip. Asserting only
    # the attribute would pass on a build where nothing renders it.
    await expect(page.locator("[data-stream-note]")).to_be_visible()
    await expect(page.locator("[data-stream-note]")).to_contain_text("Not live")


async def test_the_stream_reconnects_and_the_list_is_right_again(
    page: Page, server: Harness
) -> None:
    """The reconnect is not the deliverable, the CORRECTNESS after it is.

    `EventSource` reconnects on its own, and a page that trusted it to catch up
    would show whatever it had when the connection died. The change here
    happens while the stream is down, so only a re-fetch on reopen can show it.
    """
    server.seed(running=["vessel"])
    await page.goto(server.base)
    row = page.locator(f'[data-project="{server.project("vessel")}"]')
    await expect(row).to_have_attribute("data-state", "running")

    server.drop_connections()
    await expect(page.locator("html")).to_have_attribute("data-stream", "down", timeout=15_000)

    server.kill("vessel")

    # Nobody reloads and nobody touches the tab. `EventSource` reconnects by
    # itself, and the row has to be right afterwards.
    await expect(page.locator("html")).to_have_attribute("data-stream", "open", timeout=20_000)
    await expect(row).to_have_attribute("data-state", "stopped", timeout=20_000)


async def test_an_event_patches_one_row_without_refetching_the_listing(
    page: Page, server: Harness
) -> None:
    """The stream carries the whole session shape precisely so a change costs
    no subprocesses on the server. A page that re-fetched per event would turn
    every state change into two `ps` and two `tmux` calls."""
    server.seed(running=["vessel"], stopped=["koala"])
    await page.goto(server.base)
    row = page.locator(f'[data-project="{server.project("vessel")}"]')
    await expect(row).to_have_attribute("data-state", "running")

    # Count fetches from here on: the page has loaded, so the initial listing
    # is not in the count.
    await page.evaluate(
        """() => {
            const real = window.fetch;
            window.__fetches = 0;
            window.fetch = (...args) => {
                window.__fetches += 1;
                return real(...args);
            };
        }"""
    )

    server.kill("vessel")
    await expect(row).to_have_attribute("data-state", "stopped", timeout=20_000)

    fetches = await page.evaluate("() => window.__fetches")
    assert fetches == 0, f"the page re-fetched {fetches} times for one event"
