"""
Mock PTY automated integration tests verifying real PTY passthrough,
single-line preservation, and timed sequencing of /add-dir commands.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import pty
import select
import subprocess
import sys
import tempfile
import time
import unittest


CHILD_RECORDER_SCRIPT = """
import os
import sys
import time
import json
import tty

log_file = sys.argv[1]
records = []

try:
    tty.setraw(0)
except Exception:
    pass

while True:
    try:
        data = os.read(0, 4096)
        if not data:
            break
        records.append({
            "time": time.monotonic(),
            "bytes": list(data),
            "text": data.decode("utf-8", errors="replace"),
        })
        with open(log_file, "w") as f:
            json.dump(records, f)
        if b"__EXIT__" in data:
            break
    except Exception:
        break
"""


class TestMockPTYIntegration(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.log_path = Path(self.temp_dir.name) / "pty_events.json"
        self.child_script_path = Path(self.temp_dir.name) / "recorder.py"
        self.child_script_path.write_text(CHILD_RECORDER_SCRIPT)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _run_with_pty(self, inputs: list[bytes], delay_ms: int = 150) -> list[dict]:
        """
        Runs agy-input-wrap in a pseudo-terminal pair, feeds input chunks,
        and retrieves recorded child PTY events with timestamps.
        """
        master_fd, slave_fd = pty.openpty()

        wrapper_bin = Path(__file__).resolve().parent.parent / "bin" / "agy-input-wrap"
        cmd = [
            sys.executable,
            str(wrapper_bin),
            "--delay-ms",
            str(delay_ms),
            sys.executable,
            "-u",
            str(self.child_script_path),
            str(self.log_path),
        ]

        proc = subprocess.Popen(
            cmd,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            close_fds=True,
        )
        os.close(slave_fd)

        # Allow child process and wrapper to initialize
        time.sleep(0.2)

        try:
            for chunk in inputs:
                os.write(master_fd, chunk)
                time.sleep(0.05)

            # Wait for all actions to settle
            wait_time = (delay_ms / 1000.0) + 0.4
            time.sleep(wait_time)

            # Send exit marker
            os.write(master_fd, b"__EXIT__\n")
            time.sleep(0.1)

            # Drain any pending output from master_fd
            while True:
                r, _, _ = select.select([master_fd], [], [], 0.05)
                if not r:
                    break
                try:
                    out = os.read(master_fd, 1024)
                    if not out:
                        break
                except OSError:
                    break
        finally:
            try:
                proc.terminate()
                proc.wait(timeout=1.0)
            except Exception:
                pass
            try:
                os.close(master_fd)
            except OSError:
                pass

        if not self.log_path.exists():
            return []

        try:
            with open(self.log_path, "r") as f:
                return json.load(f)
        except Exception:
            return []

    def test_passthrough_normal_text(self) -> None:
        """Verifies normal text passes through directly without alteration."""
        events = self._run_with_pty([b"echo hello\r"])
        combined_text = "".join(e["text"] for e in events)
        self.assertIn("echo hello", combined_text)

    def test_passthrough_single_line_add_dir(self) -> None:
        """Verifies single-line /add-dir passes through untouched without sequencing delay."""
        events = self._run_with_pty([b"/add-dir /home/v/single\r"])
        combined_text = "".join(e["text"] for e in events)
        self.assertIn("/add-dir /home/v/single", combined_text)

    def test_splitting_and_delay_sequencing(self) -> None:
        """Verifies /add-dir <path>\\n<prompt> is split and sequenced with delay."""
        delay_ms = 180
        events = self._run_with_pty([b"/add-dir /target/dir\nexplain this repo\n"], delay_ms=delay_ms)

        # Find the event with /add-dir and the event with prompt
        add_dir_event = None
        prompt_event = None

        for e in events:
            if "/add-dir /target/dir" in e["text"] and add_dir_event is None:
                add_dir_event = e
            if "explain this repo" in e["text"] and prompt_event is None:
                prompt_event = e

        self.assertIsNotNone(add_dir_event, "Child did not receive /add-dir command")
        self.assertIsNotNone(prompt_event, "Child did not receive prompt command")

        # Verify sequencing order and delay
        time_diff = prompt_event["time"] - add_dir_event["time"]
        expected_min_delay = (delay_ms / 1000.0) * 0.8  # allow slight timing jitter
        self.assertGreaterEqual(
            time_diff,
            expected_min_delay,
            f"Prompt was delivered too quickly ({time_diff:.3f}s), delay was not honored.",
        )

        # Verify command termination with carriage return (\r)
        self.assertTrue(
            bytes(add_dir_event["bytes"]).endswith(b"\r")
            or b"/add-dir /target/dir\r" in bytes(add_dir_event["bytes"]),
            f"Command was not submitted with carriage return: {add_dir_event['bytes']}",
        )

    def test_bracketed_paste_sequencing(self) -> None:
        """Verifies bracketed paste /add-dir <path>\\n<prompt> is also split and sequenced."""
        delay_ms = 180
        paste_payload = b"\x1b[200~/add-dir /bracketed/path\nrun verification\x1b[201~"
        events = self._run_with_pty([paste_payload], delay_ms=delay_ms)

        add_dir_event = None
        prompt_event = None

        for e in events:
            if "/add-dir /bracketed/path" in e["text"] and add_dir_event is None:
                add_dir_event = e
            if "run verification" in e["text"] and prompt_event is None:
                prompt_event = e

        self.assertIsNotNone(add_dir_event, "Child did not receive bracketed /add-dir")
        self.assertIsNotNone(prompt_event, "Child did not receive bracketed prompt")

        time_diff = prompt_event["time"] - add_dir_event["time"]
        self.assertGreaterEqual(time_diff, 0.12)


if __name__ == "__main__":
    unittest.main()
