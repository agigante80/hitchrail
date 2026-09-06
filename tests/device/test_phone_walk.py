"""The flows a person actually does from a phone, on a phone.

Short on purpose. This tier is slow and needs hardware on the desk, so it walks
what a headless engine at the same CSS width cannot vouch for, rather than
re-asserting what `tests/e2e/` already covers.
"""

from __future__ import annotations

import pytest
from playwright.async_api import Page, expect

from e2e.conftest import Harness, e2e_name

pytestmark = pytest.mark.device


async def test_the_listing_renders_on_a_real_phone(
    device_server: Harness, phone_page: Page
) -> None:
    """The product's whole point, on the device it was designed for.

    The e2e tier asserts this at 360 CSS pixels in headless Chromium. This
    asserts it in the browser the operator actually uses, at that device's own
    font scaling and pixel density, over a real network hop.
    """
    device_server.seed(running=["vessel"], stopped=["anchor"])
    await phone_page.goto(device_server.base)

    running = phone_page.locator(f'[data-project="{device_server.project("vessel")}"]')
    stopped = phone_page.locator(f'[data-project="{device_server.project("anchor")}"]')
    await expect(running).to_be_visible(timeout=20_000)
    await expect(stopped).to_be_visible()
    await expect(running).to_have_attribute("data-state", "running")
    await expect(stopped.get_by_role("button", name="Start")).to_be_visible()


async def test_a_running_rows_controls_fit_the_phone(
    device_server: Harness, phone_page: Page
) -> None:
    """#103's shape, on hardware: the controls must be reachable, not just present.

    A row crushed to one character per line still passes a visibility check, so
    this asserts the row's own box is wider than it is tall. That is the
    property that broke on a real device and that a viewport-only test read as
    fine.
    """
    device_server.seed(running=["vessel"])
    await phone_page.goto(device_server.base)

    row = phone_page.locator(f'[data-project="{device_server.project("vessel")}"]')
    await expect(row).to_be_visible(timeout=20_000)
    for control in ("Open", "Get link", "Stop"):
        await expect(row.get_by_role("button", name=control)).to_be_visible()

    box = await row.bounding_box()
    assert box is not None, "the row has no box on the device, so nothing can be tapped"
    assert box["width"] > box["height"], (
        f"the row is {box['width']:.0f}x{box['height']:.0f} on this phone, taller than "
        f"it is wide, which is what a name crushed to one character per line looks "
        f"like. See #103."
    )


async def test_the_folder_name_is_not_wrapped_to_a_column(
    device_server: Harness, phone_page: Page
) -> None:
    """The specific defect #75 found by hand, pinned on the device that found it."""
    device_server.seed(running=["long-hyphenated-name"])
    await phone_page.goto(device_server.base)

    name = e2e_name("long-hyphenated-name")
    row = phone_page.locator(
        f'[data-project="{device_server.project("long-hyphenated-name")}"]'
    )
    await expect(row).to_be_visible(timeout=20_000)

    heading = row.get_by_text(name, exact=True)
    box = await heading.bounding_box()
    assert box is not None, f"{name} did not render a box on the phone"
    assert box["height"] < 100, (
        f"{name} is {box['height']:.0f}px tall on this phone, which is several lines: "
        f"the name is wrapping rather than fitting or eliding. See #103 and #75."
    )
