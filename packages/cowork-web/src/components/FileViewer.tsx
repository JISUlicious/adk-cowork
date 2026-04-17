import { useEffect, useState } from "react";
import { CoworkClient } from "../transport/client";

interface Props {
  client: CoworkClient;
  project: string;
  path: string;
  name: string;
}

export function FileViewer({ client, project, path, name }: Props) {
  const ext = name.split(".").pop()?.toLowerCase() || "";
  const url = client.previewUrl(project, path);

  // Images: direct passthrough
  if (["png", "jpg", "jpeg", "gif", "svg", "webp", "bmp"].includes(ext)) {
    return (
      <div className="p-4 flex justify-center">
        <img
          src={url}
          alt={name}
          className="max-w-full max-h-[70vh] object-contain"
        />
      </div>
    );
  }

  // Everything else: fetch from preview endpoint
  return <PreviewFetcher url={url} ext={ext} />;
}

function PreviewFetcher({
  url,
  ext,
}: {
  url: string;
  ext: string;
}) {
  const [data, setData] = useState<string | null>(null);
  const [contentType, setContentType] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setData(null);
    setError(null);
    fetch(url)
      .then(async (r) => {
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        setContentType(r.headers.get("content-type") || "");
        return r.text();
      })
      .then(setData)
      .catch((e) => setError(String(e)));
  }, [url]);

  if (error) {
    return (
      <div className="p-4 text-red-500 text-sm">
        Failed to load preview: {error}
      </div>
    );
  }
  if (data === null) {
    return (
      <div className="p-4 text-[var(--dls-text-secondary)] text-sm animate-pulse">Loading...</div>
    );
  }

  // HTML preview (markdown). Render in a sandboxed iframe so the
  // converter's <style> rules (which target `body`) don't leak into
  // the host page and squish the whole UI.
  if (contentType.includes("text/html")) {
    return (
      <iframe
        title="preview"
        srcDoc={data}
        sandbox=""
        className="w-full h-full min-h-[60vh] border-0"
      />
    );
  }

  // JSON previews (docx, pdf, xlsx, csv)
  if (contentType.includes("application/json")) {
    try {
      const parsed = JSON.parse(data);
      return <JsonPreview data={parsed} ext={ext} />;
    } catch {
      return <CodeBlock content={data} />;
    }
  }

  // Fallback: plain text
  return <CodeBlock content={data} />;
}

function JsonPreview({ data, ext }: { data: unknown; ext: string }) {
  // docx: paragraphs
  if (
    ext === "docx" &&
    typeof data === "object" &&
    data !== null &&
    "paragraphs" in data
  ) {
    const doc = data as { paragraphs: { text: string; style: string | null }[] };
    return (
      <div className="p-4 space-y-2 text-sm">
        {doc.paragraphs.map((p, i) => (
          <p key={i} className={p.style === "Heading 1" ? "text-lg font-bold" : ""}>
            {p.text || "\u00a0"}
          </p>
        ))}
      </div>
    );
  }

  // pdf: pages
  if (
    ext === "pdf" &&
    typeof data === "object" &&
    data !== null &&
    "pages" in data
  ) {
    const pdf = data as {
      page_count: number;
      metadata: Record<string, string | null>;
      pages: { page: number; text: string }[];
    };
    return (
      <div className="p-4 text-sm space-y-4">
        <div className="text-xs text-[var(--dls-text-secondary)]">
          {pdf.page_count} page{pdf.page_count !== 1 ? "s" : ""}
          {pdf.metadata.title && ` \u2014 ${pdf.metadata.title}`}
        </div>
        {pdf.pages.map((p) => (
          <div key={p.page} className="border-b pb-2 border-[var(--dls-border)]">
            <div className="text-[10px] text-[var(--dls-text-secondary)] mb-1">Page {p.page}</div>
            <div className="whitespace-pre-wrap">{p.text}</div>
          </div>
        ))}
      </div>
    );
  }

  // csv/xlsx: table
  if (typeof data === "object" && data !== null) {
    const sheets = Array.isArray(data) ? data : [data];
    return (
      <div className="p-2 overflow-x-auto">
        {sheets.map((sheet, si) => {
          const rows: unknown[][] = sheet.rows || [];
          const schema: string[] = sheet.schema || [];
          return (
            <div key={si} className="mb-4">
              {sheet.name && (
                <div className="text-xs text-[var(--dls-text-secondary)] mb-1 px-1">
                  {sheet.name}
                </div>
              )}
              <table className="text-xs border-collapse w-full">
                {schema.length > 0 && (
                  <thead>
                    <tr>
                      {schema.map((h: string, j: number) => (
                        <th
                          key={j}
                          className="border border-[var(--dls-border)] px-2 py-1 bg-[var(--dls-hover)] text-left font-medium"
                        >
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                )}
                <tbody>
                  {rows.slice(0, 200).map((row: unknown[], ri: number) => (
                    <tr key={ri}>
                      {(row as unknown[]).map((cell: unknown, ci: number) => (
                        <td
                          key={ci}
                          className="border border-[var(--dls-border)] px-2 py-1"
                        >
                          {cell != null ? String(cell) : ""}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
              {rows.length > 200 && (
                <div className="text-[10px] text-[var(--dls-text-secondary)] mt-1 px-1">
                  Showing 200 of {rows.length} rows
                </div>
              )}
            </div>
          );
        })}
      </div>
    );
  }

  return <CodeBlock content={JSON.stringify(data, null, 2)} />;
}

function CodeBlock({ content }: { content: string }) {
  return (
    <pre className="p-4 text-xs font-mono whitespace-pre-wrap overflow-auto text-[var(--dls-text-primary)]">
      {content}
    </pre>
  );
}
