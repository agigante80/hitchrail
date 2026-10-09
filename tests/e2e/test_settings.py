"""#154 and #238: the settings page, on a real browser at a phone width.

The hermetic tier proves the routes. What only this tier can prove is the
page: that the perimeter is text and not a disabled input, that a checkbox
row is a 44px target at 390px, that hiding a root removes its rows from the
list without ending its agent, and that a stop wait the SERVER chose is the
one the wait dialog actually keeps, which is the bug the ticket opened with.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from playwright.async_api import Page, expect

from .conftest import Harness

pytestmark = pytest.mark.e2e

TWO_ROOTS = {"personal": ["vessel"]}


async def test_the_page_holds_at_a_phone_width_and_shows_the_perimeter_as_text(
    page: Page, server: Harness
) -> None:
    server.seed(running=["vessel"], also_in=TWO_ROOTS)
    await page.goto(server.base)
    await page.get_by_role("link", name="Settings").click()
    await expect(page.locator("[data-settings]")).to_have_attribute("data-loaded", "")

    # No horizontal scroll: the page fits the viewport it was designed for.
    assert await page.evaluate(
        "() => document.documentElement.scrollWidth <= document.documentElement.clientWidth"
    )
    # Every root is a row with a checkbox, and the row is the tap target.
    rows = page.locator("[data-roots] li")
    await expect(rows).to_have_count(2)
    for i in range(2):
        box = await rows.nth(i).locator("label").bounding_box()
        assert box is not None and box["height"] >= 44, box
    # The perimeter: text with a source, and not one input among it.
    facts = page.locator("[data-facts]")
    await expect(facts.locator('[data-fact="host"] .settings-value')).to_have_text("127.0.0.1")
    await expect(facts.locator('[data-fact="host"] .settings-source')).to_have_text(
        "the default"
    )
    assert await facts.locator("input, select, textarea, button").count() == 0
    # The token is its source alone; on a loopback bind there is none, and
    # the page says that rather than showing an empty value.
    await expect(facts.locator('[data-fact="token"] .settings-value')).to_have_text("")
    await expect(facts.locator('[data-fact="token"] .settings-source')).to_have_text(
        "none: loopback only"
    )


async def test_hiding_a_root_removes_its_rows_and_leaves_its_agent_running(
    page: Page, server: Harness, tmp_path: Path
) -> None:
    """The unhappy path #154 names, on the machine rather than on a fake: the
    root toggled off holds a RUNNING project, and after the toggle its agent
    is still alive and the list simply no longer shows it. Then a reload,
    and then a restart, because "persists" means both."""
    server.seed(running=["vessel"], also_in=TWO_ROOTS, state_path=tmp_path / "s" / "state.toml")
    await page.goto(server.base)
    personal = page.locator(f'[data-project="{server.project("vessel", "personal")}"]')
    await expect(personal).to_have_attribute("data-state", "running", timeout=15_000)

    await page.goto(f"{server.base}/settings")
    box = page.locator('[data-root-toggle="personal"]')
    await expect(box).to_be_checked()
    await box.click()
    await expect(box).not_to_be_checked()
    await expect(
        page.locator('[data-roots] li[data-label="personal"] .settings-source')
    ).to_have_text("hidden here")

    await page.goto(server.base)
    work = page.locator(f'[data-project="{server.project("vessel")}"]')
    await expect(work).to_be_visible()
    await expect(personal).to_have_count(0)
    # One root shown means no chips, as one root configured never had them.
    assert await page.locator("[data-roots] button").count() == 0
    assert server.is_running("vessel", "personal"), "hiding the root ended its agent"

    await page.reload()
    await expect(work).to_be_visible()
    await expect(personal).to_have_count(0)

    server.restart()
    await page.goto(server.base)
    await expect(work).to_be_visible()
    await expect(personal).to_have_count(0)
    assert server.is_running("vessel", "personal")

    # And back, from the page.
    await page.goto(f"{server.base}/settings")
    await page.locator('[data-root-toggle="personal"]').click()
    await page.goto(server.base)
    await expect(personal).to_have_attribute("data-state", "running", timeout=15_000)


async def test_every_root_hidden_says_so_rather_than_no_folder(
    page: Page, server: Harness
) -> None:
    server.seed(stopped=["vessel"])
    await page.goto(f"{server.base}/settings")
    await page.locator('[data-root-toggle="main"]').click()
    await expect(page.locator('[data-root-toggle="main"]')).not_to_be_checked()
    await page.goto(server.base)
    await expect(page.locator("[data-empty-reason]")).to_contain_text(
        "Every root is hidden (main)"
    )


async def test_a_visible_empty_root_beside_a_hidden_one_is_not_every_root_hidden(
    page: Page, server: Harness
) -> None:
    """#256. The sentence fired on zero PROJECTS, so a root that is merely
    empty beside a hidden one read as "every root is hidden", which is a
    claim about the configuration made from the contents of a folder. The
    question is whether any root is being listed at all."""
    # A label of its own, not `personal`: the root directories are named for
    # the label under one parent, so a label another test in this module has
    # already filled would arrive here holding that test's folders.
    server.seed(stopped_in={"vacant": []})
    await page.goto(f"{server.base}/settings")
    await page.locator('[data-root-toggle="main"]').click()
    await expect(page.locator('[data-root-toggle="main"]')).not_to_be_checked()
    await page.goto(server.base)
    reason = page.locator("[data-empty-reason]")
    await expect(reason).to_contain_text("No folder here.")
    assert "Every root is hidden" not in (await reason.text_content() or "")


async def test_a_root_the_operator_disabled_is_not_something_to_show_in_settings(
    page: Page, server: Harness
) -> None:
    """#256. It told somebody to show a root in settings that the config
    file disables, where the checkbox is greyed out because no request can
    bring it back. The empty state names the file instead."""
    server.seed(stopped_in={"vacant": []}, disabled_roots=["main", "vacant"])
    await page.goto(server.base)
    reason = page.locator("[data-empty-reason]")
    await expect(reason).to_contain_text("by the config file")
    await expect(reason).to_contain_text("Enable one there")


async def test_a_refused_toggle_keeps_its_reason_through_the_repaint(
    page: Page, server: Harness, tmp_path: Path
) -> None:
    """#256. On a refusal the page repaints from a GET so the checkbox goes
    back where the truth is, and that GET cleared the note: the person saw a
    checkbox that would not stay checked and no sentence saying why. Here
    the state directory cannot be written, which is the 503 the ticket
    names, and the message survives the repaint."""
    state = tmp_path / "unwritable"
    state.mkdir()
    server.seed(running=["vessel"], also_in=TWO_ROOTS, state_path=state / "state.toml")
    state.chmod(0o500)
    try:
        await page.goto(f"{server.base}/settings")
        box = page.locator('[data-root-toggle="personal"]')
        await expect(box).to_be_checked()
        await box.click()
        note = page.locator("[data-note]")
        await expect(note).to_contain_text("Not changed.")
        # The checkbox is back where the server's answer says it is, and the
        # sentence explaining that is still on screen.
        await expect(box).to_be_checked()
        await expect(note).to_be_visible()
        await expect(note).to_contain_text("Not changed.")
    finally:
        state.chmod(0o700)


async def test_a_local_refusal_does_not_outlive_a_toggle_that_worked(
    page: Page, server: Harness, tmp_path: Path
) -> None:
    """#281. A wait out of range is refused in the page with no request, so
    no repaint consumed the refusal's flag, and the next toggle's success
    spent it clearing nothing: "Not changed" stood over a change that was
    made."""
    server.seed(stopped=["vessel"], also_in=TWO_ROOTS, state_path=tmp_path / "s" / "state.toml")
    await page.goto(f"{server.base}/settings")
    await page.locator("[data-stop-timeout]").fill("0")
    await page.locator("[data-stop-save]").click()
    note = page.locator("[data-note]")
    await expect(note).to_contain_text("Not changed.")
    box = page.locator('[data-root-toggle="personal"]')
    await box.click()
    await expect(
        page.locator('[data-roots] li[data-label="personal"] .settings-source')
    ).to_have_text("hidden here")
    await expect(note).to_be_hidden()


async def test_the_wait_dialog_keeps_the_servers_stop_timeout(
    page: Page, server: Harness
) -> None:
    """The bug #238 opened with: the page gave up at thirty seconds whatever
    the server was told. Here the server waits two seconds and the page is
    NOT told through the test seam, so what the dialog does after two
    seconds is what the server's figure did."""
    server.seed(running=["vessel"], ignores_graceful_stop=True, stop_timeout=2)
    await page.goto(server.base)
    row = page.locator(f'[data-project="{server.project("vessel")}"]')
    await expect(row).to_have_attribute("data-state", "running", timeout=15_000)
    await row.get_by_role("button", name="Stop").click()
    await page.locator("[data-dialog]").get_by_role("button", name="Stop", exact=True).click()
    await expect(page.locator("[data-dialog]")).to_contain_text(
        f"No answer from {server.project('vessel')}", timeout=8_000
    )


async def test_the_stop_wait_is_edited_here_and_a_flag_pins_it(
    page: Page, server: Harness, tmp_path: Path
) -> None:
    server.seed(stopped=["vessel"], state_path=tmp_path / "s" / "state.toml")
    await page.goto(f"{server.base}/settings")
    field = page.locator("[data-stop-timeout]")
    await expect(field).to_have_value("30")
    await field.fill("45")
    await page.locator("[data-stop-save]").click()
    await expect(page.locator("[data-stop-source]")).to_contain_text("Currently 45s, set here")
    server.restart()
    await page.reload()
    await expect(page.locator("[data-stop-timeout]")).to_have_value("45")
    # The page reads the server's figure, not its own memory of it: once the
    # listing has landed, the wait it would keep is the one set above.
    await page.goto(server.base)
    await expect(page.locator(f'[data-project="{server.project("vessel")}"]')).to_be_visible()
    patience = await page.evaluate("() => window.__hitchrail.stopTimeoutMs()")
    assert patience == 45_000


async def test_a_flag_pins_the_stop_wait_as_text(page: Page, server: Harness) -> None:
    server.seed(stopped=["vessel"], stop_timeout=60, pinned_stop_timeout=True)
    await page.goto(f"{server.base}/settings")
    await expect(page.locator("[data-stop-source]")).to_contain_text(
        "60s, from the command line"
    )
    assert await page.locator("[data-stop-timeout]").is_hidden()
    assert await page.locator("[data-stop-save]").is_hidden()


# -- #323: Appearance ---------------------------------------------------------

_BODY = "getComputedStyle(document.body).backgroundColor"
_DARK, _LIGHT = "rgb(54, 45, 36)", "rgb(243, 236, 225)"


async def test_appearance_applies_live_remembers_and_returns_to_the_system(
    page: Page, server: Harness
) -> None:
    """The header toggle can only land on Light or Dark, so this is the one way
    back to following the device. The key is the toggle's own, so the list page
    reads what was picked here, and System is its absence."""
    server.seed(stopped=["vessel"])
    await page.emulate_media(color_scheme="light")
    await page.goto(f"{server.base}/settings")
    group = page.get_by_role("radiogroup", name="Appearance")
    await expect(group.get_by_role("radio", name="System")).to_be_checked()

    await group.get_by_role("radio", name="Dark").check()
    assert await page.evaluate(_BODY) == _DARK
    assert await page.evaluate("localStorage.getItem('hitchrail-theme')") == "dark"
    await page.reload()
    await expect(group.get_by_role("radio", name="Dark")).to_be_checked()
    assert await page.evaluate(_BODY) == _DARK
    await page.goto(server.base)
    assert await page.evaluate(_BODY) == _DARK

    await page.goto(f"{server.base}/settings")
    await group.get_by_role("radio", name="System").check()
    assert await page.evaluate("localStorage.getItem('hitchrail-theme')") is None
    assert await page.evaluate(_BODY) == _LIGHT
    await page.emulate_media(color_scheme="dark")
    assert await page.evaluate(_BODY) == _DARK, "System no longer follows the device"
    await group.get_by_role("radio", name="Light").check()
    assert await page.evaluate(_BODY) == _LIGHT


async def test_appearance_still_applies_when_the_browser_will_not_store(
    page: Page, server: Harness
) -> None:
    """A private window throws on localStorage in some browsers. The choice
    then lasts for the page view, and the page does not stop working."""
    server.seed(stopped=["vessel"])
    await page.add_init_script(
        """
        Storage.prototype.getItem = () => { throw new Error('blocked'); };
        Storage.prototype.setItem = () => { throw new Error('blocked'); };
        Storage.prototype.removeItem = () => { throw new Error('blocked'); };
        """
    )
    await page.emulate_media(color_scheme="light")
    await page.goto(f"{server.base}/settings")
    group = page.get_by_role("radiogroup", name="Appearance")
    await expect(group.get_by_role("radio", name="System")).to_be_checked()
    await group.get_by_role("radio", name="Dark").check()
    assert await page.evaluate(_BODY) == _DARK
    await group.get_by_role("radio", name="System").check()
    assert await page.evaluate(_BODY) == _LIGHT


_SCHEME = "getComputedStyle(document.documentElement).colorScheme"


@pytest.mark.parametrize(("system", "chosen"), [("dark", "Light"), ("light", "Dark")])
async def test_native_controls_follow_a_choice_opposite_to_the_system(
    page: Page, server: Harness, system: str, chosen: str
) -> None:
    """#470. The meta's `light dark` drew native controls in the system scheme,
    so Light on a dark phone left every unselected radio a dark filled disc
    that read as selected. System must keep following the device: the meta never
    shows in the computed style, so `normal` is the rule leaving it in charge."""
    server.seed(stopped=["vessel"])
    await page.emulate_media(color_scheme=system)  # type: ignore[arg-type]
    await page.goto(f"{server.base}/settings")
    assert await page.evaluate(_SCHEME) == "normal"
    group = page.get_by_role("radiogroup", name="Appearance")
    await group.get_by_role("radio", name=chosen).check()
    assert await page.evaluate(_SCHEME) == chosen.lower()
    await group.get_by_role("radio", name="System").check()
    assert await page.evaluate(_SCHEME) == "normal"
