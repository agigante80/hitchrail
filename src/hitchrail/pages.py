"""Serving the HTML pages and the assets.

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
WOFF2 = "font/woff2"

# Fixed names, fixed types, no path parameter anywhere. A route that built a
# path out of the request would make `/../../etc/passwd` reachable. This does
# not choose: the mapping is this dict and nothing else can be asked for.
ASSETS = {
    "/app.css": ("app.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/logs.js": ("logs.js", "text/javascript; charset=utf-8"),
    "/settings.js": ("settings.js", "text/javascript; charset=utf-8"),
    # #160. The mark, the tile a phone makes of it, and the manifest that
    # names the tile. Served without a token, the only assets that are: see
    # `security.UNAUTHENTICATED_ASSETS` for the argument.
    "/icon.svg": ("icon.svg", "image/svg+xml"),
    "/icon-180.png": ("icon-180.png", "image/png"),
    "/icon-512.png": ("icon-512.png", "image/png"),
    "/manifest.webmanifest": ("manifest.webmanifest", "application/manifest+json"),
    # Self hosted, not fetched from Google (#76). Six faces, and only six: the
    # ones the stylesheet can actually reach. See `app.css` for why the display
    # face needs 500 rather than 400, which is not obvious.
    "/fonts/ZillaSlab-500.woff2": ("fonts/ZillaSlab-500.woff2", WOFF2),
    "/fonts/ZillaSlab-700.woff2": ("fonts/ZillaSlab-700.woff2", WOFF2),
    "/fonts/Karla-400.woff2": ("fonts/Karla-400.woff2", WOFF2),
    "/fonts/Karla-600.woff2": ("fonts/Karla-600.woff2", WOFF2),
    "/fonts/Karla-700.woff2": ("fonts/Karla-700.woff2", WOFF2),
    "/fonts/IBMPlexMono-400.woff2": ("fonts/IBMPlexMono-400.woff2", WOFF2),
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


async def logs_page(request: Request) -> Response:
    """The logs page (#151): the same file for every project.

    The name in the URL chooses NOTHING here. `server.py` has already asked
    the engine whether the name is one a client may address, through the
    same function the logs API uses, and refused with the API's own envelope
    if not; what arrives here is a fixed file that reads its project from its
    own URL in the browser. That is what keeps this module's rule true: it
    reads files it chose, never files a request chose.
    """
    return FileResponse(WEB / "logs.html", media_type=HTML, headers=_REVALIDATE)


async def settings_page(request: Request) -> Response:
    """The settings page (#238), behind the token like `/`. It fetches
    `/api/config` itself; nothing about the machine is in this file."""
    return FileResponse(WEB / "settings.html", media_type=HTML, headers=_REVALIDATE)


def asset_route(path: str) -> Callable[[Request], Awaitable[Response]]:
    """One handler per asset, closed over a name this module chose."""
    filename, media_type = ASSETS[path]

    async def handler(request: Request) -> Response:
        return FileResponse(WEB / filename, media_type=media_type, headers=_REVALIDATE)

    return handler
