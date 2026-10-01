"""Is every module under the size guideline, or argued past it?

The caps and their arguments are `size_caps_engine.py` and
`size_caps_outer.py`.
"""

from __future__ import annotations

from size_caps_engine import ENGINE_LAYER_CAPS
from size_caps_outer import OUTER_LAYER_CAPS
from support import in_claude_ipc, source_modules


def test_every_module_is_under_the_size_guideline() -> None:
    """The reason #18 existed. Asserted so it does not silently regress.

    `.claude/CLAUDE.md` says a file past roughly 400 lines is doing more than
    one thing. config.py reached 502 before its split.

    Every module, not the two that #18 touched. Naming those two let
    discovery.py drift past 400 unnoticed while this test passed, which is the
    same shape of gap as testing three hand picked pairs for injectivity.
    """
    # One known exception, tracked as #33, recorded rather than excused by
    # loosening the threshold for everybody.
    #
    # A CAP, not an exact size. An earlier version pinned 403 exactly and so
    # went red when discovery.py got SMALLER, reporting "past the guideline"
    # about a file that had just moved towards it. Failing on the improvement
    # you asked for is how a number gets bumped instead of fixed.
    # Empty, and that is the point: #33 landed, discovery.py came under the
    # guideline, and this test failed until the entry was removed. The
    # mechanism retires its own exceptions.
    # Tracked, not excused. #50 splits derivation out of engine.py; the
    # vocabulary already moved to sessions.py, which took it from 555 to 466.
    # engine.py holds the lifecycle and nothing else since #50 took the
    # derivation out into `derive.py`, which is the one real seam in it.
    #
    # An earlier version of this note said to cut the graceful stop overlay
    # next rather than raise the number again. Measured rather than guessed,
    # that cut moves 64 lines and leaves the file at 412: still over the
    # guideline, and now with one stop sequence split across two files to buy
    # nothing. The note was wrong, so it is corrected here rather than
    # followed. What is left is a lifecycle with unusually dense comments,
    # because most of it is footguns that cost real debugging to find, and
    # those comments are the reason the file is long. Deleting them to satisfy
    # a line count would be the worst available trade.
    #
    # Raise this only for a change that adds behaviour, and say what in the
    # commit. If it passes roughly 550, look for a seam again with fresh eyes.
    caps = {**ENGINE_LAYER_CAPS, **OUTER_LAYER_CAPS}

    # Keyed by the path under `src/hitchrail` (#368), so a package's
    # `__init__.py` is never merged with the top level one.
    sizes = {rel: len(p.read_text().splitlines()) for rel, p in source_modules().items()}
    assert any(in_claude_ipc(rel) for rel in sizes), "the walk saw no claude_ipc module"

    over = {n: c for n, c in sizes.items() if c >= 400 and c > caps.get(n, 399)}
    assert not over, (
        f"past the guideline: {over}. Split it, or track it in `caps` with a ticket."
    )

    # And the exception cannot outlive its reason: once #33 brings discovery.py
    # under the guideline, this fails and the entry must go.
    settled = {n for n in caps if sizes.get(n, 0) < 400}
    assert not settled, f"no longer oversize, remove from `caps`: {sorted(settled)}"
