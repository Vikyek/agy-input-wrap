"""
Add-Dir Sequencer plugin for agy-input-wrap.

Detects inputs starting with one or more `/add-dir <path>` commands followed
by a prompt. Sequences them into:
1. `/add-dir <path>\\r`
2. Configurable pause (default 200ms) to let BubbleTea TUI process workspace addition
3. `<prompt>\\r`
"""

from __future__ import annotations

import os
import re
from typing import Any, Optional, Sequence

from agy_input_wrap.actions import Action, SleepAction, WriteAction
from agy_input_wrap.plugin_base import InputPlugin

# Matches `/add-dir <path>` or `/add_dir <path>`
ADD_DIR_LINE_RE = re.compile(r"^\s*/add[-_]dir\s+(\S.*)$")
DEFAULT_DELAY_SEC = 0.200


def _get_default_delay() -> float:
    env_val = os.environ.get("AGY_ADD_DIR_DELAY_MS")
    if env_val:
        try:
            return max(0.0, float(env_val) / 1000.0)
        except ValueError:
            pass
    return DEFAULT_DELAY_SEC


class AddDirSequencerPlugin(InputPlugin):
    """
    Sequences /add-dir <path>\\n<prompt> inputs into child PTY.
    """

    name = "add_dir_sequencer"

    def __init__(self, delay_sec: Optional[float] = None) -> None:
        self.delay_sec = delay_sec if delay_sec is not None else _get_default_delay()

    def configure(self, delay_sec: Optional[float] = None, **kwargs: Any) -> None:
        if delay_sec is not None:
            self.delay_sec = max(0.0, float(delay_sec))

    def _sequence_text(
        self,
        text: str,
        *,
        is_bracketed: bool = False,
    ) -> Optional[list[Action]]:
        if not text:
            return None

        # Split on newline representations
        lines = re.split(r"\r\n|\r|\n", text)
        if not lines:
            return None

        # Must start with /add-dir command
        first_match = ADD_DIR_LINE_RE.match(lines[0])
        if not first_match:
            return None

        add_dirs: list[str] = []
        idx = 0

        # Collect all contiguous /add-dir commands at the beginning
        while idx < len(lines):
            line = lines[idx]
            match = ADD_DIR_LINE_RE.match(line)
            if match:
                path = match.group(1).strip()
                add_dirs.append(f"/add-dir {path}")
                idx += 1
            else:
                break

        # Remaining lines form the prompt
        prompt_lines = lines[idx:]
        prompt_text = "\n".join(prompt_lines).strip()

        # If no subsequent prompt text exists, leave input untouched
        if not prompt_text:
            return None

        actions: list[Action] = []
        for cmd in add_dirs:
            actions.append(WriteAction(f"{cmd}\r".encode("utf-8")))
            if self.delay_sec > 0:
                actions.append(SleepAction(self.delay_sec))

        # Format prompt submission
        if is_bracketed and "\n" in prompt_text:
            prompt_payload = b"\x1b[200~" + prompt_text.encode("utf-8") + b"\x1b[201~\r"
        else:
            prompt_payload = f"{prompt_text}\r".encode("utf-8")

        actions.append(WriteAction(prompt_payload))
        return actions

    def process_bracketed_paste(self, content: str) -> Optional[Sequence[Action]]:
        return self._sequence_text(content, is_bracketed=True)

    def process_input(self, data: bytes) -> Optional[Sequence[Action]]:
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            return None
        return self._sequence_text(text, is_bracketed=False)
