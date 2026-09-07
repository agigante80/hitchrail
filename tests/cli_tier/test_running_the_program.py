"""What a person sees when they run `hitchrail`."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from .conftest import run_cli, serving

pytestmark = pytest.mark.cli


def test_a_root_without_a_label_says_what_to_type(roots: Path, agent: Path) -> None:
    """The regression that prompted #128, pinned on the binary.

    #120 changed `--root` from a path to `label=path`. argparse rendered the
    refusal as `invalid parse_root_argument value: '...'`, which shows an
    operator upgrading from 0.1.0 a Python function name instead of the sentence
    saying what to type. Fixed in 04059b9, and nothing could have caught it:
    `test_cli.py` asserts `SystemExit` and the resulting config, never what a
    person reads.
    """
    result = run_cli("--root", str(roots / "main"), "--agent-binary", str(agent))

    assert result.returncode != 0, "a root with no label was accepted"
    printed = result.stdout + result.stderr
    assert "label=path" in printed, (
        f"the refusal does not say what to type. A person upgrading from 0.1.0 "
        f"meets this first. Got:\n{printed}"
    )
    # **The CURRENT converter name, read from the module.** The ticket quotes
    # `parse_root_argument`, which is what it was called in 0.1.0. Asserting
    # that literal is an assertion that can never fire, because the function was
    # renamed: argparse renders the name the callable HAS. Read it rather than
    # spell it, so a rename cannot quietly retire the check.
    from hitchrail import cli as cli_module

    converter = cli_module._root_argument.__name__
    assert converter not in printed, (
        f"the refusal names the Python function {converter!r}. argparse's "
        f"default message shows a `type=` callable's name to somebody who "
        f"needed the sentence saying what to type. That is what 04059b9 fixed. "
        f"Got:\n{printed}"
    )


def test_a_repeated_label_is_refused_and_named(roots: Path, agent: Path) -> None:
    """Two roots under one label make `<label>~<folder>` ambiguous, which is the
    identifier every route and every DOM node is keyed by."""
    # **A label that is not also a path component.** The first version used
    # `main`, which is the name of a directory the refusal echoes, so the
    # assertion was satisfied by the PATH and never by the label: review proved
    # it passes against a message with `{root.label!r}` removed. Same shape the
    # first test in this file was already fixed for once.
    result = run_cli(
        "--root",
        f"ridgeline={roots / 'main'}",
        "--root",
        f"ridgeline={roots / 'other'}",
        "--agent-binary",
        str(agent),
    )

    assert result.returncode != 0
    printed = result.stdout + result.stderr
    # The QUOTED form, which is what `{root.label!r}` renders, so this cannot be
    # satisfied by the label turning up incidentally inside a path.
    assert "'ridgeline'" in printed, (
        f"the refusal does not name the duplicated label. Got:\n{printed}"
    )


def test_a_missing_agent_binary_is_refused_at_preflight_and_named(roots: Path) -> None:
    """#28. Asserted only against the preflight function until now.

    This is the failure a lingering systemd unit hits at boot, so the message
    reaching the journal matters: it is the only thing an operator has.
    """
    result = run_cli(
        "--root",
        f"main={roots / 'main'}",
        "--agent-binary",
        "/nonexistent/agent-that-is-not-there",
    )

    assert result.returncode != 0
    printed = result.stdout + result.stderr
    assert "agent-that-is-not-there" in printed, (
        f"the refusal does not name the binary it could not find. Got:\n{printed}"
    )


def test_two_roots_start_and_both_are_served(roots: Path, agent: Path) -> None:
    """#120's flag, proved end to end for the first time.

    Every other tier builds the app object and hands it a `Config` made in
    Python. This is the only place the flag is parsed by argparse, turned into
    roots by `build_config`, survives the preflight, and reaches a listing over
    HTTP. That whole path existed with no test that ran it.

    Loopback, so no token is required: the token requirement keys on the bind
    address, and what is under test here is the ROOTS reaching the listing, not
    the grant flow. `tests/e2e/test_token.py` covers that.
    """
    import json
    import urllib.request

    args = (
        "--root",
        f"main={roots / 'main'}",
        "--root",
        f"other={roots / 'other'}",
        "--agent-binary",
        str(agent),
    )
    with (
        serving(*args) as program,
        urllib.request.urlopen(f"{program.url}/api/projects", timeout=10) as answer,  # noqa: S310
    ):
        body = json.load(answer)

    names = {row["name"] for row in body["projects"]}
    assert "main~vessel" in names, f"the first root did not reach the listing: {names}"
    assert "other~anchor" in names, f"the second root did not reach the listing: {names}"


@pytest.mark.cli
def test_a_start_lands_on_a_server_nobody_else_can_see(agent: Path, tmp_path: Path) -> None:
    """#216. **The case this tier's conftest used to forbid in a comment.**

    It said "do not add one that does" because the console script could not be
    pointed at a socket, so a spawned Hitchrail would create `hr-` sessions on
    the operator's own server, whose kill paths are scoped to the same `hr-`
    prefix a real one uses. `TMUX_TMPDIR` removes the premise, and this case is
    the proof rather than the claim: it starts a real session and then asks both
    servers who has it.

    The project name is unique per run, so the negative assertion cannot be
    confused by a real Hitchrail on this machine holding a session of the same
    name. That matters here specifically: the developer's own service runs from
    this checkout.

    **To falsify this, point `TMUX_TMPDIR` at a SECOND private directory. Do not
    remove it.** Removing it was tried once, on 2026-09-07, and it did what this
    test exists to prevent: the start landed on the operator's own tmux server
    and left `hr-cli~probe-<hex>` there with a fake agent sleeping in it, which
    had to be found and killed by hand. The failure it produces is the same one
    either way, because the assertion is "the private server holds it" rather
    than "some server does".

    The last assertion is conditional and says so: if this machine runs no tmux
    server at all, `list-sessions` fails and the check passes on an empty
    string. That is correct rather than vacuous, and it is the reason the
    positive assertion above it is the one carrying the proof.
    """
    import json
    import subprocess
    import urllib.request
    import uuid

    root = tmp_path / "isolated"
    folder = f"probe-{uuid.uuid4().hex[:8]}"
    (root / folder).mkdir(parents=True)

    with serving("--root", f"cli={root}", "--agent-binary", str(agent)) as program:
        name = f"cli~{folder}"
        start = urllib.request.Request(  # noqa: S310
            f"{program.url}/api/sessions/{name}",
            method="POST",
            headers={"Origin": program.url},
        )
        with urllib.request.urlopen(start, timeout=25) as answer:  # noqa: S310
            assert answer.status < 300, f"the start was refused: {answer.status}"

        with urllib.request.urlopen(  # noqa: S310
            f"{program.url}/api/projects", timeout=10
        ) as answer:
            rows = {row["name"]: row["state"] for row in json.load(answer)["projects"]}
        assert rows.get(name) == "running", f"the row does not say running: {rows}"

        private = subprocess.run(
            ["tmux", "-S", str(program.tmux_socket), "list-sessions", "-F", "#{session_name}"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        assert folder in private.stdout, (
            f"the private server does not hold the session: {private.stdout!r} "
            f"{private.stderr!r}"
        )

    # Outside the `with`, so the program is stopped and its private server is
    # about to be killed. The operator's own server is asked WITHOUT the
    # isolation, which is the only way this assertion means anything.
    default = subprocess.run(
        ["tmux", "list-sessions", "-F", "#{session_name}"],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
        env={k: v for k, v in os.environ.items() if k not in {"TMUX", "TMUX_TMPDIR"}},
    )
    assert folder not in default.stdout, (
        "the session reached the operator's own tmux server, which is the whole "
        f"failure #216 is about: {default.stdout!r}"
    )


@pytest.mark.cli
def test_the_banner_hands_over_a_link_carrying_the_token(agent: Path, roots: Path) -> None:
    """#128's banner case, uncovered until #216 drained the pipe.

    `serving` used to promise it yielded the startup lines "because the banner
    is half of what this tier exists to assert", and yielded `[]`. Nothing
    asserted a line, so the sentence was the only thing making it look covered.

    A token is what makes the banner exist at all: `banner()` returns "" when
    there is none, which is every loopback start without `--token`. So this
    passes one, which also makes the link's fragment assertable.
    """
    with serving(
        "--root",
        f"main={roots / 'main'}",
        "--agent-binary",
        str(agent),
        "--token",
        "opensesame",
    ) as program:
        printed = program.expect("/grant")

    assert "token: opensesame" in printed, (
        f"the banner withheld a token nobody else knows:\n{printed}"
    )
    assert "#token=opensesame" in printed, (
        f"the link carries no token, so it hands the phone nothing usable:\n{printed}"
    )


@pytest.mark.cli
def test_the_banner_withholds_the_token_when_stdout_is_the_journal(
    agent: Path, roots: Path
) -> None:
    """#110's decision, asserted by running the program rather than by reading
    `banner()`.

    Under a systemd unit stdout IS journald, so a token printed here is kept in
    a persistent log readable by root and the `systemd-journal` group, while one
    printed to a terminal scrolls away with the operator in front of it. The
    banner degrades instead: no token, and no fragment on the link.

    `JOURNAL_STREAM` is what systemd sets, and passing it is what makes this a
    test of the deployment rather than of a branch.
    """
    with serving(
        "--root",
        f"main={roots / 'main'}",
        "--agent-binary",
        str(agent),
        "--token",
        "opensesame",
        env={"JOURNAL_STREAM": "8:12345"},
    ) as program:
        printed = program.expect("/grant")

    assert "opensesame" not in printed, (
        f"the token reached the journal, which #110 decided it must not:\n{printed}"
    )
    assert "#token=" not in printed, f"the link carries the token into the journal:\n{printed}"
