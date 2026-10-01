"""Does the token demand follow who can REACH the server, not what it binds?

A loopback bind needs no token; anything that makes it reachable from
elsewhere, a network bind or an `--allow-host` / `--allow-origin` naming a
remote name, does (#108).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from config_support import _r
from hitchrail.config import (
    Config,
    ConfigError,
)


def test_loopback_bind_needs_no_token(tmp_path: Path) -> None:
    cfg = Config(roots=_r(tmp_path))
    assert cfg.is_loopback
    assert cfg.token is None


def test_network_bind_without_a_token_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="token"):
        Config(roots=_r(tmp_path), host="0.0.0.0", token=None)


def test_network_bind_with_a_token_is_allowed(tmp_path: Path) -> None:
    cfg = Config(roots=_r(tmp_path), host="0.0.0.0", token="s3cret")
    assert not cfg.is_loopback


def test_a_named_bind_still_demands_a_token(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="token"):
        Config(roots=_r(tmp_path), host="box.lan")


# -- #108: the token demand follows reach, not the bind ----------------------
#
# The refusal used to ask `is_loopback`, which reads the BIND address. Behind a
# reverse proxy the bind stops being the truth: `tailscale serve` or an nginx
# forwards to 127.0.0.1, so Hitchrail saw a loopback socket, concluded it was
# local only, and demanded no token, while the whole tailnet could reach it.
#
# The operator declares that reach in the only place they can: `--allow-host`
# and `--allow-origin` exist for no other purpose than making a non local name
# work, so nobody passes one by accident. That is a better statement of intent
# than the bind, which anything can forward to.


def test_a_remote_allow_host_demands_a_token(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as excinfo:
        Config(
            roots=_r(tmp_path),
            host="127.0.0.1",
            token=None,
            extra_hosts=("box.tailnet.ts.net",),
        )
    assert "box.tailnet.ts.net" in str(excinfo.value)
    assert "--allow-host" in str(excinfo.value)


def test_a_remote_allow_origin_demands_a_token(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as excinfo:
        Config(
            roots=_r(tmp_path),
            host="127.0.0.1",
            token=None,
            extra_origins=("https://box.tailnet.ts.net",),
        )
    assert "box.tailnet.ts.net" in str(excinfo.value)
    assert "--allow-origin" in str(excinfo.value)


def test_a_remote_allow_host_with_a_token_is_accepted(tmp_path: Path) -> None:
    """The proxied deployment this refusal is meant to make safe, not refuse."""
    config = Config(
        roots=_r(tmp_path), host="127.0.0.1", token="t", extra_hosts=("box.tailnet.ts.net",)
    )
    assert "box.tailnet.ts.net" in config.allowed_hosts


@pytest.mark.parametrize("entry", ["localhost", "127.0.0.1", "::1", "[::1]", "127.0.0.2"])
def test_a_loopback_allow_host_still_needs_no_token(tmp_path: Path, entry: str) -> None:
    """A loopback name in the allowlist declares no reach, so refusing it would
    punish the harmless case and teach operators to pass --token reflexively."""
    assert (
        Config(roots=_r(tmp_path), host="127.0.0.1", token=None, extra_hosts=(entry,)).token
        is None
    )


@pytest.mark.parametrize(
    "entry", ["http://127.0.0.1:9000", "https://localhost", "http://[::1]:80"]
)
def test_a_loopback_allow_origin_still_needs_no_token(tmp_path: Path, entry: str) -> None:
    assert (
        Config(roots=_r(tmp_path), host="127.0.0.1", token=None, extra_origins=(entry,)).token
        is None
    )


def test_a_bare_loopback_bind_still_needs_no_token(tmp_path: Path) -> None:
    """How nearly everybody runs it. The change must not break this."""
    assert Config(roots=_r(tmp_path), host="127.0.0.1", token=None).token is None


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.1.10"])
def test_a_non_loopback_bind_still_demands_a_token(tmp_path: Path, host: str) -> None:
    """Regression guard: the new predicate must not weaken the old rule."""
    with pytest.raises(ConfigError, match="token"):
        Config(roots=_r(tmp_path), host=host, token=None)
