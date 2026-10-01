"""What `[tool.mutmut]` says, for the guards that read it.

Shared by `test_mutation_config.py`, which checks the sweep can assemble a tree
that imports, and `test_security_rules.py`, which checks every mutated module
loads the security rules.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]


def _mutmut_config() -> dict[str, list[str]]:
    """`[tool.mutmut]`, or a failure.

    **Fails rather than skips when the section is missing or unparseable.** A
    configuration guard that passes when it cannot find its configuration is
    the exact failure mode this exists to prevent, and it is how the
    `.claude/CLAUDE.md` guards used to pass quietly on a clone.
    """

    raw = (_REPO / "pyproject.toml").read_bytes()
    parsed: object = tomllib.loads(raw.decode()).get("tool", {}).get("mutmut")
    assert isinstance(parsed, dict), (
        "pyproject.toml has no usable [tool.mutmut]; the sweep cannot be configured"
    )
    section: dict[str, list[str]] = parsed
    assert section.get("source_paths"), "[tool.mutmut] names no source_paths to mutate"
    return section
