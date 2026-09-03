"""Serving the two HTML pages and the two assets.

Lifted out of `server.py` when the grant page took that file past the size
guideline. It is a real seam and not a line count: reading a file off disk and
handing it back is a different job from translating engine calls into JSON, and
it is the ONLY code in the project that reads a file chosen by a URL.

Which is why the choosing happens here and nowhere else.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path

from starlette.requests import Request
from starlette.responses import FileResponse, Response

# INSIDE the package, because `uvx hitchrail` installs a distribution and a
# directory beside it is not in one.
WEB = Path(__file__).parent / "web"

HTML = "text/html; charset=utf-8"

# Fixed names, fixed types, no path parameter anywhere. A route that built a
# path out of the request would make `/../../etc/passwd` reachable. This does
# not choose: the mapping is this dict and nothing else can be asked for.
ASSETS = {
    "/app.css": ("app.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
}


# Revalidate every time, and keep the ETag useful.
#
# `FileResponse` sets `etag` and `last-modified` and no `cache-control`, and
# with no directive a browser may apply HEURISTIC freshness: it guesses a
# lifetime from `last-modified` and serves from cache without asking. Chrome on
# Android does, and it cost a real debugging session: a layout fix was
# committed, served and confirmed present in the response body, while the phone
# went on rendering the old one from cache.
#
# That is the ordinary way this tool updates. `uvx hitchrail` pulls a new
# version and every browser already holding the page keeps its old assets.
# There is no build step here by design, so there are no hashed filenames to
# break a cache with, and revalidation is the whole mechanism.
#
# `no-cache` rather than `no-store`: the browser must ask, and an unchanged
# asset still comes back 304 with no body, which is what matters on a phone.
_REVALIDATE = {"cache-control": "no-cache"}


async def page(request: Request) -> Response:
    """The single page. Behind the token like every other route.

    Serving the shell unauthenticated was considered and rejected in #21: one
    URL to paste, and an exemption every future addition to the shell would
    inherit. `grant_page` is the door instead.
    """
    return FileResponse(WEB / "index.html", media_type=HTML, headers=_REVALIDATE)


async def grant_page(request: Request) -> Response:
    """The one page served without a token, and it carries no data.

    Self contained: it references no asset route, because every asset route
    stays behind the token, so a linked stylesheet here would be answered 401
    and the page would arrive unstyled and inert. A page reachable without a
    token must not name what is on the machine either, so no project name, no
    memory figure and no root path reaches it, and a test asserts a seeded
    project's name is absent from its body.
    """
    return FileResponse(WEB / "grant.html", media_type=HTML, headers=_REVALIDATE)


def asset_route(path: str) -> Callable[[Request], Awaitable[Response]]:
    """One handler per asset, closed over a name this module chose."""
    filename, media_type = ASSETS[path]

    async def handler(request: Request) -> Response:
        return FileResponse(WEB / filename, media_type=media_type, headers=_REVALIDATE)

    return handler
