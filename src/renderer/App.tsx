import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { useBridge } from './hooks/useBridge';
import { useTheme } from './hooks/useTheme';
import { ToastProvider, useToast } from './components/Toast';
import { CommandPalette, CommandItem } from './components/CommandPalette';
import { UpdateModal } from './components/UpdateModal';
import { ErrorBoundary } from './components/ErrorBoundary';
import { AvisosProvider, CentroAvisos, useAvisosDelServidor } from './components/Avisos';
import { DashboardView } from './views/Dashboard';
import { SecurityView } from './views/Security';
import { StorageView } from './views/Storage';
import { ConfigView } from './views/Config';
import { ServidorView } from './views/Servidor';
import logo from '../assets/logo-corto.png';

// Base de Datos, SRI y VPN salieron del menú (confundían); sus archivos quedan en views/ por si se retoman.
type TabId = 'servidor' | 'dashboard' | 'storage' | 'security' | 'config';

interface TabDef {
  id: TabId;
  label: string;
  icon: string;
  desc: string;
}

const TABS: TabDef[] = [
  { id: 'servidor',  label: 'Servidor y túnel', icon: '🛰', desc: 'Tu base lista para FacturaPro por internet (bore)' },
  { id: 'dashboard', label: 'Dashboard',    icon: '⌂', desc: 'Resumen del equipo' },
  { id: 'storage',   label: 'Almacenamiento', icon: '💾', desc: 'SFTP / FTP / Docker' },
  { id: 'security',  label: 'Seguridad',    icon: '🛡', desc: 'Cifrado, SSL y guardián anti-intrusión' },
  { id: 'config',    label: 'Configuración', icon: '⚙', desc: 'Tema, arranque automático' },
];

function AppInner() {
  const { state, error, detalle, call } = useBridge();
  const { mode, effective, change } = useTheme();
  const { toast } = useToast();
  const [activeTab, setActiveTab] = useState<TabId>('servidor');
  // Pestañas ya abiertas: se quedan montadas (antes, al cambiar de pestaña, se volvía a consultar todo desde cero)
  const [abiertas, setAbiertas] = useState<TabId[]>(['servidor']);
  useEffect(() => {
    setAbiertas(prev => prev.includes(activeTab) ? prev : [...prev, activeTab]);
  }, [activeTab]);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [sidebarExpanded, setSidebarExpanded] = useState(false);

  // Ctrl+K para abrir command palette
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setPaletteOpen(prev => !prev);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

  const goto = useCallback((id: TabId) => setActiveTab(id), []);

  const commands: CommandItem[] = useMemo(() => TABS.map(t => ({
    id: t.id, label: t.label, desc: t.desc, icon: t.icon, run: () => goto(t.id),
  })), [goto]);

  // Eventos del túnel para el centro de notificaciones (también con la ventana escondida en la bandeja)
  useAvisosDelServidor(call, state !== 'connecting' && state !== 'error');

  if (state === 'connecting') {
    return (
      <div className="empty" style={{ height: '100vh' }}>
        <div className="empty-icon">⏳</div>
        <div>Arrancando el servidor interno de la app…</div>
        <div className="muted fs-12 mt-8">Suele tardar unos segundos (la primera vez, el antivirus puede revisarlo).</div>
      </div>
    );
  }

  if (state === 'error') {
    return (
      <div className="empty" style={{ height: '100vh' }}>
        <div className="empty-icon">⚠</div>
        <div>No arrancó el servidor interno de la app</div>
        <div className="muted fs-12 mt-8">{error}</div>
        {detalle?.lineas?.length ? (
          <pre className="fs-12 mt-8" style={{ maxWidth: 760, maxHeight: 220, overflow: 'auto', textAlign: 'left',
            whiteSpace: 'pre-wrap', opacity: 0.85 }}>{detalle.lineas.join('\n')}</pre>
        ) : null}
        {detalle?.archivo ? <div className="muted fs-12 mt-8">Registro completo: {detalle.archivo}</div> : null}
        <button className="btn btn-primary mt-16" onClick={async () => {
          await (window as any).electronAPI?.bridge?.restart?.();
          location.reload();
        }}>Reintentar</button>
      </div>
    );
  }

  const activeDef = TABS.find(t => t.id === activeTab)!;

  return (
    <div className="app-shell" style={sidebarExpanded ? { gridTemplateColumns: '220px 1fr' } : undefined}>
      {/* Sidebar */}
      <nav className={`sidebar ${sidebarExpanded ? 'expanded' : ''}`}>
        <div className="sidebar-logo" title="FacPro Server Manager" onClick={() => goto('servidor')}
             style={{ background: 'transparent', padding: 2 }}>
          <img src={logo} alt="FacPro" style={{ width: '100%', height: '100%', objectFit: 'contain' }} />
        </div>
        {TABS.map(t => (
          <button
            key={t.id}
            className={`nav-item ${activeTab === t.id ? 'active' : ''}`}
            onClick={() => goto(t.id)}
          >
            <span style={{ fontSize: 18 }}>{t.icon}</span>
            <span className="nav-tooltip">{t.label}</span>
            {sidebarExpanded && (
              <span style={{ marginLeft: 10, fontSize: 13, fontWeight: 600 }}>{t.label}</span>
            )}
          </button>
        ))}
        <button className="sidebar-expander" onClick={() => setSidebarExpanded(!sidebarExpanded)} title="Expandir sidebar">
          {sidebarExpanded ? '‹' : '›'}
        </button>
      </nav>

      {/* Main */}
      <div className="main-area">
        <header className="topbar">
          <div className="topbar-title">{activeDef.icon} {activeDef.label}</div>
          <div className="topbar-spacer" />
          <CentroAvisos />
          {/* Theme toggle */}
          <div className="segmented">
            <button className={mode === 'system' ? 'active' : ''} onClick={() => change('system')} title="Tema del sistema">Auto</button>
            <button className={mode === 'light' ? 'active' : ''} onClick={() => change('light')} title="Tema claro">☀</button>
            <button className={mode === 'dark' ? 'active' : ''} onClick={() => change('dark')} title="Tema oscuro">☾</button>
          </div>
          <button className="btn btn-sm" onClick={() => setPaletteOpen(true)} title="Ctrl+K">
            ⌘K
          </button>
        </header>

        <main className="content">
          {abiertas.map(id => (
            <div key={id} style={{ display: id === activeTab ? undefined : 'none' }}>
              <ErrorBoundary nombre={TABS.find(t => t.id === id)?.label || id}>
                {id === 'dashboard' && <DashboardView call={call} goto={goto} activo={activeTab === 'dashboard'} />}
                {id === 'security' && <SecurityView call={call} toast={toast} activo={activeTab === 'security'} />}
                {id === 'storage' && <StorageView call={call} toast={toast} />}
                {id === 'servidor' && <ServidorView call={call} toast={toast} />}
                {id === 'config' && <ConfigView call={call} toast={toast} theme={{ mode, effective, change }} />}
              </ErrorBoundary>
            </div>
          ))}
        </main>
      </div>

      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} items={commands} />
    </div>
  );
}

export function App() {
  return (
    <AvisosProvider>
    <ToastProvider>
      <ErrorBoundary nombre="app">
        <AppInner />
      </ErrorBoundary>
      <ErrorBoundary silencioso>
        <UpdateModal />
      </ErrorBoundary>
    </ToastProvider>
    </AvisosProvider>
  );
}

// Tipos exportados para las vistas
export type ApiCall = ReturnType<typeof useBridge>['call'];
export type GoTo = (id: TabId) => void;
