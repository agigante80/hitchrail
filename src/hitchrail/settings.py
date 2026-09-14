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

`~/.config/hitchrail/state.toml` is HITCHRAIL's. It holds what the interface
may change, which is one thing: which configured roots are hidden today. It
can only disable. A root the operator disabled in their file stays disabled
whatever the state file says, and a label the state file names that the
operator's file does not is ignored, so nothing a request writes can widen
the set of paths.

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
import threading
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path

from hitchrail.config import Config
from hitchrail.roots import Root, RootError, parse_root_argument
from hitchrail.sessions import (
    InvalidValue,
    OperatorDisabled,
    OperatorPinned,
    StateUnwritable,
    UnknownRoot,
)

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


def _group_is_private(gid: int, uid: int) -> bool:
    """Whether a group-writable file is still the owner's alone.

    Debian, Ubuntu and Fedora give each user a private group named after them
    and a umask of 002, so every file such a user saves is group-writable and
    refusing it would refuse the default editor on the default distribution.
    The convention that makes that umask safe is the one checked: the file's
    group is the owner's primary group and carries the owner's own name. A
    file handed to a shared group, `users` or `staff`, fails both halves.
    """
    try:
        owner = pwd.getpwuid(uid)
        group = grp.getgrgid(gid)
    except KeyError:
        return False
    return owner.pw_gid == gid and group.gr_name == owner.pw_name


def state_path_for(config_path: Path) -> Path:
    return config_path.with_name("state.toml")


@dataclass(frozen=True, slots=True)
class FileSettings:
    """What the config file said. Roots only for now; #123 adds the prefix."""

    roots: tuple[Root, ...]
    session_prefix: str | None = None


# The schema is CLOSED. A misspelt key silently ignored is a setting the
# operator believes is on, which on a file that draws the perimeter is the
# wrong kind of quiet.
_ROOT_KEYS = frozenset({"label", "path", "enabled"})
_TOP_KEYS = frozenset({"roots", "session_prefix"})


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
    # The file decides where an agent may run. One anybody on the machine can
    # edit is a root anybody on the machine can add, so it is refused the way
    # ssh refuses a permissive private key, and for the same reason.
    info = path.stat()
    mode = stat.S_IMODE(info.st_mode)
    if mode & stat.S_IWOTH or (
        mode & stat.S_IWGRP and not _group_is_private(info.st_gid, info.st_uid)
    ):
        raise SettingsError(
            f"{path}: is writable by group or others (mode {mode:04o}); anybody who "
            f"can edit it chooses where an agent may run. chmod 644 it."
        )
    try:
        data = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as exc:
        raise SettingsError(f"{path}: {exc}") from exc
    except OSError as exc:
        raise SettingsError(f"{path}: cannot be read: {exc}") from exc

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
        try:
            root = parse_root_argument(f"{label}={folder}")
        except RootError as exc:
            raise SettingsError(f"{path}: roots entry {index}: {exc}") from exc
        roots.append(Root(label=root.label, path=root.path, enabled=enabled))

    prefix = data.get("session_prefix")
    if prefix is not None and not isinstance(prefix, str):
        raise SettingsError(f"{path}: session_prefix must be a string")
    return FileSettings(roots=tuple(roots), session_prefix=prefix)


# -- the state file ------------------------------------------------------


@dataclass(frozen=True, slots=True)
class State:
    """What the interface has chosen. Two things, and both are policy about
    work the token can already do: which configured roots are hidden, and
    how long a graceful stop is waited for. Neither widens anything."""

    hidden: frozenset[str] = frozenset()
    stop_timeout: int | None = None


def read_state(path: Path) -> State:
    """An unreadable file chooses nothing: hiding a running session is the
    dangerous direction, and the operator's file is the perimeter either
    way. Each field is read on its own, so a bad timeout does not lose the
    hidden set beside it."""
    try:
        data = tomllib.loads(path.read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return State()
    disabled = data.get("disabled", [])
    hidden = (
        frozenset(label for label in disabled if isinstance(label, str))
        if isinstance(disabled, list)
        else frozenset()
    )
    timeout = data.get("stop_timeout")
    # `bool` is an `int` in Python, and `stop_timeout = true` is not a wait.
    if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout <= 0:
        timeout = None
    return State(hidden=hidden, stop_timeout=timeout)


def write_state(path: Path, state: State, configured: set[str]) -> None:
    """Only labels the operator's file configures are recorded. A label that
    is not configured is not a root, and writing it would let a request
    leave a mark for a root that does not exist yet."""
    kept = sorted(state.hidden & configured)
    body = "disabled = [" + ", ".join(f'"{label}"' for label in kept) + "]\n"
    if state.stop_timeout is not None:
        body += f"stop_timeout = {state.stop_timeout}\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    header = (
        "# Written by hitchrail: what the interface has chosen. The config file is yours.\n"
    )
    tmp.write_text(header + body)
    tmp.replace(path)


@dataclass(frozen=True, slots=True)
class RootView:
    """One configured root as the settings surface shows it. `enabled` is the
    effective answer, operator's file AND state file; `editable` is whether
    a request may change it, which is false when the operator's file says no."""

    label: str
    path: Path
    enabled: bool
    editable: bool


class Preferences:
    """The interface's powers over the configuration, and where they are kept.

    Engine state rather than `Config`, because a request changes it and a
    frozen `Config` cannot: `config.roots` stays every configured root, and
    `active_roots()` is the narrowing. A `path` of `None` keeps the choice in
    memory for the life of the process, which is what a bare `Engine(config)`
    in a test gets.

    Persist FIRST, then apply. A choice that took effect in memory and failed
    to reach the disk would revert at the next restart with nothing said.

    A flag wins outright over the state file, as it does over the config
    file: `--stop-timeout 60` on the command line is the operator pinning
    it, and the settings page shows it as not editable rather than letting
    a request write a value the next restart ignores.
    """

    def __init__(self, config: Config) -> None:
        self._config = config
        self._roots = config.roots
        self._path = config.state_path
        self._state = read_state(self._path) if self._path else State()
        # The listing route and the settings route run on different threads,
        # and two edits racing would lose one of them without this.
        self._guard = threading.Lock()

    def active_roots(self) -> tuple[Root, ...]:
        hidden = self._state.hidden
        return tuple(r for r in self._roots if r.enabled and r.label not in hidden)

    def hidden_roots(self) -> tuple[str, ...]:
        """The labels absent from the listing today, so an empty page can say
        "hidden" rather than "no projects"."""
        shown = {r.label for r in self.active_roots()}
        return tuple(r.label for r in self._roots if r.label not in shown)

    def root_views(self) -> list[RootView]:
        hidden = self._state.hidden
        return [
            RootView(
                label=r.label,
                path=r.path,
                enabled=r.enabled and r.label not in hidden,
                editable=r.enabled,
            )
            for r in self._roots
        ]

    def stop_timeout(self) -> float:
        """The wait the engine and the browser both use."""
        if self.stop_timeout_editable() and self._state.stop_timeout is not None:
            return self._state.stop_timeout
        return self._config.stop_timeout

    def stop_timeout_editable(self) -> bool:
        return self._config.sources.get("stop_timeout") != "flag"

    def stop_timeout_source(self) -> str:
        if not self.stop_timeout_editable():
            return "flag"
        return "state" if self._state.stop_timeout is not None else "default"

    def set_roots_enabled(self, changes: Mapping[str, bool]) -> None:
        """Every label checked before anything is written, so a request that
        names one unknown label changes nothing at all."""
        configured = {r.label: r for r in self._roots}
        for label in changes:
            if label not in configured:
                raise UnknownRoot(f"no configured root is labelled {label!r}")
        for label, on in changes.items():
            if on and not configured[label].enabled:
                raise OperatorDisabled(
                    f"root {label!r} is disabled in the operator's config file, "
                    f"which a request cannot undo"
                )
        with self._guard:
            hidden = set(self._state.hidden)
            for label, on in changes.items():
                (hidden.discard if on else hidden.add)(label)
            self._persist(replace(self._state, hidden=frozenset(hidden)))

    def set_stop_timeout(self, seconds: object) -> None:
        """The value passes the refusal it would pass on the command line, by
        building the `Config` it would have built: one validator (premortem
        2), and `InvalidValue` carries its words."""
        if isinstance(seconds, bool) or not isinstance(seconds, int):
            raise InvalidValue(f"stop_timeout must be a whole number of seconds: {seconds!r}")
        if not self.stop_timeout_editable():
            raise OperatorPinned(
                "stop_timeout is set on the command line, which a request cannot override"
            )
        try:
            replace(self._config, stop_timeout=seconds)
        except ValueError as exc:
            raise InvalidValue(str(exc)) from exc
        with self._guard:
            self._persist(replace(self._state, stop_timeout=seconds))

    def _persist(self, state: State) -> None:
        if self._path is not None:
            try:
                write_state(self._path, state, {r.label for r in self._roots})
            except OSError as exc:
                raise StateUnwritable(f"{self._path}: cannot be written: {exc}") from exc
        self._state = state
