/// <reference types="vite/client" />

interface Window {
  electronAPI: {
    bridge: {
      getPort: () => Promise<number | null>;
      getUrl: () => Promise<string | null>;
    };
    theme: {
      set: (mode: 'system' | 'light' | 'dark') => Promise<{ mode: string; effective: string }>;
      get: () => Promise<{ source: string; effective: string }>;
      onChange: (cb: (e: { effective: string }) => void) => () => void;
    };
    app: {
      minimizeToTray: () => Promise<void>;
      quit: () => Promise<void>;
    };
    notify: (title: string, body: string) => Promise<void>;
    openExternal: (url: string) => Promise<void>;
    update: {
      check: () => Promise<{ ok: boolean; version?: string | null; message?: string }>;
      install: () => Promise<{ ok: boolean; message?: string }>;
      onStatus: (cb: (s: { state?: string; version?: string; percent?: number; message?: string }) => void) => () => void;
    };
  };
}
