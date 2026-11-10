"""
TOON compression plugin for agy-input-wrap.

Compresses pasted JSON blocks into TOON format when running inside the
interceptor, while remaining fully standalone and optional.
"""

from __future__ import annotations

import json
from typing import Any, Optional, Sequence

from agy_input_wrap.actions import Action, WriteAction
from agy_input_wrap.plugin_base import InputPlugin

BRACKETED_PASTE_START = b"\x1b[200~"
BRACKETED_PASTE_END = b"\x1b[201~"


class ToonConverterPlugin(InputPlugin):
    """
    Input plugin that converts JSON payloads inside bracketed paste events to TOON.
    """

    name: str = "toon"
    enabled: bool = True

    def __init__(
        self,
        *,
        aggressive: bool = True,
        min_chars: int = 60,
    ) -> None:
        self.aggressive = aggressive
        self.min_chars = min_chars
        self._converter_fn = None
        self._init_converter()

    def _init_converter(self) -> None:
        """Attempt to load TOON converter dynamically from toon package."""
        try:
            from toon.converter import convert_json_to_toon
            self._converter_fn = convert_json_to_toon
            return
        except ImportError:
            pass

        try:
            from src.toon_converter import convert_json_to_toon
            self._converter_fn = convert_json_to_toon
            return
        except ImportError:
            pass

        # Try from toon-mcp installed in toon-venv or python path
        import sys
        venv_paths = [
            "/home/v/.local/share/toon-venv/lib/python3.14/site-packages",
            "/home/v/Projects/toon-mcp",
        ]
        for p in venv_paths:
            if p not in sys.path:
                sys.path.append(p)
        try:
            from src.toon_converter import convert_json_to_toon
            self._converter_fn = convert_json_to_toon
        except ImportError:
            self._converter_fn = None

    def configure(self, **kwargs: Any) -> None:
        if "aggressive" in kwargs:
            self.aggressive = bool(kwargs["aggressive"])
        if "min_chars" in kwargs:
            self.min_chars = int(kwargs["min_chars"])

    def _convert_slice(self, raw_str: str) -> Optional[str]:
        if not self._converter_fn or len(raw_str) < self.min_chars:
            return None
        try:
            obj = json.loads(raw_str)
            if not isinstance(obj, (dict, list)):
                return None
            if isinstance(obj, dict) and "_toon" in obj:
                return None
            res = self._converter_fn(obj, aggressive=self.aggressive)
            if res and len(res) < len(raw_str):
                return res
        except Exception:
            return None
        return None

    def process_bracketed_paste(self, content: str) -> Optional[Sequence[Action]]:
        """Process paste content and toonify any embedded or pure JSON."""
        if not self._converter_fn or not content:
            return None

        # Check pure JSON first
        stripped = content.strip()
        if stripped.startswith(("{", "[")):
            lead_len = len(content) - len(content.lstrip())
            trail_len = len(content) - len(content.rstrip())
            end_idx = len(content) - trail_len if trail_len else len(content)
            core = content[lead_len:end_idx]

            converted = self._convert_slice(core)
            if converted is not None:
                new_text = content[:lead_len] + converted + content[end_idx:]
                payload = BRACKETED_PASTE_START + new_text.encode("utf-8") + BRACKETED_PASTE_END
                return [WriteAction(payload)]

        # Embedded JSON blocks scan
        decoder = json.JSONDecoder()
        out: list[str] = []
        pos = 0
        last_emit = 0
        content_len = len(content)
        any_converted = False

        while pos < content_len:
            ch = content[pos]
            if ch in ("{", "["):
                try:
                    obj, end_pos = decoder.raw_decode(content, pos)
                    raw_slice = content[pos:end_pos]
                    converted = self._convert_slice(raw_slice)
                    if converted is not None:
                        out.append(content[last_emit:pos])
                        out.append(converted)
                        last_emit = end_pos
                        pos = end_pos
                        any_converted = True
                        continue
                except Exception:
                    pass
            pos += 1

        if any_converted:
            out.append(content[last_emit:])
            new_text = "".join(out)
            payload = BRACKETED_PASTE_START + new_text.encode("utf-8") + BRACKETED_PASTE_END
            return [WriteAction(payload)]

        return None
