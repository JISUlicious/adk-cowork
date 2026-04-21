/**
 * Client-side "last-seen" tracker for files in the Canvas pane.
 *
 * The agent can mutate files outside the user's attention — a turn
 * writes ``scratch/draft.md`` while the user is reading the chat. To
 * surface that, we compare the server-reported ``st_mtime`` against a
 * locally-stored "last time the user opened this file" entry. If the
 * file's mtime is newer, we render a small dot next to its name.
 *
 * Storage is plain ``localStorage`` — single-tab-local, which is
 * fine for a read-status hint. Keys are namespaced by the *scope*
 * the file lives in (managed ``projects/<slug>`` or local workdir)
 * so the same path in two different scopes doesn't collide.
 *
 * No React. Callers read through ``isUpdated`` in render and call
 * ``markSeen`` when the user actually opens the file.
 */

const KEY_PREFIX = "cowork:fileseen:";

const storageKey = (fileKey: string): string => `${KEY_PREFIX}${fileKey}`;

/** True when ``mtime`` is strictly newer than the stored "last-seen"
 *  timestamp for this file. Unknown mtimes and never-seen files both
 *  return false — we only flag real forward motion.
 *
 *  ``fileKey`` is the caller's stable identity string. For Canvas
 *  files we pass ``CanvasFile.id`` which already encodes the scope
 *  (managed project slug or local workdir) and the file path. */
export function isUpdated(
  fileKey: string,
  mtime: number | null | undefined,
): boolean {
  if (typeof window === "undefined") return false;
  if (mtime == null) return false;
  try {
    const raw = window.localStorage.getItem(storageKey(fileKey));
    if (!raw) return false;
    const last = Number(raw);
    if (!Number.isFinite(last)) return false;
    return mtime > last;
  } catch {
    return false;
  }
}

/** Record the file's current mtime as "seen". Call when the user
 *  opens the file or activates its tab. No-op when mtime is null. */
export function markSeen(
  fileKey: string,
  mtime: number | null | undefined,
): void {
  if (typeof window === "undefined") return;
  if (mtime == null) return;
  try {
    window.localStorage.setItem(storageKey(fileKey), String(mtime));
  } catch {
    /* ignore quota / privacy-mode failures */
  }
}
