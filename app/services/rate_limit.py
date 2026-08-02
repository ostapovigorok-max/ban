"""In-memory sliding-window rate limiters."""

from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from datetime import timedelta

from app.utils.time import utc_now


class RateLimiter:
    def __init__(self, *, limit: int, window: timedelta) -> None:
        self._limit = limit
        self._window = window
        self._events: dict[object, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def allow(self, key: object) -> bool:
        now = utc_now().timestamp()
        cutoff = now - self._window.total_seconds()
        async with self._lock:
            bucket = self._events[key]
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= self._limit:
                return False
            bucket.append(now)
            return True

    async def clear(self) -> None:
        async with self._lock:
            self._events.clear()


admin_moderation_limiter = RateLimiter(limit=5, window=timedelta(minutes=1))
community_vote_limiter = RateLimiter(limit=30, window=timedelta(minutes=1))
