import { useCallback, useEffect, useState } from "react";
import { CoworkClient } from "../transport/client";
import type { ProjectInfo, SessionListItem } from "../transport/types";

interface Props {
  client: CoworkClient;
  project: string | null;
  sessionId: string | null;
  onSelectProject: (slug: string) => void;
  onSelectSession: (sessionId: string) => void;
  onNewSession: () => void;
}

export function TopBar({
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
  const [policyMode, setPolicyMode] = useState("work");

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
    client.getPolicyMode().then(setPolicyMode).catch(() => {});
  }, [refreshProjects, client]);

  useEffect(() => {
    refreshSessions();
  }, [refreshSessions]);

  // Refresh session list when a new session is created (sessionId changes)
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

  return (
    <div className="flex items-center gap-3 px-4 py-2 border-b border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900">
      <span className="font-semibold text-sm">Cowork</span>
      <span className="text-gray-300 dark:text-gray-600">|</span>

      {/* Project selector */}
      <select
        value={project || ""}
        onChange={(e) => e.target.value && onSelectProject(e.target.value)}
        className="text-sm px-2 py-1 rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800"
      >
        <option value="">Select project...</option>
        {projects.map((p) => (
          <option key={p.slug} value={p.slug}>
            {p.name}
          </option>
        ))}
      </select>

      {/* New project */}
      <input
        type="text"
        value={newName}
        onChange={(e) => setNewName(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && handleCreate()}
        placeholder="New project..."
        className="text-sm px-2 py-1 rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 w-36"
      />
      <button
        onClick={handleCreate}
        disabled={creating || !newName.trim()}
        className="text-xs px-3 py-1 rounded bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50"
      >
        +
      </button>
      {createError && (
        <span
          className="text-xs text-red-600 dark:text-red-400 truncate max-w-48"
          title={createError}
        >
          {createError}
        </span>
      )}

      {/* Session selector */}
      {project && (
        <>
          <span className="text-gray-300 dark:text-gray-600">|</span>
          <select
            value={sessionId || ""}
            onChange={(e) => e.target.value && onSelectSession(e.target.value)}
            className="text-sm px-2 py-1 rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 max-w-48"
          >
            <option value="">
              {sessions.length === 0
                ? "No sessions"
                : `${sessions.length} session${sessions.length !== 1 ? "s" : ""}...`}
            </option>
            {sessions.map((s) => (
              <option key={s.id} value={s.id}>
                {sessionLabel(s)}
                {s.id === sessionId ? " (active)" : ""}
              </option>
            ))}
          </select>
          <button
            onClick={onNewSession}
            className="text-xs px-3 py-1 rounded bg-gray-200 dark:bg-gray-700 hover:bg-gray-300 dark:hover:bg-gray-600"
            title="Start a new session"
          >
            + Session
          </button>
        </>
      )}

      {/* Policy mode switcher */}
      <span className="text-gray-300 dark:text-gray-600 ml-auto">|</span>
      <select
        value={policyMode}
        onChange={async (e) => {
          const mode = e.target.value;
          try {
            const confirmed = await client.setPolicyMode(mode);
            setPolicyMode(confirmed);
          } catch {
            /* revert on failure */
          }
        }}
        className={`text-xs px-2 py-1 rounded border font-medium ${
          policyMode === "plan"
            ? "border-blue-400 bg-blue-50 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300 dark:border-blue-600"
            : policyMode === "auto"
              ? "border-amber-400 bg-amber-50 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300 dark:border-amber-600"
              : "border-green-400 bg-green-50 text-green-700 dark:bg-green-900/30 dark:text-green-300 dark:border-green-600"
        }`}
        title="Policy mode: plan (read-only), work (confirm destructive), auto (allowlist only)"
      >
        <option value="plan">Plan</option>
        <option value="work">Work</option>
        <option value="auto">Auto</option>
      </select>
    </div>
  );
}
