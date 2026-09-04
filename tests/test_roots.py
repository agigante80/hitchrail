"""What a root IS, and what a qualified project identifier IS.

#119 decided a project is `<root-label>~<folder>`, always. This module is that
decision's vocabulary: pure functions of strings and paths, with the filesystem
walking left to `discovery`. Same split as `hostnames` beside `config` and
`projectnames` beside `discovery`, and for the same reason: the thing that
decides what a name MEANS should be testable without a machine.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hitchrail.roots import (
    QUALIFIER,
    Root,
    RootError,
    check_roots,
    parse_root_argument,
    qualify,
    split_identifier,
)

# -- the flag ---------------------------------------------------------------


def test_a_root_argument_is_a_label_and_a_path(tmp_path: Path) -> None:
    root = parse_root_argument(f"work={tmp_path}")
    assert root.label == "work"
    assert root.path == tmp_path.resolve()


def test_a_bare_path_is_refused_rather_than_given_a_default_label(tmp_path: Path) -> None:
    """#119. A label guessed from the directory name would change when the
    directory moved, and the identifier has to be stable."""
    with pytest.raises(RootError) as e:
        parse_root_argument(str(tmp_path))
    assert "label" in str(e.value)


def test_an_empty_label_is_refused(tmp_path: Path) -> None:
    with pytest.raises(RootError):
        parse_root_argument(f"={tmp_path}")


def test_an_empty_path_is_refused() -> None:
    with pytest.raises(RootError):
        parse_root_argument("work=")


def test_only_the_first_equals_splits(tmp_path: Path) -> None:
    """A path may legitimately contain `=`. The label may not, so the split is
    unambiguous at the first one."""
    odd = tmp_path / "a=b"
    odd.mkdir()
    assert parse_root_argument(f"work={odd}").path == odd.resolve()


@pytest.mark.parametrize("label", ["work~shop", "-lead", ".hidden", "a/b", "a b", "a:b"])
def test_a_label_is_held_to_the_project_name_allowlist(label: str, tmp_path: Path) -> None:
    """The same allowlist as a folder name, which is what keeps `~` out of it.

    That exclusion is not cosmetic: it is the whole of the injectivity
    argument. If a label could contain `~`, then label `a` with folder `b~c`
    and label `a~b` with folder `c` would both qualify to `a~b~c`.
    """
    with pytest.raises(RootError):
        parse_root_argument(f"{label}={tmp_path}")


# -- the identifier ---------------------------------------------------------


def test_qualify_joins_with_the_qualifier() -> None:
    assert qualify("work", "vessel") == f"work{QUALIFIER}vessel"


def test_split_is_the_inverse_of_qualify() -> None:
    assert split_identifier(qualify("work", "vessel")) == ("work", "vessel")


def test_qualifying_is_injective_because_neither_half_can_hold_the_qualifier() -> None:
    """The property the whole decision rests on, asserted rather than asserted
    about. `a~b` and `c` must not qualify to the same thing as `a` and `b~c`,
    and the allowlist is what makes the first pair unconstructible."""
    with pytest.raises(RootError):
        parse_root_argument(f"a{QUALIFIER}b=/tmp")


def test_an_identifier_with_no_qualifier_is_refused() -> None:
    """A bare folder name is what 0.1.0 used. It is not an identifier any more,
    and accepting it would silently address a project in whichever root came
    first, which is the ambiguity this replaced."""
    with pytest.raises(RootError):
        split_identifier("vessel")


# -- the refusals across a set of roots --------------------------------------


def _root(label: str, path: Path) -> Root:
    return Root(label=label, path=path.resolve())


def test_disjoint_roots_are_accepted(tmp_path: Path) -> None:
    a, b = tmp_path / "work", tmp_path / "personal"
    a.mkdir()
    b.mkdir()
    check_roots((_root("work", a), _root("personal", b)))


def test_no_roots_at_all_is_refused() -> None:
    with pytest.raises(RootError):
        check_roots(())


def test_two_roots_may_not_share_a_label(tmp_path: Path) -> None:
    a, b = tmp_path / "one", tmp_path / "two"
    a.mkdir()
    b.mkdir()
    with pytest.raises(RootError) as e:
        check_roots((_root("work", a), _root("work", b)))
    assert "work" in str(e.value)


def test_the_same_root_twice_is_refused(tmp_path: Path) -> None:
    a = tmp_path / "dev"
    a.mkdir()
    with pytest.raises(RootError):
        check_roots((_root("one", a), _root("two", a)))


def test_the_same_root_through_a_symlink_is_refused(tmp_path: Path) -> None:
    """Resolving before comparing is the whole of it, for the same reason
    `discovery.resolve_child` already resolves."""
    real = tmp_path / "dev"
    real.mkdir()
    link = tmp_path / "alias"
    link.symlink_to(real)
    with pytest.raises(RootError):
        check_roots((_root("one", real), _root("two", link)))


def test_overlapping_roots_are_refused_naming_both(tmp_path: Path) -> None:
    """One directory reachable under two identifiers breaks injectivity from
    the filesystem side rather than the naming side."""
    outer = tmp_path / "dev"
    inner = outer / "client"
    inner.mkdir(parents=True)
    with pytest.raises(RootError) as e:
        check_roots((_root("outer", outer), _root("inner", inner)))
    message = str(e.value)
    assert str(outer) in message and str(inner) in message


def test_overlap_is_refused_in_either_order(tmp_path: Path) -> None:
    outer = tmp_path / "dev"
    inner = outer / "client"
    inner.mkdir(parents=True)
    with pytest.raises(RootError):
        check_roots((_root("inner", inner), _root("outer", outer)))


def test_a_sibling_with_a_shared_prefix_is_not_an_overlap(tmp_path: Path) -> None:
    """`/dev` and `/dev-evil`. A string prefix comparison would call these
    nested, which is the same mistake `resolve_child` documents refusing."""
    a, b = tmp_path / "dev", tmp_path / "dev-evil"
    a.mkdir()
    b.mkdir()
    check_roots((_root("one", a), _root("two", b)))


def test_a_root_that_is_not_a_directory_is_refused(tmp_path: Path) -> None:
    missing = tmp_path / "nope"
    with pytest.raises(RootError) as e:
        check_roots((_root("gone", missing),))
    assert str(missing) in str(e.value)


def test_every_bad_root_is_named_not_only_the_first(tmp_path: Path) -> None:
    """So an operator fixes all of them in one go rather than one restart at a
    time."""
    good = tmp_path / "good"
    good.mkdir()
    with pytest.raises(RootError) as e:
        check_roots(
            (
                _root("a", tmp_path / "missing-a"),
                _root("ok", good),
                _root("b", tmp_path / "missing-b"),
            )
        )
    message = str(e.value)
    assert "missing-a" in message and "missing-b" in message


def test_the_operators_ordering_is_kept(tmp_path: Path) -> None:
    """Sorting would silently reorder somebody's interface when they add a
    root. The order given is the order rows group in."""
    a, b = tmp_path / "zeta", tmp_path / "alpha"
    a.mkdir()
    b.mkdir()
    roots = (_root("zeta", a), _root("alpha", b))
    check_roots(roots)
    assert [r.label for r in roots] == ["zeta", "alpha"]
