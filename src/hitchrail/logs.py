"""Where Hitchrail's log lines go, what they look like, and what never enters one.

Configured ONCE, by `cli.main`, before the config is built (#167). Until
then nothing under `hitchrail` had a handler, so every line fell through to
Python's handler of last resort: `WARNING` and up only, and no timestamp,
level or name, which is why the one `info` and the one `debug` call that
existed were dead in every deployment.

**uvicorn's lines are configured here too**, and `cli._serve` passes
`log_config=None` so uvicorn does not configure them again. Its own
`LOGGING_CONFIG` gives the access log a second handler on STDOUT in a second
format, so its lines and ours would have interleaved in the journal in two
shapes from two streams. One format, one stream.

**stderr, and nothing else. No file, no rotation, no purge.** Under the unit
stderr is the journal, which already rotates and vacuums; in a container it
is where logs are expected. A file of our own is a second place a secret
could end up and a category of bug this project does not need.

**Plain text, deliberately not JSON.** Structured logging is the advice for
an aggregation pipeline. This log is read by one operator in `journalctl`,
and `structlog` would be a fourth runtime dependency on a tool that spawns
processes as its user, so key and value pairs inside a readable sentence
it is.

Never the token, and never pane content, at any level. That includes a
token a caller put in a query string, which the server never reads (#388). A pane is arbitrary
terminal output from an agent reading the operator's private repositories;
returning it to an authenticated caller is one thing, keeping it in a
persistent journal is another.
"""

from __future__ import annotations

import logging
import logging.config
import sys

LEVELS = ("debug", "info", "warning", "error")
DEFAULT_LEVEL = "info"

# A timestamp even though journald stamps every entry: `journalctl -o cat`
# and a pasted terminal drop journald's, and a bug report is usually one of
# those. The logger name says which module decided.
FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

_SHOWN_LIMIT = 120

QUERY_OMITTED = "?(query omitted)"

ACCESS_WITHHELD = "access line withheld: its arguments were not the shape this version expects"


class StderrHandler(logging.StreamHandler):  # type: ignore[type-arg]
    """A `StreamHandler` on whatever `sys.stderr` is at the moment of each line.

    `ext://sys.stderr` resolves once, when the config is applied, and keeps
    that object for the life of the process. Anything that swaps stderr later
    is then written past: pytest's capture, and a test that reads what a
    refusal logged. `Handler.handle` holds the handler's lock around `emit`,
    so the swap below cannot interleave with another thread's line.

    Flushed after every record by `StreamHandler` itself, which is what #145
    lacked: the banner sat in stdout's block buffer under the unit. A line
    here reaches the journal when it is written.
    """

    def emit(self, record: logging.LogRecord) -> None:
        self.stream = sys.stderr
        super().emit(record)


class QueryFilter(logging.Filter):
    """Cut the query string off every request target in uvicorn's lines (#388).

    A phone opening a link saved before #115 sends `/?token=<the token>`.
    The server refuses it, and uvicorn's access line still wrote the target
    verbatim, so the journal kept a secret the request never used. The WHOLE
    query goes rather than a `token=` parameter: a secret under any other
    name is the same leak, and a list of names is a denylist.

    A filter on the record, not a rewrite of `scope["query_string"]`, which
    #115 deleted for editing a caller's request; the application still sees
    the query as it was sent.

    Every string argument is cut at its first `?`, whatever it starts with.
    uvicorn's h11 protocol splits the raw target at the first `?` and writes
    the rest back, so an absolute form target (through a forwarding proxy),
    a bare `?x` and `x?y` all reach the line with no leading slash. A client
    address, a method and an http version are cut by the same rule, so a
    client address that does contain one loses everything after it. Under
    uvicorn's `proxy_headers` (on by default, trusting 127.0.0.1) a local
    proxy's `X-Forwarded-For` sets that address, so it can. The effect is a
    truncated address, which is harmless (#440).

    For `uvicorn.access` it FAILS CLOSED. That line is the one place a
    changed upstream shape would leak a secret silently, so a record whose
    args are not the five tuple the installed uvicorn emits (client, method,
    target, http version, status) is replaced by a fixed line with no args,
    rather than passed through on the hope that nothing in it is a target.
    `test_a_query_string_token_reaches_no_journal_line` drives a real uvicorn
    and is what notices that the shape moved.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name == "uvicorn.access" and not _is_access_shape(record.args):
            record.msg = ACCESS_WITHHELD
            record.args = ()
        elif isinstance(record.args, tuple):
            record.args = tuple(_without_query(arg) for arg in record.args)
        _redact_traceback(record)
        return True


def _redact_traceback(record: logging.LogRecord) -> None:
    """The query is cut from the formatted exception text too (#440), and the
    frames stay: `exc_info` is NOT cleared and the traceback NOT dropped,
    since a traceback is what an operator reads an error line for.

    uvicorn logs an application error with `exc_info`, and an exception whose
    message holds the request target (a framework's "no route for /x?token=")
    would print the token. Reachable: every HTTP protocol class in uvicorn 0.54
    (h11, httptools) logs "Exception in ASGI application" with `exc_info`
    from `run_asgi`, as does the lifespan runner.

    The cut is the access line's, applied to each LINE of the text: from the
    first `?` to the end of that line. **A `?` in unrelated exception text is
    redacted too**, a ternary in a quoted source line or a message ending in a
    question, and that cost is accepted: telling a query from any other `?`
    inside free text is a denylist of shapes, and the line loses only its
    tail while its frame, file and line number remain. Whole query or nothing,
    as in #388.

    Sets `exc_text`, which `Formatter.format` prints in place of formatting
    `exc_info` again, and which is also redacted when something cached it.
    """
    if record.exc_info and record.exc_info[0] is not None and not record.exc_text:
        record.exc_text = logging.Formatter().formatException(record.exc_info)
    if record.exc_text:
        record.exc_text = "\n".join(_cut_query(line) for line in record.exc_text.split("\n"))


def _is_access_shape(args: object) -> bool:
    return (
        isinstance(args, tuple)
        and len(args) == 5
        and all(isinstance(arg, str) for arg in args[:4])
        and isinstance(args[4], int)
    )


def _cut_query(text: str) -> str:
    return text.partition("?")[0] + QUERY_OMITTED if "?" in text else text


def _without_query(arg: object) -> object:
    return _cut_query(arg) if isinstance(arg, str) else arg


def configure(level: str = DEFAULT_LEVEL) -> None:
    """Every logger this process writes through, to stderr, in one format.

    `disable_existing_loggers` is False and load bearing: every module took its
    logger at import time, before this runs, and the default of True would
    silence all of them, which is the failure this function exists to end.

    uvicorn stays at `info` when ours is turned down to `debug`: its debug is
    protocol tracing, and "run it with --verbose" is a request for Hitchrail's
    decisions. Turned UP past `info`, it follows, so `--log-level warning`
    quietens the access log as well.
    """
    ours = level.upper()
    theirs = ours if logging.getLevelName(ours) > logging.INFO else "INFO"
    handler = {"class": "hitchrail.logs.StderrHandler", "formatter": "plain"}
    # On a handler of uvicorn's own rather than on its loggers: a handler is
    # replaced each time this runs, where a logger's filters would pile up.
    theirs_handler = {**handler, "filters": ["query"]}
    uvicorns = {"handlers": ["uvicorn"], "level": theirs, "propagate": False}
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {"plain": {"format": FORMAT}},
            "filters": {"query": {"()": "hitchrail.logs.QueryFilter"}},
            "handlers": {"stderr": handler, "uvicorn": theirs_handler},
            "loggers": {
                "hitchrail": {"handlers": ["stderr"], "level": ours, "propagate": False},
                "uvicorn": uvicorns,
                "uvicorn.error": {"level": theirs},
                "uvicorn.access": uvicorns,
            },
        }
    )


def uvicorn_level() -> str:
    """What `uvicorn.run(log_level=...)` is handed. uvicorn re-applies it to
    its own loggers after `configure` ran, so it has to agree with the rule
    there; read back from the `hitchrail` logger rather than passed along, so
    the two cannot be handed different answers."""
    level = logging.getLogger("hitchrail").getEffectiveLevel()
    return logging.getLevelName(level).lower() if level > logging.INFO else "info"


def shown(value: object, limit: int = _SHOWN_LIMIT) -> str:
    """A value that arrived from a request, made safe to put in a log line.

    A journal is read in a terminal, so a control character from a `Host` or
    an `Origin` header is an escape sequence aimed at whoever reads it, and a
    newline forges a second entry. Non printable characters are escaped the
    way `repr` escapes them, and the length is bounded because the header is
    the sender's to make as long as they like.
    """
    text = str(value)
    cut = len(text) > limit
    text = "".join(c if c.isprintable() else repr(c)[1:-1] for c in text[:limit])
    return f"{text}...(truncated)" if cut else text
