"""Helpers the `Config` tests share.

Kept out of `support.py` on purpose: these build `Config` by hand, because it
is the unit under test, where `support.make_config` hides the construction.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from hitchrail.roots import Root


def _r(path: Path, label: str = "main") -> tuple[Root, ...]:
    """One root, labelled, as `Config` now takes them.

    Local to the `Config` tests on purpose. Everything else goes through
    `support.make_config`; Config is the unit under test here, so the
    construction stays visible.
    """
    return (Root(label=label, path=path.resolve()),)


Resolver = Callable[[], tuple[str, ...]]


def fixed_resolver(*addresses: str) -> Resolver:
    """A stand in for asking the operating system what this machine is called."""
    return lambda: tuple(addresses)


def no_socket(*args: object, **kwargs: object) -> object:
    """Refuse to make a socket.

    Three tests here patched gethostname and getaddrinfo and then fell straight
    through to the UDP routing table probe, so they opened a real socket and
    the wildcard filter test asserted over whatever address this developer's
    machine happened to have. Hermetic means every surface, not the two that
    were obvious.
    """
    raise OSError("tests must not open a socket")
