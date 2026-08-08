/**
 * useBridge — hook que gestiona la conexión al backend Python FastAPI.
 *
 * Espera a que el preload entregue el puerto (escrito por el bridge en stdout),
 * y expone una función `call(path, opts)` para hacer fetch a 127.0.0.1:port.
 */
import { useState, useEffect, useCallback, useRef } from 'react';

type BridgeState = 'connecting' | 'ready' | 'error';

interface CallResult<T = any> {
  ok: boolean;
  message?: string;
  data?: T;
  [k: string]: any;
}

export function useBridge() {
  const [state, setState] = useState<BridgeState>('connecting');
  const [baseUrl, setBaseUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const urlRef = useRef<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let attempts = 0;

    async function waitForPort() {
      // El preload expone window.electronAPI
      const ea = (window as any).electronAPI;
      if (!ea?.bridge?.getUrl) {
        // Estamos en navegador puro (vite sin electron) — fallback a dev server proxy
        setBaseUrl('http://127.0.0.1:9173');
        urlRef.current = 'http://127.0.0.1:9173';
        setState('ready');
        return;
      }

      while (attempts < 60 && !cancelled) {
        attempts++;
        try {
          const url = await ea.bridge.getUrl();
          if (url) {
            if (cancelled) return;
            setBaseUrl(url);
            urlRef.current = url;
            setState('ready');
            return;
          }
        } catch (e) {
          // ignore
        }
        await new Promise(r => setTimeout(r, 500));
      }

      if (!cancelled) {
        setError('No se pudo conectar al backend Python');
        setState('error');
      }
    }
    waitForPort();

    return () => { cancelled = true; };
  }, []);

  const call = useCallback(async <T = any>(
    path: string,
    opts: RequestInit = {},
  ): Promise<CallResult<T>> => {
    const base = urlRef.current || baseUrl;
    if (!base) {
      return { ok: false, message: 'Backend no listo todavía.' } as CallResult<T>;
    }
    try {
      // Si NO hay body, asegurar method GET explícito
      const method = opts.method || (opts.body ? 'POST' : 'GET');
      const headers = { 'Content-Type': 'application/json', ...(opts.headers || {}) };
      const res = await fetch(`${base}${path}`, { ...opts, method, headers });
      if (!res.ok) {
        let text = '';
        try { text = await res.text(); } catch {}
        return { ok: false, message: `HTTP ${res.status}: ${text.slice(0, 300)}` };
      }
      const json = await res.json();
      return json as CallResult<T>;
    } catch (e: any) {
      return { ok: false, message: `${e?.name || 'Error'}: ${e?.message || String(e)}` };
    }
  }, [baseUrl]);

  return { state, error, call };
}
