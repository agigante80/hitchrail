"""The tier that RUNS the program.

#128. Every other tier builds the app object directly:

    app = create_app(engine=..., config=..., bus=...)

So argument parsing, `build_config`, the preflight and the uvicorn launch are
covered by unit tests and by nothing that executes them together. The one thing
every user does first, running the binary, was the one path no tier drove.

**The gap has already cost an operator facing defect.** #120 changed `--root`
from a path to `label=path`, and argparse rendered the refusal as
`invalid parse_root_argument value: '...'`, showing a Python function name to
somebody who needed the sentence saying what to type. `test_cli.py` asserts
`SystemExit` and the config that comes out; it did not assert what a person
READS, and nothing ran the binary. One minute by hand found what the whole suite
was not shaped to see.

## Rules this tier follows

- **The installed console script**, not `python -m hitchrail`. The console
  script is what a user runs and what the unit's `ExecStart` names, so it is
  the thing whose behaviour is worth pinning.
- **A temporary root**, always.

- **A private tmux server, via `TMUX_TMPDIR` in the child's environment.**
  `env -u TMUX` stops the child inheriting an ambient SESSION; it does not
  choose a SOCKET. `TMUX_TMPDIR` does: tmux resolves its default socket under
  that directory, and with `$TMUX` unset it is decisive. So every child here
  addresses a server that exists for one test and is removed with it.

  **This file used to say the opposite**, that isolation was impossible without
  a `--tmux-socket` flag, and that the tier must therefore never start a
  session. That was wrong twice over: the environment already solved it, and the
  proposed fix would have promoted a test seam into the operator contract, which
  `docs/versioning.md` then makes MAJOR to rename. #216 records both decisions.

  Nothing asks Hitchrail to READ `TMUX_TMPDIR`, which is why this is consistent
  with `config.py:106` refusing an environment configuration layer. tmux reads
  it; Hitchrail is the process that inherits it.

  **A start case is now allowed here**, and the guard is what keeps it safe:
  `test_the_cli_tier_never_spawns_without_an_isolated_tmux` fails if any spawn
  in this tier goes out without `env=_child_env(...)`. A comment asking the next
  author not to start a session is the kind of instruction this project has
  repeatedly found worthless.
- **A fake agent**, never a real Claude. It costs money, needs credentials and
  cannot run in CI.
- **Its own marker, and NOT folded into `e2e`.** That word means "a browser" and
  no page is involved here. Widening it is how a tier stops describing anything.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

# The console script, in the environment the suite runs in. Resolved from the
# interpreter rather than from PATH: `shutil.which` would find a DIFFERENT
# hitchrail if the operator has one installed, which is exactly the confusion
# this tier exists to avoid.
CONSOLE_SCRIPT = Path(sys.executable).parent / "hitchrail"

# Generous. A refusal answers immediately; a start has to bind and print a
# banner, and CI is slower than a desk.
RUN_TIMEOUT_S = 25.0


@pytest.fixture(scope="session", autouse=True)
def the_console_script_exists() -> None:
    """Fails, never skips.

    A tier that skips when its subject is missing looks like coverage while
    proving less than none, which `.claude/CLAUDE.md` says in as many words. If the
    console script is absent the environment is not set up, and that is worth
    a red line rather than a quiet pass.
    """
    if not CONSOLE_SCRIPT.exists():
        pytest.fail(
            f"{CONSOLE_SCRIPT} does not exist, so this tier has nothing to run. "
            f"`uv sync` installs the console script; this tier asserts on the "
            f"binary a user actually invokes, not on `python -m hitchrail`."
        )


@pytest.fixture
def agent(tmp_path: Path) -> Path:
    """A fake agent that starts, says so, and waits.

    Enough for the preflight, which checks the binary is there and executable,
    and for a session that has to look alive.
    """
    path = tmp_path / "fake-agent"
    path.write_text(
        f"#!{sys.executable}\n"
        "import sys, time\n"
        'print("fake-agent: started as " + " ".join(sys.argv[1:]), flush=True)\n'
        "time.sleep(3600)\n"
    )
    path.chmod(0o755)
    return path


@pytest.fixture
def roots(tmp_path: Path) -> Path:
    parent = tmp_path / "roots"
    (parent / "main" / "vessel").mkdir(parents=True)
    (parent / "other" / "anchor").mkdir(parents=True)
    return parent


@contextlib.contextmanager
def _isolated_tmux() -> Iterator[str]:
    """A `TMUX_TMPDIR` that exists for one call and is removed with it.

    Removed in a `finally`, because the tier that leaked a directory per test
    already happened: see `test_the_leak_detectors_can_actually_see_a_stray_server`.
    """
    directory = tempfile.mkdtemp(prefix="hitchrail-cli-tier-")
    try:
        yield directory
    finally:
        # **Kill the private server before the directory goes**, or a start case
        # leaves a tmux server and the agent inside it running with its socket
        # unlinked. `rmtree` removes the socket file; it does not end the
        # process holding it.
        #
        # `-S` rather than a bare `kill-server`, which control 6 forbids: the
        # socket path is inside a directory this call made, so the scope is
        # explicit rather than inherited from an environment variable.
        socket = tmux_socket_under(directory)
        if socket.exists():
            subprocess.run(
                ["tmux", "-S", str(socket), "kill-server"],
                capture_output=True,
                check=False,
                timeout=10,
            )
        shutil.rmtree(directory, ignore_errors=True)


def tmux_socket_under(tmux_tmpdir: str) -> Path:
    """Where tmux puts its default socket for this `TMUX_TMPDIR`.

    `$TMUX_TMPDIR/tmux-$UID/default`, which is tmux's own layout rather than a
    guess: the measurement is on #216, and it is what makes the isolation
    checkable from the outside instead of taken on trust.
    """
    return Path(tmux_tmpdir) / f"tmux-{os.getuid()}" / "default"


def _child_env(tmux_tmpdir: str, extra: dict[str, str] | None = None) -> dict[str, str]:
    """The environment every child in this tier runs in.

    One function, so `test_the_cli_tier_never_spawns_without_an_isolated_tmux`
    can assert that every spawn uses it. `TMUX` is dropped so an ambient session
    cannot be inherited, and `TMUX_TMPDIR` is set so the default socket lands
    somewhere private.
    """
    assert "TMUX_TMPDIR" not in (extra or {}), (
        "a caller may not choose TMUX_TMPDIR: the whole point is that this tier's "
        "children cannot reach a server anybody else can see."
    )
    env = {k: v for k, v in os.environ.items() if k != "TMUX"}
    env["TMUX_TMPDIR"] = tmux_tmpdir
    env.update(extra or {})
    return env


class Program:
    """A running console script, and everything it has said so far.

    The output matters: `serving` used to promise it yielded the startup lines
    "because the banner is half of what this tier exists to assert", and yielded
    `[]`. The promise was removed rather than met. It is met here.
    """

    def __init__(self, url: str, lines: list[str], tmux_tmpdir: str) -> None:
        self.url = url
        self.tmux_tmpdir = tmux_tmpdir
        self.tmux_socket = tmux_socket_under(tmux_tmpdir)
        self._lines = lines

    def output(self) -> str:
        return "".join(self._lines)

    def expect(self, fragment: str, timeout: float = RUN_TIMEOUT_S) -> str:
        """Wait for a line, on the CONDITION rather than on a clock.

        A sleep here would be #114 in a new file: how long uvicorn takes to
        print is not a number this file should be guessing.
        """
        import time

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            seen = self.output()
            if fragment in seen:
                return seen
            time.sleep(0.05)
        raise AssertionError(f"never printed {fragment!r}. What it did print:\n{self.output()}")


def free_port() -> int:
    import socket

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@contextlib.contextmanager
def serving(*args: str, env: dict[str, str] | None = None) -> Iterator[Program]:
    """Start the console script for real, wait for it to answer, then stop it.

    Yields a `Program`: its url, and everything it has printed. **The pipe is
    drained in a thread**, which is what makes the second half true and what
    stops the child blocking on a full pipe. There is no deadlock today,
    uvicorn's startup is a few hundred bytes against a 64KB buffer, but a
    chattier failure inside the `with` body would block the child through
    `terminate()` and burn both ten second waits before `kill()`. The fd also
    leaked per use.

    Readiness is a POLL on the socket, never a sleep. A fixed wait here would be
    the #114 defect in a new file: how long uvicorn takes to bind is not a
    number this file should be guessing, and CI is slower than a desk.
    """
    import socket as socketlib
    import threading
    import time

    port = free_port()
    base = f"http://127.0.0.1:{port}"
    with _isolated_tmux() as tmux_tmpdir:
        process = subprocess.Popen(
            [str(CONSOLE_SCRIPT), "--host", "127.0.0.1", "--port", str(port), *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=_child_env(tmux_tmpdir, env),
        )
        lines: list[str] = []

        def drain() -> None:
            assert process.stdout is not None
            for line in process.stdout:
                lines.append(line)

        pump = threading.Thread(target=drain, daemon=True)
        pump.start()
        try:
            deadline = time.monotonic() + RUN_TIMEOUT_S
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    pump.join(timeout=5)
                    raise AssertionError(
                        f"the program exited before serving:\n{''.join(lines)}"
                    )
                # A socket connect, not a request. The question is "is it
                # listening", and asking it this way needs no opinion about what
                # the first response should be: a 401 is serving just as much as
                # a 200 is.
                try:
                    with socketlib.create_connection(("127.0.0.1", port), timeout=1):
                        break
                except OSError:
                    time.sleep(0.05)
            else:
                raise AssertionError(f"{base} never answered within {RUN_TIMEOUT_S}s")
            yield Program(base, lines, tmux_tmpdir)
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
            pump.join(timeout=5)
            if process.stdout is not None:
                process.stdout.close()


def run_cli(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """Run the console script and return what a person would see.

    The child never inherits `$TMUX` and always carries a private
    `TMUX_TMPDIR`, so a suite run from inside a tmux session cannot reach the
    developer's own server and neither can the program under test.
    """
    # **An ephemeral port even for a refusal.** Every caller expects the program
    # to refuse before it binds, and that expectation is what a regression
    # breaks. Without this, a dropped preflight leaves it SERVING on the default
    # 127.0.0.1:8787, colliding with the operator's real Hitchrail, until
    # `subprocess.run`'s timeout fires. The test then fails as `TimeoutExpired`
    # rather than as the refusal test it is.
    with _isolated_tmux() as tmux_tmpdir:
        return subprocess.run(
            [str(CONSOLE_SCRIPT), "--host", "127.0.0.1", "--port", str(free_port()), *args],
            capture_output=True,
            text=True,
            timeout=RUN_TIMEOUT_S,
            check=False,
            env=_child_env(tmux_tmpdir, env),
        )
