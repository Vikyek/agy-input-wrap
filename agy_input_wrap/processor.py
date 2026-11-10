"""
PTY stream processor with bracketed paste parsing and plugin integration.
"""

from __future__ import annotations

from typing import Optional

from agy_input_wrap.actions import ActionScheduler, WriteAction
from agy_input_wrap.plugin_manager import PluginManager

BRACKETED_PASTE_START = b"\x1b[200~"
BRACKETED_PASTE_END = b"\x1b[201~"
ESC_TIMEOUT_SEC = 0.025
MAX_PASTE_BYTES = 10 * 1024 * 1024  # 10 MiB safety cap


class StreamProcessor:
    """
    Incremental byte-stream parser that handles bracketed pastes and routes
    input to the PluginManager and ActionScheduler.
    """

    def __init__(
        self,
        plugin_manager: PluginManager,
        scheduler: ActionScheduler,
        *,
        max_paste_bytes: int = MAX_PASTE_BYTES,
    ) -> None:
        self.plugin_manager = plugin_manager
        self.scheduler = scheduler
        self._max_paste_bytes = max_paste_bytes
        self._in_paste = False
        self._pending_esc = bytearray()
        self._paste_buf = bytearray()

    def has_pending_escape(self) -> bool:
        """Return True if trailing bytes await completion of escape sequence."""
        return not self._in_paste and bool(self._pending_esc)

    def flush_pending_escape(self, to_child: bytearray) -> None:
        """Flush buffered escape prefix when timeout expires."""
        if not self._pending_esc:
            return
        flushed = bytes(self._pending_esc)
        self._pending_esc.clear()

        # Check if raw input matches any plugin hook
        actions = self.plugin_manager.process_input(flushed)
        if actions:
            self.scheduler.enqueue(actions)
            self.scheduler.dispatch_ready(to_child)
        else:
            if self.scheduler.has_pending():
                self.scheduler.enqueue([WriteAction(flushed)])
            else:
                to_child.extend(flushed)

    def feed(self, chunk: bytes, to_child: bytearray) -> None:
        """
        Process an incoming chunk of bytes from stdin.
        """
        cur = chunk

        # If we had a pending escape prefix, combine it
        if self._pending_esc and not self._in_paste:
            cur = bytes(self._pending_esc) + cur
            self._pending_esc.clear()

        while cur or (self._in_paste and self._paste_buf):
            if not self._in_paste:
                idx = cur.find(b"\x1b")
                if idx == -1:
                    # No escape character in chunk; entire buffer is normal input
                    self._dispatch_raw_bytes(cur, to_child)
                    break

                if idx > 0:
                    # Emit normal bytes preceding the escape character
                    prefix = cur[:idx]
                    self._dispatch_raw_bytes(prefix, to_child)
                    cur = cur[idx:]

                # Now cur starts with b'\x1b'
                if cur.startswith(BRACKETED_PASTE_START):
                    self._in_paste = True
                    self._paste_buf.clear()
                    cur = cur[len(BRACKETED_PASTE_START):]
                    continue

                if BRACKETED_PASTE_START.startswith(cur):
                    # cur is a strict prefix of BRACKETED_PASTE_START (e.g. b'\x1b', b'\x1b[', b'\x1b[2')
                    self._pending_esc.extend(cur)
                    break

                # An escape sequence that is NOT bracketed paste start (e.g. arrow keys, Esc key followed by text)
                self._dispatch_raw_bytes(cur, to_child)
                break

            else:
                # Inside bracketed paste
                self._paste_buf.extend(cur)
                cur = b""

                end_idx = self._paste_buf.find(BRACKETED_PASTE_END)
                if end_idx != -1:
                    payload = bytes(self._paste_buf[:end_idx])
                    remainder = bytes(self._paste_buf[end_idx + len(BRACKETED_PASTE_END):])
                    self._in_paste = False
                    self._paste_buf.clear()

                    self._handle_paste_payload(payload, to_child)

                    # Continue loop with any bytes trailing the paste end marker
                    cur = remainder
                else:
                    # Safety check for paste buffer size
                    if len(self._paste_buf) > self._max_paste_bytes:
                        # Flush oversized buffer as raw bracketed paste
                        flushed = BRACKETED_PASTE_START + bytes(self._paste_buf)
                        self._paste_buf.clear()
                        self._in_paste = False
                        self._dispatch_raw_bytes(flushed, to_child)
                    break

    def _dispatch_raw_bytes(self, data: bytes, to_child: bytearray) -> None:
        """Route raw bytes through plugins or default passthrough."""
        if not data:
            return

        actions = self.plugin_manager.process_input(data)
        if actions:
            self.scheduler.enqueue(actions)
            self.scheduler.dispatch_ready(to_child)
        else:
            if self.scheduler.has_pending():
                self.scheduler.enqueue([WriteAction(data)])
            else:
                to_child.extend(data)

    def _handle_paste_payload(self, payload: bytes, to_child: bytearray) -> None:
        """Handle a completed bracketed paste payload."""
        text = payload.decode("utf-8", errors="replace")
        actions = self.plugin_manager.process_bracketed_paste(text)
        if actions:
            self.scheduler.enqueue(actions)
            self.scheduler.dispatch_ready(to_child)
        else:
            # Passthrough original bracketed paste untouched
            raw_paste = BRACKETED_PASTE_START + payload + BRACKETED_PASTE_END
            if self.scheduler.has_pending():
                self.scheduler.enqueue([WriteAction(raw_paste)])
            else:
                to_child.extend(raw_paste)
