"""The config file (#154): roots the operator edits on the machine.

Every refusal `--root` earns, the file earns identically, because both build
the same `Root` objects and `Config` refuses them; nothing validates before
`Config` does. Premortem 2 of the Phase 14 plan is the alternative, a second
validator that drifts, and the parity tests here are its rule.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from hitchrail import settings
from hitchrail.cli import build_config, main, parse_args
from hitchrail.config import Config, ConfigError
from hitchrail.roots import Root
from hitchrail.sessions import (
    InvalidValue,
    OperatorDisabled,
    OperatorPinned,
    StateUnwritable,
    UnknownRoot,
)


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(text)
    # Whatever the developer's umask: the mode is part of what is tested.
    path.chmod(0o644)
    return path


def test_a_file_with_two_roots_produces_the_same_config_as_two_flags(tmp_path: Path) -> None:
    (tmp_path / "work").mkdir()
    (tmp_path / "home").mkdir()
    path = _write(
        tmp_path,
        f'[[roots]]\nlabel = "work"\npath = "{tmp_path / "work"}"\n\n'
        f'[[roots]]\nlabel = "home"\npath = "{tmp_path / "home"}"\n',
    )
    from_file = build_config(parse_args(["--config", str(path)]))
    from_flags = build_config(
        parse_args(
            ["--root", f"work={tmp_path / 'work'}", "--root", f"home={tmp_path / 'home'}"]
        )
    )
    assert from_file.roots == from_flags.roots


def test_the_flag_wins_over_the_file_and_nothing_is_merged(tmp_path: Path) -> None:
    """`--root` still works and still wins, with no deprecation. Wins outright:
    a flag beside a file does not add to it, because a root the operator did
    not name on this command line appearing anyway is the surprise that
    matters on a tool that spawns agents."""
    (tmp_path / "work").mkdir()
    (tmp_path / "home").mkdir()
    path = _write(tmp_path, f'[[roots]]\nlabel = "home"\npath = "{tmp_path / "home"}"\n')
    config = build_config(
        parse_args(["--config", str(path), "--root", f"work={tmp_path / 'work'}"])
    )
    assert [r.label for r in config.roots] == ["work"]


def test_a_missing_file_is_no_roots_and_the_existing_refusal(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="no roots configured"):
        build_config(parse_args(["--config", str(tmp_path / "absent.toml")]))


def test_a_tilde_in_a_path_is_the_operators_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "work").mkdir()
    path = _write(tmp_path, '[[roots]]\nlabel = "work"\npath = "~/work"\n')
    config = build_config(parse_args(["--config", str(path)]))
    assert config.roots[0].path == (tmp_path / "work").resolve()


ROOTS_TOML = '[[roots]]\nlabel = "{label}"\npath = "{path}"\n'


@pytest.mark.parametrize(
    ("flag_roots", "file_roots", "reason"),
    [
        ([("a", "{d1}"), ("a", "{d2}")], None, "two roots share the label 'a'"),
        ([("a", "{d1}/nope")], None, "is not a directory"),
        ([("a", "{d1}"), ("b", "{d1}/inner")], None, "is inside root"),
        ([(".bad", "{d1}")], None, "begins with a dot"),
    ],
    ids=["duplicate-label", "not-a-directory", "nested", "bad-label"],
)
def test_every_refusal_the_flag_makes_the_file_makes_identically(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    flag_roots: list[tuple[str, str]],
    file_roots: None,
    reason: str,
) -> None:
    """The same input through both doors, the same refusal. The three
    `Config` refusals are byte identical, because both doors build the same
    `Root` objects and one function refuses them. The label refusal is the
    flag's own `type=` callable, which argparse prints and exits on, and the
    file wraps in its own line; the reason inside is the same sentence from
    the same parser, which is what the fourth case asserts."""
    d1, d2 = tmp_path / "d1", tmp_path / "d2"
    d1.mkdir()
    d2.mkdir()
    (d1 / "inner").mkdir()
    subs = {"d1": str(d1), "d2": str(d2)}
    pairs = [(label, folder.format(**subs)) for label, folder in flag_roots]
    flags: list[str] = []
    for label, folder in pairs:
        flags += ["--root", f"{label}={folder}"]
    path = _write(tmp_path, "".join(ROOTS_TOML.format(label=a, path=b) for a, b in pairs))

    with pytest.raises((ConfigError, SystemExit)) as via_flags:
        build_config(parse_args(flags))
    flag_message = str(via_flags.value)
    if isinstance(via_flags.value, SystemExit):
        flag_message = capsys.readouterr().err
    with pytest.raises(ConfigError) as via_file:
        build_config(parse_args(["--config", str(path)]))
    file_message = str(via_file.value)

    assert reason in flag_message and reason in file_message
    if not isinstance(via_flags.value, SystemExit):
        assert flag_message == file_message


def test_a_malformed_file_refuses_naming_the_file_and_the_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Never a partial set: a file that does not parse starts nothing."""
    path = _write(tmp_path, '[[roots]]\nlabel = "a"\npath = \n')
    assert main(["--config", str(path)]) == 2
    err = capsys.readouterr().err
    assert str(path) in err and "line 3" in err


def test_a_file_with_an_unknown_key_refuses_rather_than_ignoring_it(tmp_path: Path) -> None:
    """A misspelt key silently ignored is a setting the operator believes is
    on. The file's schema is closed."""
    (tmp_path / "work").mkdir()
    path = _write(
        tmp_path, f'[[roots]]\nlabel = "work"\npath = "{tmp_path / "work"}"\nenable = false\n'
    )
    with pytest.raises(ConfigError, match="enable"):
        build_config(parse_args(["--config", str(path)]))


def test_enabled_false_in_the_file_configures_the_root_and_hides_it(tmp_path: Path) -> None:
    (tmp_path / "work").mkdir()
    (tmp_path / "home").mkdir()
    path = _write(
        tmp_path,
        f'[[roots]]\nlabel = "work"\npath = "{tmp_path / "work"}"\n\n'
        f'[[roots]]\nlabel = "home"\npath = "{tmp_path / "home"}"\nenabled = false\n',
    )
    config = build_config(parse_args(["--config", str(path)]))
    assert [(r.label, r.enabled) for r in config.roots] == [("work", True), ("home", False)]
    assert [r.label for r in settings.Preferences(config).active_roots()] == ["work"]


def test_a_file_others_can_write_is_refused_and_says_why(tmp_path: Path) -> None:
    """The file decides where an agent may run, so one anybody on the machine
    can edit is a root anybody on the machine can add. Refused the way ssh
    refuses a permissive key, before it is parsed: a valid file with the
    wrong mode is still the wrong file."""
    (tmp_path / "work").mkdir()
    path = _write(tmp_path, ROOTS_TOML.format(label="work", path=tmp_path / "work"))
    path.chmod(0o666)
    with pytest.raises(ConfigError, match=r"writable by group or others \(mode 0666\)"):
        build_config(parse_args(["--config", str(path)]))
    path.chmod(0o644)
    assert [r.label for r in build_config(parse_args(["--config", str(path)])).roots] == [
        "work"
    ]


def test_group_writable_is_refused_unless_the_group_is_the_owners_own(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ubuntu's default umask is 002 under user private groups, so a plain
    664 file is the default editor's output and is accepted. The same mode
    under a shared group is what the refusal is for. The group lookup is
    faked because a test cannot chgrp to a group it is not in."""
    (tmp_path / "work").mkdir()
    path = _write(tmp_path, ROOTS_TOML.format(label="work", path=tmp_path / "work"))
    path.chmod(0o664)
    monkeypatch.setattr(settings, "_group_is_private", lambda gid, uid: True)
    assert [r.label for r in build_config(parse_args(["--config", str(path)])).roots] == [
        "work"
    ]
    monkeypatch.setattr(settings, "_group_is_private", lambda gid, uid: False)
    with pytest.raises(ConfigError, match=r"mode 0664"):
        build_config(parse_args(["--config", str(path)]))


def test_a_file_owned_by_somebody_else_is_refused_whatever_its_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The security audit of the first version: a colleague's 644 file
    passed, because only the mode was read. The owner is compared with the
    running user, root excepted. Simulated by moving the running user, since
    a test cannot chown to somebody else."""
    (tmp_path / "work").mkdir()
    path = _write(tmp_path, ROOTS_TOML.format(label="work", path=tmp_path / "work"))
    monkeypatch.setattr(os, "geteuid", lambda: os.getuid() + 12345)
    with pytest.raises(ConfigError, match=r"is owned by uid \d+, not by the user running"):
        build_config(parse_args(["--config", str(path)]))


def test_the_private_group_convention_is_read_from_the_passwd_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both halves: the file's group is the owner's primary group AND it is
    named after the owner. `users` as a primary group fails the second, a
    private group the file was not saved under fails the first, and an
    account the database no longer knows fails closed."""
    import grp
    import pwd

    def user(name: str, gid: int) -> pwd.struct_passwd:
        return pwd.struct_passwd((name, "x", 1000, gid, "", "/home/x", "/bin/sh"))

    def group(name: str, members: list[str] | None = None) -> grp.struct_group:
        return grp.struct_group((name, "x", 0, members or []))

    monkeypatch.setattr(pwd, "getpwuid", lambda uid: user("alice", 1000))
    monkeypatch.setattr(grp, "getgrgid", lambda gid: group("alice"))
    assert settings._group_is_private(1000, 1000)
    monkeypatch.setattr(grp, "getgrgid", lambda gid: group("users"))
    assert not settings._group_is_private(1000, 1000)
    monkeypatch.setattr(grp, "getgrgid", lambda gid: group("alice"))
    assert not settings._group_is_private(1001, 1000)
    # `usermod -aG alice bob`: private in name only, and the audit's case.
    monkeypatch.setattr(grp, "getgrgid", lambda gid: group("alice", ["bob"]))
    assert not settings._group_is_private(1000, 1000)
    # The owner listed in their own group is still alone (review round 2).
    monkeypatch.setattr(grp, "getgrgid", lambda gid: group("alice", ["alice"]))
    assert settings._group_is_private(1000, 1000)
    monkeypatch.setattr(grp, "getgrgid", lambda gid: group("alice", ["alice", "bob"]))
    assert not settings._group_is_private(1000, 1000)

    def unknown(uid: int) -> pwd.struct_passwd:
        raise KeyError(uid)

    monkeypatch.setattr(pwd, "getpwuid", unknown)
    assert not settings._group_is_private(1000, 1000)


# -- the state file: Hitchrail's own, and it can only disable ---------------


def _two_roots(tmp_path: Path, state: Path | None) -> settings.Preferences:
    (tmp_path / "w").mkdir(exist_ok=True)
    (tmp_path / "h").mkdir(exist_ok=True)
    config = Config(
        roots=(
            Root(label="work", path=tmp_path / "w", enabled=True),
            Root(label="home", path=tmp_path / "h", enabled=False),
        ),
        state_path=state,
    )
    return settings.Preferences(config)


def test_the_state_file_can_disable_a_root_and_never_enable_one(tmp_path: Path) -> None:
    """Hitchrail never writes the file that names the paths; the operator's
    file stays theirs. What the interface toggles lives in a state file of
    Hitchrail's own, and it can only disable further: a root the operator
    disabled in their file stays disabled whatever the state file says,
    because the perimeter is theirs to draw."""
    state = tmp_path / "state.toml"
    state.write_text('disabled = ["work"]\n')
    assert _two_roots(tmp_path, state).active_roots() == ()
    state.write_text('disabled = ["home"]\n')
    prefs = _two_roots(tmp_path, state)
    assert [r.label for r in prefs.active_roots()] == ["work"]
    assert prefs.hidden_roots() == ("home",)


def test_a_toggle_persists_first_and_only_then_applies(tmp_path: Path) -> None:
    state = tmp_path / "state.toml"
    prefs = _two_roots(tmp_path, state)
    prefs.set_roots_enabled({"work": False})
    assert settings.read_state(state).hidden == {"work"}
    assert prefs.active_roots() == ()
    # A fresh process reads the choice back: that is what "persists" means.
    assert _two_roots(tmp_path, state).active_roots() == ()
    prefs.set_roots_enabled({"work": True})
    assert settings.read_state(state).hidden == frozenset()
    assert [r.label for r in prefs.active_roots()] == ["work"]


def test_a_request_that_changes_nothing_writes_nothing(tmp_path: Path) -> None:
    """`PATCH {}`, or a toggle to the state a root is already in, on a config
    directory that cannot be written: no write, no 503, because there was
    nothing to say (review round 2)."""
    state = tmp_path / "blocked" / "state.toml"
    (tmp_path / "blocked").write_text("a file where the directory should be")
    prefs = _two_roots(tmp_path, state)
    prefs.apply()
    prefs.apply(roots={"work": True})
    assert [r.label for r in prefs.active_roots()] == ["work"]


def test_a_toggle_that_cannot_be_written_changes_nothing(tmp_path: Path) -> None:
    """Applied in memory and lost at the next restart is the drift a state
    file exists to end, so an unwritable file refuses and the set is as it
    was."""
    state = tmp_path / "blocked" / "state.toml"
    (tmp_path / "blocked").write_text("a file where the directory should be")
    prefs = _two_roots(tmp_path, state)
    with pytest.raises(StateUnwritable, match=r"state\.toml"):
        prefs.set_roots_enabled({"work": False})
    assert [r.label for r in prefs.active_roots()] == ["work"]


def test_a_request_cannot_enable_what_the_operator_disabled(tmp_path: Path) -> None:
    prefs = _two_roots(tmp_path, None)
    with pytest.raises(OperatorDisabled, match="operator's config file"):
        prefs.set_roots_enabled({"home": True})
    # Disabling it further is accepted: the direction is the same.
    prefs.set_roots_enabled({"home": False})
    assert [(v.label, v.enabled, v.editable) for v in prefs.root_views()] == [
        ("work", True, True),
        ("home", False, False),
    ]


def test_an_unknown_label_is_refused_before_anything_is_written(tmp_path: Path) -> None:
    """Every label is checked before the file is touched, so a request naming
    one bad label alongside a good one changes nothing at all."""
    state = tmp_path / "state.toml"
    prefs = _two_roots(tmp_path, state)
    with pytest.raises(UnknownRoot, match=r"'\.\./etc'"):
        prefs.set_roots_enabled({"work": False, "../etc": False})
    assert not state.exists()
    assert [r.label for r in prefs.active_roots()] == ["work"]


def test_writing_the_state_file_records_only_labels_that_are_configured(tmp_path: Path) -> None:
    state = tmp_path / "state.toml"
    settings.write_state(
        state, settings.State(hidden=frozenset({"home", "gone"})), configured={"work", "home"}
    )
    assert settings.read_state(state).hidden == {"home"}


def test_an_unreadable_state_file_disables_nothing(tmp_path: Path) -> None:
    """The failure direction: a state file that cannot be read hides no root,
    because hiding a running session is the dangerous direction and the
    operator's file is the perimeter either way."""
    state = tmp_path / "state.toml"
    state.write_text("disabled = [1, 2\n")
    assert settings.read_state(state) == settings.State()
    state.write_text('disabled = "work"\n')
    assert settings.read_state(state) == settings.State()


# -- #238: the stop timeout, a policy the interface may set -----------------


@pytest.mark.parametrize("bad", ["60", 60.5, True, 0, -5, [60]])
def test_a_stop_timeout_that_is_not_a_positive_whole_number_is_refused(
    tmp_path: Path, bad: object
) -> None:
    """Zero and below through `Config`'s own refusal, the rest through the
    type gate in front of it: `True` is an `int` to Python and is not a
    wait anybody meant."""
    state = tmp_path / "state.toml"
    prefs = _two_roots(tmp_path, state)
    with pytest.raises(InvalidValue):
        prefs.set_stop_timeout(bad)
    assert not state.exists()
    assert prefs.stop_timeout() == 30.0


def test_a_stop_timeout_persists_and_a_flag_pins_it(tmp_path: Path) -> None:
    state = tmp_path / "state.toml"
    prefs = _two_roots(tmp_path, state)
    assert prefs.stop_timeout_source() == "default"
    prefs.set_stop_timeout(45)
    assert prefs.stop_timeout() == 45
    assert prefs.stop_timeout_source() == "state"
    assert "stop_timeout = 45" in state.read_text()
    assert _two_roots(tmp_path, state).stop_timeout() == 45
    # The flag wins outright, as it does over the config file: the value in
    # the state file is neither read nor writable while the flag is given.
    pinned = settings.Preferences(
        Config(
            roots=(Root(label="work", path=tmp_path / "w"),),
            state_path=state,
            stop_timeout=60,
            sources={"stop_timeout": "flag"},
        )
    )
    assert pinned.stop_timeout() == 60
    assert pinned.stop_timeout_source() == "flag"
    assert not pinned.stop_timeout_editable()
    with pytest.raises(OperatorPinned, match="command line"):
        pinned.set_stop_timeout(45)


@pytest.mark.parametrize("bad", ["true", "0", "-5", "3601", "9999999", '"45"'])
def test_a_bad_timeout_in_the_state_file_loses_nothing_beside_it(
    tmp_path: Path, bad: str
) -> None:
    """Including one past the ceiling (#265, review round 1): a state file
    written by 0.8.0's page, which accepted any positive number, or by
    hand, is not a way past the one validator."""
    state = tmp_path / "state.toml"
    state.write_text(f'disabled = ["home"]\nstop_timeout = {bad}\n')
    read = settings.read_state(state)
    assert read.hidden == {"home"}
    assert read.stop_timeout is None


# -- #123: the session prefix, reachable at last --------------------------


def test_the_prefix_comes_from_the_flag_then_the_file_then_the_default(tmp_path: Path) -> None:
    (tmp_path / "work").mkdir()
    path = _write(
        tmp_path,
        # Top level keys come BEFORE the first `[[roots]]`: TOML reads a key
        # after a table header as that table's, and the closed schema then
        # refuses it as an unknown root key, which is the right answer.
        'session_prefix = "work-"\n' + ROOTS_TOML.format(label="work", path=tmp_path / "work"),
    )
    assert build_config(parse_args(["--config", str(path)])).session_prefix == "work-"
    flag = ["--config", str(path), "--session-prefix", "other-"]
    assert build_config(parse_args(flag)).session_prefix == "other-"
    bare = _write(tmp_path, ROOTS_TOML.format(label="work", path=tmp_path / "work"))
    assert build_config(parse_args(["--config", str(bare)])).session_prefix == "hr-"


@pytest.mark.parametrize("prefix", ["", "   ", " hr- ", "hr.", "hr:", "h r-"])
def test_every_prefix_refusal_is_reachable_from_the_command_line(
    tmp_path: Path, prefix: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """`_check_session_prefix` existed for a year with nothing reaching it
    from the command line (#123). Exit 2, the deliberate stop the unit never
    restarts, naming the prefix. The empty string is the case that matters:
    truthiness would have let `--session-prefix ""` fall through to `hr-`."""
    (tmp_path / "work").mkdir()
    argv = ["--root", f"work={tmp_path / 'work'}", "--session-prefix", prefix]
    assert main(argv) == 2
    assert "session prefix" in capsys.readouterr().err


def test_a_prefix_in_the_file_that_is_not_a_string_is_refused(tmp_path: Path) -> None:
    (tmp_path / "work").mkdir()
    path = _write(
        tmp_path,
        "session_prefix = 1\n" + ROOTS_TOML.format(label="work", path=tmp_path / "work"),
    )
    with pytest.raises(ConfigError, match="session_prefix must be a string"):
        build_config(parse_args(["--config", str(path)]))


def test_a_prefix_in_the_file_earns_the_same_refusal_as_the_flag(tmp_path: Path) -> None:
    """Premortem 2 again: the file feeds `Config` and `Config` refuses. A
    padded prefix from the file is refused in the flag's own words."""
    (tmp_path / "work").mkdir()
    path = _write(
        tmp_path,
        'session_prefix = " hr- "\n' + ROOTS_TOML.format(label="work", path=tmp_path / "work"),
    )
    with pytest.raises(ConfigError, match="non blank and unpadded"):
        build_config(parse_args(["--config", str(path)]))
