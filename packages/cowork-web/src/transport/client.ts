/**
 * Typed client for the cowork /v1 protocol.
 *
 * One class, no external state libs. Surfaces call `createSession`, then
 * `sendMessage` + `onFrame` to stream events over the WebSocket.
 */

import type {
  Frame,
  HealthInfo,
  SessionInfo,
  ProjectInfo,
  SessionListItem,
  FileEntry,
} from "./types";

export type FrameHandler = (frame: Frame) => void;

export class CoworkClient {
  private baseUrl: string;
  private token: string;
  private ws: WebSocket | null = null;
  private frameHandler: FrameHandler | null = null;

  constructor(baseUrl = "", token?: string) {
    this.baseUrl = baseUrl;
    // Use injected build-time token, or explicit override
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

  async getPolicyMode(): Promise<string> {
    const r = await fetch(`${this.baseUrl}/v1/policy/mode`, {
      headers: this.headers(),
    });
    if (!r.ok) throw new Error(`getPolicyMode: ${r.status}`);
    const data = await r.json();
    return data.mode;
  }

  async setPolicyMode(mode: string): Promise<string> {
    const r = await fetch(`${this.baseUrl}/v1/policy/mode`, {
      method: "PUT",
      headers: this.headers(),
      body: JSON.stringify({ mode }),
    });
    if (!r.ok) throw new Error(`setPolicyMode: ${r.status}`);
    const data = await r.json();
    return data.mode;
  }

  async createSession(project?: string): Promise<SessionInfo> {
    const r = await fetch(`${this.baseUrl}/v1/sessions`, {
      method: "POST",
      headers: this.headers(),
      body: project ? JSON.stringify({ project }) : undefined,
    });
    if (!r.ok) throw new Error(`createSession: ${r.status}`);
    return r.json();
  }

  async resumeSession(
    sessionId: string,
    project: string,
  ): Promise<SessionInfo> {
    const r = await fetch(
      `${this.baseUrl}/v1/sessions/${sessionId}/resume`,
      {
        method: "POST",
        headers: this.headers(),
        body: JSON.stringify({ project }),
      },
    );
    if (!r.ok) throw new Error(`resumeSession: ${r.status}`);
    return r.json();
  }

  async getHistory(sessionId: string): Promise<unknown[]> {
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

  /** Upload a file (from the Tauri drag-drop bridge or an <input type=file>). */
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

  /** Connect WebSocket for a session. Calls `onFrame` for each event. */
  connect(sessionId: string, onFrame: FrameHandler): void {
    this.disconnect();
    this.frameHandler = onFrame;
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const host = this.baseUrl
      ? this.baseUrl.replace(/^https?:/, proto)
      : `${proto}//${window.location.host}`;
    const qs = this.token ? `?token=${encodeURIComponent(this.token)}` : "";
    const url = `${host}/v1/sessions/${sessionId}/events${qs}`;
    this.ws = new WebSocket(url);

    this.ws.onopen = () => console.log("[cowork] ws open", url);
    this.ws.onmessage = (ev) => {
      console.log("[cowork] ws frame", ev.data);
      try {
        const frame: Frame = JSON.parse(ev.data);
        if (frame.type === "multi") {
          for (const sub of frame.frames) {
            this.frameHandler?.(sub);
          }
        } else {
          this.frameHandler?.(frame);
        }
      } catch {
        // ignore unparseable frames
      }
    };

    this.ws.onerror = () => {
      this.frameHandler?.({ type: "error", message: "WebSocket error" });
    };

    this.ws.onclose = () => {
      this.ws = null;
    };
  }

  disconnect(): void {
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
    this.frameHandler = null;
  }
}
