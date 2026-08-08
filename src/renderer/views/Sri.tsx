import React, { useState, useCallback, useEffect, useRef } from 'react';
import { Card } from '../components/Card';
import { AsyncButton } from '../components/Button';
import { Modal } from '../components/Modal';

interface ImapForm {
  host: string; port: string; user: string; password: string; folder: string;
  limit: number; org_id: string;
}

interface DbCfg {
  pg_host: string; pg_port: number; pg_db: string; pg_user: string; pg_pass: string;
}

const DEFAULT_IMAP: ImapForm = {
  host: 'imap.gmail.com', port: '993', user: '', password: '', folder: 'INBOX',
  limit: 50, org_id: 'default',
};

export function SriView({ call, toast }: {
  call: (path: string, opts?: RequestInit) => Promise<any>;
  toast: (title: string, body?: string, kind?: any) => void;
}) {
  const [imap, setImap] = useState<ImapForm>(DEFAULT_IMAP);
  const [autoSync, setAutoSync] = useState(false);
  const [syncInterval, setSyncInterval] = useState('15');
  const [log, setLog] = useState<{ ts: string; msg: string; kind?: string }[]>([]);
  const [lastSync, setLastSync] = useState('');
  const [inbox, setInbox] = useState<any[]>([]);
  const [inboxPage, setInboxPage] = useState(0);
  const pageSize = 50;

  // RUC
  const [ruc, setRuc] = useState('');
  const [rucData, setRucData] = useState<any>(null);
  const [rucModalOpen, setRucModalOpen] = useState(false);

  // XML modal
  const [xmlContent, setXmlContent] = useState('');
  const [xmlModalTitle, setXmlModalTitle] = useState('');
  const [xmlModalOpen, setXmlModalOpen] = useState(false);

  // PG config (se llena desde el config global)
  const [dbCfg, setDbCfg] = useState<DbCfg>({
    pg_host: '127.0.0.1', pg_port: 5432, pg_db: 'facturapro_db',
    pg_user: 'postgres_user', pg_pass: 'ClaveSegura123!',
  });

  const logRef = useRef<HTMLDivElement>(null);

  const addLog = useCallback((msg: string, kind?: string) => {
    const ts = new Date().toLocaleTimeString();
    setLog(prev => [...prev, { ts, msg, kind }].slice(-200));
    setTimeout(() => { if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight; }, 50);
  }, []);

  // Cargar config persistido
  useEffect(() => {
    (async () => {
      const r = await call('/api/config');
      if (r.ok && r.data) {
        const d = r.data;
        setImap(prev => ({
          ...prev,
          host: d.sri_imap_host || 'imap.gmail.com',
          port: String(d.sri_imap_port || 993),
          user: d.sri_imap_user || '',
          password: d.sri_imap_pass || '',
          folder: d.sri_imap_folder || 'INBOX',
          org_id: d.sri_org_id_default || 'default',
        }));
        setAutoSync(Boolean(d.sri_auto_sync));
        setSyncInterval(String(d.sri_sync_interval_min || 15));
        setDbCfg({
          pg_host: d.pg_host || '127.0.0.1',
          pg_port: d.pg_port || 5432,
          pg_db: d.pg_db || 'facturapro_db',
          pg_user: d.pg_user || 'postgres_user',
          pg_pass: d.pg_pass || 'ClaveSegura123!',
        });
      }
    })();
  }, []);

  const persistImap = useCallback(async () => {
    await call('/api/config', { method: 'POST', body: JSON.stringify({
      data: {
        sri_imap_host: imap.host, sri_imap_port: parseInt(imap.port) || 993,
        sri_imap_user: imap.user, sri_imap_pass: imap.password,
        sri_imap_folder: imap.folder, sri_auto_sync: autoSync,
        sri_sync_interval_min: parseInt(syncInterval) || 15,
        sri_org_id_default: imap.org_id,
      },
    }) });
  }, [call, imap, autoSync, syncInterval]);

  const testImap = useCallback(async () => {
    addLog(`Probando conexión ${imap.host}:${imap.port} …`);
    await persistImap();
    const r = await call('/api/sri/test-imap', {
      method: 'POST', body: JSON.stringify({ ...imap, port: parseInt(imap.port) || 993, ...dbCfg }),
    });
    if (r.ok) {
      addLog(r.message, 'ok');
      toast('Conexión IMAP', r.message, 'success');
    } else {
      addLog(r.message, 'err');
      toast('Fallo IMAP', r.message, 'danger');
    }
  }, [call, imap, dbCfg, persistImap, addLog, toast]);

  const syncNow = useCallback(async () => {
    addLog(`🔄 Sincronizando ${imap.host}:${imap.port} carpeta '${imap.folder}' …`);
    await persistImap();
    const r = await call('/api/sri/sync', {
      method: 'POST', body: JSON.stringify({
        host: imap.host, port: parseInt(imap.port) || 993,
        user: imap.user, password: imap.password, folder: imap.folder,
        limit: imap.limit, org_id: imap.org_id, ...dbCfg,
      }),
    });
    if (r.ok && r.stats) {
      const s = r.stats;
      const msg = `✅ Sync OK: ${s.comprobantes_nuevos} nuevos, ${s.comprobantes_duplicados} duplicados, ${s.errores} errores — ${s.emails_processados} emails leídos.${s.detalle ? `\n${s.detalle}` : ''}`;
      addLog(msg, 'ok');
      const now = new Date().toLocaleTimeString();
      setLastSync(`${now} — ${s.comprobantes_nuevos} nuevos`);
      toast('Sync SRI completo', `${s.comprobantes_nuevos} nuevos · ${s.comprobantes_duplicados} duplicados`, 'success');
      loadInbox(0);
    } else {
      addLog(r.message || 'Error sincronizando', 'err');
      toast('Error sync', r.message, 'danger');
    }
  }, [call, imap, dbCfg, persistImap, addLog, toast]);

  const loadInbox = useCallback(async (page: number) => {
    const params = new URLSearchParams({
      limit: String(pageSize), offset: String(page * pageSize),
      pg_host: dbCfg.pg_host, pg_port: String(dbCfg.pg_port),
      pg_db: dbCfg.pg_db, pg_user: dbCfg.pg_user, pg_pass: dbCfg.pg_pass,
    });
    const r = await call(`/api/sri/inbox?${params}`);
    if (r.ok) {
      setInbox(r.rows || []);
      setInboxPage(page);
    } else {
      addLog(r.message, 'warn');
    }
  }, [call, dbCfg, addLog]);

  useEffect(() => { loadInbox(0); }, []);

  const toggleAutoSync = async (on: boolean) => {
    setAutoSync(on);
    addLog(on ? `⏱ Auto-sync activado cada ${syncInterval} min.` : '⏱ Auto-sync desactivado.');
    await persistImap();
  };

  const consultarRuc = useCallback(async () => {
    if (ruc.length !== 13 || !/^\d{13}$/.test(ruc)) {
      toast('RUC inválido', 'Debe tener 13 dígitos numéricos.', 'warning');
      return;
    }
    const r = await call('/api/sri/ruc', { method: 'POST', body: JSON.stringify({ ruc }) });
    if (r.ok && r.data) {
      setRucData(r.data);
      setRucModalOpen(true);
    } else {
      toast('Consulta RUC', r.message, 'danger');
    }
  }, [call, ruc, toast]);

  const tipoLabel = (t: string) => ({
    '01': 'Factura', '04': 'Nota crédito', '05': 'Nota débito', '07': 'Retención',
  } as any)[t] || t;

  return (
    <div>
      {/* Recepción IMAP */}
      <Card title="Recepción automática (IMAP)" sub="Baja comprobantes XML del correo y los guarda en la BD" icon={<span>📥</span>}>
        <div className="grid-2 gap-8">
          <div className="form-row"><span className="form-label">Servidor IMAP</span><input className="input" value={imap.host} onChange={e => setImap({ ...imap, host: e.target.value })} /></div>
          <div className="form-row"><span className="form-label">Puerto</span><input className="input" value={imap.port} onChange={e => setImap({ ...imap, port: e.target.value })} /></div>
          <div className="form-row"><span className="form-label">Carpeta</span><input className="input" value={imap.folder} onChange={e => setImap({ ...imap, folder: e.target.value })} /></div>
          <div className="form-row"><span className="form-label">Correo</span><input className="input" value={imap.user} onChange={e => setImap({ ...imap, user: e.target.value })} placeholder="tucorreo@gmail.com" /></div>
          <div className="form-row"><span className="form-label">App-password</span><input type="password" className="input" value={imap.password} onChange={e => setImap({ ...imap, password: e.target.value })} /></div>
          <div className="form-row"><span className="form-label">Org ID</span><input className="input" value={imap.org_id} onChange={e => setImap({ ...imap, org_id: e.target.value })} /></div>
        </div>

        <div className="row gap-16 mt-8">
          <label className="row gap-8 fs-12 fw-700">
            <div className={`switch ${autoSync ? 'on' : ''}`} onClick={() => toggleAutoSync(!autoSync)} />
            Auto-sync cada
          </label>
          <input className="input" style={{ width: 60 }} value={syncInterval} onChange={e => setSyncInterval(e.target.value)} />
          <span className="muted fs-12">min</span>
        </div>

        <div className="btn-row">
          <AsyncButton variant="primary" onClick={testImap} runningText="Probando…">🔗 Probar conexión IMAP</AsyncButton>
          <AsyncButton variant="success" onClick={syncNow} runningText="Sincronizando…">🔄 Sincronizar ahora</AsyncButton>
        </div>

        <div className="log-box" ref={logRef}>
          {log.length === 0 ? (
            <span className="muted">Ready. Pulsa 'Probar conexión' con tus credenciales IMAP.</span>
          ) : log.map((l, i) => (
            <div key={i} className={`log-line ${l.kind || ''}`}>[{l.ts}] {l.msg}</div>
          ))}
        </div>
        <div className="muted fs-12 mt-8">Último sync: {lastSync || '—'}</div>
      </Card>

      {/* Consulta RUC */}
      <Card title="Consulta RUC contribuyente" sub="Catastro REST público del SRI (sin auth)" icon={<span>🔎</span>}>
        <div className="row gap-8">
          <input className="input mono" style={{ maxWidth: 220 }} value={ruc} onChange={e => setRuc(e.target.value)} placeholder="13 dígitos" maxLength={13} onKeyDown={e => e.key === 'Enter' && consultarRuc()} />
          <AsyncButton variant="primary" onClick={consultarRuc} runningText="Consultando…">Consultar SRI</AsyncButton>
        </div>
      </Card>

      {/* Bandeja recibidos */}
      <Card title="Bandeja de comprobantes" sub={`Página ${inboxPage + 1}`} icon={<span>📂</span>}
        right={<AsyncButton size="sm" onClick={() => loadInbox(inboxPage)} runningText="Cargando…">🔄 Refrescar</AsyncButton>}
      >
        <div className="table-wrap">
          {inbox.length === 0 ? (
            <div className="empty"><div className="empty-icon">📭</div>No hay comprobantes guardados todavía.</div>
          ) : (
            <table className="table">
              <thead><tr><th>Tipo</th><th>RUC emisor</th><th>Razón social</th><th>Importe</th><th>Estado</th><th>Fecha</th><th></th></tr></thead>
              <tbody>
                {inbox.map((r, i) => (
                  <tr key={i}>
                    <td>{tipoLabel(r.tipo_comprobante)}</td>
                    <td className="mono">{r.ruc_emisor}</td>
                    <td>{(r.razon_social_emisor || '').slice(0, 40)}</td>
                    <td className="mono">${(r.importe_total || 0).toFixed(2)}</td>
                    <td><span className={`badge ${r.estado_autorizacion?.includes('AUTORIZ') ? 'ok' : 'warn'}`}>{r.estado_autorizacion || '—'}</span></td>
                    <td className="fs-11">{r.fecha_emision}</td>
                    <td><button className="btn btn-sm" onClick={() => { setXmlContent(r.xml_recibido || '(sin XML)'); setXmlModalTitle(`XML — ${(r.clave_acceso || '').slice(0, 16)}…`); setXmlModalOpen(true); }}>Ver XML</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
        <div className="row gap-8 mt-8">
          <button className="btn btn-sm" disabled={inboxPage === 0} onClick={() => loadInbox(inboxPage - 1)}>← Anterior</button>
          <span className="muted fs-12">{inbox.length} en esta página</span>
          <button className="btn btn-sm" disabled={inbox.length < pageSize} onClick={() => loadInbox(inboxPage + 1)}>Siguiente →</button>
        </div>
      </Card>

      {/* Modal RUC */}
      <Modal open={rucModalOpen} title="Ficha del contribuyente" onClose={() => setRucModalOpen(false)}
        footer={<button className="btn btn-primary" onClick={() => setRucModalOpen(false)}>Cerrar</button>}>
        {rucData && (
          <div className="col gap-8">
            <div><strong>Razón social:</strong> {rucData.razonSocial}</div>
            <div><strong>RUC:</strong> <span className="mono">{rucData.ruc}</span></div>
            <div><strong>Estado:</strong> {rucData.estado}</div>
            <div><strong>Obligado contabilidad:</strong> {rucData.obligadoContabilidad}</div>
            <div><strong>Agente retención:</strong> {rucData.agenteRetencion}</div>
            <div><strong>Tipo contribuyente:</strong> {rucData.tipoContribuyente}</div>
            {rucData.establecimientos?.length > 0 && (
              <div>
                <strong>Establecimientos ({rucData.establecimientos.length}):</strong>
                <ul className="fs-12 mt-8">
                  {rucData.establecimientos.slice(0, 8).map((e: any, i: number) => (
                    <li key={i}>{e.numero}: {e.direccion || '—'} ({e.estado || '—'})</li>
                  ))}
                  {rucData.establecimientos.length > 8 && <li>… y {rucData.establecimientos.length - 8} más</li>}
                </ul>
              </div>
            )}
          </div>
        )}
      </Modal>

      {/* Modal XML */}
      <Modal open={xmlModalOpen} title={xmlModalTitle} onClose={() => setXmlModalOpen(false)} maxWidth={800}
        footer={<button className="btn btn-primary" onClick={() => setXmlModalOpen(false)}>Cerrar</button>}>
        <pre>{xmlContent}</pre>
      </Modal>
    </div>
  );
}
