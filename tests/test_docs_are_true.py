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

import re
from pathlib import Path

import pytest

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


def test_every_module_named_in_agents_md_exists() -> None:
    """The architecture block lists the modules. A rename that misses it leaves
    a map pointing at a road that is not there."""
    block = AGENTS_MD.read_text()
    named = set(re.findall(r"^\s{2}(\w+\.py)\s", block, re.M))
    missing = {n for n in named if not (SRC / n).exists()}
    assert not missing, f"AGENTS.md names modules that do not exist: {sorted(missing)}"


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
    from hitchrail.config import Config
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
        for m in middleware_stack(Config(root=tmp_path))
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
    unreleased = [h for h in headings if h not in normalised]
    assert not unreleased, f"changelog versions with no tag: {unreleased}"


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
