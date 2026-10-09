"""The config file, and the state file beside it (#154).

Two files, two owners, and the split is the security argument.

`~/.config/hitchrail/config.toml` is the OPERATOR's. It names the roots, which
is the perimeter: control 5 says a project resolves to a direct child of a
configured root and nothing else on the machine is reachable, and everything
downstream rests on that set being chosen by whoever started the process and
being immutable while it runs. Hitchrail reads this file once at startup and
never writes it. A route that added a root would remove the control, and a
process that rewrote the file that defines it would be the same power one
step removed.

`~/.config/hitchrail/state.toml` is HITCHRAIL's, and lives in `statefile.py`
(#443): what the interface may change, and the only half a request writes. It
can only disable, so nothing a request writes can widen the set of paths. It
is read by this module's `_read_private`, so the one mode and directory rule
holds both files.

Both are read through the same `Root` objects `--root` builds, and `Config`
refuses them the same way. Nothing here validates a root; that is the rule
that keeps one validator, and premortem 2 of the Phase 14 plan is the
alternative.
"""

from __future__ import annotations

import grp
import os
import pwd
import stat
import tomllib
from dataclasses import dataclass
from pathlib import Path

from hitchrail.projectnames import explain_name
from hitchrail.roots import Root, RootError, parse_root_argument

# The XDG base directory. Honoured, rather than `~/.config` hardcoded, because
# the user unit in `packaging/hitchrail.service` is the deployment this file
# exists for, and a unit can set it.
CONFIG_HOME_ENV = "XDG_CONFIG_HOME"


class SettingsError(ValueError):
    """The config file cannot be used. A `ValueError` like every other startup
    refusal, so `cli.main` reports it and exits 2 without a traceback."""


def default_config_path() -> Path:
    base = os.environ.get(CONFIG_HOME_ENV) or str(Path.home() / ".config")
    return Path(base) / "hitchrail" / "config.toml"


def _read_private(path: Path) -> str:
    """The file's bytes, once its mode and owner say nobody else could have
    written them.

    The file decides where an agent may run. One anybody on the machine can
    edit is a root anybody on the machine can add, so it is refused the way
    ssh's `StrictModes` refuses a permissive private key, and for the same
    reason: writable by others, writable by a group that is not the owner's
    own, or owned by somebody who is not the user running this (root
    excepted, who can edit anything regardless). The security audit of the
    first version found the owner unchecked: a colleague's 644 file passed.

    One descriptor for the check and the read, so the mode and the bytes come
    from the same inode rather than a file swapped in between a `stat` and a
    `read_text`.
    """
    # The DIRECTORY first, by the same rule (#270). A parent others can
    # write to is a parent others can `mv` a fresh 644 file into, over this
    # one, so a private file in a shared directory is private until the
    # next rename. ssh's `StrictModes` refuses a writable parent for the
    # same reason. Not `fstat` of the open file's directory: there is no
    # descriptor for "the directory this name resolved through", and the
    # window between the two stats is the same one the rename needs anyway.
    _refuse_if_shared(path.parent, path.parent.stat(), "the directory holding it")
    # And the directory the NAME resolves into (#281): a config path that is
    # a symlink is opened at its target, so a 0777 directory there let anyone
    # rename a file over the target. Both, since the lexical one holds the
    # link and whoever can replace the link chooses the target.
    real = path.resolve()
    if real.parent != path.parent:
        _refuse_if_shared(real.parent, real.parent.stat(), "the directory it resolves into")
    fd = os.open(real, os.O_RDONLY)
    try:
        info = os.fstat(fd)
        _refuse_if_shared(path, info, "it")
        chunks = []
        while chunk := os.read(fd, 65536):
            chunks.append(chunk)
    finally:
        os.close(fd)
    try:
        return b"".join(chunks).decode()
    except UnicodeDecodeError as exc:
        # A `ValueError`, so neither the `OSError` nor the `TOMLDecodeError`
        # arm in the caller catches it, and it was a traceback (#270).
        raise SettingsError(f"{path}: is not UTF-8 ({exc}); a config file is text") from exc


def _refuse_if_shared(path: Path, info: os.stat_result, what: str) -> None:
    """The one rule, for the file and for its directory: owned by the user
    running this (or root), and writable by nobody else."""
    mode = stat.S_IMODE(info.st_mode)
    if info.st_uid not in (os.geteuid(), 0):
        raise SettingsError(
            f"{path}: is owned by uid {info.st_uid}, not by the user running "
            f"hitchrail; whoever owns {what} chooses where an agent may run"
        )
    if mode & stat.S_IWOTH or (
        mode & stat.S_IWGRP and not _group_is_private(info.st_gid, info.st_uid)
    ):
        raise SettingsError(
            f"{path}: is writable by group or others (mode {mode:04o}); anybody who "
            f"can edit {what} chooses where an agent may run. chmod 644 the file "
            f"and 755 the directory."
        )


def _group_is_private(gid: int, uid: int) -> bool:
    """Whether a group-writable file is still the owner's alone.

    Debian, Ubuntu and Fedora give each user a private group named after them
    and a umask of 002, so every file such a user saves is group-writable and
    refusing it would refuse the default editor on the default distribution.
    The convention that makes that umask safe is the one checked: the file's
    group is the owner's primary group, carries the owner's own name, and has
    no other members. A file handed to a shared group, `users` or `staff`,
    fails the first two; a private group
    that `usermod -aG alice bob` has given a second member is private in name
    only and fails the third (`gr_mem` lists the supplementary members, and
    everybody there but the owner is somebody else).
    """
    try:
        owner = pwd.getpwuid(uid)
        group = grp.getgrgid(gid)
    except KeyError:
        return False
    # The owner listed in their own group (`alice:x:1000:alice`, which LDAP
    # `memberUid` and `gpasswd -a alice alice` both produce) is still alone.
    others = set(group.gr_mem) - {owner.pw_name}
    return owner.pw_gid == gid and group.gr_name == owner.pw_name and not others


def state_path_for(config_path: Path) -> Path:
    return config_path.with_name("state.toml")


@dataclass(frozen=True, slots=True)
class FileSettings:
    """What the config file said. Roots only for now; #123 adds the prefix."""

    roots: tuple[Root, ...]
    session_prefix: str | None = None
    stop_prompt: str | None = None
    stop_prompt_timeout: int | None = None
    stop_policy: str | None = None


# The schema is CLOSED. A misspelt key silently ignored is a setting the
# operator believes is on, which on a file that draws the perimeter is the
# wrong kind of quiet.
_ROOT_KEYS = frozenset({"label", "path", "enabled"})
_TOP_KEYS = frozenset(
    {"roots", "session_prefix", "stop_prompt", "stop_prompt_timeout", "stop_policy"}
)


def read_config_file(path: Path) -> FileSettings:
    """The file, or an empty settings object when there is none.

    A missing file is not an error: the flags are the other door, and a
    machine with neither gets the existing "no roots configured" refusal
    from `Config`. A file that does not parse IS an error, named with its
    line, and starts nothing: a partial set is the drift this file exists
    to end.
    """
    if not path.is_file():
        return FileSettings(roots=())
    try:
        text = _read_private(path)
    except OSError as exc:
        raise SettingsError(f"{path}: cannot be read: {exc}") from exc
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise SettingsError(f"{path}: {exc}") from exc

    unknown = set(data) - _TOP_KEYS
    if unknown:
        raise SettingsError(
            f"{path}: unknown key {sorted(unknown)[0]!r}; the keys are {sorted(_TOP_KEYS)}"
        )
    raw_roots = data.get("roots", [])
    if not isinstance(raw_roots, list):
        raise SettingsError(f"{path}: `roots` must be a list of tables, `[[roots]]`")
    roots: list[Root] = []
    for index, entry in enumerate(raw_roots, start=1):
        if not isinstance(entry, dict):
            raise SettingsError(f"{path}: roots entry {index} is not a table")
        stray = set(entry) - _ROOT_KEYS
        if stray:
            raise SettingsError(
                f"{path}: roots entry {index} has an unknown key {sorted(stray)[0]!r}; "
                f"the keys are {sorted(_ROOT_KEYS)}"
            )
        label = entry.get("label", "")
        folder = entry.get("path", "")
        enabled = entry.get("enabled", True)
        if not isinstance(label, str) or not isinstance(folder, str):
            raise SettingsError(f"{path}: roots entry {index}: label and path must be strings")
        if not isinstance(enabled, bool):
            raise SettingsError(f"{path}: roots entry {index}: enabled must be true or false")
        # THE SAME PARSER AS THE FLAG, fed the same `label=path` text. That is
        # what makes the refusals identical rather than similar: an empty
        # label, an empty path and a label the allowlist refuses are refused
        # here in the flag's own words, and the directory, duplicate and
        # nesting refusals happen later in `Config`, once, for both doors.
        #
        # Except one character. The flag splits on the first `=`, so a label
        # `a=b` composed into `a=b=/x` parsed as label `a` at `<cwd>/b=/x`
        # (#270): the allowlist refuses `=` and never got to see it. The
        # same validator, asked first, so it is still one; an EMPTY label
        # is left to the parser, whose words for it the tests pin.
        complaint = explain_name(label) if label else None
        if complaint is not None:
            raise SettingsError(
                f"{path}: roots entry {index}: root label {label!r} is not usable: {complaint}"
            )
        try:
            root = parse_root_argument(f"{label}={folder}")
        except RootError as exc:
            raise SettingsError(f"{path}: roots entry {index}: {exc}") from exc
        roots.append(Root(label=root.label, path=root.path, enabled=enabled))

    prefix = data.get("session_prefix")
    if prefix is not None and not isinstance(prefix, str):
        raise SettingsError(f"{path}: session_prefix must be a string")
    # #242. Type only, here: what a usable prompt or wait IS lives in
    # `Config`, which refuses the flag and the file in the same words.
    prompt = data.get("stop_prompt")
    if prompt is not None and not isinstance(prompt, str):
        raise SettingsError(f"{path}: stop_prompt must be a string")
    wait = data.get("stop_prompt_timeout")
    # `bool` is an `int` in Python, and `stop_prompt_timeout = true` is not a wait.
    if wait is not None and (isinstance(wait, bool) or not isinstance(wait, int)):
        raise SettingsError(f"{path}: stop_prompt_timeout must be a whole number of seconds")
    policy = data.get("stop_policy")
    if policy is not None and not isinstance(policy, str):
        raise SettingsError(f"{path}: stop_policy must be a string")
    return FileSettings(
        roots=tuple(roots),
        session_prefix=prefix,
        stop_prompt=prompt,
        stop_prompt_timeout=wait,
        stop_policy=policy,
    )
