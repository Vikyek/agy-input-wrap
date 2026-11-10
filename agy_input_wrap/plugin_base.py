"""
Base interface for agy-input-wrap modular plugins.
"""

from __future__ import annotations

from abc import ABC
from typing import Any, Optional, Sequence

from agy_input_wrap.actions import Action


class InputPlugin(ABC):
    """
    Abstract base class for all input interceptor plugins.

    Plugins can intercept either complete bracketed paste payloads (decoded text)
    or raw streaming input chunks (bytes). If a plugin returns a sequence of
    Action instances, those actions are scheduled and fed to the child PTY.
    Returning None passes the input through to subsequent plugins or the default handler.
    """

    name: str = "base"
    enabled: bool = True

    def configure(self, **kwargs: Any) -> None:
        """Configure plugin parameters at runtime."""
        pass

    def process_bracketed_paste(self, content: str) -> Optional[Sequence[Action]]:
        """
        Process text from a complete bracketed paste (\\x1b[200~ ... \\x1b[201~).

        Args:
            content: The decoded UTF-8 string payload of the paste.

        Returns:
            Sequence of Action objects if handled, or None to fall through.
        """
        return None

    def process_input(self, data: bytes) -> Optional[Sequence[Action]]:
        """
        Process raw input bytes received outside bracketed paste.

        Args:
            data: Raw input bytes received from stdin.

        Returns:
            Sequence of Action objects if handled, or None to fall through.
        """
        return None
