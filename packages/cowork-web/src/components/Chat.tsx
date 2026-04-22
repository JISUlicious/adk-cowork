/**
 * Chat pane — design-system port of the legacy ``ChatPane``.
 *
 * Uses the warm-editorial markup (``.msg`` / ``.av`` / ``.by`` /
 * ``.body`` for assistant turns; ``.msg-user`` for user turns; the
 * ``.composer`` block for the input area). Per-message agent identity
 * comes from ``ChatMessage.agent`` populated by ``useChat``; the
 * agent's color drives the avatar swatch via ``agentStyle``.
 *
 * Tool-call chrome is owned by ``ToolCallCard`` which honors the
 * ``toolStyle`` preference (``collapsed`` | ``expanded`` | ``terminal``).
 * Approval chrome is inline inside ``ToolCallCard``; the banner /
 * queue variants from the design prototype were dropped in Phase
 * F.P1 because they were cosmetic with no behavioural difference.
 */

import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ChatMessage } from "../hooks/useChat";
import { usePreferences } from "../preferences";
import type { CoworkClient } from "../transport/client";
import { copyIntoWorkdir, isTauri, pickFiles, readLocalFileBytes } from "../transport/tauri";
import { agentStyle, AgentStack, Icon } from "./atoms";
import { ToolCallCard } from "./ToolCallCard";

/** Context the composer needs to turn a user-picked file into a path
 *  the agent can read via ``fs_read``. Derived from the currently
 *  active surface + selection in ``App``. */
export type AttachContext =
  | { mode: "managed"; client: CoworkClient; project: string }
  | { mode: "local"; workdir: string };

interface Attachment {
  /** Relative path inside the project (managed) or absolute path inside
   *  the workdir (local) — whatever the agent's ``fs_read`` will resolve. */
  path: string;
  /** Display-only short name for the chip. */
  displayName: string;
}

/** Sub-agents the composer can route to via ``@mention``. Keep in
 *  sync with ``cowork_core.agents.root_agent`` sub_agents list. Typos
 *  still send — the root agent calls them out in reply rather than
 *  silently failing, matching the AT_MENTION_PROTOCOL directive. */
const AT_MENTION_AGENTS = ["researcher", "writer", "analyst", "reviewer"] as const;

interface Props {
  messages: ChatMessage[];
  sending: boolean;
  agents: string[];
  client: CoworkClient;
  sessionId?: string | null;
  sessionTitle?: string;
  /** Tool-call ids the user has already approved/denied in this
   *  session. ``ToolCallCard`` uses this to hide the banner after the
   *  page reloads or the session is re-entered. */
  decidedToolIds?: Set<string>;
  onMarkToolDecided?: (toolId: string) => void;
  /** Tool *names* the user has trusted for the session. A subsequent
   *  ``confirmation_required`` for a trusted tool is auto-approved
   *  without showing the banner — so approving ``python_exec_run``
   *  once covers the agent's next invocation even after the app
   *  relaunches and the server's approval counter is empty. */
  trustedToolNames?: Set<string>;
  onMarkToolTrusted?: (toolName: string) => void;
  onSend: (text: string) => void;
  onApproveTool?: (
    toolName: string,
    summary: string,
    toolCallId?: string,
  ) => void | Promise<void>;
  onDenyTool?: (toolName: string, summary: string) => void;
  /** Attachment upload context. When undefined the composer's attach
   *  button is disabled (no project / workdir selected yet). */
  attach?: AttachContext;
}

export function Chat({
  messages,
  sending,
  agents,
  client,
  sessionId,
  sessionTitle,
  decidedToolIds,
  onMarkToolDecided,
  onSend,
  onApproveTool,
  onDenyTool,
  attach,
}: Props) {
  const [prefs] = usePreferences();
  const [input, setInput] = useState("");
  const [attached, setAttached] = useState<Attachment[]>([]);
  const [attachBusy, setAttachBusy] = useState(false);
  const [attachError, setAttachError] = useState<string | null>(null);
  // Tier E.E2 — @-mention autocomplete + auto-route toggle.
  const [atMenuOpen, setAtMenuOpen] = useState(false);
  const [atMenuQuery, setAtMenuQuery] = useState("");
  const [atMenuIdx, setAtMenuIdx] = useState(0);
  const [autoRoute, setAutoRoute] = useState(true);
  const bodyRef = useRef<HTMLDivElement>(null);
  const taRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Fetch the session's auto-route flag whenever the session switches.
  // Missing session falls back to the server default (True) without an
  // HTTP round-trip — the composer chip is meant to be cheap to render.
  useEffect(() => {
    if (!sessionId) {
      setAutoRoute(true);
      return;
    }
    client
      .getSessionAutoRoute(sessionId)
      .then(setAutoRoute)
      .catch(() => setAutoRoute(true));
  }, [client, sessionId]);

  const toggleAutoRoute = async () => {
    if (!sessionId) return;
    const next = !autoRoute;
    setAutoRoute(next); // optimistic
    try {
      const confirmed = await client.setSessionAutoRoute(sessionId, next);
      setAutoRoute(confirmed);
    } catch {
      setAutoRoute(!next);
    }
  };

  /** Detect an active ``@<token>`` at the textarea cursor. Returns
   *  ``null`` when the caret isn't on an @-mention, otherwise the
   *  matched query (without the leading ``@``) and the start index of
   *  the ``@`` so we can splice cleanly on pick. */
  const detectAtMention = (
    value: string,
    cursor: number,
  ): { query: string; start: number } | null => {
    let i = cursor;
    while (i > 0 && /[A-Za-z0-9_-]/.test(value.charAt(i - 1))) i--;
    if (i === 0 || value.charAt(i - 1) !== "@") return null;
    // ``@`` must be at start-of-message or follow whitespace — otherwise
    // the user is probably mid-word / writing an email.
    if (i - 1 > 0 && !/\s/.test(value.charAt(i - 2))) return null;
    return { query: value.slice(i, cursor).toLowerCase(), start: i - 1 };
  };

  const atMatches = AT_MENTION_AGENTS.filter((name) =>
    name.toLowerCase().startsWith(atMenuQuery),
  );

  const refreshAtMenu = (value: string, cursor: number | null | undefined) => {
    if (cursor == null) {
      setAtMenuOpen(false);
      return;
    }
    const mention = detectAtMention(value, cursor);
    if (!mention) {
      setAtMenuOpen(false);
      return;
    }
    setAtMenuQuery(mention.query);
    setAtMenuOpen(true);
    setAtMenuIdx(0);
  };

  const applyAtMention = (agentName: string) => {
    const el = taRef.current;
    if (!el) return;
    const cursor = el.selectionStart ?? input.length;
    const mention = detectAtMention(input, cursor);
    if (!mention) {
      setAtMenuOpen(false);
      return;
    }
    const before = input.slice(0, mention.start);
    const after = input.slice(cursor);
    const inserted = `@${agentName} `;
    const next = before + inserted + after;
    setInput(next);
    setAtMenuOpen(false);
    const nextCursor = before.length + inserted.length;
    requestAnimationFrame(() => {
      el.focus();
      el.setSelectionRange(nextCursor, nextCursor);
    });
  };

  useEffect(() => {
    bodyRef.current?.scrollTo({ top: bodyRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    const el = taRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 180)}px`;
  }, [input]);

  const submit = () => {
    const trimmed = input.trim();
    if ((!trimmed && attached.length === 0) || sending) return;
    const body = attached.length
      ? `Attached files:\n${attached.map((a) => `- @${a.path}`).join("\n")}\n\n${trimmed}`
      : trimmed;
    onSend(body);
    setInput("");
    setAttached([]);
    setAttachError(null);
  };

  /** Reset the native input so re-picking the same file re-fires ``change``. */
  const resetFileInput = () => {
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const addAttachment = (a: Attachment) =>
    setAttached((prev) => [...prev, a]);

  const removeAttachment = (path: string) =>
    setAttached((prev) => prev.filter((a) => a.path !== path));

  /** Browser <input type="file"> path: bytes are in-memory already, so
   *  we can upload directly without touching the disk. Managed mode
   *  only — web + local-dir doesn't have a writable backing store. */
  const onWebFilesPicked = async (files: FileList | null) => {
    if (!files || !files.length || !attach) return;
    if (attach.mode !== "managed") {
      setAttachError("Local-dir mode needs the desktop app to attach files.");
      return;
    }
    setAttachBusy(true);
    setAttachError(null);
    try {
      for (const f of Array.from(files)) {
        const r = await attach.client.uploadFile(attach.project, f, f.name, "files");
        addAttachment({ path: r.path, displayName: r.name });
      }
    } catch (e) {
      setAttachError(`Upload failed: ${e}`);
    } finally {
      setAttachBusy(false);
      resetFileInput();
    }
  };

  /** Desktop path: pick native paths, then either copy into the workdir
   *  (local mode) or stream bytes into the project (managed mode). */
  const onAttachClick = async () => {
    if (!attach) return;
    if (!isTauri()) {
      fileInputRef.current?.click();
      return;
    }
    setAttachBusy(true);
    setAttachError(null);
    try {
      const paths = await pickFiles();
      for (const src of paths) {
        const name = src.split("/").pop() || "upload.bin";
        if (attach.mode === "local") {
          const dest = await copyIntoWorkdir(src, attach.workdir);
          addAttachment({ path: dest, displayName: name });
        } else {
          const bytes = await readLocalFileBytes(src);
          const copy = new Uint8Array(bytes.byteLength);
          copy.set(bytes);
          const r = await attach.client.uploadFile(
            attach.project,
            new Blob([copy.buffer as ArrayBuffer]),
            name,
            "files",
          );
          addAttachment({ path: r.path, displayName: r.name });
        }
      }
    } catch (e) {
      setAttachError(`Attach failed: ${e}`);
    } finally {
      setAttachBusy(false);
    }
  };

  const onKey = (e: React.KeyboardEvent) => {
    if (atMenuOpen && atMatches.length > 0) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setAtMenuIdx((i) => (i + 1) % atMatches.length);
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setAtMenuIdx((i) => (i - 1 + atMatches.length) % atMatches.length);
        return;
      }
      if (e.key === "Tab" || (e.key === "Enter" && !e.shiftKey && !(e.metaKey || e.ctrlKey))) {
        e.preventDefault();
        applyAtMention(atMatches[atMenuIdx]);
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        setAtMenuOpen(false);
        return;
      }
    }
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      submit();
    } else if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  const headerStatus = sending ? "running" : "idle";

  return (
    <>
      <div className="chat-head">
        {agents.length > 0 && <AgentStack agents={agents} size={22} />}
        <div className="sess-title" style={{ flex: 1, minWidth: 0, display: "flex", alignItems: "baseline", gap: 8, overflow: "hidden" }}>
          <span style={{ fontFamily: "var(--serif)", fontSize: "var(--fs-xl)", color: "var(--ink)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {sessionTitle?.trim() || (sessionId ? "Untitled session" : "No session")}
          </span>
          {!sessionTitle?.trim() && sessionId && (
            <span style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-4)", flexShrink: 0 }}>
              {sessionId.slice(0, 8)}
            </span>
          )}
        </div>
        <span
          className={`tag ${headerStatus}`}
          style={{
            fontFamily: "var(--mono)",
            fontSize: 11,
            padding: "2px 8px",
            borderRadius: 10,
            background: sending ? "var(--accent-soft)" : "var(--paper-3)",
            color: sending ? "var(--accent-ink)" : "var(--ink-3)",
          }}
        >
          ● {headerStatus}
        </span>
      </div>

      <div className="chat-body" ref={bodyRef}>
        <div className="chat-inner">
          {messages.length === 0 && (
            <div style={{ padding: "60px 0", textAlign: "center", color: "var(--ink-3)", fontFamily: "var(--serif)", fontSize: "var(--fs-lg)" }}>
              Start the conversation.
            </div>
          )}
          {messages.map((m, i) => {
            // A confirmation banner is only actionable on the latest
            // unresolved turn. If any message comes after this one —
            // especially a user message like "Approved: …" — the user
            // has already responded and the banner in this row is
            // history, not an open decision.
            const historical = i < messages.length - 1;
            return (
              <div key={i} data-msg-index={i}>
                <MessageRow
                  m={m}
                  historical={historical}
                  toolStyle={prefs.toolStyle}
                  decidedToolIds={decidedToolIds}
                  onMarkToolDecided={onMarkToolDecided}
                  onApproveTool={onApproveTool}
                  onDenyTool={onDenyTool}
                  onSend={onSend}
                />
              </div>
            );
          })}
          {sending && <ThinkingDots />}
        </div>
      </div>

      <div className="composer">
        <div className="composer-inner">
          {attached.length > 0 && (
            <div className="composer-attachments">
              {attached.map((a) => (
                <span key={a.path} className="artifact-ref" title={a.path}>
                  <span className="ico">
                    <Icon name="doc" size={11} />
                  </span>
                  <span className="nm">{a.displayName}</span>
                  <button
                    type="button"
                    className="rm"
                    title="Remove"
                    onClick={() => removeAttachment(a.path)}
                  >
                    ×
                  </button>
                </span>
              ))}
            </div>
          )}
          <div style={{ position: "relative" }}>
            <textarea
              ref={taRef}
              value={input}
              onChange={(e) => {
                setInput(e.target.value);
                refreshAtMenu(e.target.value, e.target.selectionStart);
              }}
              onKeyUp={(e) => {
                // Cursor can move without content changing (arrow keys,
                // Home/End, mouse click). Recompute @-mention state so
                // the menu tracks the caret.
                const el = e.target as HTMLTextAreaElement;
                refreshAtMenu(el.value, el.selectionStart);
              }}
              onClick={(e) => {
                const el = e.target as HTMLTextAreaElement;
                refreshAtMenu(el.value, el.selectionStart);
              }}
              onBlur={() => {
                // Blur fires before mousedown on the menu buttons — delay
                // the close so a click still lands. onMouseDown on the
                // menu preventDefaults to keep the textarea focused, so
                // most users never hit this path, but it's the fallback.
                window.setTimeout(() => setAtMenuOpen(false), 120);
              }}
              onKeyDown={onKey}
              placeholder={
                agents.length
                  ? `Reply to ${agents.map(prettyAgent).join(", ")}…  Use @ to target one.`
                  : "Send a message to get started…"
              }
              rows={2}
              disabled={sending}
            />
            {atMenuOpen && atMatches.length > 0 && (
              <div
                style={{
                  position: "absolute",
                  bottom: "calc(100% + 4px)",
                  left: 10,
                  minWidth: 180,
                  background: "var(--paper)",
                  border: "1px solid var(--line)",
                  borderRadius: "var(--radius-md)",
                  boxShadow: "0 8px 22px rgba(0,0,0,0.15)",
                  zIndex: 20,
                  overflow: "hidden",
                }}
                onMouseDown={(e) => e.preventDefault()}
              >
                {atMatches.map((name, i) => (
                  <button
                    key={name}
                    type="button"
                    onClick={() => applyAtMention(name)}
                    onMouseEnter={() => setAtMenuIdx(i)}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 8,
                      width: "100%",
                      padding: "6px 10px",
                      background:
                        i === atMenuIdx ? "var(--paper-2)" : "transparent",
                      textAlign: "left",
                      cursor: "pointer",
                    }}
                  >
                    <span
                      style={{
                        fontFamily: "var(--mono)",
                        fontSize: 11,
                        color: "var(--ink-3)",
                      }}
                    >
                      @
                    </span>
                    <span style={{ fontSize: "var(--fs-sm)", color: "var(--ink)" }}>
                      {name}
                    </span>
                  </button>
                ))}
              </div>
            )}
          </div>
          <div className="composer-row">
            <input
              ref={fileInputRef}
              type="file"
              multiple
              style={{ display: "none" }}
              onChange={(e) => void onWebFilesPicked(e.target.files)}
            />
            <button
              className="iconbtn"
              type="button"
              onClick={() => void onAttachClick()}
              disabled={!attach || attachBusy || sending}
              title={attach ? (attachBusy ? "Uploading…" : "Attach files") : "Select a project or folder first"}
            >
              <Icon name="more" size={15} />
            </button>
            <button
              type="button"
              onClick={() => void toggleAutoRoute()}
              disabled={!sessionId}
              title={
                sessionId
                  ? autoRoute
                    ? "Auto-route @-mentions (click to disable)"
                    : "Auto-route disabled — @-mentions go to the root"
                  : "Open a session to toggle @-mention routing"
              }
              style={{
                padding: "2px 8px",
                borderRadius: 12,
                fontFamily: "var(--mono)",
                fontSize: 11,
                border: "1px solid var(--line)",
                background: autoRoute ? "var(--accent-soft)" : "var(--paper-3)",
                color: autoRoute ? "var(--accent-ink)" : "var(--ink-3)",
                opacity: sessionId ? 1 : 0.5,
                cursor: sessionId ? "pointer" : "not-allowed",
              }}
            >
              @-route {autoRoute ? "on" : "off"}
            </button>
            <button
              className="send"
              type="button"
              onClick={submit}
              disabled={sending || (!input.trim() && attached.length === 0)}
              title="Send (⌘⏎)"
              style={{ marginLeft: "auto" }}
            >
              ↑
            </button>
          </div>
        </div>
        <div className="composer-hint">
          <span>
            <span className="k">⌘⏎</span> send
          </span>
          <span>
            <span className="k">@</span> target agent
          </span>
          {attachError && (
            <span style={{ color: "var(--err, #c33)" }}>{attachError}</span>
          )}
          {agents.length > 0 && (
            <span style={{ marginLeft: "auto" }}>{agents.length} agent{agents.length === 1 ? "" : "s"} in session</span>
          )}
        </div>
      </div>
    </>
  );
}

function MessageRow({
  m,
  historical,
  toolStyle,
  decidedToolIds,
  onMarkToolDecided,
  onApproveTool,
  onDenyTool,
  onSend,
}: {
  m: ChatMessage;
  historical?: boolean;
  toolStyle: "collapsed" | "expanded" | "terminal";
  decidedToolIds?: Set<string>;
  onMarkToolDecided?: (toolId: string) => void;
  onApproveTool?: (toolName: string, summary: string) => void | Promise<void>;
  onDenyTool?: (toolName: string, summary: string) => void;
  onSend: (text: string) => void;
}) {
  if (m.role === "user") {
    return (
      <div className="msg-user">
        <div className="msg-user-inner">
          <div className="msg-user-meta">
            <span>You</span>
          </div>
          <div className="msg-user-bubble user-bubble">
            <p>{m.text}</p>
          </div>
        </div>
        <div className="av-user">·</div>
      </div>
    );
  }

  if (m.role === "compaction") {
    return <CompactionSeparator m={m} />;
  }

  const s = agentStyle(m.agent);
  return (
    <div className="msg">
      <div className="av" style={{ background: s.color }} title={m.agent ?? ""}>
        {s.letter}
      </div>
      <div>
        <div className="by">
          <span>{prettyAgent(m.agent)}</span>
          <span className="role">{prettyRole(m.agent)}</span>
        </div>
        {m.thought && (
          <details style={{ marginBottom: 8 }}>
            <summary style={{ fontSize: "var(--fs-xs)", color: "var(--ink-3)", cursor: "pointer", fontFamily: "var(--mono)" }}>
              <span style={{ display: "inline-flex", alignItems: "center", gap: 5, verticalAlign: "middle" }}>
                <Icon name="brain" size={11} /> thinking
              </span>
            </summary>
            <div
              style={{
                fontSize: "var(--fs-sm)",
                color: "var(--ink-2)",
                fontStyle: "italic",
                padding: "6px 10px",
                borderLeft: "2px solid var(--line)",
                margin: "4px 0 8px",
                fontFamily: "var(--serif)",
                whiteSpace: "pre-wrap",
              }}
            >
              {m.thought}
            </div>
          </details>
        )}
        {renderSegments(m, {
          historical,
          toolStyle,
          decidedToolIds,
          onMarkToolDecided,
          onApproveTool,
          onDenyTool,
          onSend,
        })}
      </div>
    </div>
  );
}

/**
 * Render an assistant message in arrival order.
 *
 * Each ADK event carries a list of ``parts`` — text or function calls —
 * and the agent may emit several events in a single turn. Storing them
 * as ordered ``segments`` and rendering through here means the reader
 * sees narration and tool calls interleave exactly the way the model
 * produced them, instead of the previous "all text first, all tool
 * calls at the end" layout. Legacy messages without segments (empty
 * array) fall back to the old text-then-tools shape.
 */
function renderSegments(
  m: ChatMessage,
  handlers: {
    historical?: boolean;
    toolStyle: "collapsed" | "expanded" | "terminal";
    decidedToolIds?: Set<string>;
    onMarkToolDecided?: (toolId: string) => void;
    onApproveTool?: (
      toolName: string,
      summary: string,
      toolCallId?: string,
    ) => void | Promise<void>;
    onDenyTool?: (toolName: string, summary: string) => void;
    onSend: (text: string) => void;
  },
): React.ReactNode {
  const renderTool = (tc: ReturnType<typeof findTool>) => {
    if (!tc) return null;
    // A confirmation tool call in a non-latest message has already
    // been responded to (the user's next message would have been
    // pushed after it), so treat it as decided from a UI standpoint
    // regardless of whether we have it in ``decidedToolIds``.
    const decided =
      handlers.historical ||
      (handlers.decidedToolIds?.has(tc.id) ?? false);
    return (
      <ToolCallCard
        key={tc.id}
        entry={tc}
        toolStyle={handlers.toolStyle}
        decided={decided}
        onApprove={async (toolName, summary) => {
          handlers.onMarkToolDecided?.(tc.id);
          await handlers.onApproveTool?.(toolName, summary, tc.id);
          handlers.onSend(`Approved: ${summary}`);
        }}
        onDeny={(toolName, summary) => {
          handlers.onMarkToolDecided?.(tc.id);
          handlers.onDenyTool?.(toolName, summary);
          handlers.onSend(`Denied: ${summary}`);
        }}
      />
    );
  };

  if (m.segments && m.segments.length > 0) {
    return m.segments.map((seg, i) => {
      if (seg.kind === "text") {
        if (!seg.text) return null;
        return (
          <div className="body" key={`t-${i}`}>
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{seg.text}</ReactMarkdown>
          </div>
        );
      }
      return renderTool(findTool(m, seg.toolId));
    });
  }

  return (
    <>
      {m.text && (
        <div className="body">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.text}</ReactMarkdown>
        </div>
      )}
      {m.toolCalls.map((tc) => renderTool(tc))}
    </>
  );
}

function findTool(m: ChatMessage, id: string) {
  return m.toolCalls.find((t) => t.id === id);
}

/**
 * Rendered when ADK's compactor folds a range of prior events into a
 * single summary. Displays as an inline separator with the summary
 * tucked under a ``<details>`` so the chat stays skimmable, with the
 * compacted invocation range shown as a subtle timestamp tag.
 */
function CompactionSeparator({ m }: { m: ChatMessage }) {
  const range = m.compactionRange;
  const span =
    range?.start && range?.end
      ? `${formatCompactionStamp(range.start)} → ${formatCompactionStamp(range.end)}`
      : null;
  return (
    <div
      style={{
        margin: "16px 0",
        display: "flex",
        alignItems: "center",
        gap: 10,
        color: "var(--ink-3)",
      }}
    >
      <div style={{ flex: 1, height: 1, background: "var(--line)" }} />
      <details
        style={{
          fontSize: "var(--fs-xs)",
          fontFamily: "var(--mono)",
          color: "var(--ink-3)",
          maxWidth: "65%",
        }}
      >
        <summary style={{ cursor: "pointer", listStyle: "none" }}>
          <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
            <Icon name="refresh" size={11} />
            compacted
            {span && <span style={{ color: "var(--ink-4)" }}>· {span}</span>}
          </span>
        </summary>
        <div
          style={{
            marginTop: 6,
            padding: "8px 12px",
            background: "var(--paper-2)",
            border: "1px solid var(--line)",
            borderRadius: "var(--radius-sm)",
            color: "var(--ink-2)",
            fontFamily: "var(--serif)",
            fontSize: "var(--fs-sm)",
            lineHeight: 1.55,
            whiteSpace: "pre-wrap",
          }}
        >
          {m.text}
        </div>
      </details>
      <div style={{ flex: 1, height: 1, background: "var(--line)" }} />
    </div>
  );
}

function formatCompactionStamp(unix: number): string {
  try {
    const d = new Date(unix * 1000);
    return d.toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return String(unix);
  }
}

function ThinkingDots() {
  return (
    <div className="msg" style={{ opacity: 0.65 }}>
      <div className="av" style={{ background: "var(--ink-4)" }}>·</div>
      <div className="by" style={{ alignItems: "center" }}>
        <span style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-xs)", color: "var(--ink-3)" }}>
          working…
        </span>
      </div>
    </div>
  );
}

function prettyAgent(agent: string | undefined): string {
  if (!agent) return "Agent";
  return agent.charAt(0).toUpperCase() + agent.slice(1);
}

function prettyRole(agent: string | undefined): string {
  switch ((agent ?? "").toLowerCase()) {
    case "researcher":
      return "research · Ada";
    case "writer":
      return "writer · Orson";
    case "analyst":
      return "analysis · Iris";
    case "reviewer":
      return "review · Kit";
    default:
      return "agent";
  }
}

