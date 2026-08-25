"""Scratch probe, deleted after the review."""
from __future__ import annotations

import logging
import time
from pathlib import Path

import httpx
import pytest

from hitchrail.config import Config
from hitchrail.security import TOKEN_COOKIE
from test_live_socket import TIMEOUT, TOKEN, LiveServer, free_port, make_app

pytestmark = pytest.mark.live


def _capture(port, do_request):
    records: list[str] = []

    class Capture(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    handler = Capture()
    access = logging.getLogger("uvicorn.access")
    return records, handler, access


def _run(tmp_path: Path, do_request):
    port = free_port()
    config = Config(root=tmp_path, host="127.0.0.1", port=port, token=TOKEN)
    server = LiveServer(make_app(config), port, log_level="info")
    records: list[str] = []

    class Capture(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    handler = Capture()
    access = logging.getLogger("uvicorn.access")
    server.start()
    access.addHandler(handler)
    try:
        do_request(server)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and not records:
            time.sleep(0.05)
    finally:
        access.removeHandler(handler)
        server.stop()
    return "\n".join(records)


def test_probe_cookie_already_valid(tmp_path: Path) -> None:
    def req(server):
        r = httpx.get(
            f"{server.base}/x?token={TOKEN}&keep=1",
            headers={"Host": "127.0.0.1", "Cookie": f"{TOKEN_COOKIE}={TOKEN}"},
            follow_redirects=False,
            timeout=TIMEOUT,
        )
        print("STATUS(cookie-valid):", r.status_code)

    logged = _run(tmp_path, req)
    print("LOG(cookie-valid):", logged)
    assert TOKEN not in logged, "LEAK: token logged when cookie already valid"


def test_probe_wrong_token(tmp_path: Path) -> None:
    def req(server):
        r = httpx.get(
            f"{server.base}/x?token=nearly-{TOKEN}",
            headers={"Host": "127.0.0.1"},
            follow_redirects=False,
            timeout=TIMEOUT,
        )
        print("STATUS(wrong):", r.status_code)

    logged = _run(tmp_path, req)
    print("LOG(wrong):", logged)


def test_probe_post_with_token(tmp_path: Path) -> None:
    def req(server):
        r = httpx.post(
            f"{server.base}/x?token={TOKEN}",
            headers={"Host": "127.0.0.1"},
            follow_redirects=False,
            timeout=TIMEOUT,
        )
        print("STATUS(post):", r.status_code)

    logged = _run(tmp_path, req)
    print("LOG(post):", logged)
    assert TOKEN not in logged, "LEAK: token logged on a POST grant attempt"


def test_probe_bearer_header(tmp_path: Path) -> None:
    def req(server):
        r = httpx.get(
            f"{server.base}/x?token={TOKEN}",
            headers={"Host": "127.0.0.1", "Authorization": f"Bearer {TOKEN}"},
            follow_redirects=False,
            timeout=TIMEOUT,
        )
        print("STATUS(bearer):", r.status_code)

    logged = _run(tmp_path, req)
    print("LOG(bearer):", logged)
    assert TOKEN not in logged, "LEAK: token logged when Authorization already valid"
