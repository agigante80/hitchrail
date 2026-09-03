"""Every third party action runs with the repository's permissions.

A tag is a mutable pointer. `actions/checkout@v7` is whatever the owner of that
repository last pointed `v7` at, and it runs here with the workflow token. A
commit SHA is immutable, so what CI runs is what somebody reviewed.

#4 pinned them. This is what stops the next `uses:` line arriving on a tag,
because the ticket's own verification was "grep and look", and a check that
depends on somebody remembering to look is not a check. The upstream half, a
tag repointed at different code, genuinely cannot be asserted from in here; the
pinning can, and is.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

WORKFLOWS = sorted(
    (Path(__file__).resolve().parents[1] / ".github" / "workflows").glob("*.yml")
)

# `owner/repo@ref`, and the ref is what this test is about. Local actions
# (`./.github/actions/x`) and reusable workflows carry no third party code and
# are matched separately if they ever appear.
_USES = re.compile(r"^\s*-?\s*uses:\s*(?P<action>[^\s#]+)", re.M)
_SHA = re.compile(r"^[0-9a-f]{40}$")


def test_there_are_workflows_to_check() -> None:
    """Guard the guard. A renamed directory would make every test below vacuous
    by iterating an empty list, which is the failure this project has already
    shipped once in a teardown assertion."""
    assert WORKFLOWS, "no workflow files found, so the pinning checks prove nothing"


@pytest.mark.parametrize("workflow", WORKFLOWS, ids=lambda p: p.name)
def test_every_third_party_action_is_pinned_to_a_sha(workflow: Path) -> None:
    unpinned = []
    for match in _USES.finditer(workflow.read_text()):
        action = match.group("action")
        if action.startswith("./"):
            continue
        _, _, ref = action.partition("@")
        if not _SHA.match(ref):
            unpinned.append(action)
    assert not unpinned, (
        f"{workflow.name} runs third party code from a mutable ref: {unpinned}. "
        "Pin it: gh api repos/<owner>/<repo>/commits/<tag> --jq .sha"
    )


@pytest.mark.parametrize("workflow", WORKFLOWS, ids=lambda p: p.name)
def test_every_pinned_action_says_which_version_it_is(workflow: Path) -> None:
    """A bare SHA is unreadable, so the version lives in a trailing comment.

    The comment is documentation and the SHA is the contract. They can disagree
    if somebody edits one, and nothing here can catch that: a SHA is opaque
    without asking GitHub, and this suite does not reach the network.
    """
    undocumented = [
        line.strip()
        for line in workflow.read_text().splitlines()
        if _USES.match(line) and "@" in line and "#" not in line
    ]
    assert not undocumented, (
        f"{workflow.name} pins an action with no `# vX.Y.Z` comment: {undocumented}"
    )
