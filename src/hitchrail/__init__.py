"""Start and stop headless Claude Code sessions across a folder of projects."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("hitchrail")
except PackageNotFoundError:  # pragma: no cover - only when run from a bare checkout
    # Read rather than written out a second time. pyproject.toml is the single
    # canonical version source, so there is no mirror here that can drift.
    __version__ = "0.0.0+unknown"
