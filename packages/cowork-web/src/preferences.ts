/**
 * Per-user appearance preferences (client-side only).
 *
 * The Settings → Appearance group binds to this store; components
 * read ``toolStyle`` to pick the tool-call rendering variant. Theme
 * is delegated to ``theme.ts`` which already handles ``system`` with
 * media-query tracking.
 *
 * Storage is plain ``localStorage`` under ``cowork_prefs`` — the same
 * shape the design prototype used (``cowork_tweaks``), renamed to
 * reflect that it's shipped user-facing config, not a hidden dev knob.
 *
 * Knobs dropped in Phase F cleanup because they were cosmetic with no
 * behavioural difference or because only one value was ever wired:
 * - ``approvalStyle`` (banner / queue variants) — inline is permanent.
 * - ``refinement`` — only ``editorial`` was ever wired.
 * - ``density`` / ``layout`` — rarely changed, noisy Settings rows;
 *   kept as static defaults on ``<html>`` so the CSS still hits.
 */

import { useCallback, useEffect, useState } from "react";
import type { ThemeMode } from "./theme";

export type ToolStyle = "collapsed" | "expanded" | "terminal";

export interface Preferences {
  theme: ThemeMode;
  accentHue: number;
  toolStyle: ToolStyle;
}

export const DEFAULT_PREFERENCES: Preferences = {
  theme: "system",
  accentHue: 42,
  toolStyle: "collapsed",
};

const STORAGE_KEY = "cowork_prefs";

const readStored = (): Partial<Preferences> => {
  if (typeof window === "undefined") return {};
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    return typeof parsed === "object" && parsed !== null ? parsed : {};
  } catch {
    return {};
  }
};

export const loadPreferences = (): Preferences => ({
  ...DEFAULT_PREFERENCES,
  ...readStored(),
});

export const persistPreferences = (prefs: Preferences): void => {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs));
  } catch {
    /* ignore storage failures — preferences are soft state */
  }
};

/**
 * Apply preferences that map 1:1 to a DOM attribute or custom property
 * on ``<html>``. Theme is handled by ``theme.ts`` (media-query aware)
 * and excluded here — callers should invoke ``applyThemeMode`` alongside.
 */
export const applyAppearance = (prefs: Preferences): void => {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  // ``density``, ``layout``, and ``refinement`` are no longer
  // user-facing knobs; pin them to the defaults that every component
  // was already designed around so the CSS attribute selectors still
  // match.
  root.dataset.density = "airy";
  root.dataset.layout = "three";
  root.dataset.refinement = "editorial";
  root.style.setProperty("--accent-h", String(prefs.accentHue));
};

/**
 * React hook backed by ``localStorage``. Updates are mirrored into the
 * DOM via ``applyAppearance`` so the rest of the tree picks them up
 * through CSS attribute selectors (no prop drilling).
 *
 * A custom ``cowork:prefs-change`` event broadcasts updates inside the
 * tab so unrelated components stay in sync.
 */
const PREFS_EVENT = "cowork:prefs-change";

export function usePreferences(): [Preferences, (patch: Partial<Preferences>) => void] {
  const [prefs, setPrefs] = useState<Preferences>(() => loadPreferences());

  useEffect(() => {
    const onChange = (e: Event) => {
      const detail = (e as CustomEvent<Preferences>).detail;
      if (detail) setPrefs(detail);
    };
    window.addEventListener(PREFS_EVENT, onChange as EventListener);
    return () => window.removeEventListener(PREFS_EVENT, onChange as EventListener);
  }, []);

  const update = useCallback((patch: Partial<Preferences>) => {
    setPrefs((prev) => {
      const next = { ...prev, ...patch };
      persistPreferences(next);
      applyAppearance(next);
      window.dispatchEvent(new CustomEvent(PREFS_EVENT, { detail: next }));
      return next;
    });
  }, []);

  return [prefs, update];
}
