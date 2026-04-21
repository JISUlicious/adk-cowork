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

/** Native folder picker. Returns absolute path or ``null`` if cancelled. */
export async function pickWorkdir(): Promise<string | null> {
  if (!isTauri()) return null;
  const { invoke } = await import("@tauri-apps/api/core");
  try {
    return (await invoke<string | null>("pick_workdir")) ?? null;
  } catch {
    return null;
  }
}

/** Last-picked workdir remembered for this launch (in-memory on the Rust side). */
export async function getRecentWorkdir(): Promise<string | null> {
  if (!isTauri()) return null;
  const { invoke } = await import("@tauri-apps/api/core");
  try {
    return (await invoke<string | null>("recent_workdir")) ?? null;
  } catch {
    return null;
  }
}

export async function setRecentWorkdir(path: string): Promise<void> {
  if (!isTauri()) return;
  const { invoke } = await import("@tauri-apps/api/core");
  try {
    await invoke("set_recent_workdir", { path });
  } catch {
    /* ignore */
  }
}

/** Native multi-file picker for composer attachments. Returns the list
 *  of absolute paths the user selected, or an empty list if cancelled
 *  or not in Tauri. */
export async function pickFiles(): Promise<string[]> {
  if (!isTauri()) return [];
  const { invoke } = await import("@tauri-apps/api/core");
  try {
    return (await invoke<string[]>("pick_files")) ?? [];
  } catch {
    return [];
  }
}

/** Read the raw bytes of a local absolute path. Wraps the Rust
 *  ``read_dropped_file`` command so the composer's attach flow can reuse
 *  the same plumbing as native file-drop in managed mode. */
export async function readLocalFileBytes(path: string): Promise<Uint8Array> {
  if (!isTauri()) throw new Error("readLocalFileBytes: not in Tauri");
  const { invoke } = await import("@tauri-apps/api/core");
  const bytes = await invoke<number[]>("read_dropped_file", { path });
  return new Uint8Array(bytes);
}

/** Copy a dropped file into the current workdir (desktop mode).
 *  Returns the destination absolute path, or throws. */
export async function copyIntoWorkdir(
  src: string,
  workdir: string,
): Promise<string> {
  if (!isTauri()) throw new Error("copyIntoWorkdir: not in Tauri");
  const { invoke } = await import("@tauri-apps/api/core");
  return invoke<string>("copy_into_workdir", { src, workdir });
}
