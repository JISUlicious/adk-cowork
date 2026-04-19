/**
 * Typed client for the cowork /v1 protocol.
 *
 * Streams ADK ``Event`` JSON over either SSE (default, browser-friendly)
 * or WebSocket (kept for future bidirectional use). Both wire formats
 * are identical to Google ADK's own ``/run_sse`` / ``/run_live`` — raw
 * ``Event.model_dump_json(exclude_none=True, by_alias=True)``.
 */

import type {
  AdkEvent,
  HealthInfo,
  SessionInfo,
  ProjectInfo,
  SessionListItem,
  FileEntry,
} from "./types";

export type EventHandler = (ev: AdkEvent) => void;

export class CoworkClient {
  private baseUrl: string;
  private token: string;
  private ws: WebSocket | null = null;
  private es: EventSource | null = null;
  private eventHandler: EventHandler | null = null;

  constructor(baseUrl = "", token?: string) {
    this.baseUrl = baseUrl;
    this.token =
      token ?? (typeof __COWORK_TOKEN__ !== "undefined" ? __COWORK_TOKEN__ : "");
  }

  private headers(): Record<string, string> {
    const h: Record<string, string> = { "Content-Type": "application/json" };
    if (this.token) h["x-cowork-token"] = this.token;
    return h;
  }

  async health(): Promise<HealthInfo> {
    const r = await fetch(`${this.baseUrl}/v1/health`, {
      headers: this.headers(),
    });
    if (!r.ok) throw new Error(`health: ${r.status}`);
    return r.json();
  }

  async listProjects(): Promise<ProjectInfo[]> {
    const r = await fetch(`${this.baseUrl}/v1/projects`, {
      headers: this.headers(),
    });
    if (!r.ok) throw new Error(`listProjects: ${r.status}`);
    return r.json();
  }

  async createProject(name: string): Promise<ProjectInfo> {
    const r = await fetch(`${this.baseUrl}/v1/projects`, {
      method: "POST",
      headers: this.headers(),
      body: JSON.stringify({ name }),
    });
    if (!r.ok) throw new Error(`createProject: ${r.status}`);
    return r.json();
  }

  async listSessions(projectSlug: string): Promise<SessionListItem[]> {
    const r = await fetch(
      `${this.baseUrl}/v1/projects/${projectSlug}/sessions`,
      { headers: this.headers() },
    );
    if (!r.ok) throw new Error(`listSessions: ${r.status}`);
    return r.json();
  }

  async deleteProject(projectSlug: string): Promise<void> {
    const h: Record<string, string> = {};
    if (this.token) h["x-cowork-token"] = this.token;
    const r = await fetch(`${this.baseUrl}/v1/projects/${projectSlug}`, {
      method: "DELETE",
      headers: h,
    });
    if (!r.ok) throw new Error(`deleteProject: ${r.status}`);
  }

  async deleteSession(projectSlug: string, sessionId: string): Promise<void> {
    const h: Record<string, string> = {};
    if (this.token) h["x-cowork-token"] = this.token;
    const r = await fetch(
      `${this.baseUrl}/v1/projects/${projectSlug}/sessions/${sessionId}`,
      { method: "DELETE", headers: h },
    );
    if (!r.ok) throw new Error(`deleteSession: ${r.status}`);
  }

  /** Server-wide default mode — used for sessions that have not been
   *  opened yet. Read-only in practice today; ``setPolicyMode`` is a
   *  deprecated shim. Use the session-scoped variants below for real
   *  mutations. */
  async getPolicyMode(): Promise<string> {
    const r = await fetch(`${this.baseUrl}/v1/policy/mode`, {
      headers: this.headers(),
    });
    if (!r.ok) throw new Error(`getPolicyMode: ${r.status}`);
    const data = await r.json();
    return data.mode;
  }

  async getSessionPolicyMode(sessionId: string): Promise<string> {
    const r = await fetch(
      `${this.baseUrl}/v1/sessions/${sessionId}/policy/mode`,
      { headers: this.headers() },
    );
    if (!r.ok) throw new Error(`getSessionPolicyMode: ${r.status}`);
    const data = await r.json();
    return data.mode;
  }

  async setSessionPolicyMode(
    sessionId: string,
    mode: string,
  ): Promise<string> {
    const r = await fetch(
      `${this.baseUrl}/v1/sessions/${sessionId}/policy/mode`,
      {
        method: "PUT",
        headers: this.headers(),
        body: JSON.stringify({ mode }),
      },
    );
    if (!r.ok) throw new Error(`setSessionPolicyMode: ${r.status}`);
    const data = await r.json();
    return data.mode;
  }

  async getSessionPythonExec(sessionId: string): Promise<string> {
    const r = await fetch(
      `${this.baseUrl}/v1/sessions/${sessionId}/policy/python_exec`,
      { headers: this.headers() },
    );
    if (!r.ok) throw new Error(`getSessionPythonExec: ${r.status}`);
    return (await r.json()).policy;
  }

  async setSessionPythonExec(
    sessionId: string,
    policy: "confirm" | "allow" | "deny",
  ): Promise<string> {
    const r = await fetch(
      `${this.baseUrl}/v1/sessions/${sessionId}/policy/python_exec`,
      {
        method: "PUT",
        headers: this.headers(),
        body: JSON.stringify({ policy }),
      },
    );
    if (!r.ok) throw new Error(`setSessionPythonExec: ${r.status}`);
    return (await r.json()).policy;
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
      headers: this.headers(),
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
        headers: this.headers(),
        body: JSON.stringify(body),
      },
    );
    if (!r.ok) throw new Error(`resumeSession: ${r.status}`);
    return r.json();
  }

  /** Grant one approval for a gated tool in this session. The permission
   *  callback consumes the approval on the next call of ``toolName``. */
  async approveTool(
    sessionId: string,
    toolName: string,
  ): Promise<{ tool: string; remaining: number }> {
    const r = await fetch(
      `${this.baseUrl}/v1/sessions/${sessionId}/approvals`,
      {
        method: "POST",
        headers: this.headers(),
        body: JSON.stringify({ tool: toolName }),
      },
    );
    if (!r.ok) throw new Error(`approveTool: ${r.status}`);
    return r.json();
  }

  async listLocalFiles(
    workdir: string,
    path: string = "",
  ): Promise<{
    path: string;
    entries: { name: string; kind: "dir" | "file"; size: number | null }[];
  }> {
    const qs = new URLSearchParams({ workdir, path });
    const r = await fetch(`${this.baseUrl}/v1/local-files?${qs.toString()}`, {
      headers: this.headers(),
    });
    if (!r.ok) throw new Error(`listLocalFiles: ${r.status}`);
    return r.json();
  }

  async readLocalFile(
    workdir: string,
    path: string,
  ): Promise<{ path: string; content: string; truncated: boolean; size: number }> {
    const qs = new URLSearchParams({ workdir, path });
    const r = await fetch(
      `${this.baseUrl}/v1/local-files/content?${qs.toString()}`,
      { headers: this.headers() },
    );
    if (!r.ok) throw new Error(`readLocalFile: ${r.status}`);
    return r.json();
  }

  async listLocalSessions(
    workdir: string,
  ): Promise<{ id: string; created_at: string; title: string | null }[]> {
    const r = await fetch(
      `${this.baseUrl}/v1/local-sessions?workdir=${encodeURIComponent(workdir)}`,
      { headers: this.headers() },
    );
    if (!r.ok) throw new Error(`listLocalSessions: ${r.status}`);
    return r.json();
  }

  async deleteLocalSession(workdir: string, sessionId: string): Promise<void> {
    const h: Record<string, string> = {};
    if (this.token) h["x-cowork-token"] = this.token;
    const r = await fetch(
      `${this.baseUrl}/v1/local-sessions/${sessionId}?workdir=${encodeURIComponent(workdir)}`,
      { method: "DELETE", headers: h },
    );
    if (!r.ok) throw new Error(`deleteLocalSession: ${r.status}`);
  }

  async getHistory(sessionId: string): Promise<AdkEvent[]> {
    const r = await fetch(
      `${this.baseUrl}/v1/sessions/${sessionId}/history`,
      { headers: this.headers() },
    );
    if (!r.ok) throw new Error(`getHistory: ${r.status}`);
    return r.json();
  }

  async sendMessage(sessionId: string, text: string): Promise<void> {
    const r = await fetch(
      `${this.baseUrl}/v1/sessions/${sessionId}/messages`,
      {
        method: "POST",
        headers: this.headers(),
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
      { headers: this.headers() },
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
  ): Promise<{ name: string; path: string; size: number }> {
    const form = new FormData();
    form.append("file", file, filename);
    const r = await fetch(
      `${this.baseUrl}/v1/projects/${project}/upload?prefix=${prefix}`,
      {
        method: "POST",
        headers: this.token ? { "x-cowork-token": this.token } : {},
        body: form,
      },
    );
    if (!r.ok) throw new Error(`uploadFile: ${r.status}`);
    return r.json();
  }

  /** Open an SSE stream — preferred for browser clients. */
  connectStream(sessionId: string, onEvent: EventHandler): void {
    this.disconnect();
    this.eventHandler = onEvent;
    const qs = this.token ? `?token=${encodeURIComponent(this.token)}` : "";
    const url = `${this.baseUrl}/v1/sessions/${sessionId}/events/stream${qs}`;
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

  /** Connect via WebSocket. Kept for callers that want full duplex. */
  connect(sessionId: string, onEvent: EventHandler): void {
    this.disconnect();
    this.eventHandler = onEvent;
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const host = this.baseUrl
      ? this.baseUrl.replace(/^https?:/, proto)
      : `${proto}//${window.location.host}`;
    const qs = this.token ? `?token=${encodeURIComponent(this.token)}` : "";
    const url = `${host}/v1/sessions/${sessionId}/events${qs}`;
    this.ws = new WebSocket(url);

    this.ws.onopen = () => console.log("[cowork] ws open", url);
    this.ws.onmessage = (ev) => {
      try {
        const adkEvent: AdkEvent = JSON.parse(ev.data);
        this.eventHandler?.(adkEvent);
      } catch {
        /* ignore */
      }
    };
    this.ws.onerror = () => {
      this.eventHandler?.({
        author: "cowork-client",
        errorCode: "WS_ERROR",
        errorMessage: "WebSocket error",
        turnComplete: true,
      });
    };
    this.ws.onclose = () => {
      this.ws = null;
    };
  }

  disconnect(): void {
    if (this.es) {
      this.es.close();
      this.es = null;
    }
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
    this.eventHandler = null;
  }
}
