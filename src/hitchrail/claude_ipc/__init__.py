"""Everything that knows Claude Code internals, and the only place that may.

Every constant and every parsing rule below depends on UNDOCUMENTED Claude Code
behaviour that will change without notice. That is the whole reason this package
exists: when it breaks, exactly one package changes and the interface degrades to
`pending` rather than reporting something false.

Written against Claude Code as of 2026-08. If a session link stops resolving or
an agent stops being found in the process table, look here first and expect the
cause to be upstream rather than a bug in Hitchrail.

This package is also the vendor seam. Multi agent is an explicit v1 non goal
(design section 3.1); what is kept open is the seam, not an abstraction.
Nothing outside this package may name a Claude Code behaviour, file or key
sequence, and "name" includes iterating one: `lint-imports` cannot see a string
literal, so the quarantine has grep tests instead.

This package is in the engine layer and imports nothing from the web layer.

**A package since #368**, split along the seams the single file already had:
`screen` reads a pane, `keys` types into one, `launch` builds the argv and finds
the session link, `plugins` updates the plugins. The rest of Hitchrail imports
THIS module and calls through its attributes, never a submodule, so that
`monkeypatch.setattr(claude_ipc, "plugin_runner", ...)` still reaches the
caller; a test forbids importing a submodule from outside the package.
"""

from hitchrail.claude_ipc.keys import (
    ANSWER_KEYS,
    GRACEFUL_STOP_KEYS,
    AnswerNotSafe,
    Pane,
    StopNotSafe,
    request_stop,
    request_wrap_up,
    send_answer,
)
from hitchrail.claude_ipc.launch import (
    REMOTE_CONTROL_MARKER,
    URL_BASE,
    SessionUrl,
    bridge_url,
    launch_argv,
    session_url,
    trusted_folders,
)
from hitchrail.claude_ipc.plugins import (
    PluginFailure,
    PluginOutcome,
    PluginResult,
    PluginRunner,
    PluginsFailed,
    RunnerClosed,
    RunningChild,
    plugin_runner,
    update_plugins,
)
from hitchrail.claude_ipc.screen import (
    WrapUpWatch,
    awaits_answer,
    input_is_clear,
    shows_input_box,
)

__all__ = [
    "ANSWER_KEYS",
    "GRACEFUL_STOP_KEYS",
    "REMOTE_CONTROL_MARKER",
    "URL_BASE",
    "AnswerNotSafe",
    "Pane",
    "PluginFailure",
    "PluginOutcome",
    "PluginResult",
    "PluginRunner",
    "PluginsFailed",
    "RunnerClosed",
    "RunningChild",
    "SessionUrl",
    "StopNotSafe",
    "WrapUpWatch",
    "awaits_answer",
    "bridge_url",
    "input_is_clear",
    "launch_argv",
    "plugin_runner",
    "request_stop",
    "request_wrap_up",
    "send_answer",
    "session_url",
    "shows_input_box",
    "trusted_folders",
    "update_plugins",
]
