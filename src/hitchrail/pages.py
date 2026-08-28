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


async def page(request: Request) -> Response:
    """The single page. Behind the token like every other route.

    Serving the shell unauthenticated was considered and rejected in #21: one
    URL to paste, and an exemption every future addition to the shell would
    inherit. `grant_page` is the door instead.
    """
    return FileResponse(WEB / "index.html", media_type=HTML)


async def grant_page(request: Request) -> Response:
    """The one page served without a token, and it carries no data.

    Self contained: it references no asset route, because every asset route
    stays behind the token, so a linked stylesheet here would be answered 401
    and the page would arrive unstyled and inert. A page reachable without a
    token must not name what is on the machine either, so no project name, no
    memory figure and no root path reaches it, and a test asserts a seeded
    project's name is absent from its body.
    """
    return FileResponse(WEB / "grant.html", media_type=HTML)


def asset_route(path: str) -> Callable[[Request], Awaitable[Response]]:
    """One handler per asset, closed over a name this module chose."""
    filename, media_type = ASSETS[path]

    async def handler(request: Request) -> Response:
        return FileResponse(WEB / filename, media_type=media_type)

    return handler
