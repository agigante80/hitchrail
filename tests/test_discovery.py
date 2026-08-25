"""The root as a hard boundary, from both directions.

Hermetic: everything happens inside tmp_path. The two symlink tests create
their own target directories under tmp_path.parent, which pytest owns.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hitchrail.discovery import (
    AlreadyExists,
    InvalidName,
    OutsideRoot,
    create_project,
    list_projects,
    project_path,
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
        "x" * 65,
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
