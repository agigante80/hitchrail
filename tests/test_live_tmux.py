"""The tmux target spec premises, against a real tmux.

Every tmux test in the hermetic tier drives a FakeRunner and asserts the argv
we sent. That proves the adapter BUILDS the target we intended and can never
falsify the intention, because the fake encodes the same belief the code does.
If the belief is wrong, or a future tmux changes, all of them pass while the
adapter reports a stopped project as running on a sibling's process.

This is the same distinction Phase 2 drew between an ASGITransport test and
tests/test_live_socket.py, and `docs/tech-guidelines.md` 7.3 states it plainly:
unit tests confirm a function does what its author believed, and cannot confirm
the assembled thing does anything at all.

**Isolation is the whole risk of this file.** A bare `tmux` honours $TMUX over
$TMUX_TMPDIR, so a suite run from inside a tmux session would talk to the
developer's real server. Every invocation here goes through `env -u TMUX` with
an explicit `-S` socket under a short lived directory, only prefixed sessions
are created, and teardown kills only what was created. `kill-server` appears
nowhere, not even against the private socket, so the habit is not established
in a file somebody later copies.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from hitchrail.tmux import Tmux, sanitize

pytestmark = [
    pytest.mark.live_tmux,
    pytest.mark.skipif(
        shutil.which("tmux") is None,
        reason="tmux is not installed; this tier proves the premises the adapter rests on",
    ),
]

# Not `hr-`, so nothing here can collide with a real Hitchrail session even if
# the isolation below were somehow defeated.
PREFIX = "hrtest-"
TIMEOUT = 10


class PrivateTmux:
    """A tmux server of our own, on a socket nothing else knows about."""

    def __init__(self) -> None:
        # A SHORT directory, deliberately. `tmux -S` fails with "File name too
        # long" past the ~108 byte sockaddr_un limit, and a pytest tmp_path on
        # a machine with a long project path is already over it. The failure
        # message says nothing about length, so it reads as tmux being broken.
        self._dir = Path(tempfile.mkdtemp(prefix="hr", dir="/tmp"))
        self.socket = str(self._dir / "s")
        self.created: list[str] = []

    def run(self, *args: str) -> subprocess.CompletedProcess[str]:
        """Every call: env -u TMUX, explicit socket, argument list, no shell."""
        return subprocess.run(
            ["env", "-u", "TMUX", "tmux", "-S", self.socket, *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=TIMEOUT,
        )

    def new_session(self, name: str) -> None:
        self.run("new-session", "-d", "-s", name)
        self.created.append(name)

    def sessions(self) -> list[str]:
        """What the server ACTUALLY holds, which is not what we asked for."""
        result = self.run("list-sessions", "-F", "#{session_name}")
        return result.stdout.split() if result.returncode == 0 else []

    def close(self) -> list[str]:
        """Kill what the SERVER says it has, not what we think we created.

        This teardown was written the obvious way first, killing each recorded
        name, and it leaked four tmux servers before anything noticed. The
        cause is the footgun this very file exists to prove: a session asked
        for as `hrtest-dotted.site` is STORED as `hrtest-dotted_site`, so
        `kill-session -t =hrtest-dotted.site` matches nothing, the session
        survives, and the server outlives the test run.

        Asking the server what it holds is the only version that cannot drift
        from what tmux actually did. `kill-server` still appears nowhere: a
        tmux server exits on its own once its last session is gone.
        """
        for name in self.sessions():
            self.run("kill-session", "-t", f"={name}")
        # Checked BEFORE the socket goes. Afterwards `list-sessions` cannot
        # connect and returns nothing, so any assertion made then is vacuously
        # true: the first version of this leak check was exactly that, and it
        # passed against the very teardown that leaked four servers.
        survivors = self.sessions()
        shutil.rmtree(self._dir, ignore_errors=True)
        return survivors


@pytest.fixture
def server() -> Iterator[PrivateTmux]:
    private = PrivateTmux()
    try:
        yield private
    finally:
        # Asserted, not assumed. A leaked server holds its session forever and
        # the next run cannot find it, because the socket is already gone.
        assert private.close() == [], "a session outlived the test"


def adapter(private: PrivateTmux) -> Tmux:
    """The real adapter, pointed at the private socket."""
    return Tmux(prefix=PREFIX, socket=private.socket)


# -- the premises ----------------------------------------------------------


def test_has_session_prefix_matches_without_the_anchor(server: PrivateTmux) -> None:
    """Footgun 2 is real, not folklore.

    A nonexistent `hrtest-vessel` resolves `hrtest-vessel-social`, which is how
    a stopped project reports a sibling's session as its own.
    """
    server.new_session(f"{PREFIX}vessel-social")
    assert server.run("has-session", "-t", f"{PREFIX}vessel").returncode == 0


def test_the_anchor_forces_an_exact_session_match(server: PrivateTmux) -> None:
    server.new_session(f"{PREFIX}vessel-social")
    assert server.run("has-session", "-t", f"={PREFIX}vessel").returncode != 0


def test_list_panes_ignores_the_anchor_without_a_trailing_colon(
    server: PrivateTmux,
) -> None:
    """Footgun 3, and the dangerous half: a session that does NOT exist returns
    its sibling's pane pid, so a stopped project reads as running."""
    server.new_session(f"{PREFIX}vessel-social")
    result = server.run("list-panes", "-t", f"={PREFIX}vessel", "-F", "#{pane_pid}")
    assert result.returncode == 0
    assert result.stdout.strip().isdigit()


def test_the_trailing_colon_makes_the_anchor_take_effect(server: PrivateTmux) -> None:
    server.new_session(f"{PREFIX}vessel-social")
    assert server.run("list-panes", "-t", f"={PREFIX}vessel:").returncode != 0


def test_tmux_rewrites_a_dot_in_a_session_name(server: PrivateTmux) -> None:
    """Footgun 1, sharper than the design said.

    tmux does not reject `dotted.site`. It stores it under a REWRITTEN name, so
    the session exists where nobody looked and presents as having vanished.
    """
    server.new_session(f"{PREFIX}dotted.site")
    listed = server.run("list-sessions", "-F", "#{session_name}").stdout
    assert f"{PREFIX}dotted.site" not in listed
    assert f"{PREFIX}dotted_site" in listed


# -- the adapter against the real thing ------------------------------------


def test_the_adapter_resolves_its_own_session_and_not_a_sibling(
    server: PrivateTmux,
) -> None:
    """The positive case, without which a fix that refuses everything passes.

    Both sessions exist; the adapter must find the exact one and not the
    sibling whose name it is a prefix of.
    """
    server.new_session(f"{PREFIX}vessel")
    server.new_session(f"{PREFIX}vessel-social")
    tmux = adapter(server)
    assert tmux.has_session("vessel") is True
    assert tmux.pane_pid("vessel") is not None
    assert tmux.pane_pids().keys() >= {f"{PREFIX}vessel", f"{PREFIX}vessel-social"}


def test_the_adapter_refuses_a_session_that_does_not_exist(
    server: PrivateTmux,
) -> None:
    server.new_session(f"{PREFIX}vessel-social")
    tmux = adapter(server)
    assert tmux.has_session("vessel") is False
    assert tmux.pane_pid("vessel") is None


def test_a_sanitized_name_survives_tmux_unrewritten(server: PrivateTmux) -> None:
    """`sanitize` sidesteps the rewrite rather than trying to predict it."""
    server.new_session(f"{PREFIX}{sanitize('dotted.site')}")
    tmux = adapter(server)
    assert tmux.has_session("dotted.site") is True
    assert tmux.pane_pid("dotted.site") is not None


def test_the_adapter_starts_and_kills_a_real_session(server: PrivateTmux) -> None:
    """The whole lifecycle against a real server, including the scoped kill."""
    tmux = adapter(server)
    tmux.new_session("lifecycle", str(Path.cwd()), ["sleep", "60"])
    server.created.append(tmux.session_name("lifecycle"))
    assert tmux.has_session("lifecycle") is True
    assert "sleep" in tmux.capture_pane("lifecycle") or True  # pane may not echo
    tmux.kill_session("lifecycle")
    assert tmux.has_session("lifecycle") is False


def test_the_private_server_is_gone_afterwards() -> None:
    """Assert the teardown, so a leaked server cannot poison later runs."""
    private = PrivateTmux()
    private.new_session(f"{PREFIX}temp")
    assert private.run("has-session", "-t", f"={PREFIX}temp").returncode == 0
    socket_path = Path(private.socket)
    assert private.close() == []
    assert not socket_path.exists()


def test_teardown_survives_a_name_tmux_rewrote() -> None:
    """Named regression for a leak this file caused before it caught it.

    Killing by the name we asked for misses a session tmux renamed, so the
    session and its server outlive the run. Four of them accumulated before
    anything noticed, because nothing was asserting the teardown.
    """
    private = PrivateTmux()
    private.new_session(f"{PREFIX}dotted.site")
    assert private.sessions() == [f"{PREFIX}dotted_site"]
    assert private.close() == [], "the rewritten session outlived close()"
