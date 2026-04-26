"""FastAPI application factory for ``cowork-server`` (the shared base).

All shared state is behind abstract protocols (EventBus, AuthGuard,
ConnectionLimiter) so backends can be swapped without touching routes.

The OpenAPI schema is published at ``/openapi.json`` and rendered at
``/docs`` (Swagger UI) + ``/redoc``. Routes are tagged into the same
groups used by the UI panes documented in ``ARCHITECTURE.md §2``;
auth uses an ``x-cowork-token`` header advertised as the
``cowork-token`` security scheme so Swagger's Authorize button
unlocks "Try it out".

**Slice U0 — server split.** ``create_app`` accepts a ``mode``
parameter discriminating which route sets to register:

* ``"all"`` (default, back-compat) — every route, regardless of
  deployment shape. Keeps existing tests + CLI sidecar contract
  untouched.
* ``"app"`` — single-user backend (cowork-server-app). Common
  routes + local-dir browsing + SU config edits. No managed-project
  or managed-files routes.
* ``"web"`` — multi-user backend (cowork-server-web). Common routes
  + managed projects + managed files + MU config (operator-gated;
  filled in by U1). No local-dir browsing.

The two new backends — ``cowork_server_app`` and
``cowork_server_web`` — wrap this factory with the appropriate
mode, hiding the discrimination from their public ``create_app``.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from importlib.metadata import PackageNotFoundError, version as _pkg_version
from typing import Any, Literal

from cowork_core import CoworkConfig, CoworkRuntime, PreviewCache, build_runtime
from cowork_core.config import McpServerConfig
from cowork_core.runner import APP_NAME, MCPInstallError, SkillInstallError
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
    AddMcpServerRequest,
    AddMcpServerResponse,
    AutoRouteResponse,
    ClearNotificationsResponse,
    CreateProjectRequest,
    CreateSessionRequest,
    DeleteMcpServerResult,
    DeleteResponse,
    DeleteSkillResult,
    FileEntry,
    GrantApprovalRequest,
    GrantApprovalResponse,
    HealthResponse,
    InstallSkillResult,
    McpServerInfo,
    McpServerRecord,
    McpServersListResponse,
    RestartMcpResult,
    ValidateSkillResult,
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
    AuditEntry as ApiAuditEntry,
    AuditQueryResponse,
    ConfigCompactionPatch,
    ConfigCompactionView,
    ConfigModelPatch,
    ConfigModelView,
    EffectiveConfig,
    McpDisabledResponse,
    MemoryPageContent,
    MemoryPageList,
    SetAutoRouteRequest,
    SetMcpDisabledRequest,
    SetPolicyModeRequest,
    SetPythonExecRequest,
    SetSkillsEnabledRequest,
    SetToolAllowlistRequest,
    SkillsEnabledResponse,
    UserProfile,
    UserProfilePatch,
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
    {"name": "skills", "description": "User-installable skill bundles (zip install / uninstall)."},
    {"name": "mcp", "description": "Model Context Protocol server management (add / remove / restart)."},
    {"name": "config", "description": "Workspace-wide config edits — model + compaction (single-user only)."},
    {"name": "profile", "description": "Per-user profile (display name + email)."},
    {"name": "memory", "description": "Per-scope memory page management (list / read / delete)."},
    {"name": "audit", "description": "Audit log — every tool call + settings change (operator-only in MU)."},
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


CreateAppMode = Literal["all", "app", "web"]


def create_app(
    cfg: CoworkConfig | None = None,
    token: str | None = None,
    config_path: Path | None = None,
    mode: CreateAppMode = "all",
) -> FastAPI:
    """Build the FastAPI app.

    ``mode`` controls which route sets are registered:

    * ``"all"`` (default) — every route, back-compat with pre-U0
      tests + sidecar contract.
    * ``"app"`` — common routes + local-dir browsing + SU config
      edits. No managed projects/files. Used by cowork-server-app.
    * ``"web"`` — common routes + managed projects + managed files +
      MU config edits. No local-dir browsing. Used by
      cowork-server-web; refuses to start with empty
      ``cfg.auth.keys``.
    """
    cfg = cfg or CoworkConfig()
    token = token or cfg.auth.token or generate_token()
    if mode == "web" and not cfg.auth.keys:
        raise ValueError(
            "mode='web' requires non-empty cfg.auth.keys; "
            "the multi-user backend won't start without API keys "
            "configured. Set [auth].keys in cowork.toml.",
        )
    guard = create_guard(token, cfg.auth.keys or None)
    runtime: CoworkRuntime = build_runtime(cfg, config_path=config_path)
    # U1 — pick up the boot-merged config so route handlers see the
    # effective values (TOML defaults overlaid by DB overrides in MU).
    # ``runtime.cfg`` is the canonical merged source going forward.
    cfg = runtime.cfg

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
    async def health(
        user: UserIdentity = Depends(guard),
    ) -> dict[str, Any]:
        """Service + per-component status.

        ``backend`` names the runtime backend in use (today always
        ``local``). ``components`` is a dict of subsystem → status;
        distributed deployments extend this with ``eventbus``,
        ``sessions``, etc. ``auth`` reports whether multi-user keys are
        configured, so clients can distinguish sidecar from hosted.

        ``is_operator`` (Slice U1) is computed per-request — it
        reports whether THIS caller can edit workspace-wide
        settings (model + compaction). The UI uses this to gate
        editor affordances.
        """
        from cowork_server.auth import is_operator

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
                    "source": s.source,
                    "version": s.version,
                    "triggers": list(s.triggers),
                    "content_hash": s.content_hash,
                }
                for s in runtime.skills.all_skills()
            ],
            "mcp": [
                {
                    "name": st.name,
                    "status": st.status,
                    "last_error": st.last_error,
                    "tool_count": st.tool_count,
                    "transport": st.transport,
                }
                for st in runtime.mcp_status.values()
            ],
            "compaction": {
                "enabled": cfg.compaction.enabled,
                "compaction_interval": cfg.compaction.compaction_interval,
                "overlap_size": cfg.compaction.overlap_size,
                "token_threshold": cfg.compaction.token_threshold,
                "event_retention_size": cfg.compaction.event_retention_size,
            },
            # Slice T1 — surface state the Settings UI uses to decide
            # whether to render workspace-wide config blocks editable
            # or read-only. ``is_multi_user`` is the auth-level gate;
            # ``has_config_file`` distinguishes "TOML on disk" mode
            # from "env-only" mode (server started without
            # ``COWORK_CONFIG_PATH``).
            "is_multi_user": bool(runtime.multi_user),
            "has_config_file": runtime.config_path is not None,
            # Slice U1 — operator gate state. ``is_operator`` is the
            # per-request check (caller's label vs configured operator);
            # ``operator_configured`` is the global flag used by the UI
            # to branch the read-only notice text between
            # "no operator configured" and "operator is someone else".
            "is_operator": is_operator(cfg, user),
            "operator_configured": bool(cfg.auth.operator),
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

    @app.get(
        "/v1/sessions/{session_id}/policy/skills_enabled",
        tags=["policy"],
        summary="Get the per-session skill enable map",
        response_model=SkillsEnabledResponse,
    )
    async def get_session_skills_enabled_policy(
        session_id: str,
        user: UserIdentity = Depends(guard),
    ) -> dict[str, dict[str, bool]]:
        """Slice II — return the session's skill enable overrides.
        Skills absent from the dict default to enabled, so the empty
        map is the unrestricted default."""
        try:
            enabled = await runtime.get_session_skills_enabled(
                session_id=session_id, user_id=user.user_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"enabled": enabled}

    @app.put(
        "/v1/sessions/{session_id}/policy/skills_enabled",
        tags=["policy"],
        summary="Set the per-session skill enable map",
        response_model=SkillsEnabledResponse,
    )
    async def set_session_skills_enabled_policy(
        session_id: str,
        body: SetSkillsEnabledRequest,
        user: UserIdentity = Depends(guard),
    ) -> dict[str, dict[str, bool]]:
        """Replace the session's skill enable overrides. The root
        prompt's skill registry omits disabled skills on the next
        turn; ``load_skill`` refuses them with an explanatory
        error."""
        try:
            applied = await runtime.set_session_skills_enabled(
                session_id=session_id, enabled=body.enabled, user_id=user.user_id,
            )
        except ValueError as exc:
            message = str(exc)
            if message.startswith("no session"):
                raise HTTPException(status_code=404, detail=message) from exc
            raise HTTPException(status_code=400, detail=message) from exc
        return {"enabled": applied}

    @app.get(
        "/v1/sessions/{session_id}/policy/mcp_disabled",
        tags=["policy"],
        summary="Get the per-session disabled-MCP-server list",
        response_model=McpDisabledResponse,
    )
    async def get_session_mcp_disabled_policy(
        session_id: str,
        user: UserIdentity = Depends(guard),
    ) -> dict[str, list[str]]:
        """Slice VI — return the list of MCP server names disabled
        for this session. Empty list = all configured servers
        enabled. Tools owned by a listed server are blocked with an
        explanatory error from the disable callback."""
        try:
            disabled = await runtime.get_session_mcp_disabled(
                session_id=session_id, user_id=user.user_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"disabled": disabled}

    @app.put(
        "/v1/sessions/{session_id}/policy/mcp_disabled",
        tags=["policy"],
        summary="Set the per-session disabled-MCP-server list",
        response_model=McpDisabledResponse,
    )
    async def set_session_mcp_disabled_policy(
        session_id: str,
        body: SetMcpDisabledRequest,
        user: UserIdentity = Depends(guard),
    ) -> dict[str, list[str]]:
        """Replace the session's disabled-MCP-server list. Takes
        effect on the next tool call — no restart needed (the
        disable callback reads session state every call)."""
        try:
            applied = await runtime.set_session_mcp_disabled(
                session_id=session_id, disabled=body.disabled, user_id=user.user_id,
            )
        except ValueError as exc:
            message = str(exc)
            if message.startswith("no session"):
                raise HTTPException(status_code=404, detail=message) from exc
            raise HTTPException(status_code=400, detail=message) from exc
        return {"disabled": applied}

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

    # ── Skills (user-installable bundles) ─────────────────────────────

    @app.post(
        "/v1/skills",
        tags=["skills"],
        summary="Install a skill from a zip archive",
        response_model=InstallSkillResult,
    )
    async def install_skill(
        file: UploadFile = File(...),
        user: UserIdentity = Depends(guard),
    ) -> dict[str, str]:
        """Upload a ``.zip`` containing exactly one
        ``<name>/SKILL.md`` bundle. Extracts to
        ``<workspace>/global/skills/<name>/`` atomically; validation
        failures (bad frontmatter, path traversal, zip-bomb,
        bundled-name collision) return 400."""
        try:
            data = await file.read()
        finally:
            await file.close()
        try:
            installed = runtime.install_skill_zip(data)
        except SkillInstallError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "name": installed.name,
            "description": installed.description,
            "license": installed.license,
            "source": installed.source,
            "version": installed.version,
            "triggers": list(installed.triggers),
            "content_hash": installed.content_hash,
        }

    @app.post(
        "/v1/skills/validate",
        tags=["skills"],
        summary="Dry-run install validation for a skill zip",
        response_model=ValidateSkillResult,
    )
    async def validate_skill(
        file: UploadFile = File(...),
        user: UserIdentity = Depends(guard),
    ) -> dict[str, str]:
        """Run the same validation pipeline as ``POST /v1/skills`` —
        zip-bomb caps, path-traversal rejection, frontmatter parse,
        bundled-collision check, name-vs-frontmatter match — but
        roll back the staging dir instead of committing. Returns
        the parsed ``SkillInfo`` on success; any validation failure
        returns 400 with the exception message."""
        try:
            data = await file.read()
        finally:
            await file.close()
        try:
            parsed = runtime.validate_skill_zip(data)
        except SkillInstallError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "name": parsed.name,
            "description": parsed.description,
            "license": parsed.license,
            "source": parsed.source,
            "version": parsed.version,
            "triggers": list(parsed.triggers),
            "content_hash": parsed.content_hash,
        }

    @app.delete(
        "/v1/skills/{name}",
        tags=["skills"],
        summary="Uninstall a user-installed skill",
        response_model=DeleteSkillResult,
    )
    async def uninstall_skill(
        name: str,
        user: UserIdentity = Depends(guard),
    ) -> dict[str, str]:
        """Remove the folder under ``<workspace>/global/skills/<name>/``
        and reload the registry. Bundled skills return 400; unknown
        names return 404."""
        try:
            runtime.uninstall_skill(name)
        except SkillInstallError as exc:
            message = str(exc)
            if message.startswith("unknown skill"):
                raise HTTPException(status_code=404, detail=message) from exc
            raise HTTPException(status_code=400, detail=message) from exc
        return {"name": name, "status": "deleted"}

    # ── MCP server management (Slice IV) ──────────────────────────────

    def _server_info(name: str, cfg: McpServerConfig) -> dict[str, Any]:
        """Materialise an MCP server config for the wire shape."""
        return {
            "name": name,
            "transport": cfg.transport,
            "command": cfg.command,
            "args": list(cfg.args),
            "env": dict(cfg.env),
            "url": cfg.url,
            "headers": dict(cfg.headers),
            "tool_filter": list(cfg.tool_filter) if cfg.tool_filter else None,
            "description": cfg.description,
            "bundled": cfg.bundled,
        }

    def _status_payload(status: Any) -> dict[str, Any]:
        return {
            "name": status.name,
            "status": status.status,
            "last_error": status.last_error,
            "tool_count": status.tool_count,
            "transport": status.transport,
        }

    @app.get(
        "/v1/mcp/servers",
        tags=["mcp"],
        summary="List configured MCP servers + per-server status",
        response_model=McpServersListResponse,
    )
    async def list_mcp_servers(
        user: UserIdentity = Depends(guard),
    ) -> dict[str, Any]:
        """One row per server: the saved config + the live build
        status. Settings → MCP servers renders this list and gates
        the delete affordance on ``server.bundled``."""
        records: list[dict[str, Any]] = []
        for name, (cfg, status) in runtime.list_mcp_servers().items():
            records.append(
                {
                    "server": _server_info(name, cfg),
                    "status": _status_payload(status),
                }
            )
        return {"servers": records}

    @app.post(
        "/v1/mcp/servers",
        tags=["mcp"],
        summary="Add or update an MCP server (with dry-run discovery)",
        response_model=AddMcpServerResponse,
    )
    async def add_mcp_server(
        body: AddMcpServerRequest,
        user: UserIdentity = Depends(guard),
    ) -> dict[str, Any]:
        """Validate the name, dry-run the connection (so the user
        gets immediate feedback if the command/url is wrong), and
        persist to ``<workspace>/global/mcp/servers.json``. Returns
        the saved config + the discovered tool list so Settings can
        offer those tools as ``tool_filter`` options. The change
        does **not** take effect until ``POST /v1/mcp/restart``."""
        cfg = McpServerConfig(
            transport=body.transport,
            command=body.command,
            args=body.args,
            env=body.env,
            url=body.url,
            headers=body.headers,
            tool_filter=body.tool_filter,
            description=body.description,
            bundled=False,
        )
        try:
            tool_names = await runtime.dry_run_mcp_server(cfg)
        except MCPInstallError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            runtime.save_mcp_server(body.name, cfg)
        except MCPInstallError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "server": _server_info(body.name, cfg),
            "tools": tool_names,
        }

    @app.delete(
        "/v1/mcp/servers/{name}",
        tags=["mcp"],
        summary="Remove a user MCP server",
        response_model=DeleteMcpServerResult,
    )
    async def delete_mcp_server_endpoint(
        name: str,
        user: UserIdentity = Depends(guard),
    ) -> dict[str, str]:
        """Removes the entry from ``servers.json``. Bundled servers
        (declared in ``cowork.toml``) refuse with 400. Takes effect
        on the next ``POST /v1/mcp/restart``."""
        try:
            runtime.delete_mcp_server(name)
        except MCPInstallError as exc:
            message = str(exc)
            if message.startswith("unknown MCP server"):
                raise HTTPException(status_code=404, detail=message) from exc
            raise HTTPException(status_code=400, detail=message) from exc
        return {"name": name, "status": "deleted"}

    @app.post(
        "/v1/mcp/restart",
        tags=["mcp"],
        summary="Re-mount MCP toolsets from the current effective config",
        response_model=RestartMcpResult,
    )
    async def restart_mcp(
        user: UserIdentity = Depends(guard),
    ) -> dict[str, Any]:
        """Tear down current MCP toolsets, rebuild from the merged
        TOML + ``servers.json`` config, and replace the runner's
        agent in place. ``session_service`` is preserved so existing
        sessions stay reachable. **In-flight turns terminate** when
        the agent's tool list mutates underneath them — Settings
        confirms before calling this."""
        await runtime.restart_mcp()
        return {
            "servers": [_status_payload(s) for s in runtime.mcp_status.values()],
        }

    # ── Workspace-wide config edits (Slice T1, refined in U1) ──────────

    def _require_writable_workspace_settings(user: UserIdentity) -> Any:
        """Return ``runtime.workspace_settings_store`` or raise the
        right HTTP error.

        503 when there's no editable surface (env-only SU mode →
        store is None). 403 in multi-user mode when the caller isn't
        the configured operator (or no operator is configured at all
        — branched message). Single-user mode passes through (the
        local user is the operator by definition).
        """
        from cowork_server.auth import is_operator

        if runtime.workspace_settings_store is None:
            raise HTTPException(
                status_code=503,
                detail=(
                    "no editable settings surface (env-only SU mode); "
                    "set COWORK_CONFIG_PATH and restart to enable "
                    "in-app config edits"
                ),
            )
        if runtime.multi_user and not is_operator(cfg, user):
            if not cfg.auth.operator:
                raise HTTPException(
                    status_code=403,
                    detail=(
                        "workspace-wide config is operator-only and no "
                        "operator is configured for this server. Set "
                        "[auth].operator in cowork.toml to a user label "
                        "from [auth].keys, then restart."
                    ),
                )
            raise HTTPException(
                status_code=403,
                detail=(
                    f"workspace-wide config is operator-only; "
                    f"only the configured operator "
                    f"(label='{cfg.auth.operator}') can edit shared "
                    f"settings"
                ),
            )
        return runtime.workspace_settings_store

    def _log_settings_change(section: str, patch: dict[str, Any], user: UserIdentity) -> None:
        """R5 — record every workspace-settings PUT in two places so
        operators can answer 'where did my edit go':

        1. **Audit row** (V1) — structured row in the audit DB with
           ``kind="settings_change"`` and ``tool_name="config.<section>"``.
           Queryable via ``GET /v1/audit``.
        2. **Stdout breadcrumb** — short ``[settings] ... → <destination>``
           line for log-tailers; redundant with the audit row but
           cheap and zero-config to read.
        """
        import json as _json
        from datetime import UTC as _UTC, datetime as _datetime

        from cowork_core.audit import AuditEntry as _AuditEntry

        keys = ", ".join(f"{section}.{k}" for k in patch)
        destination = "multiuser.db" if runtime.multi_user else "cowork.toml"
        # Stdout breadcrumb (kept for log-tailers; will move to a
        # structured logger in V4c).
        print(
            f"[settings] {keys} updated → {destination} "
            f"(operator={user.label})",
            flush=True,
        )
        # Structured audit row.
        try:
            args_json = _json.dumps({"section": section, "keys": list(patch.keys())})
        except (TypeError, ValueError):
            args_json = None
        runtime.audit_sink.record(_AuditEntry(
            ts=_datetime.now(_UTC).isoformat(),
            user_id=user.user_id,
            kind="settings_change",
            tool_name=f"config.{section}",
            args_json=args_json,
            result_json=_json.dumps({"destination": destination}),
        ))

    @app.put(
        "/v1/config/model",
        tags=["config"],
        summary="Update [model] config",
        response_model=ConfigModelView,
    )
    async def update_config_model(
        body: ConfigModelPatch,
        user: UserIdentity = Depends(guard),
    ) -> dict[str, Any]:
        """Mutate the ``[model]`` section of the workspace settings.

        Single-user mode: writes directly to ``cowork.toml``. Multi-
        user mode: requires operator identity; writes to a DB-backed
        override layer in ``<workspace>/multiuser.db``. ``api_key``
        accepts a literal secret or an ``"env:VAR"`` reference (stored
        verbatim).

        Takes effect on next server restart. The UI surfaces a
        "restart required" banner after a successful save.
        """
        store = _require_writable_workspace_settings(user)
        patch = body.model_dump(exclude_none=True)
        try:
            section = store.set_section("model", patch)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        _log_settings_change("model", patch, user)
        return {
            "base_url": section.get("base_url", cfg.model.base_url),
            "model": section.get("model", cfg.model.model),
            "api_key": section.get("api_key", cfg.model.api_key),
        }

    @app.put(
        "/v1/config/compaction",
        tags=["config"],
        summary="Update [compaction] config",
        response_model=ConfigCompactionView,
    )
    async def update_config_compaction(
        body: ConfigCompactionPatch,
        user: UserIdentity = Depends(guard),
    ) -> dict[str, Any]:
        """Mutate the ``[compaction]`` section of the workspace
        settings. Single-user mode writes ``cowork.toml`` directly;
        multi-user mode writes the DB override layer (operator-only).
        Pydantic validates the field ranges
        (``compaction_interval >= 1``, ``overlap_size >= 0``,
        ``token_threshold >= 1``, ``event_retention_size >= 0``).
        Takes effect on next server restart."""
        store = _require_writable_workspace_settings(user)
        patch = body.model_dump(exclude_none=True)
        try:
            section = store.set_section("compaction", patch)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        _log_settings_change("compaction", patch, user)
        return {
            "enabled": section.get("enabled", cfg.compaction.enabled),
            "compaction_interval": section.get(
                "compaction_interval", cfg.compaction.compaction_interval,
            ),
            "overlap_size": section.get(
                "overlap_size", cfg.compaction.overlap_size,
            ),
            "token_threshold": section.get(
                "token_threshold", cfg.compaction.token_threshold,
            ),
            "event_retention_size": section.get(
                "event_retention_size", cfg.compaction.event_retention_size,
            ),
        }

    @app.get(
        "/v1/config/effective",
        tags=["config"],
        summary="Get the effective workspace config + per-key source map",
        response_model=EffectiveConfig,
    )
    async def get_config_effective(
        user: UserIdentity = Depends(guard),
    ) -> dict[str, Any]:
        """Return merged ``[model]`` + ``[compaction]`` + a per-key
        source map (``"db"`` for keys overridden in
        ``multiuser.db.workspace_settings``, ``"toml"`` for keys
        coming from ``cowork.toml`` defaults).

        Slice U1 — the UI uses this to render ``(db)`` / ``(toml)``
        source badges next to each editable field. Loaded on Settings
        mount and refreshed after each save.
        """
        # Source map starts out all "toml" (the boot default); any
        # key present in the store's overrides flips to "db" or
        # "toml" depending on which backing wrote it.
        overrides: dict[str, dict[str, Any]] = {}
        if runtime.workspace_settings_store is not None:
            try:
                overrides = runtime.workspace_settings_store.get_overrides()
            except Exception:
                overrides = {}
        # In MU the overrides come from DB; in SU they came from TOML
        # already (FS backing reads cowork.toml).
        source_label = "db" if runtime.multi_user else "toml"
        sources: dict[str, str] = {}
        for section, fields in overrides.items():
            for leaf in fields:
                sources[f"{section}.{leaf}"] = source_label
        # Default any non-overridden key to "toml" (the boot default).
        for key in (
            "model.base_url", "model.model", "model.api_key",
            "compaction.enabled", "compaction.compaction_interval",
            "compaction.overlap_size", "compaction.token_threshold",
            "compaction.event_retention_size",
        ):
            sources.setdefault(key, "toml")
        return {
            "model": {
                "base_url": cfg.model.base_url,
                "model": cfg.model.model,
                "api_key": cfg.model.api_key,
            },
            "compaction": {
                "enabled": cfg.compaction.enabled,
                "compaction_interval": cfg.compaction.compaction_interval,
                "overlap_size": cfg.compaction.overlap_size,
                "token_threshold": cfg.compaction.token_threshold,
                "event_retention_size": cfg.compaction.event_retention_size,
            },
            "source": sources,
        }

    # ── Audit log (Slice V1) ───────────────────────────────────────────

    @app.get(
        "/v1/audit",
        tags=["audit"],
        summary="Query the audit log (operator-only in MU)",
        response_model=AuditQueryResponse,
    )
    async def query_audit(
        user_id: str | None = None,
        session_id: str | None = None,
        tool_name: str | None = None,
        since_ts: str | None = None,
        limit: int = 100,
        user: UserIdentity = Depends(guard),
    ) -> dict[str, Any]:
        """Query the audit log. Multi-user mode: operator-only —
        the audit covers every authenticated user's activity, so
        access is gated to prevent one user from snooping on
        another. Single-user mode: open (the local user audits
        their own activity).

        Filters are AND'd. ``limit`` is capped at 1000 server-side.
        Newest-first ordering by ``ts``.
        """
        from cowork_server.auth import is_operator

        if runtime.multi_user and not is_operator(cfg, user):
            raise HTTPException(
                status_code=403,
                detail="audit log is operator-only in multi-user mode",
            )
        entries = runtime.audit_sink.query(
            user_id=user_id,
            session_id=session_id,
            tool_name=tool_name,
            since_ts=since_ts,
            limit=limit,
        )
        return {
            "entries": [
                {
                    "ts": e.ts,
                    "user_id": e.user_id,
                    "kind": e.kind,
                    "tool_name": e.tool_name,
                    "session_id": e.session_id,
                    "project_id": e.project_id,
                    "args_json": e.args_json,
                    "result_json": e.result_json,
                    "error_text": e.error_text,
                    "duration_ms": e.duration_ms,
                }
                for e in entries
            ],
        }

    # ── Per-user profile (Slice T1) ────────────────────────────────────

    _PROFILE_KEY = "settings/profile.json"

    @app.get(
        "/v1/profile",
        tags=["profile"],
        summary="Get the calling user's profile",
        response_model=UserProfile,
    )
    async def get_profile(
        user: UserIdentity = Depends(guard),
    ) -> dict[str, Any]:
        """Read the calling user's profile from the ``UserStore``.
        ``display_name`` and ``email`` default to empty strings when
        unset. ``user_id`` is sourced from the auth token, never the
        body — clients can't change it via this route."""
        import json

        raw = runtime.user_store.read(user.user_id, _PROFILE_KEY)
        data: dict[str, Any] = {}
        if raw is not None:
            try:
                parsed = json.loads(raw.decode("utf-8"))
                if isinstance(parsed, dict):
                    data = parsed
            except (ValueError, UnicodeDecodeError):
                data = {}
        return {
            "user_id": user.user_id,
            "display_name": str(data.get("display_name", "")),
            "email": str(data.get("email", "")),
        }

    @app.put(
        "/v1/profile",
        tags=["profile"],
        summary="Update the calling user's profile",
        response_model=UserProfile,
    )
    async def put_profile(
        body: UserProfilePatch,
        user: UserIdentity = Depends(guard),
    ) -> dict[str, Any]:
        """Update the calling user's profile. Only the fields named in
        the body are touched; ``None`` keeps the existing value.
        Per-user — alice's PUT can't affect bob's profile."""
        import json

        raw = runtime.user_store.read(user.user_id, _PROFILE_KEY)
        current: dict[str, Any] = {}
        if raw is not None:
            try:
                parsed = json.loads(raw.decode("utf-8"))
                if isinstance(parsed, dict):
                    current = parsed
            except (ValueError, UnicodeDecodeError):
                current = {}

        if body.display_name is not None:
            current["display_name"] = body.display_name
        if body.email is not None:
            if body.email and "@" not in body.email:
                raise HTTPException(
                    status_code=422,
                    detail="email must contain '@'",
                )
            current["email"] = body.email

        runtime.user_store.write(
            user.user_id, _PROFILE_KEY,
            json.dumps(current).encode("utf-8"),
        )
        return {
            "user_id": user.user_id,
            "display_name": str(current.get("display_name", "")),
            "email": str(current.get("email", "")),
        }

    # ── Memory page management (Slice T1) ──────────────────────────────

    _MEMORY_PAGES_PREFIX = "memory/pages/"

    def _validate_memory_scope(scope: str) -> str:
        if scope not in {"user", "project"}:
            raise HTTPException(
                status_code=400,
                detail=f"scope must be 'user' or 'project', got {scope!r}",
            )
        return scope

    async def _resolve_project_id(session_id: str | None, user_id: str) -> str:
        """For project-scope memory routes — get the project's
        ``str(project.root)`` from the session's CoworkToolContext.
        Returns 400 when ``session_id`` is missing, 404 when the
        session doesn't exist."""
        from cowork_core.tools.base import COWORK_CONTEXT_KEY

        if not session_id:
            raise HTTPException(
                status_code=400,
                detail=(
                    "session_id query parameter is required for "
                    "scope='project' memory routes"
                ),
            )
        sess = await runtime.runner.session_service.get_session(
            app_name="cowork", user_id=user_id, session_id=session_id,
        )
        if sess is None:
            raise HTTPException(
                status_code=404, detail=f"session {session_id} not found",
            )
        ctx = sess.state.get(COWORK_CONTEXT_KEY)
        if ctx is None or not hasattr(ctx, "project"):
            raise HTTPException(
                status_code=404,
                detail=f"session {session_id} has no project context",
            )
        return str(ctx.project.root)

    def _list_pages_user(user_id: str) -> list[dict[str, Any]]:
        keys = runtime.user_store.list(user_id, _MEMORY_PAGES_PREFIX)
        return [
            _page_info(name, runtime.user_store.read(user_id, name))
            for name in keys if name.endswith(".md")
        ]

    def _list_pages_project(user_id: str, project_id: str) -> list[dict[str, Any]]:
        keys = runtime.project_store.list(
            user_id, project_id, _MEMORY_PAGES_PREFIX,
        )
        return [
            _page_info(
                name, runtime.project_store.read(user_id, project_id, name),
            )
            for name in keys if name.endswith(".md")
        ]

    def _page_info(key: str, body: bytes | None) -> dict[str, Any]:
        # Strip the "memory/pages/" prefix for the public name; the
        # full key is an implementation detail of the storage layer.
        public_name = key[len(_MEMORY_PAGES_PREFIX):] if key.startswith(_MEMORY_PAGES_PREFIX) else key
        if body is None:
            return {"name": public_name, "size": 0, "preview": ""}
        text = body.decode("utf-8", errors="replace")
        preview = text[:80].replace("\n", " ").replace("\r", " ")
        return {"name": public_name, "size": len(body), "preview": preview}

    @app.get(
        "/v1/memory/{scope}/pages",
        tags=["memory"],
        summary="List memory pages for the given scope",
        response_model=MemoryPageList,
    )
    async def list_memory_pages(
        scope: str,
        session_id: str | None = None,
        user: UserIdentity = Depends(guard),
    ) -> dict[str, Any]:
        """List pages under ``memory/pages/`` for the given scope.
        ``user`` scope reads from the calling user's ``UserStore``;
        ``project`` scope requires ``?session_id=`` to identify which
        project's store to query."""
        scope = _validate_memory_scope(scope)
        if scope == "user":
            pages = _list_pages_user(user.user_id)
        else:
            project_id = await _resolve_project_id(session_id, user.user_id)
            pages = _list_pages_project(user.user_id, project_id)
        return {"scope": scope, "pages": pages}

    @app.get(
        "/v1/memory/{scope}/pages/{name:path}",
        tags=["memory"],
        summary="Read a memory page",
        response_model=MemoryPageContent,
    )
    async def read_memory_page(
        scope: str,
        name: str,
        session_id: str | None = None,
        user: UserIdentity = Depends(guard),
    ) -> dict[str, Any]:
        """Return the full content of ``pages/<name>`` (e.g.
        ``pages/scratch.md``). ``name`` is the relative-to-pages name
        — the route prepends ``memory/pages/`` before lookup. 404 on
        missing."""
        scope = _validate_memory_scope(scope)
        if not name or ".." in name.split("/") or name.startswith("/"):
            raise HTTPException(status_code=400, detail=f"invalid page name: {name!r}")
        key = f"{_MEMORY_PAGES_PREFIX}{name}"
        if scope == "user":
            body = runtime.user_store.read(user.user_id, key)
        else:
            project_id = await _resolve_project_id(session_id, user.user_id)
            body = runtime.project_store.read(user.user_id, project_id, key)
        if body is None:
            raise HTTPException(status_code=404, detail=f"page not found: {name}")
        return {
            "scope": scope,
            "name": name,
            "content": body.decode("utf-8", errors="replace"),
        }

    @app.delete(
        "/v1/memory/{scope}/pages/{name:path}",
        tags=["memory"],
        summary="Delete a memory page",
        response_model=DeleteResponse,
    )
    async def delete_memory_page(
        scope: str,
        name: str,
        session_id: str | None = None,
        user: UserIdentity = Depends(guard),
    ) -> dict[str, str]:
        """Idempotent — deleting a missing page returns 200, not 404
        (matches the existing skill / MCP delete semantics)."""
        scope = _validate_memory_scope(scope)
        if not name or ".." in name.split("/") or name.startswith("/"):
            raise HTTPException(status_code=400, detail=f"invalid page name: {name!r}")
        key = f"{_MEMORY_PAGES_PREFIX}{name}"
        if scope == "user":
            runtime.user_store.delete(user.user_id, key)
        else:
            project_id = await _resolve_project_id(session_id, user.user_id)
            runtime.project_store.delete(user.user_id, project_id, key)
        return {"status": "deleted"}

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

    # ── Local-dir file browser + sessions (desktop surface; SU only) ─

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

    # ── Slice U0 — filter routes by deployment mode ───────────────────
    #
    # Each backend's create_app calls into this shared function with a
    # mode discriminator. We register everything above, then strip the
    # routes that don't belong in the requested deployment shape.
    # Filtering after registration keeps the route bodies clean (no
    # mode-conditional indentation), and future MU-only routes added
    # by cowork-server-web's app_factory after this returns won't be
    # affected by the filter.
    if mode != "all":
        _filter_routes_by_mode(app, mode)

    return app


_SU_ONLY_PATH_PREFIXES = (
    "/v1/local-files",
    "/v1/local-sessions",
)
_MU_ONLY_PATH_PREFIXES = (
    "/v1/projects",
)


def _filter_routes_by_mode(app: FastAPI, mode: CreateAppMode) -> None:
    """Strip routes that don't belong in the requested deployment mode.

    ``mode == "app"`` removes managed-projects + managed-files routes
    (everything under ``/v1/projects/...``).
    ``mode == "web"`` removes local-dir routes
    (``/v1/local-files``, ``/v1/local-sessions``).

    The OpenAPI schema is regenerated automatically on the next
    ``/openapi.json`` request — FastAPI memoises it via
    ``app.openapi_schema``, which we clear here so the filtered
    surface is reflected.
    """
    keep = []
    for route in app.router.routes:
        path = getattr(route, "path", "")
        if mode == "app" and any(path.startswith(p) for p in _MU_ONLY_PATH_PREFIXES):
            continue
        if mode == "web" and any(path.startswith(p) for p in _SU_ONLY_PATH_PREFIXES):
            continue
        keep.append(route)
    app.router.routes = keep
    # Force OpenAPI schema regeneration on next access.
    app.openapi_schema = None


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
