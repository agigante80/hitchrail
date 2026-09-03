"""#77: a policy the browser actually accepts, which no other tier can show.

Every other assertion about the CSP is about the string we emit. Whether that
string lets the application work is decided by the browser parsing it, and a
policy that is one directive too strict breaks the page silently: the shell
renders nothing, the fonts fall back, and every unit test still passes because
the header is exactly what we said it would be.

This is the tier that would notice.
"""

from __future__ import annotations

import pytest
from playwright.async_api import ConsoleMessage, Page, expect

from .conftest import Harness

pytestmark = pytest.mark.e2e

TOKEN = "s3cret-key-value"


def _csp_violations(page: Page) -> list[str]:
    """Chromium reports a blocked subresource or fetch as a console error
    naming the directive, and Playwright surfaces those. Verified by blocking
    `connect-src` on purpose:

        Connecting to 'http://.../api/grant' violates the following Content
        Security Policy directive: "default-src 'none'"

    Collected rather than asserted per message, so a failure reports every
    violation at once instead of the first.
    """
    seen: list[str] = []

    def note(message: ConsoleMessage) -> None:
        text = message.text
        if "Content Security Policy" in text or "Refused to" in text:
            seen.append(text)

    page.on("console", note)
    page.on("pageerror", lambda error: seen.append(f"pageerror: {error}"))
    return seen


async def _reach_the_shell(page: Page, server: Harness, violations: list[str]) -> None:
    """Walk grant to shell, and report a CSP violation as the CAUSE.

    Without this the first failure of this file said "element(s) not found"
    while the console held `Refused to connect because it violates the
    document's Content Security Policy`. The functional assertion fires before
    the violation assertion, so the useful message has to be carried into it.
    """
    await page.goto(f"{server.base}/grant#token={TOKEN}")
    locator = page.locator(f'[data-project="{server.project("vessel")}"]')
    try:
        await expect(locator).to_be_visible(timeout=15_000)
    except AssertionError as exc:  # pragma: no cover - only on a broken policy
        if violations:
            raise AssertionError(f"the policy blocked the page: {violations}") from exc
        raise


async def test_the_grant_page_works_under_its_own_policy(page: Page, server: Harness) -> None:
    """The grant page is inline script and inline style behind a sha256 hash.

    A wrong hash blocks the script, the page never trades the token, and the
    only symptom is that nothing happens. That is exactly the failure a hash
    based policy invites, so it is the one worth driving.
    """
    server.seed(stopped=["vessel"], token=TOKEN)
    violations = _csp_violations(page)

    # Reaching the shell means the inline script ran, read the fragment, traded
    # it and redirected. Every step of that is something the policy could
    # block, and `connect-src` did block the trade in the first version of it.
    await _reach_the_shell(page, server, violations)
    assert not violations, violations


async def test_the_shell_loads_every_asset_under_its_own_policy(
    page: Page, server: Harness
) -> None:
    """`default-src 'self'` has to cover app.css, app.js and six font routes.

    #76 is what makes that possible: the faces were fetched from Google, so a
    policy strict enough to be worth having would have broken the page. They
    are served from here now.
    """
    server.seed(stopped=["vessel"], token=TOKEN)
    violations = _csp_violations(page)

    await _reach_the_shell(page, server, violations)

    # The stylesheet applied, so style-src let it through. Asserted through a
    # computed style rather than the header, because the header being right and
    # the sheet being blocked look identical from the server.
    font = await page.evaluate("getComputedStyle(document.body).fontFamily")
    assert font, "no computed font family, so the stylesheet did not apply"

    loaded = await page.evaluate("document.fonts.size")
    assert loaded, "no font faces registered, so font-src blocked them"
    assert not violations, violations


async def test_every_response_refuses_to_be_framed(page: Page, server: Harness) -> None:
    """The exposure #77 is actually about, asserted on a live socket rather
    than through ASGITransport: a page that guesses an allowlisted hostname
    frames `/grant` and draws its own chrome around the password field."""
    server.seed(stopped=["vessel"], token=TOKEN)
    response = await page.goto(f"{server.base}/grant")
    assert response is not None
    assert response.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert response.headers["x-content-type-options"] == "nosniff"
