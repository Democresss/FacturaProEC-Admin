/**
 * useTheme — Dark / Light / System con auto-detección y persistencia.
 *
 * Habla con el main process via IPC para que nativeTheme sea consistente,
 * y aplica data-theme al <html> para que las variables CSS reaccionen.
 */
import { useState, useEffect, useCallback } from 'react';

export type ThemeMode = 'system' | 'light' | 'dark';
export type EffectiveTheme = 'light' | 'dark';

function persist(mode: ThemeMode) {
  try { localStorage.setItem('fpec_theme', mode); } catch {}
}

function loadStored(): ThemeMode {
  try {
    const v = localStorage.getItem('fpec_theme');
    if (v === 'light' || v === 'dark' || v === 'system') return v;
  } catch {}
  return 'system';
}

export function useTheme() {
  const [mode, setMode] = useState<ThemeMode>(() => loadStored());
  const [effective, setEffective] = useState<EffectiveTheme>('light');

  // Aplicar al DOM
  const apply = useCallback((eff: EffectiveTheme) => {
    document.documentElement.setAttribute('data-theme', eff);
    setEffective(eff);
  }, []);

  // Configurar en electron main + escuchar cambios del SO
  useEffect(() => {
    const ea = (window as any).electronAPI;

    async function init() {
      if (ea?.theme) {
        try {
          await ea.theme.set(mode);
          const cur = await ea.theme.get();
          apply(cur.effective as EffectiveTheme);

          if (ea.theme.onChange) {
            ea.theme.onChange((e: { effective: string }) => {
              apply(e.effective as EffectiveTheme);
            });
          }
        } catch { /* no electron */ }
      } else {
        // Browser fallback
        if (mode === 'system') {
          const dark = window.matchMedia('(prefers-color-scheme: dark)').matches;
          apply(dark ? 'dark' : 'light');
        } else {
          apply(mode);
        }
      }
    }
    init();
  }, [mode, apply]);

  const change = useCallback((m: ThemeMode) => {
    setMode(m);
    persist(m);
  }, []);

  return { mode, effective, change };
}
