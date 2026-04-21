/**
 * Tool-call card — three visual modes per the design system.
 *
 *   collapsed : chip with a status pill; click to expand body.
 *   expanded  : body always shown (no toggle).
 *   terminal  : collapsed chip by default; expands into monospaced
 *               shell-style framing for shellish tools (shell_run /
 *               python_exec_run). Non-shellish tools fall back to the
 *               ``collapsed`` body renderer so we don't terminal-frame
 *               things like ``fs_read`` output.
 *
 * The body itself is owned by ``renderToolWidget`` (typed per-tool
 * renderers from M1/F1) — we wrap it in the design-system chrome.
 * Confirmation banner stays inline regardless of mode.
 */

import { useState } from "react";
import type { ToolCallEntry } from "../hooks/useChat";
import { Icon } from "./atoms";
import { renderToolWidget } from "./ToolWidgets";

interface Props {
  entry: ToolCallEntry;
  toolStyle?: "collapsed" | "expanded" | "terminal";
  /** True when the user has already approved/denied this exact tool
   *  call — hides the confirmation banner even if the ADK event
   *  history still reports ``confirmation_required``. Drives
   *  persistence across session switches / reloads. */
  decided?: boolean;
  onApprove?: (toolName: string, summary: string) => void | Promise<void>;
  onDeny?: (toolName: string, summary: string) => void;
}

export function ToolCallCard({
  entry,
  toolStyle = "collapsed",
  decided: decidedProp,
  onApprove,
  onDeny,
}: Props) {
  const [open, setOpen] = useState(
    toolStyle === "expanded" || entry.status === "confirmation",
  );
  const [decidedLocal, setDecidedLocal] = useState(false);
  const decided = decidedProp || decidedLocal;

  const summary =
    (entry.result?.summary as string) ||
    `${entry.name}(${shortArgs(entry.args)})`;
  const details = entry.result?.details as Record<string, unknown> | undefined;

  const isShellish = SHELLISH_TOOLS.has(entry.name);
  // ``terminal`` now means "collapsed chip that opens into a
  // terminal-framed body for shellish tools". Non-shellish tools under
  // the ``terminal`` pref fall back to the regular collapsed behavior.
  const useTerminalBody = toolStyle === "terminal" && isShellish;

  const isOpen = toolStyle === "expanded" || open;
  const cardClass = [
    "tool",
    isOpen ? "open" : "",
    toolStyle === "expanded" ? "tool-card" : "",
    useTerminalBody ? "tool-term-host" : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div className={cardClass}>
      <div className="tool-head" onClick={() => toolStyle !== "expanded" && setOpen((v) => !v)}>
        <span className="ic">
          <Icon name={iconForTool(entry.name)} size={12} />
        </span>
        <span className="nm">{entry.name}</span>
        <span className="arg">{shortArgs(entry.args)}</span>
        <StatusPill status={entry.status} />
        <span className="chev">
          <Icon name="chevR" size={11} />
        </span>
      </div>

      {entry.status === "confirmation" && !decided && (
        <ConfirmationBanner
          name={entry.name}
          summary={summary}
          details={details}
          onApprove={async () => {
            setDecidedLocal(true);
            await onApprove?.(entry.name, summary);
          }}
          onDeny={() => {
            setDecidedLocal(true);
            onDeny?.(entry.name, summary);
          }}
        />
      )}

      {isOpen && (
        <div className="tool-body">
          {useTerminalBody ? (
            <TerminalBody entry={entry} />
          ) : (() => {
            const widget = renderToolWidget(entry);
            if (widget) return widget;
            return (
              <>
                {Object.entries(entry.args).map(([k, v]) => (
                  <div className="kv" key={k}>
                    <span className="k">{k}</span>
                    <span className="v">{truncate(String(v), 300)}</span>
                  </div>
                ))}
                {entry.result && !entry.result.confirmation_required && (
                  <pre>
                    {entry.result.error
                      ? String(entry.result.error)
                      : compactPreview(entry.result)}
                  </pre>
                )}
              </>
            );
          })()}
        </div>
      )}
    </div>
  );
}

/** Shell-style body for ``terminal``-pref shellish tool calls — command
 *  line on top, stdout / stderr beneath. Rendered inside the regular
 *  expand body so the collapse/expand chip UX works the same as every
 *  other tool. Styled via the ``.tool-term-host`` override block. */
function TerminalBody({ entry }: { entry: ToolCallEntry }) {
  const dur = (entry.result?.duration_ms as number | undefined) ?? null;
  const stdout = (entry.result?.stdout as string | undefined) ?? "";
  const stderr = (entry.result?.stderr as string | undefined) ?? "";
  const cmd =
    (entry.args.command as string | undefined) ??
    (entry.args.code as string | undefined) ??
    "";
  return (
    <div className="tool-term-body">
      {cmd && <div className="p">$ {cmd}</div>}
      {stdout && <div className="out">{truncate(stdout, 2000)}</div>}
      {stderr && <div className="c">{truncate(stderr, 1000)}</div>}
      {entry.result?.error ? (
        <div className="c">! {String(entry.result.error)}</div>
      ) : null}
      {entry.status === "pending" && <div className="c">…</div>}
      {dur != null && (
        <div className="c" style={{ marginTop: 4 }}>[{dur}ms]</div>
      )}
    </div>
  );
}

function ConfirmationBanner({
  name,
  summary,
  details,
  onApprove,
  onDeny,
}: {
  name: string;
  summary: string;
  details: Record<string, unknown> | undefined;
  onApprove: () => void | Promise<void>;
  onDeny: () => void;
}) {
  return (
    <div className="appr">
      <div className="appr-hd">
        <span className="badge">approval</span>
        <div className="t">{name} needs your confirmation</div>
      </div>
      <div className="appr-bd">
        <div className="ask">{summary}</div>
        {details && (
          <div className="detail">
            {Object.entries(details).slice(0, 6).map(([k, v]) => (
              <div className="ln" key={k}>
                <span className="k">{k}</span>
                <span>{truncate(String(v), 160)}</span>
              </div>
            ))}
          </div>
        )}
      </div>
      <div className="appr-ft">
        <div className="opts" />
        <button
          className="btn ghost"
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onDeny();
          }}
        >
          Deny
        </button>
        <button
          className="btn primary"
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            void onApprove();
          }}
        >
          Approve
        </button>
      </div>
    </div>
  );
}

function StatusPill({ status }: { status: ToolCallEntry["status"] }) {
  const map: Record<string, { cls: string; label: string }> = {
    pending: { cls: "run", label: "running" },
    ok: { cls: "ok", label: "ok" },
    error: { cls: "err", label: "error" },
    confirmation: { cls: "err", label: "approval" },
  };
  const v = map[status] ?? map.pending;
  return <span className={`status ${v.cls}`}>{v.label}</span>;
}

const SHELLISH_TOOLS = new Set([
  "shell_run",
  "python_exec_run",
]);

function iconForTool(name: string): string {
  if (name.startsWith("fs_")) return "doc";
  if (name.startsWith("python") || name.startsWith("shell")) return "terminal";
  if (name.startsWith("http") || name.startsWith("search") || name.startsWith("web")) return "globe";
  if (name.startsWith("email")) return "doc";
  if (name === "load_skill") return "puzzle";
  return "zap";
}

function shortArgs(args: Record<string, unknown>): string {
  const keys = Object.keys(args);
  if (!keys.length) return "";
  if (keys.length === 1) {
    return `${keys[0]}: ${truncate(String(args[keys[0]]), 80)}`;
  }
  return keys.map((k) => `${k}: ${truncate(String(args[k]), 30)}`).join(", ");
}

function truncate(s: string, limit: number): string {
  return s.length > limit ? s.slice(0, limit) + "…" : s;
}

function compactPreview(result: Record<string, unknown>): string {
  const text = result.content || result.text || result.stdout || result.output;
  if (typeof text === "string" && text) return truncate(text, 500);
  return truncate(JSON.stringify(result, null, 2), 500);
}
