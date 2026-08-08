/**
 * preload.ts — Puente seguro entre el renderer y el proceso main.
 *
 * Expone una API mínima y tipada vía contextBridge. El renderer NO
 * tiene acceso a Node; toda interacción con el SO pasa por aquí.
 */
import { contextBridge, ipcRenderer } from 'electron';

const api = {
  bridge: {
    getPort: (): Promise<number | null> => ipcRenderer.invoke('bridge:get-port'),
    getUrl: (): Promise<string | null> => ipcRenderer.invoke('bridge:get-url'),
  },
  theme: {
    set: (mode: 'system' | 'light' | 'dark') =>
      ipcRenderer.invoke('theme:set', mode) as Promise<{ mode: string; effective: string }>,
    get: () => ipcRenderer.invoke('theme:get') as Promise<{ source: string; effective: string }>,
    onChange: (cb: (e: { effective: string }) => void) => {
      const h = (_e: unknown, payload: { effective: string }) => cb(payload);
      ipcRenderer.on('theme:system-changed', h);
      return () => ipcRenderer.removeListener('theme:system-changed', h);
    },
  },
  app: {
    minimizeToTray: () => ipcRenderer.invoke('app:minimize-to-tray'),
    quit: () => ipcRenderer.invoke('app:quit'),
  },
  notify: (title: string, body: string) => ipcRenderer.invoke('notify', title, body),
  openExternal: (url: string) => ipcRenderer.invoke('shell:open', url),
  update: {
    check: () => ipcRenderer.invoke('update:check'),
    install: () => ipcRenderer.invoke('update:install'),
    onStatus: (cb: (s: any) => void) => {
      const h = (_e: unknown, p: any) => cb(p);
      ipcRenderer.on('update:status', h);
      ipcRenderer.on('update:progress', h);
      return () => {
        ipcRenderer.removeListener('update:status', h);
        ipcRenderer.removeListener('update:progress', h);
      };
    },
  },
};

export type ElectronAPI = typeof api;

contextBridge.exposeInMainWorld('electronAPI', api);
