"""Capture the interface, so the README can show it rather than describe it.

Not a test. It asserts almost nothing and its output is a directory of PNGs; it
lives here because the harness that boots a real server against a temporary
root with a fake agent is the only thing that can produce an honest picture,
and duplicating that in a script would be a second way to launch the app.

**Deselected by default**, by `-m "not screenshots"` in `addopts`. Run it on
purpose:

    uv run pytest -m screenshots

**Three decisions #105 asked to be made explicitly rather than fall out of the
first implementation:**

- **PNG, not SVG.** Playwright can emit either and SVG diffs far better, but it
  renders the DOM rather than photographing it, so it would not show the font
  substitution and the layout crush that made three of this project's visual
  defects visible.
- **Committed, not generated into an ignored directory.** GitHub renders a
  README from the repository, so images that exist only on a release are images
  the README cannot show. The weight is accepted and mitigated by regenerating
  at a release rather than on every interface change.
- **A stale image does NOT fail a check.** A pixel comparison is flaky across
  font versions and machines, and a flaky gate gets disabled. What is asserted
  instead is that every shot produced a file large enough to be a rendered page.
  Freshness is a release step, not a test.

**Nothing here may photograph the machine it runs on.** The world is seeded from
the fake agent shim, so no screenshot carries a real project name. That is the
one part of #106 that outlived its closure: a screenshot is content this project
creates rather than history it inherits.

**A project name was not the only thing that could leak.** The first capture
showed `/tmp/pytest-of-<username>/pytest-2786/hr0` in the page header, because
the interface displays the root it was given and `tmp_path_factory` builds that
path from the account name. The picture was accurate and it published a
username.

Hence `shots_server`: the same harness on a neutral root. Fixing the ROOT rather
than the pixels matters, because an image edited afterwards is no longer a
render of the running application, which is the whole reason #105 asked for
these to be captured rather than taken by hand.
"""

from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import tempfile
from collections.abc import Iterator

import pytest
from playwright.async_api import Page, ViewportSize, expect

from .conftest import Harness

pytestmark = [pytest.mark.e2e, pytest.mark.screenshots]

SHOTS = pathlib.Path(__file__).resolve().parents[2] / "docs" / "screenshots"

# Every segment neutral, because the interface displays this path.
SHOT_ROOT = pathlib.Path(tempfile.gettempdir()) / "hitchrail-demo" / "projects"

# The case the project exists for, at the CSS width of the phones it was walked
# on, and a desktop width for the wide layout.
PHONE = ViewportSize(width=360, height=780)
DESKTOP = ViewportSize(width=1280, height=860)


# Four derived states in one listing, so `detached` with its pid and `stale`
# appear rather than only the happy path. Names are fixtures, not projects.
def _seed_the_world(harness: Harness) -> None:
    """Spelled out rather than a `**dict`, which defeats `seed`'s typed
    signature and hides a misspelled state behind a mypy error per call."""
    harness.seed(
        running=["vessel", "harbour"],
        stopped=["anchor"],
        detached=["drifter"],
        stale=["remnant"],
    )


@pytest.fixture
def shots_server() -> Iterator[Harness]:
    """The `server` fixture with a root that is safe to photograph.

    Identical otherwise, including the private tmux socket and the scoped
    teardown: only sessions on this socket are killed, never a bare
    `tmux kill-server`.
    """
    if shutil.which("tmux") is None:  # pragma: no cover - CI installs tmux
        pytest.skip("the browser tier drives a real tmux")

    shutil.rmtree(SHOT_ROOT.parent, ignore_errors=True)
    SHOT_ROOT.mkdir(parents=True)
    # Short, for the reason the tier's own fixture gives: a unix socket path is
    # capped near 108 bytes and a long temp path fails as a confusing ENOENT.
    sock_dir = tempfile.mkdtemp(prefix="hrsh")
    sock = str(pathlib.Path(sock_dir) / "s")
    harness = Harness(SHOT_ROOT, sock)
    try:
        yield harness
    finally:
        harness.stop_serving()
        harness.reap_orphans()
        subprocess.run(
            ["tmux", "-S", sock, "kill-server"],
            capture_output=True,
            text=True,
            env={k: v for k, v in os.environ.items() if k != "TMUX"},
            check=False,
        )
        shutil.rmtree(sock_dir, ignore_errors=True)
        shutil.rmtree(SHOT_ROOT.parent, ignore_errors=True)


async def _settled(page: Page, harness: Harness) -> None:
    await expect(page.locator(f'[data-project="{harness.project("vessel")}"]')).to_be_visible(
        timeout=15_000
    )
    # The memory footer arrives after the first poll. Without this, half the
    # captures show a page mid render, which is worse than no picture.
    await page.wait_for_timeout(600)


async def _shoot(page: Page, name: str) -> None:
    SHOTS.mkdir(parents=True, exist_ok=True)
    path = SHOTS / f"{name}.png"
    await page.screenshot(path=str(path), full_page=False)
    assert path.stat().st_size > 5_000, f"{name}.png is too small to be a rendered page"


async def test_capture_the_phone_list(page: Page, shots_server: Harness) -> None:
    """The headline image: four states at a phone width."""
    await page.set_viewport_size(PHONE)
    _seed_the_world(shots_server)
    await page.goto(shots_server.base)
    await _settled(page, shots_server)
    await _shoot(page, "phone-list")


async def test_capture_two_roots_on_a_phone(page: Page, shots_server: Harness) -> None:
    """#122's own exit criterion: two identically named rows told apart at a
    phone width, shown rather than described.

    This is the picture the phase exists for. Before the qualified identifier
    these were one row, and stopping it stopped the other project's agent.
    """
    await page.set_viewport_size(PHONE)
    shots_server.seed(
        running=["vessel", "harbour"],
        stopped=["anchor"],
        also_in={"personal": ["vessel"]},
    )
    await page.goto(shots_server.base)
    await _settled(page, shots_server)
    # **Both rows RUNNING**, not merely both present. If one is still settling
    # the picture shows two rows differing in state as well as in root, and a
    # reader would reasonably conclude the state is what tells them apart. The
    # root chip has to be the only difference for the image to make its point.
    # The BADGE, not `data-state`. #88's `awaiting_input` is an overlay: the
    # row is `data-state="running"` while the badge reads `waiting`, so waiting
    # on the attribute passed with the picture still showing two different
    # badges. What a reader compares is the badge, so that is what to wait on.
    for label in ("main", "personal"):
        row = page.locator(f'[data-project="{shots_server.project("vessel", label)}"]')
        await expect(row.locator(".badge")).to_have_text("running", timeout=15_000)
    await _shoot(page, "phone-two-roots")


async def test_capture_the_phone_list_dark(page: Page, shots_server: Harness) -> None:
    """Dark is a first class requirement in the design, so it gets a picture
    rather than a sentence."""
    await page.set_viewport_size(PHONE)
    await page.emulate_media(color_scheme="dark")
    _seed_the_world(shots_server)
    await page.goto(shots_server.base)
    await _settled(page, shots_server)
    await _shoot(page, "phone-list-dark")


async def test_capture_the_desktop_list(page: Page, shots_server: Harness) -> None:
    await page.set_viewport_size(DESKTOP)
    _seed_the_world(shots_server)
    await page.goto(shots_server.base)
    await _settled(page, shots_server)
    await _shoot(page, "desktop-list")


async def test_capture_the_log_drawer(page: Page, shots_server: Harness) -> None:
    """The drawer with real output in it, which is what makes it legible."""
    await page.set_viewport_size(PHONE)
    _seed_the_world(shots_server)
    await page.goto(shots_server.base)
    await _settled(page, shots_server)
    row = page.locator(f'[data-project="{shots_server.project("vessel")}"]')
    logs = row.get_by_role("button", name="Logs")
    if await logs.count():
        await logs.first.click()
        await page.wait_for_timeout(800)
    await _shoot(page, "phone-logs")


async def test_capture_the_new_folder_sheet(page: Page, shots_server: Harness) -> None:
    await page.set_viewport_size(PHONE)
    _seed_the_world(shots_server)
    await page.goto(shots_server.base)
    await _settled(page, shots_server)
    new = page.get_by_role("button", name="New")
    if await new.count():
        await new.first.click()
        await page.wait_for_timeout(500)
    await _shoot(page, "phone-new-folder")


async def test_capture_the_grant_page(page: Page, shots_server: Harness) -> None:
    """The first thing anybody reaching this over a network sees."""
    await page.set_viewport_size(PHONE)
    shots_server.seed(stopped=["vessel"], token="s3cret-key-value")
    await page.goto(f"{shots_server.base}/grant")
    await page.wait_for_timeout(600)
    await _shoot(page, "phone-grant")
