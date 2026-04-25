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

export interface HealthInfo {
  status: string;
  /** Active LLM model identifier from ``[model] model`` in cowork.toml.
   *  Surfaced read-only in Settings → System. */
  model?: string;
  tools: string[];
  skills: SkillInfo[];
  compaction?: CompactionSettings;
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
