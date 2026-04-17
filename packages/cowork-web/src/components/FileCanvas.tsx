import { useCallback, useEffect, useState } from "react";
import { CoworkClient } from "../transport/client";
import type { FileEntry } from "../transport/types";
import { FileViewer } from "./FileViewer";

interface Props {
  client: CoworkClient;
  project: string | null;
  sessionId: string | null;
}

type FileNode = FileEntry & { fullPath: string; scope: "files" | "scratch" };

export function FileCanvas({ client, project, sessionId }: Props) {
  const [files, setFiles] = useState<FileNode[]>([]);
  const [selected, setSelected] = useState<FileNode | null>(null);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    if (!project) return;
    setLoading(true);
    try {
      const [projectFiles, scratchFiles] = await Promise.all([
        client
          .listFiles(project, "files")
          .then((entries) =>
            entries.map((e) => ({
              ...e,
              fullPath: `files/${e.name}`,
              scope: "files" as const,
            })),
          )
          .catch(() => [] as FileNode[]),
        sessionId
          ? client
              .listFiles(project, `sessions/${sessionId}/scratch`)
              .then((entries) =>
                entries.map((e) => ({
                  ...e,
                  fullPath: `sessions/${sessionId}/scratch/${e.name}`,
                  scope: "scratch" as const,
                })),
              )
              .catch(() => [] as FileNode[])
          : Promise.resolve([] as FileNode[]),
      ]);
      setFiles([...projectFiles, ...scratchFiles]);
    } finally {
      setLoading(false);
    }
  }, [client, project, sessionId]);

  // Clear selection when project or session changes
  useEffect(() => {
    setSelected(null);
    setFiles([]);
  }, [project, sessionId]);

  // Poll for file changes while a session is active
  useEffect(() => {
    refresh();
    if (!sessionId) return;
    const id = setInterval(refresh, 3000);
    return () => clearInterval(id);
  }, [refresh, sessionId]);

  if (!project) {
    return (
      <div className="flex items-center justify-center h-full text-[var(--dls-text-secondary)] text-sm">
        Select a project to view files.
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {/* File tree */}
      <div className="border-b border-[var(--dls-border)] overflow-y-auto max-h-[40%]">
        <div className="flex items-center justify-between px-3 py-2 border-b border-[var(--dls-border)]">
          <span className="text-xs font-semibold text-[var(--dls-text-secondary)] uppercase tracking-wide">
            Files
          </span>
          <button
            onClick={refresh}
            className="text-xs text-[var(--dls-text-secondary)] hover:text-[var(--dls-text-primary)]"
            title="Refresh"
          >
            {loading ? "..." : "\u21bb"}
          </button>
        </div>
        {files.length === 0 && (
          <div className="px-3 py-4 text-xs text-[var(--dls-text-secondary)]">No files yet.</div>
        )}
        {files.map((f) => (
          <button
            key={f.fullPath}
            onClick={() => setSelected(f)}
            className={`w-full text-left px-3 py-1.5 text-xs hover:bg-[var(--dls-hover)] flex items-center gap-2 ${
              selected?.fullPath === f.fullPath
                ? "bg-[rgba(var(--dls-accent-rgb),0.08)] text-[var(--dls-accent)]"
                : ""
            }`}
          >
            <span className="text-[var(--dls-text-secondary)]">
              {f.kind === "dir" ? "\ud83d\udcc1" : "\ud83d\udcc4"}
            </span>
            <span className="truncate">{f.name}</span>
            <span className="ml-auto text-[10px] text-[var(--dls-text-secondary)]">
              {f.scope === "scratch" ? "scratch" : "project"}
            </span>
          </button>
        ))}
      </div>

      {/* Viewer */}
      <div className="flex-1 overflow-auto">
        {selected ? (
          <FileViewer
            client={client}
            project={project}
            path={selected.fullPath}
            name={selected.name}
          />
        ) : (
          <div className="flex items-center justify-center h-full text-[var(--dls-text-secondary)] text-sm">
            Select a file to preview.
          </div>
        )}
      </div>
    </div>
  );
}
