"""Everything that knows Antigravity CLI (`agy`) internals, and the only place that may.

The second agent package (#294), beside `claude_ipc` and held to the same
quarantine: nothing outside it may name an agy behaviour, flag or key, and the
rest of Hitchrail calls the `Antigravity` adapter through the `Agent` protocol.

Every shape below was recorded on a real agy, 1.2.14 and then 1.3.3, on
2026-10-10, on a private tmux server in throwaway folders; the captures are on
#294. agy updates its own binary in place, so expect them to move. What was not
recorded is not guessed: a question waiting on a person reads as unknown, no
answer key is ever sent, and the background work menu Claude Code raises at
`/exit` has no counterpart here because none was seen.

The rest of Hitchrail imports THIS module, never a submodule, as for
`claude_ipc`.
"""

from hitchrail.agy_ipc.adapter import Antigravity
from hitchrail.agy_ipc.keys import ANSWER_KEYS, STOP_KEYS
from hitchrail.agy_ipc.launch import MARKER, URL_BASE

__all__ = ["ANSWER_KEYS", "MARKER", "STOP_KEYS", "URL_BASE", "Antigravity"]
