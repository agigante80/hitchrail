"""What a person sees when they run `hitchrail`."""

from __future__ import annotations

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
    result = run_cli(
        "--root",
        f"main={roots / 'main'}",
        "--root",
        f"main={roots / 'other'}",
        "--agent-binary",
        str(agent),
    )

    assert result.returncode != 0
    printed = result.stdout + result.stderr
    assert "main" in printed, f"the refusal does not name the label. Got:\n{printed}"


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
        serving(*args) as (base, _),
        urllib.request.urlopen(f"{base}/api/projects", timeout=10) as answer,  # noqa: S310
    ):
        body = json.load(answer)

    names = {row["name"] for row in body["projects"]}
    assert "main~vessel" in names, f"the first root did not reach the listing: {names}"
    assert "other~anchor" in names, f"the second root did not reach the listing: {names}"
