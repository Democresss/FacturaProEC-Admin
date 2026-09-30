import React, { useEffect, useState, useCallback } from 'react';
import { Modal } from './Modal';

/**
 * UpdateModal — Modal in-app para el auto-update.
 *
 * Escucha los eventos que el main process envía via IPC:
 *   - 'update:status'  → { state: 'available'|'downloaded'|'error'|..., version, notas }
 *   - 'update:progress' → { percent: 0-100 }
 *
 * Se monta automáticamente cuando hay una actualización disponible,
 * SIN usar Notification del SO (eso lo pediste explícito: modal dentro del programa,
 * no notificaciones Windows cada rato). Muestra la lista de novedades de la versión nueva.
 *
 * El modal NO se puede cerrar si está descargando (no tiene sentido). Si ya se
 * descargó, el botón "Reiniciar y actualizar" ejecuta `update:install` del preload.
 *
 * Todos los hooks van ANTES de cualquier `return`: antes había useCallback después de
 * `if (!visible) return null` y React se caía (error #310) justo al llegar una actualización.
 */

type UpdateState = 'idle' | 'checking' | 'available' | 'downloaded' | 'up-to-date' | 'error';

interface StatusPayload {
  state: UpdateState;
  version?: string;
  message?: string;
  notas?: string[];
}

interface ProgressPayload {
  percent: number;
}

export function UpdateModal() {
  const [state, setState] = useState<UpdateState>('idle');
  const [version, setVersion] = useState<string | null>(null);
  const [percent, setPercent] = useState(0);
  const [dismissed, setDismissed] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [notas, setNotas] = useState<string[]>([]);
  const [instalando, setInstalando] = useState(false);
  const [pideClave, setPideClave] = useState(false);
  const [clave, setClave] = useState('');

  const reset = useCallback(() => {
    setState('idle');
    setVersion(null);
    setPercent(0);
    setDismissed(false);
    setErrorMsg(null);
  }, []);

  const handleInstall = useCallback(async () => {
    const ea = (window as any).electronAPI;
    setInstalando(true);
    let r: any = null;
    try { r = await ea?.update?.install(pideClave ? clave : undefined); } catch (e: any) { r = { ok: false, message: String(e?.message || e) }; }
    setClave('');
    // Si se instaló, la app se cierra y se vuelve a abrir sola; si no, se dice por qué (antes no pasaba nada)
    if (r && r.ok === false) {
      setInstalando(false);
      setErrorMsg(r.message || 'No se pudo instalar');
      setState('error');
    }
  }, [pideClave, clave]);

  const handleDismiss = useCallback(() => {
    if (state === 'available') return; // No dejar cerrar mientras descarga
    setDismissed(true);
    if (state === 'error') reset();
  }, [state, reset]);

  useEffect(() => {
    const ea = (window as any).electronAPI;
    if (!ea?.update?.onStatus) return;

    const off = ea.update.onStatus((payload: StatusPayload | ProgressPayload) => {
      // El preload enrolla 'update:status' y 'update:progress' en el mismo callback.
      // Distinguimos por campo: 'percent' → progreso, 'state' → cambio de estado.
      if ('percent' in payload && typeof (payload as ProgressPayload).percent === 'number') {
        setPercent((payload as ProgressPayload).percent);
        return;
      }
      const p = payload as StatusPayload;
      if (Array.isArray(p.notas) && p.notas.length) setNotas(p.notas.filter(n => typeof n === 'string').slice(0, 20));
      if (p.state) {
        if (p.state === 'available') {
          // Nueva versión detectada → mostramos el modal, reseteamos dismiss.
          setDismissed(false);
          setState('available');
          setVersion(p.version || null);
          setPercent(0);
        } else if (p.state === 'downloaded') {
          setDismissed(false);
          ea?.update?.necesitaClave?.().then((v: boolean) => setPideClave(!!v)).catch(() => {});
          setState('downloaded');
          setVersion(p.version || null);
          setPercent(100);
        } else if (p.state === 'error') {
          setState('error');
          setErrorMsg(p.message || 'Error desconocido');
        } else if (p.state === 'up-to-date') {
          // Al día: no mostramos nada, reseteamos por si quedó abierto.
          reset();
        }
      }
    });
    return () => { if (typeof off === 'function') off(); };
  }, [reset]);

  // No mostrar nada si está al día, idle o descartado mientras no haya update.
  const open = state === 'available' || state === 'downloaded' || state === 'error';
  if (!open || dismissed) return null;

  let title: string;
  if (state === 'available') title = `⬇ Actualizando a la nueva versión${version ? ' v' + version : ''}…`;
  else if (state === 'downloaded') title = `✓ Actualización lista${version ? ' v' + version : ''}`;
  else title = '⚠ Error de actualización';

  // El footer depende del estado.
  let footer: React.ReactNode = null;
  if (state === 'downloaded') {
    footer = (
      <>
        <button className="btn" onClick={handleDismiss}>Más tarde</button>
        <button className="btn btn-primary" onClick={handleInstall} disabled={instalando || (pideClave && !clave)}>
          {instalando ? 'Instalando…' : '↻ Reiniciar y actualizar'}
        </button>
      </>
    );
  } else if (state === 'error') {
    footer = <button className="btn" onClick={reset}>Cerrar</button>;
  }
  // En 'available' (descargando): sin footer, el botón ✕ está deshabilitado en el header.

  const downloading = state === 'available';
  const novedades = state !== 'error' && notas.length > 0 && (
    <div style={{ marginTop: 14 }}>
      <div className="fw-700 fs-13" style={{ marginBottom: 6 }}>Novedades</div>
      <ul style={{ margin: 0, paddingLeft: 18, maxHeight: 220, overflow: 'auto', fontSize: 13 }}>
        {notas.map((n, i) => <li key={i} style={{ marginBottom: 4 }}>{n}</li>)}
      </ul>
    </div>
  );

  return (
    <Modal
      open={true}
      title={title}
      onClose={downloading ? () => {} : handleDismiss}
      maxWidth={520}
      footer={footer}
    >
      {downloading && (
        <div className="updater-body">
          <div style={{ marginBottom: 12, color: 'var(--text-muted)', fontSize: 13 }}>
            Descargando el nuevo instalador en segundo plano. La app sigue siendo usable.
          </div>
          <div className="progress-bar">
            <div className="progress-bar-fill" style={{ width: `${percent}%` }} />
          </div>
          <div style={{ marginTop: 8, display: 'flex', justifyContent: 'space-between', fontSize: 12, color: 'var(--text-muted)' }}>
            <span>{percent}%</span>
            <span>Se instalará al reiniciar</span>
          </div>
          {novedades}
        </div>
      )}
      {state === 'downloaded' && (
        <div className="updater-body">
          <div style={{ marginBottom: 12 }}>
            La nueva versión <strong>v{version}</strong> ya está descargada y lista para instalar.
            Al reiniciar, se aplicará automáticamente.
          </div>
          <div style={{ fontSize: 13, color: 'var(--text-muted)' }}>
            {instalando
              ? 'Instalando… La app se cierra y se vuelve a abrir sola en la versión nueva.'
              : 'El túnel sigue en línea mientras tanto (corre en Docker).'}
          </div>
          {pideClave && !instalando && (
            <div style={{ marginTop: 12 }}>
              <label className="form-label">Clave de tu usuario de Linux (la de «sudo»)</label>
              <input className="input" type="password" autoFocus value={clave} onChange={e => setClave(e.target.value)}
                     onKeyDown={e => { if (e.key === 'Enter' && clave) handleInstall(); }} />
              <div className="fs-11 muted" style={{ marginTop: 4 }}>
                Solo se usa para instalar esta actualización y no se guarda. Activa el «Modo administrador» para no volver a escribirla.
              </div>
            </div>
          )}
          {novedades}
        </div>
      )}
      {state === 'error' && (
        <div className="updater-body">
          <div style={{ marginBottom: 8 }}>No se pudo completar la actualización:</div>
          <pre style={{ whiteSpace: 'pre-wrap', fontSize: 12, background: 'var(--bg-input)', padding: 8, borderRadius: 6 }}>
{errorMsg || 'Error desconocido'}
          </pre>
          <div style={{ marginTop: 12, fontSize: 12, color: 'var(--text-muted)' }}>
            Puedes cerrar e intentarlo más tarde (la app revisará otra vez al reiniciar).
          </div>
        </div>
      )}
    </Modal>
  );
}
