"""Out-of-band per-tool approval counters.

Approvals are granted by the UI (``POST /v1/sessions/{id}/approvals``)
and consumed by the permission callback on the next gated call of the
same tool. They are **not** ADK session state:

- ADK ``SessionService`` uses optimistic concurrency control — writes
  via a stale session handle raise ``last_update_time`` errors. When
  the user hits Approve mid-turn, our out-of-band ``append_event``
  races with whatever the runner is writing and eventually loses.
- Approvals are ephemeral — one-shot tokens that never need to survive
  a server restart. Persisting them would actually be unsafe (stale
  "approved to run python" from last week).

Interface is a protocol so a distributed deployment can swap in a
Redis-backed store without touching routes or the permission callback.
"""

from __future__ import annotations

import threading
from typing import Protocol, runtime_checkable


@runtime_checkable
class ApprovalStore(Protocol):
    """Per-session, per-tool approval counter."""

    def grant(self, session_id: str, tool_name: str) -> int:
        """Increment the counter for ``tool_name`` in this session.
        Returns the new count."""

    def consume(self, session_id: str, tool_name: str) -> bool:
        """If the counter is > 0, decrement and return True. Else False."""

    def list(self, session_id: str) -> dict[str, int]:
        """Return a snapshot of pending approvals for this session."""

    def clear(self, session_id: str) -> None:
        """Drop all pending approvals for a session (e.g. on delete)."""


class InMemoryApprovalStore:
    """Single-process default. Thread-safe; no persistence."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: dict[str, dict[str, int]] = {}

    def grant(self, session_id: str, tool_name: str) -> int:
        with self._lock:
            bucket = self._counts.setdefault(session_id, {})
            bucket[tool_name] = bucket.get(tool_name, 0) + 1
            return bucket[tool_name]

    def consume(self, session_id: str, tool_name: str) -> bool:
        with self._lock:
            bucket = self._counts.get(session_id)
            if not bucket:
                return False
            remaining = bucket.get(tool_name, 0)
            if remaining <= 0:
                return False
            bucket[tool_name] = remaining - 1
            return True

    def list(self, session_id: str) -> dict[str, int]:
        with self._lock:
            return dict(self._counts.get(session_id, {}))

    def clear(self, session_id: str) -> None:
        with self._lock:
            self._counts.pop(session_id, None)
