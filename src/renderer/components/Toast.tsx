import React, { createContext, useContext, useState, useCallback, useRef } from 'react';
import { emitirAviso } from './Avisos';

export type ToastKind = 'success' | 'warning' | 'danger' | 'info';

interface ToastItem {
  id: number;
  title: string;
  body?: string;
  kind: ToastKind;
}

interface ToastCtx {
  toast: (title: string, body?: string, kind?: ToastKind) => void;
}

const Ctx = createContext<ToastCtx>({ toast: () => {} });

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const idRef = useRef(0);

  const toast = useCallback((title: string, body?: string, kind: ToastKind = 'info') => {
    const id = ++idRef.current;
    setItems(prev => [...prev, { id, title, body, kind }]);
    // Lo que importa (bien, cuidado, error) queda también en el centro de notificaciones; lo informativo no.
    const nivel = kind === 'success' ? 'ok' : kind === 'warning' ? 'aviso' : kind === 'danger' ? 'error' : null;
    if (nivel) emitirAviso({ nivel, titulo: title, texto: body, origen: 'App' });
    // Auto-dismiss a los 5s
    setTimeout(() => {
      setItems(prev => prev.filter(t => t.id !== id));
    }, 5000);
  }, []);

  return (
    <Ctx.Provider value={{ toast }}>
      {children}
      <div className="toast-container">
        {items.map(t => (
          <div key={t.id} className={`toast ${t.kind}`}>
            <div style={{ flex: 1 }}>
              <div className="toast-title">{t.title}</div>
              {t.body && <div className="toast-body">{t.body}</div>}
            </div>
            <button className="btn btn-sm" onClick={() =>
              setItems(prev => prev.filter(x => x.id !== t.id))}>✕</button>
          </div>
        ))}
      </div>
    </Ctx.Provider>
  );
}

export function useToast() {
  return useContext(Ctx);
}
