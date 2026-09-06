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

- **NOT a private tmux socket, and this file used to claim otherwise.**
  `env -u TMUX` stops the child inheriting an ambient session; it does not
  choose a socket. `Config.tmux_socket` is the only thing that does, and the
  CLI exposes no way to set it: no flag, no environment variable. So the
  program this tier runs talks to the DEFAULT tmux server, the operator's own.

  Today that contact is read only, one `list-panes -a`, because no case here
  starts or stops a session. **Do not add one that does** until the CLI can be
  pointed at a socket: a spawned Hitchrail creates `hr-` sessions on the default
  server, and its kill paths are scoped to the same `hr-` prefix a real one
  uses. #216 carries that decision, which changes the operator contract rather
  than a test.

  The browser tier really is isolated, and can be, because it builds a `Config`
  in Python and passes `tmux_socket` straight in. The console script has no such
  path, which is the whole difference.
- **A fake agent**, never a real Claude. It costs money, needs credentials and
  cannot run in CI.
- **Its own marker, and NOT folded into `e2e`.** That word means "a browser" and
  no page is involved here. Widening it is how a tier stops describing anything.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
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
    proving less than none, which `AGENTS.md` says in as many words. If the
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


def free_port() -> int:
    import socket

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@contextlib.contextmanager
def serving(*args: str, env: dict[str, str] | None = None) -> Iterator[str]:
    """Start the console script for real, wait for it to answer, then stop it.

    Yields the base url. **Not the banner**: an earlier version of this
    docstring said it yielded the startup lines "because the banner is half of
    what this tier exists to assert", and yielded `[]`. Nothing asserted a
    banner line, so the sentence was the only thing making it look covered.
    Draining the pipe and asserting on it is worth doing, and is on #216.

    Readiness is a POLL on the socket, never a sleep. A fixed wait here would be
    the #114 defect in a new file: how long uvicorn takes to bind is not a
    number this file should be guessing, and CI is slower than a desk.
    """
    import socket as socketlib
    import time

    port = free_port()
    child = {k: v for k, v in os.environ.items() if k != "TMUX"}
    child.update(env or {})
    process = subprocess.Popen(
        [str(CONSOLE_SCRIPT), "--host", "127.0.0.1", "--port", str(port), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=child,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + RUN_TIMEOUT_S
        while time.monotonic() < deadline:
            if process.poll() is not None:
                output = process.stdout.read() if process.stdout else ""
                raise AssertionError(f"the program exited before serving:\n{output}")
            # A socket connect, not a request. The question is "is it
            # listening", and asking it this way needs no opinion about what
            # the first response should be: a 401 is serving just as much as a
            # 200 is.
            try:
                with socketlib.create_connection(("127.0.0.1", port), timeout=1):
                    break
            except OSError:
                time.sleep(0.05)
        else:
            raise AssertionError(f"{base} never answered within {RUN_TIMEOUT_S}s")
        yield base
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


def run_cli(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """Run the console script and return what a person would see.

    `env -u TMUX` in spirit: the child never inherits `$TMUX`, so a suite run
    from inside a tmux session cannot reach the developer's own server.
    """
    child = {k: v for k, v in os.environ.items() if k != "TMUX"}
    child.update(env or {})
    # **An ephemeral port even for a refusal.** Every caller expects the program
    # to refuse before it binds, and that expectation is what a regression
    # breaks. Without this, a dropped preflight leaves it SERVING on the default
    # 127.0.0.1:8787, colliding with the operator's real Hitchrail, until
    # `subprocess.run`'s timeout fires. The test then fails as `TimeoutExpired`
    # rather than as the refusal test it is.
    return subprocess.run(
        [str(CONSOLE_SCRIPT), "--host", "127.0.0.1", "--port", str(free_port()), *args],
        capture_output=True,
        text=True,
        timeout=RUN_TIMEOUT_S,
        check=False,
        env=child,
    )
