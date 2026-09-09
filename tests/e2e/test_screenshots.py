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
import re
import shutil
import subprocess
import tempfile
from collections.abc import Iterator

import pytest
from playwright.async_api import Locator, Page, ViewportSize, expect

from . import conftest as e2e_conftest
from .conftest import SHOT_PREFIX, Harness

pytestmark = [pytest.mark.e2e, pytest.mark.screenshots]

SHOTS = pathlib.Path(__file__).resolve().parents[2] / "docs" / "screenshots"

# Every segment neutral, because the interface displays this path.
#
# **Fixed, so this tier is single instance by construction (#214).** The fixture
# `rmtree`s it at setup, so two concurrent capture runs delete each other's root
# and both fail confusingly. That is accepted rather than fixed, and the reason
# has to be the true one: an earlier note here said the tier "runs deliberately
# at a release, never twice at once", and that was false. `AGENTS.md` documents
# `uv run pytest -m e2e` as the browser tier's command, and any `-m` replaces
# the `-m "not screenshots"` in `addopts`, so an ordinary developer running the
# browser tier used to capture these images.
#
# The real reason is that the path is PHOTOGRAPHED. A run identity in it reaches
# `docs/screenshots/` and the README, which is the same rule `SHOT_PREFIX`
# follows and states, so it cannot carry a pid the way `E2E_PREFIX` does.
#
# What makes the collision unlikely now is not luck: the collection hook in
# `tests/conftest.py` means this tier runs only when a run asks for
# `-m screenshots` by name, so two concurrent captures take two people deciding
# to capture at once rather than one person running the tier next door.
SHOT_ROOT = pathlib.Path(tempfile.gettempdir()) / "hitchrail-demo" / "projects"

# The case the project exists for, at the CSS width of the phones it was walked
# on, and a desktop width for the wide layout.
PHONE = ViewportSize(width=360, height=780)
DESKTOP = ViewportSize(width=1280, height=860)


# Four derived states in one listing, so `detached` with its pid and `stale`
# appear rather than only the happy path. Names are fixtures, not projects.
def _seed_the_world(harness: Harness) -> None:
    """Spelled out rather than a `**dict`, which defeats `seed`'s typed
    signature and hides a misspelled state behind a mypy error per call.

    **`detached` stays, and with it a real pid in the published images (#215).**
    Decided 2026-09-07 rather than left as an oversight, because every way of
    removing it is worse:

    - Dropping `detached` loses the state the code itself calls "the one a naive
      tool gets wrong", and `README.md`'s alt text advertises it: "detached with
      its pid".
    - Faking the pid through `Engine`'s `procs_fn` seam corrupts the picture.
      `derive` walks the process TREE by pid, `descendants`, `first_matching_in_tree`,
      `by_pid`, while pane pids come from real tmux, so a rewritten table
      desynchronises the two and changes the STATES rendered.
    - Masking it at capture time is possible, Playwright takes `mask` and
      `style`, but `metaFor` returns one string into one `<p class="meta">`, so
      the mask covers the whole line and not the pid. Masking precisely needs the
      pid wrapped in its own element, which is a DOM change made for a test's
      benefit: the move #216 refused when it declined to add `--tmux-socket`.

    So the pid is published, knowingly. It is a uid-space process id from a
    development machine, it identifies no person, and the ticket calls it
    harmless in itself. What it costs is a readable diff: four of seven images
    change on every capture, from the pid and from `up 0s` versus `up 1s`, so a
    screenshot refresh cannot be reviewed. That is accepted and is why a capture
    now recaptures only what it is asked for.
    """
    harness.seed(
        running=["vessel", "harbour"],
        stopped=["anchor"],
        detached=["drifter"],
        stale=["remnant"],
    )


@pytest.fixture
def shots_server(monkeypatch: pytest.MonkeyPatch) -> Iterator[Harness]:
    """The `server` fixture with a root that is safe to photograph.

    Identical otherwise, including the private tmux socket and the scoped
    teardown: only sessions on this socket are killed, never a bare
    `tmux kill-server`.
    """
    # **Fails rather than skips**, which is exit criterion 2 (#237). A skip here
    # made the browser tier's result depend on what the machine has, and left
    # `ci.yml`'s grep for `skipped` as the only thing that noticed.
    assert shutil.which("tmux") is not None, (
        "tmux is not installed, and this tier FAILS rather than skips (criterion 2).\n"
        "\n"
        "The roadmap's second exit criterion is that no tier's result depends on "
        "what the machine happens to have, and it allows exactly one exception: a "
        "tier may require hardware if it is opt in and FAILS when the hardware is "
        "absent. `device` is that exception. This tier used to skip, which made "
        "its result depend on the machine after all, and a CI grep for the word "
        "`skipped` was the only thing noticing.\n"
        "\n"
        "tmux is a RUNTIME prerequisite of Hitchrail, not an optional extra, so a "
        "machine without it cannot run the tool either. Install it, or deselect "
        "this tier by name."
    )

    # Pinned for the duration, so the published images carry no run identity.
    #
    # `monkeypatch` rather than a manual save and restore. The manual version
    # rebound the global BEFORE its `try`, and three statements that can raise
    # sat between them: `SHOT_ROOT` is a fixed shared path, `rmtree` swallows
    # its errors, and the `mkdir` after it can raise. The override would then
    # outlive the fixture and every later e2e test in that session would run
    # under a constant prefix, which is #177's contamination re-armed.
    monkeypatch.setattr(e2e_conftest, "E2E_PREFIX", SHOT_PREFIX)

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


def row(page: Page, harness: Harness, name: str) -> Locator:
    """The row for a seeded project, which is what most captures prove on."""
    return page.locator(f'[data-project="{harness.project(name)}"]')


async def _shoot(page: Page, name: str, showing: Locator) -> None:
    """Photograph the page, having first proved it is showing the right thing.

    **`showing` is required, and that is the fix for #215.** Two captures here
    guarded their click with `if await control.count():` and then shot
    regardless, so when the control was not found the tier photographed whatever
    was on screen and passed. `phone-logs.png` shipped as a copy of
    `phone-list.png` for months because of it: the control is named `Open`, not
    `Logs`, so the count was zero every time.

    The assertion in this tier IS the picture, and a picture nothing checks is
    the same rotten green as a test with no assertion. Making the proof a
    parameter rather than a convention means a new capture cannot be added
    without naming what makes its image the thing it claims to be.
    """
    await expect(showing).to_be_visible()
    SHOTS.mkdir(parents=True, exist_ok=True)
    path = SHOTS / f"{name}.png"

    # **Checked on the surface being photographed, immediately before the
    # shutter.** A test asserting `SHOT_PREFIX` has no digits pins the CONSTANT
    # and not its USE: review proved that deleting the pin from `shots_server`
    # left the whole suite green while every image came back reading
    # `hrx1569650-anchor`, which is the exact regression the constant check was
    # written for.
    #
    # This cannot be true and the image still wrong, because it reads what the
    # page actually rendered. It fails the capture rather than publishing a bad
    # one, which is the only moment that matters: these six PNGs are what the
    # README shows to strangers.
    rendered = await page.locator("[data-project]").evaluate_all(
        "els => els.map(e => e.getAttribute('data-project'))"
    )
    carrying_identity = [value for value in rendered if re.search(r"hrx\d", value or "")]
    assert not carrying_identity, (
        f"{name}.png would publish run identity in {carrying_identity}. The shots "
        f"tier must pin SHOT_PREFIX; see #177 and README.md's alt text."
    )

    await page.screenshot(path=str(path), full_page=False)
    assert path.stat().st_size > 5_000, f"{name}.png is too small to be a rendered page"


async def test_capture_the_phone_list(page: Page, shots_server: Harness) -> None:
    """The headline image: four states at a phone width."""
    await page.set_viewport_size(PHONE)
    _seed_the_world(shots_server)
    await page.goto(shots_server.base)
    await _settled(page, shots_server)
    await _shoot(page, "phone-list", row(page, shots_server, "vessel"))


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
    await _shoot(page, "phone-two-roots", page.locator("[data-project]").first)


async def test_capture_the_phone_list_dark(page: Page, shots_server: Harness) -> None:
    """Dark is a first class requirement in the design, so it gets a picture
    rather than a sentence."""
    await page.set_viewport_size(PHONE)
    await page.emulate_media(color_scheme="dark")
    _seed_the_world(shots_server)
    await page.goto(shots_server.base)
    await _settled(page, shots_server)
    await _shoot(page, "phone-list-dark", row(page, shots_server, "vessel"))


async def test_capture_the_desktop_list(page: Page, shots_server: Harness) -> None:
    await page.set_viewport_size(DESKTOP)
    _seed_the_world(shots_server)
    await page.goto(shots_server.base)
    await _settled(page, shots_server)
    await _shoot(page, "desktop-list", row(page, shots_server, "vessel"))


async def test_capture_the_log_drawer(page: Page, shots_server: Harness) -> None:
    """The drawer with real output in it, which is what makes it legible."""
    await page.set_viewport_size(PHONE)
    _seed_the_world(shots_server)
    await page.goto(shots_server.base)
    await _settled(page, shots_server)
    # **`Open`, not `Logs`.** The control has never been called Logs; `app.js`
    # names it `Open`. The old lookup found nothing every time, and because the
    # click was guarded rather than asserted, the tier photographed the plain
    # list and published it as the drawer (#215).
    await row(page, shots_server, "vessel").get_by_role("button", name="Open").click()
    drawer = page.locator("[data-dialog]")
    await expect(drawer).to_contain_text("last 40 lines of the pane")
    await _shoot(page, "phone-logs", drawer)


async def test_capture_the_new_folder_sheet(page: Page, shots_server: Harness) -> None:
    await page.set_viewport_size(PHONE)
    _seed_the_world(shots_server)
    await page.goto(shots_server.base)
    await _settled(page, shots_server)
    await page.get_by_role("button", name="New").click()
    sheet = page.locator("[data-dialog]")
    await expect(sheet).to_contain_text("New folder")
    await _shoot(page, "phone-new-folder", sheet)


async def test_capture_the_grant_page(page: Page, shots_server: Harness) -> None:
    """The first thing anybody reaching this over a network sees."""
    await page.set_viewport_size(PHONE)
    shots_server.seed(stopped=["vessel"], token="s3cret-key-value")
    await page.goto(f"{shots_server.base}/grant")
    await page.wait_for_timeout(600)
    await _shoot(page, "phone-grant", page.get_by_label("Access key"))
