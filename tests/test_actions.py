"""
Tests for ActionScheduler.
"""

from __future__ import annotations

import time
import unittest

from agy_input_wrap.actions import ActionScheduler, SleepAction, WriteAction


class TestActionScheduler(unittest.TestCase):
    def test_empty_scheduler(self) -> None:
        scheduler = ActionScheduler()
        buf = bytearray()
        self.assertFalse(scheduler.has_pending())
        self.assertIsNone(scheduler.time_until_ready())
        self.assertFalse(scheduler.dispatch_ready(buf))
        self.assertEqual(len(buf), 0)

    def test_pure_write_actions(self) -> None:
        scheduler = ActionScheduler()
        buf = bytearray()
        scheduler.enqueue([WriteAction(b"hello "), WriteAction(b"world")])
        self.assertTrue(scheduler.has_pending())
        self.assertEqual(scheduler.time_until_ready(), 0.0)

        dispatched = scheduler.dispatch_ready(buf)
        self.assertTrue(dispatched)
        self.assertEqual(bytes(buf), b"hello world")
        self.assertFalse(scheduler.has_pending())

    def test_sleep_and_wake(self) -> None:
        scheduler = ActionScheduler()
        buf = bytearray()
        scheduler.enqueue([
            WriteAction(b"part1"),
            SleepAction(0.05),
            WriteAction(b"part2"),
        ])

        # First dispatch should write part1 and set sleep timer
        dispatched = scheduler.dispatch_ready(buf)
        self.assertTrue(dispatched)
        self.assertEqual(bytes(buf), b"part1")
        self.assertTrue(scheduler.has_pending())

        time_left = scheduler.time_until_ready()
        self.assertIsNotNone(time_left)
        self.assertGreater(time_left, 0.0)

        # Immediate second dispatch before sleep expires should do nothing
        dispatched2 = scheduler.dispatch_ready(buf)
        self.assertFalse(dispatched2)
        self.assertEqual(bytes(buf), b"part1")

        # Wait for sleep to expire
        time.sleep(0.06)
        self.assertEqual(scheduler.time_until_ready(), 0.0)

        # Now part2 should be dispatched
        dispatched3 = scheduler.dispatch_ready(buf)
        self.assertTrue(dispatched3)
        self.assertEqual(bytes(buf), b"part1part2")
        self.assertFalse(scheduler.has_pending())


if __name__ == "__main__":
    unittest.main()
