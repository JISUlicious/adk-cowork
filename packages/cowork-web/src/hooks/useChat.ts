import { useCallback, useRef, useState } from "react";
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

export interface ChatMessage {
  role: "user" | "assistant";
  text: string;
  thought: string;
  toolCalls: ToolCallEntry[];
}

function newAssistant(): ChatMessage {
  return { role: "assistant", text: "", thought: "", toolCalls: [] };
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

  const setMessagesSync = useCallback((msgs: ChatMessage[] | ((prev: ChatMessage[]) => ChatMessage[])) => {
    setMessages((prev) => {
      const next = typeof msgs === "function" ? msgs(prev) : msgs;
      messagesRef.current = next;
      return next;
    });
  }, []);

  const setSendingSync = useCallback((value: boolean) => {
    sendingRef.current = value;
    setSending(value);
  }, []);

  // Per-session state cache: preserves messages + sending across session switches
  const sessionCacheRef = useRef<
    Map<string, { messages: ChatMessage[]; sending: boolean; pending: ChatMessage | null; toolMap: Map<string, [number, number]> }>
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

    const hasFunctionResponse = parts.some((p) => p.functionResponse);
    const hasFunctionCall = parts.some((p) => p.functionCall);
    const hasText = parts.some((p) => typeof p.text === "string" && p.text);

    // User turn: role === "user" and not a tool response echo.
    const isUserTurn = role === "user" && !hasFunctionResponse && hasText;

    if (isUserTurn) {
      const text = parts.map((p) => p.text ?? "").join("");
      setMessagesSync((prev) => [
        ...prev,
        { role: "user", text, thought: "", toolCalls: [] },
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
        setMessagesSync((prev) => {
          const next = [...prev];
          const msg = next[mi];
          if (!msg) return prev;
          const tcs = msg.toolCalls.map((t) => ({ ...t }));
          const tc = tcs[ti];
          if (!tc) return prev;
          tc.result = result;
          if (result.confirmation_required) tc.status = "confirmation";
          else if (result.error) tc.status = "error";
          else tc.status = "ok";
          next[mi] = { ...msg, toolCalls: tcs };
          return next;
        });
      }
    } else if (hasText || hasFunctionCall) {
      // Assistant content: text (body or thought) and/or tool_call parts.
      if (!pendingRef.current) {
        pendingRef.current = newAssistant();
      }
      const pending = pendingRef.current;

      for (const part of parts) {
        if (typeof part.text === "string" && part.text) {
          if (part.thought) pending.thought += part.text;
          else pending.text += part.text;
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
        }
      }

      const snapshot: ChatMessage = {
        role: "assistant",
        text: pending.text,
        thought: pending.thought,
        toolCalls: pending.toolCalls.map((t) => ({ ...t })),
      };

      setMessagesSync((prev) => {
        const next = [...prev];
        const lastIdx = next.length - 1;
        const last = next[lastIdx];
        let msgIdx: number;
        if (last?.role === "assistant") {
          next[lastIdx] = snapshot;
          msgIdx = lastIdx;
        } else {
          next.push(snapshot);
          msgIdx = next.length - 1;
        }
        // Refresh tool-id index (message index may have shifted).
        pending.toolCalls.forEach((tc, ti) => {
          toolMapRef.current.set(tc.id, [msgIdx, ti]);
        });
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

  /** Save current session state into the cache before switching away. */
  const saveCurrentSession = useCallback(() => {
    const sid = sessionRef.current;
    if (!sid) return;
    sessionCacheRef.current.set(sid, {
      messages: messagesRef.current,
      sending: sendingRef.current,
      pending: pendingRef.current,
      toolMap: new Map(toolMapRef.current),
    });
  }, []);

  /** Restore cached session state, or reset to empty. */
  const restoreSession = useCallback((sid: string) => {
    const cached = sessionCacheRef.current.get(sid);
    if (cached) {
      setMessagesSync(cached.messages);
      setSendingSync(cached.sending);
      pendingRef.current = cached.pending;
      toolMapRef.current = cached.toolMap;
    } else {
      setMessagesSync([]);
      setSendingSync(false);
      pendingRef.current = null;
      toolMapRef.current = new Map();
    }
  }, [setMessagesSync, setSendingSync]);

  const connectSession = useCallback(
    (sid: string) => {
      client.disconnect();
      sessionRef.current = sid;
      setSessionId(sid);
      client.connectStream(sid, handleEvent);
    },
    [client, handleEvent],
  );

  const ensureSession = useCallback(
    async (project?: string) => {
      if (sessionRef.current) return sessionRef.current;
      const info = await client.createSession(project);
      connectSession(info.session_id);
      return info.session_id;
    },
    [client, connectSession],
  );

  const resumeSession = useCallback(
    async (existingSessionId: string, project: string) => {
      // Save current session state before switching
      saveCurrentSession();

      // Check if we have a cached version of the target session
      const cached = sessionCacheRef.current.get(existingSessionId);
      if (cached) {
        restoreSession(existingSessionId);
        connectSession(existingSessionId);
        return;
      }

      try {
        const info = await client.resumeSession(existingSessionId, project);
        setMessagesSync([]);
        pendingRef.current = null;
        toolMapRef.current = new Map();
        try {
          const events = await client.getHistory(info.session_id);
          for (const ev of events) handleEvent(ev);
          pendingRef.current = null;
          setSendingSync(false);
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
          },
        ]);
      }
    },
    [client, connectSession, handleEvent, saveCurrentSession, restoreSession],
  );

  const send = useCallback(
    async (text: string, project?: string) => {
      if (!text.trim() || sending) return;
      setMessagesSync((prev) => [
        ...prev,
        { role: "user", text, thought: "", toolCalls: [] },
      ]);
      setSendingSync(true);
      try {
        const sid = await ensureSession(project);
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
          },
        ]);
      }
    },
    [client, sending, ensureSession, setMessagesSync, setSendingSync],
  );

  const reset = useCallback(() => {
    client.disconnect();
    sessionRef.current = null;
    setSessionId(null);
    pendingRef.current = null;
    toolMapRef.current.clear();
    setMessagesSync([]);
    setSendingSync(false);
  }, [client, setMessagesSync, setSendingSync]);

  const newSession = useCallback(
    async (project?: string) => {
      saveCurrentSession();
      client.disconnect();
      sessionRef.current = null;
      setSessionId(null);
      pendingRef.current = null;
      toolMapRef.current = new Map();
      setMessagesSync([]);
      setSendingSync(false);
      try {
        const info = await client.createSession(project);
        connectSession(info.session_id);
      } catch (e) {
        setMessagesSync((prev) => [
          ...prev,
          { role: "assistant", text: `Failed to create session: ${e}`, thought: "", toolCalls: [] },
        ]);
      }
    },
    [client, connectSession, saveCurrentSession, setMessagesSync, setSendingSync],
  );

  return { messages, sending, send, reset, newSession, resumeSession, sessionId };
}
