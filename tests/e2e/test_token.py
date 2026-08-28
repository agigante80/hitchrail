"""#21: the grant travels in a fragment, which no server ever sees.

The browser tier is the only one that can show this. A fragment is not sent in
the request, so the assertion that matters is about what the SERVER saw, and
only a real browser decides what to send.
"""

from __future__ import annotations

import pytest
from playwright.async_api import Page, expect

from .conftest import Harness

pytestmark = pytest.mark.e2e

TOKEN = "s3cret-key-value"


async def test_the_fragment_never_reaches_the_server(page: Page, server: Harness) -> None:
    """What the browser SENDS, which is not the same as what the server saw.

    Worth being exact about, because the obvious reading of this test is wrong.
    Playwright records the URL after the browser has already stripped the
    fragment, so this cannot fail on account of the fragment: what it does
    constrain is that the page never BUILDS a url carrying the key, which is
    the mistake a person would actually make (`fetch("/api/grant?token=" + t)`,
    verified to turn this red). The server side assertion, against the access
    line uvicorn writes, is #78 and reuses #20's live socket machinery.
    """
    server.seed(stopped=["vessel"], token=TOKEN)
    seen: list[str] = []
    page.on("request", lambda request: seen.append(request.url))

    await page.goto(f"{server.base}/grant#token={TOKEN}")
    await expect(page.locator(f'[data-project="{server.project("vessel")}"]')).to_be_visible(
        timeout=15_000
    )

    assert seen, "no requests were recorded"
    leaked = [url for url in seen if TOKEN in url]
    assert not leaked, leaked
    # And the grant page itself fetched nothing but itself and the grant.
    # A self contained page is a security property here, not a performance one:
    # it is the only page served without a token, so anything it reaches for is
    # either a 401 or a request to somebody else carrying a `Referer`.
    #
    # Sliced at the navigation to `/`, because everything after that is the app
    # loading its own assets, which is a different page with a cookie.
    paths = [url.removeprefix(server.base) for url in seen]
    assert f"{server.base}/" in seen, seen
    cut = paths.index("/")
    before = paths[:cut]
    assert before == ["/grant", "/api/grant"], before
    assert all(url.startswith(server.base) for url in seen[:cut]), seen[:cut]


async def test_the_grant_leaves_the_address_bar(page: Page, server: Harness) -> None:
    server.seed(stopped=["vessel"], token=TOKEN)
    await page.goto(f"{server.base}/grant#token={TOKEN}")
    await expect(page.locator(f'[data-project="{server.project("vessel")}"]')).to_be_visible(
        timeout=15_000
    )
    assert TOKEN not in page.url, page.url


async def test_the_cookie_survives_a_reload_so_the_link_is_used_once(
    page: Page, server: Harness
) -> None:
    server.seed(stopped=["vessel"], token=TOKEN)
    await page.goto(f"{server.base}/grant#token={TOKEN}")
    row = page.locator(f'[data-project="{server.project("vessel")}"]')
    await expect(row).to_be_visible(timeout=15_000)

    await page.goto(server.base)
    await expect(row).to_be_visible()


async def test_the_grant_page_is_the_only_thing_reachable_without_the_key(
    page: Page, server: Harness
) -> None:
    server.seed(stopped=["vessel"], token=TOKEN)
    for path in ("/", "/app.js", "/app.css", "/api/projects", "/api/events"):
        response = await page.request.get(f"{server.base}{path}")
        assert response.status == 401, f"{path} -> {response.status}"
    assert (await page.request.get(f"{server.base}/grant")).status == 200


async def test_an_arrival_with_no_key_can_type_one(page: Page, server: Harness) -> None:
    """A person who opens the address without the fragment must see something
    they can act on. A raw JSON 401 in a browser window is a dead end."""
    server.seed(stopped=["vessel"], token=TOKEN)
    await page.goto(f"{server.base}/grant")

    await expect(page.get_by_role("dialog")).to_contain_text(
        "Anyone with this key can run code on that machine as you."
    )
    field = page.get_by_label("Access key")
    assert await field.get_attribute("type") == "password", "the key was shown in clear"

    await field.fill(TOKEN)
    await page.get_by_role("button", name="Unlock").click()
    await expect(page.locator(f'[data-project="{server.project("vessel")}"]')).to_be_visible(
        timeout=15_000
    )


async def test_a_wrong_key_says_so_without_confirming_anything(
    page: Page, server: Harness
) -> None:
    """A wrong key and a missing one are indistinguishable at the API. The
    screen must not become the oracle the middleware refuses to be."""
    server.seed(stopped=["vessel"], token=TOKEN)
    await page.goto(f"{server.base}/grant")

    await page.get_by_label("Access key").fill("not-the-key")
    await page.get_by_role("button", name="Unlock").click()

    alert = page.get_by_role("alert")
    await expect(alert).to_be_visible()
    await expect(alert).to_contain_text("not accepted")
    assert "not-the-key" not in await alert.inner_text(), "the screen echoed the attempt"
    assert page.url.endswith("/grant"), page.url


async def test_a_rejected_fragment_does_not_sit_in_the_address_bar(
    page: Page, server: Harness
) -> None:
    """The key is cleared BEFORE the request, not after it.

    This is the assertion that holds that line, for BOTH outcomes. On success
    the page navigates away, so the address bar ends up clean whether or not
    anything cleared it, and a test written against the success path passes for
    a build that never clears anything. Only the rejected key stays on the
    page long enough for the difference to show, which is also the case where
    it matters: it would sit in the address bar, and in the history entry that
    syncs to every signed in device, for as long as the person stares at the
    failure.
    """
    server.seed(stopped=["vessel"], token=TOKEN)
    await page.goto(f"{server.base}/grant#token=not-the-key")

    await expect(page.get_by_role("alert")).to_be_visible(timeout=15_000)
    assert "not-the-key" not in page.url, page.url


async def test_an_api_caller_still_gets_json(page: Page, server: Harness) -> None:
    """The exemption is one PATH, not a content type rule. Were it
    `Accept: text/html` on any 401, the API would start answering a script with
    HTML the moment somebody sent a browser shaped header."""
    server.seed(stopped=["vessel"], token=TOKEN)
    response = await page.request.get(
        f"{server.base}/api/projects", headers={"accept": "text/html"}
    )
    assert response.status == 401
    assert "application/json" in response.headers["content-type"]
