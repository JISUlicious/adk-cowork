"""Single-process in-memory implementation of ``ConnectionLimiter``.

Per-user counter guarded by one asyncio.Lock. Exceeding the cap raises
``HTTPException(429)`` so the FastAPI layer can reject the stream without
extra wiring.
"""

from __future__ import annotations

import asyncio

from fastapi import HTTPException

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
