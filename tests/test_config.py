"""Configuration: does `Config` refuse every field value it cannot honour?

The fields with no other home: roots, the session prefix, the stop timeouts,
the agent binary, the port, the memory floors, the token's shape, the protected
project and the wrap up prompt. Hosts, origins, reach and the machine's own
addresses each have their own file; the guards that read the source are in
`test_source_guards.py` (#30 split them out of this one).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from config_support import _r
from hitchrail.config import (
    Config,
    ConfigError,
)


def test_missing_root_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="root"):
        Config(roots=_r(tmp_path / "nope"))


def test_a_file_as_root_is_refused(tmp_path: Path) -> None:
    target = tmp_path / "notes.txt"
    target.write_text("x")
    with pytest.raises(ConfigError, match="root"):
        Config(roots=_r(target))


def test_the_config_is_frozen(tmp_path: Path) -> None:
    # Validation happens once, in __post_init__. A mutable Config could be
    # edited past its own refusals after construction.
    cfg = Config(roots=_r(tmp_path))
    with pytest.raises(AttributeError):
        cfg.token = "sneaked in"  # type: ignore[misc]


@pytest.mark.parametrize("prefix", ["", "   ", " hr-", "hr- ", "hr.", "hr:", "h r-"])
def test_a_prefix_that_would_make_the_kill_guard_vacuous_is_refused(
    tmp_path: Path, prefix: str
) -> None:
    """Named regression: "never kill a session without the prefix" needs a prefix.

    Every tmux session name satisfies startswith(""), so an empty prefix turns
    the guard that protects the developer's own sessions into a no-op. Dots and
    colons are refused for the separate reason that tmux reads them as window
    and pane separators.
    """
    with pytest.raises(ConfigError, match="session prefix"):
        Config(roots=_r(tmp_path), session_prefix=prefix)


def test_a_stop_timeout_past_the_ceiling_is_refused_and_the_ceiling_is_named(
    tmp_path: Path,
) -> None:
    """#265. Above 2^31-1 ms a browser's `setTimeout` fires at once, so the
    page said "it has not finished" while the engine waited forever."""
    with pytest.raises(ConfigError, match="at most 3600 seconds"):
        Config(roots=_r(tmp_path), stop_timeout=3601)
    assert Config(roots=_r(tmp_path), stop_timeout=3600).stop_timeout == 3600


@pytest.mark.parametrize("binary", ["", "  ", "-rf", "--dangerously-skip-permissions"])
def test_a_flag_shaped_agent_binary_is_refused(tmp_path: Path, binary: str) -> None:
    # argv[0] starting with a hyphen is read as an option by whatever parses it,
    # and no shell being involved does not help.
    with pytest.raises(ConfigError, match="agent binary"):
        Config(roots=_r(tmp_path), agent_binary=binary)


def test_agent_binary_is_stored_stripped(tmp_path: Path) -> None:
    """#302. The old per-caller check computed the stripped value and never
    wrote it back, so the server spawned an operator's padding its own
    refusal had already rejected as a shape."""
    assert Config(roots=_r(tmp_path), agent_binary="  claude  ").agent_binary == "claude"


def test_spawn_agent_binary_falls_back_to_agent_binary(tmp_path: Path) -> None:
    """Every Config built outside `cli.main`, `support.make_config` included,
    leaves `resolved_agent_binary` unset. #196's field must not make those
    Configs spawn nothing."""
    cfg = Config(roots=_r(tmp_path), agent_binary="my-agent")
    assert cfg.resolved_agent_binary is None
    assert cfg.spawn_agent_binary == "my-agent"


def test_spawn_agent_binary_prefers_the_resolved_path(tmp_path: Path) -> None:
    cfg = Config(
        roots=_r(tmp_path), agent_binary="claude", resolved_agent_binary="/usr/local/bin/claude"
    )
    assert cfg.spawn_agent_binary == "/usr/local/bin/claude"


def test_a_relative_resolved_agent_binary_is_refused(tmp_path: Path) -> None:
    """Only `cli.preflight`'s own lookup may set this field, and that lookup
    is required to answer with an absolute path or nothing (#298): a relative
    value here can only mean a second, less careful resolver wrote it."""
    with pytest.raises(ConfigError, match="resolved_agent_binary"):
        Config(roots=_r(tmp_path), agent_binary="claude", resolved_agent_binary="claude")


@pytest.mark.parametrize("port", [0, -1, 65536, 99999])
def test_a_port_out_of_range_is_refused(tmp_path: Path, port: int) -> None:
    with pytest.raises(ConfigError, match="port"):
        Config(roots=_r(tmp_path), port=port)


def test_a_non_positive_stop_timeout_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="stop timeout"):
        Config(roots=_r(tmp_path), stop_timeout=0)


def test_an_inverted_pair_of_memory_floors_is_refused(tmp_path: Path) -> None:
    # The soft floor is the "ask first" threshold and the hard floor is the
    # refusal. Inverted, the confirmation gate can never fire and the guard
    # loses a step without saying so.
    with pytest.raises(ConfigError, match="soft floor"):
        Config(roots=_r(tmp_path), hard_floor_mb=3072, soft_floor_mb=1536)


@pytest.mark.parametrize("bad", ["", "   ", "\t"])
def test_an_empty_token_is_refused(tmp_path: Path, bad: str) -> None:
    """Named regression: `""` is not None, so it switched authentication ON
    with a secret that an empty cookie matches.

    `compare_digest(b"", b"")` is True, so `Cookie: hitchrail_token=` was
    served. An operator reaches this with `--token "$UNSET_VARIABLE"` and
    believes they configured authentication.
    """
    with pytest.raises(ConfigError, match="empty token"):
        Config(roots=_r(tmp_path), token=bad)


def test_no_token_at_all_is_still_allowed_on_loopback(tmp_path: Path) -> None:
    # None means "no authentication", which is a legitimate loopback choice.
    # Only the empty string, which looks like a token and is not, is refused.
    assert Config(roots=_r(tmp_path), token=None).token is None


# -- #36: refusals nobody exercised ----------------------------------------


@pytest.mark.parametrize("field", ["hard_floor_mb", "soft_floor_mb", "session_mb"])
def test_a_negative_memory_figure_is_refused(tmp_path: Path, field: str) -> None:
    """Every field, not the one that happened to be tested.

    A negative floor makes the guard's arithmetic meaningless: `remaining <
    hard_mb` is true for any remaining when the floor is below zero, so the
    guard either refuses everything or approves everything depending on which
    figure went negative.
    """
    with pytest.raises(ConfigError, match=f"{field} must not be negative"):
        Config(roots=_r(tmp_path), **{field: -1})  # type: ignore[arg-type]


# -- #48: a protection that cannot match is not a protection ----------------


@pytest.mark.parametrize(
    "value",
    ["./hitchrail", "hitchrail/", "../hitchrail", ".hidden", "-flag", "", "a b", "a" * 300],
)
def test_a_self_project_that_could_never_be_a_project_is_refused(
    tmp_path: Path, value: str
) -> None:
    """Shape. Each of these is accepted by string equality and matches nothing."""
    with pytest.raises(ConfigError) as exc:
        Config(roots=_r(tmp_path), self_project=value)
    assert "--self-project" in str(exc.value)


@pytest.mark.parametrize("value", ["main~Hitchrail", "main~hitchrai", "main~hitchrail2"])
def test_a_well_shaped_self_project_that_is_not_there_is_refused(
    tmp_path: Path, value: str
) -> None:
    """The half a shape check cannot reach, and the likelier mistake.

    A capital letter and a typo are what a person actually gets wrong, and both
    pass every pattern. Without the existence check this ticket would have
    closed while the guard stayed broken for its two commonest failures.
    """
    (tmp_path / "hitchrail").mkdir()
    with pytest.raises(ConfigError) as exc:
        Config(roots=_r(tmp_path), self_project=value)
    assert "is not a folder in" in str(exc.value)


def test_a_self_project_that_is_really_there_is_accepted(tmp_path: Path) -> None:
    (tmp_path / "hitchrail").mkdir()
    cfg = Config(roots=_r(tmp_path), self_project="main~hitchrail")
    assert cfg.self_project == "main~hitchrail"


def test_no_self_project_protects_nothing_and_that_is_fine(tmp_path: Path) -> None:
    """Optional. Absence must not become a startup failure."""
    assert Config(roots=_r(tmp_path)).self_project is None


def test_a_file_is_not_a_self_project(tmp_path: Path) -> None:
    """`is_dir`, not `exists`: Hitchrail cannot be running inside a file."""
    (tmp_path / "hitchrail").write_text("not a folder")
    with pytest.raises(ConfigError):
        Config(roots=_r(tmp_path), self_project="main~hitchrail")


def test_the_refusal_names_the_flag_and_the_root(tmp_path: Path) -> None:
    """The operator has to be able to act on it without reading the source."""
    (tmp_path / "real").mkdir()
    with pytest.raises(ConfigError) as exc:
        Config(roots=_r(tmp_path), self_project="main~typo")
    message = str(exc.value)
    assert "--self-project" in message and "typo" in message and str(tmp_path) in message


# -- #242: the wrap up prompt -----------------------------------------------


@pytest.mark.parametrize("prompt", [None, "", "   ", "\t"])
def test_an_absent_or_blank_stop_prompt_is_none(tmp_path: Path, prompt: str | None) -> None:
    """A cleared form sends `""`: a prompt of nothing would type `Enter`."""
    assert Config(roots=_r(tmp_path), stop_prompt=prompt).stop_prompt is None


def test_a_stop_prompt_is_stored_stripped(tmp_path: Path) -> None:
    assert Config(roots=_r(tmp_path), stop_prompt="  /wrapup  ").stop_prompt == "/wrapup"


@pytest.mark.parametrize("prompt", ["a\nb", "a\rb", "a\x07", "a\x1b[2Jb", "/wrap\tup"])
def test_a_stop_prompt_that_is_not_one_printable_line_is_refused_without_echo(
    tmp_path: Path, prompt: str
) -> None:
    with pytest.raises(ConfigError, match="stop prompt must be one line") as caught:
        Config(roots=_r(tmp_path), stop_prompt=prompt)
    assert prompt.strip() not in str(caught.value)


def test_a_stop_prompt_past_the_cap_is_refused_and_the_cap_is_accepted(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="at most 4096"):
        Config(roots=_r(tmp_path), stop_prompt="x" * 4097)
    assert Config(roots=_r(tmp_path), stop_prompt="x" * 4096).stop_prompt == "x" * 4096


@pytest.mark.parametrize("seconds", [0, 9, 9.9, 3601, -1])
def test_a_stop_prompt_timeout_outside_its_bounds_is_refused(
    tmp_path: Path, seconds: float
) -> None:
    with pytest.raises(ConfigError, match="between 10 and 3600"):
        Config(roots=_r(tmp_path), stop_prompt_timeout=seconds)


@pytest.mark.parametrize("seconds", [10, 3600])
def test_a_stop_prompt_timeout_at_either_bound_is_accepted(
    tmp_path: Path, seconds: int
) -> None:
    assert (
        Config(roots=_r(tmp_path), stop_prompt_timeout=seconds).stop_prompt_timeout == seconds
    )
