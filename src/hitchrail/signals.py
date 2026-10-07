"""Ending an agent nothing addressable owns, by pid, through a handle (#107).

The one destructive path in Hitchrail that is not scoped by the tmux prefix,
so it is scoped by a check. It has its own seam (the pidfd callables in
`procs.py`), its own refusals and its own safety argument (design 5.2b), and
it depends on nothing in the stop machinery beside it in `engine.py`, which
is why it left that file at #274: a reader auditing what can signal a process
by pid should find one file, and `tests/test_source_guards.py` holds it to
being this one.

`Engine.signal_detached` is a one line delegate, so the route and the tests
reach it where they always did. The function here takes the engine for its
derivation, its refusals and its announcement. `engine` imports this module
and this module names `Engine` for the type checker only, so the two do not
form an import cycle at run time.

This module is in the engine layer and imports nothing from the web layer;
`lint-imports` enforces it.
"""

from __future__ import annotations

import errno
import os
import signal
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from hitchrail import procs
from hitchrail.procs import ProcTable
from hitchrail.roots import split_identifier
from hitchrail.sessions import (
    EngineError,
    Gone,
    MachineUnreadable,
    NotDetached,
    NotOurs,
    OwnedElsewhere,
    PidfdUnavailable,
    Protected,
    Session,
    State,
    UnknownProject,
)

if TYPE_CHECKING:
    from hitchrail.engine import Engine

_NO_PIDFD = (
    "this machine cannot signal through a race free handle (no pidfd support), "
    "and Hitchrail will not fall back to signalling a bare pid"
)


def _refusal_for(exc: OSError, pid: int, verb: str, *, opening: bool = False) -> EngineError:
    """Which refusal an errno is (#107).

    EPERM means different things at the two calls, which is why `opening`
    exists (#272). `pidfd_send_signal(2)` documents EPERM as "does not have
    permission to send the signal to the target process", the kernel's own
    ownership refusal and the backstop the uid check only anticipates.
    `pidfd_open(2)` documents no EPERM at all: EINVAL, EMFILE, ENFILE,
    ENODEV, ENOMEM and ESRCH, and nothing else. So an EPERM there is not
    about the target: it is seccomp or an LSM refusing the syscall to US,
    and reporting that as "not ours to signal" sends the operator looking at
    the wrong process. `pidfd_unavailable` is what that is, the same answer
    as a kernel without the syscall, and the route already refuses rather
    than falling back to a bare pid.
    """
    if exc.errno == errno.ESRCH:
        return Gone(f"pid {pid} is gone, so there is nothing to {verb}")
    if exc.errno == errno.EPERM and not opening:
        return NotOurs(f"the kernel refused to {verb} pid {pid}: it is not ours to signal")
    if exc.errno == errno.EPERM:
        return PidfdUnavailable(
            f"the kernel refused a handle to pid {pid} (EPERM), which pidfd_open does not "
            f"return for ownership: something on this machine, a seccomp filter or an LSM, "
            f"denies the syscall. " + _NO_PIDFD
        )
    if exc.errno in (errno.ENOSYS, errno.EINVAL, errno.EOPNOTSUPP):
        return PidfdUnavailable(_NO_PIDFD)
    # EMFILE, ENFILE, ENOMEM: the machine, not the process.
    return MachineUnreadable(f"cannot {verb} pid {pid}: {exc}")


@dataclass(frozen=True)
class Seam:
    """#107. The pidfd seam, the callables from `procs.py`; a test hands in a
    recorder. Held as fields so a test that must prove the ORDER, handle
    before verification, can watch both through one fake."""

    open_pidfd: Callable[[int], int]
    send_signal: Callable[[int, int], None]
    close_pidfd: Callable[[int], None]
    owner_uid: Callable[[int], int]
    cwd_of: Callable[[int], Path]

    @classmethod
    def with_defaults(
        cls,
        open_pidfd: Callable[[int], int] | None = None,
        send_signal: Callable[[int, int], None] | None = None,
        close_pidfd: Callable[[int], None] | None = None,
        owner_uid: Callable[[int], int] | None = None,
        cwd_of: Callable[[int], Path] | None = None,
    ) -> Seam:  # pragma: no mutate block
        # Through the module attribute, when the engine is built, and never
        # imported by name: `tests/conftest.py` patches `hitchrail.procs.cwd_of`
        # so no engine reads a real `/proc` for a fake pid, and a name bound
        # when this module was imported would never see that patch.
        #
        # Never mutated, and not for want of a test. An `or` turned `and`
        # here hands a hermetic test's fake pid or fake descriptor to the
        # REAL syscall, so a sweep would `pidfd_open` whatever this machine
        # runs as pid 900, or `os.close` a descriptor the test runner owns.
        return cls(
            open_pidfd=open_pidfd or procs.open_pidfd,
            send_signal=send_signal or procs.send_signal,
            close_pidfd=close_pidfd or procs.close_pidfd,
            owner_uid=owner_uid or procs.owner_uid,
            cwd_of=cwd_of or procs.cwd_of,
        )


def signal_detached(
    engine: Engine, name: str, force: bool = False, seen_pid: int | None = None
) -> Session:
    """End an agent nothing addressable owns, through a handle (#107).

    The one destructive path that is not scoped by the tmux prefix, so
    it is scoped by a check, and the check is only sound in this order:
    **acquire the handle, then verify, then signal through the handle.**
    A pidfd refers to one process for as long as it is open; a pid reused
    between the listing and the call is a different process the handle
    does not refer to, and one that exited is `ESRCH` at the send. Verify
    before open, and the window is open again, the same argument as
    reading `ps` before tmux in `derive.look`.

    What the handle buys, exactly: a stranger is never signalled. What it
    does not buy is "the process derivation identified" in the strong
    sense, since the anchor is an argv suffix and a DIFFERENT agent for
    the same project passes verification. That is the operator's own
    agent for that project either way, and the confirmation sentence
    covers it: "Hitchrail can see no session that owns this agent. If it
    is open on a screen somewhere, this will end it there too."

    Refused before any handle is opened: the protected project, the
    process tree this server runs in, a row that is not detached, an
    owner Hitchrail can SEE (attach there instead), and another user's
    process. Nothing here ever falls back to `os.kill`.

    **The uid check before the open is advisory, and the refusals after
    the handle are the property** (#272). `owner_uid` stats
    `/proc/<pid>` before there is a handle, so a pid reused by another
    user's process in that window passes it; what actually refuses that
    process is the readlink of its working directory, which is not
    readable to us and raises `NotOurs` below, and under a non root
    Hitchrail the kernel's own EPERM at `pidfd_send_signal`. Running
    Hitchrail as root removes the second of those, which is one more
    reason the unit does not. The early check stays because it answers
    in the right words a moment sooner and costs one `stat`.

    `force` is SIGKILL, and it is a second explicit request on its own
    route, never the default: #169's rule that a kill is always available
    and never what happens first.

    `seen_pid` is the pid the person confirmed (#279). Without it, the
    agent signalled is whichever one derivation picks NOW, which may be a
    second agent for the same folder that started after the row was drawn:
    ours, and not the one the confirmation was about. With it, a mismatch
    is `NotOurs` before any handle, and the verification after the handle
    holds the derived pid, so the binding lasts through to the send.
    Optional, so a client that sends no body keeps today's behaviour.
    """
    engine._require_addressable(name)
    # The label names the root whose child the process must be running
    # in, checked after the handle below (#264). Not the listing: the
    # review's first version refused a folder the root no longer listed,
    # which made a detached agent in a renamed folder unreachable on the
    # one route that reaches past tmux, and scanned every root, so an
    # unplugged spare root refused every project. The tmux routes are
    # prefix scoped and never needed either.
    label, _ = split_identifier(name)
    root = next((r for r in engine.config.roots if r.label == label), None)
    if root is None:
        raise UnknownProject(name)
    session = engine.get(name)
    if session.protected:
        raise Protected(name)
    if session.state is State.STOPPED:
        # Unknown and stopped are two answers, as on stop and kill.
        engine._reject_if_not_a_project(name)
    if session.state is not State.DETACHED or session.pid is None:
        raise NotDetached(
            f"{name} is {session.state.value}, and this route is for an agent "
            "no session owns; use stop or kill for a session"
        )
    if session.held_elsewhere is not None:
        raise OwnedElsewhere(name, session.foreign_session, session.foreign_server_pid)
    pid = session.pid
    if seen_pid is not None and seen_pid != pid:
        raise NotOurs(
            f"the row moved: pid {seen_pid} was shown for {name} and its agent is "
            f"now pid {pid}, so nothing was signalled. Look again before ending it"
        )
    _refuse_our_own_tree(engine._procs_fn, pid)
    try:
        if engine._pidfd.owner_uid(pid) != os.getuid():
            raise NotOurs(f"pid {pid} belongs to another user on this machine")
    except OSError as exc:
        raise Gone(f"pid {pid} is gone: {exc}") from exc

    try:
        pidfd = engine._pidfd.open_pidfd(pid)
    except AttributeError as exc:
        raise PidfdUnavailable(_NO_PIDFD) from exc
    except OSError as exc:
        raise _refusal_for(exc, pid, "open a handle to", opening=True) from exc
    try:
        # AFTER the handle: what the machine says now is what is signalled.
        # ONE look, and the classification below reads the same table the
        # row was derived from (#272). It used to take a fresh `ps` on the
        # error path, so a pid that changed identity and then exited
        # between the two reads was reported as `gone` when the row that
        # refused it had seen it alive under another identity: two
        # refusals for one instant, chosen by which read happened to win.
        machine = engine._look()
        verified = engine._derive(name, machine)
        if verified.state is not State.DETACHED or verified.pid != pid:
            # Two answers, told apart on the error path only: the pid is
            # gone from the table, or it is there under another identity.
            # A table that could not be read says neither.
            table = machine.table
            if not table.ok:
                raise MachineUnreadable("the process table could not be read after the handle")
            if pid not in table.by_pid:
                raise Gone(f"pid {pid} left between the listing and this request")
            raise NotOurs(
                f"pid {pid} is no longer the agent for {name}: it changed identity "
                "between the listing and this request, so nothing was signalled"
            )
        if verified.held_elsewhere is not None:
            raise OwnedElsewhere(name, verified.foreign_session, verified.foreign_server_pid)
        # The DIRECTORY, which the argv does not carry (#264). Two
        # instances as the same user, both labelled `main` as the README
        # suggests, roots `/a` and `/b` both holding `foo`: B's agent
        # carries `main~foo` in its argv and matches A's derivation
        # exactly, and nothing in a snapshot tells the two apart. Where
        # the process actually runs does. Read after the handle, so it is
        # the process the handle refers to that is judged; the kernel
        # reports a renamed folder by its new name, which is why such an
        # agent can still be ended here.
        try:
            cwd = engine._pidfd.cwd_of(pid)
        except PermissionError as exc:
            # Readable for our own processes; another user's, reached
            # through a pid reused between the uid check and the handle,
            # is refused here in the right words.
            raise NotOurs(f"pid {pid} is another user's process: {exc}") from exc
        except OSError as exc:
            raise Gone(f"pid {pid} is gone: {exc}") from exc
        # UNDER the root, at any depth, not a direct child: the agent
        # binary moves into `<project>/.claude/worktrees/<name>` for a
        # worktree session (review round 2), and a parent equality
        # refused that agent as another instance's. Roots cannot nest,
        # so "under this root" is exactly "not under another instance's".
        if not cwd.is_relative_to(root.path):
            raise NotOurs(
                f"pid {pid} runs in {cwd}, which is not under root {root.label!r} as "
                f"configured ({root.path}): another instance's agent, or a root that "
                "moved since it started. Nothing was signalled"
            )
        try:
            engine._pidfd.send_signal(pidfd, signal.SIGKILL if force else signal.SIGTERM)
        except AttributeError as exc:
            raise PidfdUnavailable(_NO_PIDFD) from exc
        except OSError as exc:
            raise _refusal_for(exc, pid, "signal") from exc
    finally:
        engine._pidfd.close_pidfd(pidfd)
    engine._announce(verified)
    return verified


def _refuse_our_own_tree(procs_fn: Callable[[], ProcTable], pid: int) -> None:
    """`self_project` is a name compare; this is the process tree. A
    detached row whose pid is an ancestor of this server, tmux included,
    would take the interface down with it, and nothing else refuses it."""
    table = procs_fn()
    if not table.ok:
        # A guard that cannot look must not pass (control 7): an empty
        # table from a failed `ps` would end the walk after one step.
        raise MachineUnreadable("the process table could not be read, so nothing is signalled")
    seen: set[int] = set()
    current = os.getpid()
    while current > 1 and current not in seen:
        if current == pid:
            raise Protected(f"pid {pid} is in the process tree this server runs in")
        seen.add(current)
        proc = table.by_pid.get(current)
        if proc is None:
            return
        current = proc.ppid
