/** Wire types matching cowork-server transport frames. */

export interface TextFrame {
  type: "text";
  text: string;
  author?: string;
  thought?: boolean;
}

export interface ToolCallFrame {
  type: "tool_call";
  name: string;
  args: Record<string, unknown>;
  id?: string;
  author?: string;
}

export interface ToolResultFrame {
  type: "tool_result";
  name: string;
  result: Record<string, unknown>;
  id?: string;
  author?: string;
}

export interface EndTurnFrame {
  type: "end_turn";
}

export interface ErrorFrame {
  type: "error";
  message: string;
}

export interface MultiFrame {
  type: "multi";
  frames: Frame[];
  author?: string;
}

export type Frame =
  | TextFrame
  | ToolCallFrame
  | ToolResultFrame
  | EndTurnFrame
  | ErrorFrame
  | MultiFrame;

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
