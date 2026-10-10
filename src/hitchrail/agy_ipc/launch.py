"""Starting agy and finding its session link.

Part of the `agy_ipc` quarantine (#294). `launch_argv` holds the literal
permission skipping argv, which is why this module is on the security rules' list.
"""

from __future__ import annotations

import re
from pathlib import Path

from hitchrail.agent import SessionUrl

# agy refuses a trailing positional (`unexpected argument`, and the pane dies),
# so it cannot carry a project tag the way Claude Code does after
# `--remote-control`. It accepts `--add-dir=<folder>`, which names the folder
# it already works in, and that makes the argv tail unique per project AND per
# root, which is what `find_detached` needs.
#
# It is also the MARKER, not `--remote-control`: agy's argv carries that too,
# and a pane holding agy must not read as Claude Code's. The `=` keeps the
# folder in the same argument, so a path with spaces is one argv entry.
#
# Measured on 1.3.3: the flag also skips the folder trust prompt, which
# appeared without it in the same untrusted folder. See `Antigravity.trusted`.
MARKER = "--add-dir="

URL_BASE = "https://antigravity.google.com/r/"

# The link id as captured: a UUID with a `-v<n>` suffix. A strict shape rather
# than "no separator", because the link is scraped from a pane: a long URL
# wrapped at the pane's edge leaves a truncated id on the row, and a loose
# pattern would offer a link to the wrong place. Truncated, this does not
# match, and the row says `pending`.
_LINK = re.compile(
    rf"{re.escape(URL_BASE)}"
    r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}-v[0-9]{1,4})(?=\s|$)"
)


def launch_argv(binary: str, folder: Path) -> list[str]:
    """The argv that starts agy. A LIST, never a string.

    `--dangerously-skip-permissions` is what makes unattended operation
    possible and is the whole of this project's threat model, as for Claude
    Code. `--remote-control` prints the link `session_url` scrapes.
    """
    return [binary, "--dangerously-skip-permissions", "--remote-control", f"{MARKER}{folder}"]


def session_url(pane_text: str | None) -> SessionUrl | None:
    """The LAST link in the pane, or None for `pending`.

    agy writes no file a link could be read from (nothing was found beside
    its settings), so the pane is the only source and the result is always
    `scraped`: the interface says where it came from. The last rather than
    the first, because scrollback from an earlier agy in the same pane sits
    above the current one's.
    """
    if not pane_text:
        return None
    found = _LINK.findall(pane_text)
    return SessionUrl(f"{URL_BASE}{found[-1]}", "scraped") if found else None
