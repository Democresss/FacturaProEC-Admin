import React, { useState, useEffect } from 'react';
import { Card } from '../components/Card';
import { AsyncButton } from '../components/Button';

interface SystemInfo {
  ok: boolean;
  is_admin?: boolean;
  local_ip?: string;
  disk?: { total_gb: number; used_gb: number; free_gb: number; used_pct: number };
  file_count?: number;
  services?: Record<string, boolean>;
  platform?: string;
  python?: string;
  error?: string;
}

export function DashboardView({ call, goto }: {
  call: (path: string, opts?: RequestInit) => Promise<any>;
  goto: (id: any) => void;
}) {
  const [info, setInfo] = useState<SystemInfo | null>(null);

  const refresh = async () => {
    const r = await call('/api/system/info');
    setInfo(r);
  };

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 15000);
    return () => clearInterval(id);
  }, []);

  const services = info?.services || {};
  const serviceList: [string, string, boolean][] = [
    ['openssh_22', 'OpenSSH / SFTP (22)', services.openssh_22],
    ['sftpgo_2022', 'SFTPGo (2022)', services.sftpgo_2022],
    ['ftp_21', 'FTP (21)', services.ftp_21],
    ['postgres_5432', 'PostgreSQL (5432)', services.postgres_5432],
    ['minio_9000', 'MinIO S3 (9000)', services.minio_9000],
    ['sftpgo_web_8080', 'SFTPGo Web (8080)', services.sftpgo_web_8080],
  ];

  return (
    <div>
      {info?.ok === false && (
        <Card title="Error" icon={<span>⚠</span>}>
          <div className="danger">{info.error}</div>
        </Card>
      )}

      <div className="grid-4 mb-16" style={{ marginBottom: 16 }}>
        <Card>
          <div className="stat-block">
            <span className="label">IP local</span>
            <span className="value mono fs-13">{info?.local_ip || '—'}</span>
          </div>
        </Card>
        <Card>
          <div className="stat-block">
            <span className="label">Espacio usado</span>
            <span className="value">{info?.disk?.used_pct ?? '—'}%</span>
            <span className="muted fs-11">{info?.disk?.used_gb ?? 0} / {info?.disk?.total_gb ?? 0} GB</span>
          </div>
        </Card>
        <Card>
          <div className="stat-block">
            <span className="label">Archivos locales</span>
            <span className="value">{info?.file_count ?? '—'}</span>
          </div>
        </Card>
        <Card>
          <div className="stat-block">
            <span className="label">Permisos admin</span>
            <span className="value">
              <span className={`badge ${info?.is_admin ? 'ok' : 'warn'}`}>{info?.is_admin ? 'SÍ' : 'NO'}</span>
            </span>
          </div>
        </Card>
      </div>

      <div className="grid-2" style={{ marginBottom: 16 }}>
        <Card
          title="Servicios detectados"
          sub="Puertos abiertos en la IP local (auto-refresco cada 15s)"
          icon={<span>🛰</span>}
          right={<AsyncButton variant="primary" size="sm" onClick={refresh}>🔄 Refrescar</AsyncButton>}
        >
          <div className="col mt-16">
            {serviceList.map(([key, label, on]) => (
              <div key={key} className="row between">
                <span className="fs-13">{label}</span>
                <span className={`badge ${on ? 'ok' : 'neutral'}`}>
                  <span className={`dot ${on ? '' : 'pulse'}`} /> {on ? 'ON' : 'OFF'}
                </span>
              </div>
            ))}
          </div>
        </Card>

        <Card title="Atajos" sub="Accesos rápidos a los módulos" icon={<span>⚡</span>}>
          <div className="grid-2 gap-8">
            <button className="btn" onClick={() => goto('db')}>🗄 Ver Base de Datos</button>
            <button className="btn" onClick={() => goto('sri')}>🧾 Sincronizar SRI</button>
            <button className="btn" onClick={() => goto('security')}>🛡 Ver Seguridad</button>
            <button className="btn" onClick={() => goto('storage')}>💾 Almacenamiento</button>
            <button className="btn" onClick={() => goto('vpn')}>🔒 VPN</button>
            <button className="btn" onClick={() => goto('config')}>⚙ Configuración</button>
          </div>
        </Card>
      </div>

      <Card title="Plataforma" icon={<span>ℹ</span>}>
        <div className="grid-2 fs-12">
          <div><span className="muted">SO:</span> <span className="mono">{info?.platform}</span></div>
          <div><span className="muted">Python:</span> <span className="mono">{info?.python}</span></div>
        </div>
      </Card>
    </div>
  );
}
