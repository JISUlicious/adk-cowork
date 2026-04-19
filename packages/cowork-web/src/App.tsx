import { useEffect, useMemo, useState } from "react";
import { CoworkClient } from "./transport/client";
import { useChat } from "./hooks/useChat";
import { TopBar } from "./components/TopBar";
import { Sidebar } from "./components/Sidebar";
import { DesktopSidebar } from "./components/DesktopSidebar";
import { ChatPane } from "./components/ChatPane";
import { FileCanvas } from "./components/FileCanvas";
import { DesktopFileCanvas } from "./components/DesktopFileCanvas";
import { StatusBar } from "./components/StatusBar";
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
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const { messages, sending, send, reset, newSession, resumeSession, sessionId } =
    useChat(client);

  // Scope passed to useChat — determines managed vs local-dir session type.
  const scope = workdir ? { workdir } : project ? { project } : undefined;

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

  const handleApproveTool = async (toolName: string, _summary: string) => {
    if (!sessionId) return;
    try {
      await client.approveTool(sessionId, toolName);
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

  return (
    <div className="h-[100dvh] min-h-screen w-full overflow-hidden bg-[var(--dls-app-bg)] text-[var(--dls-text-primary)] font-sans p-3 md:p-4">
      <div className="flex h-full w-full gap-3 md:gap-4">
        {/* Left sidebar */}
        <aside
          className={`${
            sidebarOpen ? "flex" : "hidden"
          } relative shrink-0 w-64 flex-col overflow-hidden rounded-[24px] border border-[var(--dls-border)] bg-[var(--dls-sidebar)] p-2.5 lg:flex`}
        >
          <div className="shrink-0 px-2 py-2 mb-2">
            <span className="text-[15px] font-semibold text-[var(--dls-text-primary)]">
              Cowork
            </span>
          </div>
          <div className="flex min-h-0 flex-1">
            {surface === "desktop" ? (
              <DesktopSidebar
                client={client}
                workdir={workdir}
                sessionId={sessionId}
                onPickWorkdir={handlePickWorkdir}
                onSelectSession={handleSelectSession}
                onNewSession={handleNewSession}
                onDeleteSession={handleDeleteSession}
              />
            ) : (
              <Sidebar
                client={client}
                project={project}
                sessionId={sessionId}
                onSelectProject={handleSelectProject}
                onSelectSession={handleSelectSession}
                onNewSession={handleNewSession}
                onDeleteSession={handleDeleteSession}
                onDeleteProject={handleDeleteProject}
              />
            )}
          </div>
        </aside>

        {/* Main panel — chat */}
        <main className="min-w-0 flex-1 flex flex-col overflow-hidden rounded-[24px] border border-[var(--dls-border)] bg-[var(--dls-surface)] shadow-[var(--dls-shell-shadow)]">
          <TopBar
            client={client}
            project={project}
            sessionId={sessionId}
            onToggleSidebar={() => setSidebarOpen((v) => !v)}
          />
          <div className="flex-1 flex flex-col min-h-0">
            <ChatPane
              messages={messages}
              sending={sending}
              onSend={handleSend}
              onApproveTool={handleApproveTool}
            />
          </div>
          <StatusBar sessionId={sessionId} />
        </main>

        {/* Right panel — files. Web surface speaks the project API
            (scratch/+files/ layout); desktop surface browses the
            user-picked workdir. */}
        <aside className="hidden xl:flex shrink-0 w-80 flex-col overflow-hidden rounded-[24px] border border-[var(--dls-border)] bg-[var(--dls-surface)] shadow-[var(--dls-card-shadow)]">
          {surface === "desktop" ? (
            <DesktopFileCanvas
              client={client}
              workdir={workdir}
              sessionId={sessionId}
            />
          ) : (
            <FileCanvas
              client={client}
              project={project}
              sessionId={sessionId}
            />
          )}
        </aside>
      </div>

      {/* Drop status overlay */}
      {dropStatus && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 px-4 py-2 text-xs rounded-full bg-[var(--dls-surface)] border border-[var(--dls-border)] shadow-[var(--dls-shell-shadow)] text-[var(--dls-text-secondary)]">
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
