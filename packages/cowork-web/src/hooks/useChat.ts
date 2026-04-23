import { useCallback, useMemo, useRef, useState } from "react";
import { CoworkClient } from "../transport/client";
import { notify } from "../transport/tauri";
import type { AdkEvent } from "../transport/types";

export interface ToolCallEntry {
  id: string;
  name: string;
  args: Record<string, unknown>;
  result?: Record<string, unknown>;
  status: "pending" | "ok" | "error" | "confirmation";
}

/** Ordered segment inside an assistant message — preserves the actual
 *  arrival order so narration and tool calls interleave on screen the
 *  same way the agent emitted them. */
export type MessageSegment =
  | { kind: "text"; text: string }
  | { kind: "tool"; toolId: string };

export interface ChatMessage {
  role: "user" | "assistant" | "compaction";
  /** Concatenated text across all text segments — kept for legacy
   *  callers (e.g. user turns); renderers should prefer ``segments``. */
  text: string;
  thought: string;
  toolCalls: ToolCallEntry[];
  /** Ordered narration + tool-call timeline. Absent for user turns. */
  segments: MessageSegment[];
  /** Author from the ADK event — `researcher`, `writer`, `analyst`,
   *  `reviewer`, the root agent name, or undefined for user turns. */
  agent?: string;
  /** For ``role === "compaction"`` only: start/end unix timestamps of
   *  the invocation range the summary covers. */
  compactionRange?: { start?: number; end?: number };
}

/** Author ids the server uses for sentinels/errors — they shouldn't
 *  appear in the agent roster or colour a monogram. */
const SYNTHETIC_AUTHORS = new Set(["cowork-server", "cowork-client"]);

const DECIDED_STORAGE_PREFIX = "cowork:decided:";

function loadDecidedFromStorage(sid: string): Set<string> {
  if (typeof window === "undefined") return new Set();
  try {
    const raw = window.localStorage.getItem(DECIDED_STORAGE_PREFIX + sid);
    if (!raw) return new Set();
    const arr = JSON.parse(raw);
    return new Set(Array.isArray(arr) ? arr : []);
  } catch {
    return new Set();
  }
}

function persistDecidedToStorage(sid: string, ids: Set<string>): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(
      DECIDED_STORAGE_PREFIX + sid,
      JSON.stringify(Array.from(ids)),
    );
  } catch {
    /* ignore quota / privacy-mode failures */
  }
}

function newAssistant(agent?: string): ChatMessage {
  const clean = agent && !SYNTHETIC_AUTHORS.has(agent) ? agent : undefined;
  return { role: "assistant", text: "", thought: "", toolCalls: [], segments: [], agent: clean };
}

export function useChat(client: CoworkClient) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [sending, setSending] = useState(false);
  const sendingRef = useRef(false);
  const messagesRef = useRef<ChatMessage[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const sessionRef = useRef<string | null>(null);
  const pendingRef = useRef<ChatMessage | null>(null);
  // id → (message-index, toolCalls-index)
  const toolMapRef = useRef<Map<string, [number, number]>>(new Map());
  // Distinct agent authors observed in the active session — drives the
  // monogram stack on the corresponding session row.
  const [agents, setAgents] = useState<string[]>([]);
  const agentsRef = useRef<Set<string>>(new Set());
  // Session ids with a turn currently in flight. Updated for the active
  // session through the SSE stream; for background sessions, the entry
  // stays until the user returns and we replay history (at which point
  // we clear it — there's no way to observe a background turn from a
  // disconnected client, so we accept a brief false-positive window).
  const [sendingIds, setSendingIds] = useState<Set<string>>(new Set());
  const markSending = useCallback((sid: string | null, v: boolean) => {
    if (!sid) return;
    setSendingIds((prev) => {
      const has = prev.has(sid);
      if (v === has) return prev;
      const next = new Set(prev);
      if (v) next.add(sid);
      else next.delete(sid);
      return next;
    });
  }, []);
  // Tool-call ids the user has already acted on (approve or deny). We
  // track this separately from the server-side approval counter so
  // reloading a past session doesn't resurrect the banner on a tool
  // call whose confirmation the user already resolved. Persisted per
  // session via ``sessionCacheRef``.
  const [decidedToolIds, setDecidedToolIds] = useState<Set<string>>(new Set());
  const decidedToolIdsRef = useRef<Set<string>>(new Set());
  const markToolDecided = useCallback((toolId: string) => {
    if (decidedToolIdsRef.current.has(toolId)) return;
    decidedToolIdsRef.current.add(toolId);
    setDecidedToolIds(new Set(decidedToolIdsRef.current));
    const sid = sessionRef.current;
    if (sid) persistDecidedToStorage(sid, decidedToolIdsRef.current);
  }, []);
  // Background SSE subscriptions — keyed by session id. When the user
  // switches away from a session whose turn is still in flight, we
  // install a listener that keeps consuming events until the server
  // emits ``turnComplete``, at which point the stream is closed and
  // ``sendingIds`` is cleared. Without this, the indicator dot on the
  // other session row would stick on ``running`` forever because the
  // primary SSE stream moved to the newly-selected session.
  const bgDisposersRef = useRef<Map<string, () => void>>(new Map());

  const setMessagesSync = useCallback((msgs: ChatMessage[] | ((prev: ChatMessage[]) => ChatMessage[])) => {
    // Compute and commit the next list to the ref *synchronously* so
    // subsequent event handlers in the same tick (e.g. a
    // functionResponse arriving right after a functionCall during
    // history replay) see an up-to-date view. Running the computation
    // inside React's functional updater defers both the ref write and
    // any index lookups until reconciliation — which races against
    // the next handler and previously left tool calls showing as
    // ``pending`` on replay.
    const next = typeof msgs === "function" ? msgs(messagesRef.current) : msgs;
    messagesRef.current = next;
    setMessages(next);
  }, []);

  const setSendingSync = useCallback((value: boolean) => {
    sendingRef.current = value;
    setSending(value);
    markSending(sessionRef.current, value);
  }, [markSending]);

  // Per-session state cache: preserves messages + sending across session switches
  const sessionCacheRef = useRef<
    Map<
      string,
      {
        messages: ChatMessage[];
        sending: boolean;
        pending: ChatMessage | null;
        toolMap: Map<string, [number, number]>;
        agents: Set<string>;
        decidedToolIds: Set<string>;
      }
    >
  >(new Map());

  /**
   * Fold one ADK event into the message timeline.
   *
   * Contract matches Google ADK's native event stream: we read
   * ``content.role`` / ``content.parts`` and terminate a turn on
   * ``turnComplete``. The same function handles live events and
   * replayed history.
   */
  const handleEvent = useCallback((ev: AdkEvent) => {
    const parts = ev.content?.parts ?? [];
    const role = ev.content?.role ?? "";
    // Track every real agent author we see so the Sessions row can
    // show a stack. Skip the synthetic server authors used for
    // sentinels/errors (``cowork-server``, ``cowork-client``) — they
    // aren't agents and shouldn't colour a monogram.
    if (
      ev.author &&
      ev.author !== "user" &&
      !SYNTHETIC_AUTHORS.has(ev.author) &&
      !agentsRef.current.has(ev.author)
    ) {
      agentsRef.current.add(ev.author);
      setAgents(Array.from(agentsRef.current));
    }

    // ADK ``EventCompaction`` — the runner rolled a range of prior
    // invocations into an LLM-generated summary. Render it as a
    // dedicated separator message so the user sees what happened,
    // instead of the compaction event being dropped on the floor.
    const compaction = ev.actions?.compaction;
    if (
      compaction &&
      typeof compaction === "object" &&
      compaction.compactedContent
    ) {
      const summaryText = (compaction.compactedContent.parts ?? [])
        .map((p) => (typeof p.text === "string" ? p.text : ""))
        .filter(Boolean)
        .join("\n")
        .trim();
      setMessagesSync((prev) => [
        ...prev,
        {
          role: "compaction",
          text: summaryText || "(compacted)",
          thought: "",
          toolCalls: [],
          segments: [],
          compactionRange: {
            start: compaction.startTimestamp,
            end: compaction.endTimestamp,
          },
        },
      ]);
      return;
    }

    // First-class approval events: the server appends one to the
    // session whenever the user hits Approve, carrying the original
    // tool-call id in a ``cowork:approval:<id>`` state_delta key.
    // Replay sees the same marker, so we rebuild ``decidedToolIds``
    // from the event record itself — no localStorage needed.
    const actions = ev.actions as { stateDelta?: Record<string, unknown>; state_delta?: Record<string, unknown> } | undefined;
    const stateDelta = actions?.stateDelta ?? actions?.state_delta;
    if (stateDelta && typeof stateDelta === "object") {
      let changed = false;
      for (const key of Object.keys(stateDelta)) {
        if (!key.startsWith("cowork:approval:")) continue;
        const tid = key.slice("cowork:approval:".length);
        if (tid && !decidedToolIdsRef.current.has(tid)) {
          decidedToolIdsRef.current.add(tid);
          changed = true;
        }
      }
      if (changed) setDecidedToolIds(new Set(decidedToolIdsRef.current));
    }

    const hasFunctionResponse = parts.some((p) => p.functionResponse);
    const hasFunctionCall = parts.some((p) => p.functionCall);
    const hasText = parts.some((p) => typeof p.text === "string" && p.text);

    // User turn: role === "user" and not a tool response echo.
    const isUserTurn = role === "user" && !hasFunctionResponse && hasText;

    if (isUserTurn) {
      const text = parts.map((p) => p.text ?? "").join("");
      setMessagesSync((prev) => [
        ...prev,
        { role: "user", text, thought: "", toolCalls: [], segments: [] },
      ]);
    } else if (hasFunctionResponse) {
      // Correlate tool_response parts with previously-recorded tool_calls.
      for (const part of parts) {
        const fr = part.functionResponse;
        if (!fr?.id) continue;
        const loc = toolMapRef.current.get(fr.id);
        if (!loc) continue;
        const [mi, ti] = loc;
        const result = (fr.response ?? {}) as Record<string, unknown>;
        // ``python_exec_run`` / ``shell_run`` return ``exit_code`` +
        // stdout/stderr rather than an ``error`` field when the
        // subprocess itself ran but exited non-zero. Treat any
        // non-zero exit as an error so the UI badge matches what the
        // user ran, not just "did the tool finish".
        const exitCode = result.exit_code;
        const nonZeroExit = typeof exitCode === "number" && exitCode !== 0;
        const newStatus = result.confirmation_required
          ? ("confirmation" as const)
          : result.error || nonZeroExit
            ? ("error" as const)
            : ("ok" as const);
        // Keep pendingRef in sync so the next assistant snapshot uses the right status.
        if (pendingRef.current?.toolCalls[ti]) {
          pendingRef.current.toolCalls[ti].result = result;
          pendingRef.current.toolCalls[ti].status = newStatus;
        }
        setMessagesSync((prev) => {
          const next = [...prev];
          const msg = next[mi];
          if (!msg) return prev;
          const tcs = msg.toolCalls.map((t) => ({ ...t }));
          const tc = tcs[ti];
          if (!tc) return prev;
          tc.result = result;
          tc.status = newStatus;
          next[mi] = { ...msg, toolCalls: tcs };
          return next;
        });
      }
    } else if (hasText || hasFunctionCall) {
      // Assistant content: text (body or thought) and/or tool_call parts.
      if (!pendingRef.current) {
        pendingRef.current = newAssistant(ev.author);
      } else if (
        ev.author &&
        !SYNTHETIC_AUTHORS.has(ev.author) &&
        !pendingRef.current.agent
      ) {
        pendingRef.current.agent = ev.author;
      }
      const pending = pendingRef.current;

      // ADK's streaming aggregator yields two kinds of text-bearing
      // events per turn:
      //   · ``partial=true`` chunks carrying *delta* text — we append.
      //   · a single ``partial=false``/unset aggregated event carrying
      //     the *full* accumulated text — we replace, so appending it
      //     on top of the partials wouldn't double the body.
      // History replay only persists non-partial events, so in that
      // path the first replace sets the final text outright.
      const isPartial = ev.partial === true;
      for (const part of parts) {
        if (typeof part.text === "string" && part.text) {
          if (part.thought) {
            if (isPartial) pending.thought += part.text;
            else pending.thought = part.text;
          } else {
            if (isPartial) {
              pending.text += part.text;
              const lastSeg = pending.segments[pending.segments.length - 1];
              if (lastSeg && lastSeg.kind === "text") {
                lastSeg.text += part.text;
              } else {
                pending.segments.push({ kind: "text", text: part.text });
              }
            } else {
              pending.text = part.text;
              const lastSeg = pending.segments[pending.segments.length - 1];
              if (lastSeg && lastSeg.kind === "text") {
                lastSeg.text = part.text;
              } else {
                pending.segments.push({ kind: "text", text: part.text });
              }
            }
          }
        }
        if (part.functionCall) {
          const fc = part.functionCall;
          const id =
            fc.id ?? `tc-${Date.now()}-${pending.toolCalls.length}`;
          pending.toolCalls.push({
            id,
            name: fc.name ?? "",
            args: fc.args ?? {},
            status: "pending",
          });
          pending.segments.push({ kind: "tool", toolId: id });
        }
      }

      const snapshot: ChatMessage = {
        role: "assistant",
        text: pending.text,
        thought: pending.thought,
        toolCalls: pending.toolCalls.map((t) => ({ ...t })),
        segments: pending.segments.map((s) => ({ ...s })),
        agent: pending.agent,
      };

      // Predict the target index so toolMapRef stays in sync
      // *before* the next event's handler runs — the functionResponse
      // branch reads this map synchronously and would miss entries
      // written inside a deferred React updater.
      const cur = messagesRef.current;
      const lastCur = cur[cur.length - 1];
      const msgIdx = lastCur?.role === "assistant" ? cur.length - 1 : cur.length;
      pending.toolCalls.forEach((tc, ti) => {
        toolMapRef.current.set(tc.id, [msgIdx, ti]);
      });

      setMessagesSync((prev) => {
        const next = [...prev];
        const lastIdx = next.length - 1;
        const last = next[lastIdx];
        if (last?.role === "assistant") {
          next[lastIdx] = snapshot;
        } else {
          next.push(snapshot);
        }
        return next;
      });
    }

    if (ev.errorMessage || ev.errorCode) {
      setMessagesSync((prev) => [
        ...prev,
        {
          role: "assistant",
          text: `Error${ev.errorCode ? ` (${ev.errorCode})` : ""}: ${ev.errorMessage ?? ""}`,
          thought: "",
          toolCalls: [],
          segments: [],
        },
      ]);
    }

    if (ev.turnComplete) {
      pendingRef.current = null;
      setSendingSync(false);
      if (typeof document !== "undefined" && document.hidden) {
        void notify("Cowork", "Turn complete");
      }
    }
  }, [setMessagesSync, setSendingSync]);

  // Sessions whose background turn completed since we left them. When
  // the user resumes one of these, we discard the stale cache and
  // replay history so the chat area reflects what the agent produced
  // while we were away — not the mid-stream snapshot we captured at
  // switch time.
  const staleCacheRef = useRef<Set<string>>(new Set());

  /** Install a background listener that consumes events from an
   *  in-flight session until turnComplete, then disposes itself.
   *  Updates the cache's ``sending`` flag so returning to the session
   *  (even via the cached path) reflects the completed state, and
   *  marks the cache as stale so we refresh message content. */
  const installBackgroundListener = useCallback(
    (sid: string) => {
      if (bgDisposersRef.current.has(sid)) return;
      const dispose = client.subscribeBackground(sid, (ev) => {
        if (ev.turnComplete) {
          markSending(sid, false);
          const cached = sessionCacheRef.current.get(sid);
          if (cached) {
            sessionCacheRef.current.set(sid, { ...cached, sending: false });
          }
          staleCacheRef.current.add(sid);
          const d = bgDisposersRef.current.get(sid);
          if (d) {
            d();
            bgDisposersRef.current.delete(sid);
          }
        }
      });
      bgDisposersRef.current.set(sid, dispose);
    },
    [client, markSending],
  );

  /** Save current session state into the cache before switching away.
   *  If the outgoing session still has a turn in flight, spawn a
   *  background SSE listener so we can update its ``running``
   *  indicator when ``turnComplete`` arrives even though the user is
   *  looking at a different session. */
  const saveCurrentSession = useCallback(() => {
    const sid = sessionRef.current;
    if (!sid) return;
    sessionCacheRef.current.set(sid, {
      messages: messagesRef.current,
      sending: sendingRef.current,
      pending: pendingRef.current,
      toolMap: new Map(toolMapRef.current),
      agents: new Set(agentsRef.current),
      decidedToolIds: new Set(decidedToolIdsRef.current),
    });
    if (sendingRef.current) {
      installBackgroundListener(sid);
    }
  }, [installBackgroundListener]);

  /** Restore cached session state, or reset to empty. */
  const restoreSession = useCallback((sid: string) => {
    // sessionRef.current still points at the *outgoing* session when
    // this runs — ``connectSession`` hasn't yet flipped it — so we
    // can't go through setSendingSync (which uses sessionRef). Update
    // the raw primitives directly and mark sendingIds with the
    // explicit target ``sid`` instead. This is what keeps a
    // background session's ``running`` dot intact when the user
    // switches tabs mid-turn.
    const cached = sessionCacheRef.current.get(sid);
    if (cached) {
      setMessagesSync(cached.messages);
      sendingRef.current = cached.sending;
      setSending(cached.sending);
      markSending(sid, cached.sending);
      pendingRef.current = cached.pending;
      toolMapRef.current = cached.toolMap;
      agentsRef.current = new Set(cached.agents);
      setAgents(Array.from(agentsRef.current));
      decidedToolIdsRef.current = new Set(cached.decidedToolIds);
      setDecidedToolIds(new Set(decidedToolIdsRef.current));
    } else {
      setMessagesSync([]);
      sendingRef.current = false;
      setSending(false);
      markSending(sid, false);
      pendingRef.current = null;
      toolMapRef.current = new Map();
      agentsRef.current = new Set();
      setAgents([]);
      decidedToolIdsRef.current = new Set();
      setDecidedToolIds(new Set());
    }
  }, [markSending, setMessagesSync]);

  const connectSession = useCallback(
    (sid: string) => {
      // If a background listener was watching this session, tear it
      // down — the primary handler is about to own the stream.
      const bg = bgDisposersRef.current.get(sid);
      if (bg) {
        bg();
        bgDisposersRef.current.delete(sid);
      }
      sessionRef.current = sid;
      setSessionId(sid);
      // Merge any decisions the user made in a previous launch so
      // already-approved tool calls don't resurface their banner.
      const persisted = loadDecidedFromStorage(sid);
      if (persisted.size) {
        for (const id of persisted) decidedToolIdsRef.current.add(id);
        setDecidedToolIds(new Set(decidedToolIdsRef.current));
      }
      client.connectStream(sid, handleEvent);
    },
    [client, handleEvent],
  );

  /** Scope describes which kind of session to create/resume. Managed mode
   *  supplies ``project`` (a slug); local-dir mode supplies ``workdir``. */
  type Scope = { project?: string; workdir?: string } | undefined;

  const ensureSession = useCallback(
    async (scope: Scope) => {
      if (sessionRef.current) return sessionRef.current;
      const info = await client.createSession(scope);
      connectSession(info.session_id);
      return info.session_id;
    },
    [client, connectSession],
  );

  const resumeSession = useCallback(
    async (existingSessionId: string, scope: Scope) => {
      // Save current session state before switching
      saveCurrentSession();

      // If a background turn finished since we left this session, the
      // cached state is a mid-stream snapshot that doesn't include the
      // agent's final response. Drop the cache and fall through to the
      // history-replay path to rebuild from the server's truth.
      const wasStale = staleCacheRef.current.delete(existingSessionId);
      const cached = wasStale
        ? undefined
        : sessionCacheRef.current.get(existingSessionId);

      // Pull in any approval decisions persisted for this session in
      // a previous app launch BEFORE the history replay fires. Without
      // this, the confirmation banner renders during replay (when
      // decidedToolIds is still empty) and only disappears after
      // connectSession merges storage in — a flash we want to avoid
      // since some webviews appear to settle on the pre-merge render.
      const persisted = loadDecidedFromStorage(existingSessionId);
      if (persisted.size) {
        for (const id of persisted) decidedToolIdsRef.current.add(id);
        setDecidedToolIds(new Set(decidedToolIdsRef.current));
      }

      if (cached) {
        restoreSession(existingSessionId);
        connectSession(existingSessionId);
        return;
      }

      try {
        const info = await client.resumeSession(existingSessionId, scope ?? {});
        setMessagesSync([]);
        pendingRef.current = null;
        toolMapRef.current = new Map();
        try {
          const events = await client.getHistory(info.session_id);
          for (const ev of events) handleEvent(ev);
          pendingRef.current = null;
          // sessionRef.current still points at the outgoing session
          // here; ``connectSession`` flips it below. Update primitives
          // directly and mark sendingIds against the explicit
          // incoming id so the previous session's running state
          // survives the switch.
          sendingRef.current = false;
          setSending(false);
          markSending(info.session_id, false);
        } catch {
          /* history unavailable — start clean */
        }
        connectSession(info.session_id);
      } catch (e) {
        setMessagesSync((prev) => [
          ...prev,
          {
            role: "assistant",
            text: `Failed to resume session: ${e}`,
            thought: "",
            toolCalls: [],
            segments: [],
          },
        ]);
      }
    },
    [client, connectSession, handleEvent, markSending, restoreSession, saveCurrentSession, setMessagesSync],
  );

  const send = useCallback(
    async (text: string, scope: Scope) => {
      if (!text.trim() || sending) return;
      setMessagesSync((prev) => [
        ...prev,
        { role: "user", text, thought: "", toolCalls: [], segments: [] },
      ]);
      setSendingSync(true);
      try {
        const sid = await ensureSession(scope);
        await client.sendMessage(sid, text);
      } catch (e) {
        setSendingSync(false);
        setMessagesSync((prev) => [
          ...prev,
          {
            role: "assistant",
            text: `Connection error: ${e}`,
            thought: "",
            toolCalls: [],
            segments: [],
          },
        ]);
      }
    },
    [client, sending, ensureSession, setMessagesSync, setSendingSync],
  );

  const reset = useCallback(() => {
    client.disconnect();
    for (const d of bgDisposersRef.current.values()) d();
    bgDisposersRef.current.clear();
    sessionRef.current = null;
    setSessionId(null);
    pendingRef.current = null;
    toolMapRef.current.clear();
    agentsRef.current.clear();
    setAgents([]);
    decidedToolIdsRef.current.clear();
    setDecidedToolIds(new Set());
    setSendingIds(new Set());
    setMessagesSync([]);
    setSendingSync(false);
  }, [client, setMessagesSync, setSendingSync]);

  const newSession = useCallback(
    async (scope: Scope) => {
      saveCurrentSession();
      client.disconnect();
      sessionRef.current = null;
      setSessionId(null);
      pendingRef.current = null;
      toolMapRef.current = new Map();
      agentsRef.current = new Set();
      setAgents([]);
      decidedToolIdsRef.current = new Set();
      setDecidedToolIds(new Set());
      setMessagesSync([]);
      setSendingSync(false);
      try {
        const info = await client.createSession(scope);
        connectSession(info.session_id);
      } catch (e) {
        setMessagesSync((prev) => [
          ...prev,
          { role: "assistant", text: `Failed to create session: ${e}`, thought: "", toolCalls: [], segments: [] },
        ]);
      }
    },
    [client, connectSession, saveCurrentSession, setMessagesSync, setSendingSync],
  );

  // Sessions stalled on an unresolved ``confirmation_required`` tool
  // call are "waiting". Derived from the active session's ``messages``
  // + cached sessions in ``sessionCacheRef``; never a server field.
  // Running (``sendingIds``) trumps waiting.
  const waitingIds = useMemo(() => {
    const out = new Set<string>();
    const hasPendingConfirmation = (msgs: ChatMessage[] | undefined): boolean => {
      if (!msgs) return false;
      for (const m of msgs) {
        if (m.role !== "assistant") continue;
        for (const tc of m.toolCalls) {
          if (tc.status !== "confirmation") continue;
          if (decidedToolIds.has(tc.id)) continue;
          return true;
        }
      }
      return false;
    };
    if (sessionId && !sendingIds.has(sessionId) && hasPendingConfirmation(messages)) {
      out.add(sessionId);
    }
    for (const [sid, cached] of sessionCacheRef.current.entries()) {
      if (sid === sessionId) continue;
      if (sendingIds.has(sid)) continue;
      if (hasPendingConfirmation(cached.messages)) out.add(sid);
    }
    return out;
  }, [messages, sessionId, decidedToolIds, sendingIds]);

  return {
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
  };
}
