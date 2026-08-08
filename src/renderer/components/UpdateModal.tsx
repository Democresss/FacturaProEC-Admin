import React, { useEffect, useState, useCallback } from 'react';
import { Modal } from './Modal';

/**
 * UpdateModal — Modal in-app para el auto-update.
 *
 * Escucha los eventos que el main process envía via IPC:
 *   - 'update:status'  → { state: 'available'|'downloaded'|'error'|..., version }
 *   - 'update:progress' → { percent: 0-100 }
 *
 * Se monta automáticamente cuando hay una actualización disponible,
 * SIN usar Notification del SO (eso lo pediste explícito: modal dentro del programa,
 * no notificaciones Windows cada rato).
 *
 * El modal NO se puede cerrar si está descargando (no tiene sentido). Si ya se
 * descargó, el botón "Reiniciar y actualizar" ejecuta `update:install` del preload.
 */

type UpdateState = 'idle' | 'checking' | 'available' | 'downloaded' | 'up-to-date' | 'error';

interface StatusPayload {
  state: UpdateState;
  version?: string;
  message?: string;
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

  const reset = useCallback(() => {
    setState('idle');
    setVersion(null);
    setPercent(0);
    setDismissed(false);
    setErrorMsg(null);
  }, []);

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
      if (p.state) {
        if (p.state === 'available') {
          // Nueva versión detectada → mostramos el modal, reseteamos dismiss.
          setDismissed(false);
          setState('available');
          setVersion(p.version || null);
          setPercent(0);
        } else if (p.state === 'downloaded') {
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
  const visible = open && !dismissed;
  if (!visible) return null;

  // Para 'available' el backend está descargando (autoDownload=true), mostramos progreso.
  // Para 'downloaded' ya está listo para instalar.
  // Para 'error' mostramos qué pasó y posponer.

  let title: React.ReactNode;
  if (state === 'available') title = `⬇ Actualizando a la nueva versión${version ? ' v' + version : ''}…`;
  else if (state === 'downloaded') title = `✓ Actualización lista${version ? ' v' + version : ''}`;
  else title = '⚠ Error de actualización';

  const handleInstall = useCallback(async () => {
    const ea = (window as any).electronAPI;
    try { await ea?.update?.install(); } catch { /* el main lo instala */ }
  }, []);

  const handleDismiss = useCallback(() => {
    if (state === 'available') return; // No dejar cerrar mientras descarga
    setDismissed(true);
    if (state === 'error') reset();
  }, [state, reset]);

  // El footer depende del estado.
  let footer: React.ReactNode = null;
  if (state === 'downloaded') {
    footer = (
      <>
        <button className="btn" onClick={handleDismiss}>Más tarde</button>
        <button className="btn btn-primary" onClick={handleInstall}>↻ Reiniciar y actualizar</button>
      </>
    );
  } else if (state === 'error') {
    footer = (
      <>
        <button className="btn" onClick={reset}>Cerrar</button>
      </>
    );
  }
  // En 'available' (descargando): sin footer, el botón ✕ está deshabilitado en el header.

  const downloading = state === 'available';

  return (
    <Modal
      open={true}
      title={title as string}
      onClose={downloading ? () => {} : handleDismiss}
      maxWidth={480}
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
        </div>
      )}
      {state === 'downloaded' && (
        <div className="updater-body">
          <div style={{ marginBottom: 12 }}>
            La nueva versión <strong>v{version}</strong> ya está descargada y lista para instalar.
            Al reiniciar, se aplicará automáticamente.
          </div>
          <div style={{ fontSize: 13, color: 'var(--text-muted)' }}>
            Guardá tus cambios antes de continuar.
          </div>
        </div>
      )}
      {state === 'error' && (
        <div className="updater-body">
          <div style={{ marginBottom: 8 }}>No se pudo completar la actualización:</div>
          <pre style={{ whiteSpace: 'pre-wrap', fontSize: 12, background: 'var(--bg-sunken)', padding: 8, borderRadius: 6 }}>
{errorMsg || 'Error desconocido'}
          </pre>
          <div style={{ marginTop: 12, fontSize: 12, color: 'var(--text-muted)' }}>
            Podés cerrar e intentarlo más tarde (la app revisará otra vez al reiniciar).
          </div>
        </div>
      )}
    </Modal>
  );
}
