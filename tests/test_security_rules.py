"""Does editing any mutated module load the security rules, and does the parser
that decides it refuse every shape it would otherwise read generously?

Skips where `.claude/rules/` is absent: a clone, CI, a worktree.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from mutation_support import _REPO, _mutmut_config
from support import PIDFD_MODULE, STATE_MODULE

# -- #198: the rules that load for the modules on the spawn path --------------

_SECURITY_RULE = _REPO / ".claude" / "rules" / "security.md"


def _security_rule_paths(rule: Path | None = None) -> list[str]:
    """The `paths:` list from the rule file's frontmatter, read as structure.

    Never a substring search for a module name. The frontmatter is located by
    its delimiters, `paths:` by being a top level key inside it, and its entries
    by being the indented list items that follow. A grep would match this
    docstring and every prose mention of a module below it, which is the trap
    this repository has hit three times and `test_every_mutated_module_can_be_`
    `imported_from_the_mutants_tree` already names.

    Takes the file rather than closing over it so the refusals below can be
    driven against synthetic frontmatter. Round 1 of review found the guard's
    four refusals had no test at all: they had been verified once, by hand, on
    the real file, which says nothing about whether a later edit leaves them
    able to fail.
    """
    rule = rule or _SECURITY_RULE
    text = rule.read_text()
    block = re.match(r"\A---\n(?P<front>.*?)\n---\n", text, re.S)
    assert block, (
        f"{rule} has no frontmatter block, so the path scoped rules load "
        "for nothing at all. A rewritten header must fail here rather than leave "
        "this guard comparing against an empty list."
    )

    found: list[str] = []
    inside = False
    seen_key = False
    for line in block.group("front").split("\n"):
        key = re.match(r"^paths:(?P<tail>.*)$", line)
        if key:
            # **A second `paths:` key is refused rather than merged.** The
            # parser used to return the union of both blocks, and a union is a
            # SUPERSET of what loads: YAML is last wins, so an entry from the
            # first block would satisfy this guard while the rule file never
            # loaded for it. That is the direction in which this whole check
            # can pass falsely, which is why it raises instead of being read
            # generously.
            #
            # **The key is matched with any tail, and round 2 of review is why.**
            # The first version required the key alone on its line, so a second
            # key written flow style (`paths: ["a.py"]`) or with a trailing
            # comment fell through to the `^\S` branch below, ended the list
            # silently, and left exactly the union this assertion exists to
            # refuse. Matching the name and rejecting the tail closes both.
            assert not seen_key, (
                f"{rule} has more than one top level `paths:` key. YAML keeps the "
                "last, so reading both would report modules as covered that no "
                "rule loads for."
            )
            seen_key = True
            tail = key.group("tail").strip()
            if tail and not tail.startswith("#"):
                raise AssertionError(
                    f"{rule}: `paths:` carries {tail!r} on its own line. This parser "
                    "reads the block form only, and reading a flow style list wrongly "
                    "is how a module reports as covered by a rule that never loads."
                )
            inside = True
            continue
        if not inside:
            continue
        if not line.strip() or re.match(r"^\s*#", line):
            # A comment or a blank line inside the list is legal YAML and says
            # WHY an entry is there, which is the most useful thing in the file.
            # The first version of this parser ended the list at the first one,
            # silently dropping the two entries below it, and the run that
            # caught it was the one that added a comment. A guard that reads
            # structure has to read the whole structure.
            continue
        entry = re.match(r'^\s+-\s*"(?P<path>[^"]+)"\s*$', line)
        if entry:
            found.append(entry.group("path"))
            continue
        if re.match(r"^-", line):
            # A sequence item at column zero under a mapping key is legal YAML
            # and the `^\S` branch below used to drop it, and everything after
            # it, in silence. Round 2 found it: the parser's own message says an
            # entry read as nothing is a module it would stop checking without
            # saying so, and this was that shape inside the parser saying it.
            raise AssertionError(
                f"{rule}: {line!r} is a list entry at column zero. It is legal YAML "
                "and this parser does not read it, so it must refuse rather than "
                "truncate the list here and report the rest as covered."
            )
        if re.match(r"^\S", line):
            inside = False
            continue
        raise AssertionError(
            f"{rule}: this parser cannot read {line!r} as a `paths:` entry. "
            "Failing rather than skipping it: an entry read as nothing is a module "
            "this guard would then report as missing, or worse, one it would stop "
            "checking without saying so."
        )

    assert found, (
        f"{rule} has frontmatter but no `paths:` entries this parser can "
        "read. The list is the record of which modules load the security rules, and "
        "a guard that cannot find it must fail rather than pass on nothing."
    )
    return found


def _stale_rule_entries(listed: list[str]) -> list[str]:
    """The entries naming no file, which the subset check cannot see.

    `headers.py`, `server.py` and `cli.py` are in the rule and deliberately not
    in `[tool.mutmut] source_paths`, so nothing in the subset direction checks
    them at all: rename or split one and its entry matches no file, the rules
    stop loading for it, and every guard in this repository stays green. That is
    #126's asymmetry reappearing inside the guard written to answer it.

    A function rather than a comprehension inline, because round 2 of review
    pointed out the comprehension could only ever run against the real tree, in
    its passing direction, on the one machine where `.claude/` exists. Here it
    can be driven with a list.
    """
    return [entry for entry in listed if not (_REPO / entry).exists()]


def test_every_mutated_module_loads_the_security_rules_when_it_is_edited() -> None:
    """#198. `roots.py` was created the day after the rule file was last edited,
    so nothing loaded when an agent opened the module holding the injectivity
    argument that keeps two projects off one tmux session.

    **The expectation is derived from a list somebody already maintains.**
    `[tool.mutmut] source_paths` is curated as "the modules between a web page
    and a shell", and #130 argued `roots.py` onto it with a measurement. Asking
    that the security rule covers every module the project already mutates costs
    no second list to keep.

    **What this does NOT claim, and the limit is the point.** mutmut's list is a
    LOWER BOUND, not the definition of the set. `headers.py`, `server.py` and
    `cli.py` are in the rule and are deliberately not mutated, so the two lists
    are different sizes on purpose and neither contains the other. This catches
    a module the project has already classified as being on the spawn path. It
    says nothing about one nobody has classified yet, and #126's lesson is that
    the unclassified direction is where things actually go missing.

    **It skips rather than fails without `.claude/rules/`**, which is
    gitignored, so this is not a gate: it runs on the machine where the list is
    edited and on no CI leg. That is the honest cost of deriving the check from
    a file the repository does not carry. The directory asked about is
    `rules/` rather than `.claude/` itself, which used to matter because
    `.claude/CLAUDE.md` was tracked and the parent therefore existed in every
    clone. Since 2026-09-16 nothing under `.claude/` is published, so both
    spellings skip everywhere but a working checkout; `rules/` is kept
    because it is the directory this check is actually about.

    **It is deliberately NOT in `[tool.mutmut] pytest_add_cli_args`, against the
    ticket's own instruction.** #198 required a `--deselect` entry beside the
    four repository shape guards, reasoning that a test reading `.claude/` fails
    under `mutmut run` because `also_copy` never copies it. The first half is
    right and the conclusion is not: `also_copy` carries `src/hitchrail/*` and
    `tests`, so in the mutants tree this file resolves a `_REPO` with no
    `.claude/` in it and the skip below is what runs. Review round 1 verified
    that in the tree rather than by inference: a generated `mutants/` was run
    with mutmut's own selection and reported `692 passed, 1 skipped`, the skip
    being this test. A deselect entry would have claimed a breakage that does
    not happen and hidden the guard from the one suite where somebody might
    notice it had stopped running.

    **The skip is on the DIRECTORY, and a missing file is a failure.** They are
    not the same condition, and conflating them is how this guard would have
    died quietly: `.claude/rules/` absent is a checkout that cannot carry the
    rule, while `.claude/rules/` present without the rule file is the rule having been
    renamed, moved into a subdirectory, or deleted, which is #198 recurring with
    the guard green. Review round 1 produced exactly that state and got a skip
    whose stated reason was false.
    """
    if not _SECURITY_RULE.parent.exists():
        pytest.skip("`.claude/rules/` is not in this checkout (it is gitignored)")

    assert _SECURITY_RULE.exists(), (
        f"`.claude/rules/` is here but {_SECURITY_RULE} is not, so this guard has stopped "
        "checking rather than been skipped. Restore the file, or move this constant "
        "to wherever the path scoped security rules now live."
    )

    listed = _security_rule_paths()
    missing = [p for p in _mutmut_config()["source_paths"] if p not in set(listed)]

    assert not missing, (
        "the security rules do not load for "
        + ", ".join(missing)
        + ". [tool.mutmut] source_paths in pyproject.toml treats each as a module "
        f"between a web page and a shell; {_SECURITY_RULE}'s `paths:` list decides "
        "which modules load those rules when an agent edits them, and it omits these."
    )

    gone = _stale_rule_entries(listed)
    assert not gone, (
        f"{_SECURITY_RULE} names " + ", ".join(gone) + ", which do not exist. An entry "
        "pointing at nothing loads no rules for anything, and it looks identical to a "
        "module that is covered."
    )


def test_the_module_holding_the_pidfd_path_loads_the_security_rules() -> None:
    """#274. The one destructive path not scoped by the tmux prefix sits between
    a web page and a shell whichever file holds it, so the rules load for that
    file by name. Keyed on `support.PIDFD_MODULE`, which the AST guard in
    `test_source_guards.py` holds to the code, so a move that forgets this
    list fails here rather than passing over the new file."""
    if not _SECURITY_RULE.parent.exists():
        pytest.skip("`.claude/rules/` is not in this checkout (it is gitignored)")
    assert f"src/hitchrail/{PIDFD_MODULE}" in _security_rule_paths(), (
        f"{_SECURITY_RULE} does not load for {PIDFD_MODULE}, which holds the pidfd path"
    )


def test_the_module_holding_the_state_file_loads_the_security_rules() -> None:
    """#443. The state file hides roots and its directory check decides whether
    a hide is trusted, so the rules load for whichever file writes it. Keyed on
    `support.STATE_MODULE`, which the AST guard in `test_source_guards.py`
    holds to the code."""
    if not _SECURITY_RULE.parent.exists():
        pytest.skip("`.claude/rules/` is not in this checkout (it is gitignored)")
    assert f"src/hitchrail/{STATE_MODULE}" in _security_rule_paths(), (
        f"{_SECURITY_RULE} does not load for {STATE_MODULE}, which holds the state file"
    )


def test_the_module_holding_the_state_file_is_mutated() -> None:
    """#443. The same module, by the sweep's own list: a mutant of the
    directory check must be scored wherever the check moves to."""
    assert f"src/hitchrail/{STATE_MODULE}" in _mutmut_config()["source_paths"]


# The refusals above, exercised. Round 1 of review found them written and
# unasserted: verified once by hand against the real file, which says nothing
# about whether a later edit leaves them able to fail. Each case below is a
# shape the parser must NOT read generously, because every one of them ends
# with a module whose security rules silently stop loading.


def _rule_file(tmp_path: Path, frontmatter: str) -> Path:
    rule = tmp_path / "security.md"
    rule.write_text(f"---\n{frontmatter}\n---\n\n# You are editing something\n")
    return rule


def test_the_rule_parser_reads_entries_through_comments_and_blank_lines(tmp_path: Path) -> None:
    """The regression that shipped inside this guard's own first version.

    It ended the list at the first YAML comment and silently dropped the two
    entries below it. What caught it was adding a comment to explain the fix,
    which is luck rather than a check.
    """
    rule = _rule_file(
        tmp_path,
        'paths:\n  - "src/a.py"\n  # why b is here\n\n  - "src/b.py"',
    )
    assert _security_rule_paths(rule) == ["src/a.py", "src/b.py"]


def test_the_rule_parser_refuses_a_file_with_no_frontmatter(tmp_path: Path) -> None:
    rule = tmp_path / "security.md"
    rule.write_text("# You are editing something\n\npaths are elsewhere now\n")
    with pytest.raises(AssertionError, match="no frontmatter block"):
        _security_rule_paths(rule)


def test_the_rule_parser_refuses_frontmatter_with_no_paths_key(tmp_path: Path) -> None:
    """A renamed key must not read as an empty list. An empty list makes the
    subset check vacuously true, so the guard would pass while nothing loads."""
    rule = _rule_file(tmp_path, 'globs:\n  - "src/a.py"')
    with pytest.raises(AssertionError, match="no `paths:` entries"):
        _security_rule_paths(rule)


def test_the_rule_parser_refuses_an_entry_it_cannot_read(tmp_path: Path) -> None:
    """An unquoted scalar is legal YAML and is not read here. Failing loudly is
    the point: an entry read as nothing is a module the guard stops checking."""
    rule = _rule_file(tmp_path, 'paths:\n  - "src/a.py"\n  - src/b.py')
    with pytest.raises(AssertionError, match="cannot read"):
        _security_rule_paths(rule)


def test_the_rule_parser_refuses_a_second_paths_key(tmp_path: Path) -> None:
    """The one shape that can pass FALSELY. Reading both blocks returns their
    union, and YAML keeps only the last, so an entry from the first block would
    report a module as covered by a rule that never loads for it."""
    rule = _rule_file(tmp_path, 'paths:\n  - "src/a.py"\nother: 1\npaths:\n  - "src/b.py"')
    with pytest.raises(AssertionError, match="more than one top level"):
        _security_rule_paths(rule)


def test_the_rule_parser_returns_entries_verbatim_for_the_caller_to_resolve(
    tmp_path: Path,
) -> None:
    """The parser must not normalise or drop a path that names no file: the
    existence check belongs to `_stale_rule_entries`, which is tested
    separately. This asserts only the parser's half, which is that it hands the
    entry on unchanged rather than quietly filtering it."""
    rule = _rule_file(tmp_path, 'paths:\n  - "src/hitchrail/gone.py"')
    assert _security_rule_paths(rule) == ["src/hitchrail/gone.py"]
    assert not (_REPO / "src/hitchrail/gone.py").exists()


def test_a_rule_entry_naming_no_file_is_reported_as_stale() -> None:
    """The direction the subset check cannot see, driven by a list rather than
    by the repository. Against the real tree this returns nothing, which is a
    guard that has never been observed doing its job."""
    assert _stale_rule_entries(["src/hitchrail/config.py"]) == []
    assert _stale_rule_entries(
        ["src/hitchrail/config.py", "src/hitchrail/renamed_away.py"]
    ) == ["src/hitchrail/renamed_away.py"]


def test_the_rule_parser_refuses_a_flow_style_second_paths_key(tmp_path: Path) -> None:
    """Round 2. The block-form-only key match let this through: the second key
    fell to the `^\\S` branch, ended the list silently, and returned the first
    block's entries as the answer. YAML keeps the last key, so those modules
    would have reported as covered by a rule that never loads for them."""
    rule = _rule_file(tmp_path, 'paths:\n  - "src/a.py"\npaths: ["src/c.py"]')
    with pytest.raises(AssertionError, match="more than one top level"):
        _security_rule_paths(rule)


def test_the_rule_parser_refuses_a_flow_style_first_paths_key(tmp_path: Path) -> None:
    """The same shape with only one key. Reading the name and ignoring the tail
    would report an empty list, and an empty list makes the subset check
    vacuously true."""
    rule = _rule_file(tmp_path, 'paths: ["src/a.py", "src/b.py"]')
    with pytest.raises(AssertionError, match="carries"):
        _security_rule_paths(rule)


def test_the_rule_parser_refuses_a_list_entry_at_column_zero(tmp_path: Path) -> None:
    """Legal YAML this parser does not read. It used to truncate the list there
    and report everything after it as absent, silently, which is the shape the
    parser's own refusal message forbids."""
    rule = _rule_file(tmp_path, 'paths:\n  - "src/a.py"\n- "src/b.py"\n  - "src/c.py"')
    with pytest.raises(AssertionError, match="column zero"):
        _security_rule_paths(rule)
