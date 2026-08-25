"""Listing and creating project folders, and the path safety around both."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# The filesystem's own limit on most Linux filesystems. The pattern is ASCII
# only, so a character is a byte and this is the real ceiling rather than an
# invented one. It was 64, which was arbitrary and hid perfectly ordinary
# folders for no security reason: length carries no argument here, unlike the
# alphabet and the first character, which both do.
MAX_NAME_LENGTH = 255

# Allowlist, not a denylist. A name that matches this cannot traverse, because
# it cannot contain a separator; cannot hide, because it cannot begin with a
# dot; and cannot become a flag in an argv slot, because it cannot begin with a
# hyphen. Everything outside the pattern is refused without being enumerated,
# which is what makes it robust against encodings nobody thought to list.
#
# \Z, not $. `$` matches before a trailing newline, so `evil\n` satisfied this
# pattern and became a real directory, and a name at the cap plus a newline
# walked straight past the cap the pattern is written to impose. \Z anchors at
# the actual end of the string. This is the whole allowlist failing open over
# one character, so it gets a named regression test.
NAME_PATTERN = re.compile(rf"\A[A-Za-z0-9][A-Za-z0-9._-]{{0,{MAX_NAME_LENGTH - 1}}}\Z")

_ALLOWED_CHARS = re.compile(r"[A-Za-z0-9._-]")


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


@dataclass(frozen=True)
class Unsupported:
    """A folder that exists but cannot be a project, and why.

    The reason is written for the person looking at their own folder, not for a
    log. They know the folder is there; what they need is which rule it broke.
    """

    name: str
    reason: str


@dataclass(frozen=True)
class Listing:
    """One pass over the root, keeping both halves of the answer.

    Two separate functions would mean two `iterdir()` calls that can disagree
    with each other about a directory somebody is editing.
    """

    projects: tuple[str, ...]
    unsupported: tuple[Unsupported, ...]


def _describe_offenders(offenders: list[str]) -> str:
    """Group by kind rather than listing each character.

    Naming every distinct character produced "a non ASCII character ('P'), a
    non ASCII character ('e') and 3 more" for a Cyrillic folder name, which
    tells the reader nothing they could not see and buries the one useful
    word in it.
    """
    spaces = [c for c in offenders if c.isspace()]
    non_ascii = [c for c in offenders if not c.isascii()]
    other = [c for c in offenders if c.isascii() and not c.isspace()]

    parts: list[str] = []
    if spaces:
        parts.append("a space" if spaces == [" "] else "whitespace")
    if non_ascii:
        shown = ", ".join(repr(c) for c in non_ascii[:3])
        parts.append(f"non ASCII characters ({shown}{', ...' if len(non_ascii) > 3 else ''})")
    if other:
        shown = ", ".join(repr(c) for c in other[:4])
        parts.append(f"{shown}{', ...' if len(other) > 4 else ''}")
    return " and ".join(parts)


def explain_name(name: str) -> str | None:
    """Why this name cannot be a project, or None if it can.

    Separate from `validate_name` because refusing and explaining are different
    jobs: the guard needs to be fast and total, the explanation needs to be
    read by a person who is wondering where their folder went.
    """
    if NAME_PATTERN.match(name):
        return None
    if not name:
        return "the name is empty"
    if name.startswith("."):
        return "begins with a dot, so it is a hidden directory rather than a project"
    if name.startswith("-"):
        return "begins with a hyphen, which an argv slot reads as a flag"
    if len(name) > MAX_NAME_LENGTH:
        return f"{len(name)} characters, over the {MAX_NAME_LENGTH} limit"
    offenders = sorted({c for c in name if not _ALLOWED_CHARS.match(c)})
    if offenders:
        return (
            f"contains {_describe_offenders(offenders)}; names may use letters, "
            "digits, dot, underscore and hyphen"
        )
    if not name[0].isalnum():
        # `_leading` reaches here: every character is in the allowed set, but
        # the first one is not a letter or a digit. Without this it fell
        # through to a message that named no rule at all.
        return f"begins with {name[0]!r}; a name must start with a letter or a digit"
    # Unreachable: a name whose characters are all allowed, whose first is
    # alphanumeric, and whose length is within the cap matches NAME_PATTERN by
    # construction, so it returned None at the top. Kept so the function is
    # total, because a silent None here would read as "this name is fine".
    return "not an acceptable project name"  # pragma: no cover


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


def scan(root: Path) -> Listing:
    """One pass over the root, keeping the folders that cannot be projects.

    No git filter and no badge: whether a folder is a repository has nothing to
    do with whether it is a project, which is what the design means by "a
    folder is a project".

    It does separate out what `project_path` would refuse. Listing `.git` and a
    symlink pointing out of the root as projects, then refusing both the moment
    somebody taps them, is an interface offering actions that cannot work.

    But dropping them silently is its own bug, and it was one. A folder called
    `my app` simply vanished, and the honest reading from the phone was that
    Hitchrail could not see it. So the ones that cannot be projects are
    returned alongside the ones that can, with the rule each of them broke.
    This is the same move the design already makes for `detached` sessions:
    surface the awkward state with an explanation rather than hide it or guess.

    `.git` and other dot directories are still excluded, and deliberately not
    reported as unsupported either. They are not folders somebody was trying to
    use as a project, so listing them as rejected would be noise.
    """
    projects: list[str] = []
    unsupported: list[Unsupported] = []
    try:
        entries = sorted(root.iterdir(), key=lambda p: p.name)
    except OSError as exc:
        raise RootUnavailable(f"cannot read the root {root}: {exc}") from exc

    for entry in entries:
        try:
            if not entry.is_dir():
                continue
        except OSError as exc:
            raise RootUnavailable(f"cannot read {entry} under {root}: {exc}") from exc

        name = entry.name
        reason = explain_name(name)
        if reason is None:
            try:
                resolve_child(root, name)
            except OutsideRoot:
                unsupported.append(
                    Unsupported(name, "points outside the root, so it is not safe to open")
                )
                continue
            # No `except InvalidName` here: explain_name returns None exactly
            # when NAME_PATTERN matches, which is exactly when validate_name
            # passes, so resolve_child cannot raise it on this path. A branch
            # no test can reach is dead code, not defence.
            except OSError as exc:
                raise RootUnavailable(f"cannot resolve {name!r} under {root}: {exc}") from exc
            projects.append(name)
        elif not name.startswith("."):
            # A dot directory is not a project somebody was trying to make.
            # Reporting `.git` as rejected would be noise, not information.
            unsupported.append(Unsupported(name, reason))

    return Listing(
        projects=tuple(sorted(projects, key=str.lower)),
        unsupported=tuple(sorted(unsupported, key=lambda u: u.name.lower())),
    )


def list_projects(root: Path) -> list[str]:
    """Every direct subfolder that is actually startable.

    Kept as the plain answer for callers that only act on projects, which is
    the engine. Anything rendering a list to a person should use `scan`, so the
    folders it is not showing can be accounted for.
    """
    return list(scan(root).projects)


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
