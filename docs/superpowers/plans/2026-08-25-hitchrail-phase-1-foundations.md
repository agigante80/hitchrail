# Hitchrail Phase 1: Foundations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the package, the five blocking gates, the configuration that refuses an unsafe bind, and the name allowlist that makes path traversal impossible.

**Architecture:** A `src/` layout package whose every module exists as a stub from the first commit, so the import boundary contract is enforceable before there is anything to enforce it on. Configuration is a frozen dataclass that validates in `__post_init__`, so an unsafe configuration cannot be constructed at all rather than being checked later by whoever remembers to.

**Tech Stack:** Python 3.11+, uv, uv_build, pytest, ruff, mypy, import-linter.

**Spec:** `docs/superpowers/specs/2026-08-25-hitchrail-design.md`

**Roadmap:** `docs/roadmap.md` (this plan is Phase 1 of 7)

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
- **No em dashes or en dashes** anywhere, including commit messages. A hook enforces it.
- Defaults: session prefix `hr-`, stop timeout 30 seconds, hard memory floor 1536 MB, soft floor 3072 MB, per session estimate 1536 MB, port 8787.
- Tests are hermetic. No test touches a real tmux server, a real Claude process, the network, or the filesystem outside a temporary root.

## Phase 1 file structure

| File | Responsibility |
|---|---|
| `pyproject.toml` | package metadata and every tool's configuration |
| `.python-version` | the development interpreter |
| `src/hitchrail/__init__.py` | the package, and `__version__` read from installed metadata |
| `src/hitchrail/config.py` | runtime configuration and the refusals that depend on it |
| `src/hitchrail/discovery.py` | listing and creating project folders, and the path boundary |
| `src/hitchrail/{tmux,procs,claude_ipc,ram,events,engine,security,server,cli}.py` | docstring-only stubs, filled in by later phases |
| `.github/workflows/ci.yml` | the five gates on three interpreters |

The stubs matter. import-linter fails when a contract names a module that does not exist, so a contract written against modules that arrive over fifteen tasks cannot pass on task one. The first draft of this plan handled that by telling the engineer to strip the contract and add each module back later, and then never mentioned it again in any subsequent task. Creating every module as a one line docstring on the first commit costs nine lines and makes the contract true from the beginning.

---

### Task 1: Skeleton, module stubs, tooling and gates

**Files:**
- Create: `pyproject.toml`
- Create: `.python-version`
- Create: `src/hitchrail/__init__.py`
- Create: `src/hitchrail/py.typed`
- Create: `src/hitchrail/config.py`, `discovery.py`, `tmux.py`, `procs.py`, `claude_ipc.py`, `ram.py`, `events.py`, `engine.py`, `security.py`, `server.py`, `cli.py` (stubs)
- Create: `tests/test_smoke.py`
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: nothing.
- Produces: `hitchrail.__version__: str`. A working `uv run` environment. Five gates every later task must keep green: `uv run ruff check`, `uv run ruff format --check`, `uv run mypy`, `uv run lint-imports`, `uv run pytest`.

- [x] **Step 1: Write `pyproject.toml`**

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
# ruff 0.16 formats Python code fences inside Markdown, which reaches the plan
# documents and the adapted skills under .claude/. Those hold deliberately
# partial snippets ("add this to __init__"), so formatting them is not a
# no-op, and it would let a documentation edit fail a code formatting gate.
# The gate is for the project's Python; prose is reviewed by people.
extend-exclude = ["docs", ".claude"]

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
markers = [
  "live: binds a real loopback socket on an ephemeral port",
]

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
  "hitchrail.events",
  "hitchrail.engine",
]
forbidden_modules = [
  "hitchrail.server",
  "hitchrail.cli",
  "starlette",
  "uvicorn",
  "sse_starlette",
]
```

`S603` is ruff's warning about subprocess calls. It is silenced only in the two modules that legitimately run subprocesses, so the exception is visible rather than global. `hitchrail.security` is deliberately **not** in `source_modules`: it is part of the web layer and imports Starlette on purpose.

- [x] **Step 2: Create the package files and every module stub**

`.python-version`:

```
3.12
```

`src/hitchrail/py.typed` is an empty file.

`src/hitchrail/__init__.py`:

```python
"""Start and stop headless Claude Code sessions across a folder of projects."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("hitchrail")
except PackageNotFoundError:  # pragma: no cover - only when running from a bare checkout
    __version__ = "0.0.0+unknown"
```

The version is read from installed metadata rather than written out a second
time. `pyproject.toml` is the single canonical source, so there is no mirror to
keep equal and the release gate has nothing to cross check. See
`docs/versioning.md`.

Create each of these as a docstring-only module. They exist so the import
contract in Step 1 is valid from the first commit; each later phase fills one
in.

`src/hitchrail/config.py`:

```python
"""Runtime configuration, and the refusals that depend on it."""
```

`src/hitchrail/discovery.py`:

```python
"""Listing and creating project folders, and the path safety around both."""
```

`src/hitchrail/tmux.py`:

```python
"""A thin tmux adapter, carrying the target addressing footguns."""
```

`src/hitchrail/procs.py`:

```python
"""One snapshot of the process table, and the queries the engine asks of it."""
```

`src/hitchrail/claude_ipc.py`:

```python
"""Everything that knows about Claude Code's internals. UNSTABLE by design."""
```

`src/hitchrail/ram.py`:

```python
"""Memory readings, and the decision about whether starting is wise."""
```

`src/hitchrail/events.py`:

```python
"""A tiny in-process fan out, so the SSE route has something to await."""
```

`src/hitchrail/engine.py`:

```python
"""State derivation and session lifecycle. No database, nothing to drift."""
```

`src/hitchrail/security.py`:

```python
"""The controls that stand between a web page and a shell on this machine."""
```

`src/hitchrail/server.py`:

```python
"""The HTTP layer. Routing and translation only; the logic lives in the engine."""
```

`src/hitchrail/cli.py`:

```python
"""Command line entry point."""
```

- [x] **Step 3: Write the failing smoke test**

`tests/test_smoke.py`:

```python
import hitchrail


def test_package_exposes_a_version() -> None:
    assert hitchrail.__version__
    assert hitchrail.__version__ != "0.0.0+unknown"


def test_every_module_named_in_the_import_contract_exists() -> None:
    """The contract cannot be enforced against modules that do not exist yet.

    This is why Task 1 creates every module as a stub. If a later refactor
    removes one, lint-imports fails with a config error rather than a boundary
    violation, which reads as tooling breakage instead of what it is.
    """
    import importlib

    for name in (
        "config",
        "discovery",
        "tmux",
        "procs",
        "claude_ipc",
        "ram",
        "events",
        "engine",
        "security",
        "server",
        "cli",
    ):
        assert importlib.import_module(f"hitchrail.{name}") is not None
```

- [x] **Step 4: Run to verify failure**

Run: `uv sync && uv run pytest tests/test_smoke.py -v`
Expected: FAIL. Before `uv sync` installs the package, `__version__` is `"0.0.0+unknown"` and the first test fails. Once synced it passes, which is the point of the assertion: it proves the distribution is installed rather than the working tree being on `sys.path`.

- [x] **Step 5: Run every gate**

```bash
uv sync
uv run pytest -v
uv run ruff check
uv run ruff format --check
uv run mypy
uv run lint-imports
```

Expected: pytest passes with 2 tests. All five gates pass, `lint-imports` included, because every module in the contract exists.

- [x] **Step 6: Write the CI workflow**

`.github/workflows/ci.yml`:

```yaml
name: ci

on:
  push:
    branches: [main]
  pull_request:

permissions:
  contents: read

jobs:
  check:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        python: ["3.11", "3.12", "3.13"]
    steps:
      - uses: actions/checkout@v7
      # setup-uv stopped publishing moving major tags after v7, so this is
      # pinned exactly rather than to a major that would never move again.
      - uses: astral-sh/setup-uv@v10.0.1
        with:
          enable-cache: true
      # --locked asserts uv.lock is current rather than quietly updating it,
      # so a forgotten lock change fails here instead of drifting.
      - run: uv sync --locked --python ${{ matrix.python }}
      - run: uv run ruff check
      - run: uv run ruff format --check
      - run: uv run mypy
      - run: uv run lint-imports
      - run: uv run coverage run -m pytest
      - run: uv run coverage report
```

`permissions: contents: read` is least privilege: this workflow only reads the
repository. A workflow with a write token on a package people install with
`uvx` is supply chain surface.

**Action versions are verified, not recalled.** At implementation time
`actions/checkout` was at v7 (the first draft of this plan said v5, two majors
stale) and `astral-sh/setup-uv` was at v10.0.1 with no moving major tag past
v7, which is why one is pinned to a major and the other to an exact version.
Check both again rather than trusting these numbers.

- [x] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock .python-version src tests .github
git commit -m "build: project skeleton, module stubs, tooling and CI gates"
```

---

### Task 2: Configuration and its refusals

**Files:**
- Modify: `src/hitchrail/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `is_loopback_host(host: str) -> bool`; `is_wildcard_host(host: str) -> bool`; `local_addresses() -> tuple[str, ...]`; constant `HOST_PATTERN: re.Pattern[str]`; type alias `Resolver = Callable[[], tuple[str, ...]]`; frozen dataclass `Config` with fields `root: Path`, `host: str`, `port: int`, `token: str | None`, `extra_hosts: tuple[str, ...]`, `session_prefix: str`, `stop_timeout: float`, `hard_floor_mb: int`, `soft_floor_mb: int`, `session_mb: int`, `agent_binary: str`, `sessions_dir: Path`, `tmux_socket: str | None`, `self_project: str | None`, `resolver: Resolver | None`; properties `Config.is_loopback -> bool`, `Config.allowed_hosts -> tuple[str, ...]`, `Config.allowed_origins -> frozenset[str]`; exception `ConfigError`.

`__post_init__` validates more than the plan's first draft listed, because a
class whose docstring says an unsafe configuration cannot exist has to mean it.
An empty `session_prefix` makes "never kill a session without the configured
prefix" vacuous, since every name satisfies `startswith("")`, and that guard is
what stands between a stop and the developer's own tmux sessions. A
`agent_binary` beginning with a hyphen becomes a flag in an argv slot. A
`soft_floor_mb` below `hard_floor_mb` makes the confirmation gate unreachable.
An `extra_hosts` entry carrying a port is accepted by every naive check and
then never matches, because the Host header is compared with the port stripped.

`allowed_hosts` is resolved **once**, in `__post_init__`, not on every read. As
a plain property it ran `gethostname`, `getaddrinfo` and a UDP connect per
access, and the middleware reads it once per request on the event loop.

The one thing this task exists to get right, beyond the token refusal, is the
wildcard bind. Binding to `0.0.0.0` is the normal case for a phone first tool,
and an allowlist built from the literal bind string contains only loopback
names. The phone then sends `Host: 192.168.1.10` and gets a 400 with no
explanation. That is a working security control breaking the headline use case,
which is how security controls get removed.

Adding the machine's own addresses to the allowlist is safe against the threat
the allowlist defends. DNS rebinding works through an attacker controlled
**name**; a browser only sends `Host: 192.168.1.10` when a person typed that
address.

- [x] **Step 1: Write the failing tests**

`tests/test_config.py`:

```python
from pathlib import Path

import pytest

from hitchrail.config import (
    Config,
    ConfigError,
    is_loopback_host,
    is_wildcard_host,
)


def fixed_resolver(*addresses: str):
    """A stand in for asking the operating system what this machine is called."""
    return lambda: tuple(addresses)


def test_loopback_bind_needs_no_token(tmp_path: Path) -> None:
    cfg = Config(root=tmp_path)
    assert cfg.is_loopback
    assert cfg.token is None


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1", "127.0.0.5"])
def test_loopback_forms_are_recognised(tmp_path: Path, host: str) -> None:
    assert Config(root=tmp_path, host=host).is_loopback


@pytest.mark.parametrize("host", ["0.0.0.0", "::"])
def test_wildcard_forms_are_recognised(host: str) -> None:
    assert is_wildcard_host(host)
    assert not is_loopback_host(host)


def test_network_bind_without_a_token_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="token"):
        Config(root=tmp_path, host="0.0.0.0", token=None)


def test_network_bind_with_a_token_is_allowed(tmp_path: Path) -> None:
    cfg = Config(root=tmp_path, host="0.0.0.0", token="s3cret")
    assert not cfg.is_loopback


def test_missing_root_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="root"):
        Config(root=tmp_path / "nope")


def test_allowed_hosts_covers_loopback_and_a_concrete_bind(tmp_path: Path) -> None:
    cfg = Config(root=tmp_path, host="192.168.1.10", token="t")
    assert "192.168.1.10" in cfg.allowed_hosts
    assert "localhost" in cfg.allowed_hosts


def test_a_wildcard_bind_allows_the_machines_own_address(tmp_path: Path) -> None:
    # The regression this task exists for. Without it the phone that the whole
    # design is aimed at gets a 400 from its own machine.
    cfg = Config(
        root=tmp_path,
        host="0.0.0.0",
        token="t",
        resolver=fixed_resolver("192.168.1.10", "box.lan"),
    )
    assert "192.168.1.10" in cfg.allowed_hosts
    assert "box.lan" in cfg.allowed_hosts


def test_a_wildcard_bind_never_allows_the_wildcard_itself(tmp_path: Path) -> None:
    cfg = Config(
        root=tmp_path, host="0.0.0.0", token="t", resolver=fixed_resolver("10.0.0.2")
    )
    assert "0.0.0.0" not in cfg.allowed_hosts  # noqa: S104
    assert "::" not in cfg.allowed_hosts


def test_a_concrete_bind_does_not_ask_the_resolver(tmp_path: Path) -> None:
    calls = []

    def counting_resolver() -> tuple[str, ...]:
        calls.append(1)
        return ("10.0.0.2",)

    Config(root=tmp_path, host="127.0.0.1", resolver=counting_resolver).allowed_hosts
    assert calls == []


def test_a_resolver_that_fails_does_not_break_the_config(tmp_path: Path) -> None:
    def broken_resolver() -> tuple[str, ...]:
        raise OSError("no network")

    cfg = Config(root=tmp_path, host="0.0.0.0", token="t", resolver=broken_resolver)
    assert "localhost" in cfg.allowed_hosts  # degraded, not crashed


def test_extra_allowed_hosts_are_included(tmp_path: Path) -> None:
    cfg = Config(root=tmp_path, host="0.0.0.0", token="t", extra_hosts=("box.lan",))
    assert "box.lan" in cfg.allowed_hosts


def test_wildcard_allowed_host_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="wildcard"):
        Config(root=tmp_path, host="0.0.0.0", token="t", extra_hosts=("*",))


def test_allowed_origins_pin_the_port(tmp_path: Path) -> None:
    # Hostname alone is not enough: another app on localhost:3000 would
    # otherwise be same origin against an API equivalent to a shell.
    cfg = Config(root=tmp_path, port=8787)
    assert "http://localhost:8787" in cfg.allowed_origins
    assert "http://localhost:3000" not in cfg.allowed_origins


def test_allowed_origins_include_the_default_port_forms(tmp_path: Path) -> None:
    # Behind a TLS terminating proxy the browser sends https://name with no
    # port. Refusing that would make the documented deployment impossible.
    cfg = Config(root=tmp_path, host="192.168.1.10", token="t", port=8787)
    assert "https://192.168.1.10" in cfg.allowed_origins
    assert "http://192.168.1.10" in cfg.allowed_origins
```

- [x] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL with `ImportError: cannot import name 'Config' from 'hitchrail.config'` (the stub has no names in it yet).

- [x] **Step 3: Implement**

`src/hitchrail/config.py`:

```python
"""Runtime configuration, and the refusals that depend on it."""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

LOOPBACK_NAMES = frozenset({"localhost", "localhost.localdomain"})
WILDCARD_HOSTS = frozenset({"0.0.0.0", "::", "*"})  # noqa: S104
DEFAULT_PORTS = {"http": 80, "https": 443}

Resolver = Callable[[], tuple[str, ...]]


class ConfigError(ValueError):
    """The configuration is not one Hitchrail is willing to run with."""


def is_loopback_host(host: str) -> bool:
    """Module level so the CLI can ask the same question without a second copy."""
    if host in LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def is_wildcard_host(host: str) -> bool:
    return host in WILDCARD_HOSTS


def local_addresses() -> tuple[str, ...]:
    """Names and addresses this machine answers to, for a wildcard bind.

    Adding these to the host allowlist is safe against the threat the allowlist
    defends. DNS rebinding turns an attacker controlled NAME into our address;
    a browser only sends `Host: 192.168.1.10` because a person typed it.

    Best effort by design. A machine with no network, or one where the hostname
    does not resolve, degrades to loopback only rather than raising.
    """
    found: list[str] = []

    hostname = socket.gethostname()
    if hostname:
        found.append(hostname)
        try:
            for info in socket.getaddrinfo(hostname, None):
                address = info[4][0]
                if isinstance(address, str):
                    found.append(address)
        except OSError:
            pass

    # The primary outbound address, which is usually the one a phone will use.
    # Connecting a UDP socket sends no packet; it only asks the routing table.
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 1))  # TEST-NET-1, guaranteed unrouted
        found.append(probe.getsockname()[0])
    except OSError:
        pass
    finally:
        probe.close()

    return tuple(dict.fromkeys(h for h in found if h and not is_wildcard_host(h)))


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
    agent_binary: str = "claude"
    sessions_dir: Path = field(default_factory=lambda: Path.home() / ".claude" / "sessions")
    tmux_socket: str | None = None
    self_project: str | None = None
    resolver: Resolver | None = None

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

        if is_wildcard_host(self.host):
            # We are listening on every interface, so we cannot know from the
            # bind string what the phone will type. Ask the machine.
            resolve = self.resolver or local_addresses
            try:
                hosts.extend(resolve())
            except OSError:
                pass  # degraded to loopback, which is still a working allowlist
        else:
            hosts.append(self.host)

        hosts.extend(self.extra_hosts)
        return tuple(dict.fromkeys(h for h in hosts if h and not is_wildcard_host(h)))

    @property
    def allowed_origins(self) -> frozenset[str]:
        """Exact origins the browser may claim on a mutating request.

        Hostname alone is not enough. Another application on `localhost:3000`
        would otherwise be same origin against an API equivalent to a shell.
        The default port forms are included because behind a TLS terminating
        reverse proxy the browser sends `https://name` with no port at all,
        and that deployment is documented in the README.
        """
        origins: set[str] = set()
        for host in self.allowed_hosts:
            bracketed = f"[{host}]" if ":" in host and not host.startswith("[") else host
            origins.add(f"http://{bracketed}:{self.port}")
            origins.add(f"http://{bracketed}")
            origins.add(f"https://{bracketed}")
        return frozenset(origins)
```

- [x] **Step 4: Run to verify passing**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS, 19 tests (four functions are parametrised: 4 loopback forms, 2 wildcard forms, and 13 plain functions).

- [x] **Step 5: Gates and commit**

```bash
uv run ruff check && uv run ruff format --check && uv run mypy && uv run lint-imports
git add src/hitchrail/config.py tests/test_config.py
git commit -m "feat(config): mandatory token off loopback, and an allowlist a phone can reach"
```

---

### Task 3: Folder discovery and path safety

**Files:**
- Modify: `src/hitchrail/discovery.py`
- Test: `tests/test_discovery.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `scan(root: Path) -> Listing`; `list_projects(root: Path) -> list[str]`; `explain_name(name: str) -> str | None`; `validate_name(name: str) -> None`; `resolve_child(root: Path, name: str) -> Path`; `project_path(root: Path, name: str) -> Path`; `create_project(root: Path, name: str) -> Path`; `display_name(name: str) -> str`; frozen dataclasses `Unsupported(name, reason)` and `Listing(projects, unsupported, unsupported_total)`; constant `MAX_REPORTED_UNSUPPORTED: int`; exceptions `InvalidName`, `NoSuchProject(InvalidName)`, `OutsideRoot`, `AlreadyExists`, `RootUnavailable`; constants `NAME_PATTERN: re.Pattern[str]`, `MAX_NAME_LENGTH: int`.

**`scan` returns both halves of the answer**, the folders that can be projects and the ones that cannot with the rule each broke. An earlier version filtered the unsupported ones out silently, so a folder called `my app` simply vanished and the honest reading from a phone was that Hitchrail could not see it. `list_projects` remains for the engine, which only acts on projects; anything rendering a list to a person uses `scan`. The reasoning and the options considered are in issue #7.

**`Unsupported.name` is a display name, not the raw filesystem name.** Reporting rejected folders opens an outbound path for exactly the strings the allowlist exists to keep out: a folder called `report\x1b[2J` clears the terminal of anything printing the listing, and a name that is not valid UTF-8 arrives surrogate escaped and cannot be serialised to JSON at all. `display_name` escapes both. Nothing reported here is a valid project name, so escaping loses nothing.

**`MAX_NAME_LENGTH` is 255**, the filesystem's own limit, not the 64 an earlier draft invented. Length carries no security argument here, unlike the alphabet and the first character, and the low cap hid ordinary folders for nothing.

**`NoSuchProject` subclasses `InvalidName`** so that `except InvalidName` still catches it, while the HTTP layer can tell 400 from 404. A project deleted from under a stale phone tab is not a client sending a bad request. **`RootUnavailable`** covers the root disappearing after `Config` validated it, a USB drive or an autofs mount: `FileNotFoundError` is not a `ValueError`, so unmapped it escapes every caller's refusal handling as a 500, and guessing "no projects" would report every session as stopped.

`resolve_child` is factored out so that creation and lookup share one boundary
check. In the first draft `create_project` validated the name and then called
`mkdir` without resolving, while `project_path` resolved. Two paths into the
same filesystem with different guards is how the weaker one gets found.

- [x] **Step 1: Write the failing tests**

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
    [
        "..",
        ".",
        "../etc",
        "a/b",
        "a\\b",
        "",
        ".hidden",
        "-lead",
        "--dangerously-skip-permissions",
        "x" * 65,
        "a b",
        "a\x00b",
        "a‮b",
    ],
)
def test_traversal_and_junk_names_are_refused(tmp_path: Path, name: str) -> None:
    with pytest.raises(InvalidName):
        project_path(tmp_path, name)


def test_a_leading_hyphen_is_refused_because_argv_reads_it_as_a_flag(
    tmp_path: Path,
) -> None:
    # Argument injection. There is no shell anywhere in this project, and a
    # name beginning with '-' still becomes a flag once it reaches an argv slot.
    with pytest.raises(InvalidName):
        project_path(tmp_path, "-rf")


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


def test_creating_over_a_symlink_out_of_the_root_is_refused(tmp_path: Path) -> None:
    # create_project and project_path must share one boundary check. If only
    # lookup resolves, creation is the weaker of the two paths.
    outside = tmp_path.parent / "outside_create"
    outside.mkdir(exist_ok=True)
    root = tmp_path / "root"
    root.mkdir()
    (root / "escape").symlink_to(outside, target_is_directory=True)
    with pytest.raises((AlreadyExists, OutsideRoot)):
        create_project(root, "escape")


def test_a_refused_creation_leaves_nothing_behind(tmp_path: Path) -> None:
    with pytest.raises(InvalidName):
        create_project(tmp_path, "../evil")
    assert list(tmp_path.iterdir()) == []
    assert not (tmp_path.parent / "evil").exists()
```

- [x] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_discovery.py -v`
Expected: FAIL with `ImportError: cannot import name 'AlreadyExists' from 'hitchrail.discovery'`.

- [x] **Step 3: Implement**

`src/hitchrail/discovery.py`:

```python
"""Listing and creating project folders, and the path safety around both."""

from __future__ import annotations

import re
from pathlib import Path

# Allowlist, not a denylist. A name that matches this cannot traverse, because
# it cannot contain a separator; cannot hide, because it cannot begin with a
# dot; and cannot become a flag in an argv slot, because it cannot begin with
# a hyphen. Everything outside the pattern is refused without being enumerated.
NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class InvalidName(ValueError):
    """The name is not one we are willing to turn into a path."""


class OutsideRoot(ValueError):
    """The name resolves to somewhere that is not inside the root."""


class AlreadyExists(ValueError):
    """A folder of that name is already there."""


def list_projects(root: Path) -> list[str]:
    return sorted((p.name for p in root.iterdir() if p.is_dir()), key=str.lower)


def validate_name(name: str) -> None:
    if not NAME_PATTERN.match(name):
        raise InvalidName(f"not an acceptable project name: {name!r}")


def resolve_child(root: Path, name: str) -> Path:
    """Validate the name, then prove the result is a direct child of the root.

    Two independent checks, deliberately. The pattern makes traversal
    impossible via the name itself; the resolution check catches a symlink
    inside the root that points somewhere else. Either alone would be enough
    for the cases we can think of, which is exactly why there are two.

    Every filesystem operation in this module goes through here, so creation
    and lookup cannot end up with different guards.
    """
    validate_name(name)
    candidate = root / name
    real_root = root.resolve()
    # strict=False so a name that does not exist yet still gets a boundary
    # check. create_project needs that; project_path checks existence itself.
    real = candidate.resolve()
    if real.parent != real_root:
        raise OutsideRoot(f"{name!r} resolves outside {real_root}")
    return real


def project_path(root: Path, name: str) -> Path:
    resolved = resolve_child(root, name)
    if not resolved.is_dir():
        raise InvalidName(f"no such project: {name!r}")
    return resolved


def create_project(root: Path, name: str) -> Path:
    target = resolve_child(root, name)
    if (root / name).exists() or target.exists():
        raise AlreadyExists(f"already there: {name!r}")
    target.mkdir()
    return target
```

`(root / name).exists()` is checked alongside `target.exists()` because
`Path.exists()` follows symlinks: a dangling symlink inside the root reports
`False` on the resolved path while very much occupying the name.

- [x] **Step 4: Run to verify passing**

Run: `uv run pytest tests/test_discovery.py -v`
Expected: PASS, 22 tests (10 plain functions plus one parametrised case with 13 values, minus the two that share the parametrised body: 9 plain + 13 parametrised).

Count them from the output rather than trusting this line. If the number
disagrees, a test was dropped in transcription, which is worth finding now.

- [x] **Step 5: Gates and commit**

```bash
uv run ruff check && uv run ruff format --check && uv run mypy && uv run lint-imports
git add src/hitchrail/discovery.py tests/test_discovery.py
git commit -m "feat(discovery): list and create folders behind one shared boundary check"
```

---


## How these tasks were executed

The steps above are ticked from the outcome rather than from a stopwatch. The
phase ran through the ticket workflow rather than strictly top to bottom, so
the commits do not map one to one onto the numbered steps. What was verified
before ticking is that every deliverable each task names exists, is imported by
the code that uses it, and has tests that fail when it is removed: the five
gates, the CI workflow, the configuration and its refusals, and the discovery
layer with its path safety.

## Phase 1 exit criteria

**Met. Verified against the running code on 2026-08-25 at `2c9be3b`**, by executing
each criterion rather than by reading the tests that cover it.

- [x] All five gates green on 3.11, 3.12 and 3.13, `lint-imports` included and passing without the contract having been edited after Task 1.
      *CI green on `2c9be3b` across all three legs. `git log 0b59370..HEAD -- pyproject.toml`
      shows no commit touching `[tool.importlinter]`, so the contract written in Task 1 is
      the contract still being enforced.*
- [x] `Config(root=..., host="0.0.0.0", token="t")` produces an `allowed_hosts` containing this machine's own LAN address.
      *Real resolver, no injection: `('17-R4', '127.0.1.1', '192.168.33.11')`. See the
      caveat below, which is about other spellings of the same intent.*
- [x] `Config(root=..., host="0.0.0.0")` with no token raises `ConfigError`.
- [x] `allowed_origins` rejects `http://localhost:3000` while accepting `http://localhost:8787`.
- [x] Every name in the refusal parameter list raises `InvalidName`, and a symlink out of the root raises `OutsideRoot` on both lookup and creation.
      *14 payloads, none accepted by `project_path` or by `create_project`. The symlink
      case refuses on both paths, which it did not in the first draft.*
- [x] A refused creation leaves nothing on disk.
      *Asserted as a side effect check, not only as an exception: the root is still empty
      and no sibling was created outside it.*

### One criterion passes its letter and not all of its intent

Criterion 2 names `0.0.0.0`, and that works. What it is *for* is "a wildcard bind
reaches the phone", and that has an IPv6 shaped hole:

- `::0` and `0:0:0:0:0:0:0:0` are not recognised as wildcards, so the resolver is
  never consulted and the allowlist gets the literal bind string back instead of an
  address. A first check of this read the result as "non empty, therefore a LAN
  address", which flattered it; `['::0']` is the wildcard echoed back.
- `getaddrinfo` returns IPv6 addresses in bare form, and a browser sends
  `Host: [2001:db8::5]`. The bare form is what lands in `allowed_hosts`, so the two
  never match.

Both are issue #8, milestoned Phase 2, which is where they start to matter: Task 4
is the first code to consume `allowed_hosts`, and until then the gap is theoretical.
Phase 1's contract is the six criteria above, and they hold.

### What this phase cost, and what it taught

Three tickets, 134 tests, 99% branch coverage across `config.py` and `discovery.py`.
Four rounds of code review found 23 confirmed defects, 14 of which were fixed inside
the batch and 9 of which became #8, #9 and #10 when the review loop hit its bad fix
injection trip wire.

The one worth remembering: `NAME_PATTERN` was anchored with `$`, which matches before
a trailing newline, so `evil\n` became a real directory and a name at the cap plus a
newline walked past the cap. **Every hand written payload in the ticket's own test
list passed that pattern.** Guards here want fuzzing or property tests, not only
enumeration.

When these hold, start Phase 2 from `docs/roadmap.md`.
