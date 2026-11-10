"""
Tests for AddDirSequencerPlugin and StreamProcessor.
"""

from __future__ import annotations

import unittest

from agy_input_wrap.actions import ActionScheduler, SleepAction, WriteAction
from agy_input_wrap.plugin_manager import PluginManager
from agy_input_wrap.plugins.add_dir_sequencer import AddDirSequencerPlugin
from agy_input_wrap.processor import StreamProcessor


class TestAddDirSequencerPlugin(unittest.TestCase):
    def setUp(self) -> None:
        self.plugin = AddDirSequencerPlugin(delay_sec=0.2)

    def test_normal_text_passthrough(self) -> None:
        """Normal text passes through untouched (returns None)."""
        self.assertIsNone(self.plugin.process_input(b"echo hello world\n"))
        self.assertIsNone(self.plugin.process_input(b"git status\r"))
        self.assertIsNone(self.plugin.process_input(b"a"))
        self.assertIsNone(self.plugin.process_bracketed_paste("echo hello world\n"))

    def test_single_line_add_dir_passthrough(self) -> None:
        """Single-line /add-dir without prompt passes through untouched."""
        # Without newline
        self.assertIsNone(self.plugin.process_input(b"/add-dir /path/to/repo"))
        self.assertIsNone(self.plugin.process_bracketed_paste("/add-dir /path/to/repo"))

        # With newline but no subsequent prompt text
        self.assertIsNone(self.plugin.process_input(b"/add-dir /path/to/repo\n"))
        self.assertIsNone(self.plugin.process_input(b"/add-dir /path/to/repo\r\n"))
        self.assertIsNone(self.plugin.process_bracketed_paste("/add-dir /path/to/repo\n"))

        # With trailing whitespace only
        self.assertIsNone(self.plugin.process_input(b"/add-dir /path/to/repo\n   \n\t"))

    def test_split_and_delay_sequencing(self) -> None:
        """Splits /add-dir <path>\\n<prompt> into timed sequence."""
        actions = self.plugin.process_input(b"/add-dir /foo\nbar")
        self.assertIsNotNone(actions)
        self.assertEqual(len(actions), 3)

        self.assertIsInstance(actions[0], WriteAction)
        self.assertEqual(actions[0].data, b"/add-dir /foo\r")

        self.assertIsInstance(actions[1], SleepAction)
        self.assertEqual(actions[1].seconds, 0.2)

        self.assertIsInstance(actions[2], WriteAction)
        self.assertEqual(actions[2].data, b"bar\r")

    def test_windows_crlf_newlines(self) -> None:
        """Handles \\r\\n newlines identically."""
        actions = self.plugin.process_input(b"/add-dir /foo/bar\r\nPlease review this code\r\n")
        self.assertIsNotNone(actions)
        self.assertEqual(len(actions), 3)
        self.assertEqual(actions[0].data, b"/add-dir /foo/bar\r")
        self.assertEqual(actions[1].seconds, 0.2)
        self.assertEqual(actions[2].data, b"Please review this code\r")

    def test_underscore_variant(self) -> None:
        """Supports /add_dir alias."""
        actions = self.plugin.process_input(b"/add_dir /my/dir\nexplain this")
        self.assertIsNotNone(actions)
        self.assertEqual(actions[0].data, b"/add-dir /my/dir\r")
        self.assertEqual(actions[2].data, b"explain this\r")

    def test_multiple_add_dirs(self) -> None:
        """Sequences multiple /add-dir lines before the prompt."""
        text = "/add-dir /dir1\n/add-dir /dir2\nStart investigation"
        actions = self.plugin.process_input(text.encode("utf-8"))
        self.assertIsNotNone(actions)
        # cmd1 -> sleep -> cmd2 -> sleep -> prompt
        self.assertEqual(len(actions), 5)
        self.assertEqual(actions[0].data, b"/add-dir /dir1\r")
        self.assertIsInstance(actions[1], SleepAction)
        self.assertEqual(actions[2].data, b"/add-dir /dir2\r")
        self.assertIsInstance(actions[3], SleepAction)
        self.assertEqual(actions[4].data, b"Start investigation\r")

    def test_bracketed_paste_single_line_prompt(self) -> None:
        """Bracketed paste is properly sequenced with trailing return."""
        actions = self.plugin.process_bracketed_paste("/add-dir /foo\nbar")
        self.assertIsNotNone(actions)
        self.assertEqual(actions[0].data, b"/add-dir /foo\r")
        self.assertIsInstance(actions[1], SleepAction)
        self.assertEqual(actions[2].data, b"bar\r")

    def test_bracketed_paste_multiline_prompt(self) -> None:
        """Multiline prompt in bracketed paste retains paste markers to prevent line-submit."""
        actions = self.plugin.process_bracketed_paste("/add-dir /foo\nline1\nline2")
        self.assertIsNotNone(actions)
        self.assertEqual(actions[0].data, b"/add-dir /foo\r")
        self.assertEqual(actions[2].data, b"\x1b[200~line1\nline2\x1b[201~\r")

    def test_configurable_delay(self) -> None:
        """Allows tuning the pause duration."""
        self.plugin.configure(delay_sec=0.150)
        actions = self.plugin.process_input(b"/add-dir /foo\nbar")
        self.assertIsNotNone(actions)
        self.assertEqual(actions[1].seconds, 0.150)


class TestStreamProcessorIntegration(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = PluginManager(load_builtins=True)
        self.scheduler = ActionScheduler()
        self.processor = StreamProcessor(self.manager, self.scheduler)
        self.to_child = bytearray()

    def test_stream_normal_text(self) -> None:
        self.processor.feed(b"hello world", self.to_child)
        self.assertEqual(bytes(self.to_child), b"hello world")
        self.assertFalse(self.scheduler.has_pending())

    def test_stream_unbracketed_add_dir(self) -> None:
        self.processor.feed(b"/add-dir /foo\nbar", self.to_child)
        # First write action is immediately dispatched to to_child
        self.assertEqual(bytes(self.to_child), b"/add-dir /foo\r")
        self.assertTrue(self.scheduler.has_pending())

        # Advance scheduler after sleep
        self.scheduler._sleep_until = 0.0
        self.scheduler.dispatch_ready(self.to_child)
        self.assertEqual(bytes(self.to_child), b"/add-dir /foo\rbar\r")

    def test_stream_bracketed_paste_add_dir(self) -> None:
        chunk = b"\x1b[200~/add-dir /foo\nbar\x1b[201~"
        self.processor.feed(chunk, self.to_child)
        self.assertEqual(bytes(self.to_child), b"/add-dir /foo\r")
        self.assertTrue(self.scheduler.has_pending())

        self.scheduler._sleep_until = 0.0
        self.scheduler.dispatch_ready(self.to_child)
        self.assertEqual(bytes(self.to_child), b"/add-dir /foo\rbar\r")

    def test_stream_bracketed_paste_normal_passthrough(self) -> None:
        chunk = b"\x1b[200~function test() { return 1; }\x1b[201~"
        self.processor.feed(chunk, self.to_child)
        self.assertEqual(bytes(self.to_child), chunk)
        self.assertFalse(self.scheduler.has_pending())


if __name__ == "__main__":
    unittest.main()
