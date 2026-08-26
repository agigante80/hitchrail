"""What a session IS, and every refusal the engine can make.

Split out of `engine.py` along the same seam `hostnames.py` used: the
vocabulary in one module, the thing that derives and drives it in another.

Phase 5 imports the exceptions wholesale to map them to status codes, and
Phase 6 is written against `Session.as_dict()`, so both are a contract with
layers above rather than engine internals. Keeping them here means the API can
import what it maps from without importing the engine that raises it.

Nothing here imports `engine`. The dependency runs one way, and a test asserts
it.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class EngineError(Exception):
    """Anything the engine refuses to do, and the base the API maps from."""


class UnknownProject(EngineError):
    """No such folder in the root."""


class AlreadyRunning(EngineError):
    """There is already an agent in this folder."""


class NotRunning(EngineError):
    """There is nothing here to stop."""


class Protected(EngineError):
    """This is the session Hitchrail is running inside.

    Stopping it takes the interface down with it and has no undo, so it is
    refused rather than confirmed.
    """


class Locked(EngineError):
    """A start is already in flight for this folder.

    Answered immediately rather than by blocking. A web interface makes double
    submission easy, and holding the second request open behind a lock ties up
    a worker thread to say something already known.
    """


class StartFailed(EngineError):
    """The agent never appeared.

    Carries the pane output, because "it did not start" without the reason is
    a support request rather than an error message.
    """

    def __init__(self, output: str) -> None:
        super().__init__("the session did not start")
        self.output = output


class _MemoryVerdict(EngineError):
    def __init__(self, available_mb: int, needed_mb: int) -> None:
        super().__init__(f"{available_mb} MB available, {needed_mb} MB needed for a session")
        self.available_mb = available_mb
        self.needed_mb = needed_mb


class MemoryRefused(_MemoryVerdict):
    """Below the hard floor. Refused outright."""


class MemoryNeedsAck(_MemoryVerdict):
    """Between the floors. Proceeds only with an explicit acknowledgement.

    A third outcome, not a rounding of the other two. Collapsing it into
    either removes the confirmation step the design asks for.
    """


class MachineUnreadable(EngineError):
    """The process table could not be read, so no state can be derived.

    An ERROR rather than a state, deliberately. `ProcTable.ok` distinguishes
    "nothing is running" from "we could not look", and rendering the second as
    the first tells the user something false about their machine: every running
    agent would appear as `stale` or `stopped`. The design settles it, "if
    Hitchrail cannot determine a session's state, it says so rather than
    guessing", and it must not become a fifth state, because the table below
    has four and the in flight stop is an overlay rather than a member.

    Note this is NOT the same as tmux returning no sessions. An empty pane map
    is the ordinary state of a machine with nothing started.
    """


class State(StrEnum):
    """A `StrEnum` so the wire format is the NAME.

    An `IntEnum` would put the ordering into the API, and inserting a fifth
    member later would change what an old client reads.
    """

    RUNNING = "running"
    STALE = "stale"
    DETACHED = "detached"
    STOPPED = "stopped"


@dataclass(frozen=True)
class Session:
    """One project's derived state. Frozen: nothing holds one and mutates it."""

    name: str
    state: State
    pid: int | None = None
    ram_mb: int = 0
    uptime_s: int = 0
    url: str | None = None
    stopping: bool = False
    protected: bool = False

    def as_dict(self) -> dict[str, object]:
        """Serialising a session is not HTTP knowledge.

        The engine needs this to publish events, the import contract forbids
        borrowing a formatter from the server, and a second copy of this shape
        would drift from the first.
        """
        return {
            "name": self.name,
            "state": str(self.state),
            "pid": self.pid,
            "ram_mb": self.ram_mb,
            "uptime_s": self.uptime_s,
            "url": self.url,
            "stopping": self.stopping,
            "protected": self.protected,
        }
