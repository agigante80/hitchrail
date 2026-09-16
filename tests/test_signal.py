"""`Engine.signal_detached` (#107): the one destructive path not scoped by a
tmux prefix, so scoped by a check, and the check is only sound in one
order: the handle first, the verification second, the signal through the
handle. Every test here is a refusal or the order; the happy path is one
test, and the live tmux tier holds the syscall on a real process.
"""

from __future__ import annotations

import errno
import os
import signal
from collections.abc import Callable
from pathlib import Path

import pytest

from conftest import FakePidfd, FakeTmux, ScriptedProcs, ps_row
from hitchrail.engine import (
    Engine,
    Gone,
    MachineUnreadable,
    NotDetached,
    NotOurs,
    OwnedElsewhere,
    PidfdUnavailable,
    Protected,
    State,
    UnknownProject,
)
from hitchrail.procs import ProcTable, parse_ps
from support import DEFAULT_LABEL, make_config

ORPHAN = 900
ME = os.getpid()


def proj(folder: str) -> str:
    return f"{DEFAULT_LABEL}~{folder}"


@pytest.fixture
def root(tmp_path: Path) -> Path:
    for folder in ("vessel", "network", "hitchrail"):
        (tmp_path / folder).mkdir()
    return tmp_path


def _engine(
    root: Path,
    procs: Callable[[], ProcTable],
    fake: FakePidfd,
    *,
    foreign: dict[str, int] | None = None,
    sessions: dict[str, int] | None = None,
    self_project: str | None = None,
) -> Engine:
    config = make_config(
        root,
        sessions_dir=root / ".sessions",
        agent_config_path=root / "no-agent-config.json",
        self_project=self_project,
    )
    return Engine(
        config,
        tmux=FakeTmux(sessions=sessions, foreign=foreign),
        procs_fn=procs,
        meminfo_fn=lambda: "MemAvailable: 8388608 kB\n",
        ceiling_fn=lambda pid: None,
        open_pidfd=fake.open,
        send_signal=fake.send,
        close_pidfd=fake.close,
        owner_uid=fake.owner,
    )


class Watched:
    """`ScriptedProcs` that also logs every read into the pidfd recorder, so
    the order of "open" against "look" is one list."""

    def __init__(self, fake: FakePidfd, *stages: str) -> None:
        self.inner = ScriptedProcs(*stages)
        self.fake = fake

    def __call__(self) -> ProcTable:
        self.fake.events.append(("look", self.inner.reads))
        return self.inner()


DETACHED = ps_row(ORPHAN, 1, project=proj("vessel"))


def test_a_detached_agent_with_no_owner_is_signalled_with_sigterm(root: Path) -> None:
    fake = FakePidfd()
    engine = _engine(root, Watched(fake, DETACHED), fake)
    session = engine.signal_detached(proj("vessel"))
    assert session.state is State.DETACHED and session.pid == ORPHAN
    assert fake.signals == [signal.SIGTERM]
    assert not fake.leaked


def test_the_handle_is_opened_before_the_verification(root: Path) -> None:
    """The correctness here IS the order. Verify before open, and a pid
    reused in the window is signalled; open before verify, and the handle
    refers to the process the listing saw, so a reuse fails verification and
    an exit is `ESRCH` at the send. One recorder, two seams."""
    fake = FakePidfd()
    engine = _engine(root, Watched(fake, DETACHED), fake)
    engine.signal_detached(proj("vessel"))
    kinds = [kind for kind, _ in fake.events]
    # The first look feeds the row and the ancestry walk; the open comes
    # BEFORE the look that verifies; the send comes after that look.
    opened = kinds.index("open")
    sent = kinds.index("send")
    assert "look" in kinds[opened:sent], kinds
    assert kinds.index("close") > sent


def test_sigkill_is_never_sent_on_the_first_request(root: Path) -> None:
    fake = FakePidfd()
    engine = _engine(root, Watched(fake, DETACHED), fake)
    engine.signal_detached(proj("vessel"))
    assert signal.SIGKILL not in fake.signals
    # A second, explicit request on its own route is the only way to it.
    engine.signal_detached(proj("vessel"), force=True)
    assert fake.signals == [signal.SIGTERM, signal.SIGKILL]
    assert not fake.leaked


def test_a_pid_that_changed_identity_is_refused_after_the_handle_is_opened(root: Path) -> None:
    """The reuse race. The listing saw `vessel`'s agent at pid 900; by the
    time the request lands, 900 is `sleep`. The handle refers to the process
    that was there, verification sees a different one, nothing is signalled,
    the handle is closed."""
    fake = FakePidfd()
    reused = ps_row(ORPHAN, 1, args="sleep 60")
    engine = _engine(root, Watched(fake, DETACHED, reused), fake)
    with pytest.raises(NotOurs, match="changed identity"):
        engine.signal_detached(proj("vessel"))
    assert fake.signals == []
    assert [k for k, _ in fake.events if k == "open"] == ["open"]
    assert not fake.leaked


def test_an_agent_that_exited_before_the_handle_is_gone(root: Path) -> None:
    fake = FakePidfd(fail_open=OSError(errno.ESRCH, "No such process"))
    engine = _engine(root, Watched(fake, DETACHED), fake)
    with pytest.raises(Gone):
        engine.signal_detached(proj("vessel"))
    assert fake.signals == []


def test_a_zombie_that_the_send_cannot_reach_is_gone_and_the_handle_is_closed(
    root: Path,
) -> None:
    fake = FakePidfd(fail_send=OSError(errno.ESRCH, "No such process"))
    engine = _engine(root, Watched(fake, DETACHED), fake)
    with pytest.raises(Gone):
        engine.signal_detached(proj("vessel"))
    assert not fake.leaked


def test_a_foreign_owned_agent_is_refused_and_the_session_is_named(root: Path) -> None:
    fake = FakePidfd()
    table = ps_row(700, 1) + ps_row(ORPHAN, 700, project=proj("vessel"))
    engine = _engine(root, Watched(fake, table), fake, foreign={"cc-vessel": 700})
    with pytest.raises(OwnedElsewhere, match="'cc-vessel'") as caught:
        engine.signal_detached(proj("vessel"))
    assert caught.value.session == "cc-vessel"
    assert [k for k, _ in fake.events if k in ("open", "send")] == []


def test_a_row_that_is_not_detached_is_refused_before_any_handle(root: Path) -> None:
    fake = FakePidfd()
    running = ps_row(500, 1, args="tmux") + ps_row(501, 500, project=proj("vessel"))
    engine = _engine(root, Watched(fake, running), fake, sessions={proj("vessel"): 500})
    with pytest.raises(NotDetached, match="running"):
        engine.signal_detached(proj("vessel"))
    with pytest.raises(NotDetached, match="stopped"):
        engine.signal_detached(proj("network"))
    assert [k for k, _ in fake.events if k in ("open", "send", "owner")] == []


def test_the_protected_project_is_refused_before_any_handle_is_opened(root: Path) -> None:
    fake = FakePidfd()
    detached = ps_row(ORPHAN, 1, project=proj("hitchrail"))
    engine = _engine(root, Watched(fake, detached), fake, self_project=proj("hitchrail"))
    with pytest.raises(Protected):
        engine.signal_detached(proj("hitchrail"))
    assert [k for k, _ in fake.events if k in ("open", "send", "owner")] == []


def test_this_servers_own_ancestry_is_refused(root: Path) -> None:
    """`self_project` is a name compare; the process tree is a second guard.
    A detached row whose pid is an ancestor of this process, the tmux
    server say, would take the interface down with it."""
    fake = FakePidfd()
    # The orphan is this test process's own parent's parent: an ancestor.
    table = ps_row(ORPHAN, 1, project=proj("vessel")) + ps_row(4242, ORPHAN) + ps_row(ME, 4242)
    engine = _engine(root, Watched(fake, table), fake)
    with pytest.raises(Protected, match="process tree this server runs in"):
        engine.signal_detached(proj("vessel"))
    assert [k for k, _ in fake.events if k in ("open", "send")] == []


def test_another_users_process_is_refused_before_any_handle(root: Path) -> None:
    fake = FakePidfd(uid=os.getuid() + 1)
    engine = _engine(root, Watched(fake, DETACHED), fake)
    with pytest.raises(NotOurs, match="another user"):
        engine.signal_detached(proj("vessel"))
    assert [k for k, _ in fake.events if k in ("open", "send")] == []


def test_a_kernel_refusal_at_the_send_is_not_ours_and_the_handle_is_closed(root: Path) -> None:
    fake = FakePidfd(fail_send=PermissionError(errno.EPERM, "Operation not permitted"))
    engine = _engine(root, Watched(fake, DETACHED), fake)
    with pytest.raises(NotOurs, match="not ours to signal"):
        engine.signal_detached(proj("vessel"))
    assert not fake.leaked


@pytest.mark.parametrize(
    "failure",
    [AttributeError("module 'os' has no attribute 'pidfd_open'"), OSError(errno.ENOSYS, "no")],
    ids=["no-python-support", "no-kernel-support"],
)
def test_no_pidfd_support_refuses_rather_than_falling_back(
    root: Path, failure: BaseException, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Never `os.kill`. A race free path that silently degrades to a racy
    one is the guard failing open control 7 forbids."""
    killed: list[tuple[int, int]] = []
    monkeypatch.setattr(os, "kill", lambda pid, sig: killed.append((pid, sig)))
    fake = FakePidfd(fail_open=failure)
    engine = _engine(root, Watched(fake, DETACHED), fake)
    with pytest.raises(PidfdUnavailable, match="race free handle"):
        engine.signal_detached(proj("vessel"))
    assert killed == []
    assert fake.signals == []


def test_a_handle_the_machine_cannot_spare_is_the_machine_not_the_process(root: Path) -> None:
    fake = FakePidfd(fail_open=OSError(errno.EMFILE, "Too many open files"))
    engine = _engine(root, Watched(fake, DETACHED), fake)
    with pytest.raises(MachineUnreadable):
        engine.signal_detached(proj("vessel"))


def test_an_unreadable_machine_after_the_handle_signals_nothing(root: Path) -> None:
    """A verification that cannot complete is never one that passed."""
    fake = FakePidfd()
    unreadable = ProcTable([], ok=False)
    stages = iter([ProcTable.__call__ if False else None])  # placeholder, replaced below
    del stages

    reads = {"n": 0}
    good = ScriptedProcs(DETACHED)

    def procs() -> ProcTable:
        reads["n"] += 1
        fake.events.append(("look", reads["n"]))
        # The first looks (row and ancestry) succeed; the verification fails.
        return good() if reads["n"] <= 2 else unreadable

    engine = _engine(root, procs, fake)
    with pytest.raises(MachineUnreadable):
        engine.signal_detached(proj("vessel"))
    assert fake.signals == []
    assert not fake.leaked


def test_an_unknown_root_label_is_refused_before_any_pid_is_looked_up(root: Path) -> None:
    """A second instance's agents carry identifiers under another label,
    and their argv would match; the label has to name a configured root
    before anything about a pid is read."""
    fake = FakePidfd()
    other = ps_row(ORPHAN, 1, project="other~vessel")
    engine = _engine(root, Watched(fake, other), fake)
    with pytest.raises(UnknownProject):
        engine.signal_detached("other~vessel")
    assert [k for k, _ in fake.events if k in ("open", "send", "owner")] == []


def test_a_folder_the_root_has_never_heard_of_is_refused_before_any_pid_is_looked_up(
    root: Path,
) -> None:
    """#264. Two instances as the same user, both labelled `main` as the
    README suggests, different roots: B's agent carries `main~ledger` in its
    argv and this instance has no `ledger`. The label check passes; the
    listing is what says this is not our project, and it is asked before
    the derive so the pid is never even read."""
    fake = FakePidfd()
    theirs = ps_row(ORPHAN, 1, project=proj("ledger"))
    engine = _engine(root, Watched(fake, theirs), fake)
    with pytest.raises(UnknownProject):
        engine.signal_detached(proj("ledger"))
    assert [k for k, _ in fake.events if k in ("open", "send", "owner")] == []


def test_a_detached_agent_in_a_renamed_folder_is_refused_here_and_reachable_by_tmux(
    root: Path,
) -> None:
    """Premortem 2 of the Phase 20 plan: the listing check must not make a
    live session unreachable. A folder renamed under a running agent keeps
    its tmux session, and stop and kill reach it by the prefix (#42); only
    the pid route, which has no prefix, refuses the name the root no longer
    lists, and its refusal names the listing."""
    fake = FakePidfd()
    (root / "vessel").rename(root / "vessel-renamed")
    running = ps_row(500, 1, args="tmux") + ps_row(501, 500, project=proj("vessel"))
    engine = _engine(root, Watched(fake, running), fake, sessions={proj("vessel"): 500})
    assert engine.get(proj("vessel")).state is State.RUNNING
    with pytest.raises(UnknownProject):
        engine.signal_detached(proj("vessel"))
    engine.kill(proj("vessel"))


# -- round 1 of the review, pinned -----------------------------------------


def test_a_leftover_session_under_another_label_is_still_stoppable(root: Path) -> None:
    """#42's guarantee, kept: the label check lives on the signal route and
    not in `_require_addressable`, so a live `hr-other~vessel` left over
    after a restart under a different label can still be stopped and
    killed, while the pid route refuses the label before any lookup."""
    fake = FakePidfd()
    running = ps_row(500, 1, args="tmux") + ps_row(501, 500, project="other~vessel")
    engine = _engine(root, Watched(fake, running), fake, sessions={"other~vessel": 500})
    assert engine.get("other~vessel").state is State.RUNNING
    engine.kill("other~vessel")
    with pytest.raises(UnknownProject):
        engine.signal_detached("other~vessel")


def test_an_unreadable_table_fails_the_ancestry_walk_closed(root: Path) -> None:
    """A guard that cannot look must not pass: an empty table from a failed
    `ps` would end the ppid walk after one step and let the signal through."""
    fake = FakePidfd()
    stages = [ProcTable(parse_ps(DETACHED)), ProcTable([], ok=False)]

    def procs() -> ProcTable:
        # The first look derives the row; the second, the ancestry walk, fails.
        return stages.pop(0) if len(stages) > 1 else stages[0]

    engine = _engine(root, procs, fake)
    with pytest.raises(MachineUnreadable, match="process table"):
        engine.signal_detached(proj("vessel"))
    assert [k for k, _ in fake.events if k in ("open", "send")] == []


def test_a_process_that_left_after_the_handle_is_gone_not_reused(root: Path) -> None:
    """Two answers after the handle, told apart by the table: the pid still
    there under another identity is `not_ours`, the pid absent is `gone`."""
    fake = FakePidfd()
    engine = _engine(root, Watched(fake, DETACHED, ""), fake)
    with pytest.raises(Gone, match="left between the listing"):
        engine.signal_detached(proj("vessel"))
    assert fake.signals == []
    assert not fake.leaked
