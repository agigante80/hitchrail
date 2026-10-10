"""Claude Code behind the `Agent` interface (#290).

Part of the `claude_ipc` quarantine. A wrapper and nothing more: each method
calls the function the engine layer called directly before #290, with the two
paths that used to travel in `Config` held here instead, so the engine never
learns that this agent keeps its trust map and its bridge ids in files.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from hitchrail.agent import Pane, SessionUrl, WrapUpWatch
from hitchrail.claude_ipc import keys, launch, screen


class ClaudeCode:
    package = "claude-code"
    marker = launch.REMOTE_CONTROL_MARKER
    answer_keys = keys.ANSWER_KEYS

    def __init__(self, config_path: Path, sessions_dir: Path) -> None:
        self._config_path = config_path
        self._sessions_dir = sessions_dir

    def launch_argv(self, binary: str, project: str, folder: Path) -> list[str]:
        # The folder is not used: Claude Code takes the project tag after
        # `--remote-control`, which is already unique per project.
        return launch.launch_argv(binary, project)

    def trusted(self) -> frozenset[str] | None:
        return launch.trusted_folders(self._config_path)

    def folder_is_trusted(self, folder: Path, trusted: frozenset[str]) -> bool:
        return launch.folder_is_trusted(folder, trusted)

    def bridge_url(self, pid: int) -> str | None:
        return launch.bridge_url(pid, self._sessions_dir)

    def session_url(self, pid: int, pane_text: str | None) -> SessionUrl | None:
        return launch.session_url(pid, self._sessions_dir, pane_text)

    def request_stop(self, pane: Pane, project: str, settle: Callable[[float], None]) -> None:
        keys.request_stop(pane, project, settle=settle)

    def request_wrap_up(
        self, pane: Pane, project: str, prompt: str, settle: Callable[[float], None]
    ) -> None:
        keys.request_wrap_up(pane, project, prompt, settle=settle)

    def send_answer(self, pane: Pane, project: str, key: str) -> None:
        keys.send_answer(pane, project, key)

    def awaits_answer(self, pane: str) -> bool | None:
        return screen.awaits_answer(pane)

    def wrap_up_watch(self, sent_at: float) -> WrapUpWatch:
        return screen.WrapUpWatch(sent_at=sent_at)
