"""The root as a hard boundary: what it contains, and what may be opened.

The vocabulary these checks are built from lives in `projectnames.py`, split
out at #33. This module owns the filesystem: scanning, resolving, creating.
That one owns what a valid name IS.
"""

from __future__ import annotations

import errno
from dataclasses import dataclass
from pathlib import Path

from hitchrail.projectnames import (
    MAX_NAME_LENGTH,
    NAME_PATTERN,
    InvalidName,
    display_name,
    explain_name,
    validate_name,
)
from hitchrail.roots import Root, RootError, qualify, split_identifier

__all__ = [
    "MAX_NAME_LENGTH",
    "MAX_REPORTED_UNSUPPORTED",
    "NAME_PATTERN",
    "AlreadyExists",
    "InvalidName",
    "Listing",
    "NoSuchProject",
    "OutsideRoot",
    "RootUnavailable",
    "Unsupported",
    "create_project",
    "display_name",
    "explain_name",
    "list_projects",
    "project_path",
    "resolve_child",
    "scan",
    "validate_name",
]

MAX_REPORTED_UNSUPPORTED = 50


# Characters that are dangerous to hand to whatever renders the listing, as
# opposed to merely invalid in a name. Written as escapes rather than literals
# on purpose: several of these are invisible or reorder their neighbours, so a
# literal here would be unreadable in the source and could reorder this very
# comment.
#
#   \x00-\x1f, \x7f-\x9f  C0 and C1 controls, and DEL. A folder named
#                         report\x1b[2J clears the terminal of anything
#                         printing the listing.
#   \u200b-\u200f         zero width space through the LTR and RTL marks
#   \u2028-\u202e         line and paragraph separators, bidi embedding and
#                         override. The override displays proj<RLO>gnp.exe as
#                         projexe.gnp, even through textContent.
#   \u2066-\u2069         bidi isolates, the same trick with newer codepoints


class NoSuchProject(InvalidName):
    """The name is fine, but there is no folder of that name.

    A subclass so that `except InvalidName` still catches it and the declared
    interface for later phases does not change. It exists because the HTTP
    layer has to answer 400 for a malformed name and 404 for a missing one,
    and one exception type cannot carry both. A project deleted from under a
    stale phone tab is not a client sending a bad request.
    """


class RootUnavailable(Exception):
    """The root itself could not be read.

    Config checks the root is a directory once, at construction. A USB drive,
    an autofs mount or a sync client can take it away afterwards, and
    FileNotFoundError is not a ValueError, so it escaped every caller's refusal
    handling as a 500. Reporting honestly that the root cannot be read is the
    behaviour control 7 asks for; guessing that there are no projects would say
    every session is stopped.

    NOT a ValueError, deliberately, and this is the whole point of the class.
    `InvalidName`, `NoSuchProject`, `OutsideRoot` and `AlreadyExists` are all
    things the CALLER did wrong, and a handler written as
    `except ValueError -> 400` is correct for every one of them. This is not:
    an unplugged drive is not a bad request, and answering 400 would tell the
    caller to fix something they did not break. It was a ValueError in its
    first version, which put it in the bucket the exception was created to
    escape from.
    """


class OutsideRoot(ValueError):
    """The name does not resolve to a direct child of the root."""


class AlreadyExists(ValueError):
    """A folder of that name is already there."""


@dataclass(frozen=True)
class Unsupported:
    """A folder that exists but cannot be a project, and why.

    `name` is a DISPLAY name, escaped by `display_name`, not the raw filesystem
    name. That distinction is the whole safety of this type. Reporting rejected
    folders opens an outbound path for exactly the strings the allowlist exists
    to keep out: a folder called `report\\x1b[2J` clears the terminal of
    anything printing the listing, and a bidi override reorders what a reader
    sees even through `textContent`. Nothing here is a valid project name, so
    nothing is lost by escaping it, and there is no need to pass the raw bytes
    on: no caller can open these anyway.

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

    `unsupported` is capped at `MAX_REPORTED_UNSUPPORTED`; `unsupported_total`
    is the true count. A root that shares a tree with a Downloads folder can
    hold thousands of odd names, and serialising all of them to a phone to say
    "these are not projects" is worse than saying how many there were. Showing
    a capped list with an honest total is the point: this whole type exists
    because dropping things silently was the bug.
    """

    projects: tuple[str, ...]
    unsupported: tuple[Unsupported, ...]
    unsupported_total: int = 0


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


def _broken_link_reason(entry: Path) -> str:
    """Why a symlink is not a directory, for the person looking at their folder.

    `is_dir()` answers False for a dangling link, a loop and a link to a file
    alike, and those want different explanations. `stat()` follows the link and
    raises with an errno that tells them apart.

    The target is text from OUTSIDE the root, so it is attacker influenceable
    on a shared machine and goes through `display_name` like every other
    reported name. A target called `report\x1b[2J` would otherwise clear the
    terminal of anything printing the listing, which is the exact hazard
    `display_name` was written for, arriving through a different door.
    """
    try:
        entry.stat()
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            return "is a symlink loop, so it has no target to open"
        try:
            target = str(entry.readlink())
        except OSError:
            return "is a symlink whose target cannot be read"
        return f"points at a target that does not exist: {display_name(target)}"
    return "is a symlink to something that is not a directory"


def _dedup_order(entry: Path) -> tuple[int, str]:
    """Real directories before symlinks, then by name.

    `scan` keeps the FIRST name it accepts for a resolved directory, so this
    decides which of several names for one directory survives.

    Name order alone was wrong, and the failure shows up over time rather than
    across machines: a running `zebra` loses the tie the moment somebody adds
    `alpha -> zebra`, so it vanishes from the list, reappears under a name with
    no session, reads as stopped, and a tap puts a second agent in the
    directory the first is working in. A real directory's name is durable,
    because creating a link cannot change it. See #11.

    This does NOT close the case where every candidate is a symlink, which
    happens when the shared target is unlistable. See #32.

    A raising `is_symlink` is caught rather than allowed to propagate: this runs
    inside the `sorted()` whose OSError becomes `RootUnavailable`, and one
    unreadable entry must not take the whole root down. The reachable case is
    EACCES; a racing unlink is ENOENT, which pathlib swallows before this.
    """
    try:
        is_link = entry.is_symlink()
    except OSError:
        is_link = False
    return (1 if is_link else 0, entry.name)


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
    # Resolved directory -> the name already accepted for it. Two names for one
    # directory means two rows that each start their own agent in it, because a
    # session is keyed off the name. `_dedup_order` decides which name wins.
    seen: dict[Path, str] = {}

    # Only failing to read the root itself is fatal. Everything below is per
    # entry, and one bad entry must not take the healthy ones with it.
    try:
        entries = sorted(root.iterdir(), key=_dedup_order)
    except OSError as exc:
        raise RootUnavailable(f"cannot read the root {root}: {exc}") from exc

    for entry in entries:
        name = entry.name
        try:
            if not entry.is_dir():
                # A regular file is not somebody's attempt at a project, so it
                # is skipped in silence as before. A broken LINK is different:
                # the user put it there meaning to open something, and this
                # module's whole argument is that a folder which simply
                # vanishes reads as Hitchrail being unable to see it.
                if not entry.is_symlink():
                    continue
                # A distinct name, not `reason`: assigning a str here narrows
                # the variable and mypy then rejects the `str | None` that
                # `explain_name` returns below.
                link_reason = _broken_link_reason(entry)
                if not name.startswith("."):
                    unsupported.append(Unsupported(display_name(name), link_reason))
                continue
            reason = explain_name(name)
            if reason is None:
                resolved = resolve_child(root, name)
                first = seen.get(resolved)
                if first is None:
                    seen[resolved] = name
                    projects.append(name)
                    continue
                # Reported, never dropped in silence: a folder that vanishes
                # reads as Hitchrail being unable to see it, which is the bug
                # `scan` exists to avoid. Name the survivor so the row explains
                # itself.
                reason = f"another name for {display_name(first)}, already listed"
        except OutsideRoot:
            reason = "points outside the root, so it is not safe to open"
        except OSError as exc:
            # ESTALE on an autofs mount, EACCES on one subdirectory. Reporting
            # it as unreadable keeps the other twenty projects visible; making
            # it fatal for the whole root was the same silent loss this
            # function was written to fix, relocated one level up.
            reason = f"cannot be read: {exc.strerror or exc}"

        # A dot directory is not a project somebody was trying to make.
        # Reporting `.git` as rejected would be noise, not information.
        if not name.startswith("."):
            unsupported.append(Unsupported(display_name(name), reason))

    ordered = sorted(unsupported, key=lambda u: u.name.lower())
    return Listing(
        projects=tuple(sorted(projects, key=str.lower)),
        unsupported=tuple(ordered[:MAX_REPORTED_UNSUPPORTED]),
        unsupported_total=len(ordered),
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


# -- #120: several roots ----------------------------------------------------
#
# The per-root functions above are unchanged and stay the boundary check. What
# is added here is the plural layer: which root a name belongs to, and the
# qualified identifier that keeps two roots' same named folders apart.
#
# Deliberately a layer rather than a rewrite. `resolve_child` proving a path is
# a direct child of ONE root is the property the whole security argument rests
# on, and it is not made better by teaching it about labels.


def scan_roots(roots: tuple[Root, ...]) -> Listing:
    """One pass over every root, with every name qualified.

    Order is the operator's, root by root and then within each root, because
    sorting would silently reorder somebody's interface the day they add a
    root.

    **Qualified even with one root**, per #119. A single root that stayed bare
    would mean every identifier changed the day a second was added, which is
    the instability the decision exists to prevent.
    """
    projects: list[str] = []
    unsupported: list[Unsupported] = []
    total = 0
    for root in roots:
        listing = scan(root.path)
        projects += [qualify(root.label, name) for name in listing.projects]
        # The root is named on the rejection too. "`.hidden` is not a project"
        # is a puzzle when two roots are configured and only one has it.
        unsupported += [
            Unsupported(name=qualify(root.label, u.name), reason=u.reason)
            for u in listing.unsupported
        ]
        total += listing.unsupported_total
    return Listing(
        projects=tuple(projects),
        unsupported=tuple(unsupported[:MAX_REPORTED_UNSUPPORTED]),
        unsupported_total=total,
    )


def list_root_projects(roots: tuple[Root, ...]) -> list[str]:
    """Every project identifier across every root."""
    return list(scan_roots(roots).projects)


def _root_for(roots: tuple[Root, ...], identifier: str) -> tuple[Root, str]:
    """Split an identifier and find the root it names.

    **By label, never by searching the roots in order.** A search would make
    the answer depend on the order of `--root` flags, and an identifier whose
    meaning depends on argv order is not the stable identifier #119 required.
    """
    try:
        label, name = split_identifier(identifier)
    except RootError as exc:
        raise OutsideRoot(str(exc)) from exc
    for root in roots:
        if root.label == label:
            return root, name
    raise OutsideRoot(f"no root is labelled {label!r}")


def resolve_identifier(roots: tuple[Root, ...], identifier: str) -> Path:
    """The qualified form of `project_path`.

    The label picks a root; the folder half still goes through `resolve_child`,
    so the qualified identifier is not a second way to leave the boundary.
    """
    root, name = _root_for(roots, identifier)
    return project_path(root.path, name)


def create_in_root(roots: tuple[Root, ...], identifier: str) -> Path:
    """The qualified form of `create_project`."""
    root, name = _root_for(roots, identifier)
    return create_project(root.path, name)
