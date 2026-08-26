"""The quarantine: everything that knows Claude Code internals.

Nothing outside this module may know any of it, and two of the assertions here
are greps rather than imports, because `lint-imports` cannot see a string
literal or a usage pattern.
"""

from __future__ import annotations

from pathlib import Path

from hitchrail import claude_ipc
from hitchrail.claude_ipc import (
    GRACEFUL_STOP_KEYS,
    REMOTE_CONTROL_MARKER,
    launch_argv,
    request_stop,
)

SRC = Path(__file__).parent.parent / "src" / "hitchrail"


class FakePane:
    """Anything with send_keys satisfies the Pane protocol. Deliberately not a Tmux."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, ...]] = []

    def send_keys(self, project: str, *keys: str) -> None:
        self.sent.append((project, *keys))


# -- launching -------------------------------------------------------------


def test_launch_argv_is_a_list_not_a_string() -> None:
    """The no shell rule has to survive the handoff to the tmux adapter."""
    argv = launch_argv("claude", "vessel")
    assert isinstance(argv, list)
    assert all(isinstance(a, str) for a in argv)


def test_launch_argv_uses_the_configured_binary() -> None:
    """So `--agent-binary` actually reaches the process that gets spawned."""
    assert launch_argv("/opt/claude", "vessel")[0] == "/opt/claude"


def test_launch_argv_carries_the_marker_the_process_table_looks_for() -> None:
    """State derivation finds the agent by this substring, so it must be sent."""
    assert REMOTE_CONTROL_MARKER in launch_argv("claude", "vessel")


# -- stopping --------------------------------------------------------------


def test_request_stop_sends_the_documented_sequence() -> None:
    pane = FakePane()
    request_stop(pane, "vessel")
    assert [sent[1:] for sent in pane.sent] == list(GRACEFUL_STOP_KEYS)


def test_request_stop_targets_the_project_it_was_given() -> None:
    pane = FakePane()
    request_stop(pane, "vessel")
    assert {sent[0] for sent in pane.sent} == {"vessel"}


def test_request_stop_takes_anything_shaped_like_a_pane() -> None:
    """The seam is structural, not nominal.

    This fails if the annotation is ever tightened to the concrete `Tmux`,
    which is the point: naming Tmux there puts "the stop channel is tmux" back
    into the function written to remove channel assumptions. An adapter wanting
    a signal needs the process table, and one wanting an HTTP call needs
    neither.
    """

    class NotATmux:
        def __init__(self) -> None:
            self.count = 0

        def send_keys(self, project: str, *keys: str) -> None:
            self.count += 1

    pane = NotATmux()
    request_stop(pane, "vessel")
    assert pane.count == len(GRACEFUL_STOP_KEYS)


# -- the quarantine itself -------------------------------------------------


def test_the_stop_keys_live_only_here() -> None:
    """`lint-imports` cannot catch a string, so this is a grep."""
    leaked = [
        p.name
        for p in SRC.glob("*.py")
        if p.name != "claude_ipc.py" and "/exit" in p.read_text()
    ]
    assert leaked == []


def test_the_marker_lives_only_here() -> None:
    leaked = [
        p.name
        for p in SRC.glob("*.py")
        if p.name != "claude_ipc.py" and REMOTE_CONTROL_MARKER in p.read_text()
    ]
    assert leaked == []


def test_the_engine_never_iterates_the_stop_keys() -> None:
    """A usage pattern, not an import, so no contract can enforce it.

    Grepping for "/exit" alone passes while the engine still loops over the
    sequence, which is the leak the design's section 4.3 exists to prevent.
    """
    engine = (SRC / "engine.py").read_text()
    assert "GRACEFUL_STOP_KEYS" not in engine
    assert "send_keys" not in engine


def test_this_module_carries_an_instability_warning() -> None:
    """Every claim in here is an undocumented internal that will change.

    A reader who does not know that will treat a broken bridge id as a bug in
    Hitchrail rather than as Claude Code having moved.
    """
    doc = claude_ipc.__doc__ or ""
    assert "undocumented" in doc.lower()


def test_the_stop_sequence_is_a_sequence_of_key_groups() -> None:
    """Each group is one send_keys call, so C-c C-c then /exit Enter is three
    calls rather than one string of characters."""
    assert isinstance(GRACEFUL_STOP_KEYS, tuple)
    assert all(isinstance(group, tuple) and group for group in GRACEFUL_STOP_KEYS)
