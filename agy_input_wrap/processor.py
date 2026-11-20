"""
PTY stream processor with bracketed paste parsing and plugin integration.
"""

from __future__ import annotations

import re
from typing import Optional

from agy_input_wrap.actions import ActionScheduler, WriteAction
from agy_input_wrap.plugin_manager import PluginManager

BRACKETED_PASTE_START = b"\x1b[200~"
BRACKETED_PASTE_END = b"\x1b[201~"
ESC_TIMEOUT_SEC = 0.025
MAX_PASTE_BYTES = 10 * 1024 * 1024  # 10 MiB safety cap

# Kitty keyboard protocol and xterm modifyOtherKeys Enter variants
_KITTY_MOD_ENTER_RE = re.compile(rb"^\x1b\[13;(?:[2-9]|[1-9]\d+)(?::[12])?u$")
_KITTY_PLAIN_ENTER_RE = re.compile(rb"^\x1b\[13(?:;1(?::[12])?)?u$")
_XTERM_MOD_ENTER_RE = re.compile(rb"^\x1b\[27;(?:[2-9]|[1-9]\d+);13~$")
_XTERM_PLAIN_ENTER_RE = re.compile(rb"^\x1b\[27;1;13~$")
_ADD_DIR_PREFIX_RE = re.compile(r"^\s*/add[-_]dir\s+")
_KITTY_PUSH_RE = re.compile(rb"\x1b\[>[0-9;]*u")
_KITTY_POP_RE = re.compile(rb"\x1b\[<[0-9;]*u")


def _is_pending_escape_prefix(buf: bytes) -> bool:
    """Return True if buf is an incomplete bracketed-paste or CSI escape sequence."""
    if BRACKETED_PASTE_START.startswith(buf):
        return True
    if buf.startswith(b"\x1b[") and 2 <= len(buf) < 32:
        return all(0x20 <= b <= 0x3F for b in buf[2:])
    return False


def _consume_escape_sequence(buf: bytes) -> tuple[bytes, bytes]:
    """Split one complete escape sequence from the front of buf."""
    if len(buf) <= 1:
        return buf, b""
    second = buf[1]
    if second == ord("["):
        limit = min(len(buf), 32)
        for idx in range(2, limit):
            if 0x40 <= buf[idx] <= 0x7E:
                return buf[: idx + 1], buf[idx + 1 :]
        return buf[:limit], buf[limit:]
    if second == ord("O") and len(buf) >= 3:
        return buf[:3], buf[3:]
    return buf[:2], buf[2:]


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
        self._line_buf = ""
        self._line_valid = True
        self._kitty_keyboard_enabled = False
        self._output_tail = b""

    def observe_output(self, data: bytes) -> None:
        """Track child PTY terminal mode changes (e.g. Kitty keyboard protocol)."""
        if not data:
            return
        buf = self._output_tail + data
        self._output_tail = buf[-16:]

        last_push = -1
        for m in _KITTY_PUSH_RE.finditer(buf):
            last_push = m.end()
        last_pop = -1
        for m in _KITTY_POP_RE.finditer(buf):
            last_pop = m.end()

        if last_push > last_pop:
            self._kitty_keyboard_enabled = True
        elif last_pop > last_push:
            self._kitty_keyboard_enabled = False

    def has_pending_escape(self) -> bool:
        """Return True if trailing bytes await completion of escape sequence."""
        return not self._in_paste and bool(self._pending_esc)

    def flush_pending_escape(self, to_child: bytearray) -> None:
        """Flush buffered escape prefix when timeout expires."""
        if not self._pending_esc:
            return
        flushed = bytes(self._pending_esc)
        self._pending_esc.clear()

        actions = self.plugin_manager.process_input(flushed)
        if actions:
            self._reset_line()
            self.scheduler.enqueue(actions)
            self.scheduler.dispatch_ready(to_child)
        else:
            self._emit_raw(flushed, to_child)

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
                    self._process_plain_chunk(cur, to_child)
                    break

                if idx > 0:
                    self._process_plain_chunk(cur[:idx], to_child)
                    cur = cur[idx:]

                # Now cur starts with b'\x1b'
                if cur.startswith(BRACKETED_PASTE_START):
                    self._in_paste = True
                    self._paste_buf.clear()
                    cur = cur[len(BRACKETED_PASTE_START):]
                    continue

                if _is_pending_escape_prefix(cur):
                    self._pending_esc.extend(cur)
                    break

                seq, cur = _consume_escape_sequence(cur)
                self._process_escape_sequence(seq, to_child)

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
                        self._line_valid = False
                        self._dispatch_raw_bytes(flushed, to_child)
                    break

    def _reset_line(self) -> None:
        self._line_buf = ""
        self._line_valid = True

    def _emit_raw(self, data: bytes, to_child: bytearray) -> None:
        if not data:
            return
        if self.scheduler.has_pending():
            self.scheduler.enqueue([WriteAction(data)])
        else:
            to_child.extend(data)

    def _maybe_intercept_add_dir_newline(self, raw_seq: bytes, to_child: bytearray) -> bool:
        """
        If the current typed line is `/add-dir <path>` and a newline-continuation
        key is pressed, submit `/add-dir <path>` and pause before subsequent input.
        """
        if not self._line_valid:
            return False
        sequencer = self.plugin_manager.get("add_dir_sequencer")
        if sequencer is None or not sequencer.enabled:
            return False
        matches_fn = getattr(sequencer, "matches_line", None)
        submit_fn = getattr(sequencer, "build_submit_actions", None)
        if not (callable(matches_fn) and callable(submit_fn) and matches_fn(self._line_buf)):
            return False

        actions = submit_fn(kitty_escape=self._kitty_keyboard_enabled)
        self._reset_line()
        self.scheduler.enqueue(actions)
        self.scheduler.dispatch_ready(to_child)
        return True

    def _process_plain_chunk(self, data: bytes, to_child: bytearray) -> None:
        """Process raw non-escape bytes, checking plugins and tracking typed lines."""
        if not data:
            return

        actions = self.plugin_manager.process_input(data)
        if actions:
            self._reset_line()
            self.scheduler.enqueue(actions)
            self.scheduler.dispatch_ready(to_child)
            return

        text_start = 0
        idx = 0
        length = len(data)
        while idx < length:
            b = data[idx]
            if b >= 0x20 and b != 0x7F:
                idx += 1
                continue

            if idx > text_start:
                seg = data[text_start:idx]
                self._emit_raw(seg, to_child)
                if self._line_valid:
                    try:
                        self._line_buf += seg.decode("utf-8")
                    except UnicodeDecodeError:
                        self._line_valid = False

            ctrl = data[idx : idx + 1]
            if b in (0x0D, 0x03, 0x15):  # CR, Ctrl+C, Ctrl+U
                self._emit_raw(ctrl, to_child)
                self._reset_line()
            elif b in (0x7F, 0x08):  # DEL, BS
                self._emit_raw(ctrl, to_child)
                if self._line_valid and self._line_buf:
                    self._line_buf = self._line_buf[:-1]
            elif b == 0x09:  # Tab
                self._emit_raw(ctrl, to_child)
                if not (self._line_valid and _ADD_DIR_PREFIX_RE.match(self._line_buf)):
                    self._line_valid = False
            elif b == 0x0A:  # LF / Ctrl+J
                if not self._maybe_intercept_add_dir_newline(ctrl, to_child):
                    self._emit_raw(ctrl, to_child)
                    self._line_valid = False
            else:
                self._emit_raw(ctrl, to_child)
                self._line_valid = False

            idx += 1
            text_start = idx

        if text_start < length:
            seg = data[text_start:]
            self._emit_raw(seg, to_child)
            if self._line_valid:
                try:
                    self._line_buf += seg.decode("utf-8")
                except UnicodeDecodeError:
                    self._line_valid = False

    def _process_escape_sequence(self, seq: bytes, to_child: bytearray) -> None:
        """Process a single escape sequence outside bracketed paste."""
        if not seq:
            return

        if (
            seq in (b"\x1b\r", b"\x1b\n")
            or _KITTY_MOD_ENTER_RE.match(seq)
            or _XTERM_MOD_ENTER_RE.match(seq)
        ):
            if not self._maybe_intercept_add_dir_newline(seq, to_child):
                self._emit_raw(seq, to_child)
                self._line_valid = False
            return

        if _KITTY_PLAIN_ENTER_RE.match(seq) or _XTERM_PLAIN_ENTER_RE.match(seq):
            self._emit_raw(seq, to_child)
            self._reset_line()
            return

        actions = self.plugin_manager.process_input(seq)
        if actions:
            self._reset_line()
            self.scheduler.enqueue(actions)
            self.scheduler.dispatch_ready(to_child)
            return

        self._emit_raw(seq, to_child)
        self._line_valid = False

    def _dispatch_raw_bytes(self, data: bytes, to_child: bytearray) -> None:
        """Route raw bytes through plugins or default passthrough."""
        if not data:
            return

        actions = self.plugin_manager.process_input(data)
        if actions:
            self._reset_line()
            self.scheduler.enqueue(actions)
            self.scheduler.dispatch_ready(to_child)
        else:
            self._emit_raw(data, to_child)

    def _handle_paste_payload(self, payload: bytes, to_child: bytearray) -> None:
        """Handle a completed bracketed paste payload."""
        text = payload.decode("utf-8", errors="replace")
        actions = self.plugin_manager.process_bracketed_paste(text)
        if actions:
            self._reset_line()
            self.scheduler.enqueue(actions)
            self.scheduler.dispatch_ready(to_child)
        else:
            if "\n" not in text and "\r" not in text and self._line_valid:
                self._line_buf += text
            else:
                self._line_valid = False
            # Passthrough original bracketed paste untouched
            raw_paste = BRACKETED_PASTE_START + payload + BRACKETED_PASTE_END
            self._emit_raw(raw_paste, to_child)
