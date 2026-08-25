# Hitchrail Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the engine and HTTP API for Hitchrail, so that a person can start, inspect and stop headless Claude Code sessions across a folder of projects using `curl`, with no browser interface yet.

**Architecture:** State is derived on demand from tmux and the process table, with no database. Every external surface (tmux, the process table, memory readings, the Claude state directory, the clock) is injected, so the whole engine is testable without touching a real machine. A thin Starlette layer sits on top and holds no logic worth testing separately.

**Tech Stack:** Python 3.11+, uv, Starlette 1.6, uvicorn, sse-starlette, pytest, ruff, mypy, import-linter.

**Spec:** `docs/superpowers/specs/2026-08-25-hitchrail-design.md`

**Roadmap:** `docs/roadmap.md` (this plan is Phase 1)

## Global Constraints

Copied verbatim from the spec. Every task inherits these.

- **Python `>=3.11`.** CI runs 3.11, 3.12 and 3.13. All blocking.
- **Exactly three runtime dependencies:** `starlette>=1.6,<2`, `uvicorn>=0.52,<1`, `sse-starlette>=3.4,<4`. A fourth requires a written justification in the pull request.
- **Starlette 1.x API only.** `on_startup`, `on_shutdown`, `add_event_handler()`, `@app.route()` and `@app.websocket_route()` were removed at 1.0. Use the `lifespan` async context manager and an explicit `routes=` list. Examples written against 0.4x are wrong.
- **No shell, ever.** Every subprocess call takes an argument list. `shell=True` is forbidden with no exceptions.
- **The engine layer must not import** `hitchrail.server`, `hitchrail.cli`, `starlette`, `uvicorn` or `sse_starlette`. Enforced by import-linter in CI.
- **Never a bare `tmux kill-server`.** Never kill a session whose name does not carry the configured prefix.
- **The root stays lean.** Every tool is configured from `pyproject.toml`. No new root level dotfiles without a reason.
- **`src/` layout**, so tests run against the installed distribution.
- Defaults: session prefix `hr-`, stop timeout 30 seconds, hard memory floor 1536 MB, soft floor 3072 MB, per session estimate 1536 MB, port 8787.
- Tests are hermetic. No test touches a real tmux server, a real Claude process, the network, or the filesystem outside a temporary root.

---

### Task 1: Skeleton, tooling and gates

**Files:**
- Create: `pyproject.toml`
- Create: `.python-version`
- Create: `src/hitchrail/__init__.py`
- Create: `src/hitchrail/py.typed`
- Create: `tests/test_smoke.py`
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: nothing.
- Produces: `hitchrail.__version__: str`. A working `uv run` environment. Four gates that later tasks must keep green: `uv run ruff check`, `uv run ruff format --check`, `uv run mypy`, `uv run lint-imports`, `uv run pytest`.

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "hitchrail"
version = "0.1.0"
description = "Start and stop headless Claude Code sessions across a folder of projects, from your phone."
readme = "README.md"
requires-python = ">=3.11"
license = "MIT"
license-files = ["LICENSE"]
authors = [{ name = "agigante80" }]
keywords = ["claude-code", "tmux", "session-manager", "self-hosted"]
classifiers = [
  "Development Status :: 3 - Alpha",
  "Environment :: Web Environment",
  "Intended Audience :: Developers",
  "License :: OSI Approved :: MIT License",
  "Operating System :: POSIX :: Linux",
  "Programming Language :: Python :: 3.11",
  "Programming Language :: Python :: 3.12",
  "Programming Language :: Python :: 3.13",
]
dependencies = [
  "starlette>=1.6,<2",
  "uvicorn>=0.52,<1",
  "sse-starlette>=3.4,<4",
]

[project.scripts]
hitchrail = "hitchrail.cli:main"

[project.urls]
Homepage = "https://github.com/agigante80/hitchrail"
Issues = "https://github.com/agigante80/hitchrail/issues"

[build-system]
requires = ["uv_build>=0.12.5,<0.13"]
build-backend = "uv_build"

[dependency-groups]
dev = [
  "pytest>=9.1",
  "pytest-asyncio>=1.4",
  "httpx>=0.28",
  "ruff>=0.16",
  "mypy>=2.3",
  "import-linter>=2.13",
  "coverage[toml]>=7.15",
]

[tool.ruff]
line-length = 96
src = ["src", "tests"]

[tool.ruff.lint]
select = ["E", "F", "W", "I", "N", "UP", "B", "A", "C4", "SIM", "PTH", "RUF", "S"]
ignore = ["S101"]

[tool.ruff.lint.per-file-ignores]
"src/hitchrail/tmux.py" = ["S603"]
"src/hitchrail/procs.py" = ["S603"]
"tests/*" = ["S603", "S607"]

[tool.mypy]
python_version = "3.11"
strict = true
files = ["src", "tests"]
warn_unreachable = true

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
addopts = "-ra --strict-markers --strict-config"

[tool.coverage.run]
source = ["hitchrail"]
branch = true

[tool.importlinter]
root_package = "hitchrail"
include_external_packages = true

[[tool.importlinter.contracts]]
name = "the engine layer knows nothing about the web"
type = "forbidden"
source_modules = [
  "hitchrail.config",
  "hitchrail.discovery",
  "hitchrail.tmux",
  "hitchrail.procs",
  "hitchrail.claude_ipc",
  "hitchrail.ram",
  "hitchrail.engine",
  "hitchrail.events",
]
forbidden_modules = [
  "hitchrail.server",
  "hitchrail.cli",
  "starlette",
  "uvicorn",
  "sse_starlette",
]
```

`S603` is ruff's warning about subprocess calls. It is silenced only in the two modules that legitimately run subprocesses, so the exception is visible rather than global.

- [ ] **Step 2: Create the package files**

`.python-version`:

```
3.12
```

`src/hitchrail/py.typed` is an empty file.

`src/hitchrail/__init__.py`:

```python
"""Start and stop headless Claude Code sessions across a folder of projects."""

__version__ = "0.1.0"
```

- [ ] **Step 3: Write the failing smoke test**

`tests/test_smoke.py`:

```python
import hitchrail


def test_package_exposes_a_version() -> None:
    assert hitchrail.__version__ == "0.1.0"
```

- [ ] **Step 4: Sync and run the gates**

```bash
uv sync
uv run pytest -v
uv run ruff check
uv run ruff format --check
uv run mypy
uv run lint-imports
```

Expected: pytest passes with 1 test. All four gates pass. If `lint-imports` complains that a module in the contract does not exist, that is expected until Task 2 onwards create them; remove the not yet created modules from `source_modules` and add each back in the task that creates it.

- [ ] **Step 5: Write the CI workflow**

`.github/workflows/ci.yml`:

```yaml
name: ci

on:
  push:
    branches: [main]
  pull_request:

jobs:
  check:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        python: ["3.11", "3.12", "3.13"]
    steps:
      - uses: actions/checkout@v5
      - uses: astral-sh/setup-uv@v7
        with:
          enable-cache: true
      - run: uv sync --python ${{ matrix.python }}
      - run: uv run ruff check
      - run: uv run ruff format --check
      - run: uv run mypy
      - run: uv run lint-imports
      - run: uv run coverage run -m pytest
      - run: uv run coverage report
```

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock .python-version src tests .github
git commit -m "build: project skeleton, tooling and CI gates"
```

---

### Task 2: Configuration and its refusals

**Files:**
- Create: `src/hitchrail/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `is_loopback_host(host: str) -> bool`; `Config` (frozen dataclass) with fields `root: Path`, `host: str`, `port: int`, `token: str | None`, `session_prefix: str`, `stop_timeout: float`, `hard_floor_mb: int`, `soft_floor_mb: int`, `session_mb: int`, `claude_binary: str`, `sessions_dir: Path`, `tmux_socket: str | None`, `self_project: str | None`; property `Config.is_loopback -> bool`; property `Config.allowed_hosts -> tuple[str, ...]`; exception `ConfigError`.

- [ ] **Step 1: Write the failing tests**

`tests/test_config.py`:

```python
from pathlib import Path

import pytest

from starlette.applications import Starlette

from hitchrail.config import Config, ConfigError, is_loopback_host


def test_loopback_bind_needs_no_token(tmp_path: Path) -> None:
    cfg = Config(root=tmp_path)
    assert cfg.is_loopback
    assert cfg.token is None


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1", "127.0.0.5"])
def test_loopback_forms_are_recognised(tmp_path: Path, host: str) -> None:
    assert Config(root=tmp_path, host=host).is_loopback


def test_network_bind_without_a_token_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="token"):
        Config(root=tmp_path, host="0.0.0.0", token=None)


def test_network_bind_with_a_token_is_allowed(tmp_path: Path) -> None:
    cfg = Config(root=tmp_path, host="0.0.0.0", token="s3cret")
    assert not cfg.is_loopback


def test_missing_root_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="root"):
        Config(root=tmp_path / "nope")


def test_allowed_hosts_covers_loopback_and_the_bind_address(tmp_path: Path) -> None:
    cfg = Config(root=tmp_path, host="192.168.1.10", token="t")
    assert "192.168.1.10" in cfg.allowed_hosts
    assert "localhost" in cfg.allowed_hosts


def test_extra_allowed_hosts_are_included(tmp_path: Path) -> None:
    cfg = Config(root=tmp_path, host="0.0.0.0", token="t", extra_hosts=("box.lan",))
    assert "box.lan" in cfg.allowed_hosts


def test_wildcard_allowed_host_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="wildcard"):
        Config(root=tmp_path, host="0.0.0.0", token="t", extra_hosts=("*",))
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hitchrail.config'`

- [ ] **Step 3: Implement**

`src/hitchrail/config.py`:

```python
"""Runtime configuration, and the refusals that depend on it."""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field
from pathlib import Path

LOOPBACK_NAMES = frozenset({"localhost", "localhost.localdomain"})


def is_loopback_host(host: str) -> bool:
    """Module level so the CLI can ask the same question without a second copy."""
    if host in LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class ConfigError(ValueError):
    """The configuration is not one Hitchrail is willing to run with."""


@dataclass(frozen=True)
class Config:
    root: Path
    host: str = "127.0.0.1"
    port: int = 8787
    token: str | None = None
    extra_hosts: tuple[str, ...] = ()
    session_prefix: str = "hr-"
    stop_timeout: float = 30.0
    hard_floor_mb: int = 1536
    soft_floor_mb: int = 3072
    session_mb: int = 1536
    claude_binary: str = "claude"
    sessions_dir: Path = field(default_factory=lambda: Path.home() / ".claude" / "sessions")
    tmux_socket: str | None = None
    self_project: str | None = None

    def __post_init__(self) -> None:
        if not self.root.is_dir():
            raise ConfigError(f"root is not a directory: {self.root}")
        if any(h.strip() == "*" or h.startswith("*") for h in self.extra_hosts):
            raise ConfigError(
                "a wildcard allowed host defeats the point of the allowlist; "
                "name the hosts explicitly"
            )
        if not self.is_loopback and not self.token:
            raise ConfigError(
                "a token is required when binding to anything but loopback: "
                "anyone who can reach this API can run code as you"
            )

    @property
    def is_loopback(self) -> bool:
        return is_loopback_host(self.host)

    @property
    def allowed_hosts(self) -> tuple[str, ...]:
        """Hosts the server will answer to. Never contains a wildcard."""
        hosts = ["localhost", "127.0.0.1", "::1", "[::1]"]
        if self.host not in {"0.0.0.0", "::"}:  # noqa: S104
            hosts.append(self.host)
        hosts.extend(self.extra_hosts)
        return tuple(dict.fromkeys(hosts))
```

- [ ] **Step 4: Run to verify passing**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS, 8 tests.

- [ ] **Step 5: Gates and commit**

```bash
uv run ruff check && uv run mypy && uv run lint-imports
git add src/hitchrail/config.py tests/test_config.py
git commit -m "feat(config): configuration with a mandatory token off loopback"
```

---

### Task 3: Folder discovery and path safety

**Files:**
- Create: `src/hitchrail/discovery.py`
- Test: `tests/test_discovery.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `list_projects(root: Path) -> list[str]`; `project_path(root: Path, name: str) -> Path`; `create_project(root: Path, name: str) -> Path`; exceptions `InvalidName`, `OutsideRoot`, `AlreadyExists`; constant `NAME_PATTERN: re.Pattern[str]`.

- [ ] **Step 1: Write the failing tests**

`tests/test_discovery.py`:

```python
from pathlib import Path

import pytest

from hitchrail.discovery import (
    AlreadyExists,
    InvalidName,
    OutsideRoot,
    create_project,
    list_projects,
    project_path,
)


def test_lists_only_directories_case_insensitively(tmp_path: Path) -> None:
    (tmp_path / "beta").mkdir()
    (tmp_path / "Alpha").mkdir()
    (tmp_path / "notes.txt").write_text("x")
    assert list_projects(tmp_path) == ["Alpha", "beta"]


def test_lists_folders_without_git(tmp_path: Path) -> None:
    (tmp_path / "ideas").mkdir()
    assert list_projects(tmp_path) == ["ideas"]


def test_dotted_names_are_allowed(tmp_path: Path) -> None:
    (tmp_path / "dotted.site").mkdir()
    assert project_path(tmp_path, "dotted.site").is_dir()


@pytest.mark.parametrize(
    "name",
    ["..", ".", "../etc", "a/b", "a\\b", "", ".hidden", "-lead", "x" * 65, "a b"],
)
def test_traversal_and_junk_names_are_refused(tmp_path: Path, name: str) -> None:
    with pytest.raises(InvalidName):
        project_path(tmp_path, name)


def test_symlink_escaping_the_root_is_refused(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside_root"
    outside.mkdir(exist_ok=True)
    root = tmp_path / "root"
    root.mkdir()
    (root / "escape").symlink_to(outside, target_is_directory=True)
    with pytest.raises(OutsideRoot):
        project_path(root, "escape")


def test_creating_a_folder_makes_it_startable(tmp_path: Path) -> None:
    created = create_project(tmp_path, "fresh")
    assert created.is_dir()
    assert list_projects(tmp_path) == ["fresh"]


def test_creating_an_existing_folder_is_refused(tmp_path: Path) -> None:
    (tmp_path / "taken").mkdir()
    with pytest.raises(AlreadyExists):
        create_project(tmp_path, "taken")


def test_creating_a_traversal_name_is_refused(tmp_path: Path) -> None:
    with pytest.raises(InvalidName):
        create_project(tmp_path, "../evil")
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_discovery.py -v`
Expected: FAIL, module not found.

- [ ] **Step 3: Implement**

`src/hitchrail/discovery.py`:

```python
"""Listing and creating project folders, and the path safety around both."""

from __future__ import annotations

import re
from pathlib import Path

# Allowlist, not a denylist. A name that matches this cannot traverse,
# because it cannot contain a separator and cannot begin with a dot.
NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class InvalidName(ValueError):
    """The name is not one we are willing to turn into a path."""


class OutsideRoot(ValueError):
    """The name resolves to somewhere that is not inside the root."""


class AlreadyExists(ValueError):
    """A folder of that name is already there."""


def list_projects(root: Path) -> list[str]:
    return sorted((p.name for p in root.iterdir() if p.is_dir()), key=str.lower)


def project_path(root: Path, name: str) -> Path:
    """Resolve a project name to a directory inside root, or refuse.

    Two independent checks, deliberately. The pattern makes traversal
    impossible via the name itself; the resolution check catches a symlink
    inside the root that points somewhere else. Either alone would be enough
    for the cases we can think of, which is exactly why there are two.
    """
    if not NAME_PATTERN.match(name):
        raise InvalidName(f"not an acceptable project name: {name!r}")

    candidate = root / name
    if not candidate.is_dir():
        raise InvalidName(f"no such project: {name!r}")

    real_root = root.resolve()
    real = candidate.resolve()
    if real.parent != real_root:
        raise OutsideRoot(f"{name!r} resolves outside {real_root}")
    return real


def create_project(root: Path, name: str) -> Path:
    if not NAME_PATTERN.match(name):
        raise InvalidName(f"not an acceptable project name: {name!r}")
    target = root / name
    if target.exists():
        raise AlreadyExists(f"already there: {name!r}")
    target.mkdir()
    return target.resolve()
```

- [ ] **Step 4: Run to verify passing**

Run: `uv run pytest tests/test_discovery.py -v`
Expected: PASS, 16 tests (the parametrised case counts as 9).

- [ ] **Step 5: Gates and commit**

```bash
uv run ruff check && uv run mypy && uv run lint-imports
git add src/hitchrail/discovery.py tests/test_discovery.py
git commit -m "feat(discovery): list and create project folders, refuse traversal"
```

---

### Task 4: The tmux adapter and its five footguns

**Files:**
- Create: `src/hitchrail/tmux.py`
- Test: `tests/test_tmux.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `sanitize(name: str) -> str`; class `Tmux(prefix: str, socket: str | None = None, run: Runner | None = None)` with methods `session_name(project) -> str`, `session_target(project) -> str`, `pane_target(project) -> str`, `has_session(project) -> bool`, `list_sessions() -> list[str]`, `pane_pid(project) -> int | None`, `new_session(project, cwd, argv) -> None`, `kill_session(project) -> None`, `capture_pane(project, lines=40) -> str`, `send_keys(project, keys) -> None`; type alias `Runner = Callable[[list[str]], subprocess.CompletedProcess[str]]`; exception `NotOurSession`.

This is the module the spec calls out as carrying knowledge that is invisible from the outside. Each test below names the footgun it defends.

- [ ] **Step 1: Write the failing tests**

`tests/test_tmux.py`:

```python
from __future__ import annotations

import subprocess

import pytest

from hitchrail.tmux import NotOurSession, Tmux, sanitize


class FakeRunner:
    """Records argv and replays canned stdout per tmux subcommand."""

    def __init__(self, stdout: dict[str, str] | None = None, rc: dict[str, int] | None = None):
        self.calls: list[list[str]] = []
        self.stdout = stdout or {}
        self.rc = rc or {}

    def __call__(self, argv: list[str]) -> subprocess.CompletedProcess[str]:
        self.calls.append(argv)
        sub = next((a for a in argv if a in self.stdout or a in self.rc), "")
        return subprocess.CompletedProcess(
            argv, self.rc.get(sub, 0), self.stdout.get(sub, ""), ""
        )


def test_dots_and_colons_are_sanitised() -> None:
    # Footgun 1: tmux reads . and : as window and pane separators, so a
    # session named dotted.site can be created but never addressed.
    assert sanitize("dotted.site") == "dotted-it"
    assert sanitize("a:b.c") == "a-b-c"


def test_session_target_is_anchored_for_exact_matching() -> None:
    # Footgun 2: without the = prefix, has-session prefix matches, so
    # hr-vessel resolves hr-vessel-social.
    t = Tmux(prefix="hr-")
    assert t.session_target("vessel") == "=hr-vessel"


def test_pane_target_carries_a_trailing_colon() -> None:
    # Footgun 3: list-panes takes a pane target, ignores the = anchor, and
    # falls back to prefix matching. The trailing colon qualifies it as a
    # session, which is what makes the anchor mean anything.
    t = Tmux(prefix="hr-")
    assert t.pane_target("vessel") == "=hr-vessel:"


def test_has_session_uses_the_anchored_target() -> None:
    runner = FakeRunner()
    Tmux(prefix="hr-", run=runner).has_session("vessel")
    assert runner.calls[-1] == ["tmux", "has-session", "-t", "=hr-vessel"]


def test_pane_pid_uses_the_pane_target() -> None:
    runner = FakeRunner(stdout={"list-panes": "4242\n"})
    assert Tmux(prefix="hr-", run=runner).pane_pid("vessel") == 4242
    assert "=hr-vessel:" in runner.calls[-1]


def test_pane_pid_is_none_when_there_is_no_pane() -> None:
    runner = FakeRunner(stdout={"list-panes": ""}, rc={"list-panes": 1})
    assert Tmux(prefix="hr-", run=runner).pane_pid("gone") is None


def test_list_sessions_strips_the_prefix_and_ignores_strangers() -> None:
    runner = FakeRunner(stdout={"list-sessions": "hr-vessel\nhr-network\nsomeone-else\n"})
    assert Tmux(prefix="hr-", run=runner).list_sessions() == ["vessel", "network"]


def test_list_sessions_is_empty_when_no_server_is_running() -> None:
    runner = FakeRunner(stdout={"list-sessions": ""}, rc={"list-sessions": 1})
    assert Tmux(prefix="hr-", run=runner).list_sessions() == []


def test_new_session_passes_argv_as_a_list_and_never_a_shell_string() -> None:
    runner = FakeRunner()
    Tmux(prefix="hr-", run=runner).new_session("vessel", "/tmp/x", ["claude", "--flag"])
    argv = runner.calls[-1]
    assert argv[:5] == ["tmux", "new-session", "-d", "-s", "hr-vessel"]
    assert "-c" in argv and "/tmp/x" in argv
    assert argv[-2:] == ["claude", "--flag"]
    assert not any(" " in a and a.startswith("claude") for a in argv)


def test_kill_session_refuses_a_name_that_is_not_ours() -> None:
    # Footgun 5: never kill a session we did not create.
    runner = FakeRunner(stdout={"list-sessions": "someone-else\n"})
    with pytest.raises(NotOurSession):
        Tmux(prefix="hr-", run=runner).kill_session("../someone-else")


def test_kill_session_targets_only_the_named_session() -> None:
    runner = FakeRunner()
    Tmux(prefix="hr-", run=runner).kill_session("vessel")
    assert runner.calls[-1] == ["tmux", "kill-session", "-t", "=hr-vessel"]


def test_no_method_ever_issues_kill_server() -> None:
    runner = FakeRunner()
    t = Tmux(prefix="hr-", run=runner)
    t.has_session("a")
    t.list_sessions()
    t.kill_session("a")
    t.capture_pane("a")
    assert not any("kill-server" in argv for argv in runner.calls)


def test_socket_is_threaded_through_every_call() -> None:
    runner = FakeRunner()
    Tmux(prefix="hr-", socket="/tmp/hr.sock", run=runner).has_session("a")
    assert runner.calls[-1][:3] == ["tmux", "-S", "/tmp/hr.sock"]


def test_capture_pane_asks_for_the_requested_scrollback() -> None:
    runner = FakeRunner(stdout={"capture-pane": "line one\nline two\n"})
    text = Tmux(prefix="hr-", run=runner).capture_pane("vessel", lines=40)
    assert text == "line one\nline two\n"
    assert "-40" in runner.calls[-1]
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_tmux.py -v`
Expected: FAIL, module not found.

- [ ] **Step 3: Implement**

`src/hitchrail/tmux.py`:

```python
"""A thin tmux adapter.

Every method here exists to encode one non obvious tmux behaviour. Read the
comments before changing any of the target string construction: each one cost
real debugging to find and is invisible from the outside.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable

Runner = Callable[[list[str]], "subprocess.CompletedProcess[str]"]


class NotOurSession(ValueError):
    """Refusing to touch a session this instance did not create."""


def sanitize(name: str) -> str:
    """tmux reads '.' and ':' as window and pane separators in a target spec.

    A session called `dotted.site` can be created and then never addressed
    again, which reads as the session vanishing. Replace both.
    """
    return name.replace(".", "-").replace(":", "-")


def _default_runner(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, capture_output=True, text=True, check=False)


class Tmux:
    def __init__(
        self,
        prefix: str,
        socket: str | None = None,
        run: Runner | None = None,
    ) -> None:
        self.prefix = prefix
        self.socket = socket
        self._run: Runner = run or _default_runner

    def _argv(self, *args: str) -> list[str]:
        base = ["tmux"]
        if self.socket:
            base += ["-S", self.socket]
        return base + list(args)

    def session_name(self, project: str) -> str:
        return f"{self.prefix}{sanitize(project)}"

    def session_target(self, project: str) -> str:
        """'=' anchors an exact match. Without it `hr-vessel` prefix matches
        `hr-vessel-social`, and a stopped project reads as running."""
        return f"={self.session_name(project)}"

    def pane_target(self, project: str) -> str:
        """list-panes takes a PANE target, ignores a leading '=', and falls
        back to prefix matching. The trailing ':' qualifies the string as a
        session, which is what makes the anchor take effect."""
        return f"={self.session_name(project)}:"

    def has_session(self, project: str) -> bool:
        return self._run(self._argv("has-session", "-t", self.session_target(project))).returncode == 0

    def list_sessions(self) -> list[str]:
        result = self._run(self._argv("list-sessions", "-F", "#{session_name}"))
        if result.returncode != 0:
            return []  # no server running is normal, not an error
        return [
            line[len(self.prefix) :]
            for line in result.stdout.splitlines()
            if line.startswith(self.prefix)
        ]

    def pane_pid(self, project: str) -> int | None:
        result = self._run(
            self._argv("list-panes", "-t", self.pane_target(project), "-F", "#{pane_pid}")
        )
        if result.returncode != 0:
            return None
        first = result.stdout.split()
        return int(first[0]) if first else None

    def new_session(self, project: str, cwd: str, argv: list[str]) -> None:
        self._run(
            self._argv(
                "new-session", "-d", "-s", self.session_name(project), "-c", cwd, *argv
            )
        )

    def kill_session(self, project: str) -> None:
        name = self.session_name(project)
        if not name.startswith(self.prefix) or "/" in project:
            raise NotOurSession(project)
        self._run(self._argv("kill-session", "-t", self.session_target(project)))

    def capture_pane(self, project: str, lines: int = 40) -> str:
        result = self._run(
            self._argv(
                "capture-pane", "-p", "-J", "-S", f"-{lines}", "-t", self.pane_target(project)
            )
        )
        return result.stdout if result.returncode == 0 else ""

    def send_keys(self, project: str, keys: str) -> None:
        self._run(self._argv("send-keys", "-t", self.pane_target(project), keys, "Enter"))
```

- [ ] **Step 4: Run to verify passing**

Run: `uv run pytest tests/test_tmux.py -v`
Expected: PASS, 14 tests.

- [ ] **Step 5: Gates and commit**

```bash
uv run ruff check && uv run mypy && uv run lint-imports
git add src/hitchrail/tmux.py tests/test_tmux.py
git commit -m "feat(tmux): adapter carrying the five tmux footguns, each with a named test"
```

---

### Task 5: The process table adapter

**Files:**
- Create: `src/hitchrail/procs.py`
- Test: `tests/test_procs.py`

**Interfaces:**
- Consumes: nothing.
- Produces: frozen dataclass `Proc(pid: int, ppid: int, rss_kb: int, etime_s: int, args: str)`; `snapshot(run: Runner | None = None) -> ProcTable`; class `ProcTable(procs: list[Proc])` with `by_pid: dict[int, Proc]`, `children(pid) -> list[Proc]`, `descendants(pid) -> list[Proc]`, `tree_rss_mb(pid) -> int`, `matching(marker: str) -> list[Proc]`, `first_matching_in_tree(pid, marker) -> Proc | None`; reuses `Runner` from `hitchrail.tmux`.

- [ ] **Step 1: Write the failing tests**

`tests/test_procs.py`:

```python
from __future__ import annotations

import subprocess

from hitchrail.procs import Proc, ProcTable, parse_ps, snapshot

PS_OUTPUT = """\
  100     1  4096      600 /usr/bin/tmux new-session -d -s hr-a
  101   100 512000     600 claude --dangerously-skip-permissions --remote-control a
  102   101  20480      590 python3 helper.py
  200     1 480000     120 claude --dangerously-skip-permissions --remote-control orphan
  300     1   2048     999 /usr/bin/gedit notes.txt
"""


def table() -> ProcTable:
    return ProcTable(parse_ps(PS_OUTPUT))


def test_parses_every_row() -> None:
    procs = parse_ps(PS_OUTPUT)
    assert len(procs) == 5
    assert procs[1] == Proc(
        pid=101,
        ppid=100,
        rss_kb=512000,
        etime_s=600,
        args="claude --dangerously-skip-permissions --remote-control a",
    )


def test_args_containing_spaces_survive() -> None:
    assert parse_ps(PS_OUTPUT)[4].args == "/usr/bin/gedit notes.txt"


def test_blank_and_malformed_rows_are_skipped() -> None:
    assert parse_ps("\n  oops\n  1 2 3 4 ok\n") == [
        Proc(pid=1, ppid=2, rss_kb=3, etime_s=4, args="ok")
    ]


def test_children_and_descendants() -> None:
    t = table()
    assert [p.pid for p in t.children(100)] == [101]
    assert sorted(p.pid for p in t.descendants(100)) == [101, 102]


def test_tree_rss_sums_the_whole_subtree_in_megabytes() -> None:
    # 4096 + 512000 + 20480 kB is 524 MB after integer division.
    assert table().tree_rss_mb(100) == 524


def test_tree_rss_of_an_unknown_pid_is_zero() -> None:
    assert table().tree_rss_mb(9999) == 0


def test_matching_finds_every_claude_anywhere() -> None:
    assert sorted(p.pid for p in table().matching("--remote-control")) == [101, 200]


def test_first_matching_in_tree_finds_a_child_not_just_the_root() -> None:
    found = table().first_matching_in_tree(100, "--remote-control")
    assert found is not None
    assert found.pid == 101


def test_first_matching_in_tree_returns_none_when_absent() -> None:
    assert table().first_matching_in_tree(300, "--remote-control") is None


def test_snapshot_asks_ps_for_etimes_not_etime() -> None:
    calls: list[list[str]] = []

    def runner(argv: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, PS_OUTPUT, "")

    assert len(snapshot(run=runner).by_pid) == 5
    # etimes is seconds; etime is a d-hh:mm:ss string nobody should parse.
    assert "pid,ppid,rss,etimes,args" in " ".join(calls[0])
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_procs.py -v`
Expected: FAIL, module not found.

- [ ] **Step 3: Implement**

`src/hitchrail/procs.py`:

```python
"""One snapshot of the process table, and the queries the engine asks of it."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field

from hitchrail.tmux import Runner


@dataclass(frozen=True)
class Proc:
    pid: int
    ppid: int
    rss_kb: int
    etime_s: int
    args: str


def parse_ps(text: str) -> list[Proc]:
    procs: list[Proc] = []
    for line in text.splitlines():
        parts = line.split(maxsplit=4)
        if len(parts) < 5:
            continue
        try:
            pid, ppid, rss, etimes = (int(p) for p in parts[:4])
        except ValueError:
            continue
        procs.append(Proc(pid=pid, ppid=ppid, rss_kb=rss, etime_s=etimes, args=parts[4]))
    return procs


def _default_runner(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, capture_output=True, text=True, check=False)


@dataclass
class ProcTable:
    procs: list[Proc]
    by_pid: dict[int, Proc] = field(init=False)
    _by_ppid: dict[int, list[Proc]] = field(init=False)

    def __post_init__(self) -> None:
        self.by_pid = {p.pid: p for p in self.procs}
        self._by_ppid = {}
        for p in self.procs:
            self._by_ppid.setdefault(p.ppid, []).append(p)

    def children(self, pid: int) -> list[Proc]:
        return list(self._by_ppid.get(pid, ()))

    def descendants(self, pid: int) -> list[Proc]:
        out: list[Proc] = []
        stack = self.children(pid)
        while stack:
            proc = stack.pop()
            out.append(proc)
            stack.extend(self.children(proc.pid))
        return out

    def tree_rss_mb(self, pid: int) -> int:
        root = self.by_pid.get(pid)
        if root is None:
            return 0
        total_kb = root.rss_kb + sum(p.rss_kb for p in self.descendants(pid))
        return total_kb // 1024

    def matching(self, marker: str) -> list[Proc]:
        return [p for p in self.procs if marker in p.args]

    def first_matching_in_tree(self, pid: int, marker: str) -> Proc | None:
        root = self.by_pid.get(pid)
        if root is not None and marker in root.args:
            return root
        for proc in self.descendants(pid):
            if marker in proc.args:
                return proc
        return None


def snapshot(run: Runner | None = None) -> ProcTable:
    runner = run or _default_runner
    # etimes gives whole seconds. etime gives "1-02:03:04", which nobody
    # should be parsing.
    result = runner(["ps", "-eo", "pid,ppid,rss,etimes,args", "--no-headers"])
    return ProcTable(parse_ps(result.stdout))
```

- [ ] **Step 4: Run to verify passing**

Run: `uv run pytest tests/test_procs.py -v`
Expected: PASS, 10 tests.

- [ ] **Step 5: Gates and commit**

```bash
uv run ruff check && uv run mypy && uv run lint-imports
git add src/hitchrail/procs.py tests/test_procs.py
git commit -m "feat(procs): process table snapshot with subtree memory and marker search"
```

---

### Task 6: The Claude Code quarantine

**Files:**
- Create: `src/hitchrail/claude_ipc.py`
- Test: `tests/test_claude_ipc.py`

**Interfaces:**
- Consumes: nothing.
- Produces: constant `REMOTE_CONTROL_MARKER = "--remote-control"`; `launch_argv(binary: str, project: str) -> list[str]`; `session_url(pid: int, sessions_dir: Path, pane_text: str | None = None) -> str | None`; `bridge_url(pid: int, sessions_dir: Path) -> str | None`.

Everything in this module depends on undocumented Claude Code internals. It is the only module allowed to know about them, so that a breaking change upstream touches one file.

- [ ] **Step 1: Write the failing tests**

`tests/test_claude_ipc.py`:

```python
import json
from pathlib import Path

from hitchrail.claude_ipc import (
    REMOTE_CONTROL_MARKER,
    bridge_url,
    launch_argv,
    session_url,
)


def test_launch_argv_carries_the_marker_we_identify_sessions_by() -> None:
    argv = launch_argv("claude", "vessel")
    assert argv[0] == "claude"
    assert REMOTE_CONTROL_MARKER in argv
    assert argv[-1] == "vessel"


def test_launch_argv_is_a_list_with_no_shell_metacharacters_joined() -> None:
    assert all(isinstance(a, str) and " " not in a for a in launch_argv("claude", "a"))


def test_state_file_supplies_the_url_verbatim(tmp_path: Path) -> None:
    (tmp_path / "42.json").write_text(
        json.dumps({"bridgeSessionId": "session_01Kx2c8zfkvZsKR1kZjpTX1G"})
    )
    assert session_url(42, tmp_path) == (
        "https://claude.ai/code/session_01Kx2c8zfkvZsKR1kZjpTX1G"
    )


def test_the_session_prefix_is_not_added_twice(tmp_path: Path) -> None:
    (tmp_path / "42.json").write_text(json.dumps({"bridgeSessionId": "session_abc"}))
    assert session_url(42, tmp_path, None) == "https://claude.ai/code/session_abc"


def test_missing_state_file_falls_back_to_the_pane(tmp_path: Path) -> None:
    pane = "welcome\nhttps://claude.ai/code/session_fallback\n$ "
    assert session_url(9, tmp_path, pane) == "https://claude.ai/code/session_fallback"


def test_pane_fallback_takes_the_last_url(tmp_path: Path) -> None:
    pane = "https://claude.ai/code/session_old\nhttps://claude.ai/code/session_new\n"
    assert session_url(9, tmp_path, pane) == "https://claude.ai/code/session_new"


def test_unreadable_state_file_does_not_raise(tmp_path: Path) -> None:
    (tmp_path / "7.json").write_text("{not json")
    assert session_url(7, tmp_path, None) is None


def test_bridge_url_refuses_the_pane_fallback(tmp_path: Path) -> None:
    # bridge_url answers "is there a live bridge", so a URL that merely
    # appeared as text in the terminal must not count.
    assert bridge_url(9, tmp_path) is None


def test_no_url_anywhere_is_none(tmp_path: Path) -> None:
    assert session_url(9, tmp_path, "nothing here") is None
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_claude_ipc.py -v`
Expected: FAIL, module not found.

- [ ] **Step 3: Implement**

`src/hitchrail/claude_ipc.py`:

```python
"""Everything that knows about Claude Code's internals.

UNSTABLE. None of this is a documented interface. `~/.claude/sessions/<pid>.json`
and its `bridgeSessionId` key are implementation details that can change or
disappear in any Claude Code release. They are quarantined here so that when
they do, exactly one module needs fixing and the rest of Hitchrail degrades to
reporting "pending" rather than reporting something false.

Verified against claude 2.1.205: the state file held
  "bridgeSessionId":"session_01Kx2c8zfkvZsKR1kZjpTX1G"
and the terminal printed
  https://claude.ai/code/session_01Kx2c8zfkvZsKR1kZjpTX1G
so the value is the URL path segment verbatim, `session_` prefix included. Do
not add one.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REMOTE_CONTROL_MARKER = "--remote-control"
URL_BASE = "https://claude.ai/code/"

_URL_RE = re.compile(r"https://claude\.ai/code/[A-Za-z0-9_-]+")


def launch_argv(binary: str, project: str) -> list[str]:
    return [binary, "--dangerously-skip-permissions", REMOTE_CONTROL_MARKER, project]


def bridge_url(pid: int, sessions_dir: Path) -> str | None:
    """The URL according to Claude's own state file, or nothing.

    Stricter than session_url on purpose: this answers "is there a live
    bridge", so the terminal fallback is not acceptable here.
    """
    state = sessions_dir / f"{pid}.json"
    try:
        data = json.loads(state.read_text())
    except (OSError, ValueError):
        return None
    session_id = data.get("bridgeSessionId")
    if not isinstance(session_id, str) or not session_id:
        return None
    return f"{URL_BASE}{session_id}"


def session_url(pid: int, sessions_dir: Path, pane_text: str | None = None) -> str | None:
    """Good enough for a status column.

    Falls back to scraping the terminal, which can pick up a URL that merely
    arrived as message text rather than one belonging to a live bridge. Fine
    for display, useless for deciding anything. Use bridge_url for decisions.
    """
    from_state = bridge_url(pid, sessions_dir)
    if from_state:
        return from_state
    if not pane_text:
        return None
    found = _URL_RE.findall(pane_text)
    return found[-1] if found else None
```

- [ ] **Step 4: Run to verify passing**

Run: `uv run pytest tests/test_claude_ipc.py -v`
Expected: PASS, 9 tests.

- [ ] **Step 5: Gates and commit**

```bash
uv run ruff check && uv run mypy && uv run lint-imports
git add src/hitchrail/claude_ipc.py tests/test_claude_ipc.py
git commit -m "feat(claude-ipc): quarantine the undocumented session bridge lookup"
```

---

### Task 7: The memory guard

**Files:**
- Create: `src/hitchrail/ram.py`
- Test: `tests/test_ram.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `available_mb(meminfo_text: str) -> int`; `read_meminfo(path: Path = Path("/proc/meminfo")) -> str`; `StrEnum Verdict` with members `OK`, `SOFT`, `HARD`; `guard(available_mb: int, need_mb: int, hard_mb: int, soft_mb: int) -> Verdict`.

- [ ] **Step 1: Write the failing tests**

`tests/test_ram.py`:

```python
import pytest

from hitchrail.ram import Verdict, available_mb, guard

MEMINFO = """\
MemTotal:       32729088 kB
MemFree:        16868352 kB
MemAvailable:   25198592 kB
Buffers:          123456 kB
"""


def test_reads_mem_available_not_mem_free() -> None:
    assert available_mb(MEMINFO) == 24608


def test_missing_mem_available_is_zero_not_a_crash() -> None:
    assert available_mb("MemTotal: 100 kB\n") == 0


@pytest.mark.parametrize(
    ("available", "expected"),
    [
        (24608, Verdict.OK),
        (5000, Verdict.OK),
        (4608, Verdict.OK),
        (4607, Verdict.SOFT),
        (3072, Verdict.SOFT),
        (3071, Verdict.HARD),
        (0, Verdict.HARD),
    ],
)
def test_guard_thresholds(available: int, expected: Verdict) -> None:
    # Starting costs 1536 MB. Below 3072 MB free we refuse outright; between
    # that and (soft + need) we ask first.
    assert guard(available, need_mb=1536, hard_mb=1536, soft_mb=3072) is expected


def test_hard_floor_is_about_what_is_left_after_starting() -> None:
    # 3000 free, 1536 needed, leaves 1464, which is under the 1536 hard floor.
    assert guard(3000, need_mb=1536, hard_mb=1536, soft_mb=0) is Verdict.HARD


def test_verdict_serialises_as_its_name() -> None:
    assert str(Verdict.SOFT) == "soft"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_ram.py -v`
Expected: FAIL, module not found.

- [ ] **Step 3: Implement**

`src/hitchrail/ram.py`:

```python
"""Memory readings, and the decision about whether starting is wise.

The thresholds are not academic. A machine that runs out of memory here does
not degrade: the kernel reaps a whole tmux scope and a live agent disappears
mid task. A web interface makes starting one tap, so the guard matters more
here than it does behind a CLI.
"""

from __future__ import annotations

import re
from enum import StrEnum
from pathlib import Path

_AVAILABLE_RE = re.compile(r"^MemAvailable:\s+(\d+)\s+kB", re.MULTILINE)


class Verdict(StrEnum):
    OK = "ok"
    SOFT = "soft"
    HARD = "hard"


def read_meminfo(path: Path = Path("/proc/meminfo")) -> str:
    try:
        return path.read_text()
    except OSError:
        return ""


def available_mb(meminfo_text: str) -> int:
    match = _AVAILABLE_RE.search(meminfo_text)
    return int(match.group(1)) // 1024 if match else 0


def guard(available_mb: int, need_mb: int, hard_mb: int, soft_mb: int) -> Verdict:
    """Decide against what would be LEFT after starting, not what is free now."""
    remaining = available_mb - need_mb
    if remaining < hard_mb:
        return Verdict.HARD
    if remaining < soft_mb:
        return Verdict.SOFT
    return Verdict.OK
```

- [ ] **Step 4: Run to verify passing**

Run: `uv run pytest tests/test_ram.py -v`
Expected: PASS, 11 tests.

- [ ] **Step 5: Gates and commit**

```bash
uv run ruff check && uv run mypy && uv run lint-imports
git add src/hitchrail/ram.py tests/test_ram.py
git commit -m "feat(ram): memory guard deciding on what is left after starting"
```

---

### Task 8: State derivation across all four states

**Files:**
- Create: `src/hitchrail/engine.py`
- Test: `tests/conftest.py`
- Test: `tests/test_engine_state.py`

**Interfaces:**
- Consumes: `Config`, `Tmux`, `ProcTable`, `discovery.list_projects`, `claude_ipc.*`, `ram.*`.
- Produces: `StrEnum State` with `RUNNING`, `STALE`, `DETACHED`, `STOPPED`; frozen dataclass `Session(name, state, pid, ram_mb, uptime_s, url, stopping, protected)`; class `Engine(config, tmux, procs_fn, meminfo_fn, clock)` with `list() -> list[Session]` and `get(name) -> Session`. Later tasks add `start`, `stop`, `kill` and `logs` to the same class.

- [ ] **Step 1: Write the shared fixtures**

`tests/conftest.py`:

```python
from __future__ import annotations

import subprocess
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from hitchrail.config import Config
from hitchrail.procs import ProcTable, parse_ps
from hitchrail.tmux import Tmux


class FakeTmux(Tmux):
    """A Tmux whose server is a dict."""

    def __init__(self, prefix: str = "hr-", sessions: dict[str, int] | None = None) -> None:
        super().__init__(prefix=prefix, run=self._never)
        self.sessions: dict[str, int] = dict(sessions or {})
        self.pane_text: dict[str, str] = {}
        self.killed: list[str] = []
        self.started: list[tuple[str, str, list[str]]] = []
        self.sent: list[tuple[str, str]] = []
        self.next_pid = 1000

    @staticmethod
    def _never(argv: list[str]) -> subprocess.CompletedProcess[str]:
        raise AssertionError(f"FakeTmux must never shell out: {argv}")

    def has_session(self, project: str) -> bool:
        return project in self.sessions

    def list_sessions(self) -> list[str]:
        return sorted(self.sessions)

    def pane_pid(self, project: str) -> int | None:
        return self.sessions.get(project)

    def new_session(self, project: str, cwd: str, argv: list[str]) -> None:
        self.started.append((project, cwd, argv))
        self.next_pid += 1
        self.sessions[project] = self.next_pid

    def kill_session(self, project: str) -> None:
        self.killed.append(project)
        self.sessions.pop(project, None)

    def capture_pane(self, project: str, lines: int = 40) -> str:
        return self.pane_text.get(project, "")

    def send_keys(self, project: str, keys: str) -> None:
        self.sent.append((project, keys))


class FakeClock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def root(tmp_path: Path) -> Path:
    for name in ("vessel", "vessel-social", "network", "dotted.site"):
        (tmp_path / name).mkdir()
    return tmp_path


@pytest.fixture
def config(root: Path) -> Config:
    return Config(root=root, sessions_dir=root / ".sessions")


@pytest.fixture
def sessions_dir(config: Config) -> Path:
    config.sessions_dir.mkdir(parents=True, exist_ok=True)
    return config.sessions_dir


def procs_from(text: str) -> Callable[[], ProcTable]:
    def _fn() -> ProcTable:
        return ProcTable(parse_ps(text))

    return _fn


@pytest.fixture
def plenty_of_memory() -> Callable[[], str]:
    return lambda: "MemAvailable:   25198592 kB\n"
```

- [ ] **Step 2: Write the failing state tests**

`tests/test_engine_state.py`:

```python
from __future__ import annotations

from pathlib import Path
from collections.abc import Callable

from hitchrail.config import Config
from hitchrail.engine import Engine, State

from .conftest import FakeClock, FakeTmux, procs_from

TMUX_PID = 500
CLAUDE_PID = 501

RUNNING_PS = f"""\
 {TMUX_PID}     1   4096   600 tmux new-session -d -s hr-vessel
 {CLAUDE_PID}  {TMUX_PID} 512000 600 claude --dangerously-skip-permissions --remote-control vessel
"""

STALE_PS = f"""\
 {TMUX_PID}     1   4096   600 tmux new-session -d -s hr-vessel
"""

DETACHED_PS = """\
 900     1 480000   120 claude --dangerously-skip-permissions --remote-control vessel
"""


def build(
    config: Config,
    tmux: FakeTmux,
    ps_text: str,
    memory: Callable[[], str],
) -> Engine:
    return Engine(
        config=config,
        tmux=tmux,
        procs_fn=procs_from(ps_text),
        meminfo_fn=memory,
        clock=FakeClock(),
    )


def test_running_when_tmux_owns_a_live_claude(config, plenty_of_memory) -> None:
    tmux = FakeTmux(sessions={"vessel": TMUX_PID})
    session = build(config, tmux, RUNNING_PS, plenty_of_memory).get("vessel")
    assert session.state is State.RUNNING
    assert session.pid == CLAUDE_PID
    assert session.ram_mb == 500
    assert session.uptime_s == 600


def test_stale_when_the_terminal_outlives_claude(config, plenty_of_memory) -> None:
    tmux = FakeTmux(sessions={"vessel": TMUX_PID})
    session = build(config, tmux, STALE_PS, plenty_of_memory).get("vessel")
    assert session.state is State.STALE
    assert session.pid is None


def test_detached_when_claude_outlives_its_terminal(config, plenty_of_memory) -> None:
    # The blind spot. A tool that only asks tmux reports this as stopped,
    # which invites starting a second agent in the same folder.
    session = build(config, FakeTmux(), DETACHED_PS, plenty_of_memory).get("vessel")
    assert session.state is State.DETACHED
    assert session.pid == 900


def test_stopped_when_neither_exists(config, plenty_of_memory) -> None:
    session = build(config, FakeTmux(), "", plenty_of_memory).get("network")
    assert session.state is State.STOPPED
    assert session.pid is None
    assert session.url is None


def test_sibling_prefixes_do_not_bleed(config, plenty_of_memory) -> None:
    tmux = FakeTmux(sessions={"vessel-social": TMUX_PID})
    engine = build(config, tmux, RUNNING_PS, plenty_of_memory)
    assert engine.get("vessel").state is State.STOPPED


def test_list_covers_every_folder_including_dotted_names(config, plenty_of_memory) -> None:
    names = [s.name for s in build(config, FakeTmux(), "", plenty_of_memory).list()]
    assert names == ["vessel", "vessel-social", "network", "dotted.site"]


def test_url_comes_from_the_state_file(config, sessions_dir, plenty_of_memory) -> None:
    (sessions_dir / f"{CLAUDE_PID}.json").write_text('{"bridgeSessionId":"session_zz"}')
    tmux = FakeTmux(sessions={"vessel": TMUX_PID})
    session = build(config, tmux, RUNNING_PS, plenty_of_memory).get("vessel")
    assert session.url == "https://claude.ai/code/session_zz"


def test_url_is_none_while_pending(config, plenty_of_memory) -> None:
    tmux = FakeTmux(sessions={"vessel": TMUX_PID})
    assert build(config, tmux, RUNNING_PS, plenty_of_memory).get("vessel").url is None


def test_the_controller_project_is_marked_protected(root, plenty_of_memory) -> None:
    cfg = Config(root=root, sessions_dir=root / ".s", self_project="vessel")
    tmux = FakeTmux(sessions={"vessel": TMUX_PID})
    assert build(cfg, tmux, RUNNING_PS, plenty_of_memory).get("vessel").protected
    assert not build(cfg, tmux, RUNNING_PS, plenty_of_memory).get("network").protected
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/test_engine_state.py -v`
Expected: FAIL, no module named `hitchrail.engine`.

- [ ] **Step 4: Implement**

`src/hitchrail/engine.py`:

```python
"""State derivation and session lifecycle.

No database. Everything is read from tmux and the process table when asked,
so there is nothing that can drift out of step with the machine. The single
exception is documented in Task 10: the fact that a graceful stop is in
flight, which lives in memory and is deliberately not persisted.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from hitchrail import claude_ipc, discovery, ram
from hitchrail.config import Config
from hitchrail.procs import ProcTable, snapshot
from hitchrail.tmux import Tmux


class State(StrEnum):
    RUNNING = "running"
    STALE = "stale"
    DETACHED = "detached"
    STOPPED = "stopped"


@dataclass(frozen=True)
class Session:
    name: str
    state: State
    pid: int | None = None
    ram_mb: int = 0
    uptime_s: int = 0
    url: str | None = None
    stopping: bool = False
    protected: bool = False


class Engine:
    def __init__(
        self,
        config: Config,
        tmux: Tmux | None = None,
        procs_fn: Callable[[], ProcTable] | None = None,
        meminfo_fn: Callable[[], str] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config
        self.tmux = tmux or Tmux(prefix=config.session_prefix, socket=config.tmux_socket)
        self._procs_fn = procs_fn or snapshot
        self._meminfo_fn = meminfo_fn or (lambda: ram.read_meminfo())
        self._clock = clock
        self._stopping: dict[str, float] = {}

    # -- reading -------------------------------------------------------

    def list(self) -> list[Session]:
        table = self._procs_fn()
        return [
            self._derive(name, table) for name in discovery.list_projects(self.config.root)
        ]

    def get(self, name: str) -> Session:
        return self._derive(name, self._procs_fn())

    def available_mb(self) -> int:
        return ram.available_mb(self._meminfo_fn())

    def _derive(self, name: str, table: ProcTable) -> Session:
        protected = (
            self.config.self_project is not None and name == self.config.self_project
        )
        pane_pid = self.tmux.pane_pid(name) if self.tmux.has_session(name) else None

        if pane_pid is not None:
            claude = table.first_matching_in_tree(
                pane_pid, claude_ipc.REMOTE_CONTROL_MARKER
            )
            if claude is not None:
                return self._live(name, claude.pid, table, State.RUNNING, protected)
            return Session(name=name, state=State.STALE, protected=protected)

        orphan = self._find_detached(name, table)
        if orphan is not None:
            return self._live(name, orphan, table, State.DETACHED, protected)

        return Session(name=name, state=State.STOPPED, protected=protected)

    def _find_detached(self, name: str, table: ProcTable) -> int | None:
        """A Claude that outlived its terminal.

        Without this, such a session reads as stopped while it is very much
        alive, and starting again gives you two agents in one folder.
        """
        owned: set[int] = set()
        for project in self.tmux.list_sessions():
            pid = self.tmux.pane_pid(project)
            if pid is None:
                continue
            owned.add(pid)
            owned.update(p.pid for p in table.descendants(pid))

        suffix = f"{claude_ipc.REMOTE_CONTROL_MARKER} {name}"
        for proc in table.matching(claude_ipc.REMOTE_CONTROL_MARKER):
            if proc.pid in owned:
                continue
            if proc.args.rstrip().endswith(suffix):
                return proc.pid
        return None

    def _live(
        self, name: str, pid: int, table: ProcTable, state: State, protected: bool
    ) -> Session:
        proc = table.by_pid.get(pid)
        pane = self.tmux.capture_pane(name, lines=200) if state is State.RUNNING else None
        return Session(
            name=name,
            state=state,
            pid=pid,
            ram_mb=table.tree_rss_mb(pid),
            uptime_s=proc.etime_s if proc else 0,
            url=claude_ipc.session_url(pid, self.config.sessions_dir, pane),
            stopping=name in self._stopping,
            protected=protected,
        )
```

- [ ] **Step 5: Run to verify passing**

Run: `uv run pytest tests/test_engine_state.py -v`
Expected: PASS, 9 tests.

- [ ] **Step 6: Gates and commit**

```bash
uv run ruff check && uv run mypy && uv run lint-imports
git add src/hitchrail/engine.py tests/conftest.py tests/test_engine_state.py
git commit -m "feat(engine): derive all four states, including the detached blind spot"
```

---

### Task 9: Starting a session

**Files:**
- Modify: `src/hitchrail/engine.py`
- Test: `tests/test_engine_start.py`

**Interfaces:**
- Consumes: everything from Task 8.
- Produces: `Engine.start(name: str, acknowledged: bool = False) -> Session`; exceptions `EngineError`, `UnknownProject`, `AlreadyRunning`, `MemoryRefused(available_mb, needed_mb)`, `MemoryNeedsAck(available_mb, needed_mb)`, `StartFailed(output)`, `Protected`.

- [ ] **Step 1: Write the failing tests**

`tests/test_engine_start.py`:

```python
from __future__ import annotations

import pytest

from hitchrail.config import Config
from hitchrail.engine import (
    AlreadyRunning,
    Engine,
    MemoryNeedsAck,
    MemoryRefused,
    StartFailed,
    State,
    UnknownProject,
)

from .conftest import FakeClock, FakeTmux, procs_from

STARTED_PS = """\
 1001     1   4096    5 tmux new-session -d -s hr-network
 1002  1001 300000    5 claude --dangerously-skip-permissions --remote-control network
"""


def build(config: Config, tmux: FakeTmux, ps: str, mem: str) -> Engine:
    return Engine(
        config=config,
        tmux=tmux,
        procs_fn=procs_from(ps),
        meminfo_fn=lambda: mem,
        clock=FakeClock(),
    )


def test_start_launches_with_the_right_cwd_and_argv(config) -> None:
    tmux = FakeTmux()
    engine = build(config, tmux, STARTED_PS, "MemAvailable: 25198592 kB\n")
    session = engine.start("network")
    project, cwd, argv = tmux.started[0]
    assert project == "network"
    assert cwd == str((config.root / "network").resolve())
    assert argv == [
        "claude",
        "--dangerously-skip-permissions",
        "--remote-control",
        "network",
    ]
    assert session.state is State.RUNNING


def test_start_is_idempotent_for_a_live_session(config) -> None:
    tmux = FakeTmux(sessions={"network": 1001})
    engine = build(config, tmux, STARTED_PS, "MemAvailable: 25198592 kB\n")
    with pytest.raises(AlreadyRunning):
        engine.start("network")
    assert tmux.started == []


def test_unknown_project_is_refused(config) -> None:
    engine = build(config, FakeTmux(), "", "MemAvailable: 25198592 kB\n")
    with pytest.raises(UnknownProject):
        engine.start("nope")


def test_traversal_name_is_refused_before_anything_spawns(config) -> None:
    tmux = FakeTmux()
    engine = build(config, tmux, "", "MemAvailable: 25198592 kB\n")
    with pytest.raises(UnknownProject):
        engine.start("../../etc")
    assert tmux.started == []


def test_hard_memory_floor_refuses_and_spawns_nothing(config) -> None:
    tmux = FakeTmux()
    engine = build(config, tmux, "", "MemAvailable:   2097152 kB\n")  # 2048 MB
    with pytest.raises(MemoryRefused) as excinfo:
        engine.start("network")
    assert excinfo.value.available_mb == 2048
    assert excinfo.value.needed_mb == 1536
    assert tmux.started == []


def test_soft_threshold_asks_first(config) -> None:
    tmux = FakeTmux()
    engine = build(config, tmux, "", "MemAvailable:   4194304 kB\n")  # 4096 MB
    with pytest.raises(MemoryNeedsAck):
        engine.start("network")
    assert tmux.started == []


def test_soft_threshold_proceeds_once_acknowledged(config) -> None:
    tmux = FakeTmux()
    engine = build(config, tmux, STARTED_PS, "MemAvailable:   4194304 kB\n")
    engine.start("network", acknowledged=True)
    assert tmux.started != []


def test_acknowledgement_never_overrides_the_hard_floor(config) -> None:
    tmux = FakeTmux()
    engine = build(config, tmux, "", "MemAvailable:   1048576 kB\n")  # 1024 MB
    with pytest.raises(MemoryRefused):
        engine.start("network", acknowledged=True)
    assert tmux.started == []


def test_a_session_that_dies_immediately_is_reported_as_failed(config) -> None:
    tmux = FakeTmux()
    tmux.pane_text["network"] = "Error: could not start\n"
    engine = build(config, tmux, "", "MemAvailable: 25198592 kB\n")
    with pytest.raises(StartFailed) as excinfo:
        engine.start("network")
    assert "could not start" in excinfo.value.output


def test_concurrent_starts_serialise(config) -> None:
    import threading

    tmux = FakeTmux()
    engine = build(config, tmux, STARTED_PS, "MemAvailable: 25198592 kB\n")
    errors: list[Exception] = []

    def go() -> None:
        try:
            engine.start("network")
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=go) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(tmux.started) <= 1
    assert all(isinstance(e, AlreadyRunning) for e in errors)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_engine_start.py -v`
Expected: FAIL, `ImportError: cannot import name 'AlreadyRunning'`.

- [ ] **Step 3: Add the exceptions to `src/hitchrail/engine.py`**

Insert after the `State` enum:

```python
class EngineError(Exception):
    """Base for every refusal the engine makes."""


class UnknownProject(EngineError):
    pass


class AlreadyRunning(EngineError):
    pass


class NotRunning(EngineError):
    pass


class Protected(EngineError):
    """This session is the one Hitchrail is running inside."""


class StartFailed(EngineError):
    def __init__(self, output: str) -> None:
        super().__init__("the session exited immediately after starting")
        self.output = output


class _MemoryVerdict(EngineError):
    def __init__(self, available_mb: int, needed_mb: int) -> None:
        super().__init__(f"{available_mb} MB available, {needed_mb} MB needed")
        self.available_mb = available_mb
        self.needed_mb = needed_mb


class MemoryRefused(_MemoryVerdict):
    """Below the hard floor. Not overridable."""


class MemoryNeedsAck(_MemoryVerdict):
    """Below the soft threshold. The caller must confirm."""
```

- [ ] **Step 4: Add the start machinery to `Engine`**

Add `import threading` at the top, `self._lock = threading.Lock()` and `self._start_grace = 3.0` to `__init__`, then these methods:

```python
    def start(self, name: str, acknowledged: bool = False) -> Session:
        try:
            path = discovery.project_path(self.config.root, name)
        except (discovery.InvalidName, discovery.OutsideRoot) as exc:
            raise UnknownProject(name) from exc

        with self._lock:
            current = self.get(name)
            if current.state in (State.RUNNING, State.DETACHED):
                raise AlreadyRunning(name)

            verdict = ram.guard(
                self.available_mb(),
                need_mb=self.config.session_mb,
                hard_mb=self.config.hard_floor_mb,
                soft_mb=self.config.soft_floor_mb,
            )
            if verdict is ram.Verdict.HARD:
                raise MemoryRefused(self.available_mb(), self.config.session_mb)
            if verdict is ram.Verdict.SOFT and not acknowledged:
                raise MemoryNeedsAck(self.available_mb(), self.config.session_mb)

            if current.state is State.STALE:
                self.tmux.kill_session(name)

            self.tmux.new_session(
                name,
                str(path),
                claude_ipc.launch_argv(self.config.claude_binary, name),
            )

            started = self.get(name)
            if started.state is not State.RUNNING:
                raise StartFailed(self.tmux.capture_pane(name, lines=40))
            return started
```

The lock is a plain `threading.Lock`. Starlette runs sync route handlers in a
worker thread, so two taps land on two threads, not two event loop tasks.

- [ ] **Step 5: Run to verify passing**

Run: `uv run pytest tests/test_engine_start.py -v`
Expected: PASS, 10 tests.

- [ ] **Step 6: Gates and commit**

```bash
uv run ruff check && uv run mypy && uv run lint-imports
git add src/hitchrail/engine.py tests/test_engine_start.py
git commit -m "feat(engine): start with a memory guard, a start lock and honest failure"
```

---

### Task 10: The three step stop, and the log tail

**Files:**
- Modify: `src/hitchrail/engine.py`
- Test: `tests/test_engine_stop.py`

**Interfaces:**
- Consumes: everything from Tasks 8 and 9.
- Produces: `Engine.stop(name: str) -> Session` (begins a graceful stop); `Engine.kill(name: str) -> Session`; `Engine.stopping_since(name: str) -> float | None`; `Engine.expire_stops() -> list[str]`; `Engine.logs(name: str, lines: int = 40) -> str`.

- [ ] **Step 1: Write the failing tests**

`tests/test_engine_stop.py`:

```python
from __future__ import annotations

import pytest

from hitchrail.config import Config
from hitchrail.engine import Engine, NotRunning, Protected, State

from .conftest import FakeClock, FakeTmux, procs_from

RUNNING_PS = """\
 500     1   4096   600 tmux new-session -d -s hr-vessel
 501   500 512000   600 claude --dangerously-skip-permissions --remote-control vessel
"""


def build(config: Config, tmux: FakeTmux, ps: str, clock: FakeClock) -> Engine:
    return Engine(
        config=config,
        tmux=tmux,
        procs_fn=procs_from(ps),
        meminfo_fn=lambda: "MemAvailable: 25198592 kB\n",
        clock=clock,
    )


def test_stop_asks_politely_and_kills_nothing(config) -> None:
    tmux = FakeTmux(sessions={"vessel": 500})
    engine = build(config, tmux, RUNNING_PS, FakeClock())
    session = engine.stop("vessel")
    assert tmux.killed == []
    assert tmux.sent  # a request was sent to the pane
    assert session.stopping
    assert session.state is State.RUNNING


def test_stopping_is_visible_in_list_and_get(config) -> None:
    tmux = FakeTmux(sessions={"vessel": 500})
    engine = build(config, tmux, RUNNING_PS, FakeClock())
    engine.stop("vessel")
    assert engine.get("vessel").stopping
    assert next(s for s in engine.list() if s.name == "vessel").stopping


def test_stopping_expires_after_the_timeout(config) -> None:
    clock = FakeClock()
    tmux = FakeTmux(sessions={"vessel": 500})
    engine = build(config, tmux, RUNNING_PS, clock)
    engine.stop("vessel")
    clock.advance(config.stop_timeout + 1)
    assert engine.expire_stops() == ["vessel"]
    assert not engine.get("vessel").stopping
    assert tmux.killed == []  # expiry never escalates on its own


def test_stopping_does_not_expire_early(config) -> None:
    clock = FakeClock()
    engine = build(config, FakeTmux(sessions={"vessel": 500}), RUNNING_PS, clock)
    engine.stop("vessel")
    clock.advance(config.stop_timeout - 1)
    assert engine.expire_stops() == []
    assert engine.get("vessel").stopping


def test_kill_during_the_wait_is_accepted(config) -> None:
    tmux = FakeTmux(sessions={"vessel": 500})
    engine = build(config, tmux, RUNNING_PS, FakeClock())
    engine.stop("vessel")
    engine.kill("vessel")
    assert tmux.killed == ["vessel"]
    assert engine.stopping_since("vessel") is None


def test_kill_without_a_preceding_stop_is_accepted(config) -> None:
    # The try-gently-first rule belongs to the interface, not the engine.
    tmux = FakeTmux(sessions={"vessel": 500})
    engine = build(config, tmux, RUNNING_PS, FakeClock())
    engine.kill("vessel")
    assert tmux.killed == ["vessel"]


def test_stopping_a_stopped_session_is_refused(config) -> None:
    engine = build(config, FakeTmux(), "", FakeClock())
    with pytest.raises(NotRunning):
        engine.stop("network")


def test_the_protected_project_cannot_be_stopped_or_killed(root) -> None:
    cfg = Config(root=root, sessions_dir=root / ".s", self_project="vessel")
    tmux = FakeTmux(sessions={"vessel": 500})
    engine = build(cfg, tmux, RUNNING_PS, FakeClock())
    with pytest.raises(Protected):
        engine.stop("vessel")
    with pytest.raises(Protected):
        engine.kill("vessel")
    assert tmux.killed == []


def test_a_restart_forgets_that_a_stop_was_in_flight(config) -> None:
    # The stopping marker is deliberately not persisted. A marker that
    # outlived the process would be a lie waiting to be told.
    tmux = FakeTmux(sessions={"vessel": 500})
    first = build(config, tmux, RUNNING_PS, FakeClock())
    first.stop("vessel")
    second = build(config, tmux, RUNNING_PS, FakeClock())
    assert not second.get("vessel").stopping


def test_logs_returns_the_pane_tail(config) -> None:
    tmux = FakeTmux(sessions={"vessel": 500})
    tmux.pane_text["vessel"] = "one\ntwo\n"
    engine = build(config, tmux, RUNNING_PS, FakeClock())
    assert engine.logs("vessel") == "one\ntwo\n"


def test_logs_for_an_unknown_project_is_refused(config) -> None:
    engine = build(config, FakeTmux(), "", FakeClock())
    with pytest.raises(NotRunning):
        engine.logs("nope")
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_engine_stop.py -v`
Expected: FAIL, `AttributeError: 'Engine' object has no attribute 'stop'`.

- [ ] **Step 3: Implement in `src/hitchrail/engine.py`**

```python
    # -- stopping ------------------------------------------------------

    def stopping_since(self, name: str) -> float | None:
        return self._stopping.get(name)

    def expire_stops(self) -> list[str]:
        """Drop stop markers older than the timeout.

        Expiry means "we stopped waiting", never "escalate". The session is
        still alive and the decision to kill it belongs to a person.
        """
        now = self._clock()
        expired = [
            name
            for name, began in self._stopping.items()
            if now - began >= self.config.stop_timeout
        ]
        for name in expired:
            self._stopping.pop(name, None)
        return expired

    def stop(self, name: str) -> Session:
        self._require_live(name)
        self._stopping[name] = self._clock()
        # Ask, do not kill. Two interrupts then the exit command is what a
        # person would type.
        self.tmux.send_keys(name, "/exit")
        return self.get(name)

    def kill(self, name: str) -> Session:
        self._require_live(name)
        self._stopping.pop(name, None)
        self.tmux.kill_session(name)
        return self.get(name)

    def logs(self, name: str, lines: int = 40) -> str:
        self._require_live(name)
        return self.tmux.capture_pane(name, lines=lines)

    def _require_live(self, name: str) -> Session:
        session = self.get(name)
        if session.protected:
            raise Protected(name)
        if session.state is State.STOPPED:
            raise NotRunning(name)
        return session
```

- [ ] **Step 4: Run to verify passing**

Run: `uv run pytest tests/test_engine_stop.py -v`
Expected: PASS, 11 tests.

- [ ] **Step 5: Gates and commit**

```bash
uv run ruff check && uv run mypy && uv run lint-imports
git add src/hitchrail/engine.py tests/test_engine_stop.py
git commit -m "feat(engine): three step stop with an in-memory, non-persisted marker"
```

---

### Task 11: The event bus

**Files:**
- Create: `src/hitchrail/events.py`
- Test: `tests/test_events.py`

**Interfaces:**
- Consumes: nothing.
- Produces: class `EventBus(maxsize: int = 32)` with `subscribe() -> AbstractContextManager[asyncio.Queue[dict[str, object]]]`, `publish(event: dict[str, object]) -> None`, property `subscriber_count: int`.

- [ ] **Step 1: Write the failing tests**

`tests/test_events.py`:

```python
from __future__ import annotations

import asyncio

from hitchrail.events import EventBus


async def test_a_subscriber_receives_a_published_event() -> None:
    bus = EventBus()
    with bus.subscribe() as queue:
        bus.publish({"kind": "state", "name": "vessel"})
        assert await asyncio.wait_for(queue.get(), timeout=1) == {
            "kind": "state",
            "name": "vessel",
        }


async def test_every_subscriber_receives_the_same_event() -> None:
    bus = EventBus()
    with bus.subscribe() as a, bus.subscribe() as b:
        bus.publish({"kind": "ping"})
        assert await asyncio.wait_for(a.get(), timeout=1) == {"kind": "ping"}
        assert await asyncio.wait_for(b.get(), timeout=1) == {"kind": "ping"}


async def test_leaving_the_context_unsubscribes() -> None:
    bus = EventBus()
    with bus.subscribe():
        assert bus.subscriber_count == 1
    assert bus.subscriber_count == 0


async def test_publishing_with_no_subscribers_is_harmless() -> None:
    EventBus().publish({"kind": "ping"})


async def test_a_slow_subscriber_is_dropped_not_blocking() -> None:
    bus = EventBus(maxsize=2)
    with bus.subscribe() as queue:
        for i in range(10):
            bus.publish({"n": i})
        assert queue.qsize() == 2
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_events.py -v`
Expected: FAIL, module not found.

- [ ] **Step 3: Implement**

`src/hitchrail/events.py`:

```python
"""A tiny in-process fan out, so the SSE route has something to await.

Deliberately lossy. A browser that cannot keep up gets events dropped rather
than being allowed to apply back pressure to the engine: a stalled tab must
never be able to slow down the machine it is watching.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Iterator

Event = dict[str, object]


class EventBus:
    def __init__(self, maxsize: int = 32) -> None:
        self._maxsize = maxsize
        self._subscribers: set[asyncio.Queue[Event]] = set()

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    @contextlib.contextmanager
    def subscribe(self) -> Iterator[asyncio.Queue[Event]]:
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=self._maxsize)
        self._subscribers.add(queue)
        try:
            yield queue
        finally:
            self._subscribers.discard(queue)

    def publish(self, event: Event) -> None:
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                continue
```

- [ ] **Step 4: Run to verify passing**

Run: `uv run pytest tests/test_events.py -v`
Expected: PASS, 5 tests.

- [ ] **Step 5: Gates and commit**

```bash
uv run ruff check && uv run mypy && uv run lint-imports
git add src/hitchrail/events.py tests/test_events.py
git commit -m "feat(events): lossy in-process fan out for the event stream"
```

---

### Task 12: Security middleware

**Files:**
- Create: `src/hitchrail/security.py`
- Test: `tests/test_security.py`

**Interfaces:**
- Consumes: `Config`.
- Produces: `OriginCheckMiddleware(app, allowed_hosts: tuple[str, ...])`; `TokenMiddleware(app, token: str | None)`; `middleware_stack(config: Config) -> list[Middleware]`; constant `SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})`.

This is the module that answers the CVE precedent in the spec. Every test asserts a refusal.

- [ ] **Step 1: Write the failing tests**

`tests/test_security.py`:

```python
from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from hitchrail.config import Config
from hitchrail.security import middleware_stack


def build(config: Config) -> Starlette:
    async def ok(request):  # type: ignore[no-untyped-def]
        return JSONResponse({"ok": True})

    return Starlette(
        routes=[Route("/x", ok, methods=["GET", "POST"])],
        middleware=middleware_stack(config),
    )


async def call(app: Starlette, method: str = "GET", **kwargs: object) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as c:
        return await c.request(method, "/x", **kwargs)  # type: ignore[arg-type]


async def test_a_known_host_is_served(tmp_path: Path) -> None:
    app = build(Config(root=tmp_path))
    assert (await call(app, headers={"host": "localhost"})).status_code == 200


async def test_an_unknown_host_is_rejected(tmp_path: Path) -> None:
    # DNS rebinding. Without this, any page the user visits in any browser
    # on the network can drive this API from their own browser.
    app = build(Config(root=tmp_path))
    assert (await call(app, headers={"host": "evil.example.com"})).status_code == 400


async def test_a_host_with_a_port_still_matches(tmp_path: Path) -> None:
    app = build(Config(root=tmp_path))
    assert (await call(app, headers={"host": "localhost:8787"})).status_code == 200


async def test_a_get_needs_no_origin(tmp_path: Path) -> None:
    app = build(Config(root=tmp_path))
    assert (await call(app, headers={"host": "localhost"})).status_code == 200


async def test_a_post_without_an_origin_is_rejected(tmp_path: Path) -> None:
    app = build(Config(root=tmp_path))
    r = await call(app, "POST", headers={"host": "localhost"})
    assert r.status_code == 403


async def test_a_post_with_a_foreign_origin_is_rejected(tmp_path: Path) -> None:
    app = build(Config(root=tmp_path))
    r = await call(
        app, "POST", headers={"host": "localhost", "origin": "https://evil.example.com"}
    )
    assert r.status_code == 403


async def test_a_post_with_a_matching_origin_is_served(tmp_path: Path) -> None:
    app = build(Config(root=tmp_path))
    r = await call(
        app, "POST", headers={"host": "localhost", "origin": "http://localhost:8787"}
    )
    assert r.status_code == 200


async def test_no_token_configured_means_no_token_demanded(tmp_path: Path) -> None:
    app = build(Config(root=tmp_path))
    assert (await call(app, headers={"host": "localhost"})).status_code == 200


async def test_a_configured_token_is_demanded(tmp_path: Path) -> None:
    app = build(Config(root=tmp_path, host="0.0.0.0", token="s3cret"))
    assert (await call(app, headers={"host": "localhost"})).status_code == 401


async def test_the_right_token_is_accepted(tmp_path: Path) -> None:
    app = build(Config(root=tmp_path, host="0.0.0.0", token="s3cret"))
    r = await call(
        app, headers={"host": "localhost", "authorization": "Bearer s3cret"}
    )
    assert r.status_code == 200


async def test_a_wrong_token_is_rejected(tmp_path: Path) -> None:
    app = build(Config(root=tmp_path, host="0.0.0.0", token="s3cret"))
    r = await call(app, headers={"host": "localhost", "authorization": "Bearer nope"})
    assert r.status_code == 401


async def test_host_checking_happens_before_token_checking(tmp_path: Path) -> None:
    # A rebound request must not even reach the token comparison.
    app = build(Config(root=tmp_path, host="0.0.0.0", token="s3cret"))
    r = await call(app, headers={"host": "evil.example.com"})
    assert r.status_code == 400
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_security.py -v`
Expected: FAIL, module not found.

- [ ] **Step 3: Implement**

`src/hitchrail/security.py`:

```python
"""The controls that stand between a web page and a shell on this machine.

Hitchrail spawns `claude --dangerously-skip-permissions`. Anyone who can drive
this API can run arbitrary code as the user who started it, so each control
below is a refusal, and each has a test that asserts the refusal.

The host allowlist is not optional. CVE-2026-32632 (GHSA-hhcg-r27j-fhv9) hit
Glances, a localhost and LAN monitoring web UI, for exactly this gap: no host
validation, therefore DNS rebinding, therefore an attacker's page reading the
API through the victim's own browser. Hitchrail has the same shape and a worse
blast radius, because it starts processes rather than reporting on them.
"""

from __future__ import annotations

import secrets
from urllib.parse import urlsplit

from starlette.middleware import Middleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from hitchrail.config import Config

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _deny(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"code": code, "message": message}, status_code=status)


class OriginCheckMiddleware:
    """CSRF control for a same origin JSON API.

    Browsers attach Origin to cross site requests and a rebound attacker
    cannot forge it, so requiring it to name a host we already trust is
    sufficient here and needs no token round trip.
    """

    def __init__(self, app: ASGIApp, allowed_hosts: tuple[str, ...]) -> None:
        self.app = app
        self.allowed = {h.lower().strip("[]") for h in allowed_hosts}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] in SAFE_METHODS:
            await self.app(scope, receive, send)
            return

        headers = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
        origin = headers.get("origin")
        if not origin:
            await _deny(403, "origin_missing", "this request needs an Origin header")(
                scope, receive, send
            )
            return
        host = urlsplit(origin).hostname or ""
        if host.lower().strip("[]") not in self.allowed:
            await _deny(403, "origin_rejected", f"origin not allowed: {origin}")(
                scope, receive, send
            )
            return
        await self.app(scope, receive, send)


class TokenMiddleware:
    def __init__(self, app: ASGIApp, token: str | None) -> None:
        self.app = app
        self.token = token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or self.token is None:
            await self.app(scope, receive, send)
            return

        headers = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
        presented = headers.get("authorization", "").removeprefix("Bearer ").strip()
        if not presented or not secrets.compare_digest(presented, self.token):
            await _deny(401, "unauthorized", "a valid token is required")(
                scope, receive, send
            )
            return
        await self.app(scope, receive, send)


def middleware_stack(config: Config) -> list[Middleware]:
    """Order matters. Host first, so a rebound request never reaches anything
    that could leak whether a token is even correct."""
    return [
        Middleware(TrustedHostMiddleware, allowed_hosts=list(config.allowed_hosts)),
        Middleware(TokenMiddleware, token=config.token),
        Middleware(OriginCheckMiddleware, allowed_hosts=config.allowed_hosts),
    ]
```

- [ ] **Step 4: Run to verify passing**

Run: `uv run pytest tests/test_security.py -v`
Expected: PASS, 12 tests.

- [ ] **Step 5: Gates and commit**

```bash
uv run ruff check && uv run mypy && uv run lint-imports
git add src/hitchrail/security.py tests/test_security.py
git commit -m "feat(security): host allowlist, origin check and constant time token"
```

---

### Task 13: The REST API

**Files:**
- Create: `src/hitchrail/server.py`
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: `Engine`, `EventBus`, `Config`, `middleware_stack`.
- Produces: `create_app(engine: Engine, config: Config, bus: EventBus | None = None) -> Starlette`; `session_json(session: Session) -> dict[str, object]`.

Error bodies are `{"code": ..., "message": ...}` with the codes the interface branches on: `ram_soft`, `ram_hard`, `self_protected`, `start_died`, `unknown_project`, `already_running`, `not_running`, `invalid_name`, `already_exists`.

- [ ] **Step 1: Write the failing tests**

`tests/test_api.py`:

```python
from __future__ import annotations

import httpx
import pytest

from hitchrail.engine import Engine
from hitchrail.server import create_app

from .conftest import FakeClock, FakeTmux, procs_from

RUNNING_PS = """\
 500     1   4096   600 tmux new-session -d -s hr-vessel
 501   500 512000   600 claude --dangerously-skip-permissions --remote-control vessel
"""

HEADERS = {"host": "localhost", "origin": "http://localhost:8787"}


@pytest.fixture
def engine(config):
    return Engine(
        config=config,
        tmux=FakeTmux(sessions={"vessel": 500}),
        procs_fn=procs_from(RUNNING_PS),
        meminfo_fn=lambda: "MemAvailable: 25198592 kB\n",
        clock=FakeClock(),
    )


@pytest.fixture
def client(engine, config):
    app = create_app(engine=engine, config=config)
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://localhost")


async def test_projects_lists_every_folder_with_its_state(client) -> None:
    async with client as c:
        body = (await c.get("/api/projects", headers=HEADERS)).json()
    names = [p["name"] for p in body["projects"]]
    assert names == ["vessel", "vessel-social", "network", "dotted.site"]
    assert body["projects"][0]["state"] == "running"
    assert body["projects"][2]["state"] == "stopped"


async def test_projects_reports_available_memory(client) -> None:
    async with client as c:
        body = (await c.get("/api/projects", headers=HEADERS)).json()
    assert body["memory"]["available_mb"] == 24608


async def test_start_returns_the_new_session(config) -> None:
    # FakeTmux.new_session hands out pid 1001, so the process table has to
    # describe that pid for the started session to read back as running.
    started_ps = """\
 1001     1   4096    5 tmux new-session -d -s hr-network
 1002  1001 300000    5 claude --dangerously-skip-permissions --remote-control network
"""
    engine = Engine(
        config=config,
        tmux=FakeTmux(),
        procs_fn=procs_from(started_ps),
        meminfo_fn=lambda: "MemAvailable: 25198592 kB\n",
        clock=FakeClock(),
    )
    transport = httpx.ASGITransport(app=create_app(engine=engine, config=config))
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as c:
        r = await c.post("/api/sessions/network", headers=HEADERS)
    assert r.status_code == 201
    assert r.json()["state"] == "running"


async def test_starting_a_running_session_is_a_conflict(client) -> None:
    async with client as c:
        r = await c.post("/api/sessions/vessel", headers=HEADERS)
    assert r.status_code == 409
    assert r.json()["code"] == "already_running"


async def test_unknown_project_is_a_404_with_a_code(client) -> None:
    async with client as c:
        r = await c.post("/api/sessions/nope", headers=HEADERS)
    assert r.status_code == 404
    assert r.json()["code"] == "unknown_project"


async def test_hard_memory_refusal_is_507_with_the_numbers(config) -> None:
    engine = Engine(
        config=config,
        tmux=FakeTmux(),
        procs_fn=procs_from(""),
        meminfo_fn=lambda: "MemAvailable: 1048576 kB\n",
        clock=FakeClock(),
    )
    transport = httpx.ASGITransport(app=create_app(engine=engine, config=config))
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as c:
        r = await c.post("/api/sessions/network", headers=HEADERS)
    assert r.status_code == 507
    assert r.json()["code"] == "ram_hard"
    assert r.json()["available_mb"] == 1024


async def test_soft_memory_needs_an_acknowledgement(config) -> None:
    engine = Engine(
        config=config,
        tmux=FakeTmux(),
        procs_fn=procs_from(""),
        meminfo_fn=lambda: "MemAvailable: 4194304 kB\n",
        clock=FakeClock(),
    )
    transport = httpx.ASGITransport(app=create_app(engine=engine, config=config))
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as c:
        first = await c.post("/api/sessions/network", headers=HEADERS)
        assert first.status_code == 409
        assert first.json()["code"] == "ram_soft"
        second = await c.post("/api/sessions/network?acknowledged=1", headers=HEADERS)
    assert second.status_code != 409


async def test_delete_begins_a_graceful_stop_and_kills_nothing(client, engine) -> None:
    async with client as c:
        r = await c.delete("/api/sessions/vessel", headers=HEADERS)
    assert r.status_code == 202
    assert r.json()["stopping"] is True
    assert engine.tmux.killed == []


async def test_delete_with_kill_kills(client, engine) -> None:
    async with client as c:
        r = await c.delete("/api/sessions/vessel?kill=1", headers=HEADERS)
    assert r.status_code == 200
    assert engine.tmux.killed == ["vessel"]


async def test_kill_without_a_preceding_stop_is_accepted_by_the_api(client, engine) -> None:
    async with client as c:
        await c.delete("/api/sessions/vessel?kill=1", headers=HEADERS)
    assert engine.tmux.killed == ["vessel"]


async def test_logs_returns_the_pane_tail(client, engine) -> None:
    engine.tmux.pane_text["vessel"] = "one\ntwo\n"
    async with client as c:
        r = await c.get("/api/sessions/vessel/logs", headers=HEADERS)
    assert r.json()["text"] == "one\ntwo\n"


async def test_creating_a_folder_makes_it_appear(client, config) -> None:
    async with client as c:
        r = await c.post("/api/projects", json={"name": "brand-new"}, headers=HEADERS)
        assert r.status_code == 201
        body = (await c.get("/api/projects", headers=HEADERS)).json()
    assert "brand-new" in [p["name"] for p in body["projects"]]
    assert (config.root / "brand-new").is_dir()


async def test_creating_a_traversing_folder_is_refused(client, config) -> None:
    async with client as c:
        r = await c.post("/api/projects", json={"name": "../evil"}, headers=HEADERS)
    assert r.status_code == 400
    assert r.json()["code"] == "invalid_name"
    assert not (config.root.parent / "evil").exists()


async def test_creating_an_existing_folder_is_a_conflict(client) -> None:
    async with client as c:
        r = await c.post("/api/projects", json={"name": "network"}, headers=HEADERS)
    assert r.status_code == 409
    assert r.json()["code"] == "already_exists"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_api.py -v`
Expected: FAIL, module not found.

- [ ] **Step 3: Implement**

`src/hitchrail/server.py`:

```python
"""The HTTP layer. Routing and translation only; the logic lives in the engine.

Starlette 1.x: lifespan context manager and an explicit routes list. The
on_startup, on_shutdown, add_event_handler and @app.route decorators were all
removed at 1.0, so any example using them predates this API.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from hitchrail import discovery, engine as eng
from hitchrail.config import Config
from hitchrail.events import EventBus
from hitchrail.security import middleware_stack


def session_json(session: eng.Session) -> dict[str, object]:
    return {
        "name": session.name,
        "state": str(session.state),
        "pid": session.pid,
        "ram_mb": session.ram_mb,
        "uptime_s": session.uptime_s,
        "url": session.url,
        "stopping": session.stopping,
        "protected": session.protected,
    }


def _error(status: int, code: str, message: str, **extra: object) -> JSONResponse:
    return JSONResponse({"code": code, "message": message, **extra}, status_code=status)


def create_app(engine: eng.Engine, config: Config, bus: EventBus | None = None) -> Starlette:
    events = bus or EventBus()

    def announce(session: eng.Session) -> None:
        events.publish({"kind": "session", "session": session_json(session)})

    async def list_projects(request: Request) -> Response:
        engine.expire_stops()
        return JSONResponse(
            {
                "projects": [session_json(s) for s in engine.list()],
                "memory": {"available_mb": engine.available_mb()},
            }
        )

    async def create_project(request: Request) -> Response:
        payload = await request.json()
        name = str(payload.get("name", ""))
        try:
            discovery.create_project(config.root, name)
        except discovery.InvalidName as exc:
            return _error(400, "invalid_name", str(exc))
        except discovery.AlreadyExists as exc:
            return _error(409, "already_exists", str(exc))
        session = engine.get(name)
        announce(session)
        return JSONResponse(session_json(session), status_code=201)

    async def start(request: Request) -> Response:
        name = request.path_params["name"]
        acknowledged = request.query_params.get("acknowledged") in {"1", "true"}
        try:
            session = engine.start(name, acknowledged=acknowledged)
        except eng.UnknownProject as exc:
            return _error(404, "unknown_project", str(exc))
        except eng.AlreadyRunning as exc:
            return _error(409, "already_running", str(exc))
        except eng.MemoryNeedsAck as exc:
            return _error(
                409,
                "ram_soft",
                "starting would leave the machine short on memory",
                available_mb=exc.available_mb,
                needed_mb=exc.needed_mb,
            )
        except eng.MemoryRefused as exc:
            return _error(
                507,
                "ram_hard",
                "not enough memory to start a session",
                available_mb=exc.available_mb,
                needed_mb=exc.needed_mb,
            )
        except eng.StartFailed as exc:
            return _error(502, "start_died", str(exc), output=exc.output)
        announce(session)
        return JSONResponse(session_json(session), status_code=201)

    async def stop(request: Request) -> Response:
        name = request.path_params["name"]
        kill = request.query_params.get("kill") in {"1", "true"}
        try:
            session = engine.kill(name) if kill else engine.stop(name)
        except eng.Protected as exc:
            return _error(423, "self_protected", str(exc))
        except eng.NotRunning as exc:
            return _error(409, "not_running", str(exc))
        announce(session)
        return JSONResponse(session_json(session), status_code=200 if kill else 202)

    async def logs(request: Request) -> Response:
        name = request.path_params["name"]
        try:
            text = engine.logs(name, lines=int(request.query_params.get("lines", 40)))
        except eng.NotRunning as exc:
            return _error(409, "not_running", str(exc))
        return JSONResponse({"name": name, "text": text})

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        app.state.events = events
        app.state.engine = engine
        yield

    return Starlette(
        routes=[
            Route("/api/projects", list_projects, methods=["GET"]),
            Route("/api/projects", create_project, methods=["POST"]),
            Route("/api/sessions/{name}", start, methods=["POST"]),
            Route("/api/sessions/{name}", stop, methods=["DELETE"]),
            Route("/api/sessions/{name}/logs", logs, methods=["GET"]),
        ],
        middleware=middleware_stack(config),
        lifespan=lifespan,
    )
```

- [ ] **Step 4: Run to verify passing**

Run: `uv run pytest tests/test_api.py -v`
Expected: PASS, 14 tests.

- [ ] **Step 5: Gates and commit**

```bash
uv run ruff check && uv run mypy && uv run lint-imports
git add src/hitchrail/server.py tests/test_api.py
git commit -m "feat(api): REST surface with a stable error code envelope"
```

---

### Task 14: The event stream

**Files:**
- Modify: `src/hitchrail/server.py`
- Test: `tests/test_sse.py`

**Interfaces:**
- Consumes: `EventBus`, `create_app`.
- Produces: a `GET /api/events` route returning `EventSourceResponse`.

- [ ] **Step 1: Write the failing tests**

`tests/test_sse.py`:

```python
from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from hitchrail.engine import Engine
from hitchrail.events import EventBus
from hitchrail.server import create_app

from .conftest import FakeClock, FakeTmux, procs_from

HEADERS = {"host": "localhost", "accept": "text/event-stream"}


@pytest.fixture
def parts(config):
    bus = EventBus()
    engine = Engine(
        config=config,
        tmux=FakeTmux(sessions={"vessel": 500}),
        procs_fn=procs_from(""),
        meminfo_fn=lambda: "MemAvailable: 25198592 kB\n",
        clock=FakeClock(),
    )
    return bus, create_app(engine=engine, config=config, bus=bus)


async def test_the_stream_announces_itself_as_event_stream(parts) -> None:
    _bus, app = parts
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as c:
        async with c.stream("GET", "/api/events", headers=HEADERS) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")


async def test_a_published_event_reaches_the_stream(parts) -> None:
    bus, app = parts
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as c:
        async with c.stream("GET", "/api/events", headers=HEADERS) as response:
            async def publish_soon() -> None:
                await asyncio.sleep(0.05)
                bus.publish({"kind": "session", "session": {"name": "vessel"}})

            task = asyncio.create_task(publish_soon())
            payload = None
            async for line in response.aiter_lines():
                if line.startswith("data:"):
                    payload = json.loads(line.removeprefix("data:").strip())
                    break
            await task
    assert payload == {"kind": "session", "session": {"name": "vessel"}}


async def test_the_stream_is_reachable_without_an_origin_header(parts) -> None:
    # EventSource cannot set headers, and GET is a safe method, so the
    # origin check must not apply to it.
    _bus, app = parts
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as c:
        async with c.stream("GET", "/api/events", headers=HEADERS) as response:
            assert response.status_code == 200


async def test_a_forged_host_cannot_open_the_stream(parts) -> None:
    _bus, app = parts
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as c:
        r = await c.get("/api/events", headers={"host": "evil.example.com"})
    assert r.status_code == 400
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_sse.py -v`
Expected: FAIL with 404 on `/api/events`.

- [ ] **Step 3: Implement**

Add to the imports in `src/hitchrail/server.py`:

```python
import json

from sse_starlette.sse import EventSourceResponse
```

Add the route handler inside `create_app`, before the `return Starlette(...)`:

```python
    async def event_stream(request: Request) -> Response:
        async def publisher() -> AsyncIterator[dict[str, str]]:
            with events.subscribe() as queue:
                while True:
                    if await request.is_disconnected():
                        return
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=1.0)
                    except TimeoutError:
                        continue
                    yield {"event": "message", "data": json.dumps(event)}

        # sse-starlette handles ping keepalive, disconnect detection and
        # generator shutdown. Note its documented caveat: SSE and
        # GZipMiddleware do not mix, so gzip is never applied here.
        return EventSourceResponse(publisher())
```

Add `import asyncio` at the top, and add the route to the list:

```python
            Route("/api/events", event_stream, methods=["GET"]),
```

- [ ] **Step 4: Run to verify passing**

Run: `uv run pytest tests/test_sse.py -v`
Expected: PASS, 4 tests.

- [ ] **Step 5: Gates and commit**

```bash
uv run ruff check && uv run mypy && uv run lint-imports
git add src/hitchrail/server.py tests/test_sse.py
git commit -m "feat(sse): event stream over sse-starlette"
```

---

### Task 15: The command line entry point

**Files:**
- Create: `src/hitchrail/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `Config`, `Engine`, `create_app`.
- Produces: `parse_args(argv: list[str]) -> argparse.Namespace`; `build_config(args) -> Config`; `main(argv: list[str] | None = None) -> int`.

- [ ] **Step 1: Write the failing tests**

`tests/test_cli.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from hitchrail.cli import build_config, main, parse_args


def test_root_defaults_to_the_current_directory(tmp_path: Path) -> None:
    args = parse_args(["--root", str(tmp_path)])
    assert build_config(args).root == tmp_path


def test_loopback_is_the_default_bind(tmp_path: Path) -> None:
    cfg = build_config(parse_args(["--root", str(tmp_path)]))
    assert cfg.host == "127.0.0.1"
    assert cfg.is_loopback
    assert cfg.token is None


def test_a_network_bind_generates_a_token_when_none_is_given(tmp_path: Path) -> None:
    cfg = build_config(parse_args(["--root", str(tmp_path), "--host", "0.0.0.0"]))
    assert cfg.token
    assert len(cfg.token) >= 24


def test_an_explicit_token_is_used_verbatim(tmp_path: Path) -> None:
    cfg = build_config(
        parse_args(["--root", str(tmp_path), "--host", "0.0.0.0", "--token", "mine"])
    )
    assert cfg.token == "mine"


def test_a_missing_root_exits_with_a_message(tmp_path: Path, capsys) -> None:
    code = main(["--root", str(tmp_path / "nope")])
    assert code == 2
    assert "root is not a directory" in capsys.readouterr().err


def test_the_token_is_printed_once_on_a_network_bind(tmp_path: Path, capsys, monkeypatch) -> None:
    monkeypatch.setattr("hitchrail.cli._serve", lambda app, cfg: 0)
    main(["--root", str(tmp_path), "--host", "0.0.0.0"])
    out = capsys.readouterr().out
    assert "token" in out.lower()
    assert "anyone with this" in out.lower()


def test_no_token_banner_on_loopback(tmp_path: Path, capsys, monkeypatch) -> None:
    monkeypatch.setattr("hitchrail.cli._serve", lambda app, cfg: 0)
    main(["--root", str(tmp_path)])
    assert "token" not in capsys.readouterr().out.lower()


def test_extra_allowed_hosts_reach_the_config(tmp_path: Path) -> None:
    cfg = build_config(
        parse_args(
            ["--root", str(tmp_path), "--host", "0.0.0.0", "--token", "t",
             "--allow-host", "box.lan"]
        )
    )
    assert "box.lan" in cfg.allowed_hosts
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_cli.py -v`
Expected: FAIL, module not found.

- [ ] **Step 3: Implement**

`src/hitchrail/cli.py`:

```python
"""Command line entry point."""

from __future__ import annotations

import argparse
import secrets
import sys
from pathlib import Path

import uvicorn

from hitchrail.config import Config, ConfigError
from hitchrail.engine import Engine
from hitchrail.server import create_app


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="hitchrail",
        description="Start and stop headless Claude Code sessions across a folder of projects.",
    )
    parser.add_argument("--root", default=".", type=Path, help="folder holding the projects")
    parser.add_argument("--host", default="127.0.0.1", help="address to bind")
    parser.add_argument("--port", default=8787, type=int)
    parser.add_argument("--token", default=None, help="required off loopback; generated if omitted")
    parser.add_argument(
        "--allow-host",
        dest="allow_hosts",
        action="append",
        default=[],
        help="an extra hostname this server will answer to; repeatable",
    )
    parser.add_argument("--self-project", default=None, help="a project that must never be stopped")
    return parser.parse_args(argv)


def build_config(args: argparse.Namespace) -> Config:
    token = args.token
    if not is_loopback_host(args.host) and not token:
        token = secrets.token_urlsafe(24)
    return Config(
        root=args.root,
        host=args.host,
        port=args.port,
        token=token,
        extra_hosts=tuple(args.allow_hosts),
        self_project=args.self_project,
    )


def _serve(app: Starlette, config: Config) -> int:
    uvicorn.run(app, host=config.host, port=config.port, log_level="info")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        config = build_config(args)
    except ConfigError as exc:
        print(f"hitchrail: {exc}", file=sys.stderr)
        return 2

    if config.token:
        print(f"\n  token: {config.token}")
        print("  Anyone with this token can run code on this machine as you.\n")

    engine = Engine(config=config)
    return _serve(create_app(engine=engine, config=config), config)
```

`build_config` reuses `is_loopback_host` from Task 2 rather than carrying a
second list of loopback spellings. Two copies of that rule would drift, and the
one that drifts is the one that decides whether a token is demanded.

- [ ] **Step 4: Run to verify passing**

Run: `uv run pytest tests/test_cli.py -v`
Expected: PASS, 8 tests.

- [ ] **Step 5: Prove it against a real machine**

This is the step that makes Phase 1 done. Tests passing is not this step.

```bash
mkdir -p /tmp/hitchrail-demo/demo-project
uv run hitchrail --root /tmp/hitchrail-demo &
curl -s -H 'Host: localhost' localhost:8787/api/projects | python3 -m json.tool
curl -s -X POST -H 'Host: localhost' -H 'Origin: http://localhost:8787' \
  localhost:8787/api/sessions/demo-project | python3 -m json.tool
# confirm a real tmux session exists and Claude is in it
tmux list-sessions | grep hr-
curl -s -X DELETE -H 'Host: localhost' -H 'Origin: http://localhost:8787' \
  'localhost:8787/api/sessions/demo-project?kill=1'
# and confirm the rebinding refusal on a live socket
curl -s -o /dev/null -w '%{http_code}\n' -H 'Host: evil.example.com' localhost:8787/api/projects
```

Expected: the list shows `demo-project`, starting it produces a real tmux
session and a `claude.ai/code` URL, killing it removes the session, and the
forged Host returns 400.

- [ ] **Step 6: Gates and commit**

```bash
uv run ruff check && uv run ruff format --check && uv run mypy && uv run lint-imports && uv run pytest
git add src/hitchrail/cli.py tests/test_cli.py
git commit -m "feat(cli): serve command with a generated token off loopback"
```

---

## Phase 1 exit criteria

- [ ] All five gates green on 3.11, 3.12 and 3.13.
- [ ] `uvx hitchrail --root ~/dev` serves an API a person can drive with `curl`.
- [ ] A real session has been started, observed, gracefully stopped and killed by hand.
- [ ] A forged `Host` header has been refused on a live socket, not only in a test.
- [ ] Every state in the design's section 4.1, including `detached`, has a passing test.
- [ ] Every tmux footgun in the design's section 4.2 has a named regression test.

When these hold, write the Phase 2 plan from `docs/roadmap.md`.
