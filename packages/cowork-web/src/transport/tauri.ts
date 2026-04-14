/**
 * Bridge between the web UI and the Tauri native shell.
 *
 * When running inside Tauri, the Rust sidecar spawns cowork-server on a
 * random port and publishes the URL + token via `invoke("get_server")`.
 * When running in a plain browser, this module is a no-op — the caller
 * falls back to Vite's dev proxy + build-injected token.
 */

export interface ServerInfo {
  url: string;
  token: string;
}

export function isTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

export async function getServerFromTauri(): Promise<ServerInfo | null> {
  if (!isTauri()) return null;
  const { invoke } = await import("@tauri-apps/api/core");
  // Retry briefly in case the webview loads before the sidecar handshake lands.
  for (let attempt = 0; attempt < 20; attempt++) {
    try {
      return await invoke<ServerInfo>("get_server");
    } catch {
      await new Promise((r) => setTimeout(r, 250));
    }
  }
  return null;
}

export type DropHandler = (paths: string[]) => void;

/** Subscribe to native file-drop events. Returns an unlisten fn; no-op in browser mode. */
export async function onFileDrop(handler: DropHandler): Promise<() => void> {
  if (!isTauri()) return () => {};
  const { getCurrentWebview } = await import("@tauri-apps/api/webview");
  const webview = getCurrentWebview();
  const unlisten = await webview.onDragDropEvent((event) => {
    if (event.payload.type === "drop") {
      handler(event.payload.paths.map((p) => String(p)));
    }
  });
  return unlisten;
}

/** Fire an OS notification via the Web Notification API (works inside Tauri's webview). */
export async function notify(title: string, body: string): Promise<void> {
  if (typeof Notification === "undefined") return;
  try {
    if (Notification.permission === "default") {
      await Notification.requestPermission();
    }
    if (Notification.permission === "granted") {
      new Notification(title, { body });
    }
  } catch {
    /* ignore */
  }
}

/** Open the cowork workspace directory in the OS file manager. */
export async function openWorkspaceInFileManager(): Promise<void> {
  if (!isTauri()) return;
  const { invoke } = await import("@tauri-apps/api/core");
  await invoke("open_workspace");
}
