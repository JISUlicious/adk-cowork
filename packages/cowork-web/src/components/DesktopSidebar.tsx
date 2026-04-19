import { useCallback, useEffect, useState } from "react";
import { CoworkClient } from "../transport/client";
import { FolderOpen, Folder, MessageSquarePlus, Trash2 } from "lucide-react";

interface LocalSession {
  id: string;
  created_at: string;
  title: string | null;
}

interface Props {
  client: CoworkClient;
  workdir: string | null;
  sessionId: string | null;
  onPickWorkdir: () => void;
  onSelectSession: (sessionId: string) => void;
  onNewSession: () => void;
  onDeleteSession: (sessionId: string) => Promise<void>;
}

export function DesktopSidebar({
  client,
  workdir,
  sessionId,
  onPickWorkdir,
  onSelectSession,
  onNewSession,
  onDeleteSession,
}: Props) {
  const [sessions, setSessions] = useState<LocalSession[]>([]);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!workdir) {
      setSessions([]);
      return;
    }
    try {
      setSessions(await client.listLocalSessions(workdir));
    } catch {
      setSessions([]);
    }
  }, [client, workdir]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    if (sessionId && workdir) refresh();
  }, [sessionId, workdir, refresh]);

  const sessionLabel = (s: LocalSession, idx: number) => {
    if (s.title) return s.title;
    if (s.created_at) {
      const d = new Date(s.created_at);
      const now = new Date();
      const diffMin = Math.floor((now.getTime() - d.getTime()) / 60000);
      if (diffMin < 1) return "Just now";
      if (diffMin < 60) return `${diffMin}m ago`;
      const diffHr = Math.floor(diffMin / 60);
      if (diffHr < 24) return `${diffHr}h ago`;
      return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
    }
    return `Session ${idx + 1}`;
  };

  const folderName = workdir ? workdir.split("/").filter(Boolean).pop() : null;

  return (
    <div className="flex h-full min-h-0 min-w-0 flex-1 flex-col">
      {/* Current workdir */}
      <div className="min-w-0 border-b border-[var(--dls-border)] pb-3 mb-2">
        {workdir ? (
          <div className="flex items-center gap-2 px-2 py-1.5 rounded-xl bg-[var(--dls-active)]">
            <Folder size={14} className="text-[var(--dls-text-secondary)] shrink-0" />
            <div className="min-w-0 flex-1">
              <div className="truncate text-[13px] font-medium text-[var(--dls-text-primary)]" title={workdir}>
                {folderName}
              </div>
              <div className="truncate text-[10px] text-[var(--dls-text-secondary)]" title={workdir}>
                {workdir}
              </div>
            </div>
          </div>
        ) : (
          <div className="px-2 py-1.5 text-[12px] text-[var(--dls-text-secondary)]">
            No folder selected
          </div>
        )}
        <button
          type="button"
          onClick={onPickWorkdir}
          className="mt-2 flex w-full items-center gap-2 rounded-xl border border-[var(--dls-border)] bg-[var(--dls-surface)] px-3 py-2 text-[12px] text-[var(--dls-text-secondary)] transition-colors hover:bg-[var(--dls-hover)] hover:text-[var(--dls-text-primary)]"
        >
          <FolderOpen size={13} />
          <span>Open Folder…</span>
        </button>
      </div>

      {/* Session list */}
      <div className="min-h-0 min-w-0 flex-1 overflow-x-hidden overflow-y-auto pr-1">
        {!workdir ? (
          <div className="px-2 py-2 text-[11px] text-[var(--dls-text-secondary)]">
            Pick a folder to start.
          </div>
        ) : (
          <div className="space-y-0.5 pb-3">
            {sessions.length === 0 ? (
              <div className="px-3 py-2 text-[11px] text-[var(--dls-text-secondary)]">
                No sessions in this folder yet.
              </div>
            ) : (
              sessions.map((s, i) => {
                const isActive = s.id === sessionId;
                const isPendingDelete = confirmDeleteId === s.id;
                return (
                  <div key={s.id} className="flex flex-col">
                    <div
                      className={`group flex min-h-8 w-full items-center rounded-xl text-left text-[13px] transition-colors ${
                        isActive
                          ? "bg-[var(--dls-active)] text-[var(--dls-text-primary)] font-medium"
                          : "text-[var(--dls-text-secondary)] hover:bg-[var(--dls-hover)] hover:text-[var(--dls-text-primary)]"
                      }`}
                    >
                      <button
                        type="button"
                        className="min-w-0 flex-1 truncate px-3 py-1.5 text-left"
                        onClick={() => { setConfirmDeleteId(null); onSelectSession(s.id); }}
                      >
                        {sessionLabel(s, i)}
                      </button>
                      <button
                        type="button"
                        className="mr-1 shrink-0 rounded-md p-1 opacity-0 transition-opacity group-hover:opacity-100 text-[var(--dls-text-secondary)] hover:text-red-500"
                        title="Delete session"
                        onClick={(e) => {
                          e.stopPropagation();
                          setConfirmDeleteId(isPendingDelete ? null : s.id);
                        }}
                      >
                        <Trash2 size={12} />
                      </button>
                    </div>
                    {isPendingDelete && (
                      <div className="mx-1 mb-1 flex items-center justify-between rounded-xl bg-red-500/10 px-3 py-1.5 text-[11px]">
                        <span className="text-red-500">Delete session?</span>
                        <div className="flex gap-1">
                          <button
                            type="button"
                            className="rounded-md px-2 py-0.5 text-[var(--dls-text-secondary)] hover:bg-[var(--dls-hover)]"
                            onClick={() => setConfirmDeleteId(null)}
                          >
                            Cancel
                          </button>
                          <button
                            type="button"
                            className="rounded-md bg-red-500 px-2 py-0.5 text-white hover:bg-red-600"
                            onClick={async () => {
                              setConfirmDeleteId(null);
                              await onDeleteSession(s.id);
                              await refresh();
                            }}
                          >
                            Delete
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                );
              })
            )}
            <button
              type="button"
              className="flex w-full items-center gap-2 rounded-xl px-3 py-1.5 text-[12px] text-[var(--dls-text-secondary)] transition-colors hover:bg-[var(--dls-hover)] hover:text-[var(--dls-text-primary)]"
              onClick={onNewSession}
            >
              <MessageSquarePlus size={13} />
              <span>New session</span>
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
