import { useEffect, useState } from "react";
import { CoworkClient } from "../transport/client";
import {
  type ThemeMode,
  applyThemeMode,
  getInitialThemeMode,
  persistThemeMode,
  subscribeToSystemTheme,
} from "../theme";
import { Sun, Moon, Monitor, Menu } from "lucide-react";

interface Props {
  client: CoworkClient;
  project: string | null;
  sessionId: string | null;
  sessionTitle?: string;
  onToggleSidebar?: () => void;
}

const THEME_CYCLE: ThemeMode[] = ["light", "dark", "system"];
const THEME_ICONS: Record<ThemeMode, typeof Sun> = {
  light: Sun,
  dark: Moon,
  system: Monitor,
};

export function TopBar({
  client,
  project,
  sessionId,
  sessionTitle,
  onToggleSidebar,
}: Props) {
  const [policyMode, setPolicyMode] = useState("work");
  const [themeMode, setThemeMode] = useState<ThemeMode>(getInitialThemeMode);

  useEffect(() => {
    return subscribeToSystemTheme(() => {
      if (themeMode === "system") applyThemeMode("system");
    });
  }, [themeMode]);

  useEffect(() => {
    client.getPolicyMode().then(setPolicyMode).catch(() => {});
  }, [client]);

  const cycleTheme = () => {
    const idx = THEME_CYCLE.indexOf(themeMode);
    const next = THEME_CYCLE[(idx + 1) % THEME_CYCLE.length];
    setThemeMode(next);
    applyThemeMode(next);
    persistThemeMode(next);
  };

  const ThemeIcon = THEME_ICONS[themeMode];

  const title = sessionTitle || (sessionId ? sessionId.slice(0, 8) : project || "Cowork");

  return (
    <header className="z-10 flex h-12 shrink-0 items-center justify-between border-b border-[var(--dls-border)] bg-[var(--dls-surface)] px-4 md:px-6">
      <div className="flex min-w-0 items-center gap-3">
        {/* Mobile sidebar toggle */}
        {onToggleSidebar && (
          <button
            type="button"
            onClick={onToggleSidebar}
            className="flex h-9 w-9 items-center justify-center rounded-md text-[var(--dls-text-secondary)] transition-colors hover:bg-[var(--dls-hover)] hover:text-[var(--dls-text-primary)] lg:hidden"
          >
            <Menu size={18} />
          </button>
        )}
        <h1 className="truncate text-[15px] font-semibold text-[var(--dls-text-primary)]">
          {title}
        </h1>
        {project && (
          <span className="hidden truncate text-[13px] text-[var(--dls-text-secondary)] lg:inline">
            {project}
          </span>
        )}
      </div>

      <div className="flex items-center gap-1.5">
        {/* Policy mode */}
        <select
          value={policyMode}
          onChange={async (e) => {
            const mode = e.target.value;
            try {
              const confirmed = await client.setPolicyMode(mode);
              setPolicyMode(confirmed);
            } catch {
              /* revert on failure */
            }
          }}
          className={`rounded-md px-2.5 py-1.5 text-[12px] font-medium transition-colors focus:outline-none ${policyModeClass(policyMode)}`}
          title="Policy mode"
        >
          <option value="plan">Plan</option>
          <option value="work">Work</option>
          <option value="auto">Auto</option>
        </select>

        <div className="h-4 w-px bg-[var(--dls-border)]" />

        {/* Theme toggle */}
        <button
          type="button"
          onClick={cycleTheme}
          className="flex h-9 w-9 items-center justify-center rounded-md text-[var(--dls-text-secondary)] transition-colors hover:bg-[var(--dls-hover)] hover:text-[var(--dls-text-primary)]"
          title={`Theme: ${themeMode}`}
        >
          <ThemeIcon size={16} />
        </button>
      </div>
    </header>
  );
}

function policyModeClass(mode: string): string {
  switch (mode) {
    case "plan":
      return "border border-blue-400/50 bg-blue-500/10 text-blue-600 dark:text-blue-400";
    case "auto":
      return "border border-amber-400/50 bg-amber-500/10 text-amber-600 dark:text-amber-400";
    default:
      return "border border-green-400/50 bg-green-500/10 text-green-600 dark:text-green-400";
  }
}
