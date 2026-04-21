"""Per-user notification store.

Mirrors the ``approvals.py`` shape: a ``Protocol`` + a thread-safe
in-memory default. The motivation is identical — notifications are
side-channel state that the UI needs to read and write at arbitrary
moments (poll from any tab, mark read from a click), and writing them
through the ADK session event list would collide with the runner's
OCC-protected appends the same way approvals did. See
``cowork_core/approvals.py:11–22``.

Deliberately ephemeral: server restart wipes pending notifications.
A persistent backend can swap in later without touching producers or
routes.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


# Kind strings kept as bare literals instead of an Enum so the wire
# dict round-trips through JSON without a conversion step — producers
# and the UI both read them directly.
NotificationKind = str  # "turn_complete" | "approval_needed" | "error"


@dataclass
class Notification:
    id: str
    user_id: str
    kind: NotificationKind
    text: str
    session_id: str | None = None
    project: str | None = None
    created_at: float = field(default_factory=time.time)
    read: bool = False

    def to_wire(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "text": self.text,
            "session_id": self.session_id,
            "project": self.project,
            "created_at": self.created_at,
            "read": self.read,
        }


@runtime_checkable
class NotificationStore(Protocol):
    """Per-user notification inbox."""

    def add(
        self,
        user_id: str,
        kind: NotificationKind,
        text: str,
        *,
        session_id: str | None = None,
        project: str | None = None,
    ) -> Notification:
        """Append a notification. Returns the stored record."""

    def list(self, user_id: str) -> list[Notification]:
        """Most-recent first snapshot of notifications for this user."""

    def mark_read(self, user_id: str, notification_id: str) -> bool:
        """Flip ``read`` to True for one entry. Returns False if it
        doesn't exist for this user."""

    def clear(self, user_id: str) -> int:
        """Drop all notifications for this user. Returns the count removed."""


class InMemoryNotificationStore:
    """Single-process default. Thread-safe; no persistence."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_user: dict[str, list[Notification]] = {}

    def add(
        self,
        user_id: str,
        kind: NotificationKind,
        text: str,
        *,
        session_id: str | None = None,
        project: str | None = None,
    ) -> Notification:
        note = Notification(
            id=f"ntf-{uuid.uuid4().hex[:16]}",
            user_id=user_id,
            kind=kind,
            text=text,
            session_id=session_id,
            project=project,
        )
        with self._lock:
            self._by_user.setdefault(user_id, []).append(note)
        return note

    def list(self, user_id: str) -> list[Notification]:
        with self._lock:
            return list(reversed(self._by_user.get(user_id, [])))

    def mark_read(self, user_id: str, notification_id: str) -> bool:
        with self._lock:
            bucket = self._by_user.get(user_id, [])
            for n in bucket:
                if n.id == notification_id:
                    n.read = True
                    return True
            return False

    def clear(self, user_id: str) -> int:
        with self._lock:
            bucket = self._by_user.pop(user_id, [])
            return len(bucket)
