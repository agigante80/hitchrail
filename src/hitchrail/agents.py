"""Which agents this Hitchrail runs, and which one a project's root starts (#290).

**The closed mapping is the security property.** A config file names a package
by a string, and that string selects one of the classes below; it is never an
import path, a module name or a template, so the file can choose among agents
this code knows and cannot make it load or run anything else (Fails if 4 in
Phase 23's plan). A name not in `PACKAGES` is refused when the config is built,
before anything listens.

Built once per engine from the frozen `Config`, and read only: nothing a
request can send changes which agents exist or which one a root runs.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from hitchrail import claude_ipc, discovery
from hitchrail.agent import Agent
from hitchrail.agentconfig import DEFAULT_AGENT
from hitchrail.config import Config
from hitchrail.roots import RootError, split_identifier

__all__ = ["DEFAULT_AGENT", "PACKAGES", "Agents", "Configured", "launch_folder"]

# Keyed by `agentconfig.PACKAGE_NAMES`, which is what a config file may name;
# a test holds the two sets equal.

PACKAGES: dict[str, Callable[[Config], Agent]] = {
    "claude-code": lambda config: claude_ipc.ClaudeCode(
        config.agent_config_path, config.sessions_dir
    ),
}


@dataclass(frozen=True)
class Configured:
    """One configured agent: the operator's identifier, its package, and the
    binary to spawn, already resolved by preflight when there was one."""

    ident: str
    agent: Agent
    binary: str


class Agents:
    def __init__(self, config: Config) -> None:
        # The default first: `all()` is the order derivation asks in, and the
        # agent that ran every root before #290 is the likeliest answer.
        self._by_ident: dict[str, Configured] = {
            DEFAULT_AGENT: Configured(
                DEFAULT_AGENT, PACKAGES["claude-code"](config), config.spawn_agent_binary
            )
        }
        for ident, spec in config.agents.items():
            self._by_ident[ident] = Configured(
                ident, PACKAGES[spec.package](config), spec.spawn_agent_binary
            )
        self._by_label = {root.label: root.agent for root in config.roots}

    def all(self) -> tuple[Configured, ...]:
        """Every configured agent, the default first."""
        return tuple(self._by_ident.values())

    def for_project(self, identifier: str) -> Configured:
        """The agent a project's root runs. The default for a name no root
        holds: derivation is asked about such names and must not raise, and
        nothing can be started there, because `start` resolves the folder
        first and refuses."""
        try:
            label, _ = split_identifier(identifier)
        except RootError:
            return self._by_ident[DEFAULT_AGENT]
        return self._by_ident[self._by_label.get(label, DEFAULT_AGENT)]


def launch_folder(config: Config, name: str) -> Path:
    """The folder `engine.start` hands the agent, which `find_detached` must
    rebuild the same argv from: an agent that takes its folder as an argument
    (#290) has an argv tail that names it.

    The RESOLVED path, as `start` passes it. A project whose folder cannot be
    resolved any more falls back to the name, which no started agent's argv
    carries: an agent whose argv names its folder is then not found, the
    answer `start` would give too, and one whose argv does not (Claude Code)
    ignores the folder and is found exactly as before.
    """
    try:
        return discovery.resolve_identifier(config.roots, name)
    except (discovery.NoSuchProject, ValueError):
        return Path(name)
