/**
 * Typed client for the cowork /v1 protocol.
 *
 * Streams ADK ``Event`` JSON over SSE. The wire format matches Google
 * ADK's own ``/run_sse`` — raw
 * ``Event.model_dump_json(exclude_none=True, by_alias=True)``.
 */

import type {
  AddMcpServerRequest,
  AddMcpServerResponse,
  AdkEvent,
  FileEntry,
  HealthInfo,
  LocalFileListResult,
  LocalFileReadResult,
  LocalSessionListItem,
  MCPServerStatusInfo,
  McpServerRecord,
  Notification,
  PolicyMode,
  ProjectInfo,
  PythonExecPolicy,
  SearchResults,
  SessionInfo,
  SessionListItem,
  SkillInfo,
  ToolAllowlist,
  ToolApprovalResult,
  UploadFileResult,
} from "./types";

export type EventHandler = (ev: AdkEvent) => void;

export class CoworkClient {
  private baseUrl: string;
  private token: string;
  private es: EventSource | null = null;
  private eventHandler: EventHandler | null = null;
  /** Extra SSE streams kept open for sessions that were running when
   *  the user switched away. Indexed by sessionId so we can close a
   *  specific one on ``turnComplete`` without touching the primary. */
  private bgStreams = new Map<string, EventSource>();

  constructor(baseUrl = "", token?: string) {
    this.baseUrl = baseUrl;
    this.token =
      token ?? (typeof __COWORK_TOKEN__ !== "undefined" ? __COWORK_TOKEN__ : "");
  }

  /** JSON request headers (content-type + token). Used for every
   *  method whose body is JSON. */
  private jsonHeaders(): Record<string, string> {
    const h: Record<string, string> = { "Content-Type": "application/json" };
    if (this.token) h["x-cowork-token"] = this.token;
    return h;
  }

  /** Token-only headers. Used for DELETE (no body) and for
   *  FormData uploads where the browser sets content-type itself. */
  private authHeaders(): Record<string, string> {
    return this.token ? { "x-cowork-token": this.token } : {};
  }

  /** Compose the SSE URL for a session's event stream. Token is
   *  passed as a query param because ``EventSource`` can't set
   *  custom request headers. */
  private sessionStreamUrl(sessionId: string): string {
    const qs = this.token ? `?token=${encodeURIComponent(this.token)}` : "";
    return `${this.baseUrl}/v1/sessions/${sessionId}/events/stream${qs}`;
  }

  async health(): Promise<HealthInfo> {
    const r = await fetch(`${this.baseUrl}/v1/health`, {
      headers: this.jsonHeaders(),
    });
    if (!r.ok) throw new Error(`health: ${r.status}`);
    return r.json();
  }

  async listProjects(): Promise<ProjectInfo[]> {
    const r = await fetch(`${this.baseUrl}/v1/projects`, {
      headers: this.jsonHeaders(),
    });
    if (!r.ok) throw new Error(`listProjects: ${r.status}`);
    return r.json();
  }

  async createProject(name: string): Promise<ProjectInfo> {
    const r = await fetch(`${this.baseUrl}/v1/projects`, {
      method: "POST",
      headers: this.jsonHeaders(),
      body: JSON.stringify({ name }),
    });
    if (!r.ok) throw new Error(`createProject: ${r.status}`);
    return r.json();
  }

  async listSessions(projectSlug: string): Promise<SessionListItem[]> {
    const r = await fetch(
      `${this.baseUrl}/v1/projects/${projectSlug}/sessions`,
      { headers: this.jsonHeaders() },
    );
    if (!r.ok) throw new Error(`listSessions: ${r.status}`);
    return r.json();
  }

  async deleteProject(projectSlug: string): Promise<void> {
    const r = await fetch(`${this.baseUrl}/v1/projects/${projectSlug}`, {
      method: "DELETE",
      headers: this.authHeaders(),
    });
    if (!r.ok) throw new Error(`deleteProject: ${r.status}`);
  }

  async deleteSession(projectSlug: string, sessionId: string): Promise<void> {
    const r = await fetch(
      `${this.baseUrl}/v1/projects/${projectSlug}/sessions/${sessionId}`,
      { method: "DELETE", headers: this.authHeaders() },
    );
    if (!r.ok) throw new Error(`deleteSession: ${r.status}`);
  }

  /** Toggle ``pinned`` (or other session metadata) for a managed
   *  project session. Server rewrites ``session.toml`` under a
   *  process-local lock so concurrent toggles don't collide. */
  async patchSession(
    projectSlug: string,
    sessionId: string,
    patch: { pinned?: boolean; title?: string },
  ): Promise<SessionListItem> {
    const r = await fetch(
      `${this.baseUrl}/v1/projects/${projectSlug}/sessions/${sessionId}`,
      {
        method: "PATCH",
        headers: this.jsonHeaders(),
        body: JSON.stringify(patch),
      },
    );
    if (!r.ok) throw new Error(`patchSession: ${r.status}`);
    return r.json();
  }

  /** Most-recent-first list of notifications for the current user.
   *  Ephemeral on the server — a restart wipes them. */
  async listNotifications(): Promise<Notification[]> {
    const r = await fetch(`${this.baseUrl}/v1/notifications`, {
      headers: this.jsonHeaders(),
    });
    if (!r.ok) throw new Error(`listNotifications: ${r.status}`);
    const body = (await r.json()) as { notifications: Notification[] };
    return body.notifications ?? [];
  }

  async markNotificationRead(id: string): Promise<void> {
    const r = await fetch(
      `${this.baseUrl}/v1/notifications/${id}/read`,
      { method: "POST", headers: this.jsonHeaders() },
    );
    if (!r.ok) throw new Error(`markNotificationRead: ${r.status}`);
  }

  async clearNotifications(): Promise<void> {
    const r = await fetch(`${this.baseUrl}/v1/notifications`, {
      method: "DELETE",
      headers: this.jsonHeaders(),
    });
    if (!r.ok) throw new Error(`clearNotifications: ${r.status}`);
  }

  /** Install a user-owned skill from a zip archive. Body is
   *  ``multipart/form-data`` with a single ``file`` field; server
   *  expands under ``<workspace>/global/skills/<name>/`` after
   *  validating the archive shape + frontmatter. 400 on any
   *  validation failure. */
  async installSkill(file: File | Blob, filename = "skill.zip"): Promise<SkillInfo> {
    const form = new FormData();
    form.append("file", file, filename);
    const r = await fetch(`${this.baseUrl}/v1/skills`, {
      method: "POST",
      headers: this.authHeaders(),
      body: form,
    });
    if (!r.ok) {
      const detail = await r.text();
      throw new Error(`installSkill: ${r.status} — ${detail}`);
    }
    return r.json();
  }

  /** Uninstall a user-owned skill. Bundled skills return 400;
   *  unknown names return 404. */
  async uninstallSkill(name: string): Promise<void> {
    const r = await fetch(
      `${this.baseUrl}/v1/skills/${encodeURIComponent(name)}`,
      { method: "DELETE", headers: this.authHeaders() },
    );
    if (!r.ok) {
      const detail = await r.text();
      throw new Error(`uninstallSkill: ${r.status} — ${detail}`);
    }
  }

  /** Configured MCP servers + their live status (Slice IV). Each entry
   *  pairs the user-editable ``McpServerInfo`` with the per-server
   *  ``MCPServerStatusInfo`` from the last toolset build. Bundled
   *  servers (declared in ``cowork.toml``) carry ``bundled: true``
   *  and refuse delete. */
  async listMcpServers(): Promise<McpServerRecord[]> {
    const r = await fetch(`${this.baseUrl}/v1/mcp/servers`, {
      headers: this.jsonHeaders(),
    });
    if (!r.ok) throw new Error(`listMcpServers: ${r.status}`);
    return ((await r.json()).servers ?? []) as McpServerRecord[];
  }

  /** Add or update a user MCP server. Server dry-runs the connection
   *  and returns the discovered tool list so the caller can pick a
   *  narrower ``tool_filter`` on a follow-up save. The change is
   *  staged in ``<workspace>/global/mcp/servers.json`` but does NOT
   *  affect the running root agent — call ``restartMcp`` to remount. */
  async addMcpServer(req: AddMcpServerRequest): Promise<AddMcpServerResponse> {
    const r = await fetch(`${this.baseUrl}/v1/mcp/servers`, {
      method: "POST",
      headers: this.jsonHeaders(),
      body: JSON.stringify(req),
    });
    if (!r.ok) {
      const detail = await r.text();
      throw new Error(`addMcpServer: ${r.status} — ${detail}`);
    }
    return r.json();
  }

  /** Remove a user MCP server from ``servers.json``. Bundled servers
   *  return 400; unknown names return 404. Like add, takes effect on
   *  the next ``restartMcp`` call. */
  async deleteMcpServer(name: string): Promise<void> {
    const r = await fetch(
      `${this.baseUrl}/v1/mcp/servers/${encodeURIComponent(name)}`,
      { method: "DELETE", headers: this.authHeaders() },
    );
    if (!r.ok) {
      const detail = await r.text();
      throw new Error(`deleteMcpServer: ${r.status} — ${detail}`);
    }
  }

  /** Rebuild the root agent's MCP toolsets from the current effective
   *  config (TOML + servers.json). In-flight turns terminate — the
   *  Settings UI confirms before calling. Returns the fresh per-server
   *  status list so the caller can refresh badges without a second
   *  health roundtrip. */
  async restartMcp(): Promise<MCPServerStatusInfo[]> {
    const r = await fetch(`${this.baseUrl}/v1/mcp/restart`, {
      method: "POST",
      headers: this.jsonHeaders(),
    });
    if (!r.ok) throw new Error(`restartMcp: ${r.status}`);
    return ((await r.json()).servers ?? []) as MCPServerStatusInfo[];
  }

  /** Cross-project ⌘K palette search. Server caches per (user, q) for
   *  30 s, capped at 50 hits per section — see ``cowork_server/app.py``
   *  ``_run_search``. */
  async search(q: string): Promise<SearchResults> {
    const qs = new URLSearchParams({ q });
    const r = await fetch(`${this.baseUrl}/v1/search?${qs.toString()}`, {
      headers: this.jsonHeaders(),
    });
    if (!r.ok) throw new Error(`search: ${r.status}`);
    return r.json();
  }

  /** Server-wide default mode — used for sessions that have not been
   *  opened yet. Read-only; to change mode for an active session, use
   *  ``setSessionPolicyMode`` below. */
  async getPolicyMode(): Promise<PolicyMode> {
    const r = await fetch(`${this.baseUrl}/v1/policy/mode`, {
      headers: this.jsonHeaders(),
    });
    if (!r.ok) throw new Error(`getPolicyMode: ${r.status}`);
    return (await r.json()).mode as PolicyMode;
  }

  async getSessionPolicyMode(sessionId: string): Promise<PolicyMode> {
    const r = await fetch(
      `${this.baseUrl}/v1/sessions/${sessionId}/policy/mode`,
      { headers: this.jsonHeaders() },
    );
    if (!r.ok) throw new Error(`getSessionPolicyMode: ${r.status}`);
    return (await r.json()).mode as PolicyMode;
  }

  async setSessionPolicyMode(
    sessionId: string,
    mode: PolicyMode,
  ): Promise<PolicyMode> {
    const r = await fetch(
      `${this.baseUrl}/v1/sessions/${sessionId}/policy/mode`,
      {
        method: "PUT",
        headers: this.jsonHeaders(),
        body: JSON.stringify({ mode }),
      },
    );
    if (!r.ok) throw new Error(`setSessionPolicyMode: ${r.status}`);
    return (await r.json()).mode as PolicyMode;
  }

  async getSessionPythonExec(sessionId: string): Promise<PythonExecPolicy> {
    const r = await fetch(
      `${this.baseUrl}/v1/sessions/${sessionId}/policy/python_exec`,
      { headers: this.jsonHeaders() },
    );
    if (!r.ok) throw new Error(`getSessionPythonExec: ${r.status}`);
    return (await r.json()).policy as PythonExecPolicy;
  }

  async setSessionPythonExec(
    sessionId: string,
    policy: PythonExecPolicy,
  ): Promise<PythonExecPolicy> {
    const r = await fetch(
      `${this.baseUrl}/v1/sessions/${sessionId}/policy/python_exec`,
      {
        method: "PUT",
        headers: this.jsonHeaders(),
        body: JSON.stringify({ policy }),
      },
    );
    if (!r.ok) throw new Error(`setSessionPythonExec: ${r.status}`);
    return (await r.json()).policy as PythonExecPolicy;
  }

  /** Per-agent tool allowlist (Tier E.E1). Empty dict = no
   *  restrictions; absent agent = unrestricted; empty list = silenced.
   *  Root agent is always unrestricted — the allowlist scopes
   *  specialist sub-agents only. */
  async getSessionToolAllowlist(sessionId: string): Promise<ToolAllowlist> {
    const r = await fetch(
      `${this.baseUrl}/v1/sessions/${sessionId}/policy/tool_allowlist`,
      { headers: this.jsonHeaders() },
    );
    if (!r.ok) throw new Error(`getSessionToolAllowlist: ${r.status}`);
    return ((await r.json()).allowlist ?? {}) as ToolAllowlist;
  }

  async setSessionToolAllowlist(
    sessionId: string,
    allowlist: ToolAllowlist,
  ): Promise<ToolAllowlist> {
    const r = await fetch(
      `${this.baseUrl}/v1/sessions/${sessionId}/policy/tool_allowlist`,
      {
        method: "PUT",
        headers: this.jsonHeaders(),
        body: JSON.stringify({ allowlist }),
      },
    );
    if (!r.ok) throw new Error(`setSessionToolAllowlist: ${r.status}`);
    return ((await r.json()).allowlist ?? {}) as ToolAllowlist;
  }

  /** `@`-mention auto-route flag (Tier E.E2). When on (default), the
   *  root agent honors a leading ``@<agent_name>`` in the user's
   *  message by transferring to that sub-agent. When off, the
   *  directive is omitted from the root's prompt. */
  async getSessionAutoRoute(sessionId: string): Promise<boolean> {
    const r = await fetch(
      `${this.baseUrl}/v1/sessions/${sessionId}/policy/auto_route`,
      { headers: this.jsonHeaders() },
    );
    if (!r.ok) throw new Error(`getSessionAutoRoute: ${r.status}`);
    return Boolean((await r.json()).enabled);
  }

  async setSessionAutoRoute(
    sessionId: string,
    enabled: boolean,
  ): Promise<boolean> {
    const r = await fetch(
      `${this.baseUrl}/v1/sessions/${sessionId}/policy/auto_route`,
      {
        method: "PUT",
        headers: this.jsonHeaders(),
        body: JSON.stringify({ enabled }),
      },
    );
    if (!r.ok) throw new Error(`setSessionAutoRoute: ${r.status}`);
    return Boolean((await r.json()).enabled);
  }

  /** Per-session skill enable map (Slice II). Skills absent from the
   *  returned dict default to enabled — UIs send only the entries
   *  they want to override. The root agent's prompt registry omits
   *  disabled skills on the next turn; ``load_skill`` refuses them. */
  async getSessionSkillsEnabled(sessionId: string): Promise<Record<string, boolean>> {
    const r = await fetch(
      `${this.baseUrl}/v1/sessions/${sessionId}/policy/skills_enabled`,
      { headers: this.jsonHeaders() },
    );
    if (!r.ok) throw new Error(`getSessionSkillsEnabled: ${r.status}`);
    return ((await r.json()).enabled ?? {}) as Record<string, boolean>;
  }

  async setSessionSkillsEnabled(
    sessionId: string,
    enabled: Record<string, boolean>,
  ): Promise<Record<string, boolean>> {
    const r = await fetch(
      `${this.baseUrl}/v1/sessions/${sessionId}/policy/skills_enabled`,
      {
        method: "PUT",
        headers: this.jsonHeaders(),
        body: JSON.stringify({ enabled }),
      },
    );
    if (!r.ok) throw new Error(`setSessionSkillsEnabled: ${r.status}`);
    return ((await r.json()).enabled ?? {}) as Record<string, boolean>;
  }

  /**
   * Create a new session.
   *
   * Pass ``project`` for managed mode (web surface) or ``workdir`` for
   * local-dir mode (desktop surface). The two are mutually exclusive; the
   * server rejects both.
   */
  async createSession(opts?: {
    project?: string;
    workdir?: string;
  }): Promise<SessionInfo> {
    const body: Record<string, string> = {};
    if (opts?.project) body.project = opts.project;
    if (opts?.workdir) body.workdir = opts.workdir;
    const r = await fetch(`${this.baseUrl}/v1/sessions`, {
      method: "POST",
      headers: this.jsonHeaders(),
      body: Object.keys(body).length ? JSON.stringify(body) : undefined,
    });
    if (!r.ok) throw new Error(`createSession: ${r.status}`);
    return r.json();
  }

  async resumeSession(
    sessionId: string,
    opts: { project?: string; workdir?: string },
  ): Promise<SessionInfo> {
    const body: Record<string, string> = {};
    if (opts.project) body.project = opts.project;
    if (opts.workdir) body.workdir = opts.workdir;
    const r = await fetch(
      `${this.baseUrl}/v1/sessions/${sessionId}/resume`,
      {
        method: "POST",
        headers: this.jsonHeaders(),
        body: JSON.stringify(body),
      },
    );
    if (!r.ok) throw new Error(`resumeSession: ${r.status}`);
    return r.json();
  }

  /** Grant one approval for a gated tool in this session. The permission
   *  callback consumes the approval on the next call of ``toolName``.
   *  When ``toolCallId`` is supplied the server also appends an
   *  approval event to the session's history so replaying the
   *  session doesn't re-prompt for the same call. */
  async approveTool(
    sessionId: string,
    toolName: string,
    toolCallId?: string,
  ): Promise<ToolApprovalResult> {
    const r = await fetch(
      `${this.baseUrl}/v1/sessions/${sessionId}/approvals`,
      {
        method: "POST",
        headers: this.jsonHeaders(),
        body: JSON.stringify(
          toolCallId
            ? { tool: toolName, tool_call_id: toolCallId }
            : { tool: toolName },
        ),
      },
    );
    if (!r.ok) throw new Error(`approveTool: ${r.status}`);
    return r.json();
  }

  async listLocalFiles(
    workdir: string,
    path: string = "",
  ): Promise<LocalFileListResult> {
    const qs = new URLSearchParams({ workdir, path });
    const r = await fetch(`${this.baseUrl}/v1/local-files?${qs.toString()}`, {
      headers: this.jsonHeaders(),
    });
    if (!r.ok) throw new Error(`listLocalFiles: ${r.status}`);
    return r.json();
  }

  async readLocalFile(
    workdir: string,
    path: string,
  ): Promise<LocalFileReadResult> {
    const qs = new URLSearchParams({ workdir, path });
    const r = await fetch(
      `${this.baseUrl}/v1/local-files/content?${qs.toString()}`,
      { headers: this.jsonHeaders() },
    );
    if (!r.ok) throw new Error(`readLocalFile: ${r.status}`);
    return r.json();
  }

  async listLocalSessions(workdir: string): Promise<LocalSessionListItem[]> {
    const r = await fetch(
      `${this.baseUrl}/v1/local-sessions?workdir=${encodeURIComponent(workdir)}`,
      { headers: this.jsonHeaders() },
    );
    if (!r.ok) throw new Error(`listLocalSessions: ${r.status}`);
    return r.json();
  }

  async deleteLocalSession(workdir: string, sessionId: string): Promise<void> {
    const r = await fetch(
      `${this.baseUrl}/v1/local-sessions/${sessionId}?workdir=${encodeURIComponent(workdir)}`,
      { method: "DELETE", headers: this.authHeaders() },
    );
    if (!r.ok) throw new Error(`deleteLocalSession: ${r.status}`);
  }

  /** Local-dir counterpart to ``patchSession``. Writes / updates
   *  ``<workdir>/.cowork/sessions/{id}/session.toml`` server-side. */
  async patchLocalSession(
    workdir: string,
    sessionId: string,
    patch: { pinned?: boolean; title?: string },
  ): Promise<SessionListItem> {
    const r = await fetch(
      `${this.baseUrl}/v1/local-sessions/${sessionId}?workdir=${encodeURIComponent(workdir)}`,
      {
        method: "PATCH",
        headers: this.jsonHeaders(),
        body: JSON.stringify(patch),
      },
    );
    if (!r.ok) throw new Error(`patchLocalSession: ${r.status}`);
    return r.json();
  }

  async getHistory(sessionId: string): Promise<AdkEvent[]> {
    const r = await fetch(
      `${this.baseUrl}/v1/sessions/${sessionId}/history`,
      { headers: this.jsonHeaders() },
    );
    if (!r.ok) throw new Error(`getHistory: ${r.status}`);
    return r.json();
  }

  async sendMessage(sessionId: string, text: string): Promise<void> {
    const r = await fetch(
      `${this.baseUrl}/v1/sessions/${sessionId}/messages`,
      {
        method: "POST",
        headers: this.jsonHeaders(),
        body: JSON.stringify({ text }),
      },
    );
    if (!r.ok) throw new Error(`sendMessage: ${r.status}`);
  }

  async listFiles(
    project: string,
    prefix: string,
  ): Promise<FileEntry[]> {
    const r = await fetch(
      `${this.baseUrl}/v1/projects/${project}/files/${prefix}`,
      { headers: this.jsonHeaders() },
    );
    if (!r.ok) throw new Error(`listFiles: ${r.status}`);
    return r.json();
  }

  previewUrl(project: string, path: string): string {
    const qs = this.token ? `?token=${encodeURIComponent(this.token)}` : "";
    return `${this.baseUrl}/v1/projects/${project}/preview/${path}${qs}`;
  }

  async uploadFile(
    project: string,
    file: File | Blob,
    filename: string,
    prefix: "files" | "scratch" = "files",
  ): Promise<UploadFileResult> {
    const form = new FormData();
    form.append("file", file, filename);
    const r = await fetch(
      `${this.baseUrl}/v1/projects/${project}/upload?prefix=${prefix}`,
      {
        method: "POST",
        headers: this.authHeaders(),
        body: form,
      },
    );
    if (!r.ok) throw new Error(`uploadFile: ${r.status}`);
    return r.json();
  }

  /** Open an SSE stream — preferred for browser clients.
   *
   *  Closes the current *primary* stream and installs this one in its
   *  place. Background streams opened via ``subscribeBackground`` are
   *  left alone so in-flight turns in other sessions keep consuming
   *  events until their ``turnComplete`` arrives. */
  connectStream(sessionId: string, onEvent: EventHandler): void {
    // Close only the primary stream. Do NOT touch bgStreams — those
    // are owned by separate sessions and have their own lifecycle.
    if (this.es) {
      this.es.close();
      this.es = null;
    }
    this.eventHandler = onEvent;
    const url = this.sessionStreamUrl(sessionId);
    this.es = new EventSource(url);

    this.es.onopen = () => console.log("[cowork] sse open", url);
    this.es.onmessage = (ev) => {
      try {
        const adkEvent: AdkEvent = JSON.parse(ev.data);
        this.eventHandler?.(adkEvent);
      } catch {
        /* ignore unparseable frames */
      }
    };
    this.es.onerror = () => {
      // EventSource auto-reconnects on transient errors; surface a
      // soft error only when the stream is fully closed.
      if (this.es && this.es.readyState === EventSource.CLOSED) {
        this.eventHandler?.({
          author: "cowork-client",
          errorCode: "SSE_CLOSED",
          errorMessage: "SSE stream closed",
          turnComplete: true,
        });
      }
    };
  }

  disconnect(): void {
    if (this.es) {
      this.es.close();
      this.es = null;
    }
    this.eventHandler = null;
    for (const es of this.bgStreams.values()) es.close();
    this.bgStreams.clear();
  }

  /** Open an auxiliary SSE stream for a background session — used to
   *  observe ``turnComplete`` for a session the user switched away
   *  from while its turn was still in flight. Returns a disposer that
   *  closes the stream. */
  subscribeBackground(sessionId: string, onEvent: EventHandler): () => void {
    // Replace any existing background stream for this session.
    this.bgStreams.get(sessionId)?.close();
    const es = new EventSource(this.sessionStreamUrl(sessionId));
    es.onmessage = (ev) => {
      try {
        const adkEvent: AdkEvent = JSON.parse(ev.data);
        onEvent(adkEvent);
      } catch {
        /* ignore unparseable frames */
      }
    };
    es.onerror = () => {
      if (es.readyState === EventSource.CLOSED) {
        this.bgStreams.delete(sessionId);
      }
    };
    this.bgStreams.set(sessionId, es);
    return () => {
      const cur = this.bgStreams.get(sessionId);
      if (cur === es) {
        es.close();
        this.bgStreams.delete(sessionId);
      }
    };
  }
}
