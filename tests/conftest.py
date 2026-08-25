"""Fixtures shared by the whole suite.

Phase 4 adds the engine fakes here (FakeTmux, FakeClock, ScriptedProcs). For
now it holds the one guard that keeps the hermetic tier honest.
"""

from __future__ import annotations

import pytest

# What the stubbed resolver answers with. `.invalid` is reserved by RFC 2606
# precisely so it can never resolve, and 203.0.113.0/24 is TEST-NET-3, so
# neither can be confused for a real machine if one leaks into an assertion.
STUB_HOSTNAME = "test-host.invalid"
STUB_ADDRESS = "203.0.113.7"


@pytest.fixture(autouse=True)
def no_real_network(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the hermetic tier hermetic, without asking every test to remember.

    `Config(host="0.0.0.0")` with no `resolver` falls through to the real
    `local_addresses()`, which runs `gethostname`, `getaddrinfo` and a UDP
    connect. Around twenty tests did exactly that, so the tier that
    `docs/tech-guidelines.md` section 7.4 calls hermetic was doing real DNS,
    and its answers changed with the machine it ran on.

    Stubbed here rather than by passing a resolver at every call site on
    purpose: a rule that every test has to remember is a rule that decays, and
    this one had already decayed by the time it was written down. A test that
    wants a specific answer still passes `resolver=` and overrides this.

    `tests/test_live_socket.py` is the documented exception to the hermetic
    rule and is marked `live`, so it is left alone.
    """
    if request.node.get_closest_marker("live"):
        return
    monkeypatch.setattr(
        "hitchrail.config.local_addresses", lambda: (STUB_HOSTNAME, STUB_ADDRESS)
    )
