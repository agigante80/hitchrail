"""agy behind the `Agent` interface (#294).

Part of the `agy_ipc` quarantine. What agy cannot be asked is answered as
unknown, never guessed: no question is read, so `awaits_answer` is None and
`answer_keys` is empty; no file holds the link, so `bridge_url` is None.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from hitchrail.agent import Pane, SessionUrl, WrapUpWatch
from hitchrail.agy_ipc import keys, launch, screen


class Antigravity:
    package = "antigravity"
    marker = launch.MARKER
    answer_keys = keys.ANSWER_KEYS
    # agy 1.3.3 has extensions, not plugins, and no update a CLI flag runs.
    has_plugins = False

    def launch_argv(self, binary: str, project: str, folder: Path) -> list[str]:
        # The project is not used: agy refuses a trailing tag, and the folder
        # in `--add-dir=` is already unique per project and per root.
        return launch.launch_argv(binary, folder)

    def trusted(self) -> frozenset[str] | None:
        # Not read from agy's settings: the launch argv's `--add-dir=` skips
        # the trust prompt (measured on 1.3.3, #294), so no folder Hitchrail
        # starts agy in will stop on it. `folder_is_trusted` says so for each.
        return frozenset()

    def folder_is_trusted(self, folder: Path, trusted: frozenset[str]) -> bool:
        return True

    def bridge_url(self, pid: int) -> str | None:
        return None

    def session_url(self, pid: int, pane_text: str | None) -> SessionUrl | None:
        return launch.session_url(pane_text)

    def request_stop(self, pane: Pane, project: str, settle: Callable[[float], None]) -> None:
        keys.request_stop(pane, project, settle)

    def request_wrap_up(
        self, pane: Pane, project: str, prompt: str, settle: Callable[[float], None]
    ) -> None:
        keys.request_wrap_up(pane, project, prompt, settle)

    def send_answer(self, pane: Pane, project: str, key: str) -> None:
        keys.send_answer(pane, project, key)

    def awaits_answer(self, pane: str) -> bool | None:
        return None

    def wrap_up_watch(self, sent_at: float) -> WrapUpWatch:
        return screen.WrapUpWatch(sent_at=sent_at)
