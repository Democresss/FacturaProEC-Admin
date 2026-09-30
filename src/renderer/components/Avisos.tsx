/**
 * Centro de notificaciones DENTRO de la app (en vez de notificaciones de Windows a cada rato).
 *
 * Junta en un solo lugar:
 *   - lo que pasa con el túnel aunque no estés mirando (lo escribe el vigilante, sea el de la app o el servicio:
 *     túnel caído y levantado de nuevo, puerto nuevo, aviso a FacturaPro…) → /api/servidor/avisos;
 *   - las actualizaciones (nueva versión descargándose, lista, instalada);
 *   - los resultados de lo que haces en la app (los mensajes verdes, amarillos y rojos).
 * Se guarda en este equipo (localStorage de la app) y la campana muestra cuántas no has leído.
 */
import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';

export type NivelAviso = 'ok' | 'info' | 'aviso' | 'error';

export interface Aviso {
  id: string;
  t: number;          // milisegundos
  nivel: NivelAviso;
  titulo: string;
  texto?: string;
  origen: string;
  leido: boolean;
}

type Nuevo = { nivel: NivelAviso; titulo: string; texto?: string; origen: string; t?: number };

interface AvisosCtx {
  avisos: Aviso[];
  agregar: (a: Nuevo) => void;
  marcarLeidos: () => void;
  borrarTodo: () => void;
}

const CLAVE = 'facpro-avisos';
const MAXIMO = 150;
const Ctx = createContext<AvisosCtx>({ avisos: [], agregar: () => {}, marcarLeidos: () => {}, borrarTodo: () => {} });

function leerGuardados(): Aviso[] {
  try {
    const v = JSON.parse(localStorage.getItem(CLAVE) || '[]');
    return Array.isArray(v) ? v.filter(a => a && typeof a.titulo === 'string').slice(0, MAXIMO) : [];
  } catch {
    return [];
  }
}

function guardar(clave: string, valor: string) {
  try { localStorage.setItem(clave, valor); } catch { /* sin almacenamiento: sigue en memoria */ }
}

/** Desde cualquier parte (sin contexto): window.dispatchEvent(new CustomEvent('facpro-aviso', { detail })) */
export function emitirAviso(a: Nuevo) {
  window.dispatchEvent(new CustomEvent('facpro-aviso', { detail: a }));
}

export function AvisosProvider({ children }: { children: React.ReactNode }) {
  const [avisos, setAvisos] = useState<Aviso[]>(leerGuardados);

  useEffect(() => { guardar(CLAVE, JSON.stringify(avisos.slice(0, MAXIMO))); }, [avisos]);

  const agregar = useCallback((a: Nuevo) => {
    const t = a.t || Date.now();
    setAvisos(prev => {
      // El mismo aviso repetido en menos de un minuto no se duplica
      if (prev.some(x => x.titulo === a.titulo && x.texto === a.texto && Math.abs(x.t - t) < 60000)) return prev;
      const nuevo: Aviso = { id: `${t}-${Math.random().toString(36).slice(2, 8)}`, t, nivel: a.nivel, titulo: a.titulo,
                             texto: a.texto, origen: a.origen, leido: false };
      return [nuevo, ...prev].sort((x, y) => y.t - x.t).slice(0, MAXIMO);
    });
  }, []);

  const marcarLeidos = useCallback(() => setAvisos(prev => prev.some(a => !a.leido) ? prev.map(a => ({ ...a, leido: true })) : prev), []);
  const borrarTodo = useCallback(() => setAvisos([]), []);

  // Avisos emitidos desde cualquier componente (por ejemplo los mensajes de la app)
  useEffect(() => {
    const h = (e: Event) => {
      const d = (e as CustomEvent).detail;
      if (d && typeof d.titulo === 'string') agregar(d);
    };
    window.addEventListener('facpro-aviso', h);
    return () => window.removeEventListener('facpro-aviso', h);
  }, [agregar]);

  // Actualizaciones de la app
  useEffect(() => {
    const ea = (window as any).electronAPI;
    // ¿Se acaba de actualizar?
    ea?.app?.version?.().then((v: string) => {
      let antes: string | null = null;
      try { antes = localStorage.getItem('facpro-version'); } catch { /* noop */ }
      if (antes && v && antes !== v) {
        agregar({ nivel: 'ok', titulo: `Actualizada a la versión ${v}`, texto: `Antes tenías la ${antes}.`, origen: 'Actualización' });
      }
      if (v) guardar('facpro-version', v);
    }).catch(() => {});
    if (!ea?.update?.onStatus) return;
    const off = ea.update.onStatus((p: any) => {
      if (!p || typeof p.state !== 'string') return;
      if (p.state === 'available') {
        agregar({ nivel: 'info', titulo: `Nueva versión ${p.version || ''}: descargando`, origen: 'Actualización',
                  texto: Array.isArray(p.notas) && p.notas.length ? p.notas.slice(0, 6).join(' · ') : undefined });
      } else if (p.state === 'downloaded') {
        agregar({ nivel: 'ok', titulo: `Versión ${p.version || ''} lista`, origen: 'Actualización',
                  texto: 'Se instala sola cuando la app quede en la bandeja (o con «Reiniciar y actualizar»).' });
      } else if (p.state === 'error') {
        agregar({ nivel: 'error', titulo: 'No se pudo descargar la actualización', texto: p.message, origen: 'Actualización' });
      }
    });
    return () => { if (typeof off === 'function') off(); };
  }, [agregar]);

  return <Ctx.Provider value={{ avisos, agregar, marcarLeidos, borrarTodo }}>{children}</Ctx.Provider>;
}

export function useAvisos() {
  return useContext(Ctx);
}

/** Trae los eventos del vigilante (túnel) cada 30 s. `call` es el cliente del backend. */
export function useAvisosDelServidor(call: (path: string, opts?: RequestInit) => Promise<any>, activo: boolean) {
  const { agregar } = useAvisos();
  useEffect(() => {
    if (!activo) return;
    let vivo = true;
    const traer = async () => {
      let desde = 0;
      try { desde = parseFloat(localStorage.getItem('facpro-avisos-desde') || '0') || 0; } catch { /* noop */ }
      // Primera vez: solo lo de las últimas 24 horas (no inundar con historia vieja)
      if (!desde) desde = Date.now() / 1000 - 24 * 3600;
      const r = await call('/api/servidor/avisos?desde=' + desde);
      if (!vivo || !r?.ok || !Array.isArray(r.data)) return;
      let maximo = desde;
      for (const e of r.data) {
        const t = Number(e.t) || 0;
        maximo = Math.max(maximo, t);
        const nivel: NivelAviso = ['ok', 'aviso', 'error'].includes(e.nivel) ? e.nivel : 'info';
        agregar({ nivel, titulo: String(e.texto || ''), origen: 'Túnel', t: Math.round(t * 1000) });
      }
      guardar('facpro-avisos-desde', String(maximo));
    };
    traer();
    const id = setInterval(traer, 30000);
    return () => { vivo = false; clearInterval(id); };
  }, [call, activo, agregar]);
}

const COLOR: Record<NivelAviso, string> = { ok: 'var(--success)', info: 'var(--primary)', aviso: 'var(--warning)', error: 'var(--danger)' };

function cuando(t: number) {
  const s = Math.max(0, Math.round((Date.now() - t) / 1000));
  if (s < 60) return 'ahora';
  if (s < 3600) return `hace ${Math.floor(s / 60)} min`;
  if (s < 86400) return `hace ${Math.floor(s / 3600)} h`;
  try {
    return new Date(t).toLocaleString('es-EC', { dateStyle: 'short', timeStyle: 'short' });
  } catch {
    return new Date(t).toLocaleString();
  }
}

/** La campana de la barra superior y su panel. */
export function CentroAvisos() {
  const { avisos, marcarLeidos, borrarTodo } = useAvisos();
  const [abierto, setAbierto] = useState(false);
  const [filtro, setFiltro] = useState<'todos' | 'problemas'>('todos');
  const caja = useRef<HTMLDivElement>(null);
  const sinLeer = avisos.filter(a => !a.leido).length;
  const conProblema = avisos.filter(a => !a.leido && (a.nivel === 'error' || a.nivel === 'aviso')).length;

  // Cerrar al hacer clic fuera; al cerrar, lo visto queda leído
  useEffect(() => {
    if (!abierto) return;
    const h = (e: MouseEvent) => {
      if (caja.current && !caja.current.contains(e.target as Node)) { setAbierto(false); marcarLeidos(); }
    };
    const k = (e: KeyboardEvent) => { if (e.key === 'Escape') { setAbierto(false); marcarLeidos(); } };
    document.addEventListener('mousedown', h);
    document.addEventListener('keydown', k);
    return () => { document.removeEventListener('mousedown', h); document.removeEventListener('keydown', k); };
  }, [abierto, marcarLeidos]);

  const lista = filtro === 'problemas' ? avisos.filter(a => a.nivel === 'error' || a.nivel === 'aviso') : avisos;

  return (
    <div ref={caja} style={{ position: 'relative' }}>
      <button className="btn btn-sm" title="Notificaciones" aria-label={`Notificaciones: ${sinLeer} sin leer`}
              onClick={() => { if (abierto) marcarLeidos(); setAbierto(!abierto); }} style={{ position: 'relative' }}>
        🔔
        {sinLeer > 0 && (
          <span style={{ position: 'absolute', top: -6, right: -6, minWidth: 18, height: 18, padding: '0 5px', borderRadius: 9,
                         background: conProblema ? 'var(--danger)' : 'var(--primary)', color: '#fff', fontSize: 11,
                         fontWeight: 700, lineHeight: '18px', textAlign: 'center' }}>
            {sinLeer > 99 ? '99+' : sinLeer}
          </span>
        )}
      </button>
      {abierto && (
        <div role="dialog" aria-label="Notificaciones"
             style={{ position: 'absolute', right: 0, top: 'calc(100% + 8px)', width: 'min(400px, calc(100vw - 32px))', zIndex: 60,
                      background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 'var(--radius)',
                      boxShadow: 'var(--shadow-lg)', overflow: 'hidden' }}>
          <div className="row between items-center" style={{ padding: '10px 12px', borderBottom: '1px solid var(--border)' }}>
            <span className="fw-700 fs-13">Notificaciones</span>
            <div className="segmented">
              <button className={filtro === 'todos' ? 'active' : ''} onClick={() => setFiltro('todos')}>Todas</button>
              <button className={filtro === 'problemas' ? 'active' : ''} onClick={() => setFiltro('problemas')}>Problemas</button>
            </div>
          </div>
          <div style={{ maxHeight: '60vh', overflow: 'auto' }}>
            {lista.length === 0 && (
              <div className="muted fs-12" style={{ padding: 20, textAlign: 'center' }}>
                {filtro === 'problemas' ? 'Sin problemas registrados.' : 'Aquí aparece lo que pasa con tu túnel, las actualizaciones y lo que hagas en la app.'}
              </div>
            )}
            {lista.map(a => (
              <div key={a.id} style={{ display: 'flex', gap: 10, padding: '10px 12px', borderBottom: '1px solid var(--border)',
                                       background: a.leido ? 'transparent' : 'var(--primary-faint)' }}>
                <span style={{ color: COLOR[a.nivel], fontSize: 12, marginTop: 2 }}>●</span>
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div className="fs-13" style={{ fontWeight: a.leido ? 500 : 700, wordBreak: 'break-word' }}>{a.titulo}</div>
                  {a.texto && <div className="fs-12 muted" style={{ wordBreak: 'break-word' }}>{a.texto}</div>}
                  <div className="fs-11 muted" style={{ marginTop: 2 }}>{a.origen} · {cuando(a.t)}</div>
                </div>
              </div>
            ))}
          </div>
          {avisos.length > 0 && (
            <div className="row between" style={{ padding: '8px 12px' }}>
              <button className="btn btn-sm" onClick={marcarLeidos} disabled={!sinLeer}>Marcar leídas</button>
              <button className="btn btn-sm" onClick={() => { if (window.confirm('¿Borrar todas las notificaciones?')) borrarTodo(); }}>Borrar todo</button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
