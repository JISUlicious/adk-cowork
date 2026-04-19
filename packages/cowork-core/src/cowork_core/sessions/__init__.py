"""ADK session service protocol + local (SQLite) implementation.

The protocol intentionally mirrors ADK's ``BaseSessionService`` with two
cowork-specific additions: ``register_context`` (so surfaces can stash a
builder for the non-JSON-safe ``CoworkToolContext``) and the usual async
CRUD. A future ``PostgresCoworkSessionService`` implements this protocol
against a SQL backend without touching FastAPI routes.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from cowork_core.sessions.sqlite import SqliteCoworkSessionService


@runtime_checkable
class CoworkSessionService(Protocol):
    """The surface cowork uses against ADK's session store.

    Callers should treat this as the public seam; cowork-specific methods
    (``register_context``) sit alongside ADK's standard CRUD
    (``create_session``, ``get_session``, etc.).
    """

    def register_context(self, session_id: str, builder: Any) -> None: ...

    async def create_session(
        self,
        *,
        app_name: str,
        user_id: str,
        state: dict[str, Any] | None = None,
        session_id: str | None = None,
    ) -> Any: ...

    async def get_session(
        self,
        *,
        app_name: str,
        user_id: str,
        session_id: str,
        config: Any | None = None,
    ) -> Any | None: ...

    async def list_sessions(
        self, *, app_name: str, user_id: str | None = None,
    ) -> Any: ...

    async def delete_session(
        self, *, app_name: str, user_id: str, session_id: str,
    ) -> None: ...

    async def append_event(self, session: Any, event: Any) -> Any: ...


__all__ = ["CoworkSessionService", "SqliteCoworkSessionService"]
