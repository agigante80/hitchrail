"""What Hitchrail writes to its log, and what it never does (#167).

The refusals are the point. A log that says what happened is a convenience;
a log that holds the token, a pane or an escape sequence from a forged header
is a leak or an attack on whoever reads the journal.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest

from conftest import FakeTmux, procs_from
from hitchrail import logs
from hitchrail.config import Config
from hitchrail.engine import Engine
from support import make_config
from test_api import HEADERS, NO_AGENT_CONFIG, RUNNING_PS, client_for, make_engine, proj

TOKEN = "s3cret-log-token-value"


def test_a_printable_value_is_shown_as_it_is() -> None:
    assert logs.shown("main~vessel") == "main~vessel"


def test_a_control_character_is_escaped_rather_than_written() -> None:
    """A newline forges a second journal entry and an escape sequence is
    aimed at the terminal the journal is read in."""
    shown = logs.shown("evil\n2026-10-01 INFO hitchrail.engine: forged\x1b[2J")
    assert "\n" not in shown
    assert "\x1b" not in shown
    assert "\\n" in shown
    assert "\\x1b" in shown


def test_a_long_value_is_cut_and_says_so() -> None:
    shown = logs.shown("a" * 500)
    assert shown == "a" * 120 + "...(truncated)"
    assert logs.shown("a" * 120) == "a" * 120, "exactly the limit is not cut"


def test_a_stream_that_is_gone_does_not_fail_the_caller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A closed pipe under the log is not a reason for a stop to fail.
    `Handler.handleError` swallows it; this holds if somebody overrides it."""

    class Gone:
        def write(self, _text: str) -> int:
            raise BrokenPipeError

        def flush(self) -> None:
            raise BrokenPipeError

    logs.configure("debug")
    monkeypatch.setattr(sys, "stderr", Gone())
    logging.getLogger("hitchrail.engine").info("stop %s: requested", "main~vessel")


def test_each_line_goes_to_stderr_at_the_moment_it_is_written(
    capsys: pytest.CaptureFixture[str],
) -> None:
    logs.configure("info")
    logging.getLogger("hitchrail.engine").info("one line")
    captured = capsys.readouterr()
    assert "INFO hitchrail.engine: one line" in captured.err
    assert captured.out == "", "a second stream is two shapes in one journal"


def test_uvicorns_access_log_shares_the_handler(capsys: pytest.CaptureFixture[str]) -> None:
    """Its own config would have put it on stdout, in a second format."""
    logs.configure("info")
    logging.getLogger("uvicorn.access").info("GET / 200")
    assert "INFO uvicorn.access: GET / 200" in capsys.readouterr().err


def _access_line(target: str) -> None:
    """Logged the way uvicorn's `h11_impl` logs one, arguments and all."""
    logging.getLogger("uvicorn.access").info(
        '%s - "%s %s HTTP/%s" %d', "127.0.0.1:5000", "GET", target, "1.1", 401
    )


def test_a_query_string_never_reaches_the_access_line(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """#388. The whole query, whatever the parameter is called."""
    logs.configure("info")
    _access_line(f"/?token={TOKEN}")
    _access_line(f"/api/projects?k={TOKEN}&keep=1")
    err = capsys.readouterr().err
    assert TOKEN not in err
    assert f'"GET /{logs.QUERY_OMITTED} HTTP/1.1" 401' in err
    assert f'"GET /api/projects{logs.QUERY_OMITTED} HTTP/1.1" 401' in err


def test_a_target_without_a_query_is_written_as_it_was(
    capsys: pytest.CaptureFixture[str],
) -> None:
    logs.configure("info")
    _access_line("/api/sessions")
    assert '"GET /api/sessions HTTP/1.1" 401' in capsys.readouterr().err


def test_a_websocket_line_loses_its_query_too(capsys: pytest.CaptureFixture[str]) -> None:
    """uvicorn writes these through `uvicorn.error`, which propagates to the
    `uvicorn` logger's handler rather than having its own."""
    logs.configure("info")
    logging.getLogger("uvicorn.error").info(
        '%s - "WebSocket %s" 403', "127.0.0.1:5000", f"/ws?token={TOKEN}"
    )
    err = capsys.readouterr().err
    assert TOKEN not in err
    assert f"/ws{logs.QUERY_OMITTED}" in err


def test_our_own_lines_are_not_rewritten(capsys: pytest.CaptureFixture[str]) -> None:
    """The filter is uvicorn's. A line of ours naming a path is a decision we
    wrote, and editing it behind our back would make it lie."""
    logs.configure("info")
    logging.getLogger("hitchrail.engine").info("saw %s", "/a?b")
    assert "saw /a?b" in capsys.readouterr().err


def test_debug_is_ours_and_not_uvicorns() -> None:
    logs.configure("debug")
    assert logging.getLogger("hitchrail.engine").isEnabledFor(logging.DEBUG)
    assert not logging.getLogger("uvicorn.error").isEnabledFor(logging.DEBUG)
    assert logs.uvicorn_level() == "info"


def test_loggers_made_before_configure_still_write(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Every module took its logger at import, long before `main` runs.
    `disable_existing_loggers` left at its default silences all of them."""
    early = logging.getLogger("hitchrail.engine")
    logs.configure("info")
    early.info("still here")
    assert "still here" in capsys.readouterr().err


# -- through the real app --------------------------------------------------


def _engine(tmp_path: Path, token: str | None = None) -> tuple[Engine, Config]:
    for name in ("vessel", "network"):
        (tmp_path / name).mkdir(exist_ok=True)
    config = make_config(
        tmp_path,
        sessions_dir=tmp_path / ".sessions",
        agent_config_path=NO_AGENT_CONFIG,
        **({"host": "0.0.0.0", "token": token} if token else {}),
    )
    engine = make_engine(
        config, FakeTmux(sessions={proj("vessel"): 500}), procs_from(RUNNING_PS)
    )
    return engine, config


@pytest.mark.integration
async def test_the_token_never_reaches_a_log_on_a_request(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """At debug, after an authenticated request, a refused one, and a near miss.
    The near miss matters most: a wrong token one character off is a token."""
    logs.configure("debug")
    engine, config = _engine(tmp_path, TOKEN)
    async with client_for(engine, config) as c:
        ok = await c.get(
            "/api/projects", headers={**HEADERS, "authorization": f"Bearer {TOKEN}"}
        )
        near = await c.get(
            "/api/projects",
            headers={**HEADERS, "authorization": "Bearer s3cret-log-token-valuX"},
        )
        none = await c.get("/api/projects", headers=HEADERS)
    assert (ok.status_code, near.status_code, none.status_code) == (200, 401, 401)
    err = capsys.readouterr().err
    assert "a credential was offered and did not match" in err
    assert "no credential was offered" in err
    assert TOKEN not in err
    assert "s3cret-log-token-valuX" not in err


@pytest.mark.integration
async def test_a_rejected_host_is_one_escaped_line(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The one trace a DNS rebinding attempt leaves, and the header is the
    attacker's to fill."""
    engine, config = _engine(tmp_path)
    with caplog.at_level(logging.INFO, logger="hitchrail"):
        async with client_for(engine, config) as c:
            r = await c.get("/api/projects", headers={"host": "evil.example\x1b[2J"})
    assert r.json()["code"] == "host_rejected"
    rejected = [
        rec.getMessage() for rec in caplog.records if "rejected Host" in rec.getMessage()
    ]
    assert len(rejected) == 1, rejected
    assert "\x1b" not in rejected[0]
    assert "evil.example\\x1b[2J" in rejected[0]


@pytest.mark.integration
async def test_a_rejected_origin_is_one_escaped_line(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    engine, config = _engine(tmp_path)
    with caplog.at_level(logging.INFO, logger="hitchrail"):
        async with client_for(engine, config) as c:
            await c.post(
                f"/api/sessions/{proj('network')}",
                headers={"host": "localhost", "origin": "http://evil.example\n"},
            )
            await c.post(f"/api/sessions/{proj('network')}", headers={"host": "localhost"})
    messages = [rec.getMessage() for rec in caplog.records]
    origin = [m for m in messages if "rejected Origin" in m]
    assert len(origin) == 1, messages
    assert "\n" not in origin[0]
    assert len([m for m in messages if "no Origin header" in m]) == 1, messages


@pytest.mark.integration
async def test_a_refused_route_names_its_code(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """`ram_hard` is the refusal most likely to be read as "Hitchrail is
    broken", and the log is where the numbers are checked afterwards."""
    for name in ("vessel", "network"):
        (tmp_path / name).mkdir()
    config = make_config(
        tmp_path,
        sessions_dir=tmp_path / ".sessions",
        agent_config_path=NO_AGENT_CONFIG,
    )
    engine = make_engine(config, FakeTmux(), procs_from(""), "MemAvailable: 1048576 kB\n")
    with caplog.at_level(logging.INFO, logger="hitchrail"):
        async with client_for(engine, config) as c:
            r = await c.post(f"/api/sessions/{proj('network')}", headers=HEADERS)
    assert r.status_code == 507
    assert any("refused 507 ram_hard" in rec.getMessage() for rec in caplog.records)


@pytest.mark.integration
async def test_a_name_from_the_path_is_escaped_in_a_refusal(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    engine, config = _engine(tmp_path)
    with caplog.at_level(logging.INFO, logger="hitchrail"):
        async with client_for(engine, config) as c:
            r = await c.post("/api/sessions/main~no%0Ape%1b", headers=HEADERS)
    assert r.status_code == 404
    refused = [rec.getMessage() for rec in caplog.records if "refused 404" in rec.getMessage()]
    assert refused, [rec.getMessage() for rec in caplog.records]
    assert not [m for m in refused if "\n" in m or "\x1b" in m]
