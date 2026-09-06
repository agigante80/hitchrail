"""The documents make checkable claims, so check them.

Every guard this project has protects the SOURCE: five gates, an import
contract, module size caps, a tier partition, a template lockstep. Nothing
protected the prose, and the prose is what an outside reader meets first.

The cost was not hypothetical. The conventions file, then `.claude/CLAUDE.md`
and now `AGENTS.md`, told every reader that
`engine.py`, `server.py`, `events.py` and `cli.py` were one line placeholders
for three phases after all four were implemented, and that is the file an agent
reads before it touches anything. The design's route table stayed correct while
its error code list fell nine behind the server (#58). A `?kill=1` contradiction
was copied into seven documents because each copy looked like the source.

The rule these tests encode: **a document may hold an argument, which no test
can check, but a claim about the code has to be checkable or it does not belong
in a document.**
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
import tempfile
import textwrap
from collections.abc import Iterator
from pathlib import Path

import pytest

from hitchrail import claude_ipc
from hitchrail.cli import parse_args
from support import make_config

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "hitchrail"
AGENTS_MD = ROOT / "AGENTS.md"

# **These guards used to skip on a clone, and now they do not.**
#
# The conventions lived in `.claude/CLAUDE.md`, which is untracked, so every
# check below ran only in the maintainer's checkout: CI validated the roadmap
# and not the file an agent reads first. #60 moved them to `AGENTS.md` at the
# root, for the wider reason that exactly one tool read the old location, and
# this is the side effect worth naming. The guard that caught a reversed
# middleware order now runs on every push, for every contributor.
#
# There is no skip mark any more. A missing `AGENTS.md` is a failure, not a
# reason to pass quietly.
ROADMAP = ROOT / "docs" / "roadmap.md"
README = ROOT / "README.md"

# Anything under this is a stub. Every real module here is far larger, and the
# four that were wrongly described as placeholders are 150 lines and up.
PLACEHOLDER_LINES = 5


def _modules() -> dict[str, int]:
    return {p.name: len(p.read_text().splitlines()) for p in SRC.glob("*.py")}


@pytest.mark.parametrize("doc", [AGENTS_MD, ROADMAP], ids=lambda p: p.name)
def test_no_document_calls_an_implemented_module_a_placeholder(doc: Path) -> None:
    """The exact failure that prompted this file.

    A reader told `server.py` is a placeholder will not read it, and an agent
    told the same will try to write it from scratch over 430 working lines.
    """
    text = doc.read_text()
    sizes = _modules()
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if "placeholder" not in sentence.lower() and "does not exist" not in sentence.lower():
            continue
        if "was wrong" in sentence or "claimed" in sentence or "wrongly" in sentence:
            continue  # the note recording the mistake is not a fresh claim
        named = [m for m in sizes if m in sentence]
        implemented = [m for m in named if sizes[m] > PLACEHOLDER_LINES]
        assert not implemented, (
            f"{doc.name} calls {implemented} a placeholder, but "
            f"{ {m: sizes[m] for m in implemented} } lines say otherwise"
        )


@pytest.mark.parametrize("doc", [AGENTS_MD, ROADMAP, README], ids=lambda p: p.name)
def test_no_document_hardcodes_a_test_count(doc: Path) -> None:
    """ "519 tests" was true once. A number that decays silently is worse than
    no number, because it reads as precision."""
    text = doc.read_text()
    stale = re.findall(r"\b(\d{3,5})\s+tests\b", text)
    assert not stale, (
        f"{doc.name} hardcodes a test count {stale}, which will be wrong within "
        "a phase. Say what is covered, not how many there are."
    )


def _named_in_agents_md() -> set[str]:
    """The modules the architecture block claims exist, by their listed name."""
    return set(re.findall(r"^\s{2}(\w+\.py)\s", AGENTS_MD.read_text(), re.M))


# `__init__.py` is a package marker rather than a module anybody navigates to,
# and listing it in the architecture block would be noise. Named here, and kept
# short on purpose: a broad pattern in this exemption is how the NEXT module
# goes missing, which is the whole failure below.
_NOT_ON_THE_MAP = {"__init__.py"}


def test_every_module_named_in_agents_md_exists() -> None:
    """The architecture block lists the modules. A rename that misses it leaves
    a map pointing at a road that is not there."""
    missing = {n for n in _named_in_agents_md() if not (SRC / n).exists()}
    assert not missing, f"AGENTS.md names modules that do not exist: {sorted(missing)}"


def test_every_module_that_exists_is_named_in_agents_md() -> None:
    """#126. The inverse of the guard above, and the direction that was missing.

    **The asymmetry was not theoretical.** The guard above was green while the
    block named neither `derive.py`, `pages.py` nor `projectnames.py`, and still
    credited `engine.py` with the state derivation #50 had moved out of it. A
    guard that only checks that named things exist cannot see a thing that was
    never named.

    Two of the three were the ones an agent most needs to find.
    `projectnames.py` holds `display_name`, which `.claude/rules/security.md`
    names as a security control, and `pages.py` is the only code in the project
    that reads a file chosen by a URL. The map told a reader deciding what it
    was safe to touch that neither existed.
    """
    on_disk = {p.name for p in SRC.glob("*.py")} - _NOT_ON_THE_MAP
    unlisted = on_disk - _named_in_agents_md()
    assert not unlisted, (
        "AGENTS.md does not name "
        + ", ".join(
            f"{n} ({len((SRC / n).read_text().splitlines())} lines)" for n in sorted(unlisted)
        )
        + ". A module missing from the architecture block is one an agent "
        "reading the map is told does not exist."
    )


def test_the_roadmap_marks_a_phase_done_only_when_its_plan_is_finished() -> None:
    """A phase headed "(done)" whose plan still has unticked steps is a phase
    somebody stopped writing down rather than one that finished."""
    road = ROADMAP.read_text()
    plans = {
        p.name: p.read_text() for p in (ROOT / "docs" / "superpowers" / "plans").glob("*.md")
    }
    for match in re.finditer(
        r"^## (Phase \d+)[^\n]*\(done\)(.*?)(?=^## |\Z)", road, re.M | re.S
    ):
        section = match.group(2)
        link = re.search(r"\(superpowers/plans/([^)]+)\)", section)
        if not link:
            continue
        plan = plans.get(link.group(1))
        assert plan is not None, f"{match.group(1)} links a plan that is not there"
        unticked = plan.count("\n- [ ] ")
        assert unticked == 0, (
            f"{match.group(1)} is marked done but its plan has {unticked} unticked items"
        )


# -- #63: the design's error table against the server -----------------------

SPEC = ROOT / "docs" / "superpowers" / "specs" / "2026-08-25-hitchrail-design.md"
SERVER = SRC / "server.py"


def _codes_the_server_returns() -> set[str]:
    """Parsed from the SOURCE, not imported from a list.

    A list exported from `server.py` and compared against the document would
    pass while a handler returned something not on it, which is the exact shape
    of the gap #63 is about. Reading the calls catches a code added inline the
    same as one added to the constant.
    """
    src = SERVER.read_text()
    codes = set(re.findall(r'_error\(\s*\d+,\s*"([a-z_]+)"', src))
    for block in re.findall(r"_ROUTING_CODES\s*=\s*\{(.*?)\}", src, re.S):
        codes |= set(re.findall(r'"([a-z_]+)"', block))
    return codes


SECURITY_SRC = SRC / "security.py"
API = ROOT / "docs" / "api.md"


def _codes_the_middleware_returns() -> set[str]:
    """The three refusals that never reach a handler.

    #58's original table missed these entirely, because it read `_error(` in
    `server.py` and the boundary answers with `deny(` in `security.py`. A
    client gets `host_rejected` and `origin_rejected` more often than most
    handler codes, and neither was documented anywhere.
    """
    return set(re.findall(r'deny\(\s*\d+,\s*"([a-z_]+)"', SECURITY_SRC.read_text()))


def _codes_the_api_doc_documents() -> set[str]:
    return set(re.findall(r"^\| `([a-z_]+)` \| \d+ \|", API.read_text(), re.M))


def test_the_api_doc_documents_every_code_the_server_can_return() -> None:
    """The table listed six of fifteen, and a reader cannot tell a short list
    from a complete one. `machine_unreadable` was the costly omission: a client
    that renders its 503 as a failed request shows an empty list where the
    truth is that the machine cannot be read.

    Reads `docs/api.md` rather than the design (#58). A design document is the
    argument for building the thing; an integrator looks for a reference, and
    the complete table used to exist only in a CLOSED phase's plan.
    """
    missing = (
        _codes_the_server_returns() | _codes_the_middleware_returns()
    ) - _codes_the_api_doc_documents()
    assert not missing, (
        f"the server returns codes docs/api.md does not document: {sorted(missing)}"
    )


def test_the_api_doc_documents_no_code_the_server_cannot_return() -> None:
    """The other direction, and it is not symmetry for its own sake. A document
    describing a refusal that cannot happen sends a client author writing a
    dead branch, which is the same class of harm as omitting a live one."""
    stale = _codes_the_api_doc_documents() - (
        _codes_the_server_returns() | _codes_the_middleware_returns()
    )
    assert not stale, (
        f"docs/api.md documents codes the server cannot return: {sorted(stale)}. "
        "Remove them, or the client writes branches that never run."
    )


# -- the README, which is the only one a stranger reads ---------------------


def test_the_readme_does_not_claim_a_phase_is_unbuilt_that_the_roadmap_closed() -> None:
    """The file a stranger meets first was the only one with no guard.

    It said "Phases 1 to 3 of 7 are built; there is no runnable server yet" and
    that "what does not exist yet is everything you would actually use: the HTTP
    API, the browser interface, and the engine" long after all three were built,
    tested and driven from a phone. Anybody arriving would have read that and
    left.

    This is the same failure `.claude/CLAUDE.md` records about ITSELF, in the
    docstring at the top of this file, repeated in the one document that guard
    did not cover. Two copies of a claim, one checked.

    Checked against the ROADMAP rather than against a number written here, so
    closing a phase updates the expectation instead of breaking the test.
    """
    readme = README.read_text()
    closed = re.findall(r"^## (Phase \d+)[^\n]*\((?:done|closed)\)", ROADMAP.read_text(), re.M)
    assert closed, "the roadmap marks no phase done, so this cannot check anything"
    highest = max(int(p.split()[1]) for p in closed)

    for match in re.finditer(r"[Pp]hases? (\d+) to (\d+) of \d+ are built", readme):
        claimed = int(match.group(2))
        assert claimed >= highest, (
            f"README says phases up to {claimed} are built; the roadmap closed "
            f"Phase {highest}. The README is the only document a stranger reads."
        )

    # The specific sentence that was wrong, in the shape it was wrong in.
    for absent in ("there is no runnable server", "no runnable server yet"):
        assert absent not in readme.lower(), (
            f"README still says {absent!r}, and the server runs"
        )


# The order below is not cosmetic and the wrong version was in CLAUDE.md for
# long enough to be quoted. Host is outermost so a rebound request never
# reaches anything that could leak whether a token is even correct, and Token
# sits before Origin so an unauthenticated caller cannot learn which origins
# this server accepts by watching 403 turn into 401. An agent that "fixed" the
# stack to match the documentation would have removed the second property and
# believed it was correcting drift, which is why this reads the code and never
# a second copy of the expected order. See #111.
_CONTROL_CLASSES = {
    "host allowlist": "HostAllowlistMiddleware",
    "token": "TokenMiddleware",
    "origin check": "OriginCheckMiddleware",
}


def test_agents_md_states_the_middleware_order_the_code_uses(tmp_path: Path) -> None:
    from hitchrail.security import middleware_stack

    line = re.search(r"^\s{2}security\.py\s+(.+)$", AGENTS_MD.read_text(), re.M)
    assert line, "AGENTS.md's architecture block no longer describes security.py"

    described = [
        _CONTROL_CLASSES[part]
        for part in (p.strip() for p in line.group(1).split(","))
        if part in _CONTROL_CLASSES
    ]
    # Starlette types `Middleware.cls` as a callable protocol rather than a
    # class, so mypy refuses `__name__` on it even though every entry here is a
    # class at runtime. `getattr` silences mypy and trips ruff's B009, so the
    # ignore is narrowed to the one attribute instead.
    actual = [
        m.cls.__name__  # type: ignore[attr-defined]
        for m in middleware_stack(make_config(tmp_path))
    ]

    assert described == actual, (
        f"AGENTS.md says {described}, middleware_stack returns {actual}. "
        "Fix the document: the stack order is deliberate and documented in its "
        "own docstring."
    )


# A feature the README says is missing, that the code has. The phase guard
# above cannot see this: it matches "phases N to M of X are built" and nothing
# else, so prose denying a specific feature passed it for a whole phase.
#
# Found while writing SECURITY.md, which #59 says must REPEAT the README's
# limitations rather than link them. Repeating a stale claim would have copied
# it into a second document, which is how the `?kill=1` contradiction reached
# seven files.
_FEATURES = {
    "live updates": SRC / "web" / "app.js",
    "the token screen": SRC / "web" / "grant.html",
    "dark theme": SRC / "web" / "app.css",
}
_DENIALS = ("do not exist yet", "does not exist yet", "is not built", "are not built")


def test_the_readme_does_not_deny_a_feature_the_code_has() -> None:
    """The README said "Live updates and the token screen do not exist yet"
    after Phase 6 shipped both, for a whole phase.

    Sentence scoped rather than document scoped, so the file can still say a
    thing does not exist when it genuinely does not.
    """
    readme = README.read_text()
    offences = []
    for sentence in re.split(r"(?<=[.!?])\s+", readme):
        lowered = sentence.lower()
        if not any(d in lowered for d in _DENIALS):
            continue
        for feature, evidence in _FEATURES.items():
            if feature in lowered and evidence.exists():
                offences.append(f"{feature!r} denied by: {sentence.strip()[:90]}")
    assert not offences, "the README denies a feature that is in the tree:\n  " + "\n  ".join(
        offences
    )


# -- #59 and #61: the two files a stranger is pointed at --------------------

SECURITY = ROOT / "SECURITY.md"
CONTRIBUTING = ROOT / "CONTRIBUTING.md"

# #59 is explicit that the limitations are REPEATED in the policy rather than
# linked from it: "Somebody reading a security policy should not have to go and
# find them." Repetition is a drift risk by construction, so it gets a guard.
#
# Matched on the distinctive claim rather than on whole sentences, so the prose
# can be edited and the substance cannot quietly go missing.
_MUST_APPEAR_IN_BOTH = {
    "unsandboxed agent": ("dangerously-skip-permissions",),
    "cleartext on plain HTTP": ("cleartext",),
    "the reverse proxy remedy": ("reverse proxy", "TLS terminating"),
}


def test_the_security_policy_repeats_the_limitations_rather_than_linking_them() -> None:
    """A reporter should not have to open a second file to learn that the thing
    they are about to report is the design."""
    policy = SECURITY.read_text().lower()
    readme = README.read_text().lower()
    missing = []
    for label, needles in _MUST_APPEAR_IN_BOTH.items():
        if not any(n.lower() in readme for n in needles):
            missing.append(f"{label}: not in the README, so the pair cannot be checked")
        elif not any(n.lower() in policy for n in needles):
            missing.append(f"{label}: in the README and not in SECURITY.md")
    assert not missing, "\n  ".join(["the policy has drifted from the README:", *missing])


def test_the_security_policy_names_a_private_channel() -> None:
    """#59's whole point. A policy that says "report responsibly" and gives no
    address sends the reporter to a public issue, which is a disclosure."""
    policy = SECURITY.read_text()
    assert "security/advisories/new" in policy, (
        "SECURITY.md must link the private reporting form, not describe it"
    )


def test_contributing_and_agents_list_the_same_gates() -> None:
    """Both files tell somebody which checks are blocking, so both are copies of
    one fact. The copy that drifts is the one a contributor happens to read.

    Compared as sets: order differs between the two on purpose, since one is a
    setup sequence and the other is a reference.
    """
    pattern = re.compile(r"^uv run ([a-z-]+)", re.M)
    contributing = set(pattern.findall(CONTRIBUTING.read_text()))
    agents = set(pattern.findall(AGENTS_MD.read_text()))
    gates = {"pytest", "ruff", "mypy", "lint-imports"}
    assert gates <= contributing, f"CONTRIBUTING.md omits gates: {sorted(gates - contributing)}"
    assert gates <= agents, f"AGENTS.md omits gates: {sorted(gates - agents)}"


def test_contributing_points_at_documents_that_exist() -> None:
    """It deliberately restates almost nothing, which makes it a page of links.
    A broken one turns "read the standard" into "there is no standard"."""
    text = CONTRIBUTING.read_text()
    broken = [
        target
        for target in re.findall(r"\]\(([^)#h][^)]*\.md)\)", text)
        if not (ROOT / target).exists()
    ]
    assert not broken, f"CONTRIBUTING.md links documents that are not there: {broken}"


# -- #62: the changelog, which is the operator contract reported against ----

CHANGELOG = ROOT / "CHANGELOG.md"


def test_the_changelog_has_somewhere_to_put_the_next_change() -> None:
    """`Unreleased` exists so a release is an edit to a heading rather than an
    archaeology exercise. Without it, entries accrue in the commit log and get
    reconstructed at release time, badly."""
    assert re.search(r"^## Unreleased$", CHANGELOG.read_text(), re.M), (
        "CHANGELOG.md has no Unreleased section, so there is nowhere to write "
        "the next operator visible change as it lands"
    )


def test_the_changelog_names_every_breaking_change_that_has_landed() -> None:
    """The two that are already in `main` and cost an operator something.

    Checked by their SUBJECT rather than by a ticket number, because a
    changelog entry citing an issue number tells an operator nothing: they are
    reading it to find out what to do, not what it was called.
    """
    text = CHANGELOG.read_text().lower()
    required = {
        "the removed query grant": "?token=",
        "the token now demanded for declared reach": "--allow-host",
    }
    missing = [label for label, needle in required.items() if needle.lower() not in text]
    assert not missing, (
        "a breaking change is in main and not in the changelog: "
        + ", ".join(missing)
        + ". An operator upgrading has no way to learn it."
    )


def test_a_released_version_heading_matches_a_real_tag() -> None:
    """A heading for a version nobody can install is worse than no heading.

    Skips while there are no tags, which is the honest state before the first
    release, and says so rather than passing silently.
    """
    import subprocess

    tags = subprocess.run(
        ["git", "tag"], cwd=ROOT, capture_output=True, text=True, check=False
    ).stdout.split()
    headings = re.findall(r"^## \[?v?(\d+\.\d+\.\d+)\]?", CHANGELOG.read_text(), re.M)
    if not tags:
        assert not headings, (
            f"the changelog names released versions {headings} and the repository "
            "has no tags, so nobody can install any of them"
        )
        pytest.skip("no tags yet, which is correct before the first release")
    normalised = {t.lstrip("v") for t in tags}
    # **The version being PREPARED is allowed to be untagged**, and #132 is why.
    # A release is now a pull request from `develop` to `main`: the changelog
    # heading has to be dated ON that request so it is reviewed with the change,
    # and the tag cannot exist until after the merge. Without this the guard
    # blocks the very merge that would create the tag it demands.
    #
    # Scoped to exactly one version, the one `pyproject.toml` currently names,
    # so it stays a guard. Every OLDER heading still needs its tag: a heading
    # for a version nobody can install is the failure this exists to catch, and
    # the version in flight is the single case where nobody can install it YET.
    preparing = re.search(
        r'^version = "(\d+\.\d+\.\d+)"', (ROOT / "pyproject.toml").read_text(), re.M
    )
    allowed = normalised | ({preparing.group(1)} if preparing else set())
    unreleased = [h for h in headings if h not in allowed]
    assert not unreleased, f"changelog versions with no tag: {unreleased}"


# -- #185, #188: the release notes the workflow can actually extract --------
#
# The changelog heading is described in three places and they disagreed. This
# file's own `test_a_released_version_heading_matches_a_real_tag` accepts
# `## [v0.4.0]`, brackets and prefix included; its `^## Unreleased$` check
# accepts neither; and `release.yml` accepts neither. So the bracketed form
# that `CHANGELOG.md`'s preamble tells an author to write passed every local
# gate and failed AFTER a merge to `main`, which is the most expensive place to
# find out. That happened, on 0.4.0.
#
# The rule is enforced here by RUNNING the workflow's own script rather than by
# restating its pattern, because a restatement is a fourth copy of the thing
# that drifted.

RELEASE_YML = ROOT / ".github" / "workflows" / "release.yml"


def _notes_script() -> str:
    """The python `release.yml` runs to turn CHANGELOG.md into release notes.

    Recovered from the workflow rather than copied, which is the whole point:
    a copy is a second source of truth and this exists because there were
    three. `tests/test_workflows_are_pinned.py` reads these files the same way,
    and for the same reason PyYAML is not used: the runtime dependency budget
    is three and full, so the parsing is stdlib.

    **Fails rather than skips when it cannot find the block.** A guard that
    quietly finds nothing to guard is the shape this whole test exists to
    remove.
    """
    blocks = re.findall(r'python3 -c "\n(.*?)\n\s*"\)"', RELEASE_YML.read_text(), re.S)
    notes = [b for b in blocks if "CHANGELOG.md" in b]
    assert len(notes) == 1, (
        f"expected exactly one CHANGELOG extraction in release.yml, found {len(notes)}; "
        "this test can no longer tell what the release will publish"
    )
    script = textwrap.dedent(notes[0])
    assert "VERSION" in script, (
        "the extraction no longer reads a VERSION from the environment, so this "
        "test cannot drive it for a given version"
    )
    return script


def _extract_notes(version: str, changelog: str) -> str:
    """What the release job would publish for `version`, given that changelog."""
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "CHANGELOG.md").write_text(changelog)
        result = subprocess.run(
            [sys.executable, "-c", _notes_script()],
            cwd=tmp,
            env={**os.environ, "VERSION": version},
            capture_output=True,
            text=True,
            check=True,
        )
    return result.stdout.strip()


def _released_versions() -> set[str]:
    """Versions a release has to be able to publish notes for.

    The tags, plus the one `pyproject.toml` names, which is the version in
    flight and has no tag until the merge that creates it. VERSIONS rather than
    headings, deliberately: enumerating headings would need a regex for what a
    heading looks like, which is a fourth copy of the rule this test exists to
    deduplicate, and it would drag in `## Unreleased`, whose section is empty by
    design.
    """
    tags = subprocess.run(
        ["git", "tag"], cwd=ROOT, capture_output=True, text=True, check=False
    ).stdout.split()
    versions = {t.lstrip("v") for t in tags}
    preparing = re.search(
        r'^version = "(\d+\.\d+\.\d+)"', (ROOT / "pyproject.toml").read_text(), re.M
    )
    if preparing:
        versions.add(preparing.group(1))
    return versions


def test_every_released_version_has_notes_the_release_job_can_extract() -> None:
    """#185, and it is the failure that produced this test.

    0.4.0 was written as `## [0.4.0] - 2026-09-05`, which is what
    [Keep a Changelog] specifies and what this file's preamble says it follows.
    The release job refused, because its pattern is anchored on `^## $version`.
    Nothing was tagged and nothing reached PyPI, which is the gate working, but
    the failure landed after a merge to `main` when it could have landed here.
    """
    changelog = CHANGELOG.read_text()
    missing = [v for v in sorted(_released_versions()) if not _extract_notes(v, changelog)]
    assert not missing, (
        f"the release job would find no notes for {missing}. Its pattern is "
        "anchored on `^## <version>`, so a heading in any other shape, brackets "
        "included, publishes nothing and stops the release after the merge"
    )


def test_a_bracketed_heading_still_extracts_nothing() -> None:
    """The guardrail, and it is an assertion rather than a promise.

    The fix for #185 must make the LOCAL check stricter, never the release
    check looser. Widening what the workflow matches would let a release
    publish under a heading nobody reviewed, and a version on PyPI cannot be
    reused. This fails the day somebody relaxes the pattern to accept the
    bracketed form instead of teaching the changelog to avoid it.
    """
    assert _extract_notes("9.9.9", "## [9.9.9] - 2026-01-01\n\nnotes\n") == ""


def test_a_version_that_prefixes_another_gets_its_own_notes() -> None:
    """#188. `^## 0.4.1` matched the heading `## 0.4.10`, so a patch release
    would have published a later version's notes under its own number.

    Synthetic rather than the real changelog, because the real one must not
    have to grow a tenth patch release to keep this covered.
    """
    changelog = (
        "# Changelog\n\n"
        "## 0.4.10 - 2026-01-02\n\nnotes for four ten\n\n"
        "## 0.4.1 - 2026-01-01\n\nnotes for four one\n"
    )
    assert _extract_notes("0.4.1", changelog) == "notes for four one"
    assert _extract_notes("0.4.10", changelog) == "notes for four ten"


def test_a_version_missing_from_the_changelog_extracts_nothing() -> None:
    """The half that keeps the refusal meaningful: a release with no notes must
    find none, rather than borrowing the nearest section."""
    assert _extract_notes("0.4.1", "## 0.4.10 - 2026-01-02\n\nnotes\n") == ""


def test_the_version_is_escaped_rather_than_read_as_a_pattern() -> None:
    """#188's other half. Interpolated raw, a version's dots matched any
    character, so `## 0x4x0` satisfied a lookup for `0.4.0`."""
    assert _extract_notes("0.4.0", "## 0x4x0 - 2026-01-01\n\nnotes\n") == ""


# -- #105: the images, which are published claims about the interface -------

SCREENSHOTS = ROOT / "docs" / "screenshots"
CAPTURE = ROOT / "tests" / "e2e" / "test_screenshots.py"


def test_every_shot_the_capture_declares_is_committed() -> None:
    """A README linking a missing image shows a broken icon to a stranger.

    Derived from the capture module rather than from a list here, so adding a
    shot cannot silently skip the check that it was committed. No pixel
    comparison: that is flaky across font versions and a flaky gate is a
    disabled gate, which #105 says explicitly.
    """
    declared = set(re.findall(r'_shoot\(page, "([a-z-]+)"\)', CAPTURE.read_text()))
    assert declared, "the capture module declares no shots, so this checks nothing"
    missing = sorted(n for n in declared if not (SCREENSHOTS / f"{n}.png").exists())
    assert not missing, (
        f"declared shots with no committed image: {missing}. "
        "Run `uv run pytest -m screenshots`."
    )


def test_the_capture_never_photographs_a_real_root() -> None:
    """The first run put `/tmp/pytest-of-<username>/...` in the page header,
    because the interface displays the root it was given and the tier's own
    fixture builds that path from the account name.

    A screenshot is content this project publishes, so the root it renders has
    to be neutral by construction rather than by whoever looked at the image.
    """
    import ast

    # Parameters, not mentions. The first version read the whole file for
    # "tmp_path_factory" and failed on its own docstring, which explains why
    # that fixture is avoided. A guard that cannot tell a use from an
    # explanation of itself is one somebody deletes.
    tree = ast.parse(CAPTURE.read_text())
    borrowed = sorted(
        {
            arg.arg
            for node in ast.walk(tree)
            if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef)
            for arg in node.args.args
            if arg.arg in {"tmp_path_factory", "tmp_path", "server"}
        }
    )
    assert not borrowed, (
        f"the capture takes {borrowed}, whose root carries the account name and "
        "is rendered in the page header. Use the neutral shots_server."
    )
    assert "hitchrail-demo" in CAPTURE.read_text(), (
        "the capture must seed a neutrally named root, since the interface displays it"
    )


# -- #117: the order of the README, which is a phase exit criterion ---------

# Positional, not textual, so renaming the heading does not break the guard and
# moving it does. The heading has already been renamed once, from "Read this
# before running it" to something a person reads rather than obeys.
_RISK_HEADING = re.compile(r"^## .*costs you to run", re.M | re.I)
_INSTRUCTION_HEADINGS = ("## Run it", "## Install")

# One distinctive phrase per limitation. Whole sentences would break on an
# ordinary edit; a phrase goes missing only when the claim does.
_LIMITATIONS = {
    "the agent is unsandboxed": "dangerously-skip-permissions",
    "the token buys keystrokes": "typed into",
    "a detached agent cannot be ended": "cannot end",
    "cleartext on plain HTTP": "cleartext",
}


def test_the_readme_states_the_risk_before_the_instructions() -> None:
    """Phase 8's objective puts the security section first, after learning what
    the tool does. It sat below Run it, Install and Working on it, so a reader
    met three sets of instructions before being told the tool spawns agents
    with permissions skipped.

    Somebody who reads "Run it" and stops has not been told what it costs them.
    Somebody who reads this and stops has lost nothing.
    """
    readme = README.read_text()
    risk = _RISK_HEADING.search(readme)
    assert risk, "the README has no section about what running this costs"
    for heading in _INSTRUCTION_HEADINGS:
        assert heading in readme, f"the README lost {heading!r}"
        assert risk.start() < readme.index(heading), (
            f"{heading!r} comes before the risk section. A reader who stops "
            "early has been told how, and not what it costs."
        )


def test_the_readme_still_states_every_limitation() -> None:
    """A section promoted to the top is one somebody will later want to soften,
    because it is the first thing a visitor sees. This is what stops that being
    invisible: the wording is free, the claims are not."""
    readme = README.read_text().lower()
    missing = [label for label, needle in _LIMITATIONS.items() if needle not in readme]
    assert not missing, (
        "the README no longer states: " + ", ".join(missing) + ". These are the "
        "limitations SECURITY.md repeats, so dropping one here makes two files wrong."
    )


# -- #110: the unit template and the phone access document ------------------
#
# Both deliverables are text that instructs an operator, and text that
# instructs an operator rots exactly like the prose above it. A unit naming a
# flag the CLI removed is a broken install, and the wildcard sentence is the
# one that must never drift back in.

UNIT = ROOT / "packaging" / "hitchrail.service"
PHONE_DOC = ROOT / "docs" / "guides" / "phone-access.md"

# The three route headings, best first. Matched as headings rather than as
# prose so a rewording of the body cannot silently reorder the argument.
_OVERLAY_HEADING = "## 1. An overlay network"
_NAMED_HEADING = "## 2. A named LAN address"
_NEVER_HEADING = "## 3. Never the wildcard"


def _lines_with_offsets(text: str) -> Iterator[tuple[int, str]]:
    offset = 0
    for line in text.splitlines(keepends=True):
        yield offset, line
        offset += len(line)


def _exec_start_argv() -> list[str]:
    """The ExecStart line, as the argument list systemd will run.

    `%h` and friends are systemd specifiers it expands at start. They survive
    `shlex.split` as ordinary characters, and `--root` takes any path, so the
    parser sees a value it accepts without this test needing to know what the
    operator's home is.
    """
    line = next(
        raw.split("=", 1)[1]
        for raw in UNIT.read_text().splitlines()
        if raw.startswith("ExecStart=")
    )
    return shlex.split(line)


def test_the_unit_template_names_flags_the_cli_accepts() -> None:
    """A unit documenting a flag the CLI removed is a broken install, and it
    fails at boot on a machine nobody is watching, which is the whole posture
    this ticket introduces.

    The argv is fed to the real parser rather than compared against a list of
    flag names. A name check passes when a flag stops taking a value.
    """
    argv = _exec_start_argv()
    assert argv, "the unit template has no ExecStart"
    assert Path(argv[0]).name == "hitchrail", (
        f"ExecStart runs {argv[0]!r}, which is not hitchrail"
    )
    parse_args(argv[1:])  # SystemExit here is the failure


def _unit_sections() -> dict[str, list[str]]:
    """The unit's directives, by section, comments dropped.

    Read as DIRECTIVES rather than as text. A substring check over the file
    matches the comment above a directive that explains why the other value is
    wrong, so the guard fails on its own explanation and the only way to make
    it pass is to delete the reasoning. Same trap as the private name hook.
    """
    sections: dict[str, list[str]] = {}
    current = ""
    for raw in UNIT.read_text().splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1]
            sections.setdefault(current, [])
        elif line and not line.startswith("#"):
            sections.setdefault(current, []).append(line)
    return sections


def test_the_unit_never_restarts_a_refusal_forever() -> None:
    """#170, and this test is the reason that defect survived a phase.

    It asserted `directives == ["Restart=on-failure"]`, which is exactly the
    state that produces the loop it is named for. Its docstring's reasoning was
    right and applied to the value it was pinning: `on-failure` restarts on ANY
    non zero exit, a configuration refusal exits 2, and an `EnvironmentFile`
    with a blank token produced 37 restarts and 38 copies of one message.

    **It also could not have noticed the fix**, which is the sharper half:
    `"RestartPreventExitStatus="` does not `startswith("Restart=")`, the `=`
    falling at index 7 against the `P`. So the old assertion stays green either
    way, and a new test beside it would have left one certifying nothing.

    The list assertion is what made it blind: it pinned the directives present
    and could not see the one that was missing.
    """
    service = _unit_sections()["Service"]
    assert "Restart=always" not in service, (
        "every deliberate refusal would become a boot loop that buries its own "
        "explanation in the journal"
    )
    assert "Restart=on-failure" in service
    assert "RestartPreventExitStatus=2" in service, (
        "on-failure alone restarts a configuration refusal forever, which is the "
        "loop this test is named for"
    )


def test_the_unit_carries_a_path_that_can_find_the_agent() -> None:
    """#195, and the failure it prevents is invisible until a reboot.

    `loginctl enable-linger` starts the user manager BEFORE any login, when its
    PATH is systemd's fallback `/usr/local/bin:/usr/bin:/bin`. The agent lives
    in `~/.local/bin`, so preflight cannot resolve it, the unit refuses with
    exit 2, and it correctly stays stopped. Measured on a real boot.

    It hides because every interactive test of the unit happens AFTER a login
    has pushed the full PATH into the manager, so the environment looks healthy
    while the boot environment never was.

    Asserted on the DIRECTIVE rather than on the file, through
    `_unit_sections()`, and the reason is sharper than the usual one. A
    substring search for `%h/.local/bin` over this file passes with no PATH
    line at all, because `ExecStart=%h/.local/bin/hitchrail` already carries
    that literal. Such a guard would have been green against the exact unit
    that died at boot.
    """
    paths = [
        directive.split("=", 1)[1]
        for directive in _unit_sections()["Service"]
        if directive.startswith("Environment=PATH=")
    ]
    assert paths, (
        "the unit sets no PATH, so a lingering install cannot find its agent at "
        "boot and is dead until somebody starts it by hand"
    )
    assert "%h/.local/bin" in paths[0], (
        f"the PATH is {paths[0]!r}, which does not carry the user's local bin "
        "directory, which is where the agent binary is installed"
    )
    assert "%h" in paths[0] and "/home/" not in paths[0], (
        "the template hardcodes a home directory, so it is one machine's unit "
        "rather than a template"
    )


def test_the_unit_prevents_the_exit_code_the_cli_actually_returns() -> None:
    """The unit's number and the program's, checked against each other.

    A unit saying 2 while the CLI returns something else is two copies of one
    rule, drifting, which is the shape #185 hit on the release path the same
    evening. So the number is not restated here: it is read out of the unit and
    driven through a real refusal.

    A root that is not a directory, because it refuses in `main` before
    anything binds. `argparse` reaches the same 2 by its own route for a usage
    error, which is what a typo in the unit's `ExecStart` produces, and that is
    why the value is not free to choose.
    """
    from hitchrail.cli import main

    prevented = {
        int(value)
        for line in _unit_sections()["Service"]
        if line.startswith("RestartPreventExitStatus=")
        for value in line.split("=", 1)[1].split()
    }
    assert prevented, "the unit prevents no exit status, so every refusal loops"

    with tempfile.TemporaryDirectory() as tmp:
        code = main(["--root", f"main={Path(tmp) / 'not-a-directory'}"])

    assert code in prevented, (
        f"the CLI refuses with exit {code} and the unit only prevents "
        f"{sorted(prevented)}, so that refusal restarts every {UNIT.name} tick"
    )


def test_the_units_start_limit_is_where_systemd_reads_it() -> None:
    """The backstop for everything `RestartPreventExitStatus` cannot name.

    That directive bounds ONE status. An unhandled exception exits 1 and would
    loop by the same mechanism, so the limit is what makes any loop terminate.

    **It has to be in `[Unit]`.** These moved out of `[Service]` at systemd 230
    and are silently ignored there now, which is the worst failure available to
    a limit: it reads as configured and does nothing.

    The window is checked too, because the default one cannot fire here.
    systemd allows five starts in ten seconds and `RestartSec` spaces attempts
    further apart than that, which is why 37 restarts in a row were never rate
    limited.
    """
    sections = _unit_sections()
    limits = [d for d in sections["Unit"] if d.startswith("StartLimit")]
    assert limits, "the unit has no start limit, so a loop this cannot name runs forever"
    assert not [d for d in sections["Service"] if d.startswith("StartLimit")], (
        "a StartLimit directive in [Service] is ignored since systemd 230"
    )

    def _value(directives: list[str], name: str) -> int | None:
        """The EFFECTIVE value of `name`, or `None` if absent or unparseable.

        **Last match, not first, because systemd is last-assignment-wins.** A
        hand-edited unit acquires a bad value by having a line APPENDED, not by
        having one rewritten, and reading the first match let exactly that pass:
        `StartLimitIntervalSec=0` added under a good pair satisfied every
        assertion here while systemd saw rate limiting switched off.

        **`None` rather than a raise on a value this cannot parse.** systemd
        accepts `30s`, `2min` and `infinity`; a bare `int()` turns each into a
        `ValueError` traceback where the caller needed the sentence. That is the
        same crash-instead-of-failure this helper was written to remove, and it
        matters: `RestartSec=1min` with burst 12 in a 120s window can never
        fire, which is the defect the last assertion here exists to catch.

        Parsing systemd's time spans properly is not this test's job. Refusing
        to guess is.
        """
        found = [d.split("=", 1)[1].strip() for d in directives if d.startswith(name)]
        if not found:
            return None
        effective = found[-1]
        return int(effective) if effective.isdigit() else None

    # A repeated directive is how this goes wrong in practice, and systemd takes
    # the LAST one. Checked separately from the values so the message says "you
    # have two of these" rather than silently reporting whichever survived.
    keys = [d.split("=", 1)[0] for d in limits]
    repeated = sorted({key for key in keys if keys.count(key) > 1})
    assert not repeated, (
        f"{repeated} appears more than once, and systemd takes the LAST "
        f"assignment, so what a reader sees here and what systemd does differ"
    )
    window = _value(limits, "StartLimitIntervalSec")
    burst = _value(limits, "StartLimitBurst")
    gap = _value(sections["Service"], "RestartSec=")
    assert window is not None and burst is not None and gap is not None, (
        f"a limit needs StartLimitIntervalSec, StartLimitBurst and RestartSec to "
        f"mean anything, and this unit has window={window} burst={burst} gap={gap}. "
        f"`None` means absent OR a value this test will not parse, such as `30s` "
        f"or `infinity`; write plain seconds so the check stays honest"
    )
    # The presence check above is not enough on its own: `StartLimitIntervalSec=0`
    # IS a StartLimit directive, so it passes while naming the exact condition it
    # failed to detect. Zero disables rate limiting outright.
    assert window > 0, (
        "StartLimitIntervalSec=0 disables rate limiting, so nothing bounds the "
        "exit 1 loop this limit exists for, and the unit sits in `activating "
        "(auto-restart)` forever instead of reaching `failed`, which means it "
        "never appears in `systemctl --user --failed` again"
    )
    assert burst * gap < window, (
        f"{burst} restarts {gap}s apart span {burst * gap}s, which is outside the "
        f"{window}s window, so the limit can never fire and the loop is unbounded"
    )
    # #201. The budget still has to outlast a real network bring up, and the
    # margin is thinner than it looks.
    #
    # **What #201 withdrew is the CAUSE, not this floor.** It used to say here
    # that a race with `After=network.target` killed the service. It did not:
    # every observed outage was missing hardware, and `After=network.target` is
    # inert in a user unit anyway, because the user manager has no such unit.
    #
    # The race is real and tight. Boot -3 of 2026-09-06 had the adapter
    # connected, took its DHCP lease 15s into the boot, and this unit's first
    # start came 7s later. Seven seconds of margin is the reason for a floor.
    assert burst * gap >= 60, (
        f"{burst} restarts {gap}s apart give up after {burst * gap}s. A boot that "
        f"has to acquire a DHCP lease took 15s to do it and this unit won by 7s, "
        f"so a named bind needs more margin than a couple of attempts. See #201."
    )


def test_the_start_limit_is_not_what_keeps_a_refusal_stopped() -> None:
    """#201 widened the start limit, and this is the property that made that
    safe rather than a weakening of #170.

    A deliberate refusal exits 2, and `RestartPreventExitStatus=2` means it is
    never restarted at all, so it never spends an attempt from the budget. The
    budget bounds an unhandled exception (exit 1) and a bind failure (exit 3).

    If the prevented status is ever dropped, widening the burst turns every
    refusal into a longer boot loop, which is exactly what #170 measured at 37
    restarts. The two directives are therefore asserted together rather than
    apart, because it is the PAIR that is correct.
    """
    sections = _unit_sections()
    prevented = [d for d in sections["Service"] if d.startswith("RestartPreventExitStatus=")]
    assert prevented == ["RestartPreventExitStatus=2"], (
        "the unit no longer prevents restarting exit 2, so a deliberate "
        "refusal now consumes the start limit and loops for as long as the "
        "budget allows. #201 widened that budget on the strength of this line"
    )
    assert "Restart=on-failure" in sections["Service"], (
        "Restart=always restarts a refusal whatever its exit code, which is "
        "the boot loop #170 measured"
    )


def test_the_phone_doc_does_not_recommend_a_wildcard_bind() -> None:
    """The one sentence that must never drift back in.

    A wildcard is allowed to APPEAR: the document's third section is about why
    not to use it, and a prohibition that cannot name the thing it forbids is
    useless. What is checked is that every mention sits under the heading that
    forbids it, which is the same structural read the private name hook needed
    for the same reason.
    """
    text = PHONE_DOC.read_text()
    forbidding = text.index(_NEVER_HEADING)
    stray = [
        line
        for offset, line in _lines_with_offsets(text)
        if "0.0.0.0" in line and offset < forbidding
    ]
    assert not stray, (
        "the phone access document mentions a wildcard bind before the section "
        f"that forbids it: {stray}"
    )


def test_the_phone_doc_leads_with_the_overlay_route() -> None:
    """Ordered best first, and the order is the argument. A LAN bind stays
    correct only while the operator stays on a network they trust, and nothing
    warns them when that stops being true."""
    text = PHONE_DOC.read_text()
    overlay = text.index(_OVERLAY_HEADING)
    named = text.index(_NAMED_HEADING)
    never = text.index(_NEVER_HEADING)
    assert overlay < named < never, (
        "the routes are out of order. Best first is the whole point: a reader "
        "who stops after the first heading must have stopped on the safe one."
    )


def test_the_phone_doc_requires_both_allowlist_flags_for_a_proxy() -> None:
    """`--allow-origin`'s help text already names the proxied case, and it is
    unobvious that both flags are needed. A doc that shows one of them sends
    the operator to a refusal they will read as a bug."""
    overlay = PHONE_DOC.read_text().split(_NAMED_HEADING)[0]
    for flag in ("--allow-host", "--allow-origin"):
        assert flag in overlay, f"the overlay route does not mention {flag}"


def test_the_keypad_offers_exactly_the_keys_the_server_will_send() -> None:
    """#204. `app.js` and `claude_ipc.py` name the same keys, or a button lies.

    Two lists rather than one because they are in two languages, and the copy
    in the browser is an AFFORDANCE while the copy on the server is the GUARD.
    That asymmetry is deliberate and is why this test exists rather than a
    generated file: a key added only to the browser is a button that does
    nothing, and a key added only to the server is a widening nobody reviewed
    against the interface.

    Reads the literal out of `app.js` as text, the way this module reads every
    other cross-file claim, because parsing the module would need a JS runtime
    to assert something a regex can see.
    """
    js = (SRC / "web" / "app.js").read_text(encoding="utf-8")
    block = re.search(r"export const ANSWER_KEYS = \[(.*?)\];", js, re.DOTALL)
    assert block, "app.js no longer declares ANSWER_KEYS where this test can read it"
    in_browser = set(re.findall(r'"([^"]+)"', block.group(1)))
    assert in_browser == set(claude_ipc.ANSWER_KEYS), (
        f"the keypad offers {sorted(in_browser)} and the server will send "
        f"{sorted(claude_ipc.ANSWER_KEYS)}, so a button either does nothing or "
        f"a key reachable on the server is not reviewed against the interface"
    )


def test_no_free_text_field_reaches_the_answer_path() -> None:
    """#204's line, asserted rather than trusted to review.

    The whole safety argument is that the operator presses a key named by words
    they read. An `<input>` built inside the answer pad would carry an
    instruction the pane never offered, which is the product the roadmap
    defers, and it would arrive as a small, plausible diff.
    """
    js = (SRC / "web" / "app.js").read_text(encoding="utf-8")
    pad = re.search(r"function answerPad\(.*?\n}", js, re.DOTALL)
    assert pad, "answerPad is no longer where this test can read it"
    assert 'createElement("input")' not in pad.group(0), (
        "answerPad builds a text input, which turns one keypress from a fixed "
        "set into arbitrary input to a shell. See #204."
    )


def test_no_e2e_test_hardcodes_the_run_prefix() -> None:
    """#177. The prefix is per RUN now, so a literal in a test body is a bug.

    Two runs of this suite on one machine used to contaminate each other. The
    tier isolates a private tmux server and a temporary root, and cannot isolate
    the third thing derivation reads: `ps -eww` is machine wide by design. With
    a constant prefix, one run's shim agent carried the same argv tail as
    another's, and a session was attributed to the wrong run. Observed as 13
    plausible, red, unrelated e2e failures.

    `E2E_PREFIX` now carries the pid, so a hardcoded `hrx-` no longer matches
    what the harness creates and the test fails for a reason that looks nothing
    like the cause. This catches it at the literal instead.

    **The conftest docstring claimed this guard already existed**, naming an
    `e2e_names` that was never written. That is the same defect this file exists
    to catch, in the file describing the tier, so it is worth having the guard
    actually be here.
    """
    e2e = ROOT / "tests" / "e2e"
    offenders = {
        path.name: [
            i
            for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
            if "hrx-" in line
        ]
        for path in sorted(e2e.glob("test_*.py"))
    }
    offenders = {name: lines for name, lines in offenders.items() if lines}
    assert not offenders, (
        f"these e2e tests hardcode the run prefix: {offenders}. It carries the "
        f"pid now, so a literal cannot match what the harness creates. Use "
        f"`server.project(name)` for an identifier or `e2e_name(name)` for a "
        f"folder, which is the one place the prefix lives. See #177."
    )
