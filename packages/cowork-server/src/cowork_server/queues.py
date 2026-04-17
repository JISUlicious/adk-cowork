"""Event bus abstraction for session event streaming.

``InMemoryEventBus`` is the default, using asyncio primitives with proper
locking and fan-out. Drop-in replacements (Redis Streams, etc.) implement
the same ``EventBus`` protocol.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator, Protocol, runtime_checkable


@runtime_checkable
class EventBus(Protocol):
    """Publish/subscribe interface for session events."""

    async def publish(self, session_id: str, payload: str) -> None: ...

    @asynccontextmanager
    async def subscribe(self, session_id: str) -> AsyncIterator[asyncio.Queue[str]]: ...  # type: ignore[override]

    async def close(self) -> None: ...


_MAX_QUEUE_SIZE = 1000


class InMemoryEventBus:
    """Lock-guarded, bounded, fan-out event bus using asyncio primitives.

    Multiple subscribers per session each get their own bounded queue.
    ``publish`` fans out to all active subscribers. Disconnected subscribers
    are cleaned up automatically via the context manager.
    """

    def __init__(self, max_queue_size: int = _MAX_QUEUE_SIZE) -> None:
        self._lock = asyncio.Lock()
        self._subscribers: dict[str, list[asyncio.Queue[str]]] = {}
        self._max_queue_size = max_queue_size

    async def publish(self, session_id: str, payload: str) -> None:
        async with self._lock:
            queues = self._subscribers.get(session_id, [])
        for q in queues:
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                # Drop oldest to make room — backpressure on slow consumers
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    q.put_nowait(payload)
                except asyncio.QueueFull:
                    pass

    @asynccontextmanager
    async def subscribe(self, session_id: str) -> AsyncIterator[asyncio.Queue[str]]:
        q: asyncio.Queue[str] = asyncio.Queue(maxsize=self._max_queue_size)
        async with self._lock:
            self._subscribers.setdefault(session_id, []).append(q)
        try:
            yield q
        finally:
            async with self._lock:
                subs = self._subscribers.get(session_id, [])
                try:
                    subs.remove(q)
                except ValueError:
                    pass
                if not subs:
                    self._subscribers.pop(session_id, None)

    async def has_subscribers(self, session_id: str) -> bool:
        async with self._lock:
            return bool(self._subscribers.get(session_id))

    async def close(self) -> None:
        async with self._lock:
            self._subscribers.clear()
