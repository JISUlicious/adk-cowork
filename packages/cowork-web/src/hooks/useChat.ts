import { useCallback, useRef, useState } from "react";
import { CoworkClient } from "../transport/client";
import { notify } from "../transport/tauri";
import type { Frame, ToolCallFrame, ToolResultFrame } from "../transport/types";

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

export function useChat(client: CoworkClient) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [sending, setSending] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const sessionRef = useRef<string | null>(null);
  const pendingRef = useRef<ChatMessage | null>(null);
  const toolMapRef = useRef<Map<string, number>>(new Map());

  const handleFrame = useCallback((frame: Frame) => {
    switch (frame.type) {
      case "text": {
        if (!pendingRef.current) {
          pendingRef.current = { role: "assistant", text: "", thought: "", toolCalls: [] };
        }
        if (frame.thought) {
          pendingRef.current.thought += frame.text;
        } else {
          pendingRef.current.text += frame.text;
        }
        // Snapshot now — react's updater runs later, and end_turn may have
        // cleared pendingRef by the time it runs.
        const snapshot: ChatMessage = {
          role: "assistant",
          text: pendingRef.current.text,
          thought: pendingRef.current.thought,
          toolCalls: [...pendingRef.current.toolCalls],
        };
        setMessages((prev) => {
          const next = [...prev];
          const last = next[next.length - 1];
          if (last?.role === "assistant") {
            next[next.length - 1] = snapshot;
          } else {
            next.push(snapshot);
          }
          return next;
        });
        break;
      }
      case "tool_call": {
        const tc = frame as ToolCallFrame;
        if (!pendingRef.current) {
          pendingRef.current = { role: "assistant", text: "", thought: "", toolCalls: [] };
        }
        const entry: ToolCallEntry = {
          id: tc.id || `tc-${Date.now()}`,
          name: tc.name,
          args: tc.args || {},
          status: "pending",
        };
        pendingRef.current.toolCalls.push(entry);
        toolMapRef.current.set(
          entry.id,
          pendingRef.current.toolCalls.length - 1,
        );
        const snapshot: ChatMessage = {
          role: "assistant",
          text: pendingRef.current.text,
          thought: pendingRef.current.thought,
          toolCalls: [...pendingRef.current.toolCalls],
        };
        setMessages((prev) => {
          const next = [...prev];
          const last = next[next.length - 1];
          if (last?.role === "assistant") {
            next[next.length - 1] = snapshot;
          } else {
            next.push(snapshot);
          }
          return next;
        });
        break;
      }
      case "tool_result": {
        const tr = frame as ToolResultFrame;
        if (!pendingRef.current) break;
        const idx = toolMapRef.current.get(tr.id || "");
        if (idx !== undefined && pendingRef.current.toolCalls[idx]) {
          const result = tr.result || {};
          const tc = pendingRef.current.toolCalls[idx];
          tc.result = result;
          if (result.confirmation_required) {
            tc.status = "confirmation";
          } else if (result.error) {
            tc.status = "error";
          } else {
            tc.status = "ok";
          }
          const snapshot: ChatMessage = {
            role: "assistant",
            text: pendingRef.current.text,
            thought: pendingRef.current.thought,
            toolCalls: pendingRef.current.toolCalls.map((t) => ({ ...t })),
          };
          setMessages((prev) => {
            const next = [...prev];
            const last = next[next.length - 1];
            if (last?.role === "assistant") {
              next[next.length - 1] = snapshot;
            }
            return next;
          });
        }
        break;
      }
      case "end_turn": {
        pendingRef.current = null;
        toolMapRef.current.clear();
        setSending(false);
        // Native notification if the app is backgrounded.
        if (typeof document !== "undefined" && document.hidden) {
          void notify("Cowork", "Turn complete");
        }
        break;
      }
      case "error": {
        pendingRef.current = null;
        toolMapRef.current.clear();
        setSending(false);
        setMessages((prev) => [
          ...prev,
          {
            role: "assistant",
            text: `Error: ${frame.message}`,
            thought: "",
            toolCalls: [],
          },
        ]);
        break;
      }
    }
  }, []);

  const connectSession = useCallback(
    (sid: string) => {
      client.disconnect();
      sessionRef.current = sid;
      setSessionId(sid);
      client.connect(sid, handleFrame);
    },
    [client, handleFrame],
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
      try {
        const info = await client.resumeSession(existingSessionId, project);
        let history: ChatMessage[] = [];
        try {
          const raw = (await client.getHistory(info.session_id)) as ChatMessage[];
          history = raw;
        } catch {
          // If history unavailable, fall back to empty timeline.
        }
        setMessages(history);
        connectSession(info.session_id);
      } catch (e) {
        setMessages((prev) => [
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
    [client, connectSession],
  );

  const send = useCallback(
    async (text: string, project?: string) => {
      if (!text.trim() || sending) return;
      setMessages((prev) => [
        ...prev,
        { role: "user", text, thought: "", toolCalls: [] },
      ]);
      setSending(true);
      try {
        const sid = await ensureSession(project);
        await client.sendMessage(sid, text);
      } catch (e) {
        setSending(false);
        setMessages((prev) => [
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
    [client, sending, ensureSession],
  );

  const reset = useCallback(() => {
    client.disconnect();
    sessionRef.current = null;
    setSessionId(null);
    pendingRef.current = null;
    toolMapRef.current.clear();
    setMessages([]);
    setSending(false);
  }, [client]);

  const newSession = useCallback(
    async (project?: string) => {
      client.disconnect();
      sessionRef.current = null;
      setSessionId(null);
      pendingRef.current = null;
      toolMapRef.current.clear();
      setMessages([]);
      setSending(false);
      try {
        const info = await client.createSession(project);
        connectSession(info.session_id);
      } catch (e) {
        setMessages((prev) => [
          ...prev,
          { role: "assistant", text: `Failed to create session: ${e}`, thought: "", toolCalls: [] },
        ]);
      }
    },
    [client, connectSession],
  );

  return { messages, sending, send, reset, newSession, resumeSession, sessionId };
}
