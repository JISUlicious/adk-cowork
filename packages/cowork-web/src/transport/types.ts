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

export interface AdkEvent {
  id?: string;
  invocationId?: string;
  author?: string;
  content?: AdkContent;
  actions?: Record<string, unknown>;
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

export interface HealthInfo {
  status: string;
  tools: string[];
  skills: string[];
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
}

export interface FileEntry {
  name: string;
  kind: "file" | "dir";
  size?: number;
  modified?: string;
}
