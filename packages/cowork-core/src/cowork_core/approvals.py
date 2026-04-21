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

The separate ``ApprovalEventLog`` records each approval as a
replayable envelope so the UI can mark the original tool call as
decided on history fetch — without ever touching the ADK session's
event list (which would collide with the runner's OCC-protected
appends).
"""

from __future__ import annotations

import threading
import time
import uuid
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


class InMemoryApprovalEventLog:
    """Queue of approval decisions awaiting promotion into the session's
    event list.

    When the user hits Approve we can't safely ``append_event`` to the
    ADK session from the HTTP handler — ``InMemorySessionService``
    updates ``session.last_update_time`` on every append, and the
    runner is appending against its own session handle throughout a
    turn. An interleaved write from the route races the runner's next
    append and trips the ``last_update_time`` check (see module
    docstring).

    Instead we:
      1. record the approval here (and publish it on the bus for the
         live UI),
      2. drain this queue *inside* ``_run_turn`` before
         ``runner.run_async`` starts — at that point no runner is
         active for the session, so the write is safe and the event
         joins the session's real event list.

    The queued dict is wire-compatible with an ADK Event so the same
    payload flows through the bus and the `session_service`.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pending: dict[str, list[dict]] = {}

    def record(
        self,
        session_id: str,
        tool_name: str,
        tool_call_id: str,
    ) -> dict:
        """Queue an approval event and return the wire dict. The
        ``id`` here is what gets persisted later in the session, so the
        bus payload and the replayed history share the same identity
        — clients can safely dedupe if they ever need to. """

        event = {
            "id": f"appr-{uuid.uuid4().hex[:16]}",
            "author": "cowork-server",
            "invocationId": "",
            "timestamp": time.time(),
            "actions": {
                "stateDelta": {
                    f"cowork:approval:{tool_call_id}": {
                        "tool": tool_name,
                        "status": "approved",
                    },
                },
            },
        }
        with self._lock:
            self._pending.setdefault(session_id, []).append(event)
        return event

    def drain(self, session_id: str) -> list[dict]:
        """Pop and return all pending approvals for a session. Called
        by ``_run_turn`` right before invoking the runner."""

        with self._lock:
            return self._pending.pop(session_id, [])

    def clear(self, session_id: str) -> None:
        with self._lock:
            self._pending.pop(session_id, None)
