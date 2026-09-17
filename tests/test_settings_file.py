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
    asked: list[tuple[int, int]] = []

    def private(gid: int, uid: int) -> bool:
        asked.append((gid, uid))
        return True

    monkeypatch.setattr(settings, "_group_is_private", private)
    assert [r.label for r in build_config(parse_args(["--config", str(path)])).roots] == [
        "work"
    ]
    # The FILE's group and owner, not a constant: a mutant that passed None
    # for either survived a predicate that ignored its arguments.
    info = path.stat()
    assert asked == [(info.st_gid, info.st_uid)]
    monkeypatch.setattr(settings, "_group_is_private", lambda gid, uid: False)
    with pytest.raises(ConfigError, match=r"mode 0664"):
        build_config(parse_args(["--config", str(path)]))
    # And a 644 file is accepted whatever the group says: the group is only
    # consulted when the group can write. A mutant that always consulted it
    # refused every file on a shared group.
    path.chmod(0o644)
    assert [r.label for r in build_config(parse_args(["--config", str(path)])).roots] == [
        "work"
    ]


def test_a_root_owned_file_is_accepted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Root can edit anything regardless, so a root owned config is not a
    widening; the exception is uid 0 exactly, which a mutant made uid 1."""
    (tmp_path / "work").mkdir()
    path = _write(tmp_path, ROOTS_TOML.format(label="work", path=tmp_path / "work"))
    real = os.fstat

    def as_root(fd: int) -> os.stat_result:
        info = real(fd)
        fields = list(info)
        fields[4] = 0  # st_uid
        fields[5] = 0  # st_gid
        return os.stat_result(tuple(fields))

    monkeypatch.setattr(os, "fstat", as_root)
    assert [r.label for r in build_config(parse_args(["--config", str(path)])).roots] == [
        "work"
    ]


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

    # The fakes check what they are asked for: a mutant that looked up
    # `None` survived fakes that ignored their argument.
    def getpwuid(uid: int) -> pwd.struct_passwd:
        assert uid == 1000, uid
        return user("alice", 1000)

    def getgrgid_alice(gid: int) -> grp.struct_group:
        assert gid == 1000, gid
        return group("alice")

    monkeypatch.setattr(pwd, "getpwuid", getpwuid)
    monkeypatch.setattr(grp, "getgrgid", getgrgid_alice)
    assert settings._group_is_private(1000, 1000)
    monkeypatch.setattr(grp, "getgrgid", lambda gid: group("users"))
    assert not settings._group_is_private(1000, 1000)
    monkeypatch.setattr(grp, "getgrgid", lambda gid: group("alice"))
    assert not settings._group_is_private(1001, 1000)
    monkeypatch.setattr(grp, "getgrgid", getgrgid_alice)
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


# -- #273: the survivors in the file reader, read and killed ------------------


def test_the_default_path_is_xdg_then_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Never exercised until the sweep: every test passed `--config` or the
    autouse XDG stub, so the two halves of the default were free to drift."""
    monkeypatch.setenv(settings.CONFIG_HOME_ENV, str(tmp_path / "xdg"))
    assert settings.default_config_path() == tmp_path / "xdg" / "hitchrail" / "config.toml"
    monkeypatch.delenv(settings.CONFIG_HOME_ENV)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    expected = tmp_path / "home" / ".config" / "hitchrail" / "config.toml"
    assert settings.default_config_path() == expected


def test_a_missing_file_is_no_roots_as_a_tuple(tmp_path: Path) -> None:
    assert settings.read_config_file(tmp_path / "absent.toml") == settings.FileSettings(
        roots=()
    )


@pytest.mark.parametrize(
    ("text", "fragment"),
    [
        ('roots = "not a list"\n', "must be a list of tables"),
        ("roots = [1]\n", "entry 1 is not a table"),
        ('[[roots]]\npath = "{d}"\n', "has an empty label"),
        ('[[roots]]\nlabel = "work"\n', "has an empty path"),
        ('[[roots]]\nlabel = 1\npath = "{d}"\n', "label and path must be strings"),
        ('[[roots]]\nlabel = "work"\npath = 1\n', "label and path must be strings"),
        ('[[roots]]\nlabel = "work"\npath = "{d}"\nenabled = "yes"\n', "must be true or false"),
        ('wat = 1\n[[roots]]\nlabel = "work"\npath = "{d}"\n', "unknown key 'wat'"),
    ],
)
def test_every_shape_the_file_refuses_says_so(tmp_path: Path, text: str, fragment: str) -> None:
    """Each refusal in its own words, asserted on the words: a mutant that
    raised with no message, accepted an unknown top level key, or defaulted
    a missing label to something the allowlist admits survived tests that
    checked only that something was refused."""
    (tmp_path / "work").mkdir()
    path = _write(tmp_path, text.format(d=tmp_path / "work"))
    with pytest.raises(ConfigError, match=fragment):
        build_config(parse_args(["--config", str(path)]))


def test_a_refusal_names_the_entry_by_its_position(tmp_path: Path) -> None:
    (tmp_path / "work").mkdir()
    path = _write(
        tmp_path,
        ROOTS_TOML.format(label="work", path=tmp_path / "work") + "[[roots]]\nlabel = 2\n",
    )
    with pytest.raises(ConfigError, match="roots entry 2:"):
        build_config(parse_args(["--config", str(path)]))


def test_the_state_files_boundaries_are_honoured(tmp_path: Path) -> None:
    """1 and 3600 are waits; 0 and 3601 are not. The sweep flipped each
    boundary by one and nothing noticed."""
    state = tmp_path / "state.toml"
    for value in (1, 3600):
        state.write_text(f"stop_timeout = {value}\n")
        assert settings.read_state(state).stop_timeout == value


def test_two_hidden_labels_and_a_timeout_survive_a_round_trip(tmp_path: Path) -> None:
    """Two labels, so the separator is real TOML; both fields, so writing
    the second does not lose the first."""
    state = tmp_path / "state.toml"
    settings.write_state(
        state,
        settings.State(hidden=frozenset({"home", "work"}), stop_timeout=45),
        configured={"work", "home"},
    )
    read = settings.read_state(state)
    assert read.hidden == {"home", "work"}
    assert read.stop_timeout == 45


def test_a_file_that_cannot_be_opened_says_so(tmp_path: Path) -> None:
    (tmp_path / "work").mkdir()
    path = _write(tmp_path, ROOTS_TOML.format(label="work", path=tmp_path / "work"))
    path.chmod(0o000)
    try:
        with pytest.raises(ConfigError, match="cannot be read"):
            build_config(parse_args(["--config", str(path)]))
    finally:
        path.chmod(0o644)


def test_a_file_with_only_a_prefix_configures_no_roots(tmp_path: Path) -> None:
    """`roots` absent is no roots, not a refusal: the flags are the other
    door. A mutant that defaulted the key to `None` refused the file."""
    path = _write(tmp_path, 'session_prefix = "work-"\n')
    read = settings.read_config_file(path)
    assert read.roots == ()
    assert read.session_prefix == "work-"


def test_the_state_file_is_written_two_levels_deep(tmp_path: Path) -> None:
    """`--config` can name a file in a directory that does not exist yet,
    and the state file sits beside it."""
    state = tmp_path / "a" / "b" / "state.toml"
    settings.write_state(state, settings.State(hidden=frozenset({"work"})), configured={"work"})
    assert settings.read_state(state).hidden == {"work"}


# -- #270: the file's remaining refusals, in words ----------------------------


def test_a_label_holding_an_equals_sign_is_refused_as_a_label(tmp_path: Path) -> None:
    """The flag splits on the first `=`, so `a=b` composed into `a=b=/x` used
    to parse as label `a` at `<cwd>/b=/x`, and the allowlist that refuses
    `=` never saw it. Asked first now; one validator, still."""
    (tmp_path / "work").mkdir()
    path = _write(tmp_path, ROOTS_TOML.format(label="a=b", path=tmp_path / "work"))
    with pytest.raises(ConfigError, match=r"roots entry 1: root label 'a=b' is not usable"):
        build_config(parse_args(["--config", str(path)]))


def test_a_nul_in_a_path_refuses_with_exit_2_rather_than_a_traceback(tmp_path: Path) -> None:
    """argv cannot carry a NUL; a TOML escape can, and `resolve` raised a
    bare `ValueError` through `build_config`."""
    path = _write(tmp_path, '[[roots]]\nlabel = "work"\npath = "/tmp/a\\u0000b"\n')
    with pytest.raises(ConfigError, match=r"root 'work' has an unusable path"):
        build_config(parse_args(["--config", str(path)]))
    assert main(["--config", str(path)]) == 2


def test_a_file_that_is_not_utf8_is_refused_naming_the_file(tmp_path: Path) -> None:
    """`UnicodeDecodeError` is a `ValueError`, which neither the `OSError`
    nor the `TOMLDecodeError` arm caught."""
    path = tmp_path / "config.toml"
    path.write_bytes(b'[[roots]]\nlabel = "w\xff"\npath = "/x"\n')
    path.chmod(0o644)
    with pytest.raises(ConfigError, match=r"config\.toml: is not UTF-8"):
        build_config(parse_args(["--config", str(path)]))
    assert main(["--config", str(path)]) == 2


def test_a_directory_others_can_write_is_refused_naming_the_directory(tmp_path: Path) -> None:
    """A writable parent lets others `mv` a fresh 644 file over a private
    one, so the file's own mode proved nothing; ssh's `StrictModes` refuses
    the parent for the same reason."""
    (tmp_path / "work").mkdir()
    shared = tmp_path / "etc"
    shared.mkdir()
    path = shared / "config.toml"
    path.write_text(ROOTS_TOML.format(label="work", path=tmp_path / "work"))
    path.chmod(0o644)
    shared.chmod(0o777)
    try:
        with pytest.raises(
            ConfigError, match=r"etc: is writable by group or others \(mode 0777\)"
        ):
            build_config(parse_args(["--config", str(path)]))
    finally:
        shared.chmod(0o755)
    assert [r.label for r in build_config(parse_args(["--config", str(path)])).roots] == [
        "work"
    ]


def test_the_directory_is_checked_before_the_file_is_opened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The order is the point: a file in a shared directory is not read at
    all, not read and then refused."""
    (tmp_path / "work").mkdir()
    shared = tmp_path / "etc"
    shared.mkdir()
    path = _write(shared, ROOTS_TOML.format(label="work", path=tmp_path / "work"))
    shared.chmod(0o777)
    opened: list[str] = []
    real_open = os.open

    def recording_open(name: object, *args: object, **kwargs: object) -> int:
        opened.append(str(name))
        return real_open(name, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "open", recording_open)
    try:
        with pytest.raises(ConfigError, match="writable by group or others"):
            build_config(parse_args(["--config", str(path)]))
    finally:
        shared.chmod(0o755)
    assert str(path) not in opened


def test_a_symlink_left_at_the_state_files_tmp_name_is_not_written_through(
    tmp_path: Path,
) -> None:
    """With a writable state directory, `state.tmp -> ~/.ssh/authorized_keys`
    was truncated and written through on the next toggle. The write goes
    through a fresh `O_EXCL` name now, which cannot follow anything, and the
    rename replaces the name rather than the target."""
    victim = tmp_path / "authorized_keys"
    victim.write_text("ssh-ed25519 AAAA somebody\n")
    state = tmp_path / "state.toml"
    (tmp_path / "state.tmp").symlink_to(victim)
    settings.write_state(state, settings.State(hidden=frozenset({"work"})), configured={"work"})
    assert victim.read_text() == "ssh-ed25519 AAAA somebody\n"
    assert settings.read_state(state).hidden == frozenset({"work"})
    assert (tmp_path / "state.tmp").is_symlink(), "the leftover was touched"
    assert sorted(p.name for p in tmp_path.iterdir() if p.name.startswith("state.")) == [
        "state.tmp",
        "state.toml",
    ], "a temporary name was left behind"
