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

# A `~/` rooted path, which is the class that slipped everything else.
#
# The design canvases showed the owner's real directory scheme as the example
# root, spelled `~/<scheme>`. It has no `/home/` prefix, so `_HOME_PATH` never
# saw it, and it is not a project name, so the private list did not hold it
# either. It sat in a public repository naming how somebody files their work.
#
# The segments ABOVE a project are the sensitive part and the part people miss.
# A path can name an employer, a client, a synced backup drive or a category
# its owner considers private; the project at the end is the only piece anyone
# meant to publish.
#
# Shape alone cannot say whether `~/foo` is private, so this inverts the test:
# an ALLOWLIST of roots a document may show. That is checkable in the open, it
# needs no secret, and it is what would have caught the canvases.
_TILDE_ROOT = re.compile(r"~/([A-Za-z0-9._-]+)")
_ALLOWED_ROOT = frozenset(
    {
        # The example root the README and the design use, and the only one an
        # artboard should ever display.
        "projects",
        # Real, published locations a document legitimately names.
        ".claude",
        # Claude Code's own config file, which `claude_ipc` reads and several
        # fixtures name. A published path belonging to another program.
        ".claude.json",
        ".config",
        ".local",
        ".cache",
        ".ssh",
        ".bashrc",
        ".gitconfig",
        # Placeholders, which are the point rather than an exception.
        "dev",
        "code",
        "src",
        "work",
        "<root>",
    }
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


def test_no_tilde_path_shows_a_real_directory_scheme() -> None:
    """`~/<scheme>` leaks how somebody files their work, without naming them.

    An allowlist rather than a pattern, because shape cannot tell a private
    scheme from a public one. Anything a document needs to show is either the
    canonical example root or a real published location, and both are short
    lists that a reviewer can read.

    **This is the check that was missing.** The canvases displayed the owner's
    actual parent directory as the example root for weeks in a public
    repository. `_HOME_PATH` did not match it, because it starts with `~` and
    not `/home/`, and the private name list did not hold it, because it is not
    a project name. It was found by walking the path above the project and
    grepping for each segment, which is not a thing anybody does twice.
    """
    offences = []
    for path in _tracked():
        try:
            text = path.read_text()
        except (UnicodeDecodeError, OSError):
            continue
        for line_no, line in enumerate(text.splitlines(), 1):
            for match in _TILDE_ROOT.finditer(line):
                if match.group(1) in _ALLOWED_ROOT:
                    continue
                offences.append(f"{path.relative_to(ROOT)}:{line_no}: {match.group(0)}")
    assert not offences, (
        "a `~/` path shows a directory scheme that is not an approved example "
        "root. The segments above a project can name an employer, a client or "
        "a private category:\n  "
        + "\n  ".join(offences[:20])
        + "\nUse ~/projects, or add the root to _ALLOWED_ROOT if it is public."
    )
