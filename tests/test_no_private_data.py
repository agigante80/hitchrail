"""No absolute home path and no email address reaches a tracked file.

The public half of a guard whose other half cannot be public.

**What happened.** This repository was public while `docs/design/` carried 52
real folder names from the owner's machine, several of them personal, because a
demo project list had been built from a real listing and nobody looked again.

**Why the specific check cannot live here.** Catching a PROJECT NAME needs a
list of the names, and a list of private names in a public repository is itself
the leak: it tells a reader exactly what to search the history for. That half is
a local pre-commit hook reading a file outside the repository, and it protects
one machine.

**Why this half can, and must.** An absolute home path and an email address are
recognisable by SHAPE, so the pattern is not secret and no list is needed. That
makes them checkable in the open, for every contributor and on every push, which
is what a guard nobody has to install is worth.

Honest about its own reach: **this test would NOT have caught the leak that
prompted it.** Fifty two folder names contain no home path and no email. It
catches the other class, the one where somebody pastes a traceback or a `ps`
line into a comment, which is exactly what happened repeatedly in this project's
issue history.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# An absolute path into somebody's home directory. Placeholder and REDACTED
# forms are allowed: a document explaining where a file lives has to say so,
# and `/home/.../x` is what a redacted paste looks like once it is safe.
_HOME_PATH = re.compile(r"(?:/home/|/Users/)(?!user\b|you\b|USER\b|<|\.\.\.)[A-Za-z0-9._-]+/")

# An email address, and NOT a URL's userinfo. `http://user:pass@box.lan` is a
# host parsing fixture, not a person, and this project has several: the `(?<![:/])`
# refuses a local part that a scheme or a colon introduced.
_EMAIL = re.compile(r"(?<![:/\w])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
# `noreply@` is how commit attribution works and names nobody. The rest are the
# TLDs reserved for documentation and for local networks, which cannot reach a
# real mailbox.
_ALLOWED_EMAIL = re.compile(
    r"noreply@|@[A-Za-z0-9.-]*claude|\.(?:example|invalid|test|localhost|lan|local)\b"
    r"|example\.(?:com|org|net)"
)

# Binary and generated files have no prose to check and blow the runtime up.
_SKIP_SUFFIX = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".woff", ".woff2", ".lock"}


# This file, which is the one place a home path and an email address SHOULD
# appear: the samples below prove the patterns can fire, and a guard that
# cannot fire reports safety it is not providing.
#
# It became self flagging the moment it was committed, because the scan reads
# `git ls-files` and an untracked file is invisible to it. That is worth
# knowing on its own: **a new file is unguarded until it is tracked**, so the
# first commit of a file is the one this cannot check. The pre-commit hook is
# what covers that gap, since it reads the staged content instead.
_SELF = Path(__file__).resolve()


def _tracked() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.split()
    return [
        ROOT / f
        for f in out
        if Path(f).suffix not in _SKIP_SUFFIX and (ROOT / f).resolve() != _SELF
    ]


def _offences(pattern: re.Pattern[str], allow: re.Pattern[str] | None = None) -> list[str]:
    found = []
    for path in _tracked():
        try:
            text = path.read_text()
        except (UnicodeDecodeError, OSError):
            continue
        for line_no, line in enumerate(text.splitlines(), 1):
            for match in pattern.finditer(line):
                if allow and allow.search(match.group(0)):
                    continue
                rel = path.relative_to(ROOT)
                found.append(f"{rel}:{line_no}: {match.group(0)}")
    return found


def test_no_absolute_home_path_is_committed() -> None:
    """A path like `/home/<somebody>/projects` names a person and a machine.

    It arrives by pasting: a traceback, a `ps` line, a shell prompt. Every one
    of those is useful evidence and none of them needs the real path in it.
    """
    offences = _offences(_HOME_PATH)
    assert not offences, (
        "an absolute home path names the person who ran the command:\n  "
        + "\n  ".join(offences[:20])
        + "\nUse a placeholder such as /home/user or <home>."
    )


def test_no_email_address_is_committed() -> None:
    """Same argument, and the same way in.

    `noreply@` and `example.com` are allowed: the first is how commit
    attribution works and names nobody, the second is reserved for documents.
    """
    offences = _offences(_EMAIL, allow=_ALLOWED_EMAIL)
    assert not offences, (
        "an email address identifies a person:\n  "
        + "\n  ".join(offences[:20])
        + "\nUse an example.com address, or none."
    )


@pytest.mark.parametrize(
    ("sample", "pattern"),
    [
        ("/home/someone/projects/x", _HOME_PATH),
        ("/Users/someone/code/y", _HOME_PATH),
        ("somebody@realmail.com", _EMAIL),
    ],
    ids=["linux home", "macos home", "email"],
)
def test_the_patterns_actually_match(sample: str, pattern: re.Pattern[str]) -> None:
    """A guard that cannot fire is worse than none, because it reports safety it
    is not providing. Both of the above pass on a clean tree, so the only thing
    proving they work is this."""
    assert pattern.search(sample)


def test_the_placeholder_forms_are_not_flagged() -> None:
    """The other direction. A check that refuses `/home/user` makes every
    document that explains a path unwriteable, and the fix people reach for is
    to delete the check."""
    for allowed in ("/home/user/x", "/home/you/x", "<home>/x", "/home/.../x"):
        assert not _HOME_PATH.search(allowed), allowed
    # And the URL userinfo that is a fixture rather than a person.
    for allowed in ("http://user:pass@box.lan", "noreply@anthropic.com"):
        m = _EMAIL.search(allowed)
        assert m is None or _ALLOWED_EMAIL.search(m.group(0)), allowed
