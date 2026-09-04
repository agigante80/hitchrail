"""What a root IS, and what a qualified project identifier IS.

#119 decided it: **a project is `<root-label>~<folder>`, always, including when
there is only one root.** This module holds that vocabulary and nothing else.
Pure functions of strings and paths, with the walking left to `discovery`, the
same split `hostnames` has beside `config` and `projectnames` beside
`discovery`. What a name MEANS should be decidable without a machine.

**The injectivity argument lives here, and it is structural rather than
careful.** `projectnames.NAME_PATTERN` is `[A-Za-z0-9][A-Za-z0-9._-]*`, so
neither a folder name nor a label can contain `~`. The qualified form therefore
has exactly one split point, and two distinct project directories can never
produce one identifier. That is the standard `tmux.sanitize` set when it threw
out a digest suffix: injective by construction beats injective by hash, and it
beats injective by careful parsing here too.

`~` rather than `/`, and that is forced rather than preferred. A slash does not
survive the route table: `work%2Fvessel` is a 404, and widening the converter
to `{name:path}` would swallow the `/kill`, `/logs` and `/url` sub-routes. `~`
is unreserved in RFC 3986 so it needs no encoding, and tmux reserves only `.`
and `:`, which `sanitize` already escapes. Verified on tmux 3.4: a session
created as `hr-work~vessel` is stored under that name and answers to
`has-session -t =hr-work~vessel`, unlike `.`, which tmux rewrites to `_`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from hitchrail.projectnames import explain_name

# The one character that may appear in an identifier and in neither half of it.
QUALIFIER = "~"


class RootError(ValueError):
    """A root, or a set of them, that this tool will not accept.

    A ValueError like the other refusals in this package, so `config` can let
    it travel as the startup refusal it always is.
    """


@dataclass(frozen=True, slots=True)
class Root:
    """One place projects are kept, and the label that names it on the wire.

    `path` is expected resolved. `parse_root_argument` resolves, and
    `check_roots` compares resolved paths, because two spellings of one
    directory are one directory and a symlink is a spelling.
    """

    label: str
    path: Path


def parse_root_argument(raw: str) -> Root:
    """`label=path`, as `--root` takes it.

    **A bare path is refused rather than given a label derived from its
    directory name.** That derivation looks helpful and is not: it makes the
    identifier a function of where the directory happens to live, so moving
    `~/projects` to `~/dev` would rename every project on the wire and break
    every link saved on a phone. #119 requires an identifier to be stable, and
    stable means stable against things that are not the identifier.
    """
    label, sep, path = raw.partition("=")
    # `partition`, so only the FIRST `=` splits. A path may contain one; a
    # label may not, because the allowlist below has no `=` in it.
    if not sep:
        raise RootError(
            f"--root takes label=path, and {raw!r} has no label. A root needs a "
            "name because that name is part of every project's identifier"
        )
    if not label:
        raise RootError(f"--root {raw!r} has an empty label")
    if not path:
        raise RootError(f"--root {raw!r} has an empty path")
    # The same allowlist as a project folder, reused rather than restated. It
    # is what keeps QUALIFIER out of a label, which is the whole of the
    # injectivity argument in the module docstring.
    complaint = explain_name(label)
    if complaint is not None:
        raise RootError(f"root label {label!r} is not usable: {complaint}")
    return Root(label=label, path=Path(path).expanduser().resolve())


def qualify(label: str, folder: str) -> str:
    """The identifier for a folder in a labelled root."""
    return f"{label}{QUALIFIER}{folder}"


def split_identifier(identifier: str) -> tuple[str, str]:
    """The inverse of `qualify`, and it refuses anything unqualified.

    A bare folder name is what 0.1.0 addressed projects by. Accepting one here
    would mean picking a root for the caller, which is precisely the ambiguity
    the qualified form removes, and it would do so silently at the moment a
    destructive route is being served.
    """
    label, sep, folder = identifier.partition(QUALIFIER)
    if not sep:
        raise RootError(
            f"{identifier!r} is not a project identifier. Since more than one "
            f"root is possible, a project is named {QUALIFIER.join(('<root>', '<folder>'))}"
        )
    return label, folder


def _contains(outer: Path, inner: Path) -> bool:
    """Is `inner` at or below `outer`?

    `is_relative_to` on resolved paths, never a string prefix. `/dev` is a
    string prefix of `/dev-evil` and is not its parent, which is the same trap
    `discovery.resolve_child` documents refusing.
    """
    return inner == outer or inner.is_relative_to(outer)


def check_roots(roots: tuple[Root, ...]) -> None:
    """Every refusal a set of roots can earn, reported together.

    **All of them at once, not the first.** An operator with three misspelled
    paths should fix three, restart once, and be serving. Reporting one per
    restart turns a typo into an afternoon.
    """
    if not roots:
        raise RootError("no roots configured. Give at least one --root label=path")

    problems: list[str] = []

    seen_labels: dict[str, Root] = {}
    for root in roots:
        if root.label in seen_labels:
            problems.append(
                f"two roots share the label {root.label!r}: "
                f"{seen_labels[root.label].path} and {root.path}"
            )
        else:
            seen_labels[root.label] = root

    missing = [r for r in roots if not r.path.is_dir()]
    problems += [f"root {r.label!r} is not a directory: {r.path}" for r in missing]

    # Only among roots that exist. A missing path resolves to something that
    # cannot be compared meaningfully, and reporting it twice, once as absent
    # and once as overlapping, describes one mistake as two.
    live = [r for r in roots if r.path.is_dir()]
    for i, outer in enumerate(live):
        for inner in live[i + 1 :]:
            if inner.path == outer.path:
                problems.append(
                    f"roots {outer.label!r} and {inner.label!r} are the same "
                    f"directory: {outer.path}"
                )
            elif _contains(outer.path, inner.path):
                problems.append(
                    f"root {inner.label!r} ({inner.path}) is inside root "
                    f"{outer.label!r} ({outer.path}), so one folder would be "
                    "reachable under two identifiers"
                )
            elif _contains(inner.path, outer.path):
                problems.append(
                    f"root {outer.label!r} ({outer.path}) is inside root "
                    f"{inner.label!r} ({inner.path}), so one folder would be "
                    "reachable under two identifiers"
                )

    if problems:
        raise RootError("; ".join(problems))
