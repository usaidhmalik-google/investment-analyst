import { useEffect, useState } from 'react';
import { getConfig } from '../api/client';
import type { ConfigResponse } from '../types';

/** Fetch /api/config once. Failures are non-fatal (UI falls back to defaults). */
export function useConfig(): ConfigResponse | null {
  const [config, setConfig] = useState<ConfigResponse | null>(null);
  useEffect(() => {
    const ctrl = new AbortController();
    getConfig(ctrl.signal)
      .then(setConfig)
      .catch(() => {
        /* backend unavailable or unauthorized; defaults are used */
      });
    return () => ctrl.abort();
  }, []);
  return config;
}

const THEME_KEY = 'ia-theme';

function initialDark(): boolean {
  if (typeof document === 'undefined') return true;
  return document.documentElement.classList.contains('dark');
}

export function useTheme(): [boolean, () => void] {
  const [dark, setDark] = useState<boolean>(initialDark);
  useEffect(() => {
    document.documentElement.classList.toggle('dark', dark);
    try {
      localStorage.setItem(THEME_KEY, dark ? 'dark' : 'light');
    } catch {
      /* storage unavailable */
    }
  }, [dark]);
  return [dark, () => setDark((d) => !d)];
}
