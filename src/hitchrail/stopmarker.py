"""The in flight stop marker, and who may write it (#242).

Moved out of `engine.py` at Phase 26, byte for byte, because that file sat at
its size cap and the rules for who holds a marker were about to grow (#432).
`hitchrail.engine` re exports `StopMarker`, so every caller that imported it
from there still does.

This module is in the engine layer and imports nothing from the web layer;
`lint-imports` enforces it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from hitchrail import claude_ipc


@dataclass(eq=False)
class StopMarker:
    """One graceful stop in flight (#242). Compared by identity, never value.

    `closing` is the wrap up: the prompt is queued behind the task and the
    sweep watches for the agent to finish both. `exiting` is the exit
    sequence sent, which is all a stop was before #242 and still is with no
    prompt configured.

    **No path claims a marker while something types into its pane.** `watch`
    is None while the prompt is being typed, and `typing` is True while the
    exit sequence is, whether the sweep or `stop()` types it (#406). A Stop
    on either is the no-op 202: a second sequence would interleave its keys
    with the first.

    **A caller that holds a marker removes it by identity**, through
    `Engine._drop`: a pop by name removes whatever marker is there now, which
    after a repeated Stop is a newer one than the caller holds. Three removals
    are by name on purpose (#407), because each ends every stop on the row,
    not one: `_derive` on a row it read `stopped`, `kill` before its
    `kill-session` and again after it, and `expire_stops`, whose snapshot and
    removal share one critical section.

    A claim that fails gives the marker back rather than replacing it: Exit
    now mutates the `closing` marker in place, and a refused exit restores
    `closing` and its watch on the same object (`Engine._give_back`).

    **The owner writes the OBJECT, not the table** (#387): the watch, the
    give back and `withdrawn`. Kill takes the marker out before its
    `kill-session` and hands it back if that fails, so a check that the
    marker is still in the table read false in that window, the outcome was
    lost, and Kill restored `closing` with no watch: stranded, as #407 was.
    Writing a marker no table holds costs nothing, since nothing reads one.

    A claim writes `exit_at`, `ceiling` and `typing` BEFORE `phase`, and
    `_derive` reads `phase` first without the lock, so a reader that sees
    `exiting` sees the flags that came with it.

    `policy` is the stop policy when Stop was confirmed, and the one its
    expiry acts on (#419): the dialog promised it, and the page can change
    the live setting during the wait. Required, so no path forgets it.
    """

    began: float
    phase: Literal["closing", "exiting"]
    policy: str
    watch: claude_ipc.WrapUpWatch | None = None
    exit_at: float | None = None
    ceiling: bool = False
    typing: bool = False
    withdrawn: bool = False

    @property
    def is_typing(self) -> bool:
        """Something is typing into the pane for this stop this moment: the
        exit sequence (`typing`), or the prompt (`closing` before its watch
        exists). The condition `Engine.stop` answers with the no-op 202.
        Read under the engine's lock."""
        return self.typing or (self.phase == "closing" and self.watch is None)
