"""The root as a hard boundary, from both directions.

Hermetic: everything happens inside tmp_path. The two symlink tests create
their own target directories under tmp_path.parent, which pytest owns.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hitchrail.discovery import (
    MAX_NAME_LENGTH,
    AlreadyExists,
    InvalidName,
    NoSuchProject,
    OutsideRoot,
    RootUnavailable,
    create_project,
    explain_name,
    list_projects,
    project_path,
    scan,
)


def test_lists_only_directories_case_insensitively(tmp_path: Path) -> None:
    (tmp_path / "beta").mkdir()
    (tmp_path / "Alpha").mkdir()
    (tmp_path / "notes.txt").write_text("x")
    assert list_projects(tmp_path) == ["Alpha", "beta"]


def test_lists_folders_without_git(tmp_path: Path) -> None:
    # A folder is a project. No git filter, no badge, no distinction.
    (tmp_path / "ideas").mkdir()
    assert list_projects(tmp_path) == ["ideas"]


def test_lists_nothing_in_an_empty_root(tmp_path: Path) -> None:
    assert list_projects(tmp_path) == []


def test_dotted_names_are_allowed(tmp_path: Path) -> None:
    # dotted.site is a real folder somebody has. Making it addressable in tmux
    # is the adapter's problem, not a reason to refuse it here.
    (tmp_path / "dotted.site").mkdir()
    assert project_path(tmp_path, "dotted.site").is_dir()


@pytest.mark.parametrize(
    "name",
    [
        "..",
        ".",
        "../etc",
        "a/b",
        "a\\b",
        "",
        ".hidden",
        "-lead",
        "--dangerously-skip-permissions",
        "x" * (MAX_NAME_LENGTH + 1),
        "a b",
        "a\x00b",
        "a‮b",
    ],
    ids=[
        "parent",
        "dot",
        "traversal",
        "posix-separator",
        "windows-separator",
        "empty",
        "hidden",
        "leading-hyphen",
        "flag-shaped",
        "too-long",
        "space",
        "null-byte",
        "rtl-override",
    ],
)
def test_traversal_and_junk_names_are_refused(tmp_path: Path, name: str) -> None:
    with pytest.raises(InvalidName):
        project_path(tmp_path, name)


def test_a_leading_hyphen_is_refused_because_argv_reads_it_as_a_flag(
    tmp_path: Path,
) -> None:
    # Argument injection. There is no shell anywhere in this project, and a
    # name beginning with '-' still becomes a flag once it reaches an argv slot
    # next to `claude`. Named separately so the reason survives a tidy up of
    # the parametrised case above.
    with pytest.raises(InvalidName):
        project_path(tmp_path, "-rf")


def test_a_name_that_matches_the_pattern_but_does_not_exist_is_refused(
    tmp_path: Path,
) -> None:
    with pytest.raises(InvalidName):
        project_path(tmp_path, "never-created")


def test_a_file_is_not_a_project(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("x")
    with pytest.raises(InvalidName):
        project_path(tmp_path, "notes.txt")


def test_symlink_escaping_the_root_is_refused(tmp_path: Path) -> None:
    # The case the pattern cannot see. A string prefix comparison passes this;
    # resolving both sides is what catches it.
    outside = tmp_path.parent / "outside_root"
    outside.mkdir(exist_ok=True)
    root = tmp_path / "root"
    root.mkdir()
    (root / "escape").symlink_to(outside, target_is_directory=True)
    with pytest.raises(OutsideRoot):
        project_path(root, "escape")


def test_a_symlink_to_a_sibling_inside_the_root_is_allowed(tmp_path: Path) -> None:
    # The boundary is the root, not "no symlinks". A link that stays inside is
    # a legitimate way for somebody to organise their projects.
    (tmp_path / "real").mkdir()
    (tmp_path / "alias").symlink_to(tmp_path / "real", target_is_directory=True)
    assert project_path(tmp_path, "alias") == (tmp_path / "real").resolve()


def test_creating_a_folder_makes_it_startable(tmp_path: Path) -> None:
    created = create_project(tmp_path, "fresh")
    assert created.is_dir()
    assert list_projects(tmp_path) == ["fresh"]


def test_creating_an_existing_folder_is_refused(tmp_path: Path) -> None:
    (tmp_path / "taken").mkdir()
    with pytest.raises(AlreadyExists):
        create_project(tmp_path, "taken")


def test_creating_a_traversal_name_is_refused(tmp_path: Path) -> None:
    with pytest.raises(InvalidName):
        create_project(tmp_path, "../evil")


def test_creating_over_a_symlink_out_of_the_root_is_refused(tmp_path: Path) -> None:
    # create_project and project_path must share one boundary check. If only
    # lookup resolves, creation is the weaker of the two paths, and the weaker
    # path is the one that gets found.
    outside = tmp_path.parent / "outside_create"
    outside.mkdir(exist_ok=True)
    root = tmp_path / "root"
    root.mkdir()
    (root / "escape").symlink_to(outside, target_is_directory=True)
    with pytest.raises((AlreadyExists, OutsideRoot)):
        create_project(root, "escape")


def test_creating_over_a_dangling_symlink_is_refused(tmp_path: Path) -> None:
    # Path.exists() follows symlinks, so a dangling link reports False on the
    # resolved path while very much occupying the name. mkdir would then raise
    # FileExistsError, which is not one of our refusals.
    (tmp_path / "ghost").symlink_to(tmp_path / "was-here-once")
    with pytest.raises(AlreadyExists):
        create_project(tmp_path, "ghost")


def test_a_refused_creation_leaves_nothing_behind(tmp_path: Path) -> None:
    # Asserting the exception is not enough. A guard that refuses after doing
    # the work passes a status check and is exactly the bug worth catching.
    root = tmp_path / "root"
    root.mkdir()
    with pytest.raises(InvalidName):
        create_project(root, "../evil")
    assert list(root.iterdir()) == []
    assert not (tmp_path / "evil").exists()


@pytest.mark.parametrize(
    "name",
    ["evil\n", "evil\r\n", "x" * (MAX_NAME_LENGTH - 1) + "\n", "ok\n\n"],
    ids=["newline", "crlf", "past-the-cap-via-newline", "double-newline"],
)
def test_a_trailing_newline_cannot_smuggle_a_name_past_the_pattern(
    tmp_path: Path, name: str
) -> None:
    """Named regression: `$` matched before a trailing newline, `\\Z` does not.

    With `$`, `evil\\n` satisfied the allowlist and became a real directory, and
    a 64 character name plus a newline walked past the pattern's own length
    cap. This is the entire path guard failing open over one character, so it
    is asserted from both directions.
    """
    with pytest.raises(InvalidName):
        project_path(tmp_path, name)
    with pytest.raises(InvalidName):
        create_project(tmp_path, name)
    assert list(tmp_path.iterdir()) == []


def test_listing_never_offers_a_folder_that_cannot_be_started(tmp_path: Path) -> None:
    """Named regression: the list and the lookup must agree.

    Listing `.git` and a symlink out of the root, then refusing both the moment
    somebody taps them, is an interface offering actions that cannot work.
    """
    outside = tmp_path.parent / "outside_listing"
    outside.mkdir(exist_ok=True)
    root = tmp_path / "root"
    root.mkdir()
    (root / "real").mkdir()
    (root / ".git").mkdir()
    (root / ".hidden").mkdir()
    (root / "-flag").mkdir()
    (root / "escape").symlink_to(outside, target_is_directory=True)

    listed = list_projects(root)
    assert listed == ["real"]
    for name in listed:
        assert project_path(root, name).is_dir()


def test_a_symlink_to_a_nested_directory_is_refused_with_an_honest_message(
    tmp_path: Path,
) -> None:
    # Deliberate: the design says a DIRECT child of the root. The message has
    # to say that rather than claiming the target is outside the root, because
    # it is not, and a misleading refusal wastes somebody's afternoon.
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "inner").mkdir()
    (tmp_path / "nested").symlink_to(tmp_path / "sub" / "inner", target_is_directory=True)
    with pytest.raises(OutsideRoot, match="not a direct child"):
        project_path(tmp_path, "nested")


def test_creating_a_folder_that_already_exists_is_refused_not_crashed(
    tmp_path: Path,
) -> None:
    (tmp_path / "racer").mkdir()
    with pytest.raises(AlreadyExists):
        create_project(tmp_path, "racer")


def test_a_create_that_loses_a_race_refuses_rather_than_raising_oserror(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Named regression: check-then-create let FileExistsError escape.

    FileExistsError is not a ValueError, so every caller's refusal handling
    missed it and the API would have answered 500 rather than a refusal. A web
    interface makes the double submission that triggers it easy.

    The race is simulated rather than run. Asserting on an already existing
    folder is not enough: check-then-create produces AlreadyExists for that
    case too, so such a test documents the contract without noticing a revert.
    Making mkdir itself lose the race is what turns this into a guard, and a
    genuinely concurrent test here would be flaky.
    """

    def lost_the_race(self: Path, *args: object, **kwargs: object) -> None:
        raise FileExistsError(17, "File exists")

    monkeypatch.setattr(Path, "mkdir", lost_the_race)
    with pytest.raises(AlreadyExists):
        create_project(tmp_path, "racer")


def test_creation_never_follows_a_symlink_to_its_target(tmp_path: Path) -> None:
    # Creating at the RESOLVED path would make the link's target instead of the
    # name that was asked for, which is a different directory entirely.
    target = tmp_path / "elsewhere"
    (tmp_path / "ghost").symlink_to(target)
    with pytest.raises(AlreadyExists):
        create_project(tmp_path, "ghost")
    assert not target.exists()


def test_a_missing_project_is_distinguishable_from_a_malformed_name(
    tmp_path: Path,
) -> None:
    """Named regression: 400 and 404 are different answers.

    Both used to raise a bare InvalidName, so the HTTP layer could only answer
    400 for each. A project deleted from under a stale phone tab is not a
    client sending a bad request.
    """
    with pytest.raises(NoSuchProject):
        project_path(tmp_path, "well-formed-but-absent")
    with pytest.raises(InvalidName) as bad:
        project_path(tmp_path, "../etc")
    assert not isinstance(bad.value, NoSuchProject)

    # Still a subclass, so existing handlers and the declared interface for
    # later phases keep working unchanged.
    assert issubclass(NoSuchProject, InvalidName)


def test_a_root_that_vanished_is_reported_rather_than_crashing(tmp_path: Path) -> None:
    """Named regression: FileNotFoundError is not a ValueError.

    Config checks the root once, at construction. A USB drive, an autofs mount
    or a sync client can take it away afterwards, and an unmapped OSError
    escaped every caller's refusal handling as a 500. This is the same door the
    AlreadyExists mapping closed on the creation side.
    """
    root = tmp_path / "gone"
    root.mkdir()
    root.rmdir()
    with pytest.raises(RootUnavailable):
        list_projects(root)
    with pytest.raises(RootUnavailable):
        create_project(root, "anything")


def test_root_unavailable_is_not_mistaken_for_an_empty_root(tmp_path: Path) -> None:
    # Guessing "no projects" from a root we could not read would report every
    # session as stopped, which is control 7's whole point.
    root = tmp_path / "vanished"
    root.mkdir()
    root.rmdir()
    with pytest.raises(RootUnavailable):
        list_projects(root)


def test_the_length_cap_is_the_filesystems_own_limit(tmp_path: Path) -> None:
    # 64 was invented. Length carries no security argument here, unlike the
    # alphabet and the first character, and the old cap hid ordinary folders
    # for no reason. 255 is what the filesystem itself allows, and the pattern
    # is ASCII only so a character is a byte.
    assert MAX_NAME_LENGTH == 255
    ok = "a" * MAX_NAME_LENGTH
    (tmp_path / ok).mkdir()
    assert project_path(tmp_path, ok).is_dir()
    with pytest.raises(InvalidName):
        project_path(tmp_path, "a" * (MAX_NAME_LENGTH + 1))


def test_scan_reports_the_folders_it_cannot_offer(tmp_path: Path) -> None:
    """The fix for the silence.

    These folders used to vanish from the listing with no signal at all, and
    the honest reading from a phone was that Hitchrail could not see them.
    """
    for name in ("normal", "my app", "café", "report(final)", "-flag"):
        (tmp_path / name).mkdir()

    listing = scan(tmp_path)
    assert listing.projects == ("normal",)

    reported = {u.name: u.reason for u in listing.unsupported}
    assert set(reported) == {"my app", "café", "report(final)", "-flag"}
    assert "a space" in reported["my app"]
    assert "non ASCII" in reported["café"]
    assert "flag" in reported["-flag"]
    # Every reason names the rule, so somebody can act on it.
    assert all(r and not r.endswith(".") for r in reported.values())


def test_scan_does_not_report_dot_directories_as_rejected_projects(
    tmp_path: Path,
) -> None:
    # .git is not a folder somebody was trying to use as a project, so listing
    # it as rejected would be noise rather than information.
    (tmp_path / "real").mkdir()
    (tmp_path / ".git").mkdir()
    (tmp_path / ".cache").mkdir()

    listing = scan(tmp_path)
    assert listing.projects == ("real",)
    assert listing.unsupported == ()


def test_scan_reports_a_symlink_out_of_the_root_rather_than_hiding_it(
    tmp_path: Path,
) -> None:
    outside = tmp_path.parent / "outside_scan"
    outside.mkdir(exist_ok=True)
    root = tmp_path / "root"
    root.mkdir()
    (root / "real").mkdir()
    (root / "escape").symlink_to(outside, target_is_directory=True)

    listing = scan(root)
    assert listing.projects == ("real",)
    assert [u.name for u in listing.unsupported] == ["escape"]
    assert "outside the root" in listing.unsupported[0].reason


def test_list_projects_still_answers_the_plain_question(tmp_path: Path) -> None:
    # The engine only acts on projects and should not have to unpack a Listing.
    (tmp_path / "one").mkdir()
    (tmp_path / "my app").mkdir()
    assert list_projects(tmp_path) == ["one"]


def test_scan_makes_one_pass_over_the_root(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # Two functions would mean two iterdir calls that can disagree about a
    # directory somebody is editing while they look at it.
    (tmp_path / "one").mkdir()
    calls: list[int] = []
    real_iterdir = Path.iterdir

    def counting(self: Path):  # type: ignore[no-untyped-def]
        calls.append(1)
        return real_iterdir(self)

    monkeypatch.setattr(Path, "iterdir", counting)
    scan(tmp_path)
    assert calls == [1]


def test_scan_is_sorted_case_insensitively_on_both_halves(tmp_path: Path) -> None:
    for name in ("Zebra", "apple", "My App", "beta gamma"):
        (tmp_path / name).mkdir()
    listing = scan(tmp_path)
    assert listing.projects == ("apple", "Zebra")
    assert [u.name for u in listing.unsupported] == ["beta gamma", "My App"]


def test_a_root_that_vanishes_mid_scan_is_reported_not_crashed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # iterdir was wrapped, but is_dir and resolve one line below were not, so
    # an autofs mount going away mid listing escaped as a bare OSError past the
    # wrapper added directly above it.
    (tmp_path / "one").mkdir()

    def vanished(self: Path) -> bool:
        raise OSError("mount went away")

    monkeypatch.setattr(Path, "is_dir", vanished)
    with pytest.raises(RootUnavailable):
        scan(tmp_path)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("ok-name", None),
        ("", "empty"),
        (".hidden", "dot"),
        ("-flag", "hyphen"),
        ("a" * 300, "over the 255 limit"),
        ("my app", "a space"),
        ("café", "non ASCII"),
    ],
)
def test_explain_name_says_which_rule_was_broken(name: str, expected: str | None) -> None:
    reason = explain_name(name)
    if expected is None:
        assert reason is None
    else:
        assert reason is not None
        assert expected in reason


def test_a_name_starting_with_an_allowed_character_that_is_not_alphanumeric(
    tmp_path: Path,
) -> None:
    # `_leading` passes every character check and still fails the pattern,
    # because the first character must be a letter or a digit. It used to fall
    # through to a message that named no rule at all.
    (tmp_path / "_leading").mkdir()
    reason = explain_name("_leading")
    assert reason is not None
    assert "start with a letter or a digit" in reason
    assert [u.reason for u in scan(tmp_path).unsupported] == [reason]


def test_an_entry_that_cannot_be_resolved_is_reported_not_crashed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # resolve() sits inside the loop, below the iterdir wrapper. An EACCES on
    # one subdirectory used to escape as a bare OSError.
    (tmp_path / "one").mkdir()
    real_resolve = Path.resolve

    def selective(self: Path, strict: bool = False) -> Path:
        if self.name == "one":
            raise OSError("EACCES")
        return real_resolve(self)

    monkeypatch.setattr(Path, "resolve", selective)
    with pytest.raises(RootUnavailable):
        scan(tmp_path)
