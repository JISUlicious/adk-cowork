"""Per-user connection-limit abstraction.

``ConnectionLimiter`` is a thin protocol; ``InMemoryConnectionLimiter`` (in
``memory.py``) is the single-process default. A future Redis-backed impl
would satisfy the same protocol.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from cowork_server.limiter.memory import InMemoryConnectionLimiter


@runtime_checkable
class ConnectionLimiter(Protocol):
    """Track and limit per-user concurrent streaming connections."""

    async def acquire(self, user_id: str) -> None:
        """Raise ``HTTPException(429)`` if the user has too many connections."""
        ...

    async def release(self, user_id: str) -> None: ...


__all__ = ["ConnectionLimiter", "InMemoryConnectionLimiter"]
