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


# -- #155: what keeps those pins from going stale ---------------------------

DEPENDABOT = Path(__file__).resolve().parents[1] / ".github" / "dependabot.yml"

# Line based, like the pinning check above, and for the same reason: this
# project has three runtime dependencies and a YAML parser is not one of them.
_ECOSYSTEM = re.compile(r"^\s*-\s*package-ecosystem:\s*\"?([\w-]+)", re.M)
_TARGET = re.compile(r"^\s*target-branch:\s*\"?([\w/-]+)", re.M)


def test_the_pins_have_something_that_updates_them() -> None:
    """A SHA pin is correct and it cannot update itself.

    The test above asserts every action is pinned. Nothing asserted that
    anybody would ever learn a newer version exists, which is the other half of
    the same control: a person reading `# v4.2.1` cannot see that v4.3.0
    shipped.
    """
    assert DEPENDABOT.exists(), (
        "nothing updates the pinned actions, so the pin above degrades from a "
        "control into a snapshot of whatever was current when it was written"
    )
    assert "github-actions" in _ECOSYSTEM.findall(DEPENDABOT.read_text())


def test_no_ecosystem_sets_a_target_branch() -> None:
    """#155, and this is the counterintuitive half.

    Setting `target-branch: develop` reads as obviously right: `main` requires
    the `version-bumped` check, a dependency bump does not bump the project
    version, so a pull request against `main` is red on a required check by
    construction.

    It costs the thing that matters most. A SECURITY update always targets the
    repository's DEFAULT branch whatever this file says, and GitHub's options
    reference is explicit that once `target-branch` is set, the options in that
    stanza stop applying to security updates. `allow` is one of them, so the
    direct-only rule would hold for version updates and silently not for
    security updates, and transitive advisories would arrive as pull requests
    nobody intends to merge.

    `develop` is the default branch instead, which lands both kinds there and
    keeps `allow` applying to both.

    **What this test cannot see is the default branch**, which is a repository
    setting rather than a file. If it is ever moved back to `main`, every
    dependency pull request lands on the release gate and this stays green.
    That is written here rather than left as a surprise; the check that would
    catch it lives in the GitHub settings, not in the suite.
    """
    targets = _TARGET.findall(DEPENDABOT.read_text())
    assert targets == [], (
        f"target-branch is set to {targets}, which stops `allow` applying to "
        "security updates, so transitive advisories start arriving as pull "
        "requests. See the comment in the file."
    )


def test_the_python_ecosystem_updates_only_what_this_project_declares() -> None:
    """Direct dependencies only, and transitive ones left alone.

    A vulnerability reached through a transitive package is fixed by moving the
    direct dependency that pulls it in, not by pinning something this project
    does not declare. A pull request against the transitive package is one
    nobody would merge, and a queue of those is how the one that matters gets
    skimmed past.

    Asserted for `uv` only. Every action a workflow names is direct, so the
    same filter on `github-actions` would express nothing.
    """
    text = DEPENDABOT.read_text()
    uv_stanza = text.split('package-ecosystem: "uv"', 1)[1].split("package-ecosystem:", 1)[0]
    assert 'dependency-type: "direct"' in uv_stanza, (
        "the Python ecosystem would open pull requests for transitive packages, "
        "which are fixed by moving a direct dependency rather than by pinning them"
    )
