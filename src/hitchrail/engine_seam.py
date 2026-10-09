"""What the sweep and the pidfd path may ask of the engine (#424).

`sweep.py` and `signals.py` were handed the whole `Engine` and reached into its
underscore members: its clock, its lock, its marker table, its derivation.
That coupled two modules to the engine's layout in a way no tool could see,
so a rename inside `Engine` broke them at run time, in the paths that kill
processes. This Protocol is the list of what they use, each member documented
where a reader of either module will look, and `tests/test_engine_seam.py`
holds both to it by reading their syntax trees: a name with a leading
underscore on the engine parameter fails the build.

`Engine` implements it with public members that return the very objects its
private ones hold (the lock, the marker table, the clock), never copies, so a
test that swaps `engine._clock` or patches `engine._announce` is still seen
by the sweep. This module is in the engine layer and imports nothing from
the web layer; `lint-imports` enforces it.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from hitchrail.config import Config
    from hitchrail.derive import Machine
    from hitchrail.events import EventBus
    from hitchrail.procs import ProcTable
    from hitchrail.restart import RestartOverlay
    from hitchrail.sessions import Session
    from hitchrail.settings import Preferences
    from hitchrail.signals import Seam
    from hitchrail.stopmarker import StopMarker
    from hitchrail.tmux import Tmux


class EngineSeam(Protocol):
    """The engine as `sweep.py` and `signals.py` see it."""

    # -- plain configuration and collaborators ----------------------------

    @property
    def config(self) -> Config:
        """The frozen configuration."""
        ...

    @property
    def prefs(self) -> Preferences:
        """What the interface may change: active roots and the stop wait."""
        ...

    @property
    def tmux(self) -> Tmux:
        """The tmux adapter, for reading a pane."""
        ...

    @property
    def kill_grace(self) -> float:
        """How long to wait for a killed agent to leave the process table."""
        ...

    @property
    def poll_interval(self) -> float:
        """The pause between those polls."""
        ...

    @property
    def end_anyway_settle(self) -> float:
        """How long `end_anyway` lets a screen settle between its two looks."""
        ...

    @property
    def pidfd(self) -> Seam:
        """The pidfd callables, `procs.py`'s unless a test injected its own."""
        ...

    # -- time ---------------------------------------------------------------

    def now(self) -> float:
        """The injected clock, so no test really waits."""
        ...

    def sleep(self, seconds: float) -> None:
        """The injected sleep."""
        ...

    # -- looking at the machine -------------------------------------------

    def look(self) -> Machine:
        """One look at the process table and tmux."""
        ...

    def process_table(self) -> ProcTable:
        """A fresh process table snapshot, for the walk up this server's tree."""
        ...

    def derive(
        self, name: str, machine: Machine, needs_a_person: frozenset[str] | None = None
    ) -> Session:
        """One row, derived from a look already taken."""
        ...

    def get(self, name: str) -> Session:
        """One row, from a look of its own."""
        ...

    def needs_a_person(self) -> frozenset[str]:
        """Every name the `awaiting_input` overlay is true for."""
        ...

    def watchers(self) -> int | None:
        """How many event subscribers are connected, or None with no bus."""
        ...

    # -- refusals the pidfd path shares with the routes -------------------

    def require_addressable(self, name: str) -> None:
        """Refuse a name that could not name a project."""
        ...

    def reject_if_not_a_project(self, name: str) -> None:
        """Refuse a name the root has never heard of."""
        ...

    # -- the two halves of a restart (#472) ---------------------------------

    def stop(self, name: str) -> Session:
        """Ask the agent to finish: the graceful stop, nothing killed."""
        ...

    def start(self, name: str, acknowledged: bool = False) -> Session:
        """Start an agent in a folder, once, with the machine's consent."""
        ...

    # -- the overlays the sweep reads and writes ------------------------------

    @property
    def stopping(self) -> dict[str, StopMarker]:
        """The in flight stop markers. Read and written under `stopping_guard`."""
        ...

    @property
    def stopping_guard(self) -> threading.Lock:
        """The lock over `stopping`, `stuck`, `awaiting_input` and the epoch."""
        ...

    @property
    def stuck(self) -> dict[str, float]:
        """Names seen waiting on a person, with when. Under `stopping_guard`."""
        ...

    @property
    def awaiting_input(self) -> set[str]:
        """Names whose last stop ended on a prompt. Under `stopping_guard`."""
        ...

    @property
    def attention_epoch(self) -> int:
        """Bumped by every clear; a sweep compares it before and after a look."""
        ...

    @property
    def attention_cleared(self) -> dict[str, int]:
        """The epoch of each name's last clear. Under `stopping_guard` (#430)."""
        ...

    @property
    def restarts(self) -> RestartOverlay:
        """Restarts pending and refused (#472). Written under `stopping_guard`."""
        ...

    def drop(self, name: str, marker: StopMarker) -> None:
        """Remove `marker`, and only it: a newer stop's stays."""
        ...

    def done_typing(self, marker: StopMarker) -> None:
        """The sequence is out, or failed: a Stop may claim the marker again."""
        ...

    def announce(self, session: Session) -> None:
        """Publish a row to the event bus. Never blocks and never raises."""
        ...


class SeamMembers:
    """`Engine`'s side of `EngineSeam`: the public names over its private ones.

    A mixin, and not members of `Engine`, because `engine.py` is held to a size
    cap and these are fourteen one line forwards. They return or call the
    private member they name and never copy it, so a test that swaps `_clock`
    or patches `_announce` on an engine is still seen by `sweep.py`. The
    declarations below say what the mixin expects of the class it joins.
    """

    if TYPE_CHECKING:
        _pidfd: Seam
        _stopping: dict[str, StopMarker]
        _stopping_guard: threading.Lock
        _stuck: dict[str, float]
        _awaiting_input: set[str]
        _attention_epoch: int
        _attention_cleared: dict[str, int]
        _restarts: RestartOverlay
        _bus: EventBus | None
        _clock: Callable[[], float]
        _sleep: Callable[[float], None]
        _procs_fn: Callable[[], ProcTable]

        def _look(self) -> Machine: ...
        def _derive(
            self, name: str, machine: Machine, needs_a_person: frozenset[str] | None = None
        ) -> Session: ...
        def _needs_a_person(self) -> frozenset[str]: ...
        def _require_addressable(self, name: str) -> None: ...
        def _reject_if_not_a_project(self, name: str) -> None: ...
        def _drop(self, name: str, marker: StopMarker) -> None: ...
        def _done_typing(self, marker: StopMarker) -> None: ...
        def _announce(self, session: Session) -> None: ...

    @property
    def pidfd(self) -> Seam:
        return self._pidfd

    @property
    def stopping(self) -> dict[str, StopMarker]:
        return self._stopping

    @property
    def stopping_guard(self) -> threading.Lock:
        return self._stopping_guard

    @property
    def stuck(self) -> dict[str, float]:
        return self._stuck

    @property
    def awaiting_input(self) -> set[str]:
        return self._awaiting_input

    @property
    def attention_epoch(self) -> int:
        return self._attention_epoch

    @property
    def attention_cleared(self) -> dict[str, int]:
        return self._attention_cleared

    @property
    def restarts(self) -> RestartOverlay:
        return self._restarts

    def now(self) -> float:
        return self._clock()

    def sleep(self, seconds: float) -> None:
        self._sleep(seconds)

    def look(self) -> Machine:
        return self._look()

    def process_table(self) -> ProcTable:
        return self._procs_fn()

    def derive(
        self, name: str, machine: Machine, needs_a_person: frozenset[str] | None = None
    ) -> Session:
        return self._derive(name, machine, needs_a_person)

    def needs_a_person(self) -> frozenset[str]:
        return self._needs_a_person()

    def watchers(self) -> int | None:
        return None if self._bus is None else self._bus.subscriber_count

    def require_addressable(self, name: str) -> None:
        self._require_addressable(name)

    def reject_if_not_a_project(self, name: str) -> None:
        self._reject_if_not_a_project(name)

    def drop(self, name: str, marker: StopMarker) -> None:
        self._drop(name, marker)

    def done_typing(self, marker: StopMarker) -> None:
        self._done_typing(marker)

    def announce(self, session: Session) -> None:
        self._announce(session)
