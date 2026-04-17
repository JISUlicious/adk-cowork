"""Per-user connection limiting for SSE/WebSocket streams.

Prevents a single user (or runaway client) from exhausting server resources.
The ``ConnectionLimiter`` protocol allows swapping in a distributed
implementation (e.g. Redis-backed) later.
"""

from __future__ import annotations

import asyncio
from typing import Protocol, runtime_checkable

from fastapi import HTTPException


@runtime_checkable
class ConnectionLimiter(Protocol):
    """Track and limit per-user concurrent streaming connections."""

    async def acquire(self, user_id: str) -> None:
        """Raise HTTPException(429) if the user has too many connections."""
        ...

    async def release(self, user_id: str) -> None: ...


_DEFAULT_MAX_PER_USER = 20


class InMemoryConnectionLimiter:
    """asyncio.Lock-guarded per-user counter with configurable max."""

    def __init__(self, max_per_user: int = _DEFAULT_MAX_PER_USER) -> None:
        self._lock = asyncio.Lock()
        self._counts: dict[str, int] = {}
        self._max = max_per_user

    async def acquire(self, user_id: str) -> None:
        async with self._lock:
            current = self._counts.get(user_id, 0)
            if current >= self._max:
                raise HTTPException(
                    status_code=429,
                    detail=f"too many concurrent connections (max {self._max})",
                )
            self._counts[user_id] = current + 1

    async def release(self, user_id: str) -> None:
        async with self._lock:
            current = self._counts.get(user_id, 0)
            if current <= 1:
                self._counts.pop(user_id, None)
            else:
                self._counts[user_id] = current - 1

    @property
    def snapshot(self) -> dict[str, int]:
        """Return a copy of current counts for monitoring."""
        return dict(self._counts)
