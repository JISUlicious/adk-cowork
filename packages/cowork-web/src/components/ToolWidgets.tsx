/**
 * Per-tool renderers.
 *
 * The generic arg/result dump in {@link ToolCallCard} is a fallback — it's
 * useful for tools we haven't specialized yet, but every tool the model
 * uses frequently gets a widget here that speaks its schema directly.
 *
 * Each widget reads its own ``args`` + ``result`` out of the
 * {@link ToolCallEntry} and returns ``null`` when there's nothing useful to
 * show yet (e.g. the tool is still ``pending``). ``renderToolWidget`` is the
 * single dispatcher called from the card.
 */

import type { ReactNode } from "react";
import type { ToolCallEntry } from "../hooks/useChat";

// ──────────────────────────── primitives ───────────────────────────────

function truncate(s: string, limit: number): string {
  return s.length > limit ? s.slice(0, limit) + "\u2026" : s;
}

function Pre({ children }: { children: ReactNode }) {
  return (
    <pre className="whitespace-pre-wrap break-all text-[11px] font-mono text-[var(--dls-text-primary)] bg-[var(--dls-app-bg)] border border-[var(--dls-border)] rounded-md px-2 py-1.5 max-h-40 overflow-y-auto">
      {children}
    </pre>
  );
}

function Labelled({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex gap-2">
      <span className="text-[var(--dls-text-secondary)] text-[11px] shrink-0 w-20">
        {label}
      </span>
      <span className="text-[11px] text-[var(--dls-text-primary)] min-w-0 flex-1 break-all">
        {children}
      </span>
    </div>
  );
}

function Path({ path }: { path: string }) {
  return (
    <code className="px-1.5 py-0.5 rounded bg-[var(--dls-app-bg)] text-[11px] text-[var(--dls-text-primary)] break-all">
      {path}
    </code>
  );
}

// ──────────────────────────── fs_edit: diff ────────────────────────────

/**
 * Line-level diff via Longest Common Subsequence.
 *
 * The agent's ``fs_edit`` supplies ``old`` + ``new`` substrings — usually a
 * few lines each. A real LCS walk lets us call out only the changed lines
 * (as ``-``/``+``) while preserving surrounding context (``=``), which
 * reads much better for multi-line edits than dumping all old-then-new.
 *
 * Complexity is O(n·m) which is fine for the snippet sizes we see — the
 * file contents themselves never land here, only the edit endpoints.
 */
type DiffRow = { kind: "-" | "+" | "="; text: string };

function lcsDiff(oldLines: string[], newLines: string[]): DiffRow[] {
  const n = oldLines.length;
  const m = newLines.length;
  // Build LCS length table.
  const table: number[][] = Array.from({ length: n + 1 }, () =>
    new Array(m + 1).fill(0),
  );
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      table[i][j] =
        oldLines[i] === newLines[j]
          ? table[i + 1][j + 1] + 1
          : Math.max(table[i + 1][j], table[i][j + 1]);
    }
  }
  // Walk the table to emit the diff.
  const rows: DiffRow[] = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (oldLines[i] === newLines[j]) {
      rows.push({ kind: "=", text: oldLines[i] });
      i++;
      j++;
    } else if (table[i + 1][j] >= table[i][j + 1]) {
      rows.push({ kind: "-", text: oldLines[i] });
      i++;
    } else {
      rows.push({ kind: "+", text: newLines[j] });
      j++;
    }
  }
  while (i < n) rows.push({ kind: "-", text: oldLines[i++] });
  while (j < m) rows.push({ kind: "+", text: newLines[j++] });
  return rows;
}

function DiffLines({ oldText, newText }: { oldText: string; newText: string }) {
  const rows = lcsDiff(oldText.split("\n"), newText.split("\n"));
  return (
    <pre className="text-[11px] font-mono rounded-md bg-[var(--dls-app-bg)] border border-[var(--dls-border)] overflow-x-auto max-h-48 overflow-y-auto">
      {rows.map((r, i) => (
        <div
          key={i}
          className={
            r.kind === "+"
              ? "px-2 bg-green-500/10 text-green-700 dark:text-green-300"
              : r.kind === "-"
                ? "px-2 bg-red-500/10 text-red-700 dark:text-red-300"
                : "px-2 text-[var(--dls-text-secondary)]"
          }
        >
          <span className="inline-block w-3 select-none opacity-60">
            {r.kind === "=" ? " " : r.kind}
          </span>
          {r.text || " "}
        </div>
      ))}
    </pre>
  );
}

function FsEditWidget({ entry }: { entry: ToolCallEntry }) {
  const path = String(entry.args.path ?? "");
  const oldText = String(entry.args.old ?? "");
  const newText = String(entry.args.new ?? "");
  return (
    <div className="space-y-2">
      <Labelled label="path">
        <Path path={path} />
      </Labelled>
      <DiffLines oldText={oldText} newText={newText} />
      {entry.result?.bytes ? (
        <div className="text-[11px] text-[var(--dls-text-secondary)]">
          wrote {String(entry.result.bytes)} bytes
        </div>
      ) : null}
    </div>
  );
}

// ──────────────────────────── fs_read / fs_write ───────────────────────

function FsReadWidget({ entry }: { entry: ToolCallEntry }) {
  const path = String(entry.args.path ?? "");
  const content =
    typeof entry.result?.content === "string" ? entry.result.content : null;
  const truncated = Boolean(entry.result?.truncated);
  return (
    <div className="space-y-1.5">
      <Labelled label="path">
        <Path path={path} />
      </Labelled>
      {content !== null && (
        <>
          <Pre>{truncate(content, 1500)}</Pre>
          <div className="text-[11px] text-[var(--dls-text-secondary)]">
            {content.length} chars{truncated ? " (truncated at 2 MB)" : ""}
          </div>
        </>
      )}
    </div>
  );
}

function FsWriteWidget({ entry }: { entry: ToolCallEntry }) {
  const path = String(entry.args.path ?? "");
  const content = String(entry.args.content ?? "");
  const bytes =
    typeof entry.result?.bytes === "number" ? entry.result.bytes : null;
  return (
    <div className="space-y-1.5">
      <Labelled label="path">
        <Path path={path} />
      </Labelled>
      <Pre>{truncate(content, 1500)}</Pre>
      {bytes !== null && (
        <div className="text-[11px] text-[var(--dls-text-secondary)]">
          wrote {bytes} bytes
        </div>
      )}
    </div>
  );
}

// ──────────────────────────── fs_list / fs_glob / fs_stat ──────────────

interface FsEntry {
  name: string;
  kind: string;
  size?: number | null;
}

function FsListWidget({ entry }: { entry: ToolCallEntry }) {
  const path = String(entry.args.path ?? "");
  const entries = Array.isArray(entry.result?.entries)
    ? (entry.result.entries as FsEntry[])
    : null;
  return (
    <div className="space-y-1.5">
      <Labelled label="dir">
        <Path path={path} />
      </Labelled>
      {entries && (
        <div className="rounded-md border border-[var(--dls-border)] overflow-hidden">
          {entries.length === 0 ? (
            <div className="px-2 py-1 text-[11px] text-[var(--dls-text-secondary)]">
              empty
            </div>
          ) : (
            <table className="w-full text-[11px] font-mono">
              <tbody>
                {entries.slice(0, 50).map((e) => (
                  <tr key={e.name} className="border-b border-[var(--dls-border)] last:border-0">
                    <td className="px-2 py-0.5 w-6 text-[var(--dls-text-secondary)]">
                      {e.kind === "dir" ? "📁" : "📄"}
                    </td>
                    <td className="px-2 py-0.5 truncate">{e.name}</td>
                    <td className="px-2 py-0.5 text-right text-[var(--dls-text-secondary)]">
                      {e.kind === "file" && typeof e.size === "number"
                        ? formatSize(e.size)
                        : ""}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {entries.length > 50 && (
            <div className="px-2 py-1 text-[10px] text-[var(--dls-text-secondary)] border-t border-[var(--dls-border)]">
              showing 50 of {entries.length}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function FsGlobWidget({ entry }: { entry: ToolCallEntry }) {
  const pattern = String(entry.args.pattern ?? "");
  const matches = Array.isArray(entry.result?.matches)
    ? (entry.result.matches as string[])
    : null;
  const truncated = Boolean(entry.result?.truncated);
  return (
    <div className="space-y-1.5">
      <Labelled label="pattern">
        <code className="text-[11px]">{pattern}</code>
      </Labelled>
      {matches && (
        <div className="rounded-md border border-[var(--dls-border)] overflow-hidden text-[11px] font-mono">
          {matches.length === 0 ? (
            <div className="px-2 py-1 text-[var(--dls-text-secondary)]">
              no matches
            </div>
          ) : (
            <>
              {matches.slice(0, 25).map((m, i) => (
                <div
                  key={i}
                  className="px-2 py-0.5 border-b border-[var(--dls-border)] last:border-0 truncate"
                >
                  {m}
                </div>
              ))}
              {matches.length > 25 && (
                <div className="px-2 py-1 text-[10px] text-[var(--dls-text-secondary)] border-t border-[var(--dls-border)]">
                  showing 25 of {matches.length}
                  {truncated ? " (server-side truncated)" : ""}
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}

function FsStatWidget({ entry }: { entry: ToolCallEntry }) {
  const path = String(entry.args.path ?? "");
  const r = entry.result ?? {};
  return (
    <div className="space-y-1">
      <Labelled label="path">
        <Path path={path} />
      </Labelled>
      {r.kind ? <Labelled label="kind">{String(r.kind)}</Labelled> : null}
      {typeof r.size === "number" && (
        <Labelled label="size">{formatSize(r.size)}</Labelled>
      )}
      {typeof r.mtime === "number" && (
        <Labelled label="mtime">
          {new Date(r.mtime * 1000).toLocaleString()}
        </Labelled>
      )}
    </div>
  );
}

function FsPromoteWidget({ entry }: { entry: ToolCallEntry }) {
  const relPath = String(entry.args.rel_path ?? "");
  const destPath =
    typeof entry.result?.path === "string" ? entry.result.path : null;
  return (
    <div className="space-y-1">
      <Labelled label="from">
        <Path path={`scratch/${relPath}`} />
      </Labelled>
      {destPath && (
        <Labelled label="to">
          <Path path={destPath} />
        </Labelled>
      )}
    </div>
  );
}

// ──────────────────────────── shell_run / python_exec_run ──────────────

function ShellRunWidget({ entry }: { entry: ToolCallEntry }) {
  const argv = Array.isArray(entry.args.argv)
    ? (entry.args.argv as string[])
    : null;
  const r = entry.result ?? {};
  const exitCode = typeof r.exit_code === "number" ? r.exit_code : null;
  const stdout = typeof r.stdout === "string" ? r.stdout : "";
  const stderr = typeof r.stderr === "string" ? r.stderr : "";
  const durationMs = typeof r.duration_ms === "number" ? r.duration_ms : null;
  return (
    <div className="space-y-1.5">
      {argv && (
        <Labelled label="cmd">
          <code className="text-[11px]">$ {argv.join(" ")}</code>
        </Labelled>
      )}
      {exitCode !== null && (
        <div className="flex gap-3 text-[11px] text-[var(--dls-text-secondary)]">
          <span>
            exit{" "}
            <span
              className={exitCode === 0 ? "text-green-500" : "text-red-500"}
            >
              {exitCode}
            </span>
          </span>
          {durationMs !== null && <span>{durationMs} ms</span>}
        </div>
      )}
      {stdout && (
        <div>
          <div className="text-[10px] text-[var(--dls-text-secondary)] mb-0.5">
            stdout
          </div>
          <Pre>{truncate(stdout, 2000)}</Pre>
        </div>
      )}
      {stderr && (
        <div>
          <div className="text-[10px] text-[var(--dls-text-secondary)] mb-0.5">
            stderr
          </div>
          <pre className="whitespace-pre-wrap text-[11px] font-mono bg-red-500/5 border border-red-500/30 rounded-md px-2 py-1.5 max-h-40 overflow-y-auto">
            {truncate(stderr, 2000)}
          </pre>
        </div>
      )}
    </div>
  );
}

function PythonExecWidget({ entry }: { entry: ToolCallEntry }) {
  const code = String(entry.args.code ?? "");
  const r = entry.result ?? {};
  const exitCode = typeof r.exit_code === "number" ? r.exit_code : null;
  const stdout = typeof r.stdout === "string" ? r.stdout : "";
  const stderr = typeof r.stderr === "string" ? r.stderr : "";
  const durationMs = typeof r.duration_ms === "number" ? r.duration_ms : null;
  return (
    <div className="space-y-1.5">
      <div>
        <div className="text-[10px] text-[var(--dls-text-secondary)] mb-0.5">
          code
        </div>
        <Pre>{truncate(code, 1500)}</Pre>
      </div>
      {exitCode !== null && (
        <div className="flex gap-3 text-[11px] text-[var(--dls-text-secondary)]">
          <span>
            exit{" "}
            <span
              className={exitCode === 0 ? "text-green-500" : "text-red-500"}
            >
              {exitCode}
            </span>
          </span>
          {durationMs !== null && <span>{durationMs} ms</span>}
        </div>
      )}
      {stdout && (
        <div>
          <div className="text-[10px] text-[var(--dls-text-secondary)] mb-0.5">
            stdout
          </div>
          <Pre>{truncate(stdout, 2000)}</Pre>
        </div>
      )}
      {stderr && (
        <div>
          <div className="text-[10px] text-[var(--dls-text-secondary)] mb-0.5">
            stderr
          </div>
          <pre className="whitespace-pre-wrap text-[11px] font-mono bg-red-500/5 border border-red-500/30 rounded-md px-2 py-1.5 max-h-40 overflow-y-auto">
            {truncate(stderr, 2000)}
          </pre>
        </div>
      )}
    </div>
  );
}

// ──────────────────────────── http_fetch ───────────────────────────────

function HttpFetchWidget({ entry }: { entry: ToolCallEntry }) {
  const url = String(entry.args.url ?? "");
  const r = entry.result ?? {};
  const status = typeof r.status === "number" ? r.status : null;
  const content = typeof r.content === "string" ? r.content : "";
  const truncated = Boolean(r.truncated);
  return (
    <div className="space-y-1.5">
      <Labelled label="GET">
        <code className="text-[11px] break-all">{url}</code>
      </Labelled>
      {status !== null && (
        <Labelled label="status">
          <span
            className={
              status >= 200 && status < 300
                ? "text-green-500"
                : status >= 400
                  ? "text-red-500"
                  : ""
            }
          >
            {status}
          </span>
        </Labelled>
      )}
      {content && (
        <>
          <Pre>{truncate(content, 2000)}</Pre>
          {truncated && (
            <div className="text-[10px] text-[var(--dls-text-secondary)]">
              body truncated at 2 MB
            </div>
          )}
        </>
      )}
    </div>
  );
}

// ──────────────────────────── search_web ───────────────────────────────

interface SearchHit {
  title?: string;
  url?: string;
  snippet?: string;
}

function SearchWebWidget({ entry }: { entry: ToolCallEntry }) {
  const query = String(entry.args.query ?? "");
  const results = Array.isArray(entry.result?.results)
    ? (entry.result.results as SearchHit[])
    : null;
  return (
    <div className="space-y-1.5">
      <Labelled label="query">
        <span className="italic">&ldquo;{query}&rdquo;</span>
      </Labelled>
      {results && (
        <div className="space-y-2">
          {results.slice(0, 8).map((hit, i) => (
            <div key={i} className="border-l-2 border-[var(--dls-border)] pl-2">
              {hit.title && (
                <div className="text-[11px] font-medium text-[var(--dls-text-primary)] truncate">
                  {hit.title}
                </div>
              )}
              {hit.url && (
                <div className="text-[10px] text-[var(--dls-accent)] truncate">
                  {hit.url}
                </div>
              )}
              {hit.snippet && (
                <div className="text-[11px] text-[var(--dls-text-secondary)] line-clamp-2">
                  {hit.snippet}
                </div>
              )}
            </div>
          ))}
          {results.length > 8 && (
            <div className="text-[10px] text-[var(--dls-text-secondary)]">
              showing 8 of {results.length}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ──────────────────────────── load_skill ───────────────────────────────

function LoadSkillWidget({ entry }: { entry: ToolCallEntry }) {
  const name = String(entry.args.name ?? "");
  const r = entry.result ?? {};
  const description = typeof r.description === "string" ? r.description : "";
  const body = typeof r.body === "string" ? r.body : "";
  return (
    <div className="space-y-1.5">
      <Labelled label="skill">
        <span className="font-medium">{name}</span>
      </Labelled>
      {description && (
        <div className="text-[11px] italic text-[var(--dls-text-secondary)]">
          {description}
        </div>
      )}
      {body && <Pre>{truncate(body, 1200)}</Pre>}
    </div>
  );
}

// ──────────────────────────── dispatch ─────────────────────────────────

export function renderToolWidget(entry: ToolCallEntry): ReactNode | null {
  // Errors/confirmations always fall through to the generic view so the
  // card can render its banners uniformly.
  if (entry.result?.error || entry.result?.confirmation_required) return null;
  switch (entry.name) {
    case "fs_edit":
      return <FsEditWidget entry={entry} />;
    case "fs_read":
      return <FsReadWidget entry={entry} />;
    case "fs_write":
      return <FsWriteWidget entry={entry} />;
    case "fs_list":
      return <FsListWidget entry={entry} />;
    case "fs_glob":
      return <FsGlobWidget entry={entry} />;
    case "fs_stat":
      return <FsStatWidget entry={entry} />;
    case "fs_promote":
      return <FsPromoteWidget entry={entry} />;
    case "shell_run":
      return <ShellRunWidget entry={entry} />;
    case "python_exec_run":
      return <PythonExecWidget entry={entry} />;
    case "http_fetch":
      return <HttpFetchWidget entry={entry} />;
    case "search_web":
      return <SearchWebWidget entry={entry} />;
    case "load_skill":
      return <LoadSkillWidget entry={entry} />;
    default:
      return null;
  }
}

// ──────────────────────────── utils ────────────────────────────────────

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}
