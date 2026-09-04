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


def _without_comments(workflow: Path) -> str:
    """The configuration, with the prose stripped out.

    **Both checks below failed on their own explanations first.** The workflow
    comments say "No username and no password: their absence is what selects
    trusted publishing" and "Nothing here needs contents: write", so a plain
    substring search found the very strings the comments exist to forbid.

    That is the second time in this repository: the screenshot guard failed on
    a docstring naming the fixture it forbids. The lesson is worth writing
    down rather than fixing twice more. A guard that reads prose as
    configuration cannot tell a use from a warning about that use, and the
    warning is exactly what a careful author writes.
    """
    kept = []
    for line in workflow.read_text().splitlines():
        if line.lstrip().startswith("#"):
            continue
        # A trailing comment, which is where the version pins live.
        head, sep, _ = line.partition("  #")
        kept.append(head if sep else line)
    return "\n".join(kept)


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


def test_no_workflow_holds_a_publish_credential() -> None:
    """#116's whole argument, asserted where somebody would undo it.

    Trusted publishing works by the ABSENCE of a username and password: the
    action falls back to OIDC when neither is given. That makes the safe
    configuration invisible, and the unsafe one a two line addition that looks
    like a fix when a publish fails.

    A long lived PyPI token in a repository secret would be the largest thing
    in this project's threat model, in a repository whose CI is deliberately
    `contents: read` so a stolen workflow token buys nothing.
    """
    offences = []
    for workflow in WORKFLOWS:
        text = _without_comments(workflow)
        for marker in ("password:", "PYPI_API_TOKEN", "TWINE_PASSWORD"):
            if marker in text:
                offences.append(f"{workflow.name} contains {marker!r}")
    assert not offences, (
        "\n  ".join(["a workflow holds a publish credential:", *offences])
        + "\n  Trusted publishing needs no secret. See #116."
    )


def test_the_publishing_job_asks_for_no_more_than_it_needs() -> None:
    """`id-token: write` is the one elevated permission, and `contents: write`
    would let a compromised action rewrite the repository it publishes from."""
    publish = next((w for w in WORKFLOWS if w.name == "publish.yml"), None)
    if publish is None:
        pytest.skip("no publish workflow yet")
    text = _without_comments(publish)
    assert "id-token: write" in text, "trusted publishing needs id-token: write"
    assert "contents: write" not in text, (
        "the publish workflow asks for contents: write, which it does not need"
    )
    assert "environment:" in text, (
        "the publish job has no environment, so nothing gates it on a human"
    )
