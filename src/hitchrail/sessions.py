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


class NoAgent(EngineError):
    """There is nothing here to ask to exit (#98).

    Distinct from `StopRefused`, and the difference is what the person should
    do next. `StopRefused` means we looked at the screen and would not risk
    typing, so the answer is to go and look. This means the state itself rules
    the action out: a `stale` session holds no agent, and a `detached` one
    holds no tmux session to type into. Nothing about the screen would change
    either answer.

    Derived rather than discovered, which is the point. The engine already
    knows both facts before it touches the machine, so refusing here costs no
    subprocess and cannot be confused with a capture that happened to fail.

    Not `NotRunning`. Something IS running in both cases, which is exactly why
    the row is not offering Start, and telling a person "there is no session"
    about a session they can see is the collapsed answer `_require_live` exists
    to avoid.
    """


class StopRefused(EngineError):
    """The graceful stop was abandoned before anything was typed (#89).

    Separate from `MachineUnreadable`, which says we could not look at the
    machine. This says we looked, and what we saw is a reason not to finish:
    the agent's input box holds text, or could not be found, or the pane could
    not be read at all. `send-keys` writes to the pty and nothing marks those
    characters as ours, so a stop command typed into a box with something
    already in it would submit the pair with the operator's authority (#91),
    and the Enter that follows it accepts whatever a dialog has highlighted.

    What that command is stays in `claude_ipc`, which is why this docstring
    does not name it: the grep guarding the quarantine cannot tell a mention
    in prose from a second copy of the sequence, and it is right not to.

    Not a state, and not a failure of the stop either. **It does not mean
    nothing was sent**, which is what this said first and is the same untruth
    #89 exists to remove: the adapter clears the box and interrupts before it
    decides, so keys have gone out and a turn may have been cut short. What did
    not happen is the request to exit, so nothing is in flight and there is no
    stop to wait for. The message carries the rest.
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

    **Still four, and #85 is where that was tested.** An agent alive inside
    another tool's tmux session was a candidate for a fifth member, `foreign`.
    It did not get one, because it differs from an orphan in nothing that
    drives behaviour: start refuses for both, a graceful stop has no pane of
    ours to type into for both, and a kill has no session of ours to kill for
    both. What differs is the sentence the row shows, and that is what
    `Session.foreign_session` carries. A state that changes no action is a word,
    and this enum is where actions are decided.
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
    # An OVERLAY on the four states, like `stopping`, and not a fifth one (#88).
    # The session really is running: the tmux session is alive and owns a live
    # agent. It is also stuck on a prompt only a person at a terminal can
    # answer, so a row that says nothing but `running` is telling the truth and
    # misleading anyway.
    awaiting_trust: bool = False
    # The second overlay of the same kind (#101): a person is needed at a
    # terminal before this agent moves. Set when a graceful stop ran out of
    # patience AND the pane was showing something that had to be answered, not
    # an ordinary input box.
    #
    # Kept apart from `awaiting_trust` rather than merged into one flag,
    # because they are found differently and cost differently: trust is a file
    # read that answers every project at once, this is one `capture-pane` on a
    # path that is rare by construction. The interface says a different thing
    # for each, which is the point of knowing which it was.
    awaiting_input: bool = False
    # The tmux session that owns this agent when it is not one of ours (#85).
    # An overlay like the two above, and a NAME rather than a boolean on
    # purpose: a flag plus a name is two facts that can disagree, and the name
    # is the only part a person can act on. It is what turns "your agent is
    # orphaned" into "your agent is in cc-vessel, attach there".
    #
    # **`None` means we could not see an owner, not that there is none.**
    # Ownership is read from `list-panes -a`, which covers the tmux server on
    # our own socket and nothing else, so an agent under a different socket,
    # under screen, or under a bare terminal comes back `None`. Anything
    # rendering this has to say "no session Hitchrail can address" rather than
    # "no tmux session", which is what the row used to claim and could not know.
    foreign_session: str | None = None

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
            "awaiting_trust": self.awaiting_trust,
            "awaiting_input": self.awaiting_input,
            "foreign_session": self.foreign_session,
        }
