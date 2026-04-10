"""Async rate limiting primitives for provider requests."""

from __future__ import annotations

import asyncio
import time


class AsyncRateLimiter:
    """Simple lock-based rate limiter with fixed minimum interval."""

    def __init__(self, requests_per_second: float) -> None:
        if requests_per_second <= 0:
            raise ValueError("requests_per_second must be > 0")
        self._min_interval = 1.0 / requests_per_second
        self._lock = asyncio.Lock()
        self._last_request_at = 0.0

    async def wait_turn(self) -> None:
        """Wait until a request can be issued under current limit."""
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_request_at
            if elapsed < self._min_interval:
                await asyncio.sleep(self._min_interval - elapsed)
            self._last_request_at = time.monotonic()
