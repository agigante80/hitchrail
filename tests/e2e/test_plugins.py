"""#297. The plugin update from the settings page, at a phone width.

The operation is the REAL one, pointed at a fake agent that holds each
plugin until the test releases it, so what is under test is the whole path:
the route, the thread, the escaping, the named event on the stream, the GET a
page reads when it joins late, and what the page draws from each.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

import pytest
from playwright.async_api import APIResponse, Page, Route, expect

from .conftest import Harness

pytestmark = pytest.mark.e2e

# #348. Not the real server's boot id, so a synthetic record painted after
# a real one is ordered by arrival, the page's rule across boots: it wins by
# arriving later, which is what every test below that delivers one wants.
SYNTHETIC_BOOT = "e2e-synthetic-boot"

THREE = [
    {"id": "alpha@m", "scope": "user"},
    {"id": "bravo@m", "scope": "user"},
    {"id": "charlie@m", "scope": "user"},
]


async def open_settings(page: Page, server: Harness) -> None:
    await page.goto(f"{server.base}/settings")
    await expect(page.locator("[data-settings]")).to_have_attribute("data-loaded", "")
    await expect(page.locator("[data-plugins-status]")).to_have_text(
        "Not run since this server started."
    )


async def test_outcomes_arrive_one_at_a_time_then_a_summary(
    page: Page, server: Harness
) -> None:
    server.seed_plugins(THREE)
    server.seed(running=["vessel"])
    await open_settings(page, server)
    button = page.locator("[data-plugins-update]")
    items = page.locator("[data-plugins-list] li")

    await button.click()
    await expect(button).to_be_disabled()
    server.release_plugin("alpha@m")
    # One outcome on the page while the other two are still held: progress,
    # not a spinner that resolves all at once.
    await expect(items).to_have_count(1)
    await expect(items.first).to_contain_text("alpha@m")
    await expect(page.locator("[data-plugins-status]")).to_have_text("Updating: 1 done so far.")

    server.release_plugin("bravo@m")
    server.release_plugin("charlie@m")
    await expect(items).to_have_count(3)
    status = page.locator("[data-plugins-status]")
    await expect(status).to_contain_text("3 updated, 0 failed, 0 left alone.")
    # A session is running, so the page says it keeps the old versions.
    await expect(status).to_contain_text("keeps the old versions until restarted")
    await expect(button).to_be_enabled()


async def test_a_partial_failure_names_the_plugin_and_is_not_an_error(
    page: Page, server: Harness
) -> None:
    server.seed_plugins(THREE)
    server.seed()
    await open_settings(page, server)
    await page.locator("[data-plugins-update]").click()
    server.release_plugin("alpha@m")
    server.release_plugin("bravo@m", fail=True)
    server.release_plugin("charlie@m")
    status = page.locator("[data-plugins-status]")
    await expect(status).to_have_text("2 updated, 1 failed, 0 left alone.")
    failed = page.locator('[data-plugins-list] li[data-result="failed"]')
    await expect(failed).to_have_count(1)
    await expect(failed).to_contain_text("bravo@m")
    await expect(failed).to_contain_text("exited 1: bravo@m: download failed")
    # The run itself is not a failure: the section says done, not failed.
    await expect(page.locator("[data-plugins]")).to_have_attribute("data-state", "done")
    # And nothing claims a running session where there is none.
    await expect(status).not_to_contain_text("restarted")


async def test_an_unreadable_listing_says_so_and_offers_no_count(
    page: Page, server: Harness
) -> None:
    server.seed_plugins("this is not json")
    server.seed()
    await open_settings(page, server)
    await page.locator("[data-plugins-update]").click()
    status = page.locator("[data-plugins-status]")
    await expect(status).to_have_text(
        "The list of installed plugins could not be understood, so nothing was updated."
    )
    await expect(status).not_to_contain_text("updated,")
    await expect(page.locator("[data-plugins-list] li")).to_have_count(0)
    await expect(page.locator("[data-plugins]")).to_have_attribute("data-state", "failed")


async def test_a_project_scoped_plugin_is_listed_and_left_alone(
    page: Page, server: Harness
) -> None:
    server.seed_plugins([{"id": "alpha@m", "scope": "user"}, {"id": "kit@x", "scope": "local"}])
    server.seed()
    await open_settings(page, server)
    await page.locator("[data-plugins-update]").click()
    server.release_plugin("alpha@m")
    await expect(page.locator("[data-plugins-status]")).to_have_text(
        "1 updated, 0 failed, 1 left alone."
    )
    skipped = page.locator('[data-plugins-list] li[data-result="skipped"]')
    await expect(skipped).to_contain_text("kit@x")
    await expect(skipped).to_contain_text("local scope is not updated")


async def test_a_page_opened_mid_run_shows_where_the_run_is(
    page: Page, server: Harness
) -> None:
    """The stream does not replay, so a phone that joins late, or comes back
    from a dropped connection, learns the run from the GET."""
    server.seed_plugins(THREE)
    server.seed()
    await open_settings(page, server)
    await page.locator("[data-plugins-update]").click()
    server.release_plugin("alpha@m")
    await expect(page.locator("[data-plugins-list] li")).to_have_count(1)

    late = await page.context.new_page()
    await late.goto(f"{server.base}/settings")
    await expect(late.locator("[data-plugins-status]")).to_have_text("Updating: 1 done so far.")
    await expect(late.locator("[data-plugins-update]")).to_be_disabled()
    await expect(late.locator("[data-plugins-list] li")).to_have_count(1)

    # And from then on the late page follows the stream like the first.
    server.release_plugin("bravo@m")
    server.release_plugin("charlie@m")
    await expect(late.locator("[data-plugins-status]")).to_have_text(
        "3 updated, 0 failed, 0 left alone."
    )


async def test_the_section_holds_at_a_phone_width_with_long_vendor_text(
    page: Page, server: Harness
) -> None:
    long_id = "a-plugin-with-a-deliberately-long-name@a-marketplace-with-one-too"
    server.seed_plugins([{"id": long_id, "scope": "user"}])
    server.seed()
    await open_settings(page, server)
    await page.locator("[data-plugins-update]").click()
    server.release_plugin(long_id, fail=True)
    await expect(page.locator("[data-plugins-status]")).to_have_text(
        "0 updated, 1 failed, 0 left alone."
    )
    assert await page.evaluate(
        "() => document.documentElement.scrollWidth <= document.documentElement.clientWidth"
    )
    box = await page.locator("[data-plugins-update]").bounding_box()
    assert box is not None and box["height"] >= 44, box


async def test_a_reconnect_mid_run_catches_up_on_what_it_missed(
    page: Page, server: Harness
) -> None:
    """Round 1 of batch 2's review: removing the `open` handler left every
    test green, because the page load's own GET covered the late joiner.
    Here the page is already open when the connection drops, and the rest of
    the run happens while it is down, so only the reconnect's GET can tell it."""
    server.seed_plugins(THREE)
    server.seed()
    await open_settings(page, server)
    await page.locator("[data-plugins-update]").click()
    server.release_plugin("alpha@m")
    await expect(page.locator("[data-plugins-list] li")).to_have_count(1)

    # Hold the page's reads of the stream so nothing arrives while it is cut,
    # then finish the run behind its back.
    await page.route("**/api/events", lambda route: route.abort())
    server.drop_connections()
    server.release_plugin("bravo@m")
    server.release_plugin("charlie@m")
    await page.wait_for_timeout(500)
    await expect(page.locator("[data-plugins-status]")).to_have_text("Updating: 1 done so far.")

    await page.unroute("**/api/events")
    await expect(page.locator("[data-plugins-status]")).to_have_text(
        "3 updated, 0 failed, 0 left alone.", timeout=15_000
    )
    await expect(page.locator("[data-plugins-update]")).to_be_enabled()


async def test_a_late_answer_never_paints_an_older_record_over_a_newer_one(
    page: Page, server: Harness
) -> None:
    """The high from round 1 of batch 2's review, reproduced as the reviewer
    did: a GET answered mid run and delivered after the run's last event
    put "Refreshing the marketplaces" back on screen with the button off, and
    nothing came afterwards to correct it."""
    server.seed_plugins(THREE)
    server.seed()
    await open_settings(page, server)

    held: list[object] = []

    async def hold(route):  # type: ignore[no-untyped-def]
        if route.request.method == "GET":
            response = await route.fetch()
            held.append(response)
            await page.wait_for_timeout(2500)
            await route.fulfill(response=response)
        else:
            await route.continue_()

    await page.locator("[data-plugins-update]").click()
    await page.route("**/api/plugins/update", hold)
    # A GET issued now is answered at "running" and delivered late. Not
    # awaited: `evaluate` would wait out the whole delay, and the race is
    # only a race if the run finishes while the answer is still held.
    await page.evaluate("() => { window.__plugins.loadPlugins(); }")
    for _ in range(100):
        if held:
            break
        await page.wait_for_timeout(20)
    assert held, "the late GET was never answered, so this would prove nothing"
    for plugin in ("alpha@m", "bravo@m", "charlie@m"):
        server.release_plugin(plugin)
    status = page.locator("[data-plugins-status]")
    await expect(status).to_have_text("3 updated, 0 failed, 0 left alone.")
    # Past the held answer's delivery: it arrived, and it lost.
    await page.wait_for_timeout(3500)
    await expect(status).to_have_text("3 updated, 0 failed, 0 left alone.")
    await expect(page.locator("[data-plugins-update]")).to_be_enabled()


async def test_a_refused_press_keeps_its_reason_on_screen(page: Page, server: Harness) -> None:
    """Round 1 of batch 2's review: the repaint after a refusal cleared the
    strip, so `update_in_flight` was never readable (#256's lesson again)."""
    server.seed_plugins(THREE)
    server.seed()
    await open_settings(page, server)
    other = await page.context.new_page()
    await other.goto(f"{server.base}/settings")
    await expect(other.locator("[data-plugins-status]")).to_have_text(
        "Not run since this server started."
    )
    # This page starts a run; the other still shows the button enabled and
    # presses it, which the server refuses.
    await page.locator("[data-plugins-update]").click()
    await expect(page.locator("[data-plugins-status]")).to_have_text(
        "Refreshing the marketplaces."
    )
    await other.evaluate(
        "() => document.querySelector('[data-plugins-update]').disabled = false"
    )
    await other.locator("[data-plugins-update]").click()
    note = other.locator("[data-note]")
    await expect(note).to_contain_text("a plugin update is already running")
    await other.wait_for_timeout(1000)
    await expect(note).to_contain_text("a plugin update is already running")
    for plugin in ("alpha@m", "bravo@m", "charlie@m"):
        server.release_plugin(plugin)
    # Round 2: the fix that kept the refusal kept it for good, so it stood
    # above the next press that DID start a run. That press is a request the
    # person made, and it clears the strip as a settings save does.
    await expect(other.locator("[data-plugins-update]")).to_be_enabled()
    server.reset_plugin_releases()
    await other.locator("[data-plugins-update]").click()
    await expect(other.locator("[data-plugins]")).to_have_attribute("data-state", "running")
    await expect(note).to_be_hidden()
    for plugin in ("alpha@m", "bravo@m", "charlie@m"):
        server.release_plugin(plugin)


async def test_no_restart_notice_when_nothing_was_updated(page: Page, server: Harness) -> None:
    """Round 1 of batch 2's review: removing the `updated` half of the notice's
    condition survived every test. A run that updated nothing changed no
    version, so a running session has nothing to restart for."""
    server.seed_plugins([{"id": "alpha@m", "scope": "user"}])
    server.seed(running=["vessel"])
    await open_settings(page, server)
    status = page.locator("[data-plugins-status]")
    # A first run that updates, so the page has counted the running session:
    # the notice is right there, and the count it read stays behind.
    await page.locator("[data-plugins-update]").click()
    server.release_plugin("alpha@m")
    await expect(status).to_contain_text("keeps the old versions until restarted")
    # A second run that updates nothing must not repeat it.
    server.reset_plugin_releases()
    await page.locator("[data-plugins-update]").click()
    server.release_plugin("alpha@m", fail=True)
    await expect(status).to_have_text("0 updated, 1 failed, 0 left alone.")


async def test_a_run_that_fails_part_way_does_not_say_nothing_was_updated(
    page: Page, server: Harness
) -> None:
    """Round 1 of batch 2's review: `agent_missing` can arrive after rows were
    already updated, and the page said "so nothing was updated" above them."""
    server.seed_plugins(THREE)
    server.seed()
    await open_settings(page, server)
    await page.locator("[data-plugins-update]").click()
    server.release_plugin("alpha@m")
    server.release_plugin("bravo@m", vanish=True)
    status = page.locator("[data-plugins-status]")
    await expect(status).to_have_text(
        "The agent could not be run after 2 plugins, listed below; the rest were not updated."
    )
    await expect(page.locator('[data-plugins-list] li[data-result="updated"]')).to_have_count(2)
    await expect(status).not_to_contain_text("nothing was updated")


async def test_a_page_left_open_across_a_restart_follows_the_new_server(
    page: Page, server: Harness
) -> None:
    """Round 2 of batch 2's review, the high: `seq` starts at 0 again in a new
    process, and a page that had seen a larger one dropped every record the
    new server sent, the idle one included, and then sat on "running" with
    the button disabled after the next press."""
    server.seed_plugins([{"id": "alpha@m", "scope": "user"}])
    server.seed()
    await open_settings(page, server)
    status = page.locator("[data-plugins-status]")
    # Two runs, so the page holds a seq no one run of the new server reaches.
    for _ in range(2):
        server.reset_plugin_releases()
        await page.locator("[data-plugins-update]").click()
        server.release_plugin("alpha@m")
        await expect(status).to_have_text("1 updated, 0 failed, 0 left alone.")

    server.restart()
    # The reconnect's GET is the new process's truth: nothing has run.
    await expect(status).to_have_text("Not run since this server started.", timeout=15_000)
    server.reset_plugin_releases()
    await page.locator("[data-plugins-update]").click()
    server.release_plugin("alpha@m")
    await expect(status).to_have_text("1 updated, 0 failed, 0 left alone.")
    await expect(page.locator("[data-plugins-update]")).to_be_enabled()


async def test_a_settings_refusal_survives_an_interleaved_plugin_success(
    page: Page, server: Harness, tmp_path: Path
) -> None:
    """#315. `settle()` used to be one flag shared by both flows: a plugin
    GET landing in the gap between a refused settings PATCH and that PATCH's
    own repainting GET consumed the "one repaint is owed" flag believing
    itself the owed one, and the settings GET that then arrived found
    nothing left to consume, hit the unconditional clearing branch, and
    wiped the refusal before anyone read it (reproduced from round 3 of
    Phase 21's batch 2 review). The state directory made unwritable is
    #256's own refusal; holding the settings repaint's GET open while a real
    plugin GET succeeds in the gap is the interleaving; the owner recorded on
    the strip is what stops the plugin's success from clearing it."""
    server.seed_plugins([{"id": "alpha@m", "scope": "user"}])
    state = tmp_path / "unwritable"
    state.mkdir()
    server.seed(state_path=state / "state.toml")
    state.chmod(0o500)
    try:
        await open_settings(page, server)
        box = page.locator('[data-root-toggle="main"]')
        await expect(box).to_be_checked()

        held: list[object] = []

        async def hold(route):  # type: ignore[no-untyped-def]
            if route.request.method == "GET":
                response = await route.fetch()
                held.append(response)
                await page.wait_for_timeout(1500)
                await route.fulfill(response=response)
            else:
                await route.continue_()

        await page.route("**/api/config", hold)
        # The PATCH fails (503, the directory cannot be written), then
        # `toggle`'s own repainting GET is what gets held.
        await box.click()
        note = page.locator("[data-note]")
        await expect(note).to_contain_text("Not changed.")

        for _ in range(100):
            if held:
                break
            await page.wait_for_timeout(20)
        assert held, "the settings repaint's GET was never held, so this proves nothing"

        # A genuinely successful plugin request, landing while the settings
        # repaint is still suspended: its own settle() must not be the one
        # that clears a strip the settings flow still owns.
        await page.evaluate("() => window.__plugins.loadPlugins()")
        await expect(note).to_contain_text("Not changed.")

        await page.wait_for_timeout(2000)  # past the held GET's delivery
        await expect(note).to_contain_text("Not changed.")
        await expect(box).to_be_checked()
    finally:
        state.chmod(0o700)


async def test_a_plugin_refusal_survives_an_interleaved_settings_success(
    page: Page, server: Harness
) -> None:
    """#315, the reverse of the case above. A plugin POST refused because a
    run is already going sets its own refusal and is owed a repaint from its
    own GET; an unrelated settings GET succeeding in that gap must not
    settle a strip the plugin flow still owns."""
    server.seed_plugins([{"id": "alpha@m", "scope": "user"}])
    server.seed()
    await open_settings(page, server)
    other = await page.context.new_page()
    await other.goto(f"{server.base}/settings")

    await page.locator("[data-plugins-update]").click()
    await expect(page.locator("[data-plugins-status]")).to_have_text(
        "Refreshing the marketplaces."
    )

    held: list[object] = []

    async def hold(route):  # type: ignore[no-untyped-def]
        if route.request.method == "GET":
            response = await route.fetch()
            held.append(response)
            await other.wait_for_timeout(1500)
            await route.fulfill(response=response)
        else:
            await route.continue_()

    await other.route("**/api/plugins/update", hold)
    await other.evaluate(
        "() => document.querySelector('[data-plugins-update]').disabled = false"
    )
    # The POST is refused (a run is already going), then `startRun`'s own
    # repainting GET is what gets held.
    await other.locator("[data-plugins-update]").click()
    note = other.locator("[data-note]")
    await expect(note).to_contain_text("a plugin update is already running")

    for _ in range(100):
        if held:
            break
        await other.wait_for_timeout(20)
    assert held, "the plugin repaint's GET was never held, so this proves nothing"

    # A genuinely successful settings request, landing while the plugin
    # repaint is still suspended.
    await other.evaluate("() => window.__settings.refresh()")
    await expect(note).to_contain_text("a plugin update is already running")

    await other.wait_for_timeout(2000)  # past the held GET's delivery
    await expect(note).to_contain_text("a plugin update is already running")

    server.release_plugin("alpha@m")


async def test_a_plugin_get_failure_does_not_inherit_a_settings_refusals_owed_repaint(
    page: Page, server: Harness, tmp_path: Path
) -> None:
    """#315, a second gap the owner check alone did not close (round 1 of
    batch 2's review). A settings refusal sets `keepNote` for its OWN
    follow up GET; a plugin GET failing in the gap is a different owner, so
    it is allowed to overwrite the strip's text, but `note()` used to leave
    `keepNote` untouched when it did. The settings repaint's `settle()`
    still correctly refuses to clear a strip it no longer owns, but the
    plugin flow's own next successful GET inherited the settings refusal's
    leftover flag, believed itself the owed repaint, consumed the flag, and
    left its own failure text stuck instead of clearing it."""
    server.seed_plugins([{"id": "alpha@m", "scope": "user"}])
    state = tmp_path / "unwritable"
    state.mkdir()
    server.seed(state_path=state / "state.toml")
    state.chmod(0o500)
    try:
        await open_settings(page, server)
        box = page.locator('[data-root-toggle="main"]')
        await expect(box).to_be_checked()

        held: list[Route] = []
        # An explicit gate, not a fixed sleep: a hold short enough for a fast
        # runner to pass vacuously (the plugin failure never actually lands
        # while the settings GET is still open) would prove nothing, and a
        # hold long enough to be safe on a slow one is still a guess. Released
        # only once the plugin failure has genuinely painted, below.
        release_settings_get = asyncio.Event()
        # Set once `route.fulfill()` has handed the response to the browser.
        # `release_settings_get.set()` alone only wakes `hold_config`; the
        # test must not assert until the FULFILL has actually happened, or it
        # is timing Playwright's own driver round trip, not the repaint (#349).
        settings_get_delivered = asyncio.Event()

        async def hold_config(route: Route) -> None:
            if route.request.method == "GET":
                response = await route.fetch()
                held.append(route)
                await release_settings_get.wait()
                await route.fulfill(response=response)
                settings_get_delivered.set()
            else:
                await route.continue_()

        await page.route("**/api/config", hold_config)
        # The PATCH is refused (the state directory cannot be written); its
        # own repainting GET is what gets held, as in the test above.
        await box.click()
        note = page.locator("[data-note]")
        await expect(note).to_contain_text("Not changed.")

        for _ in range(100):
            if held:
                break
            await page.wait_for_timeout(20)
        assert held, "the settings repaint's GET was never held, so this proves nothing"

        # A plugin GET fails outright, a network error rather than a server
        # answer, while the settings repaint is still suspended. Its note
        # overwrites the settings refusal: a different owner is allowed to,
        # and that overwrite is not the bug under test.
        await page.route("**/api/plugins/update", lambda route: route.abort(), times=1)
        await page.evaluate("() => window.__plugins.loadPlugins()")
        await expect(note).to_have_text(
            "Not connected. The plugin update's state could not be read."
        )

        # Only now, with the plugin failure already on screen, let the held
        # settings GET resolve: `settle()`'s owner guard must not clear a
        # strip the plugin flow now owns.
        #
        # `release_settings_get.set()` alone used to be followed straight by
        # the assertion below (#349): `expect().to_have_text()` checks the
        # CURRENT text and returns at once when it already matches, and it
        # already matched, unchanged, before `hold_config` had even resumed.
        # The guard being tested was never exercised; the test passed with it
        # removed entirely (round 3 of batch 2's review, reproduced). Ordering
        # past `route.fulfill()` is not enough either: the browser still has
        # to run its own `await` chain, through `settle()` and into `render`,
        # before there is anything real to assert on. `render` rebuilds the
        # roots list's CHILDREN from scratch (`replaceChildren`), whether or
        # not any value in them changed; the list itself is not replaced, so
        # marking the current checkbox, not the list, and waiting for that
        # exact node to detach orders the assertion after `settle()`
        # genuinely ran, whichever way it resolved.
        await box.evaluate("(el) => { el.dataset.repaintMarker = '349'; }")
        release_settings_get.set()
        await settings_get_delivered.wait()
        await page.locator('[data-root-toggle="main"][data-repaint-marker="349"]').wait_for(
            state="detached"
        )
        await expect(note).to_have_text(
            "Not connected. The plugin update's state could not be read."
        )

        # The next plugin GET to succeed must clear the strip on its own: a
        # GET failure is never owed a kept repaint, only a refused POST is,
        # so nothing should still be pinning this text here.
        await page.evaluate("() => window.__plugins.loadPlugins()")
        await expect(note).to_be_hidden()
    finally:
        state.chmod(0o700)


async def test_a_restart_during_the_project_count_does_not_win_the_race(
    page: Page, server: Harness
) -> None:
    """#314. `onPluginRecord`'s second check used to be a second
    `isStale(record)`, asking "is THIS record newer than what is shown",
    answered from two epoch strings alone. That question has no answer
    across a restart. Here a `done` record's own `countRunning()` fetch is
    held open while the server restarts: the reconnect's idle record, a new
    epoch, is painted by a separate, un-awaited call while the first is still
    suspended, and old code's `isStale` saw two merely DIFFERENT epochs,
    called that "not stale", and let the dead record win when it resumed."""
    server.seed_plugins([{"id": "alpha@m", "scope": "user"}])
    server.seed()
    await open_settings(page, server)

    held: list[object] = []
    # Long enough that the reconnect's idle record has time to land WHILE
    # this is still open: the race only exists if the dead record resumes
    # AFTER the live one already painted, not merely eventually after it.
    hold_ms = 7000

    async def hold(route):  # type: ignore[no-untyped-def]
        response = await route.fetch()
        held.append(response)
        await page.wait_for_timeout(hold_ms)
        await route.fulfill(response=response)

    await page.route("**/api/projects", hold)
    await page.locator("[data-plugins-update]").click()
    server.release_plugin("alpha@m")
    for _ in range(150):
        if held:
            break
        await page.wait_for_timeout(20)
    assert held, "the done record's countRunning() never reached the held route"

    server.restart()
    status = page.locator("[data-plugins-status]")
    # Proves the race is real: the idle record must land well before the held
    # fetch is due to resolve, or the ordering below tests nothing.
    await expect(status).to_have_text(
        "Not run since this server started.", timeout=hold_ms - 2000
    )

    # Past the held countRunning()'s delivery: the pre-restart done record
    # arrives late and must not overwrite the new process's idle state.
    await page.wait_for_timeout(hold_ms)
    await expect(status).to_have_text("Not run since this server started.")
    await expect(page.locator("[data-plugins-update]")).to_be_enabled()


async def test_a_second_run_overtaking_during_the_project_count_wins(
    page: Page, server: Harness
) -> None:
    """#316. A `done` record's own `countRunning()` fetch is held open; while
    it is suspended, a second run is started by ANOTHER client and reaches
    this page through the stream, with no `await` of its own, and paints
    "Refreshing the marketplaces." immediately. When the held fetch
    resolves, the first (now stale) record must not overwrite what the
    second one already painted.

    This does NOT pin task 134's snapshot formula specifically: within one
    epoch a plain `isStale(record)` re-checked against the live state passes
    it too, since the second run's seq is simply higher (round 1 of Phase 22
    batch 2's review found this passing with 134's fix reverted to the
    pre-134 code). What it guards is that SOME check runs again after the
    await rather than none; the case only 134's fix (and no earlier version)
    gets right is the cross-restart one in
    `test_a_restart_during_the_project_count_does_not_win_the_race` above,
    and the case 134's fix got wrong within one epoch is
    `test_an_older_same_epoch_record_painted_during_the_held_count_must_not_win`
    below."""
    server.seed_plugins([{"id": "alpha@m", "scope": "user"}])
    server.seed()
    await open_settings(page, server)

    held: list[object] = []

    async def hold(route):  # type: ignore[no-untyped-def]
        response = await route.fetch()
        held.append(response)
        await page.wait_for_timeout(2000)
        await route.fulfill(response=response)

    await page.route("**/api/projects", hold)
    await page.locator("[data-plugins-update]").click()
    server.release_plugin("alpha@m")
    for _ in range(150):
        if held:
            break
        await page.wait_for_timeout(20)
    assert held, "the done record's countRunning() never reached the held route"

    other = await page.context.new_page()
    await other.goto(f"{server.base}/settings")
    server.reset_plugin_releases()
    await other.locator("[data-plugins-update]").click()

    status = page.locator("[data-plugins-status]")
    await expect(status).to_have_text("Refreshing the marketplaces.")

    await page.wait_for_timeout(2500)  # past the held countRunning()'s delivery
    await expect(status).to_have_text("Refreshing the marketplaces.")

    server.release_plugin("alpha@m")
    await expect(status).to_have_text("1 updated, 0 failed, 0 left alone.", timeout=15_000)


async def test_an_older_same_epoch_record_painted_during_the_held_count_must_not_win(
    page: Page, server: Harness
) -> None:
    """Round 1 of Phase 22 batch 2's review, the high on task 134's own fix.
    A `done` record's `countRunning()` is held; while it is suspended, an
    OLDER record (lower seq, same epoch, no await of its own) is answered
    and paints. Task 134's snapshot check compared the live epoch and seq
    against what was shown before the await, found them changed by that
    older paint, and bailed, leaving the done record unpainted forever: the
    button stayed disabled and nothing later corrected it, because the done
    record was the run's last event.

    Both records are synthetic, delivered through two plain GETs, because a
    real run's own seq only ever advances by exactly one per broadcast: there
    is no legitimate server state between "the last thing shown" and "the
    next thing after it" to answer an older-but-still-newer GET with. What
    matters is only that some record with a HIGHER seq than what is shown,
    but LOWER than the suspended one, paints while it is suspended.

    Fails on 76a5104 (task 134's snapshot compares beforeEpoch/beforeSeq
    unconditionally: the older paint changes shownSeq, so the done record
    reads itself as overtaken and returns without painting). Passes before
    134 (#314) too: a plain `isStale(record)` re-checked live against
    shownSeq correctly finds 2 not less than 1 and still paints, since both
    records share one epoch, which was never the case 314 got wrong (that
    was only the cross-restart one, still covered by
    `test_a_restart_during_the_project_count_does_not_win_the_race` above).
    It is 134's specific fix that regresses this, so this test's job is
    solely to catch that regression, not to distinguish 134 from before it.
    """
    server.seed_plugins([{"id": "alpha@m", "scope": "user"}])
    server.seed()
    await open_settings(page, server)

    epoch = "e2e-synthetic-epoch"
    # The baseline: painted first so the done record's own pre-await
    # snapshot is taken of THIS epoch, the same one the older record below
    # shares. Skipping it would make the done record's very own arrival the
    # epoch transition (idle's real epoch to this one), which the fix must
    # treat as a restart, not as the within-epoch race under test.
    baseline = {
        "epoch": epoch,
        "boot": SYNTHETIC_BOOT,
        "since_boot_us": 0,
        "seq": 0,
        "state": "running",
        "started_at": 0,
        "finished_at": None,
        "outcomes": [],
        "counts": None,
        "code": None,
        "message": None,
    }
    older = {
        "epoch": epoch,
        "boot": SYNTHETIC_BOOT,
        "since_boot_us": 0,
        "seq": 1,
        "state": "running",
        "started_at": 0,
        "finished_at": None,
        "outcomes": [],
        "counts": None,
        "code": None,
        "message": None,
    }
    newer_done = {
        "epoch": epoch,
        "boot": SYNTHETIC_BOOT,
        "since_boot_us": 0,
        "seq": 2,
        "state": "done",
        "started_at": 0,
        "finished_at": 1,
        "outcomes": [
            {
                "plugin": "alpha@m",
                "scope": "user",
                "result": "updated",
                "detail": None,
                "approved_command": None,
            }
        ],
        "counts": {"updated": 1, "failed": 0, "skipped": 0, "abandoned": 0},
        "code": None,
        "message": None,
    }

    pending_gets: list[Route] = []

    async def capture_get(route: Route) -> None:
        if route.request.method == "GET":
            pending_gets.append(route)
        else:
            await route.continue_()

    held_count: list[tuple[Route, APIResponse]] = []

    async def hold_count(route: Route) -> None:
        response = await route.fetch()
        held_count.append((route, response))

    await page.route("**/api/plugins/update", capture_get)
    await page.route("**/api/projects", hold_count)

    # Paint the baseline first, so the done record's pre-await snapshot is
    # taken of this epoch rather than of the real idle record's.
    await page.evaluate("() => { window.__plugins.loadPlugins(); }")
    for _ in range(100):
        if pending_gets:
            break
        await page.wait_for_timeout(20)
    assert pending_gets, "the baseline GET never reached the route, so this proves nothing"
    await pending_gets.pop(0).fulfill(
        status=200, content_type="application/json", body=json.dumps(baseline)
    )
    status = page.locator("[data-plugins-status]")
    await expect(status).to_have_text("Refreshing the marketplaces.")

    # The done record arrives next and its own countRunning() is what gets
    # held: a real reconnect's GET, or the stream's own "plugins" event,
    # would deliver it the same way onPluginRecord sees it either way.
    await page.evaluate("() => { window.__plugins.loadPlugins(); }")
    for _ in range(100):
        if pending_gets:
            break
        await page.wait_for_timeout(20)
    assert pending_gets, "the done record's GET never reached the route, so this proves nothing"
    await pending_gets.pop(0).fulfill(
        status=200, content_type="application/json", body=json.dumps(newer_done)
    )

    for _ in range(100):
        if held_count:
            break
        await page.wait_for_timeout(20)
    assert held_count, "the done record's countRunning() never reached the held route"

    # The older, lower-seq record answered now and delivered with no await
    # of its own: it paints immediately, ahead of the still-suspended done.
    await page.evaluate("() => { window.__plugins.loadPlugins(); }")
    for _ in range(100):
        if pending_gets:
            break
        await page.wait_for_timeout(20)
    assert pending_gets, "the second GET never reached the route, so this proves nothing"
    await pending_gets.pop(0).fulfill(
        status=200, content_type="application/json", body=json.dumps(older)
    )
    await expect(status).to_have_text("Refreshing the marketplaces.")

    # Release the held countRunning(): the done record is still the newer
    # one and must win, painting over the older record that overtook it.
    count_route, count_response = held_count[0]
    await count_route.fulfill(response=count_response)
    await expect(status).to_have_text("1 updated, 0 failed, 0 left alone.")
    await expect(page.locator("[data-plugins-update]")).to_be_enabled()


async def test_visibility_regained_refreshes_a_run_the_stream_missed(
    page: Page, server: Harness
) -> None:
    """#313. The stream can stay open while the one event marking a run's end
    is exactly the frame the server's bus drops for a slow client, which is
    what a phone that sleeps mid run looks like: the connection never
    notices anything is wrong, so no reconnect ever fires to correct the
    screen. The test models it with a stream that cannot reconnect at all,
    since Playwright cannot drop one SSE frame and keep the connection.
    Coming back from either is what `visibilitychange` is for, and it
    must go through the same `loadPlugins` a reconnect uses, gated by the
    same staleness check (#314), rather than paint anything directly."""
    server.seed_plugins([{"id": "alpha@m", "scope": "user"}])
    server.seed()
    await open_settings(page, server)
    await page.locator("[data-plugins-update]").click()
    await expect(page.locator("[data-plugins-status]")).to_have_text(
        "Refreshing the marketplaces."
    )

    # The run's finishing frame never reaches the page. This does not keep
    # the stream open, as a dropped frame would: it drops the connection and
    # aborts every reconnect, the harsher case of a reconnect that keeps
    # failing (#343). Either way no frame corrects the screen, which is the
    # state `visibilitychange` must recover from, so the test fails without
    # the handler all the same.
    await page.route("**/api/events", lambda route: route.abort())
    server.drop_connections()
    server.release_plugin("alpha@m")
    # #398. The run must be OVER on the server before the page comes back:
    # `visibilitychange` reads the record once, and a read that lands while
    # the run is still finishing paints "Refreshing" again and nothing reads
    # it a second time. A fixed 300ms wait stood in for this and lost under
    # load, failing every run at a load average of 32 on 8 cores. Polled
    # from the test's own request context, which `page.route` does not
    # intercept, so the page's view of the run is still only the stale one.
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        record = await (await page.request.get(f"{server.base}/api/plugins/update")).json()
        if record["state"] == "done":
            break
        await asyncio.sleep(0.05)
    else:
        raise AssertionError(f"the released run never finished on the server: {record}")
    await expect(page.locator("[data-plugins-status]")).to_have_text(
        "Refreshing the marketplaces."
    )

    # The phone comes back to the foreground. No reconnect: the route above
    # still aborts every attempt.
    await page.evaluate(
        "() => {"
        "  Object.defineProperty(document, 'visibilityState', {"
        "    configurable: true, get: () => 'visible'"
        "  });"
        "  document.dispatchEvent(new Event('visibilitychange'));"
        "}"
    )
    await expect(page.locator("[data-plugins-status]")).to_have_text(
        "1 updated, 0 failed, 0 left alone."
    )
    await page.unroute("**/api/events")


async def test_internal_error_reads_as_one_sentence(page: Page, server: Harness) -> None:
    """#317. `internal_error` used to carry its own trailing clause, "; the
    journal has the details", which put the appended "after N plugins" right
    after "details" and read as though the JOURNAL had details after N
    plugins rather than as though the UPDATE stopped after N. A synthetic
    record over the GET (an internal error is not one the fake agent can be
    made to raise) exercises the same `failureText` a real one would reach."""
    server.seed_plugins([{"id": "alpha@m", "scope": "user"}])
    server.seed()
    await open_settings(page, server)

    record = {
        "epoch": "e2e-synthetic-epoch",
        "boot": SYNTHETIC_BOOT,
        "since_boot_us": 0,
        "seq": 1,
        "state": "failed",
        "started_at": 0,
        "finished_at": 1,
        "outcomes": [
            {
                "plugin": "alpha@m",
                "scope": "user",
                "result": "updated",
                "detail": None,
                "approved_command": None,
            }
        ],
        "counts": None,
        "code": "internal_error",
        "message": "the update stopped on an internal error",
    }

    async def answer(route):  # type: ignore[no-untyped-def]
        if route.request.method == "GET":
            await route.fulfill(
                status=200, content_type="application/json", body=json.dumps(record)
            )
        else:
            await route.continue_()

    await page.route("**/api/plugins/update", answer)
    await page.evaluate("() => window.__plugins.loadPlugins()")

    status = page.locator("[data-plugins-status]")
    await expect(status).to_have_text(
        "The update stopped on an error in Hitchrail after 1 plugin, listed "
        "below; the rest were not updated. The journal has the details."
    )


def _synthetic_record(
    epoch: str,
    seq: int,
    state: str,
    *,
    boot: str = SYNTHETIC_BOOT,
    since_boot_us: int = 0,
    **extra: object,
) -> dict[str, object]:
    base: dict[str, object] = {
        "epoch": epoch,
        "boot": boot,
        "since_boot_us": since_boot_us,
        "seq": seq,
        "state": state,
        "started_at": 0,
        "finished_at": None,
        "outcomes": [],
        "counts": None,
        "code": None,
        "message": None,
    }
    base.update(extra)
    return base


# Any, not object: spread into `_synthetic_record`, whose keyword only
# `boot` and `since_boot_us` mypy would otherwise say it might fill.
_DONE_UPDATED_ONE: dict[str, Any] = {
    "counts": {"updated": 1, "failed": 0, "skipped": 0, "abandoned": 0},
    "outcomes": [
        {
            "plugin": "alpha@m",
            "scope": "user",
            "result": "updated",
            "detail": None,
            "approved_command": None,
        }
    ],
}


async def test_a_first_load_done_record_still_wins_over_an_older_same_epoch_answer(
    page: Page, server: Harness
) -> None:
    """Round 2 of the #314 review. `onPluginRecord`'s post await check used
    to compare the live epoch against a snapshot taken before the await
    (`shownEpoch !== beforeEpoch`), which reads as "someone else's restart,
    I lose" even when the epoch that changed is this record's OWN, freshly
    established while it was suspended. Here the very first record this page
    ever sees is `done` and suspends in `countRunning()` with `shownEpoch`
    still `null`; an older answer of that SAME epoch, from a concurrent GET,
    paints first and sets `shownEpoch`; the done record resumes, finds
    `shownEpoch` no longer the `null` it started from, and bails, though it
    is plainly the newer of the two. Fails on HEAD at the final assertion:
    the screen stays on "Refreshing the marketplaces." with the button
    disabled instead of showing the done record's own outcome."""
    server.seed_plugins([{"id": "alpha@m", "scope": "user"}])
    server.seed()

    pending_gets: list[Route] = []

    async def capture_get(route: Route) -> None:
        if route.request.method == "GET":
            pending_gets.append(route)
        else:
            await route.continue_()

    held_count: list[tuple[Route, APIResponse]] = []

    async def hold_count(route: Route) -> None:
        response = await route.fetch()
        held_count.append((route, response))

    await page.route("**/api/plugins/update", capture_get)
    await page.route("**/api/projects", hold_count)

    await page.goto(f"{server.base}/settings")
    for _ in range(100):
        if pending_gets:
            break
        await page.wait_for_timeout(20)
    assert pending_gets, "the initial load's GET never reached the route"

    epoch = "e2e-first-load-epoch"
    # THE FIRST record this page ever processes: `shownEpoch` is `null`, not
    # merely a different real epoch, when this suspends below.
    await pending_gets.pop(0).fulfill(
        status=200,
        content_type="application/json",
        body=json.dumps(_synthetic_record(epoch, 5, "done", **_DONE_UPDATED_ONE)),
    )
    for _ in range(100):
        if held_count:
            break
        await page.wait_for_timeout(20)
    assert held_count, "the done record's countRunning() never reached the held route"

    # An older, but not stale, answer of the SAME epoch, delivered with no
    # await of its own: it is what establishes `shownEpoch` for the first
    # time, while the done record above is still suspended.
    await page.evaluate("() => { window.__plugins.loadPlugins(); }")
    for _ in range(100):
        if pending_gets:
            break
        await page.wait_for_timeout(20)
    assert pending_gets, "the older answer's GET never reached the route"
    await pending_gets.pop(0).fulfill(
        status=200,
        content_type="application/json",
        body=json.dumps(_synthetic_record(epoch, 3, "running")),
    )
    status = page.locator("[data-plugins-status]")
    await expect(status).to_have_text("Refreshing the marketplaces.")

    # Release the held countRunning(): the done record is still the newer of
    # the two, epoch unchanged since it started, and must win.
    count_route, count_response = held_count[0]
    await count_route.fulfill(response=count_response)
    await expect(status).to_have_text("1 updated, 0 failed, 0 left alone.")
    await expect(page.locator("[data-plugins-update]")).to_be_enabled()


async def test_a_reconnect_done_record_still_wins_over_an_older_answer_after_a_restart(
    page: Page, server: Harness
) -> None:
    """The same case as above, from a genuine prior epoch rather than a
    `null` one: the page has already shown a real epoch, the server
    restarts, and the reconnect's own done record suspends in
    `countRunning()` while an older, same-epoch answer paints first. HEAD's
    `shownEpoch !== beforeEpoch` check bails the same way whether the epoch
    it started from was `null` or a real one that has already been shown.
    Fails on HEAD at the final assertion, as above."""
    server.seed_plugins([{"id": "alpha@m", "scope": "user"}])
    server.seed()
    await open_settings(page, server)

    pending_gets: list[Route] = []

    async def capture_get(route: Route) -> None:
        if route.request.method == "GET":
            pending_gets.append(route)
        else:
            await route.continue_()

    held_count: list[tuple[Route, APIResponse]] = []

    async def hold_count(route: Route) -> None:
        response = await route.fetch()
        held_count.append((route, response))

    await page.route("**/api/plugins/update", capture_get)
    await page.route("**/api/projects", hold_count)

    server.restart()
    for _ in range(750):
        if pending_gets:
            break
        await page.wait_for_timeout(20)
    assert pending_gets, "the reconnect's own GET never reached the route"

    epoch = "e2e-restarted-epoch"
    await pending_gets.pop(0).fulfill(
        status=200,
        content_type="application/json",
        body=json.dumps(_synthetic_record(epoch, 5, "done", **_DONE_UPDATED_ONE)),
    )
    for _ in range(100):
        if held_count:
            break
        await page.wait_for_timeout(20)
    assert held_count, "the done record's countRunning() never reached the held route"

    await page.evaluate("() => { window.__plugins.loadPlugins(); }")
    for _ in range(100):
        if pending_gets:
            break
        await page.wait_for_timeout(20)
    assert pending_gets, "the older answer's GET never reached the route"
    await pending_gets.pop(0).fulfill(
        status=200,
        content_type="application/json",
        body=json.dumps(_synthetic_record(epoch, 3, "running")),
    )
    status = page.locator("[data-plugins-status]")
    await expect(status).to_have_text("Refreshing the marketplaces.")

    count_route, count_response = held_count[0]
    await count_route.fulfill(response=count_response)
    await expect(status).to_have_text("1 updated, 0 failed, 0 left alone.")
    await expect(page.locator("[data-plugins-update]")).to_be_enabled()


async def test_a_late_record_of_an_older_process_never_paints_over_a_newer_one(
    page: Page, server: Harness
) -> None:
    """ABA. A late answer from a process that has already been replaced is
    DIFFERENT from what is shown, and "a different epoch always wins" let it
    win right back over the live process, along with a second record of the
    same dead process that had sat suspended in `countRunning()` the whole
    time. Since #348 both lose because E1 started earlier in the same boot
    (`since_boot_us`), whatever `seq` they carry and whenever they arrive;
    before it they lost only because E1 had been painted over first."""
    server.seed_plugins([{"id": "alpha@m", "scope": "user"}])
    server.seed()

    pending_gets: list[Route] = []

    async def capture_get(route: Route) -> None:
        if route.request.method == "GET":
            pending_gets.append(route)
        else:
            await route.continue_()

    held_count: list[tuple[Route, APIResponse]] = []

    async def hold_count(route: Route) -> None:
        response = await route.fetch()
        held_count.append((route, response))

    await page.route("**/api/plugins/update", capture_get)
    await page.route("**/api/projects", hold_count)

    async def fulfill_next(body: dict[str, object]) -> None:
        for _ in range(100):
            if pending_gets:
                break
            await page.wait_for_timeout(20)
        assert pending_gets, "a GET never reached the route"
        await pending_gets.pop(0).fulfill(
            status=200, content_type="application/json", body=json.dumps(body)
        )

    await page.goto(f"{server.base}/settings")
    # Establishes E1 as `shownEpoch`.
    await fulfill_next(_synthetic_record("e1", 0, "running", since_boot_us=1))
    status = page.locator("[data-plugins-status]")
    await expect(status).to_have_text("Refreshing the marketplaces.")

    # An E1 record that sits suspended in countRunning() for the rest of the
    # test: released only at the very end.
    await page.evaluate("() => { window.__plugins.loadPlugins(); }")
    await fulfill_next(
        _synthetic_record("e1", 10, "done", since_boot_us=1, **_DONE_UPDATED_ONE)
    )
    for _ in range(100):
        if held_count:
            break
        await page.wait_for_timeout(20)
    assert held_count, "the awaiting E1 record's countRunning() never reached the held route"

    # E2 replaces E1 on screen: the same boot, started later.
    await page.evaluate("() => { window.__plugins.loadPlugins(); }")
    await fulfill_next(_synthetic_record("e2", 0, "running", since_boot_us=2))
    await expect(status).to_have_text("Refreshing the marketplaces.")

    # A LATE E1 record, from before the E1 to E2 transition, delivered only
    # now. Its own outcome ("1 left alone") is distinct from anything E2 has
    # shown, so painting it is unambiguous.
    await page.evaluate("() => { window.__plugins.loadPlugins(); }")
    await fulfill_next(
        _synthetic_record(
            "e1", 5, "done", since_boot_us=1, counts={"updated": 0, "failed": 0, "skipped": 1}
        )
    )
    await expect(status).to_have_text("Refreshing the marketplaces.")

    # Release the awaiting E1 record from the start: older, it must not
    # revive E1 either, whatever `seq` it carries.
    count_route, count_response = held_count[0]
    await count_route.fulfill(response=count_response)
    await expect(status).to_have_text("Refreshing the marketplaces.")
    await expect(page.locator("[data-plugins-update]")).to_be_disabled()


async def test_a_restart_during_a_page_load_leaves_the_strip_on_the_new_server(
    page: Page, server: Harness
) -> None:
    """#348. A fresh load's first record is the old process's `done`, which
    suspends in `countRunning()`; the server restarts, and the new process's
    idle record paints while it is suspended. On `18397c7` the old record
    then resumed, painted as though it were new, and retired the live epoch:
    every later record of the new server was dropped and the button stayed
    disabled after the next run. Here the order comes from the server, and
    the old process started earlier on the boot clock."""
    server.seed_plugins([{"id": "alpha@m", "scope": "user"}])
    server.seed()
    await open_settings(page, server)
    status = page.locator("[data-plugins-status]")
    button = page.locator("[data-plugins-update]")
    await button.click()
    server.release_plugin("alpha@m")
    await expect(status).to_have_text("1 updated, 0 failed, 0 left alone.")

    held: list[Route] = []

    # Only `countRunning()`'s requests, which send `accept` rather than
    # `content-type`: app.js's listing retry runs while the server is down and
    # must reach it. EVERY one is held, since the load can deliver the old
    # `done` record more than once, and a copy let through paints the old
    # epoch before the restart, where even the page before #348 retires it
    # and the test proves nothing. None is fetched: a `route.fetch()` whose
    # timing crosses the restart dies with "socket hang up", which failed
    # #348's first CI run and about one local run in three after it.
    async def hold(route: Route) -> None:
        if route.request.headers.get("accept") != "application/json":
            await route.continue_()
            return
        held.append(route)

    await page.route("**/api/projects", hold)
    await page.reload()
    for _ in range(250):
        if held:
            break
        await page.wait_for_timeout(20)
    assert held, "the load's done record never reached countRunning(), so this proves nothing"

    server.restart()
    await expect(status).to_have_text("Not run since this server started.", timeout=15_000)

    for route in held:
        await route.fulfill(json={"projects": []})
    await page.unroute("**/api/projects")
    # Nothing to wait on when the dead record is dropped, so give it the
    # time a repaint takes, then prove the new server is still followed.
    await page.wait_for_timeout(500)
    await expect(status).to_have_text("Not run since this server started.")

    server.reset_plugin_releases()
    await button.click()
    await expect(status).to_have_text("Refreshing the marketplaces.")
    server.release_plugin("alpha@m")
    await expect(status).to_have_text("1 updated, 0 failed, 0 left alone.")
    await expect(button).to_be_enabled()


async def test_a_record_of_another_boot_suspended_across_a_newer_paint_loses(
    page: Page, server: Harness
) -> None:
    """#348. Boot ids carry no order, so across boots the page takes the
    record that ARRIVED later, stamped before the await. A record that
    arrived first and merely RESUMES last must not count as the later one:
    stamping at paint time instead would reopen the lockout across a
    reboot."""
    server.seed_plugins([{"id": "alpha@m", "scope": "user"}])
    server.seed()

    pending_gets: list[Route] = []

    async def capture_get(route: Route) -> None:
        if route.request.method == "GET":
            pending_gets.append(route)
        else:
            await route.continue_()

    held_count: list[tuple[Route, APIResponse]] = []

    async def hold_count(route: Route) -> None:
        held_count.append((route, await route.fetch()))

    await page.route("**/api/plugins/update", capture_get)
    await page.route("**/api/projects", hold_count)

    async def fulfill_next(body: dict[str, object]) -> None:
        for _ in range(100):
            if pending_gets:
                break
            await page.wait_for_timeout(20)
        assert pending_gets, "a GET never reached the route"
        await pending_gets.pop(0).fulfill(
            status=200, content_type="application/json", body=json.dumps(body)
        )

    await page.goto(f"{server.base}/settings")
    # The old boot's done record, a much LATER boot clock reading than the
    # new boot's: were boot clocks compared across boots, it would win.
    await fulfill_next(
        _synthetic_record(
            "old", 7, "done", boot="boot-a", since_boot_us=10**12, **_DONE_UPDATED_ONE
        )
    )
    for _ in range(100):
        if held_count:
            break
        await page.wait_for_timeout(20)
    assert held_count, "the old boot's countRunning() never reached the held route"

    await page.evaluate("() => { window.__plugins.loadPlugins(); }")
    await fulfill_next(_synthetic_record("new", 0, "idle", boot="boot-b", since_boot_us=1))
    status = page.locator("[data-plugins-status]")
    await expect(status).to_have_text("Not run since this server started.")

    count_route, count_response = held_count[0]
    await count_route.fulfill(response=count_response)
    await page.wait_for_timeout(500)
    await expect(status).to_have_text("Not run since this server started.")
    await expect(page.locator("[data-plugins-update]")).to_be_enabled()


async def _show_record(page: Page, record: dict[str, object]) -> None:
    async def answer(route):  # type: ignore[no-untyped-def]
        if route.request.method == "GET":
            await route.fulfill(
                status=200, content_type="application/json", body=json.dumps(record)
            )
        else:
            await route.continue_()

    await page.route("**/api/plugins/update", answer)
    await page.evaluate("() => window.__plugins.loadPlugins()")


async def test_a_shutdown_before_the_listing_reads_as_one_sentence(
    page: Page, server: Harness
) -> None:
    """#370. The page had no `shutting_down` entry, so `failureText` fell
    back to the server's message, which already ends "so nothing was
    updated", and appended its own: the clause twice."""
    server.seed()
    await open_settings(page, server)
    await _show_record(
        page,
        _synthetic_record(
            "e2e-synthetic-epoch",
            1,
            "failed",
            code="shutting_down",
            message="the server was shutting down, so nothing was updated",
        ),
    )
    await expect(page.locator("[data-plugins-status]")).to_have_text(
        "The server was shutting down, so nothing was updated."
    )


async def test_a_run_cut_short_counts_what_never_started(page: Page, server: Harness) -> None:
    """#370. The done sentence counted three results of four, so a run the
    shutdown cut short summed to fewer rows than it listed."""
    server.seed()
    await open_settings(page, server)
    row = {"scope": "user", "detail": None, "approved_command": None}
    await _show_record(
        page,
        _synthetic_record(
            "e2e-synthetic-epoch",
            1,
            "done",
            finished_at=1,
            outcomes=[
                {**row, "plugin": "a@m", "result": "updated"},
                {
                    **row,
                    "plugin": "b@m",
                    "result": "abandoned",
                    "detail": "never started: the server was shutting down",
                },
            ],
            counts={"updated": 1, "failed": 0, "skipped": 0, "abandoned": 1},
        ),
    )
    await expect(page.locator("[data-plugins-status]")).to_have_text(
        "1 updated, 0 failed, 0 left alone, 1 never started."
    )
