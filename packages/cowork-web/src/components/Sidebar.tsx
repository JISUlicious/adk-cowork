import { useCallback, useEffect, useState } from "react";
import { CoworkClient } from "../transport/client";
import type { ProjectInfo, SessionListItem } from "../transport/types";
import { Plus, RefreshCw, MessageSquarePlus, ChevronDown, ChevronRight } from "lucide-react";

interface Props {
  client: CoworkClient;
  project: string | null;
  sessionId: string | null;
  onSelectProject: (slug: string) => void;
  onSelectSession: (sessionId: string) => void;
  onNewSession: () => void;
}

export function Sidebar({
  client,
  project,
  sessionId,
  onSelectProject,
  onSelectSession,
  onNewSession,
}: Props) {
  const [projects, setProjects] = useState<ProjectInfo[]>([]);
  const [sessions, setSessions] = useState<SessionListItem[]>([]);
  const [newName, setNewName] = useState("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [projectsExpanded, setProjectsExpanded] = useState(true);

  const refreshProjects = useCallback(async () => {
    try {
      setProjects(await client.listProjects());
    } catch {
      /* server not ready */
    }
  }, [client]);

  const refreshSessions = useCallback(async () => {
    if (!project) {
      setSessions([]);
      return;
    }
    try {
      setSessions(await client.listSessions(project));
    } catch {
      setSessions([]);
    }
  }, [client, project]);

  useEffect(() => {
    refreshProjects();
  }, [refreshProjects]);

  useEffect(() => {
    refreshSessions();
  }, [refreshSessions]);

  useEffect(() => {
    if (sessionId && project) refreshSessions();
  }, [sessionId, project, refreshSessions]);

  const handleCreate = async () => {
    if (!newName.trim()) return;
    setCreating(true);
    setCreateError(null);
    try {
      const p = await client.createProject(newName.trim());
      setNewName("");
      await refreshProjects();
      onSelectProject(p.slug);
    } catch (e) {
      setCreateError(String(e));
    } finally {
      setCreating(false);
    }
  };

  const sessionLabel = (s: SessionListItem) => {
    if (s.title) return s.title;
    const date = s.created_at
      ? new Date(s.created_at).toLocaleString(undefined, {
          month: "short",
          day: "numeric",
          hour: "2-digit",
          minute: "2-digit",
        })
      : s.id.slice(0, 8);
    return date;
  };

  const selectedProject = projects.find((p) => p.slug === project);

  return (
    <div className="flex h-full min-h-0 min-w-0 flex-1 flex-col">
      {/* Project list */}
      <div className="min-h-0 min-w-0 flex-1 overflow-x-hidden overflow-y-auto pr-1">
        <div className="space-y-1 pb-3">
          {projects.map((p) => {
            const isSelected = p.slug === project;
            return (
              <div key={p.slug}>
                <button
                  type="button"
                  className={`group flex min-h-9 w-full items-center justify-between rounded-xl px-3 py-2 text-left text-[13px] transition-colors ${
                    isSelected
                      ? "bg-[var(--dls-active)] text-[var(--dls-text-primary)]"
                      : "text-[var(--dls-text-secondary)] hover:bg-[var(--dls-hover)] hover:text-[var(--dls-text-primary)]"
                  }`}
                  onClick={() => onSelectProject(p.slug)}
                >
                  <div className="flex min-w-0 items-center gap-3">
                    <div
                      className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-white text-[10px] font-bold"
                      style={{
                        backgroundColor: projectSwatchColor(p.slug),
                      }}
                    >
                      {p.name.charAt(0).toUpperCase()}
                    </div>
                    <span className="min-w-0 truncate text-[14px]">
                      {p.name}
                    </span>
                  </div>
                  {isSelected && (
                    <button
                      type="button"
                      className="rounded-md p-1 text-[var(--dls-text-secondary)] hover:bg-[var(--dls-hover)] hover:text-[var(--dls-text-primary)]"
                      onClick={(e) => {
                        e.stopPropagation();
                        setProjectsExpanded((v) => !v);
                      }}
                    >
                      {projectsExpanded ? (
                        <ChevronDown size={14} />
                      ) : (
                        <ChevronRight size={14} />
                      )}
                    </button>
                  )}
                </button>

                {/* Sessions under selected project */}
                {isSelected && projectsExpanded && (
                  <div className="mt-1 px-1 pb-1">
                    <div className="relative flex flex-col gap-0.5 pl-2.5 before:absolute before:bottom-2 before:left-0 before:top-2 before:w-[2px] before:rounded-full before:bg-[var(--dls-border)] before:content-['']">
                      {sessions.length === 0 ? (
                        <div className="rounded-xl px-3 py-2 text-[11px] text-[var(--dls-text-secondary)]">
                          No sessions yet
                        </div>
                      ) : (
                        sessions.map((s) => {
                          const isActive = s.id === sessionId;
                          return (
                            <button
                              key={s.id}
                              type="button"
                              className={`group flex min-h-8 w-full items-center rounded-xl px-3 py-1.5 text-left text-[13px] transition-colors ${
                                isActive
                                  ? "bg-[var(--dls-active)] text-[var(--dls-text-primary)] font-medium"
                                  : "text-[var(--dls-text-secondary)] hover:bg-[var(--dls-hover)] hover:text-[var(--dls-text-primary)]"
                              }`}
                              onClick={() => onSelectSession(s.id)}
                            >
                              <span className="min-w-0 truncate">
                                {sessionLabel(s)}
                              </span>
                            </button>
                          );
                        })
                      )}
                      <button
                        type="button"
                        className="flex items-center gap-2 rounded-xl px-3 py-1.5 text-[12px] text-[var(--dls-text-secondary)] transition-colors hover:bg-[var(--dls-hover)] hover:text-[var(--dls-text-primary)]"
                        onClick={onNewSession}
                      >
                        <MessageSquarePlus size={13} />
                        <span>New session</span>
                      </button>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* New project */}
      <div className="relative mt-auto border-t border-[var(--dls-border)] pt-3">
        <div className="flex items-center gap-1.5">
          <input
            type="text"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleCreate()}
            placeholder="New project..."
            className="flex-1 min-w-0 rounded-xl border border-[var(--dls-border)] bg-[var(--dls-app-bg)] px-3 py-2 text-[12px] text-[var(--dls-text-primary)] placeholder:text-[var(--dls-text-secondary)] focus:outline-none focus:ring-2 focus:ring-[rgba(var(--dls-accent-rgb),0.3)]"
          />
          <button
            type="button"
            onClick={handleCreate}
            disabled={creating || !newName.trim()}
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-[var(--dls-border)] bg-[var(--dls-surface)] text-[var(--dls-text-secondary)] shadow-[var(--dls-card-shadow)] transition-colors hover:bg-[var(--dls-hover)] hover:text-[var(--dls-text-primary)] disabled:opacity-50"
            title="Create project"
          >
            <Plus size={14} />
          </button>
        </div>
        {createError && (
          <div className="mt-1 text-[11px] text-red-500 truncate" title={createError}>
            {createError}
          </div>
        )}
      </div>
    </div>
  );
}

const PROJECT_SWATCHES = ["#2563eb", "#5a67d8", "#f97316", "#10b981", "#ef4444", "#8b5cf6"];

function projectSwatchColor(seed: string) {
  const value = seed.trim() || "project";
  let hash = 0;
  for (let i = 0; i < value.length; i++) {
    hash = (hash << 5) - hash + value.charCodeAt(i);
    hash |= 0;
  }
  return PROJECT_SWATCHES[Math.abs(hash) % PROJECT_SWATCHES.length];
}
