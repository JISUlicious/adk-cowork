/**
 * Global ⌘K command palette.
 *
 * Phase F.P6a — client-only. Scopes to the active session + its file
 * surface; a server-backed cross-session / cross-project search is
 * planned for P6b (``GET /v1/search``) and will merge in as a third
 * section.
 *
 * The palette opens as a modal overlay; keyboard: ↑/↓ move the
 * selection, Enter activates, Escape closes. Clicking a row activates
 * it too. Close-on-backdrop-click is standard palette UX.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import type { ChatMessage } from "../hooks/useChat";
import type { CoworkClient } from "../transport/client";
import { Icon } from "./atoms";

export type PaletteScope =
  | { mode: "managed"; project: string }
  | { mode: "local"; workdir: string };

interface Props {
  open: boolean;
  onClose: () => void;
  scope: PaletteScope | null;
  client: CoworkClient;
  messages: ChatMessage[];
  activeSessionId: string | null;
  onOpenFile: (path: string) => void;
  onJumpToMessage: (index: number) => void;
  /** Jump to another session (used for managed-mode global results). */
  onPickSession?: (sessionId: string, project?: string) => void;
  /** Open a file that may live in a different project. */
  onPickProjectFile?: (project: string, path: string) => void;
  /** Jump to a specific message in a (possibly different) session. */
  onPickSessionMessage?: (
    sessionId: string,
    index: number,
    project?: string,
  ) => void;
}

type Match =
  | { kind: "message"; index: number; preview: string; agent?: string }
  | { kind: "file"; path: string; name: string }
  | {
      kind: "remote-session";
      sessionId: string;
      title: string | null;
      project: string;
    }
  | {
      kind: "remote-file";
      project: string;
      path: string;
      name: string;
    }
  | {
      kind: "remote-message";
      sessionId: string;
      sessionTitle: string | null;
      project: string;
      index: number;
      preview: string;
    };

const MAX_PER_SECTION = 8;

export function CommandPalette({
  open,
  onClose,
  scope,
  client,
  messages,
  activeSessionId,
  onOpenFile,
  onJumpToMessage,
  onPickSession,
  onPickProjectFile,
  onPickSessionMessage,
}: Props) {
  const [q, setQ] = useState("");
  const [files, setFiles] = useState<Array<{ path: string; name: string }>>([]);
  const [selectedIdx, setSelectedIdx] = useState(0);
  const [remote, setRemote] = useState<{
    sessions: Array<{ session_id: string; title: string | null; project: string }>;
    files: Array<{ project: string; path: string; name: string }>;
    messages: Array<{
      session_id: string;
      session_title: string | null;
      project: string;
      index: number;
      preview: string;
    }>;
  }>({ sessions: [], files: [], messages: [] });
  const inputRef = useRef<HTMLInputElement>(null);

  // Reset on open; refresh the file listing each time so renames and
  // newly-created artifacts show up without a stale cache.
  useEffect(() => {
    if (!open) return;
    setQ("");
    setSelectedIdx(0);
    inputRef.current?.focus();
    if (!scope) {
      setFiles([]);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        if (scope.mode === "managed") {
          // Managed projects route user artifacts under ``files/``; the
          // other top-level entries (``scratch/``, ``sessions/``) are
          // runtime bookkeeping that would just be noise in the palette.
          const entries = await client.listFiles(scope.project, "files");
          if (cancelled) return;
          setFiles(
            entries
              .filter((e) => e.kind === "file")
              .map((e) => ({ path: `files/${e.name}`, name: e.name })),
          );
        } else {
          const { entries } = await client.listLocalFiles(scope.workdir, "");
          if (cancelled) return;
          setFiles(
            entries
              .filter((e) => e.kind === "file")
              .map((e) => ({ path: e.name, name: e.name })),
          );
        }
      } catch {
        if (!cancelled) setFiles([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, scope, client]);

  // Debounced server-backed search. Kicks off 200 ms after the user
  // stops typing so rapid keystrokes don't spam the endpoint; the
  // server itself caches each ``(user, q)`` for 30 s.
  useEffect(() => {
    if (!open) return;
    const needle = q.trim();
    if (!needle) {
      setRemote({ sessions: [], files: [], messages: [] });
      return;
    }
    let cancelled = false;
    const t = window.setTimeout(async () => {
      try {
        const r = await client.search(needle);
        if (!cancelled) setRemote(r);
      } catch {
        if (!cancelled) setRemote({ sessions: [], files: [], messages: [] });
      }
    }, 200);
    return () => {
      cancelled = true;
      window.clearTimeout(t);
    };
  }, [open, q, client]);

  const matches = useMemo<Match[]>(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return [];

    const msgMatches: Match[] = [];
    for (let i = 0; i < messages.length; i += 1) {
      const m = messages[i];
      const parts: string[] = [];
      if (m.text) parts.push(m.text);
      for (const s of m.segments ?? []) {
        if (s.kind === "text" && s.text) parts.push(s.text);
      }
      for (const tc of m.toolCalls ?? []) {
        parts.push(tc.name);
        for (const v of Object.values(tc.args ?? {})) {
          if (typeof v === "string") parts.push(v);
        }
      }
      const blob = parts.join(" ").toLowerCase();
      if (blob.includes(needle)) {
        const preview = makePreview(parts.join(" — "), needle);
        msgMatches.push({ kind: "message", index: i, preview, agent: m.agent });
        if (msgMatches.length >= MAX_PER_SECTION) break;
      }
    }

    const fileMatches: Match[] = [];
    for (const f of files) {
      if (f.name.toLowerCase().includes(needle)) {
        fileMatches.push({ kind: "file", path: f.path, name: f.name });
        if (fileMatches.length >= MAX_PER_SECTION) break;
      }
    }

    // Remote sections — dedupe session-scope hits so the same session
    // doesn't appear as both a local message hit and a remote one.
    const remoteSessionMatches: Match[] = remote.sessions
      .filter((s) => s.session_id !== activeSessionId)
      .slice(0, MAX_PER_SECTION)
      .map((s) => ({
        kind: "remote-session" as const,
        sessionId: s.session_id,
        title: s.title,
        project: s.project,
      }));

    const remoteFileMatches: Match[] = remote.files
      .filter(
        (f) =>
          !fileMatches.some(
            (local) => local.kind === "file" && local.path === f.path,
          ),
      )
      .slice(0, MAX_PER_SECTION)
      .map((f) => ({
        kind: "remote-file" as const,
        project: f.project,
        path: f.path,
        name: f.name,
      }));

    const remoteMessageMatches: Match[] = remote.messages
      .filter((m) => m.session_id !== activeSessionId)
      .slice(0, MAX_PER_SECTION)
      .map((m) => ({
        kind: "remote-message" as const,
        sessionId: m.session_id,
        sessionTitle: m.session_title,
        project: m.project,
        index: m.index,
        preview: m.preview,
      }));

    return [
      ...msgMatches,
      ...fileMatches,
      ...remoteSessionMatches,
      ...remoteFileMatches,
      ...remoteMessageMatches,
    ];
  }, [q, messages, files, remote, activeSessionId]);

  // Clamp selection when result count shrinks.
  useEffect(() => {
    if (selectedIdx >= matches.length) setSelectedIdx(0);
  }, [matches.length, selectedIdx]);

  const activate = (m: Match) => {
    switch (m.kind) {
      case "file":
        onOpenFile(m.path);
        break;
      case "message":
        onJumpToMessage(m.index);
        break;
      case "remote-session":
        onPickSession?.(m.sessionId, m.project);
        break;
      case "remote-file":
        onPickProjectFile?.(m.project, m.path);
        break;
      case "remote-message":
        onPickSessionMessage?.(m.sessionId, m.index, m.project);
        break;
    }
    onClose();
  };

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
        return;
      }
      if (matches.length === 0) return;
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setSelectedIdx((i) => (i + 1) % matches.length);
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setSelectedIdx((i) => (i - 1 + matches.length) % matches.length);
      } else if (e.key === "Enter") {
        e.preventDefault();
        activate(matches[selectedIdx]);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, matches, selectedIdx, onClose]);

  if (!open) return null;

  const msgCount = matches.filter((m) => m.kind === "message").length;
  const fileCount = matches.filter((m) => m.kind === "file").length;
  const remoteSessionCount = matches.filter(
    (m) => m.kind === "remote-session",
  ).length;
  const remoteFileCount = matches.filter((m) => m.kind === "remote-file").length;
  const remoteMsgCount = matches.filter(
    (m) => m.kind === "remote-message",
  ).length;

  return (
    <div
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.28)",
        zIndex: 60,
        display: "flex",
        alignItems: "flex-start",
        justifyContent: "center",
        paddingTop: "14vh",
      }}
    >
      <div
        style={{
          width: 560,
          maxWidth: "90vw",
          maxHeight: "70vh",
          display: "flex",
          flexDirection: "column",
          background: "var(--paper)",
          border: "1px solid var(--line)",
          borderRadius: "var(--radius-lg, 10px)",
          boxShadow: "0 12px 42px rgba(0,0,0,0.22)",
          overflow: "hidden",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 10,
            padding: "12px 14px",
            borderBottom: "1px solid var(--line)",
          }}
        >
          <Icon name="search" size={14} />
          <input
            ref={inputRef}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search messages and files in this session…"
            style={{
              flex: 1,
              background: "transparent",
              border: 0,
              outline: 0,
              fontSize: "var(--fs-md)",
              color: "var(--ink)",
            }}
          />
          <span
            style={{
              fontFamily: "var(--mono)",
              fontSize: 10,
              color: "var(--ink-4)",
            }}
          >
            esc
          </span>
        </div>

        <div style={{ flex: 1, overflowY: "auto" }}>
          {!q.trim() ? (
            <EmptyHint text="Type to search messages in this session and files in the current scope." />
          ) : matches.length === 0 ? (
            <EmptyHint text="No matches." />
          ) : (
            <>
              {msgCount > 0 && (
                <SectionHeader label="Messages (this session)" count={msgCount} />
              )}
              {matches.map((m, i) =>
                m.kind === "message" ? (
                  <ResultRow
                    key={`m-${m.index}`}
                    active={i === selectedIdx}
                    onMouseEnter={() => setSelectedIdx(i)}
                    onClick={() => activate(m)}
                    leading={<Icon name="brain" size={11} />}
                    title={m.preview}
                    sub={m.agent ? `· ${m.agent}` : undefined}
                  />
                ) : null,
              )}
              {fileCount > 0 && (
                <SectionHeader label="Files (this scope)" count={fileCount} />
              )}
              {matches.map((m, i) =>
                m.kind === "file" ? (
                  <ResultRow
                    key={`f-${m.path}`}
                    active={i === selectedIdx}
                    onMouseEnter={() => setSelectedIdx(i)}
                    onClick={() => activate(m)}
                    leading={<Icon name="doc" size={11} />}
                    title={m.name}
                    sub={m.path !== m.name ? m.path : undefined}
                  />
                ) : null,
              )}
              {remoteSessionCount > 0 && (
                <SectionHeader label="Other sessions" count={remoteSessionCount} />
              )}
              {matches.map((m, i) =>
                m.kind === "remote-session" ? (
                  <ResultRow
                    key={`rs-${m.sessionId}`}
                    active={i === selectedIdx}
                    onMouseEnter={() => setSelectedIdx(i)}
                    onClick={() => activate(m)}
                    leading={<Icon name="doc" size={11} />}
                    title={m.title || m.sessionId.slice(0, 8)}
                    sub={`· ${m.project}`}
                  />
                ) : null,
              )}
              {remoteFileCount > 0 && (
                <SectionHeader label="Other projects · files" count={remoteFileCount} />
              )}
              {matches.map((m, i) =>
                m.kind === "remote-file" ? (
                  <ResultRow
                    key={`rf-${m.project}-${m.path}`}
                    active={i === selectedIdx}
                    onMouseEnter={() => setSelectedIdx(i)}
                    onClick={() => activate(m)}
                    leading={<Icon name="doc" size={11} />}
                    title={m.name}
                    sub={`${m.project} · ${m.path}`}
                  />
                ) : null,
              )}
              {remoteMsgCount > 0 && (
                <SectionHeader
                  label="Other sessions · messages"
                  count={remoteMsgCount}
                />
              )}
              {matches.map((m, i) =>
                m.kind === "remote-message" ? (
                  <ResultRow
                    key={`rm-${m.sessionId}-${m.index}`}
                    active={i === selectedIdx}
                    onMouseEnter={() => setSelectedIdx(i)}
                    onClick={() => activate(m)}
                    leading={<Icon name="brain" size={11} />}
                    title={m.preview}
                    sub={`${m.project} · ${m.sessionTitle || m.sessionId.slice(0, 8)}`}
                  />
                ) : null,
              )}
            </>
          )}
        </div>

        <div
          style={{
            display: "flex",
            gap: 14,
            padding: "8px 14px",
            borderTop: "1px solid var(--line)",
            fontSize: 10,
            fontFamily: "var(--mono)",
            color: "var(--ink-4)",
          }}
        >
          <span><kbd>↑↓</kbd> navigate</span>
          <span><kbd>↵</kbd> open</span>
          <span><kbd>esc</kbd> close</span>
        </div>
      </div>
    </div>
  );
}

function SectionHeader({ label, count }: { label: string; count: number }) {
  return (
    <div
      style={{
        padding: "8px 14px 4px",
        fontFamily: "var(--mono)",
        fontSize: 10,
        color: "var(--ink-4)",
        textTransform: "uppercase",
        letterSpacing: 0.4,
      }}
    >
      {label} <span style={{ color: "var(--ink-4)", marginLeft: 6 }}>{count}</span>
    </div>
  );
}

function ResultRow({
  active,
  leading,
  title,
  sub,
  onClick,
  onMouseEnter,
}: {
  active: boolean;
  leading: React.ReactNode;
  title: string;
  sub?: string;
  onClick: () => void;
  onMouseEnter: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      onMouseEnter={onMouseEnter}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        width: "100%",
        padding: "8px 14px",
        background: active ? "var(--paper-2)" : "transparent",
        textAlign: "left",
        cursor: "pointer",
        borderLeft: active ? "2px solid var(--accent)" : "2px solid transparent",
      }}
    >
      <span
        style={{
          width: 18,
          display: "grid",
          placeItems: "center",
          color: "var(--ink-3)",
        }}
      >
        {leading}
      </span>
      <span
        style={{
          flex: 1,
          minWidth: 0,
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
          fontSize: "var(--fs-sm)",
          color: "var(--ink)",
        }}
      >
        {title}
      </span>
      {sub && (
        <span
          style={{
            flexShrink: 0,
            fontSize: 11,
            color: "var(--ink-4)",
            fontFamily: "var(--mono)",
          }}
        >
          {sub}
        </span>
      )}
    </button>
  );
}

function EmptyHint({ text }: { text: string }) {
  return (
    <div
      style={{
        padding: "36px 20px",
        textAlign: "center",
        fontSize: "var(--fs-sm)",
        color: "var(--ink-4)",
        fontFamily: "var(--serif)",
      }}
    >
      {text}
    </div>
  );
}

/** Return a snippet of ``source`` centered on the first occurrence of
 *  ``needle`` (case-insensitive). The snippet is trimmed to ~120 chars
 *  with ellipses if the source is longer. */
function makePreview(source: string, needle: string): string {
  const idx = source.toLowerCase().indexOf(needle);
  if (idx === -1) return source.slice(0, 120);
  const start = Math.max(0, idx - 40);
  const end = Math.min(source.length, idx + needle.length + 60);
  const prefix = start > 0 ? "… " : "";
  const suffix = end < source.length ? " …" : "";
  return `${prefix}${source.slice(start, end).replace(/\s+/g, " ")}${suffix}`;
}
