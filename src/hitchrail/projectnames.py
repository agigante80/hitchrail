"""What a valid project NAME is, and how one is safely displayed.

Split out of `discovery.py` at #33, along the same seam `hostnames.py` used:
pure functions of a string in one module, the thing that walks the filesystem
with them in another. `discovery` imports this; this imports nothing of
`discovery`, and a test asserts that so the split stays a seam rather than a
cut through a cycle.

`display_name` is a security control and lives here. It escapes terminal
sequences and surrogate escapes out of any folder name that gets reported
outward, because a folder called `report\x1b[2J` clears the terminal of
anything printing the listing. `.claude/rules/security.md` names this module
for that reason.
"""

from __future__ import annotations

import re

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

# How many rejected folders to name before giving up and reporting a count.
# A root that shares a tree with a Downloads folder can hold thousands.
_UNSAFE_TO_DISPLAY = re.compile("[\x00-\x1f\x7f-\x9f\u200b-\u200f\u2028-\u202e\u2066-\u2069]")


def display_name(name: str) -> str:
    """Make a filesystem name safe to show, without pretending it is valid.

    Two separate hazards, both of which arrive only because rejected folders
    are now reported rather than dropped:

    - **Surrogates.** `os.listdir` surrogate escapes a name that is not valid
      UTF-8, and `json.dumps(...).encode("utf-8")` then raises. One latin-1
      named folder under the root would have turned the whole project list into
      a 500, hiding every healthy project behind it.
    - **Control and bidi characters.** These are exactly what the allowlist
      refuses on the way in, and reporting the rejection handed them straight
      back out.

    Nothing passed to this function is a valid project name, so escaping loses
    nothing: no caller can open these paths anyway.
    """
    # errors="replace" turns lone surrogates into U+FFFD rather than raising.
    decoded = name.encode("utf-8", "replace").decode("utf-8", "replace")
    return _UNSAFE_TO_DISPLAY.sub(lambda m: f"\\u{ord(m.group()):04x}", decoded)


class InvalidName(ValueError):
    """The name is not one we are willing to turn into a path."""


def _describe_offenders(offenders: list[str]) -> str:
    """Group by kind rather than listing each character.

    Naming every distinct character produced "a non ASCII character ('P'), a
    non ASCII character ('e') and 3 more" for a Cyrillic folder name, which
    tells the reader nothing they could not see and buries the one useful
    word in it.

    The buckets are exclusive. A non breaking space, which copy and paste out
    of a browser produces routinely, is both whitespace and non ASCII, and
    landing in two buckets reported one character as two separate problems.
    """
    spaces = [c for c in offenders if c.isascii() and c.isspace()]
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
