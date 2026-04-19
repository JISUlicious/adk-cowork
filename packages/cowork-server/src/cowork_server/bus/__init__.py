"""Event bus abstraction for session event streaming.

The ``EventBus`` protocol decouples FastAPI routes from any particular pub/sub
backend. ``InMemoryEventBus`` (see ``memory.py``) is the default and the only
implementation today — it serves the single-process sidecar and small-team
web deployments. A future ``RedisEventBus`` (or other distributed backend)
slots in as a new module implementing the same protocol, no route surgery
required.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator, Protocol, runtime_checkable

from cowork_server.bus.memory import InMemoryEventBus


@runtime_checkable
class EventBus(Protocol):
    """Publish/subscribe interface for session events."""

    async def publish(self, session_id: str, payload: str) -> None: ...

    @asynccontextmanager
    async def subscribe(
        self, session_id: str,
    ) -> AsyncIterator[asyncio.Queue[str]]: ...  # type: ignore[override]

    async def close(self) -> None: ...


__all__ = ["EventBus", "InMemoryEventBus"]
