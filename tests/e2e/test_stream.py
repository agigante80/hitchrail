"""#57: live updates, and a list that is right after a reconnect.

The reconnection case is the reason this tier exists. A phone suspends a
backgrounded tab, the stream drops, and the list must be CORRECT afterwards
rather than merely reconnected.
"""

from __future__ import annotations

import time

import pytest
from playwright.async_api import Page, Route, expect

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

    # The row is stale, and STAYS stale until something asks. A wall clock
    # sleep followed by a negative assertion would prove nothing: it fails on a
    # loaded runner and passes for a refetch that is merely slow. So wait for
    # the state the harness can see, then assert the page has not caught up.
    assert not server.is_running("vessel"), "the harness did not actually stop it"
    assert await row.get_attribute("data-state") == "running"

    await page.evaluate("() => document.dispatchEvent(new Event('visibilitychange'))")

    await expect(row).to_have_attribute("data-state", "stopped", timeout=20_000)
    # And the stream is LIVE again, not merely re-fetched once. Without this,
    # deleting the reopen from `onVisible` leaves the test green and the page
    # with a permanently dead stream for the rest of the session.
    await expect(page.locator("html")).to_have_attribute("data-stream", "open", timeout=20_000)


async def test_a_live_stream_says_nothing_at_all(page: Page, server: Harness) -> None:
    """A permanent "live" badge would be noise on a phone. The only state worth
    a person's attention is the one where the list has stopped being true."""
    server.seed(stopped=["vessel"])
    await page.goto(server.base)
    await expect(page.locator("html")).to_have_attribute("data-stream", "open", timeout=15_000)
    # Count first. `to_be_hidden` is satisfied by an element that does not
    # exist, so on its own it passes for a page that deleted the strip.
    await expect(page.locator("[data-stream-note]")).to_have_count(1)
    await expect(page.locator("[data-stream-note]")).not_to_be_visible()


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

    # `machine_unreadable`, not `root_unavailable`. The state's whole
    # justification is a machine that cannot be read, and a test that only ever
    # produced the other code left the named half of the condition free to be
    # deleted.
    server.break_machine()
    await page.evaluate("() => window.__hitchrail.refresh()")

    await expect(page.locator("html")).to_have_attribute("data-stream", "blind")
    await expect(page.locator("[data-stream-note]")).to_contain_text("cannot be read")

    server.heal_machine()
    await page.evaluate("() => window.__hitchrail.refresh()")

    await expect(page.locator("html")).to_have_attribute("data-stream", "open")
    await expect(page.locator("[data-stream-note]")).to_have_count(1)
    await expect(page.locator("[data-stream-note]")).not_to_be_visible()


async def test_a_root_that_went_away_is_blind_too(page: Page, server: Harness) -> None:
    """The other half of the condition. Both codes mean the same thing to a
    person: we are connected and the list cannot be read."""
    server.seed(stopped=["vessel"])
    await page.goto(server.base)
    await expect(page.locator("html")).to_have_attribute("data-stream", "open", timeout=15_000)

    gone = server.root.with_name(server.root.name + "-gone")
    server.root.rename(gone)
    try:
        await page.evaluate("() => window.__hitchrail.refresh()")
        await expect(page.locator("html")).to_have_attribute("data-stream", "blind")
    finally:
        gone.rename(server.root)


async def test_a_dropped_stream_is_visible_rather_than_silent(
    page: Page, server: Harness
) -> None:
    """A list that has quietly stopped updating looks exactly like a list where
    nothing is happening, and nothing happening is this tool's normal state."""
    server.seed(running=["vessel"])
    await page.goto(server.base)
    await expect(page.locator("html")).to_have_attribute("data-stream", "open", timeout=15_000)

    server.drop_connections()

    # ONE wait, not three in sequence. `down` is transient by design, since
    # Chromium retries a few seconds after the abort, and three `expect` calls
    # each with their own polling budget must all land inside that window. This
    # reads the attribute and the strip together in a single poll.
    async def strip() -> dict[str, object]:
        read: dict[str, object] = await page.evaluate(
            """() => {
                const note = document.querySelector("[data-stream-note]");
                return {
                    state: document.documentElement.getAttribute("data-stream"),
                    present: note !== null,
                    shown: note !== null && getComputedStyle(note).display !== "none",
                    text: note === null ? "" : note.textContent,
                };
            }"""
        )
        return read

    deadline = time.monotonic() + 15
    seen: dict[str, object] = {}
    while time.monotonic() < deadline:
        seen = await strip()
        if seen["state"] == "down" and seen["shown"]:
            break
        await page.wait_for_timeout(50)

    # The attribute is the mechanism; a person READS the strip. Asserting only
    # the attribute would pass on a build where nothing renders it, and
    # `to_be_hidden` would pass on one that deleted it.
    assert seen["present"], seen
    assert seen["state"] == "down", seen
    assert seen["shown"], seen
    assert "Not live" in str(seen["text"]), seen


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


async def test_an_event_beats_a_listing_that_was_asked_for_first(
    page: Page, server: Harness
) -> None:
    """The ordering rule, and the reason there is one.

    A listing fetched at T0 knows nothing about an event that arrived at T0+1,
    and it lands after it. Without the rule, stopping a session from a laptop
    while the phone happens to be fetching puts the row back to `running` and
    NOTHING ever corrects it: there is no polling, and a session that reached a
    terminal state sends no further event. The next tap on Stop then argues
    with a session that ended minutes ago.
    """
    server.seed(running=["vessel"])
    await page.goto(server.base)
    row = page.locator(f'[data-project="{server.project("vessel")}"]')
    await expect(row).to_have_attribute("data-state", "running")

    # Hold the listing open. The response is captured while `vessel` is still
    # running, and released only after the event has already corrected the row.
    await page.evaluate(
        """() => {
            const real = window.fetch;
            window.__release = null;
            window.fetch = async (...args) => {
                const response = await real(...args);
                const url = typeof args[0] === "string" ? args[0] : args[0].url;
                if (!url.includes("/api/projects")) return response;
                window.fetch = real;
                await new Promise((resolve) => { window.__release = resolve; });
                return response;
            };
            window.__hitchrail.refresh();
        }"""
    )
    await page.wait_for_function("() => window.__release !== null", timeout=10_000)

    server.kill("vessel")
    await expect(row).to_have_attribute("data-state", "stopped", timeout=20_000)

    await page.evaluate("() => window.__release()")

    # The stale listing has landed by now. Give it a moment to do damage, then
    # assert it did not: this negative has a definite event to wait for, unlike
    # a bare sleep.
    await page.wait_for_function(
        "() => window.__hitchrail.state.projects.length > 0", timeout=10_000
    )
    await expect(row).to_have_attribute("data-state", "stopped")


async def test_a_stream_the_server_refuses_is_reopened_anyway(
    page: Page, server: Harness
) -> None:
    """`EventSource` retries a NETWORK error and not a refused response.

    A non 200 closes it for good, by specification. The reachable case is an
    operator restarting Hitchrail, which mints a new token, against a phone
    still holding the old cookie: 401, dead stream, and a strip saying
    "Reconnecting" forever. Nothing in the page would ever reopen it, because
    the only other reopen needs the tab backgrounded and brought back.
    """
    refusals = 0

    async def refuse_once(route: Route) -> None:
        nonlocal refusals
        refusals += 1
        if refusals == 1:
            await route.fulfill(status=500, content_type="text/plain", body="no")
        else:
            await route.continue_()

    await page.route("**/api/events", refuse_once)
    server.seed(stopped=["vessel"])
    await page.goto(server.base)

    await expect(page.locator("html")).to_have_attribute("data-stream", "down", timeout=15_000)
    await expect(page.locator("html")).to_have_attribute("data-stream", "open", timeout=25_000)
    assert refusals >= 2, f"the page never asked again: {refusals}"


async def test_a_frame_the_page_cannot_use_costs_nothing(page: Page, server: Harness) -> None:
    """Two frames no client should see, and neither may become a refetch.

    A malformed one is not a reason to tear down a working stream, and an
    unrecognised shape must not turn one publisher's mistake into a root scan
    per connected client per event.
    """
    server.seed(running=["vessel"], stopped=["koala"])
    await page.goto(server.base)
    row = page.locator(f'[data-project="{server.project("vessel")}"]')
    await expect(row).to_have_attribute("data-state", "running")

    fetches = await page.evaluate(
        """async () => {
            const real = window.fetch;
            let count = 0;
            window.fetch = (...args) => { count += 1; return real(...args); };
            const stream = window.__hitchrail.stream;
            stream.dispatchEvent(new MessageEvent("message", { data: "{" }));
            stream.dispatchEvent(new MessageEvent("message", {
                data: JSON.stringify({ kind: "session", session: { name: "koala" } }),
            }));
            // The unknown project path coalesces through a timeout, so give it
            // one to fire in before counting.
            await new Promise((resolve) => setTimeout(resolve, 250));
            window.fetch = real;
            return count;
        }"""
    )
    assert fetches == 0, f"a frame the page cannot use cost {fetches} listings"

    # And the stream still works.
    server.kill("vessel")
    await expect(row).to_have_attribute("data-state", "stopped", timeout=20_000)
