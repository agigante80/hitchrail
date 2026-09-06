"""The tier that drives a REAL phone, over wireless adb.

Every other tier renders the phone layout at a phone's CSS width in headless
Chromium, which is a good proxy and is not a phone. It cannot see a soft
keyboard covering a button, a browser that clears storage between loads, a tap
target too small for a thumb, or a Chrome three versions ahead of the one CI
installs. #75 found four such defects by hand on two Android devices, and #104
exists because a walk done by hand happens once.

**Deselected by default, like the screenshot tier and for the same reason.** It
needs hardware that is not in CI and is not always on the desk, and `AGENTS.md`
is explicit that a tier which skips everywhere looks like coverage while proving
less than none. This one is never silently skipped, because it is never silently
selected:

    uv run pytest -m device

## How the phone reaches a server bound to loopback

`adb reverse tcp:P tcp:P` makes the phone's own `127.0.0.1:P` reach THIS
machine's loopback.

**The server is on loopback and not on the LAN address, and the first reason is
not negotiable:** the live Hitchrail on this machine serves the operator's real
project roots, and a test must never drive that. The second is that the token
requirement keys on the bind address, so a loopback server needs none and the
walk exercises the interface rather than the grant flow, which `test_token.py`
already covers.

## How assertions read the phone

`adb forward tcp:N localabstract:chrome_devtools_remote` exposes the device
Chrome's DevTools endpoint on this machine, and Playwright connects to it with
`connect_over_cdp`. So the tier gets the same locators and `expect` the e2e tier
uses, driving a real browser on real hardware.

**`uiautomator dump` was tried first and does not work here.** It waits for the
window to go idle before dumping, and this interface never goes idle: there is a
live SSE stream and a reconnect indicator. It returns empty output rather than an
error, which reads as "the page is blank" when the page is fine. Recorded because
it is the obvious first approach and it fails quietly.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import tempfile
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from playwright.async_api import Browser, Page, async_playwright

from e2e.conftest import Harness

# The Pixel 2 on LineageOS. **The port is NOT stable**: Android picks a new one
# every time wireless debugging is toggled, so a failure to connect is more
# likely a stale port than a missing phone.
DEFAULT_SERIAL = os.environ.get("HITCHRAIL_DEVICE", "192.168.33.22:40321")

ADB_TIMEOUT_S = 20.0


def _adb(serial: str, *args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["adb", "-s", serial, *args],
        capture_output=True,
        text=True,
        timeout=ADB_TIMEOUT_S,
        check=False,
    )
    if check and result.returncode != 0:
        raise AssertionError(f"adb {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _connected(serial: str) -> bool:
    listed = subprocess.run(
        ["adb", "devices"], capture_output=True, text=True, timeout=ADB_TIMEOUT_S, check=False
    ).stdout
    return any(
        line.startswith(serial) and line.rstrip().endswith("device")
        for line in listed.splitlines()
    )


@pytest.fixture(scope="session")
def device_serial() -> str:
    if not _connected(DEFAULT_SERIAL):
        subprocess.run(
            ["adb", "connect", DEFAULT_SERIAL],
            capture_output=True,
            timeout=ADB_TIMEOUT_S,
            check=False,
        )
    if not _connected(DEFAULT_SERIAL):
        pytest.fail(
            f"no device at {DEFAULT_SERIAL}. Wireless debugging picks a NEW port every "
            f"time it is toggled, so check Settings > Developer options > Wireless "
            f"debugging for the current one and pass it as HITCHRAIL_DEVICE. Failing "
            f"rather than skipping, because this tier is opt in: being selected means "
            f"somebody asked for it, and a silent skip would be the coverage lie "
            f"AGENTS.md names."
        )
    return DEFAULT_SERIAL


@pytest.fixture
async def device_browser(device_serial: str) -> AsyncIterator[Browser]:
    """The phone's own Chrome, driven over CDP.

    **Function scoped, not session scoped, and that is not a preference.** An
    async fixture at session scope needs an event loop at session scope, and
    `asyncio_mode = "auto"` gives function scoped loops. The mismatch does not
    error: the whole tier hangs until something kills it, with no output at all,
    which reads as the phone being unreachable. Measured at 280s of nothing.

    Reconnecting per test costs about a second against a walk that takes twenty,
    so the saving was never worth the trap.
    """
    port = _free_port()
    _adb(device_serial, "forward", f"tcp:{port}", "localabstract:chrome_devtools_remote")
    try:
        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
            # **Never `browser.close()` here.** Every other tier owns the browser
            # it launched; this one ATTACHED to the operator's real Chrome, and
            # closing it would shut the browser on their phone. Leaving the scope
            # of `async_playwright` disconnects, which is the whole teardown this
            # needs. Individual tabs are closed by `phone_page`.
            yield browser
    finally:
        _adb(device_serial, "forward", "--remove", f"tcp:{port}", check=False)


@pytest.fixture
async def phone_page(device_browser: Browser) -> AsyncIterator[Page]:
    """One real tab, closed afterwards so tabs do not accumulate on the device."""
    context = device_browser.contexts[0]
    page = await context.new_page()
    try:
        yield page
    finally:
        await page.close()


@pytest.fixture
def device_server(
    device_serial: str, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[Harness]:
    """A real Hitchrail on loopback, reachable from the phone, on a throwaway root."""
    if shutil.which("tmux") is None:
        pytest.fail("this tier drives a real tmux")

    root = tmp_path_factory.mktemp("hrdev")
    # Short, for the reason every tier here gives: a unix socket path is capped
    # near 108 bytes and a pytest temp path can exceed it.
    sock_dir = tempfile.mkdtemp(prefix="hrdv")
    sock = str(Path(sock_dir) / "s")
    harness = Harness(root, sock)

    _adb(device_serial, "reverse", f"tcp:{harness.port}", f"tcp:{harness.port}")
    try:
        yield harness
    finally:
        _adb(device_serial, "reverse", "--remove", f"tcp:{harness.port}", check=False)
        harness.stop_serving()
        harness.reap_orphans()
        subprocess.run(
            ["tmux", "-S", sock, "kill-server"],
            capture_output=True,
            text=True,
            env={k: v for k, v in os.environ.items() if k != "TMUX"},
            check=False,
        )
        harness.wait_until_the_agents_are_gone()
        shutil.rmtree(sock_dir, ignore_errors=True)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Deselect this tier unless somebody asked for it BY NAME.

    `addopts` carries `-m "not screenshots and not device"`, and that is not
    enough on its own: any `-m` on the command line REPLACES it rather than
    adding to it. So the ordinary `-m "not e2e"` re-selects this tier, and then
    a suite run reaches for a phone that may be asleep, on someone else's desk,
    or absent.

    That is not hypothetical. The identical override is how the per run prefix
    reached six published screenshots: `-m e2e` re-selected the shots tier,
    which `addopts` had deselected. #214 carries the general shape.

    So the deselection is enforced here rather than declared in configuration.
    `-m device` still selects it, which is the documented way to run it, and
    every other invocation leaves it alone whatever `-m` it carries.
    """
    expression = config.option.markexpr or ""
    if "device" in expression:
        return
    kept: list[pytest.Item] = []
    dropped: list[pytest.Item] = []
    for item in items:
        (dropped if item.get_closest_marker("device") else kept).append(item)
    if dropped:
        config.hook.pytest_deselected(items=dropped)
        items[:] = kept
