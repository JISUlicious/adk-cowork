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

export interface HealthInfo {
  status: string;
  tools: string[];
  skills: string[];
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
