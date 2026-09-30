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
  const { state, error, call } = useBridge();
  const { mode, effective, change } = useTheme();
  const { toast } = useToast();
  const [activeTab, setActiveTab] = useState<TabId>('servidor');
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
        <div>Conectando con el backend Python…</div>
        <div className="muted fs-12 mt-8">Si tarda más de 30s, revisa que Python esté en el PATH.</div>
      </div>
    );
  }

  if (state === 'error') {
    return (
      <div className="empty" style={{ height: '100vh' }}>
        <div className="empty-icon">⚠</div>
        <div>Error de conexión con el backend</div>
        <div className="muted fs-12 mt-8">{error}</div>
        <button className="btn btn-primary mt-16" onClick={() => location.reload()}>Reintentar</button>
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
          <ErrorBoundary key={activeTab} nombre={activeDef.label}>
          {activeTab === 'dashboard' && <DashboardView call={call} goto={goto} />}
          {activeTab === 'security' && <SecurityView call={call} toast={toast} />}
          {activeTab === 'storage' && <StorageView call={call} toast={toast} />}
          {activeTab === 'servidor' && <ServidorView call={call} toast={toast} />}
          {activeTab === 'config' && <ConfigView call={call} toast={toast} theme={{ mode, effective, change }} />}
          </ErrorBoundary>
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
