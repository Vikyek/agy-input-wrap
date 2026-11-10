"""
Action primitives and non-blocking scheduling for PTY stream interception.
"""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Optional, Sequence


@dataclass(frozen=True)
class Action:
    """Base class for interceptor actions."""
    pass


@dataclass(frozen=True)
class WriteAction(Action):
    """Write bytes to the child PTY."""
    data: bytes


@dataclass(frozen=True)
class SleepAction(Action):
    """Pause execution before dispatching subsequent actions."""
    seconds: float


class ActionScheduler:
    """
    Schedules and dispatches actions without blocking child output forwarding.

    When actions are queued (e.g., WriteAction, SleepAction, WriteAction),
    actions up to the first SleepAction are dispatched immediately.
    The scheduler then tracks the required pause duration, allowing the main
    event loop to continue forwarding child PTY output and handling terminal
    signals while waiting for the timer to expire.
    """

    def __init__(self) -> None:
        self._queue: list[Action] = []
        self._sleep_until: Optional[float] = None

    def enqueue(self, actions: Sequence[Action]) -> None:
        """Add actions to the scheduler queue."""
        self._queue.extend(actions)

    def has_pending(self) -> bool:
        """Return True if there are queued actions or an active sleep timer."""
        return bool(self._queue) or (self._sleep_until is not None)

    def time_until_ready(self) -> Optional[float]:
        """
        Return the seconds remaining until the next action can be dispatched.

        Returns:
            - None if the queue is empty and no timer is active.
            - 0.0 if actions are ready immediately.
            - float > 0.0 if waiting on a SleepAction timer.
        """
        if self._sleep_until is not None:
            now = time.monotonic()
            remaining = self._sleep_until - now
            return max(0.0, remaining)
        if self._queue:
            return 0.0
        return None

    def dispatch_ready(self, target_buf: bytearray) -> bool:
        """
        Dispatch all actions ready at the current moment into target_buf.

        Stops when encountering a SleepAction with duration > 0, setting
        the sleep timer.

        Returns:
            True if any bytes were written to target_buf, False otherwise.
        """
        now = time.monotonic()
        if self._sleep_until is not None:
            if now < self._sleep_until:
                return False
            self._sleep_until = None

        dispatched = False
        while self._queue:
            item = self._queue[0]
            if isinstance(item, WriteAction):
                self._queue.pop(0)
                target_buf.extend(item.data)
                dispatched = True
            elif isinstance(item, SleepAction):
                self._queue.pop(0)
                if item.seconds > 0:
                    self._sleep_until = time.monotonic() + item.seconds
                    break
            else:
                self._queue.pop(0)

        return dispatched
