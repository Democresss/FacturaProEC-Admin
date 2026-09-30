import React, { useState, useCallback } from 'react';
import { Card } from '../components/Card';
import { AsyncButton } from '../components/Button';

const PROFILES_MAP: Record<string, any> = {
  facturapro: {
    name: 'FacturaProEC Estándar (Recomendado)',
    pgDb: 'facturapro_db',
    pgUser: 'postgres_user',
    pgPass: 'ClaveSegura123!',
    minioUser: 'admin',
    minioPass: 'ClaveSegura123!',
    vpsIp: '159.223.110.159',
    frpToken: 'FacturaProSecure2026!#',
  },
  harpi: {
    name: 'Harpi Corp (Industrial)',
    pgDb: 'app_v2_db',
    pgUser: 'Harpi_postgres_',
    pgPass: '%Harpi2026/@!',
    minioUser: 'admin',
    minioPass: 'ClaveSegura123!',
    vpsIp: '159.223.110.159',
    frpToken: 'HarpiSecureEnterprise2026!#',
  },
  custom: {
    name: 'Personalizado',
  }
};

export function StorageView({ call, toast }: {
  call: (path: string, opts?: RequestInit) => Promise<any>;
  toast: (title: string, body?: string, kind?: any) => void;
}) {
  const [storagePath, setStoragePath] = useState('C:\\factura_uploads');
  const [sftpUser, setSftpUser] = useState('factura_sftp');
  const [sftpPass, setSftpPass] = useState('ClaveSFTP123!');
  const [ftpMinutes, setFtpMinutes] = useState('30');
  const [ftpIp, setFtpIp] = useState('');
  const [dockerInstalled, setDockerInstalled] = useState<boolean | null>(null);

  // Perfil y credenciales dinámicas para Docker Stack
  const [selectedProfile, setSelectedProfile] = useState('facturapro');
  const [pgDb, setPgDb] = useState('facturapro_db');
  const [pgUser, setPgUser] = useState('postgres_user');
  const [pgPass, setPgPass] = useState('ClaveSegura123!');
  const [minioUser, setMinioUser] = useState('admin');
  const [minioPass, setMinioPass] = useState('ClaveSegura123!');
  const [vpsIp, setVpsIp] = useState('159.223.110.159');
  const [frpToken, setFrpToken] = useState('FacturaProSecure2026!#');

  // Configuración de puertos del anfitrión (Host)
  const [pgHostPort, setPgHostPort] = useState('5432');
  const [minioHostPort, setMinioHostPort] = useState('9000');
  const [minioConsoleHostPort, setMinioConsoleHostPort] = useState('9001');
  const [autoRemap, setAutoRemap] = useState(true);

  const handleProfileChange = (key: string) => {
    setSelectedProfile(key);
    if (key !== 'custom' && PROFILES_MAP[key]) {
      const p = PROFILES_MAP[key];
      setPgDb(p.pgDb);
      setPgUser(p.pgUser);
      setPgPass(p.pgPass);
      setMinioUser(p.minioUser);
      setMinioPass(p.minioPass);
      setVpsIp(p.vpsIp);
      setFrpToken(p.frpToken);
    }
  };

  const ensureStorage = useCallback(async () => {
    const r = await call('/api/storage/ensure?' + new URLSearchParams({ path: storagePath }));
    toast(storagePath, r.message, r.ok ? 'success' : 'danger');
  }, [call, storagePath, toast]);

  const createSftpUser = useCallback(async () => {
    const r = await call('/api/sftp/create-user', {
      method: 'POST', body: JSON.stringify({ username: sftpUser, password: sftpPass, folder: storagePath }),
    });
    toast('Usuario SFTP', r.message, r.ok ? 'success' : 'danger');
  }, [call, sftpUser, sftpPass, storagePath, toast]);

  const installOpenssh = useCallback(async () => {
    const r = await call('/api/sftp/install-openssh', { method: 'POST', body: JSON.stringify({}) });
    toast('OpenSSH', r.message, r.ok ? 'success' : 'danger');
  }, [call, toast]);

  const launchDocker = useCallback(async () => {
    const r = await call('/api/docker/launch', {
      method: 'POST',
      body: JSON.stringify({
        profile: selectedProfile,
        pg_db: pgDb,
        pg_user: pgUser,
        pg_pass: pgPass,
        minio_user: minioUser,
        minio_pass: minioPass,
        vps_ip: vpsIp,
        frp_token: frpToken,
        pg_host_port: parseInt(pgHostPort) || 5432,
        minio_host_port: parseInt(minioHostPort) || 9000,
        minio_console_host_port: parseInt(minioConsoleHostPort) || 9001,
        auto_remap: autoRemap,
      }),
    });
    toast('Docker Stack', r.message, r.ok ? 'success' : 'danger');
  }, [call, selectedProfile, pgDb, pgUser, pgPass, minioUser, minioPass, vpsIp, frpToken, pgHostPort, minioHostPort, minioConsoleHostPort, autoRemap, toast]);

  const checkDocker = useCallback(async () => {
    const r = await call('/api/docker/installed');
    setDockerInstalled(r.ok === true);
    toast('Docker', r.ok ? 'Instalado ✓' : 'No detectado', r.ok ? 'success' : 'warning');
  }, [call, toast]);

  const openFtpTemp = useCallback(async () => {
    const r = await call('/api/firewall/ftp-temp', {
      method: 'POST', body: JSON.stringify({ minutes: parseInt(ftpMinutes) || 30, remote_ip: ftpIp }),
    });
    toast('FTP temporal', r.message, r.ok ? 'success' : 'danger');
  }, [call, ftpMinutes, ftpIp, toast]);

  const openFtpPerm = useCallback(async () => {
    const r = await call('/api/firewall/ftp-perm', { method: 'POST', body: JSON.stringify({ remote_ip: ftpIp }) });
    toast('FTP permanente', r.message, r.ok ? 'success' : 'danger');
  }, [call, ftpIp, toast]);

  const cancelFtp = useCallback(async () => {
    const r = await call('/api/firewall/ftp-cancel', { method: 'POST', body: JSON.stringify({}) });
    toast('FTP', r.message);
  }, [call, toast]);

  const openPgFirewall = useCallback(async () => {
    const r = await call('/api/firewall/pg', { method: 'POST', body: JSON.stringify({}) });
    toast('Firewall PG', r.message, r.ok ? 'success' : 'danger');
  }, [call, toast]);

  const openSftpFirewall = useCallback(async () => {
    const r = await call('/api/firewall/sftp', { method: 'POST', body: JSON.stringify({}) });
    toast('Firewall SFTP', r.message, r.ok ? 'success' : 'danger');
  }, [call, toast]);

  return (
    <div>
      <Card title="Carpeta de almacenamiento local" sub="Crea y configura permisos en la carpeta destino" icon={<span>💾</span>}>
        <div className="row gap-8">
          <input className="input mono flex-1" value={storagePath} onChange={e => setStoragePath(e.target.value)} />
          <AsyncButton variant="primary" onClick={ensureStorage} runningText="Preparando…">📁 Asegurar carpeta</AsyncButton>
        </div>
      </Card>

      <Card title="SFTP / SSH" sub="Servidor OpenSSH + usuario restringido" icon={<span>🔐</span>}>
        <div className="grid-2 gap-8">
          <div className="form-row"><span className="form-label">Usuario</span><input className="input" value={sftpUser} onChange={e => setSftpUser(e.target.value)} /></div>
          <div className="form-row"><span className="form-label">Contraseña</span><input className="input" value={sftpPass} onChange={e => setSftpPass(e.target.value)} /></div>
        </div>
        <div className="btn-row">
          <AsyncButton variant="success" onClick={createSftpUser} runningText="Creando…" confirmText={`Crear usuario ${sftpUser} restringido a ${storagePath}?`}>👤 Crear/actualizar usuario SFTP</AsyncButton>
          <AsyncButton onClick={installOpenssh} runningText="Instalando…" confirmText="Instalar y arrancar servicio OpenSSH en el puerto 22?">🚀 Instalar OpenSSH</AsyncButton>
          <AsyncButton onClick={openSftpFirewall} runningText="Abriendo…">🔓 Abrir puerto 22 (firewall)</AsyncButton>
        </div>
      </Card>

      <Card title="Docker Stack Multi-Perfil (1-Clic)" sub="Levanta PostgreSQL 17 + MinIO S3 + Túnel FRP con resolución autónoma de puertos" icon={<span>🐳</span>}>
        {/* Selector de Perfil */}
        <div className="form-row mb-12">
          <span className="form-label" style={{ fontWeight: 600 }}>Perfil de Configuración</span>
          <select className="input" value={selectedProfile} onChange={e => handleProfileChange(e.target.value)}>
            {Object.entries(PROFILES_MAP).map(([k, v]) => (
              <option key={k} value={k}>{v.name}</option>
            ))}
          </select>
        </div>

        <div className="grid-2 gap-8 mb-8">
          <div className="form-row"><span className="form-label">Base de Datos PG</span><input className="input mono" value={pgDb} onChange={e => setPgDb(e.target.value)} /></div>
          <div className="form-row"><span className="form-label">Usuario PG</span><input className="input mono" value={pgUser} onChange={e => setPgUser(e.target.value)} /></div>
          <div className="form-row"><span className="form-label">Contraseña PG</span><input className="input mono" value={pgPass} onChange={e => setPgPass(e.target.value)} /></div>
          <div className="form-row"><span className="form-label">Usuario MinIO</span><input className="input mono" value={minioUser} onChange={e => setMinioUser(e.target.value)} /></div>
          <div className="form-row"><span className="form-label">Contraseña MinIO</span><input className="input mono" value={minioPass} onChange={e => setMinioPass(e.target.value)} /></div>
          <div className="form-row"><span className="form-label">IP VPS Túnel</span><input className="input mono" value={vpsIp} onChange={e => setVpsIp(e.target.value)} /></div>
        </div>

        {/* Configuración de Puertos del Anfitrión */}
        <div style={{ background: 'var(--bg-hover)', padding: 10, borderRadius: 'var(--radius-sm)', marginBottom: 12 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
            <span style={{ fontWeight: 600, fontSize: 12 }}>Puertos Anfitrión (Host) & Auto-Reparación:</span>
            <label style={{ display: 'flex', gap: 6, alignItems: 'center', fontSize: 12, cursor: 'pointer' }}>
              <input type="checkbox" checked={autoRemap} onChange={e => setAutoRemap(e.target.checked)} />
              <span>Auto-remapear si el puerto está ocupado (5432→5433, 9000→9002)</span>
            </label>
          </div>
          <div className="grid-3 gap-8">
            <div className="form-row"><span className="form-label">Host PG</span><input className="input mono fs-12" value={pgHostPort} onChange={e => setPgHostPort(e.target.value)} /></div>
            <div className="form-row"><span className="form-label">Host MinIO API</span><input className="input mono fs-12" value={minioHostPort} onChange={e => setMinioHostPort(e.target.value)} /></div>
            <div className="form-row"><span className="form-label">Host Consola</span><input className="input mono fs-12" value={minioConsoleHostPort} onChange={e => setMinioConsoleHostPort(e.target.value)} /></div>
          </div>
        </div>

        <div className="btn-row">
          <AsyncButton variant="primary" onClick={launchDocker} runningText="Generando e iniciando…" confirmText={`¿Generar stack con perfil ${selectedProfile} (BD: ${pgDb})?`}>
            🚀 Levantar Stack ({selectedProfile})
          </AsyncButton>
          <AsyncButton onClick={checkDocker} runningText="Comprobando…">🔍 Comprobar Docker</AsyncButton>
          {dockerInstalled !== null && <span className={`badge ${dockerInstalled ? 'ok' : 'warn'}`}>{dockerInstalled ? 'Docker detectado' : 'Docker NO encontrado'}</span>}
        </div>
        <div className="mt-8">
          <span className="muted fs-12">Genera dinámicamente docker-compose.yml y frpc.toml en C:\\facturapro_docker</span>
        </div>
      </Card>

      <Card title="Firewall de puertos" sub="PostgreSQL (5432) + FTP (21) temporal/permanente" icon={<span>🔥</span>}>
        <div className="grid-2 gap-8">
          <div className="form-row"><span className="form-label">FTP minutos</span><input className="input" value={ftpMinutes} onChange={e => setFtpMinutes(e.target.value)} /></div>
          <div className="form-row"><span className="form-label">FTP IP fila</span><input className="input mono" value={ftpIp} onChange={e => setFtpIp(e.target.value)} placeholder="(vacío = todos)" /></div>
        </div>
        <div className="btn-row">
          <AsyncButton variant="primary" onClick={openPgFirewall} runningText="Abriendo…">🔓 Abrir 5432 (PG)</AsyncButton>
          <AsyncButton variant="warning" onClick={openFtpTemp} runningText="Abriendo…" confirmText={`Abrir puerto 21 temporal por ${ftpMinutes} minutos`}>⏱ FTP temporal</AsyncButton>
          <AsyncButton onClick={openFtpPerm} runningText="Abriendo…" confirmText="Abrir puerto 21 permanente (restablece regla previa)">🔒 FTP permanente</AsyncButton>
          <AsyncButton variant="danger" onClick={cancelFtp} runningText="Cerrando…">🛑 Cerrar FTP</AsyncButton>
        </div>
      </Card>
    </div>
  );
}