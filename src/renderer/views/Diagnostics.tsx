import React, { useState, useEffect, useCallback } from 'react';
import { Card } from '../components/Card';
import { AsyncButton } from '../components/Button';

interface PortStatus {
  port: number;
  service: string;
  type: string;
  status: 'FREE' | 'OPEN' | 'CONFLICT';
  is_open: boolean;
  is_conflict: boolean;
  pid?: string | number;
  process_name?: string;
  suggested_port?: number;
  recommendation?: string;
}

interface TunnelItem {
  id: string;
  type: string;
  port: number;
  pid: number;
  status: string;
  start_time: string;
  public_url?: string;
  last_logs?: string[];
}

interface ErrorEvent {
  id: string;
  timestamp: string;
  level: string;
  category: string;
  title: string;
  message: string;
  details?: string;
  stack_trace?: string;
  source?: string;
  port?: number;
  suggested_fix?: string;
}

export function DiagnosticsView({ call, toast }: {
  call: (path: string, opts?: RequestInit) => Promise<any>;
  toast: (title: string, body?: string, kind?: any) => void;
}) {
  const [ports, setPorts] = useState<PortStatus[]>([]);
  const [portSummary, setPortSummary] = useState<any>({});
  const [loadingPorts, setLoadingPorts] = useState(false);

  const [tunnels, setTunnels] = useState<TunnelItem[]>([]);
  const [tunnelType, setTunnelType] = useState('zrok_tcp');
  const [tunnelPort, setTunnelPort] = useState('5432');
  const [tunnelToken, setTunnelToken] = useState('');

  const [errors, setErrors] = useState<ErrorEvent[]>([]);
  const [severityFilter, setSeverityFilter] = useState('ALL');
  const [expandedErrorId, setExpandedErrorId] = useState<string | null>(null);

  const [autoHealResult, setAutoHealResult] = useState<any>(null);

  // Carga de puertos especiales
  const refreshPorts = useCallback(async () => {
    setLoadingPorts(true);
    try {
      const res = await call('/api/system/special-ports');
      if (res && res.ports) {
        setPorts(res.ports);
        setPortSummary(res.summary || {});
      }
    } catch (e: any) {
      toast('Error al escanear puertos', e.message, 'danger');
    } finally {
      setLoadingPorts(false);
    }
  }, [call, toast]);

  // Carga de túneles
  const refreshTunnels = useCallback(async () => {
    try {
      const res = await call('/api/tunnels/status');
      if (res && res.tunnels) {
        setTunnels(res.tunnels);
      }
    } catch (e: any) {
      // Silencioso
    }
  }, [call]);

  // Carga de errores / telemetría
  const refreshErrors = useCallback(async () => {
    try {
      const q = severityFilter !== 'ALL' ? `?severity=${severityFilter}` : '';
      const res = await call(`/api/diagnostics/errors${q}`);
      if (res && res.errors) {
        setErrors(res.errors);
      }
    } catch (e: any) {
      // Silencioso
    }
  }, [call, severityFilter]);

  useEffect(() => {
    refreshPorts();
    refreshTunnels();
    refreshErrors();
    const interval = setInterval(() => {
      refreshTunnels();
    }, 4000);
    return () => clearInterval(interval);
  }, [refreshPorts, refreshTunnels, refreshErrors]);

  // Iniciar túnel
  const handleStartTunnel = useCallback(async () => {
    const res = await call('/api/tunnels/start', {
      method: 'POST',
      body: JSON.stringify({
        tunnel_type: tunnelType,
        port: parseInt(tunnelPort) || 5432,
        token: tunnelToken || undefined,
      }),
    });
    toast(res.ok ? 'Túnel iniciado' : 'Error de túnel', res.message, res.ok ? 'success' : 'danger');
    refreshTunnels();
    refreshPorts();
  }, [call, tunnelType, tunnelPort, tunnelToken, toast, refreshTunnels, refreshPorts]);

  // Detener túnel
  const handleStopTunnel = useCallback(async (id: string) => {
    const res = await call('/api/tunnels/stop', {
      method: 'POST',
      body: JSON.stringify({ tunnel_id: id }),
    });
    toast('Túnel detenido', res.message, res.ok ? 'success' : 'warning');
    refreshTunnels();
    refreshPorts();
  }, [call, toast, refreshTunnels, refreshPorts]);

  // Auto reparar conflictos
  const handleAutoHeal = useCallback(async () => {
    const res = await call('/api/diagnostics/auto-heal', { method: 'POST' });
    setAutoHealResult(res);
    toast(
      'Auto-Reparación de Puertos',
      `Conflictos detectados: ${res.total_conflicts}. Acciones sugeridas: ${res.healing_actions?.length || 0}`,
      res.total_conflicts === 0 ? 'success' : 'warning'
    );
    refreshPorts();
  }, [call, toast, refreshPorts]);

  // Limpiar errores
  const handleClearErrors = useCallback(async () => {
    await call('/api/diagnostics/errors/clear', { method: 'POST' });
    toast('Telemetría', 'Historial de errores limpiado', 'success');
    refreshErrors();
  }, [call, toast, refreshErrors]);

  // Exportar reporte de diagnóstico
  const handleExportReport = useCallback(async () => {
    const res = await call('/api/diagnostics/export');
    if (res.ok && res.report) {
      const jsonStr = JSON.stringify(res.report, null, 2);
      navigator.clipboard.writeText(jsonStr);
      toast('Diagnóstico Exportado', 'Reporte completo JSON copiado al portapapeles', 'success');
    } else {
      toast('Error exportando', res.message, 'danger');
    }
  }, [call, toast]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* Resumen Superior */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 12 }}>
        <div>
          <h2 style={{ fontSize: 20, fontWeight: 700, margin: 0 }}>🩺 Radar de Puertos, Diagnóstico & Túneles</h2>
          <p className="muted fs-12" style={{ marginTop: 4 }}>
            Monitoreo autónomo de conflictos en puertos críticos (5432, 9000, 22), auto-reparación y telemetría de errores.
          </p>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <AsyncButton variant="primary" onClick={refreshPorts} runningText="Escaneando…">
            🔄 Re-escanear
          </AsyncButton>
          <AsyncButton variant="warning" onClick={handleAutoHeal} runningText="Analizando…">
            ⚡ Auto-Reparar Conflictos
          </AsyncButton>
          <button className="btn" onClick={handleExportReport} title="Copia reporte completo al portapapeles">
            📋 Exportar Reporte
          </button>
        </div>
      </div>

      {/* Tarjetas de Estadísticas Rápidas */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 12 }}>
        <div className="card" style={{ padding: 14 }}>
          <div className="muted fs-12">Puertos Vigilados</div>
          <div style={{ fontSize: 24, fontWeight: 800, marginTop: 4 }}>{portSummary.total_scanned || ports.length}</div>
          <div className="fs-12 mt-4">{portSummary.open_count || 0} escuchando</div>
        </div>
        <div className="card" style={{ padding: 14, borderColor: (portSummary.conflict_count || 0) > 0 ? 'var(--danger)' : 'var(--border)' }}>
          <div className="muted fs-12">Conflictos de Puerto</div>
          <div style={{ fontSize: 24, fontWeight: 800, marginTop: 4, color: (portSummary.conflict_count || 0) > 0 ? 'var(--danger)' : 'var(--success)' }}>
            {portSummary.conflict_count || 0}
          </div>
          <div className="fs-12 mt-4">{(portSummary.conflict_count || 0) > 0 ? 'Requiere atención' : 'Todo en orden ✓'}</div>
        </div>
        <div className="card" style={{ padding: 14 }}>
          <div className="muted fs-12">Túneles Activos</div>
          <div style={{ fontSize: 24, fontWeight: 800, marginTop: 4, color: tunnels.length > 0 ? 'var(--primary)' : 'inherit' }}>
            {tunnels.length}
          </div>
          <div className="fs-12 mt-4">Zrok / Ngrok / Cloudflare</div>
        </div>
        <div className="card" style={{ padding: 14 }}>
          <div className="muted fs-12">Eventos Registrados</div>
          <div style={{ fontSize: 24, fontWeight: 800, marginTop: 4 }}>{errors.length}</div>
          <div className="fs-12 mt-4">Telemetría local</div>
        </div>
      </div>

      {/* Banner de Auto-Heal si se ejecutó */}
      {autoHealResult && autoHealResult.healing_actions && autoHealResult.healing_actions.length > 0 && (
        <div className="card" style={{ padding: 16, background: 'var(--bg-hover)', borderLeft: '4px solid var(--warning)' }}>
          <div style={{ fontWeight: 600, marginBottom: 8 }}>⚡ Plan de Mitigación y Auto-Reparación Generado:</div>
          <ul style={{ paddingLeft: 20, margin: 0, fontSize: 13 }}>
            {autoHealResult.healing_actions.map((act: any, idx: number) => (
              <li key={idx} style={{ marginBottom: 4 }}>
                <strong>Puerto {act.port}:</strong> {act.detail} (Sugerido: <code>{act.suggested_port}</code>)
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* 1. RADAR DE PUERTOS ESPECIALES */}
      <Card title="Radar de Puertos Críticos y Servicios" sub="Inspección en tiempo real de puertos vinculados a FacturaPro, bases de datos y túneles" icon={<span>📡</span>}>
        <div style={{ overflowX: 'auto' }}>
          <table className="table" style={{ width: '100%', fontSize: 13, borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid var(--border)', textAlign: 'left' }}>
                <th style={{ padding: '8px 10px' }}>Puerto</th>
                <th style={{ padding: '8px 10px' }}>Servicio Esperado</th>
                <th style={{ padding: '8px 10px' }}>Tipo</th>
                <th style={{ padding: '8px 10px' }}>Estado</th>
                <th style={{ padding: '8px 10px' }}>Proceso / PID</th>
                <th style={{ padding: '8px 10px' }}>Puerto Alternativo</th>
                <th style={{ padding: '8px 10px' }}>Diagnóstico</th>
              </tr>
            </thead>
            <tbody>
              {ports.map((p) => {
                const isConflict = p.is_conflict || p.status === 'CONFLICT';
                const isOpen = p.is_open || p.status === 'OPEN';
                return (
                  <tr key={p.port} style={{ borderBottom: '1px solid var(--border)' }}>
                    <td style={{ padding: '10px', fontWeight: 700 }} className="mono">{p.port}</td>
                    <td style={{ padding: '10px' }}>{p.service}</td>
                    <td style={{ padding: '10px' }}>
                      <span className="badge" style={{ fontSize: 11 }}>{p.type}</span>
                    </td>
                    <td style={{ padding: '10px' }}>
                      {isConflict ? (
                        <span className="badge warn" style={{ background: 'var(--danger-faint)', color: 'var(--danger)' }}>
                          ⚠ CONFLICTO
                        </span>
                      ) : isOpen ? (
                        <span className="badge ok" style={{ background: 'var(--success-faint)', color: 'var(--success)' }}>
                          ● EN USO
                        </span>
                      ) : (
                        <span className="badge" style={{ opacity: 0.7 }}>
                          ○ LIBRE
                        </span>
                      )}
                    </td>
                    <td style={{ padding: '10px' }} className="mono fs-12">
                      {p.process_name ? (
                        <span>{p.process_name} {p.pid ? `[PID ${p.pid}]` : ''}</span>
                      ) : (
                        <span className="muted">-</span>
                      )}
                    </td>
                    <td style={{ padding: '10px' }} className="mono fs-12">
                      {p.suggested_port ? (
                        <strong style={{ color: 'var(--primary)' }}>{p.suggested_port}</strong>
                      ) : (
                        <span className="muted">-</span>
                      )}
                    </td>
                    <td style={{ padding: '10px', fontSize: 12 }}>
                      <span className={isConflict ? 'text-danger' : 'muted'}>{p.recommendation}</span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>

      {/* 2. GESTOR DE TÚNELES */}
      <Card title="Gestión de Túneles Nativos (Zrok, Ngrok, Cloudflare)" sub="Controla y supervisa los túneles directamente desde FacturaProEC sin ventanas CMD externas" icon={<span>🌐</span>}>
        {/* Barra para lanzar nuevo túnel */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 10, alignItems: 'end', marginBottom: 16 }}>
          <div>
            <label className="form-label">Tipo de Túnel</label>
            <select className="input" value={tunnelType} onChange={(e) => setTunnelType(e.target.value)}>
              <option value="zrok_tcp">Zrok TCP (PostgreSQL 5432)</option>
              <option value="zrok_http">Zrok HTTP (Web 8001 / API)</option>
              <option value="zrok_reserved">Zrok Reservado (Token Persistente)</option>
              <option value="ngrok_tcp">Ngrok TCP (5432)</option>
              <option value="ngrok_http">Ngrok HTTP (8001)</option>
              <option value="cloudflared_http">Cloudflare WARP/Tunnel HTTP</option>
            </select>
          </div>
          <div>
            <label className="form-label">Puerto Local</label>
            <input className="input mono" value={tunnelPort} onChange={(e) => setTunnelPort(e.target.value)} placeholder="5432" />
          </div>
          {tunnelType === 'zrok_reserved' && (
            <div>
              <label className="form-label">Token Reservado</label>
              <input className="input mono" value={tunnelToken} onChange={(e) => setTunnelToken(e.target.value)} placeholder="token-share-id" />
            </div>
          )}
          <div>
            <AsyncButton variant="primary" onClick={handleStartTunnel} runningText="Lanzando…">
              🚀 Iniciar Túnel
            </AsyncButton>
          </div>
        </div>

        {/* Lista de túneles en ejecución */}
        <div style={{ marginTop: 12 }}>
          <h4 style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>Túneles Activos en este Sistema ({tunnels.length})</h4>
          {tunnels.length === 0 ? (
            <div className="empty" style={{ padding: 24, border: '1px dashed var(--border)', borderRadius: 'var(--radius)' }}>
              <div className="muted fs-13">No hay túneles ejecutándose activamente desde la aplicación.</div>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {tunnels.map((t) => (
                <div key={t.id} className="card" style={{ padding: 12, display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
                  <div>
                    <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                      <span className="badge ok" style={{ fontSize: 11 }}>ACTIVO</span>
                      <strong>{t.type}</strong>
                      <span className="mono fs-12 muted">Puerto: {t.port} | PID: {t.pid}</span>
                    </div>
                    {t.public_url && (
                      <div style={{ marginTop: 4, display: 'flex', gap: 6, alignItems: 'center' }}>
                        <span className="fs-12 muted">URL Pública:</span>
                        <code className="mono" style={{ color: 'var(--primary)', fontWeight: 600 }}>{t.public_url}</code>
                        <button
                          className="btn btn-sm"
                          onClick={() => {
                            navigator.clipboard.writeText(t.public_url || '');
                            toast('URL copiada', t.public_url, 'success');
                          }}
                        >
                          Copiar
                        </button>
                      </div>
                    )}
                    {t.last_logs && t.last_logs.length > 0 && (
                      <div className="mono fs-11 muted" style={{ marginTop: 4, maxHeight: 40, overflow: 'hidden' }}>
                        {t.last_logs[t.last_logs.length - 1]}
                      </div>
                    )}
                  </div>
                  <div>
                    <button className="btn btn-danger" onClick={() => handleStopTunnel(t.id)}>
                      🛑 Detener
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </Card>

      {/* 3. TELEMETRÍA Y LOGS DE ERRORES */}
      <Card title="Centro de Telemetría y Errores de FacturaProEC" sub="Recopilación centralizada y persistente de advertencias, excepciones y errores de la plataforma" icon={<span>📊</span>}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12, flexWrap: 'wrap', gap: 8 }}>
          <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
            <span className="fs-12 muted">Filtrar por severidad:</span>
            {['ALL', 'CRITICAL', 'ERROR', 'WARNING', 'INFO'].map((lvl) => (
              <button
                key={lvl}
                className={`btn btn-sm ${severityFilter === lvl ? 'btn-primary' : ''}`}
                onClick={() => setSeverityFilter(lvl)}
              >
                {lvl}
              </button>
            ))}
          </div>
          <button className="btn btn-sm" onClick={handleClearErrors} title="Borra el archivo de telemetría local">
            🗑 Limpiar Historial
          </button>
        </div>

        {errors.length === 0 ? (
          <div className="empty" style={{ padding: 24, border: '1px dashed var(--border)', borderRadius: 'var(--radius)' }}>
            <div className="empty-icon">✓</div>
            <div className="fs-13">No se han registrado errores o advertencias con el filtro actual.</div>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {errors.map((err) => {
              const isExpanded = expandedErrorId === err.id;
              const lvlColor =
                err.level === 'CRITICAL' ? 'var(--danger)' :
                err.level === 'ERROR' ? 'var(--danger)' :
                err.level === 'WARNING' ? 'var(--warning)' : 'var(--primary)';

              return (
                <div key={err.id} className="card" style={{ padding: 12, cursor: 'pointer' }} onClick={() => setExpandedErrorId(isExpanded ? null : err.id)}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                      <span className="badge" style={{ background: 'var(--bg-hover)', color: lvlColor, fontWeight: 700, fontSize: 11 }}>
                        {err.level}
                      </span>
                      <strong style={{ fontSize: 13 }}>{err.title || err.message}</strong>
                      <span className="muted fs-11 mono">[{err.category}]</span>
                      {err.port && <span className="badge" style={{ fontSize: 10 }}>Puerto {err.port}</span>}
                    </div>
                    <div className="muted fs-11 mono">
                      {new Date(err.timestamp).toLocaleTimeString()}
                    </div>
                  </div>

                  {err.suggested_fix && (
                    <div style={{ marginTop: 6, fontSize: 12, color: 'var(--text-sub)' }}>
                      💡 <em>Sugerencia:</em> {err.suggested_fix}
                    </div>
                  )}

                  {isExpanded && (
                    <div style={{ marginTop: 10, paddingTop: 10, borderTop: '1px solid var(--border)' }} onClick={(e) => e.stopPropagation()}>
                      <div className="fs-12 mb-4"><strong>Origen:</strong> <code>{err.source || 'sistema'}</code></div>
                      {err.details && (
                        <div style={{ marginBottom: 6 }}>
                          <div className="muted fs-11">Detalle adicional:</div>
                          <pre className="mono fs-11" style={{ background: 'var(--bg-elev)', padding: 8, borderRadius: 4, overflowX: 'auto' }}>
                            {err.details}
                          </pre>
                        </div>
                      )}
                      {err.stack_trace && (
                        <div>
                          <div className="muted fs-11">Stack Trace:</div>
                          <pre className="mono fs-11" style={{ background: 'var(--bg-elev)', padding: 8, borderRadius: 4, overflowX: 'auto', maxHeight: 150 }}>
                            {err.stack_trace}
                          </pre>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </Card>
    </div>
  );
}