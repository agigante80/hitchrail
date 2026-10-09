"""What every route module shares: the refusal envelope, the thread hop, the
unparseable-body tuple, and the one logger they all write to.

Split out of `server.py` at #205 so the route modules can import it without
importing the app that imports them.
"""

from __future__ import annotations

import asyncio
import functools
import logging
from collections.abc import Callable
from typing import TypeVar

from starlette.responses import JSONResponse

from hitchrail import logs

T = TypeVar("T")

# What `request.json()` raises on a body it cannot parse. A body nested past
# the parser's stack raises RecursionError, which is not a ValueError, and
# 64 KB holds 20000 levels of `[`: catching ValueError alone answered it with
# a 500 and a traceback (#399, the class #356 fixed in the file reads).
_UNPARSEABLE = (ValueError, RecursionError)

# Named, not `__name__`: every route module logs through this one, and the
# journal and the tests know these lines as `hitchrail.server`'s.
logger = logging.getLogger("hitchrail.server")


async def in_thread(fn: Callable[..., T], *args: object, **kwargs: object) -> T:
    """Run a blocking engine call off the event loop.

    The engine spawns `ps` and `tmux`. Doing that on the loop stalls the SSE
    stream for every connected browser, because the stream lives on the same
    loop. A sync `def` handler would get this for free from Starlette, but a
    sync handler cannot await a request body, and the create route needs one.

    Two taps therefore land on two threads, which is what the per folder start
    lock in the engine exists to serialise.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, functools.partial(fn, *args, **kwargs))


def _error(status: int, code: str, message: str, **extra: object) -> JSONResponse:
    """Every refusal a route makes, and the one place each is logged (#167).

    The code and message only. `extra` is the caller's, and on `start_died`
    it is the dead pane's output, which never enters a log. The message can
    carry a name straight from the request path, so it goes through
    `logs.shown`. The access line uvicorn writes next says which route.
    """
    logger.log(
        logging.WARNING if status >= 500 else logging.INFO,
        "refused %s %s: %s",
        status,
        code,
        logs.shown(message),
    )
    return JSONResponse({"code": code, "message": message, **extra}, status_code=status)
