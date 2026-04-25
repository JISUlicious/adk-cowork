"""Pydantic request / response models for the cowork-server `/v1` API.

These models drive the OpenAPI schema published at ``/openapi.json``
(Swagger UI at ``/docs``). They mirror the TypeScript types in
``packages/cowork-web/src/transport/types.ts`` — the two are kept in
sync by hand for now; auto-generated TS codegen is future work.

**Convention.** Every request model sets
``model_config = ConfigDict(extra="ignore")`` so existing clients
that send extra fields keep working. Response models are strict
(no extra fields) since they're shaped by our handlers.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


# ── Tag: health ────────────────────────────────────────────────────


class CompactionInfo(BaseModel):
    enabled: bool
    compaction_interval: int
    overlap_size: int
    token_threshold: int
    event_retention_size: int


class SkillInfo(BaseModel):
    """One entry in the health payload's ``skills`` list.

    Mirrors ``cowork_core.skills.Skill`` — ``name`` + ``description``
    match what the root agent's prompt registry shows; ``license``
    lets the UI surface Cowork's MIT default vs. user-installed
    third-party skills at a glance. ``source`` discriminates where
    the skill came from; Settings uses it to disable the uninstall
    affordance on bundled skills. ``version``, ``triggers``, and
    ``content_hash`` are optional frontmatter fields surfaced for
    transparency (Slice I).
    """

    name: str
    description: str
    license: str
    source: str = "bundled"
    version: str = "0.0.0"
    triggers: list[str] = Field(default_factory=list)
    content_hash: str = ""


class InstallSkillResult(SkillInfo):
    """Return shape for ``POST /v1/skills``. Identical to
    ``SkillInfo``; a separate model keeps the Swagger example on
    the install route obvious."""


class ValidateSkillResult(SkillInfo):
    """Return shape for ``POST /v1/skills/validate``. Same fields
    as ``SkillInfo`` — validation runs the install pipeline through
    the staging step but rolls back instead of committing, so the
    parsed metadata is identical to what install would have produced.
    """


class DeleteSkillResult(BaseModel):
    name: str
    status: str  # always ``"deleted"`` for now


class MCPServerStatusInfo(BaseModel):
    """Per-MCP-server health entry surfaced in ``/v1/health.mcp``.

    Mirrors ``cowork_core.runner.MCPServerStatus``. ``status`` is
    one of ``"ok"`` / ``"error"``; ``last_error`` carries the
    string detail when the server failed to build (Settings
    surfaces it inline). ``tool_count`` stays ``None`` at startup
    — ADK's ``MCPToolset`` lazy-loads tools, and Slice IV's
    add-server flow does dry-run discovery to fill it.
    """

    name: str
    status: Literal["ok", "error"]
    last_error: str | None = None
    tool_count: int | None = None
    transport: Literal["stdio", "sse", "http"] = "stdio"


class McpServerInfo(BaseModel):
    """Public representation of an MCP server config for the
    /v1/mcp/servers list. Mirrors ``cowork_core.config.McpServerConfig``
    but with the ``bundled`` flag exposed so Settings can disable
    the delete affordance on bundled (TOML-declared) entries."""

    model_config = ConfigDict(extra="ignore")

    name: str
    transport: Literal["stdio", "sse", "http"] = "stdio"
    command: str = ""
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str = ""
    headers: dict[str, str] = Field(default_factory=dict)
    tool_filter: list[str] | None = None
    description: str = ""
    bundled: bool = False


class McpServerRecord(BaseModel):
    """One entry in the /v1/mcp/servers list — config + live
    status, ready to render directly in the Settings UI."""

    server: McpServerInfo
    status: MCPServerStatusInfo


class McpServersListResponse(BaseModel):
    servers: list[McpServerRecord]


class AddMcpServerRequest(BaseModel):
    """Body for POST /v1/mcp/servers. ``name`` is the registry
    key; the rest mirrors McpServerConfig. Server validates the
    name shape, dry-runs the connection, and persists to
    <workspace>/global/mcp/servers.json."""

    model_config = ConfigDict(extra="ignore")

    name: str
    transport: Literal["stdio", "sse", "http"] = "stdio"
    command: str = ""
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str = ""
    headers: dict[str, str] = Field(default_factory=dict)
    tool_filter: list[str] | None = None
    description: str = ""


class AddMcpServerResponse(BaseModel):
    """Result of POST /v1/mcp/servers. ``server`` reflects the
    saved config; ``tools`` is the dry-run-discovered tool name
    list — Settings shows it so the user can pick a narrower
    ``tool_filter`` and re-save. The change does **not** take
    effect until POST /v1/mcp/restart fires."""

    server: McpServerInfo
    tools: list[str]


class DeleteMcpServerResult(BaseModel):
    name: str
    status: str  # always ``"deleted"``


class RestartMcpResult(BaseModel):
    """Return shape for POST /v1/mcp/restart. ``servers`` mirrors
    /v1/health.mcp post-restart so the UI can refresh the status
    pills without a second request."""

    servers: list[MCPServerStatusInfo]


class HealthResponse(BaseModel):
    status: str
    backend: str
    auth: str
    components: dict[str, str]
    model: str | None = None
    tools: list[str] = Field(default_factory=list)
    skills: list[SkillInfo] = Field(default_factory=list)
    mcp: list[MCPServerStatusInfo] = Field(default_factory=list)
    compaction: CompactionInfo | None = None


# ── Tag: projects ──────────────────────────────────────────────────


class ProjectInfo(BaseModel):
    slug: str
    name: str
    created_at: str


class CreateProjectRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(min_length=1)


class DeleteResponse(BaseModel):
    """Generic acknowledgement for delete-style routes that return
    ``{"status": "deleted"}`` or ``{"status": "ok"}``."""

    status: str


# ── Tag: sessions ──────────────────────────────────────────────────


class CreateSessionRequest(BaseModel):
    """Body for ``POST /v1/sessions``. Supply *exactly one* of
    ``project`` (managed mode) or ``workdir`` (local-dir mode)."""

    model_config = ConfigDict(extra="ignore")

    project: str | None = Field(default=None, description="Managed-mode project slug or name.")
    workdir: str | None = Field(default=None, description="Local-dir absolute workdir path (desktop surface).")


class ResumeSessionRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    project: str | None = None
    workdir: str | None = None


class SessionInfo(BaseModel):
    session_id: str
    project: str
    cowork_session_id: str
    workdir: str = ""


class SessionListItem(BaseModel):
    id: str
    title: str | None = None
    created_at: str
    pinned: bool = False


class PatchSessionRequest(BaseModel):
    """Mutate session metadata. Today only ``pinned`` actually writes;
    ``title`` is accepted for forward compatibility."""

    model_config = ConfigDict(extra="ignore")

    pinned: bool | None = None
    title: str | None = None


class SendMessageRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    text: str


class MessageAcceptedResponse(BaseModel):
    status: Literal["accepted"]


# ── Tag: policy ────────────────────────────────────────────────────

PolicyMode = Literal["plan", "work", "auto"]
PythonExecPolicy = Literal["confirm", "allow", "deny"]


class PolicyModeResponse(BaseModel):
    mode: PolicyMode


class SetPolicyModeRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    mode: PolicyMode


class PythonExecResponse(BaseModel):
    policy: PythonExecPolicy


class SetPythonExecRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    policy: PythonExecPolicy


class ToolAllowlistResponse(BaseModel):
    """Per-agent tool allowlist (Tier E.E1).

    Empty dict = no restrictions. Absent agent in the dict =
    unrestricted. Empty list for an agent = silenced. Root agent is
    unrestricted by design.
    """

    allowlist: dict[str, list[str]] = Field(default_factory=dict)


class SetToolAllowlistRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    allowlist: dict[str, list[str]]


class AutoRouteResponse(BaseModel):
    enabled: bool


class SetAutoRouteRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enabled: bool


class SkillsEnabledResponse(BaseModel):
    """Per-session skill enable map (Slice II). Skills absent from
    ``enabled`` default to enabled — UIs send only overrides."""

    enabled: dict[str, bool]


class SetSkillsEnabledRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enabled: dict[str, bool]


class McpDisabledResponse(BaseModel):
    """Per-session list of disabled MCP server names (Slice VI).
    Empty list = all configured servers enabled. Tools owned by a
    disabled server are blocked at the ``before_tool_callback``
    layer with an explanatory error."""

    disabled: list[str]


class SetMcpDisabledRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    disabled: list[str]


# ── Tag: approvals ─────────────────────────────────────────────────


class GrantApprovalRequest(BaseModel):
    """``tool`` is required. ``tool_call_id`` is optional but
    strongly recommended — when supplied, the server records an
    approval event in session history so a replay doesn't re-prompt
    for the same call."""

    model_config = ConfigDict(extra="ignore")

    tool: str = Field(min_length=1)
    tool_call_id: str | None = None


class GrantApprovalResponse(BaseModel):
    tool: str
    remaining: int


# ── Tag: notifications ─────────────────────────────────────────────


class NotificationItem(BaseModel):
    id: str
    kind: str
    text: str
    session_id: str | None = None
    project: str | None = None
    created_at: float
    read: bool


class NotificationsListResponse(BaseModel):
    notifications: list[NotificationItem]


class MarkReadResponse(BaseModel):
    id: str
    read: bool


class ClearNotificationsResponse(BaseModel):
    cleared: int


# ── Tag: search ────────────────────────────────────────────────────


class SearchSessionHit(BaseModel):
    session_id: str
    title: str | None = None
    project: str


class SearchFileHit(BaseModel):
    project: str
    path: str
    name: str


class SearchMessageHit(BaseModel):
    session_id: str
    session_title: str | None = None
    project: str
    index: int
    preview: str


class SearchResults(BaseModel):
    sessions: list[SearchSessionHit] = Field(default_factory=list)
    files: list[SearchFileHit] = Field(default_factory=list)
    messages: list[SearchMessageHit] = Field(default_factory=list)


# ── Tag: files ─────────────────────────────────────────────────────


class FileEntry(BaseModel):
    name: str
    kind: Literal["file", "dir"]
    size: int | None = None
    modified: float | None = None


class UploadFileResult(BaseModel):
    name: str
    path: str
    size: int


# ── Tag: local-dir ─────────────────────────────────────────────────


class LocalFileListResult(BaseModel):
    path: str
    entries: list[FileEntry]


class LocalFileReadResult(BaseModel):
    path: str
    content: str
    truncated: bool
    size: int


# ``LocalSessionListItem`` mirrors ``SessionListItem``; we alias to
# keep the two endpoint groupings explicit even though the wire
# bytes are identical.
LocalSessionListItem = SessionListItem


class PatchLocalSessionRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    pinned: bool | None = None
    title: str | None = None


__all__ = [
    # health + skills + mcp
    "CompactionInfo", "HealthResponse", "MCPServerStatusInfo", "SkillInfo",
    "InstallSkillResult", "ValidateSkillResult", "DeleteSkillResult",
    "McpServerInfo", "McpServerRecord", "McpServersListResponse",
    "AddMcpServerRequest", "AddMcpServerResponse", "DeleteMcpServerResult",
    "RestartMcpResult",
    # projects
    "ProjectInfo", "CreateProjectRequest", "DeleteResponse",
    # sessions
    "CreateSessionRequest", "ResumeSessionRequest", "SessionInfo",
    "SessionListItem", "PatchSessionRequest", "SendMessageRequest",
    "MessageAcceptedResponse",
    # policy
    "PolicyMode", "PythonExecPolicy",
    "PolicyModeResponse", "SetPolicyModeRequest",
    "PythonExecResponse", "SetPythonExecRequest",
    "ToolAllowlistResponse", "SetToolAllowlistRequest",
    "AutoRouteResponse", "SetAutoRouteRequest",
    "SkillsEnabledResponse", "SetSkillsEnabledRequest",
    "McpDisabledResponse", "SetMcpDisabledRequest",
    # approvals
    "GrantApprovalRequest", "GrantApprovalResponse",
    # notifications
    "NotificationItem", "NotificationsListResponse",
    "MarkReadResponse", "ClearNotificationsResponse",
    # search
    "SearchSessionHit", "SearchFileHit", "SearchMessageHit",
    "SearchResults",
    # files
    "FileEntry", "UploadFileResult",
    # local-dir
    "LocalFileListResult", "LocalFileReadResult",
    "LocalSessionListItem", "PatchLocalSessionRequest",
]


def __getattr__(name: str) -> Any:  # pragma: no cover - import shim
    raise AttributeError(name)
