"""The two claims the skeleton has to make before anything else is worth writing."""

from __future__ import annotations

import importlib

import hitchrail

# Every module named in the import-linter contract in pyproject.toml. Keeping
# the list here rather than parsing the contract is deliberate: a test that
# derives its expectation from the thing under test cannot fail.
CONTRACT_MODULES = (
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
)


def test_package_exposes_a_version() -> None:
    """Proves the distribution is installed, not that the working tree is importable.

    A src/ layout is worthless if tests can pass by importing the source
    directory, so this asserts the metadata fallback did NOT fire.
    """
    assert hitchrail.__version__
    assert hitchrail.__version__ != "0.0.0+unknown"


def test_every_module_named_in_the_import_contract_exists() -> None:
    """The contract cannot be enforced against modules that do not exist yet.

    This is why the skeleton creates every module as a stub. If a later
    refactor removes one, lint-imports fails with a configuration error rather
    than a boundary violation, which reads as tooling breakage instead of what
    it is. This test names the real cause first.
    """
    for name in CONTRACT_MODULES:
        assert importlib.import_module(f"hitchrail.{name}") is not None
