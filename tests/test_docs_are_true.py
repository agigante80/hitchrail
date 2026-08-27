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
ROADMAP = ROOT / "docs" / "roadmap.md"

# Anything under this is a stub. Every real module here is far larger, and the
# four that were wrongly described as placeholders are 150 lines and up.
PLACEHOLDER_LINES = 5


def _modules() -> dict[str, int]:
    return {p.name: len(p.read_text().splitlines()) for p in SRC.glob("*.py")}


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


@pytest.mark.parametrize("doc", [CLAUDE_MD, ROADMAP], ids=lambda p: p.name)
def test_no_document_hardcodes_a_test_count(doc: Path) -> None:
    """ "519 tests" was true once. A number that decays silently is worse than
    no number, because it reads as precision."""
    text = doc.read_text()
    stale = re.findall(r"\b(\d{3,5})\s+tests\b", text)
    assert not stale, (
        f"{doc.name} hardcodes a test count {stale}, which will be wrong within "
        "a phase. Say what is covered, not how many there are."
    )


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
