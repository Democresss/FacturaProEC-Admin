import React, { useState, useEffect, useCallback } from 'react';
import { Card } from '../components/Card';
import { AsyncButton } from '../components/Button';

export function SecurityView({ call, toast }: {
  call: (path: string, opts?: RequestInit) => Promise<any>;
  toast: (title: string, body?: string, kind?: any) => void;
}) {
  const [shieldActive, setShieldActive] = useState(true);
  const [autoBlock, setAutoBlock] = useState(true);
  const [ports, setPorts] = useState('21,22,2022,5432');
  const [whitelist, setWhitelist] = useState<string[]>([]);
  const [newIp, setNewIp] = useState('');
  const [events, setEvents] = useState<any[]>([]);
  const [suspicious, setSuspicious] = useState<any[]>([]);

  const refresh = useCallback(async () => {
    const r = await call('/api/security/status');
    if (r.ok) {
      setShieldActive(Boolean(r.shield_active));
      setAutoBlock(Boolean(r.auto_block));
      setPorts((r.ports || []).join(','));
      setWhitelist(r.whitelist || []);
      setEvents(r.events || []);
    }
    const s = await call('/api/security/check-connections');
    if (s.ok) setSuspicious(s.suspicious || []);
  }, [call]);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 5000);
    return () => clearInterval(id);
  }, [refresh]);

  const setShield = async (on: boolean) => {
    setShieldActive(on);
    await call('/api/security/config', { method: 'POST', body: JSON.stringify({ shield_active: on }) });
    toast('Escudo', on ? 'Activado' : 'Desactivado', on ? 'success' : 'warning');
  };

  const setBlock = async (on: boolean) => {
    setAutoBlock(on);
    await call('/api/security/config', { method: 'POST', body: JSON.stringify({ auto_block: on }) });
    toast('Auto-block', on ? 'Activado' : 'Desactivado');
  };

  const savePorts = async () => {
    const list = ports.split(',').map(p => parseInt(p.trim())).filter(p => p > 0);
    await call('/api/security/config', { method: 'POST', body: JSON.stringify({ ports: list }) });
    toast('Puertos', `Vigilando: ${list.join(', ')}`, 'success');
  };

  const addIp = async () => {
    if (!newIp.trim()) return;
    const r = await call('/api/security/whitelist/add', { method: 'POST', body: JSON.stringify({ ip: newIp.trim() }) });
    if (r.ok) {
      setWhitelist(r.whitelist || []);
      setNewIp('');
      toast('Whitelist', `${newIp} añadida`, 'success');
    }
  };

  const removeIp = async (ip: string) => {
    const r = await call('/api/security/whitelist/remove', { method: 'POST', body: JSON.stringify({ ip }) });
    if (r.ok) {
      setWhitelist(r.whitelist || []);
      toast('Whitelist', `${ip} eliminada`, 'warning');
    }
  };

  const lockdown = async () => {
    if (!window.confirm('¿Activar cerrojo de emergencia? Se cerrarán todas las reglas de firewall y puertos.')) return;
    const r = await call('/api/firewall/lockdown', { method: 'POST', body: JSON.stringify({}) });
    toast('Cerrojo', r.message, r.ok ? 'danger' : 'warning');
    refresh();
  };

  return (
    <div>
      <div className="grid-2" style={{ marginBottom: 16 }}>
        <Card title="Estado del escudo" icon={<span>🛡</span>}>
          <div className="row between mb-16">
            <span>Escudo activo</span>
            <div className={`switch ${shieldActive ? 'on' : ''}`} onClick={() => setShield(!shieldActive)} />
          </div>
          <div className="row between mb-16">
            <span>Auto-block al detectar</span>
            <div className={`switch ${autoBlock ? 'on' : ''}`} onClick={() => setBlock(!autoBlock)} />
          </div>
          <div className="row gap-8">
            <span className="form-label">Puertos vigilados</span>
            <input className="input flex-1" value={ports} onChange={e => setPorts(e.target.value)} />
            <button className="btn btn-primary btn-sm" onClick={savePorts}>Guardar</button>
          </div>
        </Card>

        <Card title="Whitelist IPs" sub={`${whitelist.length} IP(s) aprobadas`} icon={<span>✅</span>}>
          <div className="row gap-8 mb-16">
            <input className="input flex-1" value={newIp} onChange={e => setNewIp(e.target.value)} placeholder="192.168.1.50" />
            <button className="btn btn-success btn-sm" onClick={addIp}>+ Añadir</button>
          </div>
          <div className="col gap-8">
            {whitelist.length === 0 ? (
              <div className="muted fs-12">Sin IPs aprobadas.</div>
            ) : whitelist.map((ip, i) => (
              <div key={i} className="row between">
                <span className="mono fs-12">{ip}</span>
                <button className="btn btn-sm" onClick={() => removeIp(ip)}>✕</button>
              </div>
            ))}
          </div>
        </Card>
      </div>

      <Card title="Conexiones activas sospechosas" sub="Vigilancia de netstat/ss en tiempo real (cada 5s)" icon={<span>📡</span>}
        right={<AsyncButton size="sm" onClick={refresh} runningText="…">🔄</AsyncButton>}>
        {suspicious.length === 0 ? (
          <div className="badge ok"><span className="dot" /> Sin conexiones sospechosas</div>
        ) : (
          <div className="table-wrap">
            <table className="table mono">
              <thead><tr><th>Puerto</th><th>IP remota</th><th>Dirección completa</th></tr></thead>
              <tbody>
                {suspicious.map((s, i) => (
                  <tr key={i}><td>{s.port}</td><td className="danger">{s.remote_ip}</td><td>{s.full_addr}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card title="Historial de eventos" sub={`${events.length} eventos (últimos 100)`} icon={<span>📜</span>}>
        <div className="table-wrap">
          {events.length === 0 ? (
            <div className="empty"><div className="empty-icon">📭</div>Sin eventos registrados.</div>
          ) : (
            <table className="table">
              <thead><tr><th>Fecha</th><th>IP</th><th>Puerto</th><th>Tipo</th><th>Detalle</th></tr></thead>
              <tbody>
                {events.map((e, i) => (
                  <tr key={i}>
                    <td className="fs-11">{e.timestamp}</td>
                    <td className="mono">{e.ip || '—'}</td>
                    <td>{e.port || '—'}</td>
                    <td><span className={`badge ${e.kind === 'bruteforce' ? 'danger' : 'warn'}`}>{e.kind}</span></td>
                    <td title={e.detail}>{(e.detail || '').slice(0, 80)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </Card>

      <Card title="Cercojo de emergencia" sub="Cierra todas las reglas de firewall y bloquea puertos" icon={<span>🚨</span>}>
        <AsyncButton variant="danger" onClick={lockdown} runningText="Activando…" confirmText="Se cerrarán todas las reglas de firewall">🔒 Activar cerrojo de emergencia</AsyncButton>
      </Card>
    </div>
  );
}
