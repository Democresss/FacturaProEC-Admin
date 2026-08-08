import React, { useState, useEffect, useCallback } from 'react';
import { Card } from '../components/Card';
import { AsyncButton } from '../components/Button';
import type { ThemeMode, EffectiveTheme } from '../hooks/useTheme';

interface ConfigViewProps {
  call: (path: string, opts?: RequestInit) => Promise<any>;
  toast: (title: string, body?: string, kind?: any) => void;
  theme: { mode: ThemeMode; effective: EffectiveTheme; change: (m: ThemeMode) => void };
}

export function ConfigView({ call, toast, theme }: ConfigViewProps) {
  const [autostart, setAutostart] = useState(true);
  const [rememberForms, setRememberForms] = useState(true);
  const [themeState, setThemeState] = useState<ThemeMode>(theme.mode);

  // Carga la config persistida
  const loadConfig = useCallback(async () => {
    const r = await call('/api/config');
    if (r.ok && r.data) {
      setAutostart(Boolean(r.data.autostart));
      setRememberForms(Boolean(r.data.remember_forms));
    }
  }, [call]);

  useEffect(() => { loadConfig(); }, []);

  // Sincroniza el tema con el hook al cambiarlo
  const setTheme = (m: ThemeMode) => {
    theme.change(m);
    setThemeState(m);
    toast('Tema', `Cambiado a ${m === 'system' ? 'Sistema' : m === 'light' ? 'Claro' : 'Oscuro'}`);
  };

  const saveAutostart = async (on: boolean) => {
    setAutostart(on);
    const r = await call('/api/autostart', { method: 'POST', body: JSON.stringify({ enable: on }) });
    await call('/api/config', { method: 'POST', body: JSON.stringify({ data: { autostart: on } }) });
    toast('Auto-arranque', r.message || (on ? 'Activado' : 'Desactivado'), r.ok ? 'success' : 'warning');
  };

  const saveRemember = async (on: boolean) => {
    setRememberForms(on);
    await call('/api/config', { method: 'POST', body: JSON.stringify({ data: { remember_forms: on } }) });
    toast('Recordar formularios', on ? 'Activado' : 'Desactivado');
  };

  return (
    <div>
      <Card title="Apariencia" sub="Tema Dark / Light / System con auto-detección del SO" icon={<span>🎨</span>}>
        <div className="row gap-16">
          <span className="form-label">Tema actual:</span>
          <div className="segmented">
            <button className={themeState === 'system' ? 'active' : ''} onClick={() => setTheme('system')}>Sistema</button>
            <button className={themeState === 'light' ? 'active' : ''} onClick={() => setTheme('light')}>☀ Claro</button>
            <button className={themeState === 'dark' ? 'active' : ''} onClick={() => setTheme('dark')}>☾ Oscuro</button>
          </div>
          <span className="muted fs-12">efectivo: <strong>{theme.effective}</strong></span>
        </div>
      </Card>

      <Card title="Arranque" sub="Inicio automático con el sistema" icon={<span>🚀</span>}>
        <div className="row between">
          <span className="fs-13">Iniciar con {navigator.platform.includes('Win') ? 'Windows' : 'el sistema'}</span>
          <div className={`switch ${autostart ? 'on' : ''}`} onClick={() => saveAutostart(!autostart)} />
        </div>
      </Card>

      <Card title="Preferencias" sub="Comportamiento de la app" icon={<span>⚙</span>}>
        <div className="row between mb-16">
          <span className="fs-13">Recordar datos de formularios (IMAP, SFTP, PG…)</span>
          <div className={`switch ${rememberForms ? 'on' : ''}`} onClick={() => saveRemember(!rememberForms)} />
        </div>
      </Card>

      <Card title="Segundo plano" sub="Minimizar a la bandeja del sistema en vez de cerrar" icon={<span> tray</span>}>
        <div className="row gap-8">
          <AsyncButton onClick={() => (window as any).electronAPI?.app.minimizeToTray()} runningText="…">📥 Minimizar a bandeja ahora</AsyncButton>
          <AsyncButton variant="danger" onClick={() => (window as any).electronAPI?.app.quit()} runningText="…">✋ Cerrar app y detener backend</AsyncButton>
        </div>
      </Card>

      <Card title="Acerca de" sub="FacturaProEC Admin v2.0.0 — Electron + Python backend" icon={<span>ℹ</span>}>
        <div className="fs-12 col gap-8">
          <div><span className="muted">Plataforma:</span> <span className="mono">{navigator.platform}</span></div>
          <div><span className="muted">User Agent:</span> <span className="mono fs-11">{navigator.userAgent.slice(0, 80)}…</span></div>
          <div><span className="muted">Backend:</span> <span className="mono">Python FastAPI en 127.0.0.1</span></div>
          <div className="muted mt-8">El backend Python reutiliza la lógica existente del StorageManager: sys_info, service_runner, SecurityGuardian, DB Viewer (SQLAlchemy async), módulo SRI (IMAP + RUC).</div>
        </div>
      </Card>
    </div>
  );
}
