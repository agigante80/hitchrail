"""#53: the page, the palette, and both themes."""

from __future__ import annotations

import pytest
from playwright.async_api import Page, expect

from .conftest import Harness

pytestmark = pytest.mark.e2e


async def test_the_page_loads_and_names_the_root(page: Page, server: Harness) -> None:
    server.seed(stopped=["vessel"])
    await page.goto(server.base)
    await expect(page.get_by_role("heading", name="hitchrail")).to_be_visible()
    await expect(page.locator("[data-root]")).to_contain_text(str(server.root))


async def test_the_assets_are_served_and_are_not_a_404_page(
    page: Page, server: Harness
) -> None:
    """A 404 body still renders, so `to_be_visible` alone would pass against a
    missing stylesheet. Assert the response, not the appearance."""
    server.seed()
    css = await page.request.get(f"{server.base}/app.css")
    js = await page.request.get(f"{server.base}/app.js")
    assert css.status == 200, css.status
    assert "text/css" in css.headers["content-type"]
    assert js.status == 200, js.status
    assert "javascript" in js.headers["content-type"]


async def test_no_asset_route_can_be_talked_into_serving_another_file(
    page: Page, server: Harness
) -> None:
    """The security content of this ticket. The asset routes take no path
    parameter, so there is no request that reaches a file this module did not
    name. Traversal is not refused; it is unreachable."""
    server.seed()
    for attempt in (
        "/../pyproject.toml",
        "/app.css/../../../etc/passwd",
        "/%2e%2e/%2e%2e/etc/passwd",
        "/app.js%00.css",
    ):
        response = await page.request.get(f"{server.base}{attempt}")
        assert response.status in (301, 307, 404), f"{attempt} -> {response.status}"
        assert "root:" not in await response.text(), f"{attempt} served /etc/passwd"


async def test_nothing_is_smaller_than_the_touch_target(page: Page, server: Harness) -> None:
    """44px, from section 7. Measured rather than eyeballed, because this is
    the requirement a stylesheet change breaks silently."""
    server.seed(stopped=["vessel", "koala"])
    await page.set_viewport_size({"width": 390, "height": 844})
    await page.goto(server.base)
    small = await page.evaluate(
        """() => [...document.querySelectorAll('button, a, input, [role=button]')]
             .map(el => ({ t: (el.textContent || el.type || '').trim().slice(0, 24),
                           h: el.getBoundingClientRect().height }))
             .filter(x => x.h > 0 && x.h < 44)"""
    )
    assert small == [], f"controls under the 44px minimum: {small}"


async def test_the_body_has_an_explicit_background_in_both_themes(
    page: Page, server: Harness
) -> None:
    """A transparent body borrows whatever is behind it, which is how a dark
    page ends up with light text on white."""
    server.seed()
    await page.emulate_media(color_scheme="light")
    await page.goto(server.base)
    assert (
        await page.evaluate("getComputedStyle(document.body).backgroundColor")
        == "rgb(243, 236, 225)"
    )
    await page.emulate_media(color_scheme="dark")
    assert (
        await page.evaluate("getComputedStyle(document.body).backgroundColor")
        == "rgb(54, 45, 36)"
    )


async def test_dark_is_a_token_swap_not_a_second_stylesheet(
    page: Page, server: Harness
) -> None:
    """Section 7 calls dark first class. Two stylesheets decay the moment
    somebody edits one of them, so there is one, plus the font sheet."""
    server.seed()
    await page.emulate_media(color_scheme="dark")
    await page.goto(server.base)
    own = await page.evaluate(
        """() => [...document.styleSheets]
             .filter(s => s.href && !s.href.includes('fonts.googleapis')).length"""
    )
    assert own == 1, f"{own} stylesheets of our own; dark must be a token swap"


async def test_an_explicit_choice_wins_over_the_system_preference(
    page: Page, server: Harness
) -> None:
    """Both directions. A page that follows the system and ignores an explicit
    choice is one that fights the person using it."""
    server.seed()
    await page.emulate_media(color_scheme="light")
    await page.goto(server.base)
    await page.get_by_role("button", name="Dark").click()
    assert (
        await page.evaluate("getComputedStyle(document.body).backgroundColor")
        == "rgb(54, 45, 36)"
    )

    await page.emulate_media(color_scheme="dark")
    await page.get_by_role("button", name="Light").click()
    assert (
        await page.evaluate("getComputedStyle(document.body).backgroundColor")
        == "rgb(243, 236, 225)"
    )


async def test_the_chosen_theme_survives_a_reload(page: Page, server: Harness) -> None:
    server.seed()
    await page.emulate_media(color_scheme="light")
    await page.goto(server.base)
    await page.get_by_role("button", name="Dark").click()
    await page.reload()
    assert (
        await page.evaluate("getComputedStyle(document.body).backgroundColor")
        == "rgb(54, 45, 36)"
    )


async def test_the_page_is_behind_the_token_like_every_other_route(
    page: Page, server: Harness
) -> None:
    """Serving the shell unauthenticated is a change to the security boundary
    and it is #21's to argue, not this route's to assume."""
    server.seed(token="s3cret")
    for path in ("/", "/app.css", "/app.js"):
        assert (await page.request.get(f"{server.base}{path}")).status == 401, path
