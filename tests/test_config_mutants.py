"""`Config`'s refusals, pinned where a mutant survived them (#377).

The survivors of the 2026-09-29 run over `config.py`, each named in the
docstring of the test that kills it, so a later reader can reapply the
mutation rather than trust this file. Kept apart from
`test_mutation_survivors.py`, which was already past the size a file should
be, and listed beside it in mutmut's selection for the same reason: a killing
test outside the selection reports its mutant as surviving again.

Nine survivors are equivalent and have no test, because no input can tell
them apart from the original:

- `remote_reach` 9, `_check_tls` 33 and `_derive_allowed_origins` 12 turn
  `.rstrip("/")` into `.rstrip(None)`, which only strips the whitespace
  `.strip()` already removed. A kept trailing slash is a path of `/`, and a
  path changes no hostname, scheme or port.
- `_check_tls` 34 and `_derive_allowed_origins` 13 turn it into
  `.lstrip("/")`: a validated origin starts with its scheme, never a slash,
  and the slash left at the end is the same harmless path.
- `_check_tls` 32 and `_derive_allowed_origins` 11 turn `.lower()` into
  `.upper()`: `urlsplit` lowercases the scheme and the hostname itself.
- `_check_tls` 21 turns the second `or` into `and`: that line is reached
  only when both flags or neither are set, where the two agree.
- `_check_extra_origins` 39 widens the port ceiling to 65536: `urlsplit`
  raises on any port past 65535 before the range check can see it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hitchrail.config import ConfigError, remote_reach
from support import make_config

# A token, so an origin off loopback is refused for its own fault and never
# for the missing token that would otherwise be the first refusal to fire.
TOKEN = "t" * 24


def _tls_pair(directory: Path) -> dict[str, Path]:
    """Two plain files: `_check_tls` asks only that each is one (#267), and
    loading the pair is `cli.build_tls_context`'s job, so no `openssl`."""
    cert, key = directory / "cert.pem", directory / "key.pem"
    cert.write_text("cert")
    key.write_text("key")
    return {"tls_cert": cert, "tls_key": key}


# -- remote_reach -------------------------------------------------------------


def test_an_origin_written_with_a_leading_double_slash_still_reaches_out() -> None:
    """Mutant killed: `remote_reach` 10, `.rstrip("/")` to `.lstrip("/")`.

    `//box.lan` has a hostname only while its slashes are kept, and
    `remote_reach` is the question the CLI asks before a Config exists, so
    `_check_extra_origins` has not yet refused the entry for its missing
    scheme. With the slashes stripped it answers "nothing reaches this".
    """
    assert remote_reach("127.0.0.1", extra_origins=("//box.lan",)) is not None


# -- _check_tls ---------------------------------------------------------------


def test_a_cert_without_a_key_names_the_key_as_missing(tmp_path: Path) -> None:
    """Mutants killed: `_check_tls` 4, 5, 9, 12, 13 and 17, each of which
    swaps or blanks a flag name in the pairing message."""
    pair = _tls_pair(tmp_path)
    with pytest.raises(ConfigError, match=r"^--tls-cert needs --tls-key: "):
        make_config(tmp_path, tls_cert=pair["tls_cert"])


def test_a_key_without_a_cert_names_the_cert_as_missing(tmp_path: Path) -> None:
    """Mutants killed: `_check_tls` 6, 9, 14 and 17, the other direction."""
    pair = _tls_pair(tmp_path)
    with pytest.raises(ConfigError, match=r"^--tls-key needs --tls-cert: "):
        make_config(tmp_path, tls_key=pair["tls_key"])


def test_a_missing_cert_file_is_refused_when_both_flags_are_given(tmp_path: Path) -> None:
    """Mutants killed: `_check_tls` 22 and 23, which return early whenever
    both flags are set and so check neither file."""
    pair = _tls_pair(tmp_path)
    with pytest.raises(ConfigError, match="not a readable file"):
        make_config(tmp_path, tls_cert=tmp_path / "absent.pem", tls_key=pair["tls_key"])


def test_a_plain_http_origin_off_loopback_is_refused_beside_tls(tmp_path: Path) -> None:
    """Mutants killed: `_check_tls` 22, 23, 31 and 41. `urlsplit(None)`
    answers with bytes, whose scheme is never the str "http"."""
    with pytest.raises(ConfigError, match="is plain http and --tls-cert is set"):
        make_config(
            tmp_path,
            token=TOKEN,
            extra_origins=("http://box.lan:8787",),
            **_tls_pair(tmp_path),
        )


def test_an_https_origin_off_loopback_is_accepted_beside_tls(tmp_path: Path) -> None:
    """Mutants killed: `_check_tls` 30 (no parse at all), 36, 37 and 38,
    each of which refuses the one deployment the refusal exists to point
    the operator at: a proxy speaking https to the browser."""
    config = make_config(
        tmp_path,
        token=TOKEN,
        extra_origins=("https://box.lan:8443/",),
        **_tls_pair(tmp_path),
    )
    assert "https://box.lan:8443" in config.allowed_origins


def test_a_plain_http_loopback_origin_is_accepted_beside_tls(tmp_path: Path) -> None:
    """Mutants killed: `_check_tls` 37, 41 and 42. A developer's own tools
    on this machine are the stated exception, and `is_loopback_host(None)`
    raises rather than answering."""
    config = make_config(
        tmp_path,
        extra_origins=("http://localhost:5173",),
        **_tls_pair(tmp_path),
    )
    assert "http://localhost:5173" in config.allowed_origins


# -- _check_numbers and check_stop_timeout -------------------------------------


@pytest.mark.parametrize("port", [1, 65535])
def test_the_first_and_last_ports_are_accepted(tmp_path: Path, port: int) -> None:
    """Mutants killed: `_check_numbers` 2 and 3 (port 1) and 4 (port 65535)."""
    assert make_config(tmp_path, port=port).port == port


@pytest.mark.parametrize("port", [0, 65536])
def test_a_port_just_outside_the_range_is_refused(tmp_path: Path, port: int) -> None:
    """The other side of the same boundaries, so the pair pins both."""
    with pytest.raises(ConfigError, match="port out of range"):
        make_config(tmp_path, port=port)


@pytest.mark.parametrize(
    "floors",
    [
        {"hard_floor_mb": 0},
        {"session_mb": 0},
        {"hard_floor_mb": 0, "soft_floor_mb": 0},
    ],
    ids=["hard", "session", "soft"],
)
def test_a_memory_figure_of_zero_is_accepted(tmp_path: Path, floors: dict[str, int]) -> None:
    """Mutants killed: `_check_numbers` 19 (`< 0` to `<= 0`) and 20 (`< 1`).

    Zero is a deliberate setting, not a mistake: a hard floor of 0 turns the
    refusal off on a machine whose owner watches memory some other way. The
    refusal is for a NEGATIVE figure, which can only be a typo.
    """
    config = make_config(tmp_path, **floors)
    for name, value in floors.items():
        assert getattr(config, name) == value


def test_a_soft_floor_equal_to_the_hard_floor_is_accepted(tmp_path: Path) -> None:
    """Mutant killed: `_check_numbers` 22, `<` to `<=`. Equal floors are a
    guard with no "ask first" band, which is a choice; only a soft floor
    BELOW the hard one makes the confirmation unreachable."""
    config = make_config(tmp_path, hard_floor_mb=2000, soft_floor_mb=2000)
    assert config.soft_floor_mb == config.hard_floor_mb == 2000


def test_a_stop_wait_under_a_second_is_accepted(tmp_path: Path) -> None:
    """Mutant killed: `check_stop_timeout` 2, `<= 0` to `<= 1`."""
    assert make_config(tmp_path, stop_timeout=0.5).stop_timeout == 0.5


# -- _check_self_project ------------------------------------------------------


def test_a_self_project_that_exists_but_is_not_a_project_name_is_refused(
    tmp_path: Path,
) -> None:
    """Mutant killed: `_check_self_project` 5, `explain_name` skipped.

    The folder has to exist for the mutant to show: otherwise the existence
    check refuses it anyway, which is why every earlier test passed. A dot
    folder is a real folder that discovery never lists, so the protection
    would name a project the interface can never show.
    """
    (tmp_path / ".git").mkdir()
    with pytest.raises(ConfigError, match="is not a project name"):
        make_config(tmp_path, self_project="main~.git")


# -- _check_extra_origins -----------------------------------------------------


def test_an_origin_with_a_trailing_slash_is_accepted(tmp_path: Path) -> None:
    """Mutants killed: `_check_extra_origins` 2 and 3, which keep the slash
    and so read it as a path. A browser's address bar adds that slash, and
    operators paste from it."""
    config = make_config(tmp_path, extra_origins=("http://localhost:5173/",))
    assert "http://localhost:5173" in config.allowed_origins


def test_an_origin_with_a_host_and_the_wrong_scheme_is_refused(tmp_path: Path) -> None:
    """Mutant killed: `_check_extra_origins` 13, `or` to `and`, which lets a
    bad scheme through whenever a hostname is present."""
    with pytest.raises(ConfigError, match="not an origin"):
        make_config(tmp_path, token=TOKEN, extra_origins=("ftp://box.lan",))


@pytest.mark.parametrize(
    "origin",
    [
        "http://localhost/x",
        "http://localhost?x=1",
        "http://localhost#x",
        "http://user@localhost",
        "http://:pass@localhost",
    ],
    ids=["path", "query", "fragment", "username", "password"],
)
def test_each_part_an_origin_does_not_carry_is_refused_alone(
    tmp_path: Path, origin: str
) -> None:
    """Mutants killed: `_check_extra_origins` 23 to 26, each of which joins
    two neighbours of the `or` chain with `and`, so each part is refused
    only when its neighbour is present too. One part per case, or a case
    carrying two survives the mutant that joins them."""
    with pytest.raises(ConfigError, match="carries no path, query, fragment or userinfo"):
        make_config(tmp_path, extra_origins=(origin,))


def test_an_origin_whose_port_is_not_a_number_is_refused(tmp_path: Path) -> None:
    """Mutant killed: `_check_extra_origins` 31, the port never read.
    `urlsplit` parses the port only when asked, so skipping the read skips
    the refusal."""
    with pytest.raises(ConfigError, match="not a valid port"):
        make_config(tmp_path, extra_origins=("http://localhost:abc",))


@pytest.mark.parametrize("port", [1, 65535])
def test_an_origin_on_the_first_or_last_port_is_accepted(tmp_path: Path, port: int) -> None:
    """Mutants killed: `_check_extra_origins` 36 and 37 (port 1) and 38
    (port 65535)."""
    config = make_config(tmp_path, extra_origins=(f"http://localhost:{port}",))
    assert f"http://localhost:{port}" in config.allowed_origins


def test_an_origin_on_port_zero_is_refused(tmp_path: Path) -> None:
    """The lower side of the same boundary. Zero is the only out of range
    port that reaches the check, since `urlsplit` raises past 65535."""
    with pytest.raises(ConfigError, match="port out of range"):
        make_config(tmp_path, extra_origins=("http://localhost:0",))
