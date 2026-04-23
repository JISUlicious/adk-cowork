/**
 * Titlebar — 40px chrome above the 3-pane shell.
 *
 * Hosts the brand mark, a breadcrumb (project/workdir → session title),
 * the auto-saved stamp (derived from the last event timestamp), the
 * policy + python_exec per-session dropdowns that used to live in
 * ``TopBar``, and the icon-button row (search, notifications, settings).
 */

import { useEffect, useRef, useState } from "react";
import type { CoworkClient } from "../transport/client";
import type { Notification, PolicyMode, PythonExecPolicy } from "../transport/types";
import { Icon } from "./atoms";

interface Props {
  client: CoworkClient;
  project: string | null;
  workdir: string | null;
  sessionId: string | null;
  sessionTitle?: string;
  userId?: string;
  lastEventAt?: number | null;
  notifications?: Notification[];
  unreadCount?: number;
  onMarkNotificationRead?: (id: string) => void | Promise<void>;
  onClearNotifications?: () => void | Promise<void>;
  onJumpToSession?: (sessionId: string) => void;
  onOpenSettings?: () => void;
  onOpenPalette?: () => void;
}

export function Titlebar({
  client,
  project,
  workdir,
  sessionId,
  sessionTitle,
  userId,
  lastEventAt,
  notifications = [],
  unreadCount = 0,
  onMarkNotificationRead,
  onClearNotifications,
  onJumpToSession,
  onOpenSettings,
  onOpenPalette,
}: Props) {
  const [policyMode, setPolicyMode] = useState<PolicyMode>("work");
  const [pythonExec, setPythonExec] = useState<PythonExecPolicy>("confirm");
  const [notifOpen, setNotifOpen] = useState(false);
  const notifRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!notifOpen) return;
    const onDocClick = (e: MouseEvent) => {
      if (!notifRef.current) return;
      if (!notifRef.current.contains(e.target as Node)) setNotifOpen(false);
    };
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [notifOpen]);

  useEffect(() => {
    if (sessionId) {
      client.getSessionPolicyMode(sessionId).then(setPolicyMode).catch(() => {});
      client.getSessionPythonExec(sessionId).then(setPythonExec).catch(() => {});
    } else {
      client.getPolicyMode().then(setPolicyMode).catch(() => {});
    }
  }, [client, sessionId]);

  const scopeLabel = workdir
    ? workdir.split("/").filter(Boolean).pop() || workdir
    : project || "Cowork";
  // Only render the session breadcrumb segment if we have a real title —
  // a raw id slice is noise next to the scope label.
  const current = sessionTitle?.trim() ? sessionTitle : null;
  const savedStamp = useSavedStamp(lastEventAt);
  const avatarLetter = (userId || "·").charAt(0).toUpperCase();

  return (
    <div className="titlebar">
      <div className="brand">
        Co<em>work</em>
      </div>
      <div className="crumbs">
        <span>{scopeLabel}</span>
        {current && (
          <>
            <span className="sep">/</span>
            <span className="cur">{current}</span>
          </>
        )}
      </div>
      {savedStamp && (
        <span
          style={{
            fontSize: 10,
            fontFamily: "var(--mono)",
            color: "var(--ink-4)",
            marginLeft: 8,
          }}
        >
          ●  auto-saved {savedStamp}
        </span>
      )}

      <div className="right">
        <select
          value={policyMode}
          disabled={!sessionId}
          onChange={async (e) => {
            if (!sessionId) return;
            const previous = policyMode;
            const next = e.target.value as PolicyMode;
            setPolicyMode(next);
            try {
              const confirmed = await client.setSessionPolicyMode(sessionId, next);
              setPolicyMode(confirmed);
            } catch {
              setPolicyMode(previous);
            }
          }}
          title={
            sessionId
              ? "Policy mode (applies to this session)"
              : "Server default — open a session to change"
          }
          style={policySelectStyle(policyMode, !sessionId)}
        >
          <option value="plan">plan</option>
          <option value="work">work</option>
          <option value="auto">auto</option>
        </select>

        <select
          value={pythonExec}
          disabled={!sessionId}
          onChange={async (e) => {
            if (!sessionId) return;
            const previous = pythonExec;
            const next = e.target.value as "confirm" | "allow" | "deny";
            setPythonExec(next);
            try {
              const confirmed = await client.setSessionPythonExec(sessionId, next);
              setPythonExec(confirmed);
            } catch {
              setPythonExec(previous);
            }
          }}
          title="python_exec_run policy for this session"
          style={pyExecSelectStyle(pythonExec, !sessionId)}
        >
          <option value="confirm">py:confirm</option>
          <option value="allow">py:allow</option>
          <option value="deny">py:deny</option>
        </select>

        <span style={{ width: 1, height: 16, background: "var(--line)", margin: "0 4px" }} />

        <button
          className="iconbtn"
          title="Search (⌘K)"
          type="button"
          onClick={onOpenPalette}
        >
          <Icon name="search" size={14} />
        </button>
        <div ref={notifRef} style={{ position: "relative" }}>
          <button
            className="iconbtn"
            title="Notifications"
            type="button"
            onClick={() => setNotifOpen((v) => !v)}
            style={{ position: "relative" }}
          >
            <Icon name="bell" size={14} />
            {unreadCount > 0 && (
              <span
                aria-label={`${unreadCount} unread`}
                style={{
                  position: "absolute",
                  top: 2,
                  right: 2,
                  width: 7,
                  height: 7,
                  borderRadius: "50%",
                  background: "var(--warn, #d98a00)",
                  boxShadow: "0 0 0 1.5px var(--paper)",
                }}
              />
            )}
          </button>
          {notifOpen && (
            <NotificationDropdown
              items={notifications}
              onJump={(id, sid) => {
                if (onMarkNotificationRead) void onMarkNotificationRead(id);
                if (sid && onJumpToSession) onJumpToSession(sid);
                setNotifOpen(false);
              }}
              onClear={async () => {
                if (onClearNotifications) await onClearNotifications();
                setNotifOpen(false);
              }}
            />
          )}
        </div>
        <button className="iconbtn" title="Settings" type="button" onClick={onOpenSettings}>
          <Icon name="settings" size={14} />
        </button>
        <div className="avatar" title={userId ?? "local"}>{avatarLetter}</div>
      </div>
    </div>
  );
}

/** "2s ago" / "1m ago" / "5m ago" / absolute time > 1h. Re-renders every 15s. */
function useSavedStamp(lastEventAt: number | null | undefined): string | null {
  const [, tick] = useState(0);
  useEffect(() => {
    if (!lastEventAt) return;
    const id = window.setInterval(() => tick((n) => n + 1), 15_000);
    return () => window.clearInterval(id);
  }, [lastEventAt]);
  if (!lastEventAt) return null;
  const secs = Math.max(0, Math.round((Date.now() - lastEventAt) / 1000));
  if (secs < 60) return `${secs}s ago`;
  const mins = Math.round(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  return `${hrs}h ago`;
}

function NotificationDropdown({
  items,
  onJump,
  onClear,
}: {
  items: Notification[];
  onJump: (id: string, sessionId: string | null | undefined) => void;
  onClear: () => void | Promise<void>;
}) {
  const hasItems = items.length > 0;
  return (
    <div
      style={{
        position: "absolute",
        top: "calc(100% + 6px)",
        right: 0,
        width: 320,
        maxHeight: 420,
        overflow: "hidden",
        display: "flex",
        flexDirection: "column",
        background: "var(--paper)",
        border: "1px solid var(--line)",
        borderRadius: "var(--radius-md)",
        boxShadow: "0 6px 18px rgba(0,0,0,0.12)",
        zIndex: 40,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "8px 12px",
          borderBottom: "1px solid var(--line)",
          fontFamily: "var(--mono)",
          fontSize: 11,
          color: "var(--ink-3)",
        }}
      >
        <span>Notifications</span>
        {hasItems && (
          <button
            type="button"
            onClick={() => void onClear()}
            style={{
              fontSize: 11,
              color: "var(--ink-3)",
              fontFamily: "var(--mono)",
              cursor: "pointer",
            }}
          >
            clear all
          </button>
        )}
      </div>
      <div style={{ overflowY: "auto", flex: 1 }}>
        {!hasItems && (
          <div
            style={{
              padding: "22px 12px",
              textAlign: "center",
              color: "var(--ink-4)",
              fontSize: 12,
              fontFamily: "var(--serif)",
            }}
          >
            Nothing new.
          </div>
        )}
        {items.map((n) => (
          <button
            key={n.id}
            type="button"
            onClick={() => onJump(n.id, n.session_id)}
            style={{
              display: "block",
              width: "100%",
              textAlign: "left",
              padding: "10px 12px",
              borderBottom: "1px solid var(--line)",
              background: n.read ? "transparent" : "var(--accent-soft, var(--paper-2))",
              cursor: "pointer",
            }}
          >
            <div
              style={{
                fontSize: 10,
                fontFamily: "var(--mono)",
                color: notifKindColor(n.kind),
                marginBottom: 3,
              }}
            >
              {notifKindLabel(n.kind)}
            </div>
            <div style={{ fontSize: 12, color: "var(--ink)" }}>{n.text}</div>
            <div
              style={{
                fontSize: 10,
                fontFamily: "var(--mono)",
                color: "var(--ink-4)",
                marginTop: 2,
              }}
            >
              {formatNotifStamp(n.created_at)}
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}

function notifKindLabel(kind: string): string {
  switch (kind) {
    case "turn_complete": return "turn complete";
    case "approval_needed": return "approval";
    case "error": return "error";
    default: return kind;
  }
}

function notifKindColor(kind: string): string {
  switch (kind) {
    case "error": return "var(--danger, #c33)";
    case "approval_needed": return "var(--warn, #d98a00)";
    default: return "var(--ink-3)";
  }
}

function formatNotifStamp(epochSec: number): string {
  const delta = Math.max(0, Math.round(Date.now() / 1000 - epochSec));
  if (delta < 60) return `${delta}s ago`;
  const m = Math.round(delta / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h}h ago`;
  return new Date(epochSec * 1000).toLocaleString();
}

function policySelectStyle(mode: string, disabled: boolean): React.CSSProperties {
  const base: React.CSSProperties = {
    fontSize: 11,
    fontFamily: "var(--mono)",
    padding: "2px 6px",
    borderRadius: "var(--radius-sm)",
    border: "1px solid var(--line)",
    background: "var(--paper)",
    color: "var(--ink-2)",
    opacity: disabled ? 0.55 : 1,
    cursor: disabled ? "not-allowed" : "pointer",
  };
  if (mode === "plan") return { ...base, borderColor: "var(--ada-soft)", color: "var(--ada)" };
  if (mode === "auto") return { ...base, borderColor: "var(--warn)", color: "var(--warn)" };
  return { ...base, borderColor: "var(--ok)", color: "var(--ok)" };
}

function pyExecSelectStyle(policy: string, disabled: boolean): React.CSSProperties {
  const base: React.CSSProperties = {
    fontSize: 11,
    fontFamily: "var(--mono)",
    padding: "2px 6px",
    borderRadius: "var(--radius-sm)",
    border: "1px solid var(--line)",
    background: "var(--paper)",
    color: "var(--ink-2)",
    opacity: disabled ? 0.55 : 1,
    cursor: disabled ? "not-allowed" : "pointer",
  };
  if (policy === "allow") return { ...base, borderColor: "var(--warn)", color: "var(--warn)" };
  if (policy === "deny") return { ...base, borderColor: "var(--danger)", color: "var(--danger)" };
  return base;
}
