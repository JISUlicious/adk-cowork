import { useEffect, useMemo, useState } from "react";
import { CoworkClient } from "./transport/client";
import { useChat } from "./hooks/useChat";
import { TopBar } from "./components/TopBar";
import { ChatPane } from "./components/ChatPane";
import { FileCanvas } from "./components/FileCanvas";
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
          setDropStatus(`Uploading ${name}…`);
          try {
            const bytes = await readTauriFile(p);
            // Copy into a fresh ArrayBuffer so Blob's type predicate is happy
            // (Uint8Array's backing buffer may be typed as SharedArrayBuffer).
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
    <div className="h-screen flex flex-col bg-white dark:bg-gray-950 text-gray-900 dark:text-gray-100">
      <TopBar
        client={client}
        project={project}
        sessionId={sessionId}
        onSelectProject={handleSelectProject}
        onSelectSession={handleSelectSession}
        onNewSession={handleNewSession}
      />
      <div className="flex-1 flex min-h-0">
        <div className="w-1/2 border-r border-gray-200 dark:border-gray-700 flex flex-col">
          <ChatPane messages={messages} sending={sending} onSend={handleSend} />
        </div>
        <div className="w-1/2 flex flex-col">
          <FileCanvas
            client={client}
            project={project}
            sessionId={sessionId}
          />
        </div>
      </div>
      {dropStatus && (
        <div className="px-3 py-1 text-xs bg-blue-50 dark:bg-blue-900/30 border-t border-blue-200 dark:border-blue-800">
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
