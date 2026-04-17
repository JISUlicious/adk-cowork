export type ThemeMode = "light" | "dark" | "system";

const THEME_PREF_KEY = "cowork.themePref";
const MEDIA_QUERY = "(prefers-color-scheme: dark)";

const getMediaQueryList = () =>
  typeof window === "undefined" ? null : window.matchMedia(MEDIA_QUERY);

const readStoredMode = (): ThemeMode => {
  if (typeof window === "undefined") return "system";
  try {
    const stored = window.localStorage.getItem(THEME_PREF_KEY);
    if (stored === "light" || stored === "dark" || stored === "system")
      return stored;
  } catch {
    /* ignore */
  }
  return "system";
};

const resolveMode = (mode: ThemeMode): "light" | "dark" => {
  if (mode !== "system") return mode;
  return getMediaQueryList()?.matches ? "dark" : "light";
};

const applyTheme = (mode: ThemeMode) => {
  if (typeof document === "undefined") return;
  const resolved = resolveMode(mode);
  document.documentElement.dataset.theme = resolved;
  document.documentElement.style.colorScheme = resolved;
};

export const bootstrapTheme = () => {
  applyTheme(readStoredMode());
};

export const getInitialThemeMode = () => readStoredMode();

export const applyThemeMode = (mode: ThemeMode) => {
  applyTheme(mode);
};

export const persistThemeMode = (mode: ThemeMode) => {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(THEME_PREF_KEY, mode);
  } catch {
    /* ignore */
  }
};

export const subscribeToSystemTheme = (onChange: (isDark: boolean) => void) => {
  const list = getMediaQueryList();
  if (!list) return () => undefined;
  const handler = (event: MediaQueryListEvent) => onChange(event.matches);
  list.addEventListener("change", handler);
  return () => list.removeEventListener("change", handler);
};
