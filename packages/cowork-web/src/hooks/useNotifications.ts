/**
 * Polling hook for server-side notifications.
 *
 * The notification store lives server-side (``cowork_core/
 * notifications.py``) and is explicitly a sibling of the ADK session
 * — see ``ARCHITECTURE.md`` §5 for why. The client polls every 20 s;
 * if we need tighter latency later, the natural follow-up is a
 * user-scoped SSE stream at ``/v1/notifications/stream``.
 *
 * Polling backs off to a single immediate fetch when the document is
 * hidden, so background tabs don't hammer the endpoint.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import type { CoworkClient } from "../transport/client";
import type { Notification } from "../transport/types";

const POLL_INTERVAL_MS = 20_000;

interface UseNotifications {
  items: Notification[];
  unread: number;
  refresh: () => Promise<void>;
  markRead: (id: string) => Promise<void>;
  clearAll: () => Promise<void>;
}

export function useNotifications(client: CoworkClient | null): UseNotifications {
  const [items, setItems] = useState<Notification[]>([]);
  const mountedRef = useRef(true);

  const refresh = useCallback(async () => {
    if (!client) return;
    try {
      const list = await client.listNotifications();
      if (mountedRef.current) setItems(list);
    } catch {
      /* soft-fail: transient network issues shouldn't spam the log */
    }
  }, [client]);

  const markRead = useCallback(
    async (id: string) => {
      if (!client) return;
      // Optimistic: flip the flag locally so the bell reacts instantly
      // even if the round-trip is slow.
      setItems((prev) =>
        prev.map((n) => (n.id === id ? { ...n, read: true } : n)),
      );
      try {
        await client.markNotificationRead(id);
      } catch {
        /* keep the optimistic state; next refresh reconciles */
      }
    },
    [client],
  );

  const clearAll = useCallback(async () => {
    if (!client) return;
    setItems([]);
    try {
      await client.clearNotifications();
    } catch {
      /* server still has them; next refresh will resurface */
    }
  }, [client]);

  useEffect(() => {
    mountedRef.current = true;
    if (!client) return () => {};
    void refresh();
    const interval = window.setInterval(() => {
      if (document.visibilityState !== "hidden") void refresh();
    }, POLL_INTERVAL_MS);
    const onVisible = () => {
      if (document.visibilityState === "visible") void refresh();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      mountedRef.current = false;
      window.clearInterval(interval);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [client, refresh]);

  const unread = items.reduce((n, it) => n + (it.read ? 0 : 1), 0);

  return { items, unread, refresh, markRead, clearAll };
}
