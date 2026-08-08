import React, { useState, useEffect, useCallback } from 'react';
import { Card } from '../components/Card';
import { AsyncButton } from '../components/Button';

interface DbConfigDto {
  pg_host: string; pg_port: number; pg_db: string; pg_user: string; pg_pass: string;
  pg_remote_host?: string; pg_remote_port?: number; pg_remote_db?: string;
  pg_remote_user?: string; pg_remote_pass?: string;
}

export function DbViewerView({ call, toast }: {
  call: (path: string, opts?: RequestInit) => Promise<any>;
  toast: (title: string, body?: string, kind?: any) => void;
}) {
  // Form PG local
  const [host, setHost] = useState('127.0.0.1');
  const [port, setPort] = useState('5432');
  const [db, setDb] = useState('facturapro_db');
  const [user, setUser] = useState('postgres_user');
  const [pass, setPass] = useState('ClaveSegura123!');

  // Form PG remoto VPN
  const [useVpn, setUseVpn] = useState(false);
  const [rHost, setRHost] = useState('');
  const [rPort, setRPort] = useState('5432');
  const [rDb, setRDb] = useState('facturapro_db');
  const [rUser, setRUser] = useState('');
  const [rPass, setRPass] = useState('');

  // State del viewer
  const [tables, setTables] = useState<string[]>([]);
  const [selected, setSelected] = useState('');
  const [connected, setConnected] = useState(false);
  const [offset, setOffset] = useState(0);
  const limit = 100;
  const [columns, setColumns] = useState<string[]>([]);
  const [rows, setRows] = useState<any[][]>([]);
  const [totalApprox, setTotalApprox] = useState(0);
  const [sql, setSql] = useState('SELECT * FROM users LIMIT 50');
  const [activeConnections, setActiveConnections] = useState<any[]>([]);

  const cfg: DbConfigDto = useVpn ? {
    pg_host: host, pg_port: parseInt(port) || 5432, pg_db: db, pg_user: user, pg_pass: pass,
    pg_remote_host: rHost, pg_remote_port: parseInt(rPort) || 5432,
    pg_remote_db: rDb, pg_remote_user: rUser, pg_remote_pass: rPass,
  } : {
    pg_host: host, pg_port: parseInt(port) || 5432, pg_db: db, pg_user: user, pg_pass: pass,
  };

  const connect = useCallback(async () => {
    setConnected(false);
    setTables([]);
    setSelected('');
    const r = await call('/api/db/connect', { method: 'POST', body: JSON.stringify(cfg) });
    if (r.ok) {
      setConnected(true);
      setTables(r.tables || []);
      setSelected(r.tables?.[0] || '');
      toast('Conexión OK', r.message, 'success');
    } else {
      toast('Fallo de conexión', r.message, 'danger');
    }
  }, [call, cfg, toast]);

  const loadData = useCallback(async (tableName?: string, off?: number) => {
    const t = tableName ?? selected;
    if (!t) return;
    const o = off ?? offset;
    const r = await call('/api/db/data', {
      method: 'POST', body: JSON.stringify({ ...cfg, table: t, offset: o, limit }),
    });
    if (r.ok) {
      setColumns(r.columns || []);
      setRows((r.rows || []).map((row: any[]) => row.map(formatCell)));
      setTotalApprox(r.total_approx || 0);
      setOffset(o);
      setSelected(t);
    } else {
      toast('Error', r.message, 'danger');
    }
  }, [call, cfg, selected, offset, toast]);

  const viewStructure = useCallback(async () => {
    if (!selected) { toast('Atención', 'Selecciona o conecta primero.', 'warning'); return; }
    const r = await call('/api/db/structure', { method: 'POST', body: JSON.stringify({ ...cfg, table: selected }) });
    if (r.ok) {
      const cols = r.columns || [];
      setColumns(['Columna', 'Tipo', 'Null', 'PK', 'Default']);
      setRows(cols.map((c: any) => [c.name, c.type, c.nullable ? 'NULL' : 'NOT NULL', c.primary_key ? 'PK' : '', c.default || '']));
      setTotalApprox(cols.length);
    } else {
      toast('Error', r.message, 'danger');
    }
  }, [call, cfg, selected, toast]);

  const runSql = useCallback(async () => {
    const r = await call('/api/db/sql', {
      method: 'POST', body: JSON.stringify({ ...cfg, sql, max_rows: 500 }),
    });
    if (r.ok) {
      setColumns(r.columns || []);
      setRows((r.rows || []).map((row: any[]) => row.map(formatCell)));
      toast('SQL ejecutado', r.message, 'success');
    } else {
      toast('SQL erróneo', r.message, 'danger');
    }
  }, [call, cfg, sql, toast]);

  const exportCsv = useCallback(async () => {
    const t = selected;
    if (!t) { toast('Atención', 'Selecciona tabla.', 'warning'); return; }
    const r = await call('/api/db/export-csv', { method: 'POST', body: JSON.stringify({ ...cfg, table: t }) });
    if (r.ok) {
      const blob = new Blob([r.csv], { type: 'text/csv;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${t}.csv`;
      a.click();
      URL.revokeObjectURL(url);
      toast('CSV exportado', `${r.rowcount} filas`, 'success');
    } else {
      toast('Error exportando', r.message, 'danger');
    }
  }, [call, cfg, selected, toast]);

  const loadActiveConnections = useCallback(async () => {
    const r = await call('/api/db/active-connections', { method: 'POST', body: JSON.stringify(cfg) });
    if (r.ok) {
      setActiveConnections(r.connections || []);
    } else {
      toast('pg_stat_activity', r.message, 'warning');
      setActiveConnections([]);
    }
  }, [call, cfg, toast]);

  useEffect(() => { if (connected && selected) loadData(selected, 0); }, [connected]);

  const connStr = useVpn
    ? `postgresql+asyncpg://${rUser}:${rPass}@${rHost}:${rPort}/${rDb}`
    : `postgresql+asyncpg://${user}:${pass}@${host}:${port}/${db}`;

  return (
    <div>
      <Card title="Configuración de conexión" sub="PostgreSQL local Docker o remoto por VPN" icon={<span>🔌</span>}>
        <div className="row mb-16">
          <label className="row gap-8 fs-12 fw-700">
            <input type="checkbox" checked={useVpn} onChange={e => setUseVpn(e.target.checked)} />
            Usar PG remoto (VPN)
          </label>
        </div>

        {!useVpn ? (
          <>
            <div className="grid-2 gap-8">
              <div className="form-row"><span className="form-label">Host</span><input className="input" value={host} onChange={e => setHost(e.target.value)} /></div>
              <div className="form-row"><span className="form-label">Puerto</span><input className="input" value={port} onChange={e => setPort(e.target.value)} /></div>
              <div className="form-row"><span className="form-label">Base de datos</span><input className="input" value={db} onChange={e => setDb(e.target.value)} /></div>
              <div className="form-row"><span className="form-label">Usuario</span><input className="input" value={user} onChange={e => setUser(e.target.value)} /></div>
              <div className="form-row"><span className="form-label">Contraseña</span><input type="password" className="input" value={pass} onChange={e => setPass(e.target.value)} /></div>
            </div>
          </>
        ) : (
          <>
            <div className="grid-2 gap-8">
              <div className="form-row"><span className="form-label">Host remoto</span><input className="input" value={rHost} onChange={e => setRHost(e.target.value)} placeholder="10.x.x.x por VPN" /></div>
              <div className="form-row"><span className="form-label">Puerto</span><input className="input" value={rPort} onChange={e => setRPort(e.target.value)} /></div>
              <div className="form-row"><span className="form-label">Base datos</span><input className="input" value={rDb} onChange={e => setRDb(e.target.value)} /></div>
              <div className="form-row"><span className="form-label">Usuario</span><input className="input" value={rUser} onChange={e => setRUser(e.target.value)} /></div>
              <div className="form-row"><span className="form-label">Contraseña</span><input type="password" className="input" value={rPass} onChange={e => setRPass(e.target.value)} /></div>
            </div>
          </>
        )}

        <div className="row">
          <span className="form-label">Connection string:</span>
          <input className="input mono flex-1" readOnly value={connStr} />
        </div>

        <div className="btn-row">
          <AsyncButton variant="success" onClick={connect} runningText="Conectando…">🔗 Conectar y Listar Tablas</AsyncButton>
          <AsyncButton onClick={() => connect()} runningText="Refrescando…">🔄 Refrescar</AsyncButton>
          <AsyncButton onClick={loadActiveConnections} runningText="Cargando…">📡 Conexiones activas (pg_stat_activity)</AsyncButton>
        </div>

        <span className={`badge ${connected ? 'ok' : 'neutral'}`}>
          <span className="dot" /> {connected ? `Conectado · ${tables.length} tablas` : 'Sin conexión'}
        </span>
      </Card>

      {activeConnections.length > 0 && (
        <Card title="Conexiones activas a PostgreSQL" sub="Lectura de pg_stat_activity" icon={<span>📡</span>}>
          <div className="table-wrap">
            <table className="table mono">
              <thead><tr><th>PID</th><th>Usuario</th><th>Cliente</th><th>Estado</th><th>Query</th><th>Duración</th></tr></thead>
              <tbody>
                {activeConnections.map((c, i) => (
                  <tr key={i}>
                    <td>{c.pid}</td><td>{c.usename || '—'}</td><td>{c.client_addr || '—'}</td>
                    <td>{c.state || '—'}</td><td title={c.query}>{(c.query || '').slice(0, 80)}</td>
                    <td>{c.duration || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {connected && (
        <Card title="Explorador de tablas" sub="Ver cualquier tabla, su estructura, datos paginados y SQL libre" icon={<span>🔎</span>}>
          <div className="row gap-8 flex-wrap mb-16">
            <select className="select" style={{ minWidth: 280 }} value={selected} onChange={e => { setSelected(e.target.value); setOffset(0); }}>
              {tables.length === 0 && <option>(sin tablas)</option>}
              {tables.map(t => <option key={t} value={t}>{t}</option>)}
            </select>
            <AsyncButton variant="primary" onClick={() => loadData(selected, 0)} runningText="Cargando…">👁 Ver datos ({limit})</AsyncButton>
            <AsyncButton onClick={viewStructure} runningText="…">ℹ Ver estructura</AsyncButton>
            <AsyncButton variant="success" onClick={exportCsv} runningText="Exportando…">💾 Exportar CSV</AsyncButton>
          </div>

          {/* Paginación */}
          <div className="row gap-8 mb-16">
            <button className="btn btn-sm" disabled={offset === 0} onClick={() => loadData(selected, Math.max(0, offset - limit))}>⬅ Anterior</button>
            <span className="muted fs-12">Página {Math.floor(offset / limit) + 1} de {totalApprox ? Math.ceil(totalApprox / limit) : '?'}</span>
            <button className="btn btn-sm" disabled={rows.length < limit} onClick={() => loadData(selected, offset + limit)}>Siguiente ➡</button>
            <span className="muted fs-12">≈{totalApprox} filas</span>
          </div>

          {/* SQL libre */}
          <div className="col mt-16">
            <label className="form-label">SQL libre (read-only)</label>
            <textarea className="input" rows={3} value={sql} onChange={e => setSql(e.target.value)} />
            <AsyncButton variant="warning" onClick={runSql} runningText="Ejecutando…" icon={<span>▶</span>}>Ejecutar SQL</AsyncButton>
          </div>

          {/* Resultados */}
          <div className="mt-16">
            <div className="muted fs-12 mb-8">{columns.length} columna(s) · {rows.length} fila(s) mostradas</div>
            <div className="table-wrap">
              {columns.length === 0 ? (
                <div className="empty"><div className="empty-icon">📭</div>(Pulsa "Ver datos" o "Ejecutar SQL")</div>
              ) : (
                <table className="table mono">
                  <thead><tr>{columns.map((c, i) => <th key={i}>{c}</th>)}</tr></thead>
                  <tbody>
                    {rows.map((r, i) => (
                      <tr key={i}>{r.map((c, j) => <td key={j} title={String(c)}>{c}</td>)}</tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        </Card>
      )}
    </div>
  );
}

function formatCell(v: any): string {
  if (v === null || v === undefined) return '(NULL)';
  if (typeof v === 'boolean') return v ? 'true' : 'false';
  if (v instanceof Uint8Array || (typeof v === 'object' && v && v.constructor?.name === 'Uint8Array')) {
    try { return new TextDecoder().decode(v).slice(0, 80); } catch { return `<${(v as any).length} bytes>`; }
  }
  const s = String(v);
  return s.length > 200 ? s.slice(0, 197) + '…' : s;
}
