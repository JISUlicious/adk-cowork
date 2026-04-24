"""FastAPI application factory for ``cowork-server``.

All shared state is behind abstract protocols (EventBus, AuthGuard,
ConnectionLimiter) so backends can be swapped without touching routes.

The OpenAPI schema is published at ``/openapi.json`` and rendered at
``/docs`` (Swagger UI) + ``/redoc``. Routes are tagged into the same
groups used by the UI panes documented in ``ARCHITECTURE.md §2``;
auth uses an ``x-cowork-token`` header advertised as the
``cowork-token`` security scheme so Swagger's Authorize button
unlocks "Try it out".
"""

from __future__ import annotations

import asyncio
import time
from importlib.metadata import PackageNotFoundError, version as _pkg_version
from typing import Any

from cowork_core import CoworkConfig, CoworkRuntime, PreviewCache, build_runtime
from cowork_core.runner import APP_NAME
from fastapi import (
    Depends,
    FastAPI,
    File,
    HTTPException,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from fastapi.security import APIKeyHeader
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions
from google.genai import types as genai_types

from cowork_server.api_models import (
    AutoRouteResponse,
    ClearNotificationsResponse,
    CreateProjectRequest,
    CreateSessionRequest,
    DeleteResponse,
    FileEntry,
    GrantApprovalRequest,
    GrantApprovalResponse,
    HealthResponse,
    LocalFileListResult,
    LocalFileReadResult,
    LocalSessionListItem,
    MarkReadResponse,
    MessageAcceptedResponse,
    NotificationItem,
    NotificationsListResponse,
    PatchLocalSessionRequest,
    PatchSessionRequest,
    PolicyMode,
    PolicyModeResponse,
    ProjectInfo,
    PythonExecPolicy,
    PythonExecResponse,
    ResumeSessionRequest,
    SearchResults,
    SendMessageRequest,
    SessionInfo,
    SessionListItem,
    SetAutoRouteRequest,
    SetPolicyModeRequest,
    SetPythonExecRequest,
    SetToolAllowlistRequest,
    ToolAllowlistResponse,
    UploadFileResult,
)
from cowork_server.auth import UserIdentity, create_guard, generate_token
from cowork_server.connections import InMemoryConnectionLimiter
from cowork_server.queues import InMemoryEventBus
from cowork_server.transport import event_to_payload, events_to_history


def _server_version() -> str:
    """Best-effort server version. Falls back to ``"0.1.0"`` when the
    package metadata isn't installed (editable installs without a build)."""
    try:
        return _pkg_version("cowork-core")
    except PackageNotFoundError:
        return "0.1.0"


_OPENAPI_TAGS: list[dict[str, str]] = [
    {"name": "health", "description": "Service status + active model."},
    {"name": "sessions", "description": "Session lifecycle (create / resume / history / messages / delete)."},
    {"name": "policy", "description": "Per-session policy: mode, python_exec, tool allowlist, @-route."},
    {"name": "approvals", "description": "Tool-call confirmation grants."},
    {"name": "notifications", "description": "Per-user notification inbox."},
    {"name": "search", "description": "Cross-project ⌘K palette search."},
    {"name": "projects", "description": "Managed-mode project CRUD."},
    {"name": "files", "description": "Managed-mode artifact files (list / upload / preview)."},
    {"name": "local-dir", "description": "Desktop-mode workdir browsing + sessions."},
    {"name": "streams", "description": "SSE / WebSocket event streams."},
]


# OpenAPI security scheme advertising the `x-cowork-token` header.
# This dependency exists purely to teach the schema about auth so the
# Swagger UI shows an Authorize button; the actual token check still
# happens through the ``guard`` dependency on each route.
_api_key_scheme = APIKeyHeader(
    name="x-cowork-token",
    scheme_name="cowork-token",
    description=(
        "Bearer-style token. Sidecar mode prints it at startup; "
        "multi-user mode reads it from `[auth].keys` in cowork.toml."
    ),
    auto_error=False,
)


def create_app(cfg: CoworkConfig | None = None, token: str | None = None) -> FastAPI:
    cfg = cfg or CoworkConfig()
    token = token or cfg.auth.token or generate_token()
    guard = create_guard(token, cfg.auth.keys or None)
    runtime: CoworkRuntime = build_runtime(cfg)

    cache_dir = runtime.workspace.root / "global" / ".preview-cache"
    preview_cache = PreviewCache(cache_dir)

    bus = InMemoryEventBus()
    limiter = InMemoryConnectionLimiter()
    # Default policy from config — never mutated at runtime
    default_policy_mode = cfg.policy.mode

    app = FastAPI(
        title="cowork-server",
        description=(
            "HTTP + SSE/WS surface for Cowork — an office-work copilot "
            "built on Google ADK. Routes are grouped by UI pane "
            "(see ARCHITECTURE.md §2) and authenticated via an "
            "`x-cowork-token` header."
        ),
        version=_server_version(),
        openapi_tags=_OPENAPI_TAGS,
        # Advertise the auth scheme on every route. The actual token
        # check stays inside ``guard`` — this dependency just teaches
        # OpenAPI / Swagger about it.
        dependencies=[Depends(_api_key_scheme)],
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^(tauri://.*|https?://(localhost|127\.0\.0\.1)(:\d+)?|https://tauri\.localhost)$",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.token = token
    app.state.runtime = runtime
    app.state.cfg = cfg
    app.state.bus = bus
    app.state.limiter = limiter
    app.state.preview_cache = preview_cache

    # ── Health ─────────────────────────────────────────────────────────

    @app.get(
        "/v1/health",
        tags=["health"],
        summary="Service status + active model",
        response_model=HealthResponse,
    )
    async def health() -> dict[str, Any]:
        """Service + per-component status.

        ``backend`` names the runtime backend in use (today always
        ``local``). ``components`` is a dict of subsystem → status;
        distributed deployments extend this with ``eventbus``,
        ``sessions``, etc. ``auth`` reports whether multi-user keys are
        configured, so clients can distinguish sidecar from hosted.
        """
        return {
            "status": "ok",
            "backend": cfg.runtime.backend,
            "auth": "multi-user" if runtime.multi_user else "sidecar",
            "components": {
                "eventbus": "ok",
                "limiter": "ok",
                "sessions": "ok",
            },
            # Active LLM model identifier (from ``[model] model`` in
            # ``cowork.toml``) so the UI can surface what the agent is
            # running against. Read-only; runtime swaps require a
            # config reload.
            "model": cfg.model.model,
            "tools": runtime.tools.names(),
            "skills": [
                {
                    "name": s.name,
                    "description": s.description,
                    "license": s.license,
                }
                for s in runtime.skills.all_skills()
            ],
            "compaction": {
                "enabled": cfg.compaction.enabled,
                "compaction_interval": cfg.compaction.compaction_interval,
                "overlap_size": cfg.compaction.overlap_size,
                "token_threshold": cfg.compaction.token_threshold,
                "event_retention_size": cfg.compaction.event_retention_size,
            },
        }

    # ── Policy (per-session, falls back to server default) ─────────────

    @app.get(
        "/v1/policy/mode",
        tags=["policy"],
        summary="Server-default policy mode",
        response_model=PolicyModeResponse,
    )
    async def get_policy_mode(user: UserIdentity = Depends(guard)) -> dict[str, str]:
        """Server-wide default used for fresh sessions. Read-only — to
        mutate mode for an active session, use
        ``PUT /v1/sessions/{id}/policy/mode``."""
        return {"mode": default_policy_mode}

    @app.get(
        "/v1/sessions/{session_id}/policy/mode",
        tags=["policy"],
        summary="Get session policy mode",
        response_model=PolicyModeResponse,
    )
    async def get_session_policy_mode(
        session_id: str,
        user: UserIdentity = Depends(guard),
    ) -> dict[str, str]:
        try:
            mode = await runtime.get_session_policy_mode(
                session_id=session_id, user_id=user.user_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"mode": mode}

    @app.put(
        "/v1/sessions/{session_id}/policy/mode",
        tags=["policy"],
        summary="Set session policy mode",
        response_model=PolicyModeResponse,
    )
    async def set_session_policy_mode(
        session_id: str,
        body: SetPolicyModeRequest,
        user: UserIdentity = Depends(guard),
    ) -> dict[str, str]:
        try:
            applied = await runtime.set_session_policy_mode(
                session_id=session_id, mode=body.mode, user_id=user.user_id,
            )
        except ValueError as exc:
            # 400 for unknown mode, 404 for missing session.
            if "unknown policy mode" in str(exc):
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"mode": applied}

    @app.get(
        "/v1/sessions/{session_id}/policy/python_exec",
        tags=["policy"],
        summary="Get python_exec_run policy",
        response_model=PythonExecResponse,
    )
    async def get_session_python_exec_policy(
        session_id: str,
        user: UserIdentity = Depends(guard),
    ) -> dict[str, str]:
        try:
            policy = await runtime.get_session_python_exec(
                session_id=session_id, user_id=user.user_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"policy": policy}

    @app.put(
        "/v1/sessions/{session_id}/policy/python_exec",
        tags=["policy"],
        summary="Set python_exec_run policy",
        response_model=PythonExecResponse,
    )
    async def set_session_python_exec_policy(
        session_id: str,
        body: SetPythonExecRequest,
        user: UserIdentity = Depends(guard),
    ) -> dict[str, str]:
        try:
            applied = await runtime.set_session_python_exec(
                session_id=session_id, policy=body.policy, user_id=user.user_id,
            )
        except ValueError as exc:
            if "unknown python_exec policy" in str(exc):
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"policy": applied}

    @app.get(
        "/v1/sessions/{session_id}/policy/tool_allowlist",
        tags=["policy"],
        summary="Get per-agent tool allowlist",
        response_model=ToolAllowlistResponse,
    )
    async def get_session_tool_allowlist_policy(
        session_id: str,
        user: UserIdentity = Depends(guard),
    ) -> dict[str, Any]:
        """Return the per-agent tool allowlist for the session.

        Tier E.E1. Empty dict = no restrictions (default). See
        ``cowork_core.policy.permissions.make_allowlist_callback`` for
        the enforcement model. The root agent is unrestricted by design.
        """
        try:
            allowlist = await runtime.get_session_tool_allowlist(
                session_id=session_id, user_id=user.user_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"allowlist": allowlist}

    @app.put(
        "/v1/sessions/{session_id}/policy/tool_allowlist",
        tags=["policy"],
        summary="Replace tool allowlist",
        response_model=ToolAllowlistResponse,
    )
    async def set_session_tool_allowlist_policy(
        session_id: str,
        body: SetToolAllowlistRequest,
        user: UserIdentity = Depends(guard),
    ) -> dict[str, Any]:
        """Replace the per-agent tool allowlist for the session.

        Body: ``{"allowlist": {"researcher": ["fs_read", ...], ...}}``.
        Agents absent from the dict run unrestricted; an empty list for
        an agent silences it (every tool call is blocked). Send
        ``{"allowlist": {}}`` to clear all restrictions.
        """
        try:
            applied = await runtime.set_session_tool_allowlist(
                session_id=session_id, allowlist=body.allowlist, user_id=user.user_id,
            )
        except ValueError as exc:
            message = str(exc)
            if message.startswith("no session"):
                raise HTTPException(status_code=404, detail=message) from exc
            raise HTTPException(status_code=400, detail=message) from exc
        return {"allowlist": applied}

    @app.get(
        "/v1/sessions/{session_id}/policy/auto_route",
        tags=["policy"],
        summary="Get @-mention auto-route flag",
        response_model=AutoRouteResponse,
    )
    async def get_session_auto_route_policy(
        session_id: str,
        user: UserIdentity = Depends(guard),
    ) -> dict[str, bool]:
        """Return the session's ``@``-mention auto-route flag
        (default True). Tier E.E2."""
        try:
            enabled = await runtime.get_session_auto_route(
                session_id=session_id, user_id=user.user_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"enabled": enabled}

    @app.put(
        "/v1/sessions/{session_id}/policy/auto_route",
        tags=["policy"],
        summary="Toggle @-mention auto-route",
        response_model=AutoRouteResponse,
    )
    async def set_session_auto_route_policy(
        session_id: str,
        body: SetAutoRouteRequest,
        user: UserIdentity = Depends(guard),
    ) -> dict[str, bool]:
        """Toggle the session's ``@``-mention auto-route flag.

        Body: ``{"enabled": bool}``. When off, the root agent's prompt
        omits the routing directive and a leading ``@name`` is treated
        as plain text.
        """
        try:
            applied = await runtime.set_session_auto_route(
                session_id=session_id, enabled=body.enabled, user_id=user.user_id,
            )
        except ValueError as exc:
            message = str(exc)
            if message.startswith("no session"):
                raise HTTPException(status_code=404, detail=message) from exc
            raise HTTPException(status_code=400, detail=message) from exc
        return {"enabled": applied}

    # ── Per-session tool approvals ─────────────────────────────────────

    @app.get(
        "/v1/sessions/{session_id}/approvals",
        tags=["approvals"],
        summary="List pending tool approvals",
        response_model=dict[str, int],
    )
    async def list_approvals(
        session_id: str,
        user: UserIdentity = Depends(guard),
    ) -> dict[str, int]:
        """Return ``{tool_name: pending_count}`` for this session."""
        try:
            return await runtime.list_tool_approvals(
                session_id=session_id, user_id=user.user_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post(
        "/v1/sessions/{session_id}/approvals",
        tags=["approvals"],
        summary="Grant a tool approval",
        response_model=GrantApprovalResponse,
    )
    async def grant_approval(
        session_id: str,
        body: GrantApprovalRequest,
        user: UserIdentity = Depends(guard),
    ) -> dict[str, Any]:
        """Grant one approval for a tool name.

        Body: ``{"tool": "python_exec_run", "tool_call_id": "fc_xyz"}``.
        The permission callback consumes the approval on the next
        invocation of that tool, so one POST allows exactly one subsequent
        call. When ``tool_call_id`` is supplied we also append an ADK
        approval event to the session so history replay can mark that
        specific call as resolved — the UI then doesn't re-prompt for an
        approval the user already acted on.
        """
        try:
            remaining = await runtime.grant_tool_approval(
                session_id=session_id, tool_name=body.tool, user_id=user.user_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        if body.tool_call_id:
            # Record the approval in a side-channel log (never ADK
            # session state — that would race the runner's OCC-guarded
            # appends and trip ``last_update_time`` errors mid-turn,
            # per ``cowork_core/approvals.py``). The log is
            # wire-compatible with ADK events so transport layers can
            # serve it via ``/history`` and publish it live.
            ev_payload = runtime.approval_log.record(
                session_id=session_id,
                tool_name=body.tool,
                tool_call_id=body.tool_call_id,
            )
            import json as _json

            await bus.publish(session_id, _json.dumps(ev_payload))

        return {"tool": body.tool, "remaining": remaining}

    # ── Notifications ──────────────────────────────────────────────────

    @app.get(
        "/v1/notifications",
        tags=["notifications"],
        summary="List user notifications",
        response_model=NotificationsListResponse,
    )
    async def list_notifications(
        user: UserIdentity = Depends(guard),
    ) -> dict[str, Any]:
        """Most-recent-first notifications for the authenticated user.

        Ephemeral: the store lives in process memory, so a server
        restart wipes unread notifications. Persistence would add
        complexity without a clear win while the runtime is
        single-process — revisit when we scale out.
        """
        notes = runtime.notifications.list(user.user_id)
        return {"notifications": [n.to_wire() for n in notes]}

    @app.post(
        "/v1/notifications/{notification_id}/read",
        tags=["notifications"],
        summary="Mark notification read",
        response_model=MarkReadResponse,
    )
    async def mark_notification_read(
        notification_id: str,
        user: UserIdentity = Depends(guard),
    ) -> dict[str, Any]:
        ok = runtime.notifications.mark_read(user.user_id, notification_id)
        if not ok:
            raise HTTPException(status_code=404, detail="notification not found")
        return {"id": notification_id, "read": True}

    @app.delete(
        "/v1/notifications",
        tags=["notifications"],
        summary="Clear all notifications",
        response_model=ClearNotificationsResponse,
    )
    async def clear_notifications(
        user: UserIdentity = Depends(guard),
    ) -> dict[str, int]:
        removed = runtime.notifications.clear(user.user_id)
        return {"cleared": removed}

    # ── Global search (⌘K palette — F.P6b) ────────────────────────────

    @app.get(
        "/v1/search",
        tags=["search"],
        summary="Cross-project palette search",
        response_model=SearchResults,
    )
    async def search(
        q: str,
        user: UserIdentity = Depends(guard),
    ) -> dict[str, Any]:
        """Naive cross-project substring search for the ⌘K palette.

        Three sections — ``sessions`` (by title), ``files`` (by path,
        scoped to each project's ``files/`` artifact dir), and
        ``messages`` (by event text). Each section is capped at 50 so a
        runaway query can't lock the server; message scanning is
        additionally limited to the 15 most-recent sessions per project
        because it's the only section that pulls full event lists.

        Results are cached per ``(user_id, q.lower())`` for 30 seconds
        so repeated keystrokes (debounced from the client) share work.
        """
        q_lower = q.strip().lower()
        if not q_lower:
            return {"sessions": [], "files": [], "messages": []}

        key = (user.user_id, q_lower)
        now = time.time()
        cached = _search_cache.get(key)
        if cached is not None and now - cached[0] < _SEARCH_CACHE_TTL:
            return cached[1]

        result = await _run_search(runtime, user.user_id, q_lower)
        _search_cache[key] = (now, result)
        # Simple bounded cache — a manual reset is cheaper than LRU
        # bookkeeping for what's expected to be a handful of active
        # queries at a time.
        if len(_search_cache) > _SEARCH_CACHE_SIZE:
            _search_cache.clear()
        return result

    # ── Sessions ───────────────────────────────────────────────────────

    @app.post(
        "/v1/sessions",
        tags=["sessions"],
        summary="Create session",
        response_model=SessionInfo,
    )
    async def create_session(
        body: CreateSessionRequest | None = None,
        user: UserIdentity = Depends(guard),
    ) -> dict[str, str]:
        """Create a new session.

        Body:
            {"project": "<slug or name>"}   — managed mode (web surface), or
            {"workdir": "/abs/path"}        — local-dir mode (desktop surface)

        Supplying ``workdir`` is the **surface selector**: present = desktop,
        absent = web. Providing both is rejected.
        """
        project_name = body.project if body else None
        workdir = body.workdir if body else None
        if project_name and workdir:
            raise HTTPException(
                status_code=400,
                detail="supply either 'project' or 'workdir', not both",
            )
        try:
            project, session, adk_sid = await runtime.open_session(
                user_id=user.user_id,
                project_name=project_name,
                workdir=workdir,
            )
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "session_id": adk_sid,
            "project": project.slug,
            "cowork_session_id": session.id,
            "workdir": str(workdir) if workdir else "",
        }

    @app.post(
        "/v1/sessions/{session_id}/resume",
        tags=["sessions"],
        summary="Resume existing session",
        response_model=SessionInfo,
    )
    async def resume_session(
        session_id: str,
        body: ResumeSessionRequest,
        user: UserIdentity = Depends(guard),
    ) -> dict[str, str]:
        project_slug = body.project or None
        workdir = body.workdir or None
        if not project_slug and not workdir:
            raise HTTPException(
                status_code=400, detail="project or workdir is required",
            )
        if project_slug and workdir:
            raise HTTPException(
                status_code=400,
                detail="supply either 'project' or 'workdir', not both",
            )
        try:
            project, session, adk_sid = await runtime.resume_session(
                session_id=session_id,
                project_slug=project_slug,
                workdir=workdir,
                user_id=user.user_id,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "session_id": adk_sid,
            "project": project.slug,
            "cowork_session_id": session.id,
            "workdir": str(workdir) if workdir else "",
        }

    @app.get(
        "/v1/sessions/{session_id}/history",
        tags=["sessions"],
        summary="Get session event history",
    )
    async def session_history(
        session_id: str,
        user: UserIdentity = Depends(guard),
    ) -> list[dict[str, Any]]:
        svc = runtime.runner.session_service
        existing = await svc.get_session(
            app_name=getattr(runtime.runner, "app_name", "cowork"),
            user_id=user.user_id,
            session_id=session_id,
        )
        if existing is None:
            raise HTTPException(status_code=404, detail="session not found")
        return events_to_history(getattr(existing, "events", []) or [])

    # ── Local-dir file browser (desktop surface) ───────────────────────

    @app.get(
        "/v1/local-files",
        tags=["local-dir"],
        summary="List workdir files",
        response_model=LocalFileListResult,
    )
    async def list_local_files(
        workdir: str,
        path: str = "",
        user: UserIdentity = Depends(guard),
    ) -> dict[str, Any]:
        """List entries of ``<workdir>/<path>``. Path confined via
        ``LocalDirExecEnv``. Hides the ``.cowork/`` bookkeeping subtree."""
        from pathlib import Path as _P

        from cowork_core.execenv import ExecEnvError, LocalDirExecEnv

        try:
            env = LocalDirExecEnv(workdir=_P(workdir), session_id="browse")
        except ExecEnvError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            abspath = env.resolve(path or ".")
        except ExecEnvError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not abspath.is_dir():
            raise HTTPException(status_code=404, detail=f"not a directory: {path}")
        entries: list[dict[str, Any]] = []
        for child in sorted(abspath.iterdir()):
            if child.name == ".cowork":
                continue  # bookkeeping, not user content
            # Hide OS / editor noise the user wouldn't create on purpose
            # (``.DS_Store`` on macOS, ``Thumbs.db`` on Windows, etc.).
            # Dotfiles in general stay hidden by default — the agent can
            # still reach them via fs tools if needed.
            if child.name.startswith("."):
                continue
            if child.name in {"Thumbs.db", "desktop.ini"}:
                continue
            try:
                stat = child.stat()
                mtime: float | None = stat.st_mtime
                size: int | None = stat.st_size if child.is_file() else None
            except OSError:
                mtime = None
                size = None
            entries.append({
                "name": child.name,
                "kind": "dir" if child.is_dir() else "file",
                "size": size,
                "modified": mtime,
            })
        return {"path": path or ".", "entries": entries}

    @app.get(
        "/v1/local-files/content",
        tags=["local-dir"],
        summary="Read workdir file content",
        response_model=LocalFileReadResult,
    )
    async def read_local_file(
        workdir: str,
        path: str,
        user: UserIdentity = Depends(guard),
    ) -> dict[str, Any]:
        """Read up to 2 MB of ``<workdir>/<path>`` as UTF-8 text."""
        from pathlib import Path as _P

        from cowork_core.execenv import ExecEnvError, LocalDirExecEnv

        try:
            env = LocalDirExecEnv(workdir=_P(workdir), session_id="browse")
            abspath = env.resolve(path)
        except ExecEnvError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not abspath.is_file():
            raise HTTPException(status_code=404, detail=f"not a file: {path}")
        max_bytes = 2_000_000
        data = abspath.read_bytes()
        truncated = len(data) > max_bytes
        if truncated:
            data = data[:max_bytes]
        return {
            "path": path,
            "content": data.decode("utf-8", errors="replace"),
            "truncated": truncated,
            "size": abspath.stat().st_size,
        }

    # ── Local-dir sessions (desktop surface) ───────────────────────────

    @app.get(
        "/v1/local-sessions",
        tags=["local-dir"],
        summary="List workdir sessions",
        response_model=list[LocalSessionListItem],
    )
    async def list_local_sessions_endpoint(
        workdir: str,
        user: UserIdentity = Depends(guard),
    ) -> list[dict[str, Any]]:
        """List sessions recorded under ``<workdir>/.cowork/sessions/``."""
        from pathlib import Path as _P

        sessions = runtime.list_local_sessions(_P(workdir))
        return [
            {
                "id": s.id,
                "created_at": s.created_at,
                "title": s.title,
                "pinned": s.pinned,
            }
            for s in sessions
        ]

    @app.patch(
        "/v1/local-sessions/{session_id}",
        tags=["local-dir"],
        summary="Update local session metadata",
        response_model=LocalSessionListItem,
    )
    async def patch_local_session(
        session_id: str,
        workdir: str,
        body: PatchLocalSessionRequest,
        user: UserIdentity = Depends(guard),
    ) -> dict[str, Any]:
        """Mutate a local-dir session's metadata. Mirrors managed
        ``PATCH /v1/projects/{slug}/sessions/{id}`` — today only
        ``pinned`` is supported. Path-confinement is handled inside
        the runtime helper (it resolves under ``<workdir>/.cowork``)."""

        from pathlib import Path as _P

        if body.pinned is None:
            raise HTTPException(status_code=400, detail="'pinned' is required")
        try:
            session = runtime.set_local_session_pinned(
                _P(workdir), session_id, body.pinned,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {
            "id": session.id,
            "title": session.title,
            "created_at": session.created_at,
            "pinned": session.pinned,
        }

    @app.delete(
        "/v1/local-sessions/{session_id}",
        tags=["local-dir"],
        summary="Delete local session",
        response_model=DeleteResponse,
    )
    async def delete_local_session_endpoint(
        session_id: str,
        workdir: str,
        user: UserIdentity = Depends(guard),
    ) -> dict[str, str]:
        from pathlib import Path as _P

        await runtime.delete_local_session(
            workdir=_P(workdir),
            session_id=session_id,
            user_id=user.user_id,
        )
        return {"status": "ok"}

    @app.post(
        "/v1/sessions/{session_id}/messages",
        tags=["sessions"],
        summary="Send user message (fire-and-forget)",
        response_model=MessageAcceptedResponse,
    )
    async def send_message(
        session_id: str,
        body: SendMessageRequest,
        user: UserIdentity = Depends(guard),
    ) -> dict[str, str]:
        task = asyncio.create_task(
            _run_turn(runtime, bus, session_id, body.text, user.user_id)
        )
        # Fire-and-forget — errors are published as events
        task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
        return {"status": "accepted"}

    # ── Event Streaming ────────────────────────────────────────────────

    @app.get(
        "/v1/sessions/{session_id}/events/stream",
        tags=["streams"],
        summary="SSE event stream (ADK Event JSON per frame)",
    )
    async def events_sse(
        session_id: str,
        user: UserIdentity = Depends(guard),
    ) -> StreamingResponse:
        await limiter.acquire(user.user_id)

        async def gen() -> Any:
            import json as _json
            try:
                async with bus.subscribe(session_id) as queue:
                    while True:
                        try:
                            payload = await asyncio.wait_for(queue.get(), timeout=15.0)
                        except TimeoutError:
                            yield ": keep-alive\n\n"
                            continue
                        yield f"data: {payload}\n\n"
                        try:
                            done = _json.loads(payload).get("turnComplete") is True
                        except (ValueError, AttributeError):
                            done = False
                        if done:
                            return
            finally:
                await limiter.release(user.user_id)

        return StreamingResponse(
            gen(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    @app.websocket("/v1/sessions/{session_id}/events")
    async def events_ws(ws: WebSocket, session_id: str) -> None:
        # WebSocket auth: validate from header or query param
        provided = ws.headers.get("x-cowork-token") or ws.query_params.get("token")
        if not provided:
            await ws.close(code=4401)
            return
        # Validate against guard — for sidecar, check the token directly
        try:
            user = guard(x_cowork_token=provided)
        except HTTPException:
            await ws.close(code=4401)
            return

        await limiter.acquire(user.user_id)
        await ws.accept()
        try:
            async with bus.subscribe(session_id) as queue:
                while True:
                    frame = await queue.get()
                    await ws.send_text(frame)
        except WebSocketDisconnect:
            pass
        finally:
            await limiter.release(user.user_id)

    # ── Projects ───────────────────────────────────────────────────────

    @app.get(
        "/v1/projects",
        tags=["projects"],
        summary="List user projects",
        response_model=list[ProjectInfo],
    )
    async def list_projects(user: UserIdentity = Depends(guard)) -> list[dict[str, str]]:
        projects = runtime.registry_for(user.user_id).list()
        return [
            {"slug": p.slug, "name": p.name, "created_at": p.created_at}
            for p in projects
        ]

    @app.post(
        "/v1/projects",
        tags=["projects"],
        summary="Create project",
        response_model=ProjectInfo,
    )
    async def create_project(
        body: CreateProjectRequest,
        user: UserIdentity = Depends(guard),
    ) -> dict[str, str]:
        try:
            project = runtime.registry_for(user.user_id).create(body.name)
        except Exception as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"slug": project.slug, "name": project.name, "created_at": project.created_at}

    @app.get(
        "/v1/projects/{project}/sessions",
        tags=["projects"],
        summary="List project sessions",
        response_model=list[SessionListItem],
    )
    async def list_sessions(
        project: str,
        user: UserIdentity = Depends(guard),
    ) -> list[dict[str, Any]]:
        try:
            proj = runtime.registry_for(user.user_id).get(project)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        sessions_dir = proj.sessions_dir
        result: list[dict[str, Any]] = []
        if sessions_dir.is_dir():
            import tomllib
            for entry in sorted(sessions_dir.iterdir()):
                toml_path = entry / "session.toml"
                if not toml_path.exists():
                    continue
                with toml_path.open("rb") as f:
                    data = tomllib.load(f)
                result.append({
                    "id": data.get("id", entry.name),
                    "title": data.get("title") or None,
                    "created_at": data.get("created_at", ""),
                    "pinned": bool(data.get("pinned", False)),
                })
        return result

    @app.patch(
        "/v1/projects/{project}/sessions/{session_id}",
        tags=["projects"],
        summary="Update project-session metadata",
        response_model=SessionListItem,
    )
    async def patch_session(
        project: str,
        session_id: str,
        body: PatchSessionRequest,
        user: UserIdentity = Depends(guard),
    ) -> dict[str, Any]:
        """Mutate a session's ``session.toml`` metadata.

        Only ``pinned`` is supported today; ``title`` is accepted for
        future use and currently ignored. Full-rewrite under a
        process-local lock in ``ProjectRegistry.set_session_pinned`` so
        concurrent PATCHes don't race.
        """

        if body.pinned is None:
            raise HTTPException(status_code=400, detail="'pinned' is required")
        try:
            session = runtime.registry_for(user.user_id).set_session_pinned(
                project, session_id, body.pinned,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {
            "id": session.id,
            "title": session.title,
            "created_at": session.created_at,
            "pinned": session.pinned,
        }

    @app.delete(
        "/v1/projects/{project}",
        tags=["projects"],
        summary="Delete project",
        response_model=DeleteResponse,
    )
    async def delete_project(
        project: str,
        user: UserIdentity = Depends(guard),
    ) -> dict[str, str]:
        try:
            runtime.registry_for(user.user_id).delete_project(project)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"status": "deleted"}

    @app.delete(
        "/v1/projects/{project}/sessions/{session_id}",
        tags=["projects"],
        summary="Delete project session",
        response_model=DeleteResponse,
    )
    async def delete_session(
        project: str,
        session_id: str,
        user: UserIdentity = Depends(guard),
    ) -> dict[str, str]:
        try:
            runtime.registry_for(user.user_id).delete_session(project, session_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"status": "deleted"}

    # ── Files ──────────────────────────────────────────────────────────

    @app.get(
        "/v1/projects/{project}/files/{path:path}",
        tags=["files"],
        summary="List project files",
        response_model=list[FileEntry],
    )
    async def list_files(
        project: str,
        path: str,
        user: UserIdentity = Depends(guard),
    ) -> list[dict[str, Any]]:
        try:
            full_path = runtime.workspace_for(user.user_id).resolve(f"projects/{project}/{path}")
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not full_path.is_dir():
            raise HTTPException(status_code=404, detail=f"not a directory: {path}")
        entries: list[dict[str, Any]] = []
        for child in sorted(full_path.iterdir()):
            stat = child.stat()
            entries.append({
                "name": child.name,
                "kind": "dir" if child.is_dir() else "file",
                "size": stat.st_size if child.is_file() else None,
                "modified": stat.st_mtime,
            })
        return entries

    @app.post(
        "/v1/projects/{project}/upload",
        tags=["files"],
        summary="Upload file to project",
        response_model=UploadFileResult,
    )
    async def upload_file(
        project: str,
        user: UserIdentity = Depends(guard),
        file: UploadFile = File(...),  # noqa: B008
        prefix: str = "files",
    ) -> dict[str, Any]:
        if prefix not in ("files", "scratch"):
            raise HTTPException(status_code=400, detail="prefix must be 'files' or 'scratch'")
        basename = (file.filename or "upload.bin").split("/")[-1].split("\\")[-1]
        try:
            dest = runtime.workspace_for(user.user_id).resolve(f"projects/{project}/{prefix}/{basename}")
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        dest.parent.mkdir(parents=True, exist_ok=True)
        size = 0
        with dest.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                out.write(chunk)
                size += len(chunk)
        return {"name": basename, "path": f"{prefix}/{basename}", "size": size}

    @app.get(
        "/v1/projects/{project}/preview/{path:path}",
        tags=["files"],
        summary="Render file preview",
    )
    async def preview_file(
        project: str,
        path: str,
        raw: int = 0,
        user: UserIdentity = Depends(guard),
    ) -> Response:
        try:
            full_path = runtime.workspace_for(user.user_id).resolve(f"projects/{project}/{path}")
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not full_path.is_file():
            raise HTTPException(status_code=404, detail=f"file not found: {path}")
        # Raw mode: bypass the converter pipeline and return the original
        # bytes. Used by the UI's "view code" toggle for files that would
        # otherwise render (e.g. markdown → HTML). Capped at 2 MB so a
        # casual click never blows up the tab on a giant file.
        if raw:
            try:
                size = full_path.stat().st_size
            except OSError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            if size > 2 * 1024 * 1024:
                raise HTTPException(status_code=413, detail="file too large for raw view")
            data = full_path.read_bytes()
            return Response(content=data, media_type="text/plain; charset=utf-8")
        try:
            result = preview_cache.get(full_path)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return Response(
            content=result.body,
            media_type=result.content_type,
            headers={"X-Content-Hash": result.content_hash},
        )

    return app


_SERVER_AUTHOR = "cowork-server"


async def _flush_pending_approvals(
    runtime: CoworkRuntime,
    session_id: str,
    user_id: str,
    bus: InMemoryEventBus,
) -> None:
    """Promote queued approval events into the session's event list.

    Called at the start of ``_run_turn`` — the only place we can
    ``append_event`` to the session without racing the runner. Each
    queued entry becomes a real ADK ``Event``, so history fetches and
    later replays see approvals inline with model/tool events rather
    than as a side channel.
    """

    pending = runtime.approval_log.drain(session_id)
    if not pending:
        return
    session = await runtime.runner.session_service.get_session(
        app_name=APP_NAME, user_id=user_id, session_id=session_id,
    )
    if session is None:
        return
    for entry in pending:
        state_delta = (entry.get("actions") or {}).get("stateDelta") or {}
        ev = Event(
            id=str(entry.get("id") or ""),
            author=_SERVER_AUTHOR,
            invocation_id="",
            actions=EventActions(state_delta=dict(state_delta)),
        )
        try:
            await runtime.runner.session_service.append_event(
                session=session, event=ev,
            )
        except Exception as exc:
            import sys

            print(
                f"[cowork-server] approval persist failed ({session_id}): {exc!r}",
                file=sys.stderr,
                flush=True,
            )
            continue


# Search cache — keyed by ``(user_id, query_lower)``. 30 s TTL is long
# enough to absorb a debounced typing burst, short enough that a newly
# created session / renamed file shows up promptly on the next open.
_SEARCH_CACHE_TTL = 30.0
_SEARCH_CACHE_SIZE = 128
# Cap per section so a runaway query doesn't hand back a megabyte of
# JSON or keep the server busy scanning forever. Message scan is extra-
# limited because it's the only section that pulls full event lists.
_SEARCH_MAX_RESULTS = 50
_SEARCH_MESSAGE_SESSION_LIMIT = 15
_search_cache: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}


def _snippet(text: str, needle: str, radius: int = 48) -> str:
    """Return a short preview of ``text`` centered on the first
    case-insensitive occurrence of ``needle``. Whitespace is normalized
    so multi-line tool output doesn't bloat the preview."""

    lower = text.lower()
    idx = lower.find(needle)
    if idx < 0:
        return text[:100]
    start = max(0, idx - radius)
    end = min(len(text), idx + len(needle) + radius)
    prefix = "… " if start > 0 else ""
    suffix = " …" if end < len(text) else ""
    core = text[start:end].replace("\r", " ").replace("\n", " ")
    return f"{prefix}{' '.join(core.split())}{suffix}"


async def _run_search(
    runtime: CoworkRuntime,
    user_id: str,
    q_lower: str,
) -> dict[str, Any]:
    """Scan the user's projects for sessions / files / messages matching
    ``q_lower``. Purely naive iteration — acceptable while the server is
    single-process; a proper index is future work."""

    import tomllib

    session_hits: list[dict[str, Any]] = []
    file_hits: list[dict[str, Any]] = []
    message_hits: list[dict[str, Any]] = []

    registry = runtime.registry_for(user_id)
    projects = registry.list()

    for project in projects:
        if (
            len(session_hits) >= _SEARCH_MAX_RESULTS
            and len(file_hits) >= _SEARCH_MAX_RESULTS
            and len(message_hits) >= _SEARCH_MAX_RESULTS
        ):
            break

        sessions_dir = project.sessions_dir
        session_metas: list[dict[str, Any]] = []
        if sessions_dir.is_dir():
            for entry in sorted(sessions_dir.iterdir()):
                toml_path = entry / "session.toml"
                if not toml_path.exists():
                    continue
                try:
                    with toml_path.open("rb") as f:
                        data = tomllib.load(f)
                except Exception:
                    continue
                session_metas.append({
                    "id": data.get("id", entry.name),
                    "title": data.get("title") or "",
                    "created_at": data.get("created_at", ""),
                })

        # Session-title matches are cheap — scan every session.
        for meta in session_metas:
            if len(session_hits) >= _SEARCH_MAX_RESULTS:
                break
            title = str(meta.get("title") or "")
            if q_lower in title.lower():
                session_hits.append({
                    "session_id": meta["id"],
                    "title": title or None,
                    "project": project.slug,
                })

        # File-name matches scoped to the artifact dir only. ``scratch/``
        # and ``sessions/`` are runtime bookkeeping; surfacing them in
        # global search would add noise without user value.
        files_dir = project.root / "files"
        if files_dir.is_dir():
            for child in files_dir.rglob("*"):
                if len(file_hits) >= _SEARCH_MAX_RESULTS:
                    break
                if not child.is_file():
                    continue
                rel = child.relative_to(project.root).as_posix()
                if q_lower in rel.lower():
                    file_hits.append({
                        "project": project.slug,
                        "path": rel,
                        "name": child.name,
                    })

        # Message scan — bounded hard because this is the expensive
        # section. Cap per-project sessions scanned so a project with
        # 500 sessions doesn't starve other projects.
        session_metas.sort(key=lambda m: str(m.get("created_at", "")), reverse=True)
        for meta in session_metas[:_SEARCH_MESSAGE_SESSION_LIMIT]:
            if len(message_hits) >= _SEARCH_MAX_RESULTS:
                break
            sid = str(meta["id"])
            try:
                existing = await runtime.runner.session_service.get_session(
                    app_name=APP_NAME, user_id=user_id, session_id=sid,
                )
            except Exception:
                continue
            if existing is None:
                continue
            events = getattr(existing, "events", []) or []
            for index, ev in enumerate(events):
                if len(message_hits) >= _SEARCH_MAX_RESULTS:
                    break
                content = getattr(ev, "content", None)
                if content is None:
                    continue
                parts = getattr(content, "parts", None) or []
                blob_parts: list[str] = []
                for p in parts:
                    txt = getattr(p, "text", None)
                    if isinstance(txt, str) and txt:
                        blob_parts.append(txt)
                if not blob_parts:
                    continue
                blob = "\n".join(blob_parts)
                if q_lower in blob.lower():
                    message_hits.append({
                        "session_id": sid,
                        "session_title": str(meta.get("title") or "") or None,
                        "project": project.slug,
                        "index": index,
                        "preview": _snippet(blob, q_lower),
                    })

    return {
        "sessions": session_hits,
        "files": file_hits,
        "messages": message_hits,
    }


def _notify_from_event(
    runtime: CoworkRuntime,
    event: Event,
    session_id: str,
    user_id: str,
) -> None:
    """Inspect one ADK event and push any user-visible notifications.

    Three triggers:

    * ``confirmation_required`` on a tool response — a gated tool is
      waiting for an explicit Approve click.
    * ``error_code`` on the event — ADK or the runner reported a turn
      failure.
    * ``turn_complete`` without an error — the session has nothing left
      running, worth announcing when the user is looking elsewhere.

    Writes only to ``runtime.notifications`` and never to the ADK
    session; same rationale as approvals (see ``notifications.py``).
    """

    content = getattr(event, "content", None)
    if content is not None:
        for part in getattr(content, "parts", None) or []:
            fr = getattr(part, "function_response", None)
            if not fr:
                continue
            resp = getattr(fr, "response", None)
            if isinstance(resp, dict) and resp.get("confirmation_required"):
                tool = getattr(fr, "name", None) or "tool"
                runtime.notifications.add(
                    user_id,
                    "approval_needed",
                    f"{tool} needs approval",
                    session_id=session_id,
                )

    error_code = getattr(event, "error_code", None)
    if error_code:
        msg = getattr(event, "error_message", "") or "turn failed"
        runtime.notifications.add(
            user_id,
            "error",
            f"{error_code}: {msg}",
            session_id=session_id,
        )
        return

    if getattr(event, "turn_complete", False):
        runtime.notifications.add(
            user_id,
            "turn_complete",
            "Turn complete",
            session_id=session_id,
        )


async def _run_turn(
    runtime: CoworkRuntime,
    bus: InMemoryEventBus,
    session_id: str,
    text: str,
    user_id: str = "local",
) -> None:
    """Drive one ADK run and publish each Event (JSON) to the bus.

    Before the runner starts, any approvals the user queued via the
    ``/approvals`` endpoint are promoted from the side-channel log
    into the session's real event list via ``append_event``. This is
    the only place we can safely write approval events — the runner
    isn't active yet, so there's no OCC race with its internal
    appends.
    """

    import sys

    runner = runtime.runner
    await _flush_pending_approvals(runtime, session_id, user_id, bus)

    content = genai_types.Content(role="user", parts=[genai_types.Part(text=text)])
    event_count = 0
    last_event: Event | None = None
    try:
        async for event in runner.run_async(
            user_id=user_id, session_id=session_id, new_message=content
        ):
            event_count += 1
            last_event = event
            _notify_from_event(runtime, event, session_id, user_id)
            await bus.publish(session_id, event_to_payload(event))
    except Exception as e:
        print(f"[cowork-server] run_turn error: {e!r}", file=sys.stderr, flush=True)
        err = Event(
            author=_SERVER_AUTHOR,
            invocation_id=getattr(last_event, "invocation_id", "") or "",
            error_code="INTERNAL",
            error_message=str(e),
            turn_complete=True,
        )
        _notify_from_event(runtime, err, session_id, user_id)
        await bus.publish(session_id, event_to_payload(err))
        return
    finally:
        print(f"[cowork-server] run_turn done, {event_count} events", file=sys.stderr, flush=True)

    if last_event is None or not getattr(last_event, "turn_complete", False):
        sentinel = Event(
            author=_SERVER_AUTHOR,
            invocation_id=getattr(last_event, "invocation_id", "") or "",
            turn_complete=True,
        )
        # Synthesized sentinel: fire the turn_complete notification here
        # since the real last event didn't carry the flag.
        _notify_from_event(runtime, sentinel, session_id, user_id)
        await bus.publish(session_id, event_to_payload(sentinel))
