"""
PTY execution engine with raw mode, winsize forwarding, and signal restoration.
"""

from __future__ import annotations

import atexit
import errno
import fcntl
import os
import pty
import select
import signal
import sys
import termios
import tty
from typing import Any, Optional, Sequence

from agy_input_wrap.actions import ActionScheduler
from agy_input_wrap.plugin_manager import PluginManager
from agy_input_wrap.processor import ESC_TIMEOUT_SEC, StreamProcessor


def _sync_winsize(src_fd: int, dst_fd: int) -> None:
    """Synchronize window dimensions between terminal file descriptors."""
    try:
        buf = fcntl.ioctl(src_fd, termios.TIOCGWINSZ, b"\x00" * 8)
        fcntl.ioctl(dst_fd, termios.TIOCSWINSZ, buf)
    except OSError:
        pass


def run_pty_proxy(
    cmd: Sequence[str],
    plugin_manager: PluginManager,
) -> int:
    """
    Run `cmd` in a child PTY proxy with raw mode, winsize propagation,
    termios restoration, and modular input stream interception.
    """
    stdin_fd = sys.stdin.fileno()
    stdout_fd = sys.stdout.fileno()

    # If standard I/O is not a terminal, pass execution directly to the command
    if not (os.isatty(stdin_fd) and os.isatty(stdout_fd)):
        os.execvp(cmd[0], list(cmd))

    old_termios = termios.tcgetattr(stdin_fd)
    master_fd, slave_fd = pty.openpty()
    _sync_winsize(stdin_fd, slave_fd)

    winch_r, winch_w = os.pipe()
    os.set_blocking(winch_r, False)
    os.set_blocking(winch_w, False)

    pid = os.fork()
    if pid == 0:
        # Child process: configure new controlling terminal session
        os.close(master_fd)
        os.close(winch_r)
        os.close(winch_w)
        os.setsid()
        fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)
        os.dup2(slave_fd, 0)
        os.dup2(slave_fd, 1)
        os.dup2(slave_fd, 2)
        if slave_fd > 2:
            os.close(slave_fd)
        os.execvp(cmd[0], list(cmd))

    # Parent process
    os.close(slave_fd)
    os.set_blocking(master_fd, False)

    def _restore_terminal() -> None:
        try:
            termios.tcsetattr(stdin_fd, termios.TCSADRAIN, old_termios)
        except OSError:
            pass

    # Ensure terminal state is restored on any unexpected exit
    atexit.register(_restore_terminal)

    def _on_winch(_signum: int, _frame: Any) -> None:
        try:
            os.write(winch_w, b"\x01")
        except OSError:
            pass

    prev_winch = signal.signal(signal.SIGWINCH, _on_winch)
    tty.setraw(stdin_fd, when=termios.TCSADRAIN)

    scheduler = ActionScheduler()
    processor = StreamProcessor(plugin_manager, scheduler)

    to_child = bytearray()
    to_stdout = bytearray()
    stdin_open = True
    child_open = True

    try:
        while child_open or to_stdout:
            # Check if any delayed actions are ready to dispatch
            scheduler.dispatch_ready(to_child)

            rlist: list[int] = [winch_r]
            wlist: list[int] = []

            if stdin_open and child_open:
                rlist.append(stdin_fd)
            if child_open:
                rlist.append(master_fd)
            if to_child and child_open:
                wlist.append(master_fd)
            if to_stdout:
                wlist.append(stdout_fd)

            # Calculate appropriate select() timeout
            timeout: Optional[float] = None
            if processor.has_pending_escape():
                timeout = ESC_TIMEOUT_SEC

            sched_time = scheduler.time_until_ready()
            if sched_time is not None:
                if timeout is None or sched_time < timeout:
                    timeout = sched_time

            try:
                readable, writable, _ = select.select(rlist, wlist, [], timeout)
            except InterruptedError:
                continue

            # Check timers on wake
            if processor.has_pending_escape():
                processor.flush_pending_escape(to_child)
            scheduler.dispatch_ready(to_child)

            if winch_r in readable:
                try:
                    os.read(winch_r, 1024)
                except OSError:
                    pass
                _sync_winsize(stdin_fd, master_fd)

            if stdin_fd in readable:
                try:
                    chunk = os.read(stdin_fd, 65536)
                except OSError:
                    chunk = b""
                if not chunk:
                    stdin_open = False
                else:
                    processor.feed(chunk, to_child)

            if master_fd in readable:
                try:
                    out_chunk = os.read(master_fd, 65536)
                except OSError as exc:
                    if exc.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
                        out_chunk = None
                    else:
                        out_chunk = b""
                if out_chunk == b"":
                    child_open = False
                elif out_chunk:
                    to_stdout.extend(out_chunk)

            if master_fd in writable and to_child:
                try:
                    written = os.write(master_fd, to_child)
                    del to_child[:written]
                except OSError as exc:
                    if exc.errno not in (errno.EAGAIN, errno.EWOULDBLOCK):
                        child_open = False

            if stdout_fd in writable and to_stdout:
                try:
                    written = os.write(stdout_fd, to_stdout)
                    del to_stdout[:written]
                except OSError:
                    break
    finally:
        atexit.unregister(_restore_terminal)
        _restore_terminal()
        signal.signal(signal.SIGWINCH, prev_winch)
        for fd in (master_fd, winch_r, winch_w):
            try:
                os.close(fd)
            except OSError:
                pass

    _, status = os.waitpid(pid, 0)
    return os.waitstatus_to_exitcode(status)
