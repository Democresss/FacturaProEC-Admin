import React, { useState, useCallback } from 'react';
import { Card } from '../components/Card';
import { AsyncButton } from '../components/Button';

export function VpnView({ call, toast }: {
  call: (path: string, opts?: RequestInit) => Promise<any>;
  toast: (title: string, body?: string, kind?: any) => void;
}) {
  const [host, setHost] = useState('');
  const [port, setPort] = useState('22');
  const [user, setUser] = useState('');
  const [pass, setPass] = useState('');
  const [folder, setFolder] = useState('/');
  const [testMsg, setTestMsg] = useState('');

  // PG remoto (VPN)
  const [pgRHost, setPgRHost] = useState('');
  const [pgRPort, setPgRPort] = useState('5432');
  const [pgRDb, setPgRDb] = useState('facturapro_db');
  const [pgRUser, setPgRUser] = useState('');
  const [pgRPass, setPgRPass] = useState('');

  const testSftp = useCallback(async () => {
    const r = await call('/api/sftp/test-full', {
      method: 'POST', body: JSON.stringify({
        host, port: parseInt(port) || 22, user, password: pass, folder,
      }),
    });
    setTestMsg(r.message);
    toast('Test SFTP', r.message, r.ok ? 'success' : 'danger');
  }, [call, host, port, user, pass, folder, toast]);

  const savePgRemote = useCallback(async () => {
    const r = await call('/api/config', {
      method: 'POST', body: JSON.stringify({
        data: {
          pg_remote_host: pgRHost, pg_remote_port: parseInt(pgRPort) || 5432,
          pg_remote_db: pgRDb, pg_remote_user: pgRUser, pg_remote_pass: pgRPass,
        },
      }),
    });
    toast('PG remoto guardado', 'Se usará en el DB Viewer', r.ok ? 'success' : 'danger');
  }, [call, pgRHost, pgRPort, pgRDb, pgRUser, pgRPass, toast]);

  return (
    <div>
      <Card title="Test de servidor remoto (SFTP/SSH)" sub="Ping + TCP + diagnóstico del puerto" icon={<span>📡</span>}>
        <div className="grid-2 gap-8">
          <div className="form-row"><span className="form-label">Host / IP</span><input className="input mono" value={host} onChange={e => setHost(e.target.value)} /></div>
          <div className="form-row"><span className="form-label">Puerto</span><input className="input" value={port} onChange={e => setPort(e.target.value)} /></div>
          <div className="form-row"><span className="form-label">Usuario</span><input className="input" value={user} onChange={e => setUser(e.target.value)} /></div>
          <div className="form-row"><span className="form-label">Contraseña</span><input type="password" className="input" value={pass} onChange={e => setPass(e.target.value)} /></div>
          <div className="form-row"><span className="form-label">Carpeta</span><input className="input" value={folder} onChange={e => setFolder(e.target.value)} /></div>
        </div>
        <div className="btn-row">
          <AsyncButton variant="primary" onClick={testSftp} runningText="Probando SFTP…">🧪 Probar SFTP</AsyncButton>
        </div>
        {testMsg && (
          <div className={`card ${testMsg.startsWith('✅') ? 'ok' : ''}`} style={{ padding: 12, borderColor: 'var(--border)', background: 'var(--bg-hover)' }}>
            <pre className="mono fs-12">{testMsg}</pre>
          </div>
        )}
      </Card>

      <Card title="PostgreSQL remoto via VPN" sub="Configuración que el DB Viewer prioriza sobre la conexión local" icon={<span>🗄</span>}>
        <div className="grid-2 gap-8">
          <div className="form-row"><span className="form-label">Host remoto</span><input className="input mono" value={pgRHost} onChange={e => setPgRHost(e.target.value)} placeholder="10.x.x.x" /></div>
          <div className="form-row"><span className="form-label">Puerto</span><input className="input" value={pgRPort} onChange={e => setPgRPort(e.target.value)} /></div>
          <div className="form-row"><span className="form-label">Base datos</span><input className="input" value={pgRDb} onChange={e => setPgRDb(e.target.value)} /></div>
          <div className="form-row"><span className="form-label">Usuario</span><input className="input" value={pgRUser} onChange={e => setPgRUser(e.target.value)} /></div>
          <div className="form-row"><span className="form-label">Contraseña</span><input type="password" className="input" value={pgRPass} onChange={e => setPgRPass(e.target.value)} /></div>
        </div>
        <div className="btn-row">
          <AsyncButton variant="success" onClick={savePgRemote} runningText="Guardando…">💾 Guardar PG remoto</AsyncButton>
        </div>
      </Card>

      <Card title="Túneles VPN" sub="Enlaces de ayuda para configurar WireGuard/Tailscale/Cloudflare" icon={<span>🔒</span>}>
        <div className="grid-2 gap-8">
          <button className="btn" onClick={() => (window as any).electronAPI?.openExternal('https://www.wireguard.com/install/')}>🛡 WireGuard (web oficial)</button>
          <button className="btn" onClick={() => (window as any).electronAPI?.openExternal('https://tailscale.com/download')}>🦖 Tailscale (descargar)</button>
          <button className="btn" onClick={() => (window as any).electronAPI?.openExternal('https://developers.cloudflare.com/cloudflare-one/connections/connect-devices/warp/')}>☁ Cloudflare WARP</button>
          <button className="btn" onClick={() => (window as any).electronAPI?.openExternal('https://openvpn.net/community-downloads/')}>🌐 OpenVPN</button>
        </div>
      </Card>
    </div>
  );
}
