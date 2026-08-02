"""Async keyed locks."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager


class KeyedLockRegistry:
    def __init__(self) -> None:
        self._entries: dict[object, tuple[asyncio.Lock, int]] = {}
        self._guard = asyncio.Lock()

    @asynccontextmanager
    async def lock(self, key: object) -> AsyncIterator[None]:
        async with self._guard:
            lock, count = self._entries.get(key, (asyncio.Lock(), 0))
            self._entries[key] = (lock, count + 1)
        try:
            async with lock:
                yield
        finally:
            async with self._guard:
                current = self._entries.get(key)
                if current is not None:
                    lock, count = current
                    if count <= 1:
                        self._entries.pop(key, None)
                    else:
                        self._entries[key] = (lock, count - 1)
