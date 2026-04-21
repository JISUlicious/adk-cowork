import { useEffect, useMemo, useState } from "react";
import { CoworkClient } from "./transport/client";
import { useChat } from "./hooks/useChat";
import { useNotifications } from "./hooks/useNotifications";
import { Titlebar } from "./components/Titlebar";
import { Sessions } from "./components/Sessions";
import { Chat } from "./components/Chat";
import { Canvas } from "./components/Canvas";
import { CommandPalette, type PaletteScope } from "./components/CommandPalette";
import { Settings } from "./components/Settings";
import {
  copyIntoWorkdir,
  getRecentWorkdir,
  isTauri,
  onFileDrop,
  openWorkspaceInFileManager,
  pickWorkdir,
  setRecentWorkdir,
} from "./transport/tauri";

interface AppProps {
  baseUrl?: string;
  token?: string;
}

/** The agent-facing surface. Derives from the runtime environment, not a
 *  build-time flag, so the same bundle runs under Tauri and in a plain
 *  browser. Desktop defaults to local-dir mode; web defaults to managed. */
type Surface = "desktop" | "web";

function App({ baseUrl, token }: AppProps = {}) {
  const client = useMemo(() => new CoworkClient(baseUrl, token), [baseUrl, token]);
  // eslint-disable-next-line no-console
  console.log("[cowork] client config", {
    baseUrl: baseUrl || "(relative)",
    hasToken: Boolean(token),
    origin: typeof window !== "undefined" ? window.location.origin : "?",
  });
  const surface: Surface = isTauri() ? "desktop" : "web";
  const [project, setProject] = useState<string | null>(null);
  const [workdir, setWorkdir] = useState<string | null>(null);
  const [dropStatus, setDropStatus] = useState<string | null>(null);
  const [lastEventAt, setLastEventAt] = useState<number | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const {
    messages,
    sending,
    sendingIds,
    waitingIds,
    send,
    reset,
    newSession,
    resumeSession,
    sessionId,
    agents,
    decidedToolIds,
    markToolDecided,
    trustedToolNames,
    markToolTrusted,
  } = useChat(client);

  // Scope passed to useChat — determines managed vs local-dir session type.
  const scope = workdir ? { workdir } : project ? { project } : undefined;

  const {
    items: notifications,
    unread: unreadNotifications,
    refresh: refreshNotifications,
    markRead: markNotificationRead,
    clearAll: clearNotifications,
  } = useNotifications(client);

  const handleJumpFromNotification = async (sid: string) => {
    if (!sid || sid === sessionId) return;
    if (!scope) return;
    try {
      await resumeSession(sid, scope);
    } catch {
      /* already-deleted or unreachable — bell still clears */
    }
  };

  // Bump the auto-saved stamp whenever the event timeline grows or mutates.
  useEffect(() => {
    if (messages.length) setLastEventAt(Date.now());
  }, [messages]);

  // Global ⌘K / Ctrl+K opens the command palette. Ignore when typing
  // inside an input / textarea / contenteditable so the shortcut
  // doesn't hijack natural text editing (e.g. the composer). The
  // palette has its own listener for Escape + ↑↓ + Enter.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "k" && e.key !== "K") return;
      if (!(e.metaKey || e.ctrlKey)) return;
      e.preventDefault();
      setPaletteOpen((v) => !v);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const paletteScope: PaletteScope | null = workdir
    ? { mode: "local", workdir }
    : project
      ? { mode: "managed", project }
      : null;

  const handleOpenFileFromPalette = (path: string) => {
    // The Canvas pane owns its own file list and preview state; the
    // palette can't reach in without extra plumbing, so we broadcast
    // a request it can optionally honor. Canvas picks this up in a
    // listener and opens the matching file in a new tab.
    window.dispatchEvent(
      new CustomEvent("cowork:palette-open-file", { detail: { path } }),
    );
  };

  const handleJumpToMessage = (index: number) => {
    const el = document.querySelector<HTMLElement>(`[data-msg-index="${index}"]`);
    if (!el) return;
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    // Brief flash so the user can locate the highlighted row. Inline
    // rather than a CSS class so we don't have to introduce a new
    // design-system rule for a one-shot affordance.
    const prev = el.style.background;
    el.style.transition = "background 240ms ease";
    el.style.background = "var(--accent-soft, var(--paper-3))";
    window.setTimeout(() => {
      el.style.background = prev;
    }, 900);
  };

  // Switch to ``projectSlug`` if it's not already active, then resume
  // ``sid``. Local-dir surface ignores project switching (there is one
  // project). Shared by palette handlers that need cross-session /
  // cross-project navigation.
  const resumeAcrossProject = async (
    sid: string,
    projectSlug?: string,
  ): Promise<void> => {
    if (projectSlug && surface === "web" && projectSlug !== project) {
      handleSelectProject(projectSlug);
      // ``resumeSession`` needs the new scope — the reset inside
      // ``handleSelectProject`` clears messages, and React batches the
      // state updates, so we await a microtask before resuming.
      await Promise.resolve();
      await resumeSession(sid, { project: projectSlug });
      return;
    }
    const target = scope ?? (projectSlug ? { project: projectSlug } : null);
    if (!target) return;
    await resumeSession(sid, target);
  };

  const handlePalettePickSession = async (
    sid: string,
    projectSlug?: string,
  ) => {
    try {
      await resumeAcrossProject(sid, projectSlug);
    } catch (e) {
      console.error("[cowork] palette session pick failed:", e);
    }
  };

  const handlePalettePickFile = async (projectSlug: string, path: string) => {
    if (surface === "desktop") return; // local mode doesn't switch projects
    if (projectSlug !== project) handleSelectProject(projectSlug);
    // Wait one microtask so the scope settles, then fire the open-file
    // broadcast Canvas listens for.
    await Promise.resolve();
    window.dispatchEvent(
      new CustomEvent("cowork:palette-open-file", { detail: { path } }),
    );
  };

  const handlePalettePickSessionMessage = async (
    sid: string,
    index: number,
    projectSlug?: string,
  ) => {
    try {
      await resumeAcrossProject(sid, projectSlug);
    } catch (e) {
      console.error("[cowork] palette message pick failed:", e);
      return;
    }
    // ``messages`` populates via SSE/history fetch after resumeSession;
    // retry the scroll until the row lands. Cap the retries so a
    // missing-index query doesn't loop forever.
    let tries = 0;
    const attempt = () => {
      const el = document.querySelector<HTMLElement>(
        `[data-msg-index="${index}"]`,
      );
      if (el) {
        handleJumpToMessage(index);
        return;
      }
      tries += 1;
      if (tries < 20) window.setTimeout(attempt, 100);
    };
    window.setTimeout(attempt, 60);
  };

  // Refresh notifications immediately when the sending state drops —
  // that's when the server just emitted turn_complete (or confirmation /
  // error) for the active session, and we don't want the bell to lag by
  // up to 20 s behind the actual event. The hook's interval still
  // covers background-tab and cross-session producers.
  useEffect(() => {
    if (!sending) void refreshNotifications();
  }, [sending, refreshNotifications]);

  // On launch in desktop mode, reopen whatever folder the user had last.
  useEffect(() => {
    if (surface !== "desktop") return;
    (async () => {
      const recent = await getRecentWorkdir();
      if (recent) setWorkdir(recent);
    })();
  }, [surface]);

  const handlePickWorkdir = async () => {
    const picked = await pickWorkdir();
    if (!picked) return;
    if (picked === workdir) return;
    reset();
    setWorkdir(picked);
    setProject(null); // Cannot be in both modes at once.
    await setRecentWorkdir(picked);
  };

  const handleSelectProject = (slug: string) => {
    if (slug !== project) {
      reset();
      setProject(slug);
      setWorkdir(null);
    }
  };

  const handleSelectSession = async (sid: string) => {
    if (sid === sessionId) return;
    if (!scope) return;
    await resumeSession(sid, scope);
  };

  const handleNewSession = () => {
    if (scope) {
      void newSession(scope);
    } else {
      reset();
    }
  };

  const handleDeleteSession = async (sid: string) => {
    if (workdir) {
      try {
        await client.deleteLocalSession(workdir, sid);
        if (sid === sessionId) reset();
      } catch (e) {
        console.error("[cowork] delete local session failed:", e);
      }
      return;
    }
    if (!project) return;
    try {
      await client.deleteSession(project, sid);
      if (sid === sessionId) reset();
    } catch (e) {
      console.error("[cowork] delete session failed:", e);
    }
  };

  const handleDeleteProject = async (slug: string) => {
    try {
      await client.deleteProject(slug);
      if (slug === project) {
        reset();
        setProject(null);
      }
    } catch (e) {
      console.error("[cowork] delete project failed:", e);
    }
  };

  const handleSend = (text: string) => {
    send(text, scope);
  };

  const handleApproveTool = async (
    toolName: string,
    _summary: string,
    toolCallId?: string,
  ) => {
    if (!sessionId) return;
    try {
      await client.approveTool(sessionId, toolName, toolCallId);
    } catch (e) {
      console.error("[cowork] approveTool failed:", e);
    }
  };

  // Native file-drop: in managed mode upload into the project; in local-dir
  // mode copy directly into the chosen workdir so the agent sees it.
  useEffect(() => {
    let unlisten: (() => void) | undefined;
    (async () => {
      unlisten = await onFileDrop(async (paths) => {
        if (surface === "desktop") {
          if (!workdir) {
            setDropStatus("Pick a folder before dropping files");
            return;
          }
          for (const p of paths) {
            const name = p.split("/").pop() || "upload.bin";
            setDropStatus(`Copying ${name} into workdir…`);
            try {
              await copyIntoWorkdir(p, workdir);
              setDropStatus(`Copied ${name}`);
            } catch (e) {
              setDropStatus(`Copy failed: ${e}`);
            }
          }
          return;
        }
        if (!project) {
          setDropStatus("Select a project before dropping files");
          return;
        }
        for (const p of paths) {
          const name = p.split("/").pop() || "upload.bin";
          setDropStatus(`Uploading ${name}...`);
          try {
            const bytes = await readTauriFile(p);
            const copy = new Uint8Array(bytes.byteLength);
            copy.set(bytes);
            await client.uploadFile(
              project,
              new Blob([copy.buffer as ArrayBuffer]),
              name,
              "files",
            );
            setDropStatus(`Uploaded ${name}`);
          } catch (e) {
            setDropStatus(`Upload failed: ${e}`);
          }
        }
      });
    })();
    return () => {
      unlisten?.();
    };
  }, [client, project, surface, workdir]);

  // Menu events from the native shell.
  useEffect(() => {
    if (!isTauri()) return;
    let unlisten: (() => void) | undefined;
    (async () => {
      const { getCurrentWindow } = await import("@tauri-apps/api/window");
      unlisten = await getCurrentWindow().listen<string>("menu", (ev) => {
        switch (ev.payload) {
          case "new_project":
            reset();
            break;
          case "open_folder":
            void handlePickWorkdir();
            break;
          case "open_workspace":
            void openWorkspaceInFileManager();
            break;
        }
      });
    })();
    return () => {
      unlisten?.();
    };
  // handlePickWorkdir captures reset + setWorkdir; include reset in deps so
  // the listener sees the current closure. handlePickWorkdir itself is stable
  // across renders for our purposes.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reset]);

  const userId = token ? token.split("-")[0] : undefined;

  return (
    <div className="app">
      <Titlebar
        client={client}
        project={project}
        workdir={workdir}
        sessionId={sessionId}
        userId={userId}
        lastEventAt={lastEventAt}
        notifications={notifications}
        unreadCount={unreadNotifications}
        onMarkNotificationRead={markNotificationRead}
        onClearNotifications={clearNotifications}
        onJumpToSession={(sid) => void handleJumpFromNotification(sid)}
        onOpenSettings={() => setSettingsOpen(true)}
        onOpenPalette={() => setPaletteOpen(true)}
      />
      <div className="shell">
        {surface === "desktop" ? (
          <Sessions
            mode="local"
            client={client}
            workdir={workdir}
            sessionId={sessionId}
            sendingIds={sendingIds}
            waitingIds={waitingIds}
            userId={userId}
            onPickWorkdir={handlePickWorkdir}
            onSelectSession={handleSelectSession}
            onNewSession={handleNewSession}
            onDeleteSession={handleDeleteSession}
            onOpenSettings={() => setSettingsOpen(true)}
            onOpenPalette={() => setPaletteOpen(true)}
          />
        ) : (
          <Sessions
            mode="managed"
            client={client}
            project={project}
            sessionId={sessionId}
            sendingIds={sendingIds}
            waitingIds={waitingIds}
            userId={userId}
            onSelectProject={handleSelectProject}
            onSelectSession={handleSelectSession}
            onNewSession={handleNewSession}
            onDeleteSession={handleDeleteSession}
            onDeleteProject={handleDeleteProject}
            onOpenSettings={() => setSettingsOpen(true)}
            onOpenPalette={() => setPaletteOpen(true)}
          />
        )}

        <main className="pane chat">
          <Chat
            messages={messages}
            sending={sending}
            agents={agents}
            sessionId={sessionId}
            decidedToolIds={decidedToolIds}
            onMarkToolDecided={markToolDecided}
            trustedToolNames={trustedToolNames}
            onMarkToolTrusted={markToolTrusted}
            onSend={handleSend}
            onApproveTool={handleApproveTool}
            attach={
              workdir
                ? { mode: "local", workdir }
                : project
                  ? { mode: "managed", client, project }
                  : undefined
            }
          />
        </main>

        {surface === "desktop" ? (
          <Canvas mode="local" client={client} workdir={workdir} sessionId={sessionId} />
        ) : (
          <Canvas mode="managed" client={client} project={project} sessionId={sessionId} />
        )}
      </div>

      {settingsOpen && (
        <Settings
          client={client}
          sessionId={sessionId}
          userId={userId}
          surface={surface === "desktop" ? "local" : "managed"}
          onClose={() => setSettingsOpen(false)}
        />
      )}

      <CommandPalette
        open={paletteOpen}
        onClose={() => setPaletteOpen(false)}
        scope={paletteScope}
        client={client}
        messages={messages}
        activeSessionId={sessionId}
        onOpenFile={handleOpenFileFromPalette}
        onJumpToMessage={handleJumpToMessage}
        onPickSession={(sid, projectSlug) => {
          void handlePalettePickSession(sid, projectSlug);
        }}
        onPickProjectFile={(projectSlug, path) => {
          void handlePalettePickFile(projectSlug, path);
        }}
        onPickSessionMessage={(sid, index, projectSlug) => {
          void handlePalettePickSessionMessage(sid, index, projectSlug);
        }}
      />

      {dropStatus && (
        <div
          style={{
            position: "fixed",
            bottom: 24,
            left: "50%",
            transform: "translateX(-50%)",
            zIndex: 50,
            padding: "6px 14px",
            fontSize: 12,
            fontFamily: "var(--mono)",
            borderRadius: 999,
            background: "var(--paper-2)",
            border: "1px solid var(--line)",
            color: "var(--ink-2)",
            boxShadow: "var(--shadow-lg, 0 10px 30px rgba(0,0,0,0.15))",
          }}
        >
          {dropStatus}
        </div>
      )}
    </div>
  );
}

async function readTauriFile(path: string): Promise<Uint8Array> {
  const { invoke } = await import("@tauri-apps/api/core");
  const bytes = await invoke<number[]>("read_dropped_file", { path });
  return new Uint8Array(bytes);
}

export default App;
