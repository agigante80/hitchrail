"""Helpers shared by the test tiers, so a change to a constructor is one edit.

**Why this exists.** `Config` was built directly at 145 call sites, and almost
none of them cared how it was built: they wanted a config pointing at a
temporary root so they could test something else. Pluralising `root` for #120
would therefore have been a 145 site diff, which is not a diff anybody reviews.

`tests/test_config.py` deliberately does NOT use this. Config is the unit under
test there, and a helper between the test and the constructor would hide the
thing being asserted.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hitchrail.config import Config
from hitchrail.roots import Root

DEFAULT_LABEL = "main"


def make_config(root: Path, **kw: Any) -> Config:
    """A Config with one root labelled `main`, for tests that do not care.

    Everything else is passed through, so a test that DOES care about a field
    names it and the rest stay at their defaults. A test that cares about
    SEVERAL roots passes `roots=` and does not use this.

    This is the edit #120 was preparing for: one line, rather than 145.
    """
    if "roots" in kw:
        raise TypeError("pass roots= to Config directly, not through make_config")
    return Config(roots=(Root(label=DEFAULT_LABEL, path=root.resolve()),), **kw)
