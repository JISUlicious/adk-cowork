/**
 * Wire types for cowork-server streams.
 *
 * The server forwards raw Google ADK ``Event`` objects via
 * ``Event.model_dump_json(exclude_none=True, by_alias=True)``, matching
 * ADK's own ``/run_sse`` / ``/run_live`` contract. All field names are
 * camelCase. Mirror here only the fields the UI consumes — everything
 * else rides through via the string-index signature.
 */

export interface AdkFunctionCall {
  id?: string;
  name?: string;
  args?: Record<string, unknown>;
}

export interface AdkFunctionResponse {
  id?: string;
  name?: string;
  response?: Record<string, unknown>;
}

export interface AdkPart {
  text?: string;
  thought?: boolean;
  functionCall?: AdkFunctionCall;
  functionResponse?: AdkFunctionResponse;
  [k: string]: unknown;
}

export interface AdkContent {
  role?: string;
  parts?: AdkPart[];
}

/** ADK's ``EventCompaction`` — set on ``event.actions.compaction`` when the
 *  runner rolls a range of prior events into an LLM-generated summary.
 *  ``compactedContent`` is a regular ADK ``Content`` block (usually a
 *  single text part). Start/end timestamps bound the invocations that
 *  were summarised. */
export interface AdkCompaction {
  startTimestamp?: number;
  endTimestamp?: number;
  compactedContent?: AdkContent;
}

export interface AdkEvent {
  id?: string;
  invocationId?: string;
  author?: string;
  content?: AdkContent;
  actions?: {
    stateDelta?: Record<string, unknown>;
    state_delta?: Record<string, unknown>;
    compaction?: AdkCompaction;
    [k: string]: unknown;
  };
  partial?: boolean;
  turnComplete?: boolean;
  errorCode?: string | null;
  errorMessage?: string | null;
  longRunningToolIds?: string[];
  timestamp?: number;
  usageMetadata?: Record<string, unknown>;
  [k: string]: unknown;
}

/** API response types */

export interface SessionInfo {
  session_id: string;
  project: string;
  cowork_session_id: string;
}

export interface CompactionSettings {
  enabled: boolean;
  compaction_interval: number;
  overlap_size: number;
  token_threshold: number;
  event_retention_size: number;
}

/** One entry in the health payload's ``skills`` list. Mirrors
 *  ``cowork_server.api_models.SkillInfo`` server-side. ``source``
 *  discriminates where the skill came from; only ``"user"`` skills
 *  are uninstallable via ``DELETE /v1/skills/{name}``. ``version``,
 *  ``triggers``, and ``content_hash`` come from optional frontmatter
 *  fields surfaced for transparency (Slice I). */
export interface SkillInfo {
  name: string;
  description: string;
  license: string;
  source: "bundled" | "user" | "project" | "workdir";
  version?: string;
  triggers?: string[];
  content_hash?: string;
}

/** MCP transport selector — picks which ADK ``ConnectionParams``
 *  flavour the server uses. ``stdio`` runs a local subprocess;
 *  ``sse`` and ``http`` connect to a URL. */
export type McpTransport = "stdio" | "sse" | "http";

/** Per-MCP-server health entry. Mirrors
 *  ``cowork_server.api_models.MCPServerStatusInfo`` server-side.
 *  ``status === "error"`` carries a non-null ``last_error`` with
 *  the failure detail Settings shows inline. */
export interface MCPServerStatusInfo {
  name: string;
  status: "ok" | "error";
  last_error: string | null;
  tool_count: number | null;
  transport: McpTransport;
}

/** MCP server config the Settings UI renders + edits. Mirrors
 *  ``cowork_server.api_models.McpServerInfo``. */
export interface McpServerInfo {
  name: string;
  transport: McpTransport;
  command: string;
  args: string[];
  env: Record<string, string>;
  url: string;
  headers: Record<string, string>;
  tool_filter: string[] | null;
  description: string;
  bundled: boolean;
}

export interface McpServerRecord {
  server: McpServerInfo;
  status: MCPServerStatusInfo;
}

/** Body for ``POST /v1/mcp/servers``. Server validates the name,
 *  dry-runs the connection, and persists to
 *  ``<workspace>/global/mcp/servers.json``. */
export interface AddMcpServerRequest {
  name: string;
  transport?: McpTransport;
  command?: string;
  args?: string[];
  env?: Record<string, string>;
  url?: string;
  headers?: Record<string, string>;
  tool_filter?: string[] | null;
  description?: string;
}

export interface AddMcpServerResponse {
  server: McpServerInfo;
  /** Tool names discovered during the dry-run probe. The UI
   *  shows them so the user can pick a narrower ``tool_filter``
   *  on a follow-up save. */
  tools: string[];
}

export interface HealthInfo {
  status: string;
  /** Active LLM model identifier from ``[model] model`` in cowork.toml.
   *  Surfaced read-only in Settings → System. */
  model?: string;
  tools: string[];
  skills: SkillInfo[];
  mcp?: MCPServerStatusInfo[];
  compaction?: CompactionSettings;
  /** Slice T1 — multi-user mode? Settings UI uses this to render
   *  workspace-wide config (model, compaction) read-only when true.
   *  Defaults to false on older servers that haven't been upgraded. */
  is_multi_user?: boolean;
  /** Slice T1 — server has a ``cowork.toml`` on disk (started with
   *  ``COWORK_CONFIG_PATH``). When false, Settings renders the
   *  config blocks read-only with an "env-only mode" notice. */
  has_config_file?: boolean;
  /** Slice U1 — caller can edit workspace-wide settings (model +
   *  compaction). True in single-user mode; in multi-user mode iff
   *  the caller's user label matches ``cfg.auth.operator``. */
  is_operator?: boolean;
  /** Slice U1 — ``cfg.auth.operator`` is non-empty. Lets the UI
   *  distinguish "no operator configured" from "operator is someone
   *  else" so the notice text is accurate. */
  operator_configured?: boolean;
}

/** Slice U1 — ``GET /v1/config/effective``. ``source`` maps each
 *  dotted setting key to where its current value came from
 *  (``"db"`` for keys overridden in multi-user mode's
 *  ``workspace_settings`` table, ``"toml"`` for keys coming from
 *  ``cowork.toml`` defaults). The Settings UI uses it to render
 *  ``(db)`` / ``(toml)`` source badges next to each editable field. */
export interface EffectiveConfig {
  model: ConfigModelView;
  compaction: ConfigCompactionView;
  source: Record<string, "db" | "toml" | string>;
}

/** Slice V3 — body for ``POST /v1/skills/install-from-source``.
 *  ``source`` is passed verbatim to ``npx skills add <source>`` —
 *  GitHub shorthand (``vercel-labs/agent-skills``), full URL, or
 *  local path (SU only). */
export interface InstallSkillFromSourceRequest {
  source: string;
}

export interface InstallSkillSkipped {
  name: string;
  reason: string;
}

export interface InstallSkillFromSourceResponse {
  installed: SkillInfo[];
  skipped: InstallSkillSkipped[];
}

/** Slice V1 — one row from ``GET /v1/audit``. Settings → System
 *  surfaces a compact tail (latest N entries) so the operator can
 *  see at a glance what the agent has been doing.
 *
 *  ``args_json`` and ``result_json`` are JSON-serialized strings
 *  (not parsed objects) — the per-tool capture policy chose what
 *  fields to include; the UI renders them as raw mono text. */
export interface AuditEntry {
  ts: string;
  user_id: string;
  kind: string;
  tool_name: string;
  session_id?: string | null;
  project_id?: string | null;
  args_json?: string | null;
  result_json?: string | null;
  error_text?: string | null;
  duration_ms?: number | null;
}

export interface AuditQueryResponse {
  entries: AuditEntry[];
}

/* ───────── Settings UI editors (Slice T1/T2) ───────── */

/** Body for ``PUT /v1/config/model``. ``null`` / missing fields are
 *  preserved in the on-disk TOML; only set fields overwrite. */
export interface ConfigModelPatch {
  base_url?: string;
  model?: string;
  api_key?: string;
}

export interface ConfigModelView {
  base_url: string;
  model: string;
  api_key: string;
}

export interface ConfigCompactionPatch {
  enabled?: boolean;
  compaction_interval?: number;
  overlap_size?: number;
  token_threshold?: number;
  event_retention_size?: number;
}

export type ConfigCompactionView = Required<ConfigCompactionPatch>;

export interface UserProfile {
  user_id: string;
  display_name: string;
  email: string;
}

export interface UserProfilePatch {
  display_name?: string;
  email?: string;
}

export interface MemoryPageInfo {
  name: string;
  size: number;
  preview: string;
}

export interface MemoryPageList {
  scope: "user" | "project" | string;
  pages: MemoryPageInfo[];
}

export interface MemoryPageContent {
  scope: string;
  name: string;
  content: string;
}

export interface ProjectInfo {
  slug: string;
  name: string;
  created_at: string;
}

export interface SessionListItem {
  id: string;
  title: string | null;
  created_at: string;
  /** True when the user has pinned this session; pinned rows float
   *  to the top of their project group. Sourced from
   *  ``session.toml``; mutated via ``PATCH /v1/projects/.../sessions
   *  /{id}`` or the local-sessions equivalent. */
  pinned?: boolean;
}

export interface FileEntry {
  name: string;
  kind: "file" | "dir";
  size?: number | null;
  /** Unix epoch seconds from ``Path.stat().st_mtime``. Optional —
   *  the server drops it when ``stat()`` fails. */
  modified?: number | null;
}

/** A server-side notification. Ephemeral (process-memory only) — the
 *  store lives in ``cowork_core/notifications.py``. Kinds the UI
 *  handles today: ``turn_complete``, ``approval_needed``, ``error``. */
export interface Notification {
  id: string;
  kind: "turn_complete" | "approval_needed" | "error" | string;
  text: string;
  session_id?: string | null;
  project?: string | null;
  /** Unix epoch seconds. */
  created_at: number;
  read: boolean;
}

/* ───────── Policy surface ───────── */

/** Session policy mode — fresh sessions inherit the server default. */
export type PolicyMode = "plan" | "work" | "auto";

/** ``python_exec_run`` gate — ``confirm`` surfaces a UI prompt,
 *  ``allow`` passes through, ``deny`` hard-blocks. */
export type PythonExecPolicy = "confirm" | "allow" | "deny";

/** Per-agent tool allowlist. Absent agent = unrestricted; empty
 *  list = silenced. Root agent is unrestricted by design. */
export type ToolAllowlist = Record<string, string[]>;

/* ───────── Upload / approval / local FS results ───────── */

/** Return shape for ``POST /v1/projects/{slug}/upload``. */
export interface UploadFileResult {
  name: string;
  path: string;
  size: number;
}

/** Return shape for ``POST /v1/sessions/{id}/approvals``. */
export interface ToolApprovalResult {
  tool: string;
  remaining: number;
}

/** Return shape for ``GET /v1/local-files`` (desktop surface). */
export interface LocalFileListResult {
  path: string;
  entries: FileEntry[];
}

/** Return shape for ``GET /v1/local-files/content``. */
export interface LocalFileReadResult {
  path: string;
  content: string;
  truncated: boolean;
  size: number;
}

/** Return item for ``GET /v1/local-sessions``. Same shape as the
 *  managed ``SessionListItem``; aliased so consumers can be explicit
 *  about surface origin. */
export type LocalSessionListItem = SessionListItem;

/* ───────── ⌘K palette search ───────── */

export interface SearchSessionHit {
  session_id: string;
  title: string | null;
  project: string;
}

export interface SearchFileHit {
  project: string;
  path: string;
  name: string;
}

export interface SearchMessageHit {
  session_id: string;
  session_title: string | null;
  project: string;
  index: number;
  preview: string;
}

export interface SearchResults {
  sessions: SearchSessionHit[];
  files: SearchFileHit[];
  messages: SearchMessageHit[];
}
