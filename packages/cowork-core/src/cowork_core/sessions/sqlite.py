"""Local (SQLite) ``CoworkSessionService`` — the default backend today.

Wraps ADK's ``SqliteSessionService`` and injects the non-serializable
``CoworkToolContext`` back into each session's in-memory state using a
registered builder callable. The wrapper pattern was originally defined in
``runner.py`` and moved here in Phase 3a so distributed backends can reuse
the same context-builder seam.
"""

from __future__ import annotations

from typing import Any

from google.adk.sessions import Session as AdkSession
from google.adk.sessions.base_session_service import (
    BaseSessionService,
    GetSessionConfig,
    ListSessionsResponse,
)
from google.adk.sessions.sqlite_session_service import SqliteSessionService

from cowork_core.tools import COWORK_CONTEXT_KEY, CoworkToolContext

# A no-arg callable that returns a live CoworkToolContext. Stored by
# open_session/resume_session so get_session can rebuild the context for
# any subsequent request (the ADK store only persists JSON-safe state).
ContextBuilder = Any  # Callable[[], CoworkToolContext]


class SqliteCoworkSessionService(BaseSessionService):
    """Context-injecting wrapper around ``SqliteSessionService``."""

    def __init__(self, db_path: str) -> None:
        self._inner = SqliteSessionService(db_path)
        self._context_builders: dict[str, ContextBuilder] = {}

    def register_context(self, session_id: str, builder: ContextBuilder) -> None:
        self._context_builders[session_id] = builder

    async def create_session(
        self,
        *,
        app_name: str,
        user_id: str,
        state: dict[str, Any] | None = None,
        session_id: str | None = None,
    ) -> AdkSession:
        # Extract CoworkToolContext before persisting — it's not JSON-safe.
        safe_state = dict(state or {})
        ctx = safe_state.pop(COWORK_CONTEXT_KEY, None)
        if ctx and isinstance(ctx, CoworkToolContext):
            safe_state["_cowork_meta"] = {
                "project_slug": ctx.project.slug,
                "session_id": ctx.session.id,
            }

        adk_session = await self._inner.create_session(
            app_name=app_name,
            user_id=user_id,
            state=safe_state,
            session_id=session_id,
        )

        # Inject the live context into the in-memory session.
        if ctx:
            adk_session.state[COWORK_CONTEXT_KEY] = ctx
        return adk_session

    async def get_session(
        self,
        *,
        app_name: str,
        user_id: str,
        session_id: str,
        config: GetSessionConfig | None = None,
    ) -> AdkSession | None:
        adk_session = await self._inner.get_session(
            app_name=app_name,
            user_id=user_id,
            session_id=session_id,
            config=config,
        )
        if adk_session is None:
            return None

        # Re-inject CoworkToolContext from the registered builder.
        if COWORK_CONTEXT_KEY not in adk_session.state:
            builder = self._context_builders.get(session_id)
            if builder:
                adk_session.state[COWORK_CONTEXT_KEY] = builder()
        return adk_session

    async def list_sessions(
        self,
        *,
        app_name: str,
        user_id: str | None = None,
    ) -> ListSessionsResponse:
        return await self._inner.list_sessions(
            app_name=app_name, user_id=user_id,
        )

    async def delete_session(
        self,
        *,
        app_name: str,
        user_id: str,
        session_id: str,
    ) -> None:
        self._context_builders.pop(session_id, None)
        await self._inner.delete_session(
            app_name=app_name, user_id=user_id, session_id=session_id,
        )

    async def append_event(self, session: AdkSession, event: Any) -> Any:
        return await self._inner.append_event(session, event)
