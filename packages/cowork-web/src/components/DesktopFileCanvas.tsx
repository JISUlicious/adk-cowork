/**
 * Right-panel file browser for desktop (local-dir) sessions.
 *
 * Shows the contents of ``workdir`` as a flat list (with a breadcrumb
 * for navigation up/down), and a text preview pane for selected files.
 * Not a full file manager — no rename/delete/create — the agent does
 * those via fs tools. This panel exists so the user can see what the
 * agent sees.
 *
 * Managed-mode sessions use ``FileCanvas`` (project API) instead; this
 * component is only mounted when the app is in desktop mode with a
 * workdir selected.
 */

import { useCallback, useEffect, useState } from "react";
import { ChevronRight, ChevronDown, FileText, Folder, RefreshCw } from "lucide-react";
import { CoworkClient } from "../transport/client";

interface Entry {
  name: string;
  kind: "dir" | "file";
  size: number | null;
}

interface Props {
  client: CoworkClient;
  workdir: string | null;
  sessionId: string | null;
}

export function DesktopFileCanvas({ client, workdir, sessionId }: Props) {
  const [cwd, setCwd] = useState("."); // relative to workdir
  const [entries, setEntries] = useState<Entry[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [content, setContent] = useState<string | null>(null);
  const [contentTruncated, setContentTruncated] = useState(false);
  const [loading, setLoading] = useState(false);
  const [listOpen, setListOpen] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!workdir) return;
    setLoading(true);
    setError(null);
    try {
      const data = await client.listLocalFiles(workdir, cwd);
      setEntries(data.entries);
    } catch (e) {
      setError(String(e));
      setEntries([]);
    } finally {
      setLoading(false);
    }
  }, [client, workdir, cwd]);

  // Reset state when the workdir or session changes.
  useEffect(() => {
    setCwd(".");
    setSelected(null);
    setContent(null);
  }, [workdir, sessionId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // Poll for changes while a session is active — the agent may be
  // writing files under the workdir.
  useEffect(() => {
    if (!sessionId) return;
    const id = setInterval(refresh, 3000);
    return () => clearInterval(id);
  }, [refresh, sessionId]);

  const loadFile = async (relPath: string) => {
    if (!workdir) return;
    setSelected(relPath);
    setContent(null);
    try {
      const data = await client.readLocalFile(workdir, relPath);
      setContent(data.content);
      setContentTruncated(data.truncated);
    } catch (e) {
      setError(String(e));
    }
  };

  const goInto = (dirName: string) => {
    setCwd(cwd === "." ? dirName : `${cwd}/${dirName}`);
    setSelected(null);
    setContent(null);
  };

  const goUp = () => {
    if (cwd === ".") return;
    const parts = cwd.split("/");
    parts.pop();
    setCwd(parts.length === 0 ? "." : parts.join("/"));
    setSelected(null);
    setContent(null);
  };

  if (!workdir) {
    return (
      <div className="flex items-center justify-center h-full text-[var(--dls-text-secondary)] text-sm">
        Pick a folder to view files.
      </div>
    );
  }

  const showUpLink = cwd !== ".";

  return (
    <div className="flex flex-col h-full">
      {/* File list */}
      <div
        className="border-b border-[var(--dls-border)] flex flex-col"
        style={{ maxHeight: listOpen ? "50%" : "auto" }}
      >
        <div className="flex items-center justify-between px-3 py-2 shrink-0">
          <button
            type="button"
            className="flex items-center gap-1.5 text-xs font-semibold text-[var(--dls-text-secondary)] uppercase tracking-wide hover:text-[var(--dls-text-primary)] transition-colors min-w-0"
            onClick={() => setListOpen((v) => !v)}
            title={cwd}
          >
            {listOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
            <span className="truncate">Files · {cwd === "." ? "/" : cwd}</span>
          </button>
          <button
            type="button"
            onClick={refresh}
            disabled={loading}
            className="text-[var(--dls-text-secondary)] hover:text-[var(--dls-text-primary)] disabled:opacity-40 transition-colors"
            title="Refresh"
          >
            <RefreshCw size={12} className={loading ? "animate-spin" : ""} />
          </button>
        </div>
        {listOpen && (
          <div className="overflow-y-auto">
            {showUpLink && (
              <button
                type="button"
                onClick={goUp}
                className="w-full text-left px-3 py-1.5 text-xs flex items-center gap-2 text-[var(--dls-text-secondary)] hover:bg-[var(--dls-hover)] transition-colors"
              >
                <span>..</span>
              </button>
            )}
            {error && (
              <div className="px-3 py-2 text-[11px] text-red-500">{error}</div>
            )}
            {!error && entries.length === 0 && !loading && (
              <div className="px-3 py-3 text-xs text-[var(--dls-text-secondary)]">
                Empty folder.
              </div>
            )}
            {entries.map((e) => {
              const fullPath = cwd === "." ? e.name : `${cwd}/${e.name}`;
              const isActive = selected === fullPath;
              return (
                <button
                  key={e.name}
                  type="button"
                  onClick={() => (e.kind === "dir" ? goInto(e.name) : loadFile(fullPath))}
                  className={`w-full text-left px-3 py-1.5 text-xs flex items-center gap-2 transition-colors ${
                    isActive
                      ? "bg-[rgba(var(--dls-accent-rgb),0.08)] text-[var(--dls-accent)]"
                      : "hover:bg-[var(--dls-hover)]"
                  }`}
                >
                  <span className="text-[var(--dls-text-secondary)] shrink-0">
                    {e.kind === "dir" ? <Folder size={12} /> : <FileText size={12} />}
                  </span>
                  <span className="truncate min-w-0 flex-1">{e.name}</span>
                  {e.kind === "file" && typeof e.size === "number" && (
                    <span className="text-[10px] text-[var(--dls-text-secondary)] shrink-0">
                      {formatSize(e.size)}
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        )}
      </div>

      {/* Preview pane */}
      <div className="flex-1 overflow-auto">
        {selected && content !== null ? (
          <div className="flex flex-col h-full">
            <div className="px-3 py-2 border-b border-[var(--dls-border)] text-xs text-[var(--dls-text-secondary)] truncate" title={selected}>
              {selected}
              {contentTruncated && (
                <span className="ml-2 text-[10px] text-amber-500">
                  (truncated at 2 MB)
                </span>
              )}
            </div>
            <pre className="flex-1 overflow-auto whitespace-pre-wrap break-all p-3 text-[11px] font-mono text-[var(--dls-text-primary)]">
              {content}
            </pre>
          </div>
        ) : (
          <div className="flex items-center justify-center h-full text-[var(--dls-text-secondary)] text-sm">
            Select a file to preview.
          </div>
        )}
      </div>
    </div>
  );
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
