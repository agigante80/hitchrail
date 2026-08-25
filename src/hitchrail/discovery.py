"""Listing and creating project folders, and the path safety around both."""

from __future__ import annotations

import re
from pathlib import Path

# Allowlist, not a denylist. A name that matches this cannot traverse, because
# it cannot contain a separator; cannot hide, because it cannot begin with a
# dot; and cannot become a flag in an argv slot, because it cannot begin with a
# hyphen. Everything outside the pattern is refused without being enumerated,
# which is what makes it robust against encodings nobody thought to list.
#
# \Z, not $. `$` matches before a trailing newline, so `evil\n` satisfied this
# pattern and became a real directory, and `("x" * 64) + "\n"` walked straight
# past the 64 character cap the pattern is written to impose. \Z anchors at the
# actual end of the string. This is the whole allowlist failing open over one
# character, so it gets a named regression test.
NAME_PATTERN = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")


class InvalidName(ValueError):
    """The name is not one we are willing to turn into a path."""


class NoSuchProject(InvalidName):
    """The name is fine, but there is no folder of that name.

    A subclass so that `except InvalidName` still catches it and the declared
    interface for later phases does not change. It exists because the HTTP
    layer has to answer 400 for a malformed name and 404 for a missing one,
    and one exception type cannot carry both. A project deleted from under a
    stale phone tab is not a client sending a bad request.
    """


class RootUnavailable(ValueError):
    """The root itself could not be read.

    Config checks the root is a directory once, at construction. A USB drive,
    an autofs mount or a sync client can take it away afterwards, and
    FileNotFoundError is not a ValueError, so it escaped every caller's refusal
    handling as a 500. Reporting honestly that the root cannot be read is the
    behaviour control 7 asks for; guessing that there are no projects would say
    every session is stopped.
    """


class OutsideRoot(ValueError):
    """The name does not resolve to a direct child of the root."""


class AlreadyExists(ValueError):
    """A folder of that name is already there."""


def validate_name(name: str) -> None:
    if not NAME_PATTERN.match(name):
        raise InvalidName(f"not an acceptable project name: {name!r}")


def resolve_child(root: Path, name: str) -> Path:
    """Validate the name, then prove the result is a direct child of the root.

    Two independent checks, deliberately. The pattern makes traversal
    impossible via the name itself; the resolution check catches a symlink
    inside the root that points somewhere else. Either alone would be enough
    for the cases we can think of, which is exactly why there are two.

    Every path in this module goes through here, so listing, lookup and
    creation cannot end up with different guards. An earlier draft had
    create_project validate and then mkdir while project_path resolved, and two
    ways into the same filesystem with different guards is how the weaker one
    gets found.

    The parent is compared for equality rather than by prefix: a prefix check
    would accept `/root-evil` for a root of `/root`. That also means a symlink
    to a NESTED directory inside the root is refused, which is deliberate and
    matches the design's "a direct child of the configured root".
    """
    validate_name(name)
    real_root = root.resolve()
    real = (root / name).resolve()
    if real.parent != real_root:
        raise OutsideRoot(
            f"{name!r} resolves to {real}, which is not a direct child of {real_root}"
        )
    return real


def list_projects(root: Path) -> list[str]:
    """Every direct subfolder that is actually startable.

    No git filter and no badge: whether a folder is a repository has nothing to
    do with whether it is a project, which is what the design means by "a
    folder is a project".

    It does exclude what `project_path` would refuse. Listing `.git` and a
    symlink pointing out of the root, and then refusing both the moment
    somebody taps them, is not "no distinction", it is an interface offering
    actions that cannot work. One guard decides membership, and it is the same
    guard that decides everything else here.

    KNOWN GAP, and it is a real one: that guard also hides ordinary folders
    whose names fall outside NAME_PATTERN, such as `my app`, `cafe` with an
    accent, or anything over 64 characters. They vanish from the listing with
    no signal. Fixing it means either widening a security control's alphabet or
    adding a way to report hidden folders, and which of those is acceptable is
    a product decision rather than a code one. See
    https://github.com/agigante80/hitchrail/issues/7.
    """
    names: list[str] = []
    try:
        entries = sorted(root.iterdir(), key=lambda p: p.name)
    except OSError as exc:
        raise RootUnavailable(f"cannot read the root {root}: {exc}") from exc
    for entry in entries:
        if not entry.is_dir():
            continue
        try:
            resolve_child(root, entry.name)
        except (InvalidName, OutsideRoot):
            continue
        names.append(entry.name)
    return sorted(names, key=str.lower)


def project_path(root: Path, name: str) -> Path:
    resolved = resolve_child(root, name)
    if not resolved.is_dir():
        raise NoSuchProject(f"no such project: {name!r}")
    return resolved


def create_project(root: Path, name: str) -> Path:
    """Create a folder, or refuse. Never creates through a symlink.

    mkdir on `root / name` rather than on the resolved path, and no existence
    check before it. Both matter:

    - Checking and then creating is a race. A concurrent create, which a web
      interface makes easy, produced a FileExistsError that is not a
      ValueError, so every caller's refusal handling missed it and the API
      would have answered 500 instead of a refusal.
    - mkdir refuses when the final component exists at all, symlinks included,
      so a dangling link occupying the name cannot be followed. Creating at the
      RESOLVED path would have created the link's target instead, which is a
      different directory than the one that was asked for.
    """
    resolve_child(root, name)
    target = root / name
    try:
        target.mkdir()
    except FileExistsError as exc:
        raise AlreadyExists(f"already there: {name!r}") from exc
    except OSError as exc:
        # The root went away between construction and now, or it is not
        # writable. Either way this is not a bad request, and letting an
        # OSError past here reopens the door the AlreadyExists mapping closed.
        raise RootUnavailable(f"cannot create in the root {root}: {exc}") from exc
    return target.resolve()
