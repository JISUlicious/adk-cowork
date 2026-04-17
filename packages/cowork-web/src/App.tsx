import { useEffect, useMemo, useState } from "react";
import { CoworkClient } from "./transport/client";
import { useChat } from "./hooks/useChat";
import { TopBar } from "./components/TopBar";
import { Sidebar } from "./components/Sidebar";
import { ChatPane } from "./components/ChatPane";
import { FileCanvas } from "./components/FileCanvas";
import { StatusBar } from "./components/StatusBar";
import {
  isTauri,
  onFileDrop,
  openWorkspaceInFileManager,
} from "./transport/tauri";

interface AppProps {
  baseUrl?: string;
  token?: string;
}

function App({ baseUrl, token }: AppProps = {}) {
  const client = useMemo(() => new CoworkClient(baseUrl, token), [baseUrl, token]);
  // eslint-disable-next-line no-console
  console.log("[cowork] client config", {
    baseUrl: baseUrl || "(relative)",
    hasToken: Boolean(token),
    origin: typeof window !== "undefined" ? window.location.origin : "?",
  });
  const [project, setProject] = useState<string | null>(null);
  const [dropStatus, setDropStatus] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const { messages, sending, send, reset, newSession, resumeSession, sessionId } =
    useChat(client);

  const handleSelectProject = (slug: string) => {
    if (slug !== project) {
      reset();
      setProject(slug);
    }
  };

  const handleSelectSession = async (sid: string) => {
    if (sid === sessionId) return;
    if (!project) return;
    await resumeSession(sid, project);
  };

  const handleNewSession = () => {
    if (project) {
      void newSession(project);
    } else {
      reset();
    }
  };

  const handleDeleteSession = async (sid: string) => {
    if (!project) return;
    try {
      await client.deleteSession(project, sid);
      // If the deleted session is active, reset the chat
      if (sid === sessionId) reset();
    } catch (e) {
      console.error("[cowork] delete session failed:", e);
    }
  };

  const handleSend = (text: string) => {
    send(text, project || undefined);
  };

  // Native file-drop: upload dropped files into the active project's files/.
  useEffect(() => {
    let unlisten: (() => void) | undefined;
    (async () => {
      unlisten = await onFileDrop(async (paths) => {
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
  }, [client, project]);

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
          case "open_workspace":
            void openWorkspaceInFileManager();
            break;
        }
      });
    })();
    return () => {
      unlisten?.();
    };
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
            <Sidebar
              client={client}
              project={project}
              sessionId={sessionId}
              onSelectProject={handleSelectProject}
              onSelectSession={handleSelectSession}
              onNewSession={handleNewSession}
              onDeleteSession={handleDeleteSession}
            />
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
            <ChatPane messages={messages} sending={sending} onSend={handleSend} />
          </div>
          <StatusBar sessionId={sessionId} />
        </main>

        {/* Right panel — files */}
        <aside className="hidden xl:flex shrink-0 w-80 flex-col overflow-hidden rounded-[24px] border border-[var(--dls-border)] bg-[var(--dls-surface)] shadow-[var(--dls-card-shadow)]">
          <FileCanvas
            client={client}
            project={project}
            sessionId={sessionId}
          />
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
