"""Listing and creating project folders, and the path safety around both."""

from __future__ import annotations

import re
from pathlib import Path

# Allowlist, not a denylist. A name that matches this cannot traverse, because
# it cannot contain a separator; cannot hide, because it cannot begin with a
# dot; and cannot become a flag in an argv slot, because it cannot begin with a
# hyphen. Everything outside the pattern is refused without being enumerated,
# which is what makes it robust against encodings nobody thought to list.
NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class InvalidName(ValueError):
    """The name is not one we are willing to turn into a path."""


class OutsideRoot(ValueError):
    """The name resolves to somewhere that is not inside the root."""


class AlreadyExists(ValueError):
    """A folder of that name is already there."""


def list_projects(root: Path) -> list[str]:
    """Every direct subfolder. No git filter, no badge: a folder is a project."""
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
    and lookup cannot end up with different guards. An earlier draft had
    create_project validate and then mkdir while project_path resolved, and two
    ways into the same filesystem with different guards is how the weaker one
    gets found.

    The parent is compared for equality rather than by prefix: a prefix check
    would accept `/root-evil` for a root of `/root`.
    """
    validate_name(name)
    real_root = root.resolve()
    real = (root / name).resolve()
    if real.parent != real_root:
        raise OutsideRoot(f"{name!r} resolves outside {real_root}")
    return real


def project_path(root: Path, name: str) -> Path:
    resolved = resolve_child(root, name)
    if not resolved.is_dir():
        raise InvalidName(f"no such project: {name!r}")
    return resolved


def create_project(root: Path, name: str) -> Path:
    resolved = resolve_child(root, name)
    # Both sides, because Path.exists() follows symlinks: a dangling link
    # inside the root reports False on the resolved path while very much
    # occupying the name, and mkdir would then raise FileExistsError rather
    # than one of our refusals.
    if resolved.exists() or (root / name).is_symlink() or (root / name).exists():
        raise AlreadyExists(f"already there: {name!r}")
    resolved.mkdir()
    return resolved
