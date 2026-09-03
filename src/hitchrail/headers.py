"""Response headers, which instruct the browser rather than decide anything.

Kept out of `security.py` on purpose. That module answers one question, "may
this request proceed", in three controls whose order is asserted. Nothing here
refuses anything: these headers tell a browser what to do with a response it
has already been given, which is a different job with a different failure mode.
Its size cap entry argues against splitting the boundary, and this is not part
of the boundary.

#77. Before this, no response in the project set any of them.

**The concrete exposure was the key, not the data.** `GET /grant` is reachable
without a token by design, and since #21 it is a page containing a password
field. Framing is a GET, so any page that knows an allowlisted hostname could
iframe `http://box.lan:8787/grant` and draw its own chrome around the field.
The app shell itself was never the risk: `SameSite=Lax` withholds the cookie
from a cross site framed subresource, so a framed `/` shows a token screen and
not somebody's projects.

The bar is knowing an allowlisted hostname, which on a LAN is a guess anybody
can make.
"""

from __future__ import annotations

import hashlib
import re
from base64 import b64encode
from pathlib import Path

from starlette.types import ASGIApp, Message, Receive, Scope, Send

WEB = Path(__file__).parent / "web"

# `nosniff` everywhere. Cheap, universal, and it stops a browser deciding for
# itself that a JSON error body is HTML.
NOSNIFF = (b"x-content-type-options", b"nosniff")

# Belt and braces with `frame-ancestors` below. X-Frame-Options is obsolete and
# is still what some browsers honour when they ignore a CSP directive they do
# not know, and DENY is what Hitchrail means: nothing here is ever legitimately
# framed, including by itself.
FRAME_DENY = (b"x-frame-options", b"DENY")

# Applies wherever a policy is not otherwise chosen: the JSON API, the assets,
# and any refusal returned before routing. `default-src 'none'` is right for a
# response that is not a document and should pull nothing.
#
# `frame-ancestors`, `base-uri` and `form-action` are in every policy here
# because none of them fall back to `default-src`. Leaving them out is how a
# policy that looks locked down still permits framing.
_COMMON = "frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
API_CSP = f"default-src 'none'; {_COMMON}"

# The app shell. Everything it loads is same origin: `/app.css`, `/app.js` and
# six font routes, since #76 stopped fetching faces from Google. That is what
# makes `'self'` sufficient and a policy worth having possible at all.
PAGE_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; "
    f"font-src 'self'; img-src 'self'; connect-src 'self'; object-src 'none'; {_COMMON}"
)

# Matches the BODY of an inline block, and only an inline one: a `<script src=>`
# has attributes before the `>` and is skipped by `[^>]*src=` never matching
# here, because a block with a src carries no body to hash.
_INLINE = re.compile(r"<(script|style)(?![^>]*\ssrc=)[^>]*>(.*?)</\1>", re.S | re.I)


def _hash_of(body: str) -> str:
    """The CSP source expression for one inline block.

    A hash rather than a nonce, because `/grant` is served straight off disk by
    `FileResponse` and a nonce would mean rewriting the document on every
    request. A hash rather than `'unsafe-inline'`, because `'unsafe-inline'` on
    the one unauthenticated page containing a password field would give away
    most of what the policy is for.

    Computed from the file at import, so it cannot drift from the page: editing
    `grant.html` changes the hash in the same breath.
    """
    digest = hashlib.sha256(body.encode()).digest()
    return f"'sha256-{b64encode(digest).decode()}'"


def _grant_csp() -> str:
    html = (WEB / "grant.html").read_text()
    scripts = [_hash_of(b) for tag, b in _INLINE.findall(html) if tag.lower() == "script"]
    styles = [_hash_of(b) for tag, b in _INLINE.findall(html) if tag.lower() == "style"]
    if not scripts or not styles:  # pragma: no cover - guarded by a test
        raise RuntimeError(
            "no inline script or style found in grant.html, so the policy below "
            "would silently be stricter than the page needs and break it"
        )
    # `connect-src 'self'` is NOT optional and was missing from the first
    # version of this policy. `connect-src` does not fall back to anything
    # useful here: with `default-src 'none'` it inherits 'none', so the page's
    # one `fetch("api/grant")` was blocked, the trade never happened, and the
    # only symptom was the page saying the key was not accepted.
    #
    # Every header assertion still passed, because the header was exactly what
    # we said it would be. The browser tier is what found it, which is the
    # argument for that tier existing.
    return (
        f"default-src 'none'; script-src {' '.join(scripts)}; "
        f"style-src {' '.join(styles)}; connect-src 'self'; {_COMMON}"
    )


GRANT_CSP = _grant_csp()


def policy_for(path: str) -> str:
    """The CSP for one path. Per route, because the two pages differ.

    Compared exactly, the way `security.route_path` is: a prefix test would
    hand the grant page's inline hashes to anything later mounted under it.
    """
    if path == "/":
        return PAGE_CSP
    if path == "/grant":
        return GRANT_CSP
    return API_CSP


class SecurityHeadersMiddleware:
    """Pure ASGI, not `BaseHTTPMiddleware`.

    `BaseHTTPMiddleware` buffers through an anyio stream and breaks the event
    stream, which is the same reason `server.py` carries no gzip middleware.
    Intercepting `http.response.start` touches the headers and nothing else, so
    a response that never ends still streams.

    Outermost in the stack, so a refusal from the host, token or origin check
    carries the headers too. Those are the responses most likely to be rendered
    somewhere unexpected, and a 400 without `nosniff` is the same hole as a 200
    without one.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":  # pragma: no cover - lifespan and websocket
            await self.app(scope, receive, send)
            return

        csp = policy_for(scope.get("path", ""))

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                headers.append(NOSNIFF)
                headers.append(FRAME_DENY)
                headers.append((b"content-security-policy", csp.encode()))
            await send(message)

        await self.app(scope, receive, send_with_headers)
