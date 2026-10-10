"""What an agent entry in the config file IS, and every refusal it can earn (#290).

Its own module beside `roots.py` for the reason that one exists: `Config`
calls the check and re-raises, and the one validator lives with the thing it
validates. Knows no agent's internals: a package is a NAME here, and
`agents.py` maps each name to the class that implements it. A test holds the
two sets equal, so a name accepted here always builds.

The operator's identifier is what the API and the page carry. It is chosen by
whoever writes the file, so it is held to an allowlist like a root label, and
`default` is reserved for the agent `--agent-binary` names, which every root
runs unless it says otherwise.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

DEFAULT_AGENT = "default"

# The closed set. A config file selects one of these by string and nothing
# else: never an import path, a module name or a template (Fails if 4 in
# Phase 23's plan). Adding an agent is a code change and a release.
PACKAGE_NAMES = frozenset({"claude-code"})

# Lower case, short, no separator tmux or a URL would read: it is shown on a
# phone and sent in JSON, never put in a path or an argv.
_IDENT = re.compile(r"[a-z][a-z0-9_-]{0,31}")


class AgentConfigError(ValueError):
    """An `[agents]` entry, or a root's `agent` key, that cannot be used."""


@dataclass(frozen=True)
class AgentSpec:
    """One `[agents.<id>]` table: which package, and which binary to spawn.

    The binary fields are named as `Config`'s are on purpose: the AST guard
    for #298 in test_source_guards.py matches the attribute name, so a spawn
    that read the raw `agent_binary` here instead of what preflight resolved
    is caught the same way as one on `Config`.
    """

    package: str
    agent_binary: str
    resolved_agent_binary: str | None = None

    @property
    def spawn_agent_binary(self) -> str:
        """What is spawned: preflight's absolute path once `cli.main` has
        threaded it in, the raw value for a spec built anywhere else."""
        return self.resolved_agent_binary or self.agent_binary


def check_agents(agents: Mapping[str, AgentSpec], wanted: Iterable[tuple[str, str]]) -> None:
    """Refuse an unusable table, or a root naming an agent it does not hold.

    `wanted` is `(root label, agent identifier)` for every root. Run once, at
    construction, so a typo in the file stops the start rather than the first
    tap on a project, on a phone, with the reason in a journal.
    """
    for ident, spec in agents.items():
        if ident == DEFAULT_AGENT:
            raise AgentConfigError(
                f"agent {DEFAULT_AGENT!r} is reserved for --agent-binary; "
                "name the table something else"
            )
        if not _IDENT.fullmatch(ident):
            raise AgentConfigError(
                f"agent {ident!r} is not usable: an identifier is a lower case "
                "letter, then up to 31 lower case letters, digits, '-' or '_'"
            )
        if spec.package not in PACKAGE_NAMES:
            raise AgentConfigError(
                f"agent {ident!r}: package {spec.package!r} is not one Hitchrail "
                f"knows; the packages are {sorted(PACKAGE_NAMES)}"
            )
        binary = spec.agent_binary
        if not binary.strip() or binary.strip() != binary or binary.startswith("-"):
            # Refused rather than stripped, unlike `--agent-binary`: a file
            # has no shell quoting to blame for stray whitespace.
            raise AgentConfigError(f"agent {ident!r}: not an acceptable binary: {binary!r}")
        resolved = spec.resolved_agent_binary
        if resolved is not None and not Path(resolved).is_absolute():
            raise AgentConfigError(
                f"agent {ident!r}: resolved_agent_binary {resolved!r} is not absolute"
            )
    known = {DEFAULT_AGENT, *agents}
    for label, ident in wanted:
        if ident not in known:
            raise AgentConfigError(
                f"root {label!r} runs agent {ident!r}, which is not configured; "
                f"the agents are {sorted(known)}"
            )
