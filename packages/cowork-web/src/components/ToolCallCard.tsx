import { useState } from "react";
import type { ToolCallEntry } from "../hooks/useChat";

interface Props {
  entry: ToolCallEntry;
  onApprove?: (summary: string) => void;
  onDeny?: (summary: string) => void;
}

const STATUS_STYLE: Record<string, string> = {
  pending: "border-yellow-400 bg-yellow-50 dark:bg-yellow-900/20",
  ok: "border-green-400 bg-green-50 dark:bg-green-900/20",
  error: "border-red-400 bg-red-50 dark:bg-red-900/20",
  confirmation: "border-amber-400 bg-amber-50 dark:bg-amber-900/20",
};

const STATUS_ICON: Record<string, string> = {
  pending: "\u23f3",
  ok: "\u2713",
  error: "\u2717",
  confirmation: "\u26a0",
};

export function ToolCallCard({ entry, onApprove, onDeny }: Props) {
  const [expanded, setExpanded] = useState(
    entry.status === "confirmation",
  );
  const [decided, setDecided] = useState(false);

  const summary =
    (entry.result?.summary as string) ||
    `${entry.name}(${JSON.stringify(entry.args)})`;
  const details = entry.result?.details as Record<string, unknown> | undefined;

  return (
    <div
      className={`border-l-4 rounded-lg px-3 py-2 text-xs font-mono ${STATUS_STYLE[entry.status] || STATUS_STYLE.pending}`}
    >
      <div
        className="flex items-center gap-2 cursor-pointer"
        onClick={() => setExpanded(!expanded)}
      >
        <span>{STATUS_ICON[entry.status] || ""}</span>
        <span className="font-semibold">{entry.name}</span>
        <span className="text-[var(--dls-text-secondary)] ml-auto">
          {expanded ? "\u25b2" : "\u25bc"}
        </span>
      </div>

      {/* Confirmation banner — always visible when confirmation status */}
      {entry.status === "confirmation" && !decided && (
        <div className="mt-2 p-2 rounded bg-amber-100 dark:bg-amber-900/40 text-amber-800 dark:text-amber-200 text-xs">
          <p className="mb-2 font-medium">{summary}</p>
          {details && (
            <div className="mb-2 space-y-0.5 text-[11px] opacity-80">
              {details.to ? <div><span className="font-medium">To:</span> {String(details.to)}</div> : null}
              {details.cc ? <div><span className="font-medium">Cc:</span> {String(details.cc)}</div> : null}
              {details.subject ? <div><span className="font-medium">Subject:</span> {String(details.subject)}</div> : null}
              {details.body_preview ? (
                <div className="mt-1 italic whitespace-pre-wrap">{truncate(String(details.body_preview), 200)}</div>
              ) : null}
            </div>
          )}
          <div className="flex gap-2">
            <button
              onClick={(e) => {
                e.stopPropagation();
                setDecided(true);
                onApprove?.(summary);
              }}
              className="px-3 py-1 rounded bg-green-600 text-white hover:bg-green-700 font-medium"
            >
              Approve
            </button>
            <button
              onClick={(e) => {
                e.stopPropagation();
                setDecided(true);
                onDeny?.(summary);
              }}
              className="px-3 py-1 rounded bg-red-600 text-white hover:bg-red-700 font-medium"
            >
              Deny
            </button>
          </div>
        </div>
      )}

      {expanded && (
        <div className="mt-2 space-y-1 text-[11px]">
          {Object.entries(entry.args).map(([k, v]) => (
            <div key={k} className="flex gap-2">
              <span className="text-[var(--dls-text-secondary)] shrink-0">{k}:</span>
              <span className="break-all text-[var(--dls-text-primary)]">
                {truncate(String(v), 300)}
              </span>
            </div>
          ))}
          {entry.result && (
            <div className="mt-1 pt-1 border-t border-[var(--dls-border)]">
              {entry.result.error ? (
                <span className="text-red-600">
                  {String(entry.result.error)}
                </span>
              ) : entry.result.confirmation_required ? (
                <span className="text-amber-600">
                  {decided ? "Waiting for response..." : "Awaiting your decision"}
                </span>
              ) : (
                <ResultPreview result={entry.result} />
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ResultPreview({ result }: { result: Record<string, unknown> }) {
  const content =
    result.content || result.text || result.stdout || result.output;
  if (typeof content === "string" && content) {
    return (
      <pre className="whitespace-pre-wrap text-[var(--dls-text-secondary)] max-h-32 overflow-y-auto">
        {truncate(content, 500)}
      </pre>
    );
  }
  // Compact JSON for other results
  const json = JSON.stringify(result, null, 2);
  return (
    <pre className="whitespace-pre-wrap text-[var(--dls-text-secondary)] max-h-32 overflow-y-auto">
      {truncate(json, 500)}
    </pre>
  );
}

function truncate(s: string, limit: number): string {
  return s.length > limit ? s.slice(0, limit) + "\u2026" : s;
}
