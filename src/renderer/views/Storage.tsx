import React, { useState, useCallback } from 'react';
import { Card } from '../components/Card';
import { AsyncButton } from '../components/Button';

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
    const r = await call('/api/docker/launch', { method: 'POST', body: JSON.stringify({}) });
    toast('Docker', r.message, r.ok ? 'success' : 'danger');
  }, [call, toast]);

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

      <Card title="Docker (ún clic)" sub="Levanta PostgreSQL 17 + MinIO S3 + SFTPGo" icon={<span>🐳</span>}>
        <div className="btn-row">
          <AsyncButton variant="primary" onClick={launchDocker} runningText="Levantando contenedores…" confirmText="Se ejecutará docker compose up -d. ¿Continuar?">🚀 Levantar stack Docker</AsyncButton>
          <AsyncButton onClick={checkDocker} runningText="Comprobando…">🔍 Comprobar Docker</AsyncButton>
          {dockerInstalled !== null && <span className={`badge ${dockerInstalled ? 'ok' : 'warn'}`}>{dockerInstalled ? 'Docker detectado' : 'Docker NO encontrado'}</span>}
        </div>
        <div className="mt-8">
          <span className="muted fs-12">Comando manual: </span>
          <code className="mono fs-11">docker run -d -p 5432:5432 -e POSTGRES_PASSWORD=ClaveSegura123! --name pg17 postgres:17-alpine</code>
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
