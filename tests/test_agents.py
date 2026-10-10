"""#290: the agent interface, and the registry the engine builds from the config.

The interface was extracted from the calls the engine layer already made of
`claude_ipc`, with no change in behaviour, so most of what it does is proved by
the suites that existed before it. What is new, and checked here, is that
every package keeps implementing every member, and how the registry picks one.
"""

from __future__ import annotations

import inspect
from pathlib import Path

from hitchrail import agent, agents, claude_ipc
from support import DEFAULT_LABEL, make_config


def _members() -> list[str]:
    return sorted(n for n in vars(agent.Agent) if not n.startswith("_"))


def test_the_interface_is_read_from_the_protocol_and_is_not_empty() -> None:
    # The walk below compares against this list, so an empty one would pass
    # every package without looking at it.
    assert {"launch_argv", "request_stop", "marker", "trusted"} <= set(_members())


def test_every_package_implements_every_member_with_the_same_parameters(
    tmp_path: Path,
) -> None:
    """Fails if a package stops implementing a member, or renames a
    parameter a caller passes by keyword."""
    config = make_config(tmp_path)
    assert agents.PACKAGES, "no package to check"
    for package, build in agents.PACKAGES.items():
        built = build(config)
        assert built.package == package, "the mapping's key is the package's own name"
        for name in _members():
            assert hasattr(built, name), f"{package} has no {name}"
            wanted = getattr(agent.Agent, name)
            if inspect.isfunction(wanted):
                have = inspect.signature(getattr(built, name)).parameters
                want = list(inspect.signature(wanted).parameters)[1:]
                assert list(have) == want, f"{package}.{name} takes {list(have)}, not {want}"


def test_the_default_agent_is_claude_code_on_the_spawned_binary(tmp_path: Path) -> None:
    config = make_config(tmp_path, agent_binary="/opt/bin/claude")
    registry = agents.Agents(config)
    (only,) = registry.all()
    assert only.ident == agents.DEFAULT_AGENT
    assert isinstance(only.agent, claude_ipc.ClaudeCode)
    assert only.binary == config.spawn_agent_binary
    assert registry.for_project(f"{DEFAULT_LABEL}~vessel") is only


def test_the_claude_code_argv_ignores_the_folder(tmp_path: Path) -> None:
    """No behaviour change: the folder argument is new to the interface, and
    Claude Code's argv is what it was before #290, for any folder."""
    built = agents.PACKAGES["claude-code"](make_config(tmp_path))
    assert built.launch_argv("claude", "main~vessel", tmp_path) == claude_ipc.launch_argv(
        "claude", "main~vessel"
    )


def test_the_launch_folder_is_the_resolved_one_start_hands_the_agent(tmp_path: Path) -> None:
    real = tmp_path / "real"
    (real / "vessel").mkdir(parents=True)
    link = tmp_path / "link"
    link.symlink_to(real)
    config = make_config(link)
    folder = agents.launch_folder(config, f"{DEFAULT_LABEL}~vessel")
    assert folder == (real / "vessel").resolve()


def test_a_folder_that_is_gone_falls_back_to_a_path_no_argv_carries(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    folder = agents.launch_folder(config, f"{DEFAULT_LABEL}~gone")
    assert folder == Path(f"{DEFAULT_LABEL}~gone")
    assert not folder.is_absolute(), "never a real folder another agent could be started in"
