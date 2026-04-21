/**
 * Sessions pane — unified across managed and local-dir surfaces.
 *
 * Renders the design's project-grouped sidebar (collapsible heading,
 * status-dot rows, search, user footer). Local-dir mode synthesizes
 * a single project group named after the workdir basename so the
 * visual structure stays uniform.
 *
 * Each row: status dot (running / waiting / done) + title + a single
 * meta line ("N msgs · M files · 5m ago") + pin + delete. The
 * per-session agent monogram stack was dropped because the agent
 * identity is already carried by the chat-pane header; the sidebar
 * only needs to answer "which sessions have life in them".
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { CoworkClient } from "../transport/client";
import type { ProjectInfo, SessionListItem } from "../transport/types";
import { Icon } from "./atoms";

interface BaseProps {
  client: CoworkClient;
  sessionId: string | null;
  /** Session ids with a turn currently in flight. A session row renders
   *  the accent ``running`` dot whenever its id is in this set,
   *  regardless of whether it's the currently-selected session. */
  sendingIds: Set<string>;
  /** Session ids stalled on an unresolved ``confirmation_required``
   *  tool call. Derived client-side from ``useChat`` — a session is
   *  waiting only when it's not also running. */
  waitingIds: Set<string>;
  /** User identity for the footer; ``undefined`` falls back to "local". */
  userId?: string;
  onSelectSession: (sessionId: string) => void;
  onNewSession: () => void;
  onDeleteSession: (sessionId: string) => Promise<void>;
  onOpenSettings?: () => void;
  onOpenPalette?: () => void;
}

interface ManagedProps extends BaseProps {
  mode: "managed";
  project: string | null;
  onSelectProject: (slug: string) => void;
  onDeleteProject: (slug: string) => Promise<void>;
}

interface LocalProps extends BaseProps {
  mode: "local";
  workdir: string | null;
  onPickWorkdir: () => void;
}

export type SessionsProps = ManagedProps | LocalProps;

interface SessionStats {
  messages: number;
  /** Managed mode only — session's scratch/ file count. ``null`` for
   *  local-dir sessions where there's no artifact concept distinct
   *  from workdir files. */
  artifacts: number | null;
}

export function Sessions(props: SessionsProps) {
  const [q, setQ] = useState("");
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  // Per-session stats cache. Populated lazily when the user selects a
  // session (one history fetch + one file-listing call). Invalidated
  // on the ``sendingIds: true → false`` transition so counts pick up
  // the work the turn just did; if the session was already cached,
  // that transition also refetches immediately.
  const [statsBySession, setStatsBySession] = useState<Record<string, SessionStats>>({});
  const prevSendingIdsRef = useRef<Set<string>>(new Set());

  const { groups, refresh: refreshGroups } = useGroups(props);

  const computeStats = useCallback(
    async (sid: string): Promise<SessionStats | null> => {
      try {
        const events = await props.client.getHistory(sid);
        // Count only events that carry actual text content — skips
        // function-call / function-response / empty system events so
        // the number matches what the user sees in the chat pane.
        const messages = events.filter((ev) => {
          const parts = ev.content?.parts ?? [];
          return parts.some((p) => typeof p.text === "string" && p.text);
        }).length;

        let artifacts: number | null = null;
        if (props.mode === "managed" && props.project) {
          try {
            const files = await props.client.listFiles(
              props.project,
              `sessions/${sid}/scratch`,
            );
            artifacts = files.length;
          } catch {
            // 404 when scratch dir hasn't been created yet — treat as 0.
            artifacts = 0;
          }
        }
        return { messages, artifacts };
      } catch {
        return null;
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [props.client, props.mode, (props as ManagedProps).project],
  );

  const loadStats = useCallback(
    async (sid: string, { force = false } = {}) => {
      if (!force && statsBySession[sid]) return;
      const stats = await computeStats(sid);
      if (stats) {
        setStatsBySession((prev) => ({ ...prev, [sid]: stats }));
      }
    },
    [computeStats, statsBySession],
  );

  // Invalidate + refetch stats when a session's turn finishes.
  // ``sendingIds`` transitioning ``true → false`` means new messages /
  // files have landed, so any cached stats for that session are stale.
  useEffect(() => {
    const prev = prevSendingIdsRef.current;
    const now = props.sendingIds;
    const finished: string[] = [];
    for (const sid of prev) {
      if (!now.has(sid)) finished.push(sid);
    }
    prevSendingIdsRef.current = new Set(now);
    if (finished.length === 0) return;
    setStatsBySession((prevStats) => {
      const next = { ...prevStats };
      for (const sid of finished) delete next[sid];
      return next;
    });
    for (const sid of finished) {
      void loadStats(sid, { force: true });
    }
  }, [props.sendingIds, loadStats]);

  // Kick off stats for the active session once it's set.
  useEffect(() => {
    if (props.sessionId) void loadStats(props.sessionId);
  }, [props.sessionId, loadStats]);

  const togglePinned = useCallback(
    async (sid: string, currentlyPinned: boolean) => {
      const pinned = !currentlyPinned;
      try {
        if (props.mode === "managed") {
          if (!props.project) return;
          await props.client.patchSession(props.project, sid, { pinned });
        } else {
          if (!props.workdir) return;
          await props.client.patchLocalSession(props.workdir, sid, { pinned });
        }
        await refreshGroups();
      } catch (e) {
        console.error("[cowork] toggle pinned failed:", e);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [
      props.mode,
      props.client,
      (props as ManagedProps).project,
      (props as LocalProps).workdir,
      refreshGroups,
    ],
  );

  const visibleGroups = useMemo(
    () =>
      groups
        .map((g) => ({
          ...g,
          sessions: g.sessions
            .filter((s) =>
              !q || (s.title ?? s.id).toLowerCase().includes(q.toLowerCase()),
            )
            // Pinned sessions float to the top of each group; within
            // each bucket preserve the existing (newest-first) order
            // the server / group-builder provided.
            .slice()
            .sort((a, b) => {
              const ap = a.pinned ? 1 : 0;
              const bp = b.pinned ? 1 : 0;
              return bp - ap;
            }),
        }))
        .filter((g) => !q || g.sessions.length),
    [groups, q],
  );

  const headerTitle = props.mode === "managed" ? "Sessions" : "Workspace";
  const handlePlus = () => {
    if (props.mode === "local" && !props.workdir) {
      props.onPickWorkdir();
      return;
    }
    props.onNewSession();
  };

  return (
    <div className="pane sessions" style={{ height: "100%", display: "flex", flexDirection: "column" }}>
      <div className="sessions-head">
        <div className="title">{headerTitle}</div>
        <button className="plus" type="button" title="New session" onClick={handlePlus}>
          +
        </button>
      </div>
      <div className="search">
        <Icon name="search" size={13} />
        <input
          placeholder="Search…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          style={{ minWidth: 0 }}
        />
        <button
          type="button"
          className="kbd"
          title="Open command palette"
          onClick={props.onOpenPalette}
          style={{ flexShrink: 0, cursor: props.onOpenPalette ? "pointer" : "default" }}
        >
          ⌘K
        </button>
      </div>

      <div style={{ flex: 1, overflowY: "auto", minHeight: 0 }}>
        {props.mode === "local" && !("workdir" in props && props.workdir) ? (
          <EmptyHint
            label="No folder open"
            action={{ label: "Open Folder…", onClick: () => (props as LocalProps).onPickWorkdir() }}
          />
        ) : visibleGroups.length === 0 ? (
          <EmptyHint label={q ? "No matches" : "No sessions yet"} />
        ) : (
          visibleGroups.map((g) => {
            const isCollapsed = collapsed[g.id] ?? false;
            return (
              <div key={g.id} className="proj">
                <div
                  className={`proj-head ${isCollapsed ? "collapsed" : ""}`}
                  onClick={() => setCollapsed((s) => ({ ...s, [g.id]: !s[g.id] }))}
                  style={{ cursor: "pointer" }}
                >
                  <span className="chev">
                    <Icon name="chevD" size={10} />
                  </span>
                  <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis" }}>
                    {g.name}
                  </span>
                  <span className="count" style={{ flexShrink: 0 }}>{g.sessions.length}</span>
                  {g.onSelect && (
                    <button
                      type="button"
                      title="Switch to this project"
                      onClick={(e) => {
                        e.stopPropagation();
                        g.onSelect?.();
                      }}
                      style={selectBtnStyle(Boolean(g.isSelected))}
                    >
                      {g.isSelected ? "•" : "›"}
                    </button>
                  )}
                  {g.onDelete && (
                    <button
                      type="button"
                      title="Delete project"
                      onClick={(e) => {
                        e.stopPropagation();
                        if (window.confirm(`Delete project "${g.name}" and all files?`)) {
                          void g.onDelete?.();
                        }
                      }}
                      style={trashBtnStyle()}
                    >
                      ×
                    </button>
                  )}
                </div>
                {g.sub && !isCollapsed && (
                  <div
                    style={{
                      padding: "2px 12px 6px 24px",
                      fontFamily: "var(--mono)",
                      fontSize: 10,
                      color: "var(--ink-4)",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                    title={g.sub}
                  >
                    {g.sub}
                  </div>
                )}
                {!isCollapsed &&
                  g.sessions.map((s) => {
                    const isActive = s.id === props.sessionId;
                    const isRunning = props.sendingIds.has(s.id);
                    const isWaiting = !isRunning && props.waitingIds.has(s.id);
                    const status: "running" | "waiting" | "done" = isRunning
                      ? "running"
                      : isWaiting
                        ? "waiting"
                        : "done";
                    const isPendingDelete = confirmDeleteId === s.id;
                    const stats = statsBySession[s.id];
                    return (
                      <div key={s.id}>
                        <div
                          className={`sess ${isActive ? "active" : ""}`}
                          onClick={() => {
                            setConfirmDeleteId(null);
                            props.onSelectSession(s.id);
                            void loadStats(s.id);
                          }}
                        >
                          <span className={`dot ${status}`} />
                          <div className="meta">
                            <div className="title">{labelFor(s)}</div>
                            <div className="sub">
                              {stats && (
                                <span style={{ fontFamily: "var(--mono)" }}>
                                  {stats.messages} msg{stats.messages === 1 ? "" : "s"}
                                  {stats.artifacts != null &&
                                    ` · ${stats.artifacts} file${stats.artifacts === 1 ? "" : "s"}`}
                                  {" · "}
                                </span>
                              )}
                              <span>{shortStamp(s.created_at)}</span>
                            </div>
                          </div>
                          <button
                            type="button"
                            title={s.pinned ? "Unpin session" : "Pin session"}
                            onClick={(e) => {
                              e.stopPropagation();
                              void togglePinned(s.id, Boolean(s.pinned));
                            }}
                            className={`pin-toggle ${s.pinned ? "pinned" : ""}`}
                            style={pinBtnStyle(Boolean(s.pinned))}
                          >
                            {s.pinned ? "★" : "☆"}
                          </button>
                          <button
                            type="button"
                            title="Delete session"
                            onClick={(e) => {
                              e.stopPropagation();
                              setConfirmDeleteId(isPendingDelete ? null : s.id);
                            }}
                            style={rowDeleteBtn()}
                          >
                            ×
                          </button>
                        </div>
                        {isPendingDelete && (
                          <div
                            style={confirmRowStyle()}
                            onClick={(e) => e.stopPropagation()}
                          >
                            <span style={{ color: "var(--danger)" }}>Delete?</span>
                            <button
                              type="button"
                              style={miniBtn()}
                              onClick={() => setConfirmDeleteId(null)}
                            >
                              Cancel
                            </button>
                            <button
                              type="button"
                              style={miniBtnDanger()}
                              onClick={async () => {
                                setConfirmDeleteId(null);
                                await props.onDeleteSession(s.id);
                                // Deleting a non-active session
                                // doesn't change sessionId, so the
                                // ``useGroups`` effect wouldn't
                                // otherwise re-fetch. Ask it to
                                // refresh so the row disappears even
                                // when deleting several in a row.
                                await refreshGroups();
                              }}
                            >
                              Delete
                            </button>
                          </div>
                        )}
                      </div>
                    );
                  })}
              </div>
            );
          })
        )}

        {props.mode === "managed" && (
          <CreateProjectInline
            client={props.client}
            onCreated={(slug) => props.onSelectProject(slug)}
          />
        )}
      </div>

      <div className="sessions-foot">
        <div className="user" style={{ minWidth: 0 }}>
          <div className="avatar">
            {(props.userId || "·").charAt(0).toUpperCase()}
          </div>
          <div style={{ minWidth: 0, flex: 1, overflow: "hidden" }}>
            <div
              className="n"
              style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
            >
              {props.userId ?? "Local"}
            </div>
            <div
              className="o"
              style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
            >
              {props.mode === "managed" ? "Managed workspace" : "Local folder"}
            </div>
          </div>
        </div>
        <button
          type="button"
          title="Settings"
          aria-label="Settings"
          onClick={props.onOpenSettings}
          style={{ flexShrink: 0 }}
        >
          <Icon name="settings" size={15} />
        </button>
      </div>
    </div>
  );
}

interface Group {
  id: string;
  name: string;
  /** Optional secondary line rendered under the header (e.g. workdir path). */
  sub?: string;
  sessions: SessionListItem[];
  isSelected?: boolean;
  onSelect?: () => void;
  onDelete?: () => void | Promise<void>;
}

function useGroups(props: SessionsProps): { groups: Group[]; refresh: () => Promise<void> } {
  const [projects, setProjects] = useState<ProjectInfo[]>([]);
  const [sessionsByProject, setSessionsByProject] = useState<Record<string, SessionListItem[]>>({});
  const [localSessions, setLocalSessions] = useState<SessionListItem[]>([]);

  const refreshProjects = useCallback(async () => {
    if (props.mode !== "managed") return;
    try {
      setProjects(await props.client.listProjects());
    } catch {
      /* server not ready */
    }
  }, [props.client, props.mode]);

  const refreshManagedSessions = useCallback(async () => {
    if (props.mode !== "managed" || !props.project) return;
    try {
      const list = await props.client.listSessions(props.project);
      list.sort((a, b) => (b.created_at ?? "").localeCompare(a.created_at ?? ""));
      setSessionsByProject((s) => ({ ...s, [(props as ManagedProps).project!]: list }));
    } catch {
      /* ignore */
    }
  }, [props]);

  const refreshLocalSessions = useCallback(async () => {
    if (props.mode !== "local" || !props.workdir) {
      setLocalSessions([]);
      return;
    }
    try {
      const list = await props.client.listLocalSessions(props.workdir);
      list.sort((a: SessionListItem, b: SessionListItem) =>
        (b.created_at ?? "").localeCompare(a.created_at ?? ""),
      );
      setLocalSessions(list);
    } catch {
      setLocalSessions([]);
    }
  }, [props]);

  useEffect(() => {
    void refreshProjects();
  }, [refreshProjects]);

  useEffect(() => {
    void refreshManagedSessions();
  }, [refreshManagedSessions]);

  useEffect(() => {
    void refreshLocalSessions();
  }, [refreshLocalSessions]);

  // Bump session lists whenever a session id appears (creation/switch).
  useEffect(() => {
    if (props.mode === "managed") void refreshManagedSessions();
    else void refreshLocalSessions();
  }, [props.sessionId, props.mode, refreshManagedSessions, refreshLocalSessions]);

  const refresh = useCallback(async () => {
    if (props.mode === "managed") {
      await Promise.all([refreshProjects(), refreshManagedSessions()]);
    } else {
      await refreshLocalSessions();
    }
  }, [props.mode, refreshProjects, refreshManagedSessions, refreshLocalSessions]);

  if (props.mode === "managed") {
    return {
      refresh,
      groups: projects.map((p) => ({
        id: `proj:${p.slug}`,
        name: p.name,
        sessions: p.slug === props.project ? sessionsByProject[p.slug] ?? [] : [],
        isSelected: p.slug === props.project,
        onSelect: () => props.onSelectProject(p.slug),
        onDelete: async () => {
          await props.onDeleteProject(p.slug);
          await refreshProjects();
        },
      })),
    };
  }

  if (!props.workdir) return { groups: [], refresh };
  const folder = props.workdir.split("/").filter(Boolean).pop() || props.workdir;
  return {
    refresh,
    groups: [
      {
        id: `local:${props.workdir}`,
        name: folder,
        sub: props.workdir,
        sessions: localSessions,
      },
    ],
  };
}

function CreateProjectInline({
  client,
  onCreated,
}: {
  client: CoworkClient;
  onCreated: (slug: string) => void;
}) {
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const handleCreate = async () => {
    if (!name.trim() || busy) return;
    setBusy(true);
    setErr(null);
    try {
      const p = await client.createProject(name.trim());
      setName("");
      onCreated(p.slug);
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ padding: "10px 12px 4px", display: "flex", flexDirection: "column", gap: 4 }}>
      <div style={{ display: "flex", gap: 6 }}>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleCreate()}
          placeholder="New project name…"
          style={{
            flex: 1,
            background: "var(--paper)",
            border: "1px solid var(--line)",
            borderRadius: "var(--radius-sm)",
            padding: "4px 8px",
            fontSize: "var(--fs-sm)",
            color: "var(--ink)",
          }}
        />
        <button
          type="button"
          onClick={handleCreate}
          disabled={busy || !name.trim()}
          style={{
            background: "var(--ink)",
            color: "var(--paper)",
            borderRadius: "var(--radius-sm)",
            padding: "4px 10px",
            fontSize: "var(--fs-sm)",
            opacity: busy || !name.trim() ? 0.5 : 1,
          }}
        >
          Add
        </button>
      </div>
      {err && (
        <div style={{ fontSize: "var(--fs-xs)", color: "var(--danger)" }}>{err}</div>
      )}
    </div>
  );
}

function EmptyHint({
  label,
  action,
}: {
  label: string;
  action?: { label: string; onClick: () => void };
}) {
  return (
    <div
      style={{
        padding: "16px 14px",
        fontSize: "var(--fs-sm)",
        color: "var(--ink-3)",
        display: "flex",
        flexDirection: "column",
        gap: 8,
      }}
    >
      <span>{label}</span>
      {action && (
        <button
          type="button"
          onClick={action.onClick}
          style={{
            alignSelf: "flex-start",
            background: "var(--ink)",
            color: "var(--paper)",
            borderRadius: "var(--radius-sm)",
            padding: "4px 10px",
            fontSize: "var(--fs-sm)",
          }}
        >
          {action.label}
        </button>
      )}
    </div>
  );
}

function labelFor(s: SessionListItem): string {
  if (s.title) return s.title;
  return s.id.slice(0, 8);
}

function shortStamp(iso?: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  const diffMin = Math.floor((Date.now() - d.getTime()) / 60_000);
  if (diffMin < 1) return "just now";
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function rowDeleteBtn(): React.CSSProperties {
  return {
    alignSelf: "center",
    flexShrink: 0,
    width: 20,
    height: 20,
    display: "grid",
    placeItems: "center",
    color: "var(--ink-4)",
    background: "transparent",
    fontSize: 14,
    lineHeight: 1,
    borderRadius: "var(--radius-sm)",
    marginLeft: 0,
  };
}

function pinBtnStyle(isPinned: boolean): React.CSSProperties {
  return {
    alignSelf: "center",
    flexShrink: 0,
    width: 20,
    height: 20,
    display: "grid",
    placeItems: "center",
    color: isPinned ? "var(--accent)" : "var(--ink-4)",
    background: "transparent",
    fontSize: 13,
    lineHeight: 1,
    borderRadius: "var(--radius-sm)",
    marginLeft: "auto",
  };
}

function selectBtnStyle(active: boolean): React.CSSProperties {
  return {
    width: 18,
    height: 18,
    fontSize: 12,
    lineHeight: 1,
    borderRadius: 4,
    color: active ? "var(--ink)" : "var(--ink-4)",
  };
}

function trashBtnStyle(): React.CSSProperties {
  return {
    width: 18,
    height: 18,
    fontSize: 14,
    lineHeight: 1,
    borderRadius: 4,
    color: "var(--ink-4)",
  };
}

function confirmRowStyle(): React.CSSProperties {
  return {
    display: "flex",
    alignItems: "center",
    gap: 6,
    margin: "4px 12px 6px",
    background: "var(--danger-soft, var(--paper-3))",
    border: "1px solid var(--danger)",
    borderRadius: "var(--radius-sm)",
    padding: "4px 8px",
    fontSize: "var(--fs-xs)",
  };
}

function miniBtn(): React.CSSProperties {
  return {
    padding: "2px 6px",
    borderRadius: 4,
    color: "var(--ink-3)",
  };
}

function miniBtnDanger(): React.CSSProperties {
  return {
    padding: "2px 8px",
    borderRadius: 4,
    background: "var(--danger)",
    color: "white",
    marginLeft: "auto",
  };
}
