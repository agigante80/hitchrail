"""`hitchrail update-plugins`, run as a person runs it (#124)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from .conftest import run_subcommand

pytestmark = pytest.mark.cli

LISTING = [
    {"id": "a@m", "scope": "user"},
    {"id": "adapt@kit", "scope": "local"},
    {"id": "b@m", "scope": "user"},
]


@pytest.fixture
def plugin_agent(tmp_path: Path) -> Path:
    """A fake agent that answers the three plugin subcommands, records every
    call with what it could see, and fails `b@m`."""
    path = tmp_path / "fake-agent"
    log = tmp_path / "calls.jsonl"
    path.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        f"with open({str(log)!r}, 'a') as f:\n"
        "    f.write(json.dumps({'argv': sys.argv[1:], 'cwd': os.getcwd(),\n"
        "        'token': 'HITCHRAIL_TOKEN' in os.environ}) + '\\n')\n"
        "args = sys.argv[1:]\n"
        "if args[:2] == ['plugin', 'list']:\n"
        f"    print({json.dumps(json.dumps(LISTING))})\n"
        "elif args[:3] == ['plugin', 'update', 'b@m']:\n"
        "    print('b@m: download failed', file=sys.stderr)\n"
        "    sys.exit(1)\n"
    )
    path.chmod(0o755)
    return path


def calls(tmp_path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in (tmp_path / "calls.jsonl").read_text().splitlines()]


def test_update_plugins_runs_with_no_server_and_reports_each_plugin(
    plugin_agent: Path, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    result = run_subcommand(
        "update-plugins",
        "--agent-binary",
        str(plugin_agent),
        env={"HOME": str(home), "HITCHRAIL_TOKEN": "must-not-reach-the-child"},
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert result.stdout.splitlines()[:3] == [
        "updated  a@m",
        "skipped  adapt@kit (local scope is not updated)",
        "failed   b@m (exited 1: b@m: download failed)",
    ]
    assert "1 updated, 1 failed, 1 skipped" in result.stdout
    seen = calls(tmp_path)
    assert [c["argv"] for c in seen] == [
        ["plugin", "marketplace", "update"],
        ["plugin", "list", "--json"],
        ["plugin", "update", "a@m", "-s", "user", "-y", "--json"],
        ["plugin", "update", "b@m", "-s", "user", "-y", "--json"],
    ]
    assert {c["cwd"] for c in seen} == {str(home)}
    assert not any(c["token"] for c in seen), "the token reached a plugin command"


def test_bare_hitchrail_still_means_the_server(plugin_agent: Path) -> None:
    """The compatibility promise: `update-plugins` added a verb, and the old
    invocation still reaches the server's own parser and its refusals."""
    result = run_subcommand("--agent-binary", str(plugin_agent))
    assert result.returncode == 2
    assert "update-plugins" not in result.stderr
    assert "root" in (result.stdout + result.stderr).lower()
