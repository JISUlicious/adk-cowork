/**
 * Canvas pane — unified file browser + multi-tab preview.
 *
 *   ┌──────────────────────────────────────────────────────┐
 *   │  [view: tree | grid | list]    [tab1] [tab2] [tab3]  │  canvas-head
 *   ├──────────────────────────────────────────────────────┤
 *   │  ┌─────── file index ──────────┐  ┌───── preview ──┐ │  canvas-body
 *   │  │  (tree / grid / list view)  │  │ FileViewer or  │ │
 *   │  │                             │  │ raw text       │ │
 *   │  └─────────────────────────────┘  └────────────────┘ │
 *   └──────────────────────────────────────────────────────┘
 *
 * Mode-aware (managed vs local-dir) so the same component renders
 * project files (``files/`` + per-session ``scratch/``) and arbitrary
 * folders the desktop user picked.
 *
 * Tabs are plain client-side state — opening a file pushes it onto
 * ``tabs``; switching sessions clears them.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { CoworkClient } from "../transport/client";
import { isUpdated as fileIsUpdated, markSeen as fileMarkSeen } from "../fileSeenStore";
import { FileViewer } from "./FileViewer";
import { FileIcon, Icon } from "./atoms";

interface CanvasFileBase {
  /** Unique identifier — stable across refreshes for tab tracking. */
  id: string;
  name: string;
  kind: "file" | "dir";
  size?: number | null;
  /** Unix epoch seconds. Compared against the ``fileSeenStore``
   *  last-seen value to drive the "updated" dot. */
  modified?: number | null;
}
interface ManagedFile extends CanvasFileBase {
  source: "managed";
  /** Full project-relative path, e.g. ``files/draft.md``. */
  fullPath: string;
  scope: "files" | "scratch";
}
interface LocalFile extends CanvasFileBase {
  source: "local";
  /** Path relative to workdir. */
  relPath: string;
}
type CanvasFile = ManagedFile | LocalFile;

interface ManagedProps {
  mode: "managed";
  client: CoworkClient;
  project: string | null;
  sessionId: string | null;
}
interface LocalProps {
  mode: "local";
  client: CoworkClient;
  workdir: string | null;
  sessionId: string | null;
}
export type CanvasProps = ManagedProps | LocalProps;

type ViewMode = "tree" | "grid" | "list";

export function Canvas(props: CanvasProps) {
  const [view, setView] = useState<ViewMode>("tree");
  const [tabs, setTabs] = useState<CanvasFile[]>([]);
  const [activeTabId, setActiveTabId] = useState<string | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);

  // Reset tabs when the underlying scope (project/workdir/session) changes.
  const scopeKey =
    props.mode === "managed"
      ? `m:${props.project ?? ""}:${props.sessionId ?? ""}`
      : `l:${("workdir" in props && props.workdir) || ""}:${props.sessionId ?? ""}`;
  const lastScope = useRef(scopeKey);
  useEffect(() => {
    if (lastScope.current !== scopeKey) {
      setTabs([]);
      setActiveTabId(null);
      lastScope.current = scopeKey;
    }
  }, [scopeKey]);

  const openFile = useCallback((f: CanvasFile) => {
    if (f.kind !== "file") return;
    // Opening the file counts as "seen" at its current mtime; the
    // updated dot clears next render.
    fileMarkSeen(f.id, f.modified);
    setTabs((prev) => (prev.some((t) => t.id === f.id) ? prev : [...prev, f]));
    setActiveTabId(f.id);
    // Auto-collapse the drawer after a pick so the preview gets the room.
    setDrawerOpen(false);
  }, []);

  // Palette requests: CommandPalette dispatches a ``cowork:palette-open-file``
  // event rather than reaching into Canvas state directly. We synthesize a
  // lightweight ``CanvasFile`` from the path so the existing tab + preview
  // plumbing handles it uniformly.
  useEffect(() => {
    const onOpen = (e: Event) => {
      const path = (e as CustomEvent<{ path: string }>).detail?.path;
      if (!path) return;
      const name = path.split("/").pop() || path;
      if (props.mode === "managed" && props.project) {
        // Strip the ``files/`` or ``scratch/`` prefix to recover the
        // ``scope`` discriminant the preview fetcher uses.
        const [head, ...rest] = path.split("/");
        const scope: "files" | "scratch" = head === "scratch" ? "scratch" : "files";
        const fullPath = rest.length ? path : `${scope}/${path}`;
        openFile({
          id: `m:${props.project}:${fullPath}`,
          source: "managed",
          kind: "file",
          name,
          fullPath,
          scope,
        });
      } else if (props.mode === "local" && "workdir" in props && props.workdir) {
        openFile({
          id: `local:${props.workdir}:${path}`,
          source: "local",
          kind: "file",
          name,
          relPath: path,
        });
      }
    };
    window.addEventListener("cowork:palette-open-file", onOpen as EventListener);
    return () =>
      window.removeEventListener("cowork:palette-open-file", onOpen as EventListener);
  }, [openFile, props]);

  const closeTab = useCallback((id: string) => {
    setTabs((prev) => {
      const next = prev.filter((t) => t.id !== id);
      setActiveTabId((cur) => {
        if (cur !== id) return cur;
        return next.length ? next[next.length - 1].id : null;
      });
      return next;
    });
  }, []);

  const activeTab = tabs.find((t) => t.id === activeTabId) ?? null;
  const showCanvas =
    (props.mode === "managed" && props.project) ||
    (props.mode === "local" && "workdir" in props && props.workdir);

  const indexNode = (
    <>
      {props.mode === "managed" ? (
        <ManagedIndex
          client={props.client}
          project={props.project!}
          sessionId={props.sessionId}
          view={view}
          activeTabId={activeTabId}
          onOpen={openFile}
        />
      ) : (
        <LocalIndex
          client={props.client}
          workdir={(props as LocalProps).workdir!}
          sessionId={props.sessionId}
          view={view}
          activeTabId={activeTabId}
          onOpen={openFile}
        />
      )}
    </>
  );

  return (
    <div className="pane canvas" style={{ height: "100%", display: "flex", flexDirection: "column" }}>
      <div className="canvas-head">
        <button
          className={`iconbtn drawer-toggle ${drawerOpen ? "on" : ""}`}
          type="button"
          title={drawerOpen ? "Hide files" : "Show files"}
          onClick={() => setDrawerOpen((v) => !v)}
          disabled={!showCanvas}
        >
          <Icon name="panelLeft" size={15} />
        </button>

        <div className="canvas-tabs">
          {tabs.map((t) => (
            <div
              key={t.id}
              className={`canvas-tab ${t.id === activeTabId ? "active" : ""}`}
              onClick={() => {
                // Reactivating a tab counts as "seen" just like open.
                fileMarkSeen(t.id, t.modified);
                setActiveTabId(t.id);
              }}
            >
              <span className="ic">
                <FileIcon kind={fileKind(t.name)} />
              </span>
              <span>{t.name}</span>
              <span
                className="cl"
                onClick={(e) => {
                  e.stopPropagation();
                  closeTab(t.id);
                }}
              >
                <Icon name="close" size={10} />
              </span>
            </div>
          ))}
        </div>

        <button
          className="iconbtn"
          type="button"
          title="Refresh"
          onClick={() => window.dispatchEvent(new CustomEvent("cowork:canvas-refresh"))}
        >
          <Icon name="refresh" size={13} />
        </button>
      </div>

      <div className="canvas-body" style={{ flex: 1, minHeight: 0, display: "flex", overflow: "hidden", position: "relative" }}>
        {!showCanvas ? (
          <div style={emptyHintStyle()}>
            {props.mode === "managed"
              ? "Select a project to browse files."
              : "Pick a folder to browse files."}
          </div>
        ) : (
          <>
            <div style={previewPaneStyle()}>
              {activeTab ? (
                <PreviewHost client={props.client} file={activeTab} />
              ) : (
                <div style={emptyHintStyle()}>Open a file to preview.</div>
              )}
            </div>

            {drawerOpen && (
              <>
                <div className="tree-pane-drawer">
                  <div className="tree-pane-head">
                    <span className="label">Files</span>
                    <div className="view-toggle small">
                      <button
                        type="button"
                        className={view === "tree" ? "active" : ""}
                        onClick={() => setView("tree")}
                        title="Tree"
                      >
                        <Icon name="tree" size={11} />
                      </button>
                      <button
                        type="button"
                        className={view === "grid" ? "active" : ""}
                        onClick={() => setView("grid")}
                        title="Grid"
                      >
                        <Icon name="grid" size={11} />
                      </button>
                      <button
                        type="button"
                        className={view === "list" ? "active" : ""}
                        onClick={() => setView("list")}
                        title="List"
                      >
                        <Icon name="list" size={11} />
                      </button>
                    </div>
                    <button
                      type="button"
                      className="iconbtn"
                      onClick={() => setDrawerOpen(false)}
                      title="Close"
                    >
                      <Icon name="close" size={12} />
                    </button>
                  </div>
                  <div style={{ flex: 1, overflowY: "auto", minHeight: 0 }}>{indexNode}</div>
                </div>
                <div className="drawer-scrim" onClick={() => setDrawerOpen(false)} />
              </>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function PreviewHost({ client, file }: { client: CoworkClient; file: CanvasFile }) {
  const kind = fileKind(file.name);
  const canRender = kind === "md" || kind === "html";
  const [view, setView] = useState<"rendered" | "code">(canRender ? "rendered" : "code");

  // Reset to the default when the active file changes.
  useEffect(() => {
    setView(canRender ? "rendered" : "code");
  }, [file.id, canRender]);

  if (file.source === "managed") {
    return (
      <div style={previewFillStyle()}>
        <div className="preview-head" style={previewHeadStyle()}>
          <span className="ic" style={{ color: "var(--ink-3)" }}>
            <FileIcon kind={kind} />
          </span>
          <span style={{ flex: 1, fontFamily: "var(--mono)", fontSize: "var(--fs-sm)", color: "var(--ink-2)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {file.fullPath}
          </span>
          {canRender && <ViewToggle view={view} onChange={setView} />}
        </div>
        <div style={{ flex: 1, minHeight: 0, overflow: "auto", display: "flex", flexDirection: "column" }}>
          <FileViewer
            client={client}
            project={managedProjectFor(file)}
            path={file.fullPath}
            name={file.name}
            view={view}
          />
        </div>
      </div>
    );
  }
  return <LocalPreview client={client} file={file} view={view} setView={setView} canRender={canRender} kind={kind} />;
}

/** Absolute-fill style. The preview pane is ``position: relative`` so
 *  this child gets concrete dimensions from its parent regardless of
 *  the flex/grid chain above it. That fixes the "h-full of nothing"
 *  problem where percentage heights silently resolve to zero and the
 *  inner iframe/pre loses its scroll region. */
function previewFillStyle(): React.CSSProperties {
  return {
    position: "absolute",
    inset: 0,
    display: "flex",
    flexDirection: "column",
  };
}

function ViewToggle({
  view,
  onChange,
}: {
  view: "rendered" | "code";
  onChange: (v: "rendered" | "code") => void;
}) {
  return (
    <div className="view-toggle small" style={{ flexShrink: 0 }}>
      <button
        type="button"
        className={view === "rendered" ? "active" : ""}
        onClick={() => onChange("rendered")}
        title="Rendered"
        aria-label="Rendered view"
      >
        <Icon name="eye" size={13} />
      </button>
      <button
        type="button"
        className={view === "code" ? "active" : ""}
        onClick={() => onChange("code")}
        title="Source"
        aria-label="Source view"
      >
        <Icon name="source" size={13} />
      </button>
    </div>
  );
}

function LocalPreview({
  client,
  file,
  view,
  setView,
  canRender,
  kind,
}: {
  client: CoworkClient;
  file: LocalFile;
  view: "rendered" | "code";
  setView: (v: "rendered" | "code") => void;
  canRender: boolean;
  kind: string;
}) {
  const [content, setContent] = useState<string | null>(null);
  const [truncated, setTruncated] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const workdirRef = useRef<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const wd = workdirRef.current;
    if (!wd) return;
    setContent(null);
    setError(null);
    client
      .readLocalFile(wd, file.relPath)
      .then((d) => {
        if (cancelled) return;
        setContent(d.content);
        setTruncated(d.truncated);
      })
      .catch((e) => {
        if (cancelled) return;
        setError(String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [client, file.relPath]);

  // Pull the workdir from the file's `id` prefix — encoded as `local:<wd>:<rel>`
  useEffect(() => {
    const parts = file.id.split(":");
    workdirRef.current = parts[1] ?? null;
  }, [file.id]);

  const isIframe = canRender && view === "rendered" && kind === "html";
  return (
    <div style={previewFillStyle()}>
      <div className="preview-head" style={previewHeadStyle()}>
        <span className="ic" style={{ color: "var(--ink-3)" }}>
          <FileIcon kind={kind} />
        </span>
        <span style={{ flex: 1, fontFamily: "var(--mono)", fontSize: "var(--fs-sm)", color: "var(--ink-2)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {file.relPath}
        </span>
        {truncated && (
          <span style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--warn)" }}>
            truncated at 2 MB
          </span>
        )}
        {canRender && <ViewToggle view={view} onChange={setView} />}
      </div>
      <div
        style={{
          flex: 1,
          minHeight: 0,
          overflow: isIframe ? "hidden" : "auto",
          display: "flex",
          flexDirection: "column",
          padding: isIframe ? 0 : "10px 14px",
        }}
      >
        {error ? (
          <div style={{ color: "var(--danger)", fontFamily: "var(--mono)", fontSize: "var(--fs-sm)" }}>{error}</div>
        ) : content === null ? (
          <div style={{ color: "var(--ink-3)", fontFamily: "var(--mono)", fontSize: "var(--fs-sm)" }}>Loading…</div>
        ) : canRender && view === "rendered" && kind === "md" ? (
          <div className="md-preview" style={{ fontFamily: "var(--sans)", fontSize: "var(--fs-md)", lineHeight: 1.6, color: "var(--ink)", maxWidth: "48em" }}>
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
          </div>
        ) : isIframe ? (
          <iframe
            title={file.name}
            srcDoc={content}
            sandbox=""
            style={{ flex: 1, width: "100%", border: 0, background: "var(--paper)" }}
          />
        ) : (
          <pre style={{ margin: 0, fontFamily: "var(--mono)", fontSize: 11.5, color: "var(--ink)", whiteSpace: "pre-wrap", wordBreak: "break-word", lineHeight: 1.5 }}>
            {content}
          </pre>
        )}
      </div>
    </div>
  );
}

/* ───────────────────────── Managed index ───────────────────────── */

function ManagedIndex({
  client,
  project,
  sessionId,
  view,
  activeTabId,
  onOpen,
}: {
  client: CoworkClient;
  project: string;
  sessionId: string | null;
  view: ViewMode;
  activeTabId: string | null;
  onOpen: (f: CanvasFile) => void;
}) {
  const [files, setFiles] = useState<ManagedFile[]>([]);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [proj, scratch] = await Promise.all([
        client
          .listFiles(project, "files")
          .then((entries) =>
            entries.map<ManagedFile>((e) => ({
              source: "managed",
              id: `m:${project}:files/${e.name}`,
              name: e.name,
              kind: e.kind,
              size: e.size ?? null,
              modified: e.modified ?? null,
              fullPath: `files/${e.name}`,
              scope: "files",
            })),
          )
          .catch(() => []),
        sessionId
          ? client
              .listFiles(project, `sessions/${sessionId}/scratch`)
              .then((entries) =>
                entries.map<ManagedFile>((e) => ({
                  source: "managed",
                  id: `m:${project}:sessions/${sessionId}/scratch/${e.name}`,
                  name: e.name,
                  kind: e.kind,
                  size: e.size ?? null,
                  modified: e.modified ?? null,
                  fullPath: `sessions/${sessionId}/scratch/${e.name}`,
                  scope: "scratch",
                })),
              )
              .catch(() => [])
          : Promise.resolve([] as ManagedFile[]),
      ]);
      setFiles([...proj, ...scratch]);
    } finally {
      setLoading(false);
    }
  }, [client, project, sessionId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Poll while a session is active — agents may be writing files.
  useEffect(() => {
    if (!sessionId) return;
    const id = window.setInterval(() => void refresh(), 3000);
    return () => window.clearInterval(id);
  }, [refresh, sessionId]);

  // Manual refresh via the canvas-head button.
  useEffect(() => {
    const onRefresh = () => void refresh();
    window.addEventListener("cowork:canvas-refresh", onRefresh);
    return () => window.removeEventListener("cowork:canvas-refresh", onRefresh);
  }, [refresh]);

  return (
    <FileViews
      view={view}
      files={files}
      activeTabId={activeTabId}
      onOpen={onOpen}
      loading={loading}
    />
  );
}

/* ───────────────────────── Local index ───────────────────────── */

/**
 * Local-mode file index. Tree view uses lazy expansion — clicking a
 * directory toggles its expanded state and loads children on demand.
 * Grid / list views keep the flat ``cwd`` navigation since those shapes
 * don't lend themselves to nested indentation.
 */
function LocalIndex({
  client,
  workdir,
  sessionId,
  view,
  activeTabId,
  onOpen,
}: {
  client: CoworkClient;
  workdir: string;
  sessionId: string | null;
  view: ViewMode;
  activeTabId: string | null;
  onOpen: (f: CanvasFile) => void;
}) {
  // Tree state: which dirs have children loaded + which are expanded.
  const [childrenByDir, setChildrenByDir] = useState<Record<string, LocalFile[]>>({});
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [loadingDirs, setLoadingDirs] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  // Grid/list state: single-level cwd navigation.
  const [cwd, setCwd] = useState(".");
  const [flatEntries, setFlatEntries] = useState<LocalFile[]>([]);
  const [flatLoading, setFlatLoading] = useState(false);

  const loadDir = useCallback(
    async (relDir: string): Promise<LocalFile[]> => {
      setLoadingDirs((prev) => {
        const next = new Set(prev);
        next.add(relDir);
        return next;
      });
      try {
        const data = await client.listLocalFiles(workdir, relDir);
        const mapped = data.entries.map<LocalFile>((e) => ({
          source: "local",
          id: `local:${workdir}:${relDir === "." ? e.name : `${relDir}/${e.name}`}`,
          name: e.name,
          kind: e.kind,
          size: e.size ?? null,
          modified: e.modified ?? null,
          relPath: relDir === "." ? e.name : `${relDir}/${e.name}`,
        }));
        setChildrenByDir((prev) => ({ ...prev, [relDir]: mapped }));
        setError(null);
        return mapped;
      } catch (e) {
        setError(String(e));
        return [];
      } finally {
        setLoadingDirs((prev) => {
          const next = new Set(prev);
          next.delete(relDir);
          return next;
        });
      }
    },
    [client, workdir],
  );

  const refreshLoadedDirs = useCallback(async () => {
    // Refresh every already-loaded dir so agent-side writes show up.
    const dirs = Object.keys(childrenByDir);
    if (view !== "tree") {
      setFlatLoading(true);
      try {
        const data = await client.listLocalFiles(workdir, cwd);
        setFlatEntries(
          data.entries.map<LocalFile>((e) => ({
            source: "local",
            id: `local:${workdir}:${cwd === "." ? e.name : `${cwd}/${e.name}`}`,
            name: e.name,
            kind: e.kind,
            size: e.size ?? null,
            modified: e.modified ?? null,
            relPath: cwd === "." ? e.name : `${cwd}/${e.name}`,
          })),
        );
        setError(null);
      } catch (e) {
        setError(String(e));
      } finally {
        setFlatLoading(false);
      }
      return;
    }
    for (const d of dirs) {
      await loadDir(d);
    }
  }, [childrenByDir, client, cwd, loadDir, view, workdir]);

  // Reset tree when the workdir or session changes.
  useEffect(() => {
    setChildrenByDir({});
    setExpanded(new Set());
    setCwd(".");
  }, [workdir, sessionId]);

  // Load (or reload) whenever the view-relevant state changes. We drop
  // the old ``!childrenByDir["."]`` guard because it read childrenByDir
  // from a stale closure — the sibling reset effect had cleared the
  // state but the value in this closure was still populated, so we'd
  // silently skip the reload. Always refetching on dep change is
  // cheap and correct.
  useEffect(() => {
    if (view === "tree") {
      void loadDir(".");
    } else {
      setFlatLoading(true);
      client
        .listLocalFiles(workdir, cwd)
        .then((data) => {
          setFlatEntries(
            data.entries.map<LocalFile>((e) => ({
              source: "local",
              id: `local:${workdir}:${cwd === "." ? e.name : `${cwd}/${e.name}`}`,
              name: e.name,
              kind: e.kind,
              size: e.size ?? null,
              modified: e.modified ?? null,
              relPath: cwd === "." ? e.name : `${cwd}/${e.name}`,
            })),
          );
          setError(null);
        })
        .catch((e) => setError(String(e)))
        .finally(() => setFlatLoading(false));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view, cwd, workdir, sessionId]);

  // Poll every 3s while a session is active.
  useEffect(() => {
    if (!sessionId) return;
    const id = window.setInterval(() => void refreshLoadedDirs(), 3000);
    return () => window.clearInterval(id);
  }, [refreshLoadedDirs, sessionId]);

  // Manual refresh button.
  useEffect(() => {
    const onRefresh = () => void refreshLoadedDirs();
    window.addEventListener("cowork:canvas-refresh", onRefresh);
    return () => window.removeEventListener("cowork:canvas-refresh", onRefresh);
  }, [refreshLoadedDirs]);

  const toggleDir = useCallback(
    async (relDir: string) => {
      setExpanded((prev) => {
        const next = new Set(prev);
        if (next.has(relDir)) next.delete(relDir);
        else next.add(relDir);
        return next;
      });
      if (!childrenByDir[relDir]) await loadDir(relDir);
    },
    [childrenByDir, loadDir],
  );

  if (view === "tree") {
    return (
      <>
        {error && (
          <div style={{ padding: "8px 12px", color: "var(--danger)", fontSize: "var(--fs-sm)" }}>{error}</div>
        )}
        <LocalTreeView
          rootKey="."
          childrenByDir={childrenByDir}
          expanded={expanded}
          loadingDirs={loadingDirs}
          activeTabId={activeTabId}
          onToggle={toggleDir}
          onOpenFile={onOpen}
        />
      </>
    );
  }

  // Grid / list: flat with cwd navigation.
  const upRow: LocalFile | null =
    cwd === "."
      ? null
      : {
          source: "local",
          id: `local:${workdir}:${cwd}::up`,
          name: "..",
          kind: "dir",
          size: null,
          relPath: parentOf(cwd),
        };
  const wrapped: LocalFile[] = upRow ? [upRow, ...flatEntries] : flatEntries;

  const handleFlatClick = (f: CanvasFile) => {
    if (f.source !== "local") return;
    if (f.name === "..") {
      setCwd(parentOf(cwd));
      return;
    }
    if (f.kind === "dir") {
      setCwd(cwd === "." ? f.name : `${cwd}/${f.name}`);
      return;
    }
    onOpen(f);
  };

  return (
    <>
      {cwd !== "." && (
        <div style={{ padding: "6px 12px", fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-3)" }}>
          {cwd}
        </div>
      )}
      {error && (
        <div style={{ padding: "8px 12px", color: "var(--danger)", fontSize: "var(--fs-sm)" }}>{error}</div>
      )}
      <FileViews
        view={view}
        files={wrapped}
        activeTabId={activeTabId}
        onOpen={handleFlatClick}
        loading={flatLoading}
      />
    </>
  );
}

/** Recursive tree view. Renders root children at depth 0; nested dirs
 *  appear indented when expanded. Files click to open as tabs; dirs
 *  click to toggle. */
function LocalTreeView({
  rootKey,
  childrenByDir,
  expanded,
  loadingDirs,
  activeTabId,
  onToggle,
  onOpenFile,
  depth = 0,
}: {
  rootKey: string;
  childrenByDir: Record<string, LocalFile[]>;
  expanded: Set<string>;
  loadingDirs: Set<string>;
  activeTabId: string | null;
  onToggle: (relDir: string) => void;
  onOpenFile: (f: CanvasFile) => void;
  depth?: number;
}) {
  const rows = childrenByDir[rootKey];
  if (rows === undefined) {
    return loadingDirs.has(rootKey) ? (
      <div style={{ padding: 14, color: "var(--ink-3)", fontFamily: "var(--mono)", fontSize: 11 }}>Loading…</div>
    ) : null;
  }
  if (!rows.length && depth === 0) {
    return <div style={{ padding: 14, color: "var(--ink-3)", fontSize: "var(--fs-sm)" }}>Empty.</div>;
  }
  return (
    <div style={{ padding: depth === 0 ? "4px 0" : 0 }}>
      {rows.map((f) => {
        const isDir = f.kind === "dir";
        const isExpanded = isDir && expanded.has(f.relPath);
        const isLoading = isDir && loadingDirs.has(f.relPath);
        return (
          <div key={f.id}>
            <div
              onClick={() => (isDir ? onToggle(f.relPath) : onOpenFile(f))}
              style={treeRowStyle(f.id === activeTabId, depth)}
            >
              <span style={{ width: 12, flexShrink: 0, color: "var(--ink-4)", display: "inline-flex", justifyContent: "center" }}>
                {isDir ? (
                  <Icon name={isExpanded ? "chevD" : "chevR"} size={10} />
                ) : null}
              </span>
              <span style={{ width: 14, color: "var(--ink-4)", flexShrink: 0, display: "inline-flex", justifyContent: "center" }}>
                <Icon name={isDir ? (isExpanded ? "folderOpen" : "folder") : "doc"} size={12} />
              </span>
              <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {f.name}
              </span>
              <UpdatedDot file={f} />
              {typeof f.size === "number" && (
                <span style={{ marginLeft: "auto", fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-4)" }}>
                  {formatSize(f.size)}
                </span>
              )}
            </div>
            {isDir && isExpanded && (
              <>
                {isLoading && !childrenByDir[f.relPath] ? (
                  <div
                    style={{
                      padding: `4px 12px 4px ${(depth + 1) * 14 + 12}px`,
                      fontFamily: "var(--mono)",
                      fontSize: 10,
                      color: "var(--ink-4)",
                    }}
                  >
                    Loading…
                  </div>
                ) : (
                  <LocalTreeView
                    rootKey={f.relPath}
                    childrenByDir={childrenByDir}
                    expanded={expanded}
                    loadingDirs={loadingDirs}
                    activeTabId={activeTabId}
                    onToggle={onToggle}
                    onOpenFile={onOpenFile}
                    depth={depth + 1}
                  />
                )}
              </>
            )}
          </div>
        );
      })}
    </div>
  );
}

/* ───────────────────────── Views ───────────────────────── */

function FileViews({
  view,
  files,
  activeTabId,
  onOpen,
  loading,
}: {
  view: ViewMode;
  files: CanvasFile[];
  activeTabId: string | null;
  onOpen: (f: CanvasFile) => void;
  loading: boolean;
}) {
  if (loading && files.length === 0) {
    return (
      <div style={{ padding: 14, color: "var(--ink-3)", fontFamily: "var(--mono)", fontSize: 11 }}>Loading…</div>
    );
  }
  if (!files.length) {
    return (
      <div style={{ padding: 14, color: "var(--ink-3)", fontSize: "var(--fs-sm)" }}>Empty.</div>
    );
  }
  if (view === "grid") return <GridView files={files} activeTabId={activeTabId} onOpen={onOpen} />;
  if (view === "list") return <ListView files={files} activeTabId={activeTabId} onOpen={onOpen} />;
  return <TreeView files={files} activeTabId={activeTabId} onOpen={onOpen} />;
}

function TreeView({ files, activeTabId, onOpen }: { files: CanvasFile[]; activeTabId: string | null; onOpen: (f: CanvasFile) => void }) {
  return (
    <div style={{ padding: "4px 0" }}>
      {files.map((f) => (
        <div
          key={f.id}
          onClick={() => onOpen(f)}
          style={treeRowStyle(f.id === activeTabId)}
        >
          <span style={{ width: 14, color: "var(--ink-4)", flexShrink: 0, display: "inline-flex", justifyContent: "center" }}>
            <Icon name={f.kind === "dir" ? "folder" : "doc"} size={12} />
          </span>
          <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {f.name}
          </span>
          <UpdatedDot file={f} />
          {typeof f.size === "number" && (
            <span style={{ marginLeft: "auto", fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-4)" }}>
              {formatSize(f.size)}
            </span>
          )}
        </div>
      ))}
    </div>
  );
}

/** Small accent dot next to filenames whose server mtime is newer
 *  than the locally-stored "last seen" timestamp (see
 *  ``fileSeenStore``). Renders nothing for never-seen files, dirs
 *  without mtime, or when the file has already been opened since
 *  its last change. */
function UpdatedDot({ file }: { file: CanvasFile }) {
  if (file.kind !== "file") return null;
  if (!fileIsUpdated(file.id, file.modified)) return null;
  return (
    <span
      className="file-dot updated"
      title="Updated since last open"
      aria-label="updated"
    />
  );
}

function ListView({ files, activeTabId, onOpen }: { files: CanvasFile[]; activeTabId: string | null; onOpen: (f: CanvasFile) => void }) {
  return (
    <div style={{ padding: "4px 0", fontSize: "var(--fs-sm)" }}>
      <div style={listHeaderStyle()}>
        <span style={{ width: 16 }} />
        <span style={{ flex: 1 }}>Name</span>
        <span style={{ width: 60, textAlign: "right" }}>Size</span>
      </div>
      {files.map((f) => (
        <div
          key={f.id}
          onClick={() => onOpen(f)}
          style={listRowStyle(f.id === activeTabId)}
        >
          <span style={{ width: 16, color: "var(--ink-4)" }}>
            <Icon name={f.kind === "dir" ? "folder" : "doc"} size={12} />
          </span>
          <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {f.name}
          </span>
          <UpdatedDot file={f} />
          <span style={{ width: 60, textAlign: "right", fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-4)" }}>
            {typeof f.size === "number" ? formatSize(f.size) : ""}
          </span>
        </div>
      ))}
    </div>
  );
}

function GridView({ files, activeTabId, onOpen }: { files: CanvasFile[]; activeTabId: string | null; onOpen: (f: CanvasFile) => void }) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fill, minmax(120px, 1fr))",
        gap: 10,
        padding: 10,
      }}
    >
      {files.map((f) => {
        const kind = fileKind(f.name);
        return (
          <div
            key={f.id}
            onClick={() => onOpen(f)}
            style={gridCardStyle(f.id === activeTabId)}
          >
            <div style={gridThumbStyle(kind)}>
              <FileIcon kind={kind} size={28} />
            </div>
            <div style={{ padding: "6px 8px", fontSize: "var(--fs-sm)", color: "var(--ink)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", display: "flex", alignItems: "center", gap: 4 }}>
              <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{f.name}</span>
              <UpdatedDot file={f} />
            </div>
            {typeof f.size === "number" && (
              <div style={{ padding: "0 8px 6px", fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-4)" }}>
                {formatSize(f.size)}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

/* ───────────────────────── Helpers ───────────────────────── */

const fileKind = (name: string): string => {
  const ext = name.split(".").pop()?.toLowerCase() ?? "";
  if (["md", "markdown"].includes(ext)) return "md";
  if (["html", "htm"].includes(ext)) return "html";
  if (["js", "ts", "tsx", "jsx", "py", "rs", "go", "rb", "json", "yaml", "yml", "toml"].includes(ext)) return "code";
  if (["csv", "tsv", "xlsx"].includes(ext)) return "table";
  if (["png", "jpg", "jpeg", "gif", "svg", "webp", "bmp"].includes(ext)) return "image";
  if (ext === "pdf") return "pdf";
  return "file";
};

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes}B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}K`;
  return `${(bytes / (1024 * 1024)).toFixed(1)}M`;
}

function parentOf(cwd: string): string {
  const parts = cwd.split("/");
  parts.pop();
  return parts.length === 0 ? "." : parts.join("/");
}

function managedProjectFor(file: ManagedFile): string {
  // id format: m:<project>:<fullPath>
  return file.id.split(":")[1];
}

/* ───────────────────────── Inline styles ───────────────────────── */

function previewPaneStyle(): React.CSSProperties {
  return {
    flex: 1,
    minWidth: 0,
    position: "relative",
    overflow: "hidden",
    background: "var(--paper)",
  };
}

function previewHeadStyle(): React.CSSProperties {
  return {
    display: "flex",
    alignItems: "center",
    gap: 8,
    padding: "8px 14px",
    borderBottom: "1px solid var(--line)",
    background: "var(--paper-2)",
  };
}

function emptyHintStyle(): React.CSSProperties {
  return {
    flex: 1,
    display: "grid",
    placeItems: "center",
    color: "var(--ink-3)",
    fontFamily: "var(--serif)",
    fontSize: "var(--fs-md)",
  };
}

function treeRowStyle(active: boolean, depth = 0): React.CSSProperties {
  return {
    display: "flex",
    alignItems: "center",
    gap: 6,
    padding: `4px 12px 4px ${12 + depth * 14}px`,
    fontSize: "var(--fs-sm)",
    color: active ? "var(--ink)" : "var(--ink-2)",
    background: active ? "var(--paper-3)" : "transparent",
    cursor: "pointer",
    borderLeft: `2px solid ${active ? "var(--accent)" : "transparent"}`,
  };
}

function listHeaderStyle(): React.CSSProperties {
  return {
    display: "flex",
    alignItems: "center",
    gap: 6,
    padding: "4px 12px",
    fontFamily: "var(--mono)",
    fontSize: 10,
    textTransform: "uppercase",
    letterSpacing: 0.06,
    color: "var(--ink-4)",
    borderBottom: "1px solid var(--line)",
  };
}

function listRowStyle(active: boolean): React.CSSProperties {
  return {
    display: "flex",
    alignItems: "center",
    gap: 6,
    padding: "4px 12px",
    fontSize: "var(--fs-sm)",
    color: active ? "var(--ink)" : "var(--ink-2)",
    background: active ? "var(--paper-3)" : "transparent",
    cursor: "pointer",
  };
}

function gridCardStyle(active: boolean): React.CSSProperties {
  return {
    border: `1px solid ${active ? "var(--accent)" : "var(--line)"}`,
    borderRadius: "var(--radius-sm)",
    background: "var(--paper-2)",
    overflow: "hidden",
    cursor: "pointer",
  };
}

function gridThumbStyle(_kind: string): React.CSSProperties {
  return {
    height: 80,
    background: "var(--paper-3)",
    display: "grid",
    placeItems: "center",
    color: "var(--ink-3)",
  };
}
