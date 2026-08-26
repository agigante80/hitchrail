"""The quarantine: everything that knows Claude Code internals.

Nothing outside this module may know any of it, and two of the assertions here
are greps rather than imports, because `lint-imports` cannot see a string
literal or a usage pattern.
"""

from __future__ import annotations

from pathlib import Path

import pytest

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


# -- the session link (#29) ------------------------------------------------


def write_session(tmp_path: Path, pid: int, payload: object) -> Path:
    import json

    path = tmp_path / f"{pid}.json"
    path.write_text(json.dumps(payload))
    return path


def test_a_valid_bridge_id_becomes_a_url(tmp_path: Path) -> None:
    """The value is the path segment VERBATIM, `session_` prefix included.

    Rewriting it would be guessing at a format that is not ours.
    """
    write_session(tmp_path, 7, {"bridgeSessionId": "session_abc123"})
    url = claude_ipc.bridge_url(7, tmp_path)
    assert url is not None
    assert url.endswith("session_abc123")


@pytest.mark.parametrize("payload", [{}, {"other": "x"}, []])
def test_a_missing_key_is_none(tmp_path: Path, payload: object) -> None:
    write_session(tmp_path, 8, payload)
    assert claude_ipc.bridge_url(8, tmp_path) is None


def test_a_missing_file_is_none(tmp_path: Path) -> None:
    assert claude_ipc.bridge_url(999, tmp_path) is None


def test_unparseable_json_is_none(tmp_path: Path) -> None:
    (tmp_path / "9.json").write_text("{not json")
    assert claude_ipc.bridge_url(9, tmp_path) is None


def test_an_unreadable_file_is_none_rather_than_an_exception(tmp_path: Path) -> None:
    """Another process writes this file; we may catch it mid write or unreadable."""
    path = tmp_path / "11.json"
    path.write_text('{"bridgeSessionId": "session_x"}')
    path.chmod(0o000)
    try:
        assert claude_ipc.bridge_url(11, tmp_path) is None
    finally:
        path.chmod(0o600)


@pytest.mark.parametrize("value", [123, None, [], {}, 1.5, True])
def test_a_non_string_bridge_id_is_refused(tmp_path: Path, value: object) -> None:
    """The file is written by another process and guaranteed to be nothing."""
    write_session(tmp_path, 12, {"bridgeSessionId": value})
    assert claude_ipc.bridge_url(12, tmp_path) is None


@pytest.mark.parametrize("value", ["../other", "a/b", "a\\b", "/abs", "x/", "..\\y"])
def test_a_bridge_id_with_a_separator_is_refused(tmp_path: Path, value: str) -> None:
    """A separator lets the value climb out of the path segment it belongs in."""
    write_session(tmp_path, 13, {"bridgeSessionId": value})
    assert claude_ipc.bridge_url(13, tmp_path) is None


@pytest.mark.parametrize(
    "value",
    ["https://evil.example", "//evil.example", "javascript:alert(1)", "http:x", "a:b"],
)
def test_a_bridge_id_with_a_scheme_is_refused(tmp_path: Path, value: str) -> None:
    """A scheme points the link at another host entirely, which the interface
    renders as a link the user taps. That is an open redirect in a UI."""
    write_session(tmp_path, 14, {"bridgeSessionId": value})
    assert claude_ipc.bridge_url(14, tmp_path) is None


@pytest.mark.parametrize("value", ["", "   "])
def test_an_empty_bridge_id_is_refused(tmp_path: Path, value: str) -> None:
    write_session(tmp_path, 15, {"bridgeSessionId": value})
    assert claude_ipc.bridge_url(15, tmp_path) is None


def test_a_bridge_id_with_control_characters_is_refused(tmp_path: Path) -> None:
    write_session(tmp_path, 16, {"bridgeSessionId": "sess\x1b[2Jion"})
    assert claude_ipc.bridge_url(16, tmp_path) is None


# -- session_url and provenance --------------------------------------------


def test_the_json_path_wins_and_is_marked_bridge(tmp_path: Path) -> None:
    write_session(tmp_path, 20, {"bridgeSessionId": "session_good"})
    found = claude_ipc.session_url(
        20, tmp_path, pane_text="see https://claude.ai/code/session_old"
    )
    assert found is not None
    assert found.source == "bridge"
    assert found.url.endswith("session_good")


def test_a_scraped_url_is_marked_scraped(tmp_path: Path) -> None:
    """Might be stale, might be another session's, might be right.

    The common bad case is scrollback from a PREVIOUS session in the same pane:
    syntactically perfect and semantically stale, which no amount of parsing
    separates from a good one. Naming the source is the only honest answer.
    """
    found = claude_ipc.session_url(
        21, tmp_path, pane_text="open https://claude.ai/code/session_scraped now"
    )
    assert found is not None
    assert found.source == "scraped"
    assert found.url.endswith("session_scraped")


def test_no_source_at_all_is_none(tmp_path: Path) -> None:
    """`None`, never a SessionUrl with an empty string: a truthy object with a
    falsy value is how a pending state becomes a broken link."""
    assert claude_ipc.session_url(22, tmp_path, pane_text="nothing here") is None
    assert claude_ipc.session_url(22, tmp_path) is None


def test_a_disagreement_between_the_two_is_logged(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A mismatch is good evidence the pane is showing stale scrollback, and it
    is exactly the diagnostic somebody wants when a link misbehaves."""
    import logging

    write_session(tmp_path, 23, {"bridgeSessionId": "session_new"})
    with caplog.at_level(logging.DEBUG, logger="hitchrail.claude_ipc"):
        claude_ipc.session_url(23, tmp_path, pane_text="https://claude.ai/code/session_old")
    assert any("session_old" in r.message or "differ" in r.message for r in caplog.records)


def test_a_scraped_url_is_validated_like_a_bridge_id(tmp_path: Path) -> None:
    """Pane text is attacker influenceable: anyone who can write to the pane
    can put a URL in the scrollback."""
    found = claude_ipc.session_url(24, tmp_path, pane_text="https://claude.ai/code/../../evil")
    assert found is None


def test_the_pid_cannot_traverse(tmp_path: Path) -> None:
    """`pid` is an int, so the filename cannot climb. Asserted so a later
    change to `str` for convenience is caught."""
    import inspect

    sig = inspect.signature(claude_ipc.bridge_url)
    assert sig.parameters["pid"].annotation in ("int", int)


def test_the_bridge_wins_when_no_pane_was_captured(tmp_path: Path) -> None:
    """The common production path, and it was the one not covered.

    Listing never captures a pane, so `session_url` is normally called with
    `pane_text=None`. The disagreement branch must be skipped rather than
    comparing against nothing.
    """
    write_session(tmp_path, 30, {"bridgeSessionId": "session_only"})
    found = claude_ipc.session_url(30, tmp_path)
    assert found is not None
    assert found.source == "bridge"
    assert found.url.endswith("session_only")


def test_a_pane_agreeing_with_the_bridge_logs_nothing(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Only a DISAGREEMENT is worth a line. Logging every agreement is noise
    that trains people to ignore the log."""
    import logging

    write_session(tmp_path, 31, {"bridgeSessionId": "session_same"})
    with caplog.at_level(logging.DEBUG, logger="hitchrail.claude_ipc"):
        claude_ipc.session_url(31, tmp_path, pane_text="https://claude.ai/code/session_same")
    assert not [r for r in caplog.records if "differ" in r.message]
