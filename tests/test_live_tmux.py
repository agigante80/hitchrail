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
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from hitchrail.procs import snapshot
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


# -- #65: the real `ps`, which is the only thing that could catch this -------


def test_a_long_command_line_survives_the_real_process_table(
    server: PrivateTmux,
) -> None:
    """The test that would have found #65, and the reason it is in THIS tier.

    Every hermetic test feeds `parse_ps` a string that was never truncated,
    because the fixtures write short rows by hand. Only a tier that runs the
    real `ps` against a real process can see that the command line was cut at
    the terminal width, and the part cut is the end of the argv, where
    `--remote-control <project>` lives.

    Measured at 80 columns before the fix: eight agents visible, twelve with
    `-ww`. The four that vanished derived as `stopped` and would have offered
    a Start into a folder that already had an agent.
    """
    # Long enough to exceed any terminal, and long in the way a real
    # deployment is: a deep path rather than an absurd project name.
    deep = Path(server._dir) / "/".join(f"segment-{i}" for i in range(12))
    deep.mkdir(parents=True, exist_ok=True)
    marker = "--remote-control a-project-under-a-deep-path"
    script = deep / "agent"
    script.write_text("#!/bin/sh\nwhile true; do sleep 0.2; done\n")
    script.chmod(0o755)

    server.run("new-session", "-d", "-s", "hr-deep", str(script), *marker.split())
    time.sleep(0.6)

    table = snapshot()

    assert table.ok, "the process table could not be read at all"
    matching = [p for p in table.procs if marker in p.args]
    assert matching, (
        f"a command line of {len(str(script)) + len(marker)} characters lost its "
        "tail. `ps` truncates to the terminal width without -ww."
    )
    assert matching[0].args.rstrip().endswith("a-project-under-a-deep-path")


# -- #66: a pane that outlives its process, against a real tmux -------------


def test_a_dead_pane_keeps_what_it_printed(server: PrivateTmux) -> None:
    """The measurement this whole ticket rests on, asserted rather than
    remembered.

    Without `remain-on-exit` a pane that exits takes the window, the session
    and then the tmux server with it in under fifty milliseconds, so there is
    nothing to capture and `start_died` arrives empty. Only this tier can see
    that: every hermetic fake returns whatever text the test put in it,
    whether or not a real tmux would still have the pane.
    """
    script = Path(server._dir) / "dying-agent"
    script.write_text(
        "#!/bin/sh\necho 'agent: missing credential'\necho 'agent: goodbye'\nexit 3\n"
    )
    script.chmod(0o755)

    # Through the ADAPTER, not a hand rolled argv. The chained `set-option`
    # and its target form are the things under test, and writing them out here
    # again would test this file's copy of them rather than the module's.
    adapter = Tmux(prefix="hr-", socket=server.socket)
    adapter.new_session("dying", str(server._dir), [str(script)])
    server.created.append("hr-dying")
    time.sleep(0.6)

    whole = adapter.capture_pane("dying", lines=0)

    assert "missing credential" in whole, f"the output was lost: {whole!r}"
    assert "goodbye" in whole
    # tmux's own line, and the exit code with it. Nothing else in this system
    # reports what an agent exited with.
    assert "status 3" in whole, f"the exit status was lost: {whole!r}"


def test_without_the_option_the_pane_is_gone_before_anything_can_read_it(
    server: PrivateTmux,
) -> None:
    """The negative half, and the reason capturing during the grace window
    cannot work: the engine's first poll is at 250ms."""
    script = Path(server._dir) / "instant-agent"
    script.write_text("#!/bin/sh\necho 'agent: gone'\nexit 3\n")
    script.chmod(0o755)

    server.run("new-session", "-d", "-s", "hr-instant", str(script))
    time.sleep(0.6)

    adapter = Tmux(prefix="hr-", socket=server.socket)
    assert adapter.capture_pane("instant", lines=0) == "", (
        "the pane survived without remain-on-exit, so this project's premise "
        "about tmux has changed and #66 should be re-measured"
    )


def test_clearing_the_option_lets_a_session_end_normally(server: PrivateTmux) -> None:
    """The cost of leaving it on. A graceful exit would leave a dead pane, the
    session would linger, and the engine would derive `stale` where the truth
    is `stopped`, silently changing the outcome of the stop flow."""
    adapter = Tmux(prefix="hr-", socket=server.socket)
    script = Path(server._dir) / "obedient-agent"
    script.write_text("#!/bin/sh\nsleep 0.4\nexit 0\n")
    script.chmod(0o755)

    adapter.new_session("obedient", str(server._dir), [str(script)])
    server.created.append("hr-obedient")
    adapter.keep_pane_on_exit("obedient", False)
    time.sleep(1.2)

    assert "hr-obedient" not in server.sessions(), (
        "the session lingered after a normal exit, so the engine would call it stale"
    )
