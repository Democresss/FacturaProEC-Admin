import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { useBridge } from './hooks/useBridge';
import { useTheme } from './hooks/useTheme';
import { ToastProvider, useToast } from './components/Toast';
import { CommandPalette, CommandItem } from './components/CommandPalette';
import { DashboardView } from './views/Dashboard';
import { DbViewerView } from './views/DbViewer';
import { SriView } from './views/Sri';
import { SecurityView } from './views/Security';
import { StorageView } from './views/Storage';
import { VpnView } from './views/Vpn';
import { ConfigView } from './views/Config';

type TabId = 'dashboard' | 'db' | 'sri' | 'security' | 'storage' | 'vpn' | 'config';

interface TabDef {
  id: TabId;
  label: string;
  icon: string;
  desc: string;
}

const TABS: TabDef[] = [
  { id: 'dashboard', label: 'Dashboard',    icon: '⌂', desc: 'Resumen del sistema' },
  { id: 'db',        label: 'Base de Datos', icon: '🗄', desc: 'Viewer PostgreSQL' },
  { id: 'sri',       label: 'SRI / Recepción', icon: '🧾', desc: 'IMAP + RUC' },
  { id: 'security',  label: 'Seguridad',    icon: '🛡', desc: 'Guardian anti-intrusión' },
  { id: 'storage',   label: 'Almacenamiento', icon: '💾', desc: 'SFTP / FTP / Docker' },
  { id: 'vpn',       label: 'VPN',          icon: '🔒', desc: 'PG remoto + túneles' },
  { id: 'config',    label: 'Configuración', icon: '⚙', desc: 'Tema, autostart, etc.' },
];

function AppInner() {
  const { state, error, call } = useBridge();
  const { mode, effective, change } = useTheme();
  const { toast } = useToast();
  const [activeTab, setActiveTab] = useState<TabId>('dashboard');
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
        <div className="sidebar-logo" title="FacturaProEC Admin" onClick={() => goto('dashboard')}>F</div>
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
          {activeTab === 'dashboard' && <DashboardView call={call} goto={goto} />}
          {activeTab === 'db' && <DbViewerView call={call} toast={toast} />}
          {activeTab === 'sri' && <SriView call={call} toast={toast} />}
          {activeTab === 'security' && <SecurityView call={call} toast={toast} />}
          {activeTab === 'storage' && <StorageView call={call} toast={toast} />}
          {activeTab === 'vpn' && <VpnView call={call} toast={toast} />}
          {activeTab === 'config' && <ConfigView call={call} toast={toast} theme={{ mode, effective, change }} />}
        </main>
      </div>

      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} items={commands} />
    </div>
  );
}

export function App() {
  return (
    <ToastProvider>
      <AppInner />
    </ToastProvider>
  );
}

// Tipos exportados para las vistas
export type ApiCall = ReturnType<typeof useBridge>['call'];
export type GoTo = (id: TabId) => void;
