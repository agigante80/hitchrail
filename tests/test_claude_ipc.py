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
    StopNotSafe,
    input_is_clear,
    launch_argv,
    request_stop,
)

SRC = Path(__file__).parent.parent / "src" / "hitchrail"


# Exact input rows captured from a real Claude Code session on 2026-09-02,
# `capture-pane -p -J -e`, in a throwaway directory on a private tmux socket.
# Pasted as bytes rather than described, because every earlier description of
# this row has been subtly wrong and the whole check turns on it.
#
# The prompt is U+276F plus U+00A0. What follows is one of three
# things, and only the third is a draft.
CLEAR_BOX = "\x1b[39m\u276f\xa0                     "
PLACEHOLDER_BOX = '\x1b[39m\u276f\xa0\x1b[2mTry "how does <filepath> work?"'
DRAFT_BOX = "\x1b[39m\u276f\xa0draft text here          "

# The trust modal's selected row, #88, from the same capture.
#
# **Note what is NOT here: the NBSP.** The input box is `\u276f\xa0` and this
# is `\u276f` followed by a colour reset and an ordinary space. An earlier
# version of this constant was written from memory with the NBSP in it, and it
# passed, while the real row matched nothing and the stop sequence would have
# typed into the trust prompt. The prompt anchor is the ornament alone for
# exactly this reason.
MODAL_BOX = "\x1b[39m \x1b[38;5;153m\u276f\x1b[39m \x1b[38;5;153mNo,\x1b[39m \x1b[38;5;153mexit"


def pane_text(input_row: str) -> str:
    """A capture with the usual noise above the row that matters."""
    return (
        "some output\n\x1b[38;5;244m────────────\n" + input_row + "\n  bypass permissions on\n"
    )


class FakePane:
    """Anything with send_keys satisfies the Pane protocol. Deliberately not a Tmux."""

    def __init__(self, captures: list[str] | None = None) -> None:
        self.sent: list[tuple[str, ...]] = []
        self.captured: list[str] = []
        # Defaults to a clear box, so a test about key ORDER does not have to
        # say anything about what the pane looked like.
        self._captures = captures if captures is not None else [pane_text(CLEAR_BOX)] * 4

    def send_keys(self, project: str, *keys: str) -> None:
        self.sent.append((project, *keys))

    def capture_pane(self, project: str, lines: int = 40, escapes: bool = False) -> str:
        self.captured.append(project)
        if not self._captures:
            return ""
        # The LAST entry repeats, so a one element script means "always this".
        # A longer one is read in order, which is what lets a test say "dirty,
        # dirty, dirty, then unreadable".
        return self._captures.pop(0) if len(self._captures) > 1 else self._captures[0]


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


def test_the_clear_box_is_read_as_clear() -> None:
    """The resting state of an idle session: prompt, then nothing but padding.

    This is the COMMON case and the one a placeholder based check gets wrong.
    The placeholder is transient: it appeared about nine seconds after start on
    the real session and was gone on the next sample, and a box cleared with
    `C-u` comes back with no placeholder at all.
    """
    assert input_is_clear(pane_text(CLEAR_BOX)) is True


def test_the_placeholder_is_read_as_clear() -> None:
    """Dim text is Claude Code's own suggestion, not something a person typed."""
    assert input_is_clear(pane_text(PLACEHOLDER_BOX)) is True


def test_a_draft_is_not_read_as_clear() -> None:
    """The whole reason the check exists. Bright text is the operator's, and
    `/exit` appended to it is an instruction we send with their authority."""
    assert input_is_clear(pane_text(DRAFT_BOX)) is False


def test_a_modal_is_not_read_as_clear() -> None:
    """#88, and it falls out rather than being detected.

    The trust modal renders its selected entry with the same prompt marker and
    bright colour a draft has, so refusing bright text refuses the modal too,
    with no list of modal wordings to keep current.
    """
    assert input_is_clear(pane_text(MODAL_BOX)) is False


def test_a_pane_with_no_input_row_cannot_be_judged() -> None:
    """`None`, not `False` and not `True`. A capture that failed, a pane still
    painting, a future layout: none of them is evidence the box is clear, and
    none is evidence a draft is there either."""
    assert input_is_clear("just some output\nand more\n") is None
    assert input_is_clear("") is None


def test_request_stop_clears_before_it_interrupts() -> None:
    """The ordering that removes the authority hazard, and the reason it is
    first: `C-u` is safe whatever state the pane is in, and doing it after an
    interrupt leaves a window where a draft is still present."""
    pane = FakePane()
    request_stop(pane, "vessel")
    assert [sent[1:] for sent in pane.sent] == list(GRACEFUL_STOP_KEYS)
    assert GRACEFUL_STOP_KEYS[0] == ("C-u",)


def test_request_stop_verifies_the_box_before_typing_into_it() -> None:
    """Two captures, and both before `/exit`. The first guards a draft that was
    already there, the second guards whatever `Escape` did."""
    pane = FakePane()
    request_stop(pane, "vessel")
    assert len(pane.captured) == 2


def test_request_stop_refuses_when_a_draft_survived_the_clear() -> None:
    """`C-u` is verified, not assumed. If the box is still bright then
    something we do not understand is happening, and appending `/exit` to it
    submits the pair with the operator's authority."""
    pane = FakePane([pane_text(DRAFT_BOX)])
    with pytest.raises(StopNotSafe):
        request_stop(pane, "vessel")
    assert not any("/exit" in sent for sent in pane.sent), "typed anyway"


def test_a_pane_that_is_not_this_agent_at_all_is_still_stopped() -> None:
    """The quarantine's own rule, applied to the check rather than to a field.

    A pane with output and no input row is a vendor we have not seen, or this
    one after a layout change. The hazard being guarded is text the OPERATOR
    typed sitting in a box we are about to append to, and there is no box, so
    there is no such text. Refusing here would turn any redesign of the input
    row into "graceful stop no longer works, use Kill", silently.
    """
    pane = FakePane(["hitchrail-shim: started\nsome output and no input row\n"])
    request_stop(pane, "vessel")
    assert any("/exit" in sent for sent in pane.sent), "refused a pane with no box to protect"


def test_a_box_seen_dirty_once_is_never_downgraded_to_unknown() -> None:
    """Round 1 of review found this, and it is the hazard this check exists for.

    The retry loop kept only the LAST attempt's verdict while "did we see a
    pane" was sticky across all of them. So a box read as dirty three times and
    then unreadable on the fourth landed in the "layout we do not know, proceed"
    branch and typed into the operator's draft: the precise #91 failure, arrived
    at through the guard rather than around it.

    A `False` anywhere is evidence, and evidence does not expire because a later
    read failed.
    """
    dirty = pane_text(DRAFT_BOX)
    pane = FakePane([dirty, dirty, dirty, ""])
    with pytest.raises(StopNotSafe):
        request_stop(pane, "vessel")

    # Asserted on the keys, not on the exception. With the bug the FIRST
    # checkpoint proceeds, `Escape` goes out, and the second checkpoint raises
    # on a pane it cannot read: the same exception type for a different and
    # much worse reason, with a turn interrupted on the way. Only the key list
    # tells those apart.
    assert [sent[1:] for sent in pane.sent] == [GRACEFUL_STOP_KEYS[0]], (
        "the first checkpoint let a box it had read as dirty through"
    )


def test_request_stop_refuses_a_pane_it_cannot_read() -> None:
    """Fails closed. An unreadable pane is not an empty one."""
    pane = FakePane([""])
    with pytest.raises(StopNotSafe):
        request_stop(pane, "vessel")
    assert not any("/exit" in sent for sent in pane.sent)


def test_request_stop_refuses_when_escape_leaves_the_box_dirty() -> None:
    """The second verification, and it is not the same as the first.

    The agreed sequence on #89 said to check that the pane CHANGED after
    `Escape`. That cannot work: an idle session has nothing to interrupt, so
    nothing changes, and the most ordinary stop there is would be refused. The
    question worth asking twice is the same one, "is the box still clear", so
    a pane that Escape put somewhere unexpected is caught without punishing a
    session that was simply idle.
    """
    pane = FakePane([pane_text(CLEAR_BOX), pane_text(DRAFT_BOX)])
    with pytest.raises(StopNotSafe):
        request_stop(pane, "vessel")
    assert not any("/exit" in sent for sent in pane.sent)


def test_request_stop_captures_with_escape_sequences() -> None:
    """Without `-e` the placeholder and a draft are the same characters, and
    the check that exists to tell them apart cannot."""
    seen: list[bool] = []

    class Recording(FakePane):
        def capture_pane(self, project: str, lines: int = 40, escapes: bool = False) -> str:
            seen.append(escapes)
            return super().capture_pane(project, lines, escapes)

    request_stop(Recording(), "vessel")
    assert seen and all(seen), "captured without escapes, so dim and bright are one thing"


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

        # Part of the protocol since #89: the sequence verifies between its
        # steps, so a pane that cannot be READ cannot be typed into either.
        def capture_pane(self, project: str, lines: int = 40, escapes: bool = False) -> str:
            return pane_text(CLEAR_BOX)

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


def test_the_launch_flags_live_only_here() -> None:
    """The other half of the quarantine, and it was missing.

    The greps above cover the stop keys and the marker, so a module that
    hardcoded the LAUNCH flags leaked past all of them. That is the same
    failure with a worse blast radius: the flags are what turn a spawn into
    "run anything as this user", and a second copy is a second thing to find
    when Claude Code renames one.

    Derived from `launch_argv` rather than spelled out, so the guard cannot
    drift from what is actually spawned, and so this test does not itself
    become the second copy it exists to forbid.
    """
    # The marker is itself `--` prefixed and has its own test above. Leaving
    # it in made `flags` impossible to empty, so the vacuity assert below
    # could never fire and this test silently re-checked the marker instead of
    # the launch flags it is named for.
    flags = [
        a
        for a in claude_ipc.launch_argv("claude", "p")
        if a.startswith("--") and a != REMOTE_CONTROL_MARKER
    ]
    assert flags, "launch_argv grew no flags, so this guard checks nothing"
    leaked = {
        p.name: f
        for p in SRC.glob("*.py")
        if p.name != "claude_ipc.py"
        for f in flags
        if f in p.read_text()
    }
    assert leaked == {}, f"launch flags outside the quarantine: {leaked}"


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
