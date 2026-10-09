"""Hitchrail's state file, and the interface's powers over the configuration.

`~/.config/hitchrail/state.toml` is HITCHRAIL's, the half of #154 that a
request may write. It holds what the interface may change: which configured
roots are hidden today, how long a graceful stop is waited for, and the stop
policy. It can only disable. A root the operator disabled in their file stays
disabled whatever the state file says, and a label the state file names that
the operator's file does not is ignored, so nothing a request writes can widen
the set of paths.

Split from `settings.py` in #443 along the seam the module docstring there
draws: the operator's file is read once and never written, this one is
written. The mode and directory rule is not restated here. It is
`settings._read_private` and `settings._refuse_if_shared`, imported rather
than copied so the state file is held to the operator file's rule by the same
code (#281, #397). The import runs one way, `statefile` to `settings`.
"""

from __future__ import annotations

import os
import tempfile
import threading
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import cast

from hitchrail.config import MAX_STOP_TIMEOUT_S, STOP_POLICIES, Config
from hitchrail.roots import Root
from hitchrail.sessions import (
    InvalidValue,
    OperatorDisabled,
    OperatorPinned,
    StateUnwritable,
    UnknownRoot,
)
from hitchrail.settings import SettingsError, _read_private, _refuse_if_shared


@dataclass(frozen=True, slots=True)
class State:
    """What the interface has chosen. Three things, and all are policy about
    work the token can already do: which configured roots are hidden, how
    long a graceful stop is waited for, and whether a stop that ends on a
    question is ended (#409). The last is a kill nobody tapped, but only of a
    session a request already asked to stop, which the same token could Kill
    outright; it widens no route."""

    hidden: frozenset[str] = frozenset()
    stop_timeout: int | None = None
    stop_policy: str | None = None


def read_state(path: Path) -> State:
    return load_state(path)[0]


def load_state(path: Path) -> tuple[State, str | None]:
    """The state, and why the file was refused, if it was.

    An unreadable file chooses nothing: hiding a running session is the
    dangerous direction, and the operator's file is the perimeter either
    way. Each field is read on its own, so a bad timeout does not lose the
    hidden set beside it.

    Read by the operator file's rule, `_read_private`, decided rather than
    exempted (#281): a hidden root is the dangerous direction, so a state
    file somebody else could write hides nothing. Refused or not UTF-8, it
    is unreadable, and chooses nothing. The reason is returned rather than
    dropped (#397), so the start can say every saved choice was forgotten;
    a file that is not there yet is a first start, not a refusal."""
    try:
        data = tomllib.loads(_read_private(path))
    except FileNotFoundError:
        # A symlink whose target is gone opens as "not found" too, and is not
        # a first start: the operator pointed the name somewhere, so every
        # saved choice vanishing needs saying (#434).
        if path.is_symlink():
            return State(), f"is a symlink to {path.readlink()}, which does not exist"
        return State(), None
    except OSError as exc:
        return State(), f"cannot be read: {exc}"
    except (SettingsError, tomllib.TOMLDecodeError) as exc:
        return State(), str(exc)
    disabled = data.get("disabled", [])
    hidden = (
        frozenset(label for label in disabled if isinstance(label, str))
        if isinstance(disabled, list)
        else frozenset()
    )
    timeout = data.get("stop_timeout")
    # `bool` is an `int` in Python, and `stop_timeout = true` is not a wait.
    # The ceiling applies here too (#265): a state file written before it
    # existed, or by hand, is not a way past the one validator.
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, int)
        or timeout <= 0
        or timeout > MAX_STOP_TIMEOUT_S
    ):
        timeout = None
    # Anything but a known policy chooses nothing, which is `ask`: a state
    # file must never be the way an unknown word reaches the engine.
    policy = data.get("stop_policy")
    if policy not in STOP_POLICIES:
        policy = None
    return State(hidden=hidden, stop_timeout=timeout, stop_policy=policy), None


def write_state(path: Path, state: State, configured: set[str]) -> None:
    """Only labels the operator's file configures are recorded. A label that
    is not configured is not a root, and writing it would let a request
    leave a mark for a root that does not exist yet."""
    kept = sorted(state.hidden & configured)
    body = "disabled = [" + ", ".join(f'"{label}"' for label in kept) + "]\n"
    if state.stop_timeout is not None:
        body += f"stop_timeout = {state.stop_timeout}\n"
    if state.stop_policy is not None:
        body += f'stop_policy = "{state.stop_policy}"\n'
    path.parent.mkdir(parents=True, exist_ok=True)
    # The read's directory rule, so a save never succeeds where the next
    # start's read refuses and forgets it (#397). The lexical parent only:
    # the read also checks where a symlinked `state.toml` resolves, but the
    # rename below replaces the link with a file in this directory.
    _refuse_if_shared(path.parent, path.parent.stat(), "the directory holding it")
    header = (
        "# Written by hitchrail: what the interface has chosen. The config file is yours.\n"
    )
    # A FRESH name, never a fixed `state.tmp` (#270): `write_text` on a
    # fixed name follows a symlink somebody left there, so with a writable
    # state directory `state.tmp -> ~/.ssh/authorized_keys` was truncated
    # and written through on the next toggle. `mkstemp` opens with
    # `O_CREAT | O_EXCL`, which cannot follow anything, and the rename onto
    # `state.toml` replaces the name, not the target of whatever it was.
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix="state.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(header + body)
        Path(tmp).replace(path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


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
        self._state, self._refusal = load_state(self._path) if self._path else (State(), None)
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

    def hidden_roots_a_request_can_show(self) -> tuple[str, ...]:
        """Of those, the ones the settings page has a checkbox for (#256).

        A root the OPERATOR'S file disables is not one of them: it is hidden
        and no request can bring it back, so telling somebody to "show one in
        settings" sends them to a page where it is greyed out. The same
        `enabled` that `root_views` reports as `editable`, asked here so the
        listing can carry the distinction the empty state needs.
        """
        shown = {r.label for r in self.active_roots()}
        return tuple(r.label for r in self._roots if r.label not in shown and r.enabled)

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

    def stop_policy(self) -> str:
        """What the engine does with a stop that ends on a question (#239)."""
        if self.stop_policy_editable() and self._state.stop_policy is not None:
            return self._state.stop_policy
        return self._config.stop_policy

    def stop_policy_editable(self) -> bool:
        """Pinned by the config file too, not only by a flag, unlike
        `stop_timeout`, which the file cannot set. The operator's file is the
        operator's: a line in it saying `ask` is a choice made on the machine,
        and a request overriding it would be the page outranking the person
        who configured the server (#409)."""
        return self._config.sources.get("stop_policy") not in ("flag", "file")

    def stop_policy_source(self) -> str:
        if not self.stop_policy_editable():
            return self._config.sources["stop_policy"]
        return "state" if self._state.stop_policy is not None else "default"

    def _pin_words(self, what: str = "stop policy") -> str:
        key = what.replace(" ", "_")
        if self._config.sources.get(key) == "flag":
            return "on the command line"
        return "in the operator's config file"

    def startup_warnings(self) -> tuple[str, ...]:
        """What the state file holds that this start does not apply, for the
        CLI to log once beside the startup block.

        A saved policy under a pin is REPORTED, not cleared (#421): clearing
        would be Hitchrail rewriting a choice because of a line in a file it
        never writes, and the report is enough for the operator removing the
        pin to know what comes back. Said only when the two differ, since only
        then does removing the pin change anything.
        """
        if self._refusal is not None:
            reason = self._refusal.rstrip(".")
            return (
                f"state file {self._path} refused, so nothing saved from the "
                f"settings page applies: {reason}. {self._next_save_words()}",
            )
        return tuple(
            warning
            for warning in (
                self._pinned_warning(
                    "stop policy",
                    self._state.stop_policy,
                    self._config.stop_policy,
                    self.stop_policy_editable(),
                ),
                self._pinned_warning(
                    "stop timeout",
                    self._state.stop_timeout,
                    self._config.stop_timeout,
                    self.stop_timeout_editable(),
                ),
            )
            if warning is not None
        )

    def _pinned_warning(
        self, what: str, saved: object, pinned: object, editable: bool
    ) -> str | None:
        """One pinnable key's report (#434); nothing when the two agree."""
        if saved is None or editable or saved == pinned:
            return None
        return (
            f"{what} {saved!r}, saved from the settings page, is overridden by "
            f"{pinned!r} set {self._pin_words(what)}; removing that "
            f"setting puts {saved!r} back in force"
        )

    def _next_save_words(self) -> str:
        """What the first toggle does to a refused file: replaces it, losing
        what it held, unless the DIRECTORY is the refusal, where the save is
        refused too (#397)."""
        assert self._path is not None
        try:
            _refuse_if_shared(self._path.parent, self._path.parent.stat(), "the directory")
        except (OSError, SettingsError):
            return "A save from the settings page is also refused until that is fixed."
        return (
            "The next save from the settings page replaces it, and what it "
            "holds is lost; fix it first to keep those choices."
        )

    def set_roots_enabled(self, changes: Mapping[str, bool]) -> None:
        self.apply(roots=changes)

    def set_stop_timeout(self, seconds: object) -> None:
        self.apply(stop_timeout=seconds)

    def apply(
        self,
        roots: Mapping[str, bool] = {},
        stop_timeout: object = None,
        stop_policy: object = None,
    ) -> None:
        """One request, one write. EVERYTHING is checked before anything is
        persisted, so a body that names one unknown label, or a valid toggle
        beside a timeout of zero, changes nothing at all: round 1 of the
        Phase 14 review found the halves applied in sequence, with the
        first written before the second was refused.

        The timeout meets the command line's refusal, `check_stop_timeout`,
        not a whole `Config`, which re-read the TLS key per PATCH (#267): one
        validator (premortem 2), and `InvalidValue` carries its words.
        """
        configured = {r.label: r for r in self._roots}
        for label in roots:
            if label not in configured:
                raise UnknownRoot(f"no configured root is labelled {label!r}")
        for label, on in roots.items():
            if on and not configured[label].enabled:
                raise OperatorDisabled(
                    f"root {label!r} is disabled in the operator's config file, "
                    f"which a request cannot undo"
                )
        if stop_timeout is not None:
            if isinstance(stop_timeout, bool) or not isinstance(stop_timeout, int):
                raise InvalidValue(
                    f"stop_timeout must be a whole number of seconds: {stop_timeout!r}"
                )
            if not self.stop_timeout_editable():
                raise OperatorPinned(
                    "stop_timeout is set on the command line, which a request cannot override"
                )
            try:
                Config.check_stop_timeout(stop_timeout)
            except ValueError as exc:
                raise InvalidValue(str(exc)) from exc
        policy: str | None = None
        if stop_policy is not None:
            if not self.stop_policy_editable():
                raise OperatorPinned(
                    f"stop_policy is set {self._pin_words()}, which a request cannot override"
                )
            # The one validator refuses anything but the two words, a
            # non string included, so the cast claims nothing it does not.
            policy = cast(str, stop_policy)
            try:
                Config.check_stop_policy(policy)
            except ValueError as exc:
                raise InvalidValue(str(exc)) from exc
        with self._guard:
            hidden = set(self._state.hidden)
            for label, on in roots.items():
                (hidden.discard if on else hidden.add)(label)
            state = replace(self._state, hidden=frozenset(hidden))
            if stop_timeout is not None:
                state = replace(state, stop_timeout=stop_timeout)
            if policy is not None:
                state = replace(state, stop_policy=policy)
            # Nothing to say, nothing written: `PATCH {}` on a read only
            # config directory answered 503 for a request that changed
            # nothing (Phase 14 review, round 2).
            if state != self._state:
                self._persist(state)

    def _persist(self, state: State) -> None:
        if self._path is not None:
            try:
                write_state(self._path, state, {r.label for r in self._roots})
            except (OSError, SettingsError) as exc:
                raise StateUnwritable(f"{self._path}: cannot be written: {exc}") from exc
        self._state = state
