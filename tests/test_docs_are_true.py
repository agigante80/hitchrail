"""The documents make checkable claims, so check them.

Every guard this project has protects the SOURCE: five gates, an import
contract, module size caps, a tier partition, a template lockstep. Nothing
protected the prose, and the prose is what an outside reader meets first.

The cost was not hypothetical. `.claude/CLAUDE.md` told every reader that
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
CLAUDE_MD = ROOT / ".claude" / "CLAUDE.md"

# `.claude/` is not published. It holds the project rules, agents and skills,
# and it named this machine and its projects until that was scrubbed, so a
# public repository is the wrong home for it.
#
# **That costs this file half its reach, and the cost is stated rather than
# hidden.** These guards run in a developer's checkout and skip on a clone, so
# CI checks the roadmap and not CLAUDE.md. A guard that skips silently is worse
# than no guard, which is why the skip carries this reason and why #106 exists
# to move the conventions somewhere tracked.
_NO_CLAUDE_MD = pytest.mark.skipif(
    not CLAUDE_MD.exists(),
    reason=".claude/ is unpublished, so this runs only where the file is",
)
ROADMAP = ROOT / "docs" / "roadmap.md"
README = ROOT / "README.md"

# Anything under this is a stub. Every real module here is far larger, and the
# four that were wrongly described as placeholders are 150 lines and up.
PLACEHOLDER_LINES = 5


def _modules() -> dict[str, int]:
    return {p.name: len(p.read_text().splitlines()) for p in SRC.glob("*.py")}


@_NO_CLAUDE_MD
@pytest.mark.parametrize("doc", [CLAUDE_MD, ROADMAP], ids=lambda p: p.name)
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


@_NO_CLAUDE_MD
@pytest.mark.parametrize("doc", [CLAUDE_MD, ROADMAP, README], ids=lambda p: p.name)
def test_no_document_hardcodes_a_test_count(doc: Path) -> None:
    """ "519 tests" was true once. A number that decays silently is worse than
    no number, because it reads as precision."""
    text = doc.read_text()
    stale = re.findall(r"\b(\d{3,5})\s+tests\b", text)
    assert not stale, (
        f"{doc.name} hardcodes a test count {stale}, which will be wrong within "
        "a phase. Say what is covered, not how many there are."
    )


@_NO_CLAUDE_MD
def test_every_module_named_in_claude_md_exists() -> None:
    """The architecture block lists the modules. A rename that misses it leaves
    a map pointing at a road that is not there."""
    block = CLAUDE_MD.read_text()
    named = set(re.findall(r"^\s{2}(\w+\.py)\s", block, re.M))
    missing = {n for n in named if not (SRC / n).exists()}
    assert not missing, f"CLAUDE.md names modules that do not exist: {sorted(missing)}"


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


def _codes_the_spec_documents() -> set[str]:
    text = SPEC.read_text()
    section = text[text.index("## 6. HTTP interface") : text.index("## 7. Interface design")]
    return set(re.findall(r"^\| `([a-z_]+)` \| \d+ \|", section, re.M))


def test_the_spec_documents_every_code_the_server_can_return() -> None:
    """The table listed six of fifteen, and a reader cannot tell a short list
    from a complete one. `machine_unreadable` was the costly omission: a client
    that renders its 503 as a failed request shows an empty list where the
    truth is that the machine cannot be read."""
    missing = _codes_the_server_returns() - _codes_the_spec_documents()
    assert not missing, (
        f"the server returns codes the design does not document: {sorted(missing)}. "
        "Add them to section 6's table."
    )


def test_the_spec_documents_no_code_the_server_cannot_return() -> None:
    """The other direction, and it is not symmetry for its own sake. A spec
    describing a refusal that cannot happen sends a client author writing a
    dead branch, which is the same class of harm as omitting a live one."""
    stale = _codes_the_spec_documents() - _codes_the_server_returns()
    assert not stale, (
        f"the design documents codes the server cannot return: {sorted(stale)}. "
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
