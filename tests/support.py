"""Helpers shared by the test tiers, so a change to a constructor is one edit.

**Why this exists.** `Config` was built directly at 145 call sites, and almost
none of them cared how it was built: they wanted a config pointing at a
temporary root so they could test something else. Pluralising `root` for #120
would therefore have been a 145 site diff, which is not a diff anybody reviews.

`tests/test_config.py` deliberately does NOT use this. Config is the unit under
test there, and a helper between the test and the constructor would hide the
thing being asserted.
"""

from __future__ import annotations

import contextlib
import os
import select
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any

from hitchrail.config import Config
from hitchrail.roots import Root

DEFAULT_LABEL = "main"


def make_config(root: Path, **kw: Any) -> Config:
    """A Config with one root labelled `main`, for tests that do not care.

    Everything else is passed through, so a test that DOES care about a field
    names it and the rest stay at their defaults. A test that cares about
    SEVERAL roots passes `roots=` and does not use this.

    This is the edit #120 was preparing for: one line, rather than 145.
    """
    if "roots" in kw:
        raise TypeError("pass roots= to Config directly, not through make_config")
    return Config(roots=(Root(label=DEFAULT_LABEL, path=root.resolve()),), **kw)


def make_certificate(directory: Path) -> tuple[Path, Path]:
    """A self signed certificate for 127.0.0.1 and `localhost`, minted into a
    temporary directory (#152).

    Generated rather than committed: a private key in a public repository is
    a private key somebody will one day copy into a deployment, and the
    `no_private_data` guard would rightly ask what it is. `openssl` is what
    every machine with a TLS stack has, and the tiers that need one FAIL
    without it rather than skip, for the reason `.claude/CLAUDE.md` gives:
    a tier that skips everywhere looks like coverage while proving nothing.
    """
    import shutil
    import subprocess

    assert shutil.which("openssl") is not None, (
        "openssl is not installed, and the TLS tests FAIL rather than skip: a "
        "certificate has to come from somewhere, and a committed one is a key "
        "in a public repository."
    )
    cert = directory / "cert.pem"
    key = directory / "key.pem"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "ec",
            "-pkeyopt",
            "ec_paramgen_curve:prime256v1",
            "-nodes",
            "-keyout",
            str(key),
            "-out",
            str(cert),
            "-days",
            "2",
            "-subj",
            "/CN=localhost",
            "-addext",
            "subjectAltName=DNS:localhost,IP:127.0.0.1",
        ],
        check=True,
        capture_output=True,
    )
    return cert, key


# -- a real orphan, for the tiers that spawn a detached agent -----------------
#
# Forks twice and exits, so the agent is reparented to init the way a real
# detached agent is when its tmux session dies. A plain `Popen` child stays
# the SUITE's child, and the suite is often run from inside a tmux (the
# CLAUDE.md warning about `$TMUX` exists because it is), so the developer's
# own tmux server sat above every seeded "orphan" and #189's ancestry walk,
# correctly, named it: the row said "in a tmux server Hitchrail is not
# configured for" and the End control was gone. The grandchild's pid is
# printed for the caller; nothing else is.
_DETACH = """
import os, sys
if os.fork():
    os._exit(0)
os.setsid()
if (pid := os.fork()):
    print(pid, flush=True)
    os._exit(0)
null = os.open(os.devnull, os.O_RDWR)
for fd in (0, 1, 2):
    os.dup2(null, fd)
os.execv(sys.argv[1], sys.argv[1:])
"""


class Orphan:
    """A process reparented to init, watched through a pidfd.

    The `Popen` surface the harnesses already used (`pid`, `poll`, `wait`,
    `terminate`, `kill`), minus the exit status: nobody can `wait(2)` on a
    process that is not their child, and a pidfd is readable once its
    process has exited, which is the one fact the callers read.
    """

    def __init__(self, argv: list[str], cwd: Path, env: dict[str, str] | None = None) -> None:
        launched = subprocess.run(
            [sys.executable, "-c", _DETACH, *argv],
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
        self.pid = int(launched.stdout)
        self._fd = os.pidfd_open(self.pid)

    def _exited(self, timeout: float) -> bool:
        return bool(select.select([self._fd], [], [], timeout)[0])

    def poll(self) -> int | None:
        """0 once the process has exited, else None; the status itself is
        init's to reap."""
        return 0 if self._exited(0) else None

    def wait(self, timeout: float) -> int:
        if not self._exited(timeout):
            raise subprocess.TimeoutExpired(cmd=str(self.pid), timeout=timeout)
        return 0

    def _send(self, sig: signal.Signals) -> None:
        with contextlib.suppress(ProcessLookupError):
            signal.pidfd_send_signal(self._fd, sig)

    def terminate(self) -> None:
        self._send(signal.SIGTERM)

    def kill(self) -> None:
        self._send(signal.SIGKILL)

    def close(self) -> None:
        """End it if it is still there, and release the descriptor."""
        if not self._exited(0):
            self.kill()
            self._exited(5)
        os.close(self._fd)
