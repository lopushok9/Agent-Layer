"""Sliding-window rate limiter."""

import asyncio
import time
from collections import deque


class RateLimiter:
    """Async-safe sliding-window rate limiter.

    ``acquire()`` blocks until a request slot is available.
    """

    def __init__(self, max_calls: int, window_seconds: float = 60.0):
        self._max_calls = max_calls
        self._window = window_seconds
        self._calls: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            # drop timestamps outside the window
            while self._calls and self._calls[0] <= now - self._window:
                self._calls.popleft()

            if len(self._calls) >= self._max_calls:
                sleep_for = self._calls[0] + self._window - now
                if sleep_for > 0:
                    await asyncio.sleep(sleep_for)
                # clean up again after sleeping
                now = time.monotonic()
                while self._calls and self._calls[0] <= now - self._window:
                    self._calls.popleft()

            self._calls.append(time.monotonic())
