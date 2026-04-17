interface Props {
  sessionId: string | null;
  policyMode?: string;
  connected?: boolean;
  statusLabel?: string;
  statusDetail?: string;
}

export function StatusBar({
  sessionId,
  policyMode,
  connected = true,
  statusLabel,
  statusDetail,
}: Props) {
  const label = statusLabel || (connected ? "Ready" : "Disconnected");
  const detail = statusDetail || (connected
    ? sessionId
      ? `Session ${sessionId.slice(0, 8)}`
      : "Waiting for session"
    : "Check server connection");

  const dotClass = connected ? "bg-green-500" : "bg-red-500";
  const pingClass = connected ? "bg-green-500/40 animate-ping" : "bg-red-500/30";

  return (
    <div className="border-t border-[var(--dls-border)] bg-[var(--dls-surface)]">
      <div className="flex h-10 items-center justify-between gap-3 px-4 md:px-6 text-[12px] text-[var(--dls-text-secondary)]">
        <div className="flex min-w-0 items-center gap-2.5">
          {/* Animated status dot */}
          <span className="relative flex h-2.5 w-2.5 shrink-0 items-center justify-center">
            {connected && (
              <span className={`absolute inline-flex h-full w-full rounded-full ${pingClass}`} />
            )}
            <span className={`relative inline-flex h-2.5 w-2.5 rounded-full ${dotClass}`} />
          </span>
          <span className="shrink-0 font-medium text-[var(--dls-text-primary)]">
            {label}
          </span>
          <span className="truncate">
            {detail}
          </span>
          {policyMode && (
            <>
              <span className="text-[var(--dls-border)]">&middot;</span>
              <span className="capitalize">{policyMode} mode</span>
            </>
          )}
        </div>

        {sessionId && (
          <span
            className="shrink-0 font-mono text-[11px] opacity-60"
            title={sessionId}
          >
            {sessionId.slice(0, 12)}
          </span>
        )}
      </div>
    </div>
  );
}
