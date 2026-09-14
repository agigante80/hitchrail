"""Start and stop headless Claude Code sessions across a folder of projects."""

from importlib.metadata import PackageNotFoundError, version


def installed_version() -> str | None:
    """The version the installed distribution carries, or `None` from a bare
    checkout with no install. Read rather than written out a second time:
    `pyproject.toml` is the single canonical version source, so there is no
    mirror here that can drift. `None` is the honest answer for the page
    (#147), where a guessed number is worse than none; the CLI below prints a
    placeholder because `--version` has to print something."""
    try:
        return version("hitchrail")
    except PackageNotFoundError:  # pragma: no cover - only when run from a bare checkout
        return None


__version__ = installed_version() or "0.0.0+unknown"
