/**
 * Cifrado: las claves que guarda la app (cifradas con tu usuario del sistema) y el SSL de tu base y del túnel.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { Card } from './Card';
import { AsyncButton } from './Button';

type Call = (path: string, opts?: RequestInit) => Promise<any>;

const VERDE = '#22c55e', ROJO = '#ef4444', AMBAR = '#f59e0b';

export function CifradoCard({ call }: { call: Call }) {
  const [claves, setClaves] = useState<any>(null);
  const [ssl, setSsl] = useState<any>(null);

  const cargarClaves = useCallback(async () => {
    const r = await call('/api/security/cifrado');
    if (r.ok) setClaves(r);
  }, [call]);

  const revisarSsl = useCallback(async () => {
    const r = await call('/api/servidor/analizar');
    if (r.ok) setSsl(r.data);
  }, [call]);

  useEffect(() => { cargarClaves(); }, []);

  const pg = ssl?.postgres || {};
  const tuneles: any[] = ssl?.bore?.contenedores || [];

  return (
    <Card title="Cifrado" icon={<span>🔐</span>}
          sub="Las claves que guarda esta app y el SSL con el que viajan tus datos por internet.">
      <div className="grid-2">
        <div className="stat-block">
          <div className="fw-700">Claves guardadas</div>
          {!claves && <div className="fs-12 muted">Revisando…</div>}
          {claves && (
            <>
              <div className="fs-12" style={{ color: claves.en_claro ? ROJO : VERDE }}>
                {claves.en_claro ? `${claves.en_claro} clave(s) sin cifrar` : `✓ ${claves.cifradas} clave(s) cifrada(s)`}
              </div>
              <div className="fs-11 muted">Con: {claves.metodo}. Solo tu usuario de este equipo puede leerlas; si alguien copia
                el archivo a otra cuenta o PC, no las puede abrir.</div>
              <div className="fs-11 muted">La clave de la base para FacturaPro no se guarda aquí: se muestra una vez al configurar
                y FacturaPro la guarda cifrada.</div>
            </>
          )}
        </div>
        <div className="stat-block">
          <div className="row between items-center">
            <span className="fw-700">SSL de tu base</span>
            <AsyncButton size="sm" onClick={revisarSsl}>Revisar SSL</AsyncButton>
          </div>
          {!ssl && <div className="fs-12 muted">Pulsa «Revisar SSL».</div>}
          {ssl && (
            <>
              <div className="fs-12" style={{ color: pg.ssl === true ? VERDE : pg.ssl === false ? ROJO : AMBAR }}>
                PostgreSQL{pg.contenedor ? ` (${pg.contenedor})` : ''}: {pg.ssl === true ? '✓ SSL activo'
                  : pg.ssl === false ? 'SSL apagado → actívalo en «Servidor y túnel» → Configurar todo' : 'no se pudo revisar'}
              </div>
              {tuneles.map(t => (
                <div key={t.contenedor} className="fs-12" style={{ color: t.ssl === true ? VERDE : t.ssl === false ? ROJO : AMBAR }}>
                  Túnel bore.pub:{t.puerto || '?'} ({t.servicio}): {t.ssl === true ? '✓ viaja cifrado'
                    : t.ssl === false ? 'SIN cifrar' : t.en_linea ? 'en línea' : 'no responde'}
                </div>
              ))}
              {ssl.conexion && (
                <div className="fs-12" style={{ color: ssl.conexion.en_linea ? VERDE : ROJO }}>
                  {ssl.conexion.en_linea ? '✓ Desde internet tu base responde con SSL' : 'Desde internet tu base no responde ahora'}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </Card>
  );
}
