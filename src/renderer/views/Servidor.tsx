/**
 * Servidor y túnel — deja la base de la empresa lista para FacturaPro (lo mismo que FacPro Servidor).
 *
 * Revisa Docker, PostgreSQL y MinIO (todos, para elegir), activa SSL, crea un usuario propio para
 * FacturaPro con clave segura, levanta el túnel bore con puerto fijo y lo vigila. Backend: /api/servidor/*.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Card } from '../components/Card';
import { AsyncButton } from '../components/Button';

type Call = (path: string, opts?: RequestInit) => Promise<any>;
type Toast = (title: string, body?: string, kind?: any) => void;

interface Contenedor { nombre: string; imagen: string; corriendo: boolean; creado?: string }
interface Base { nombre: string; dueno: string; tablas: number | null }
interface Tunel { contenedor: string; corriendo: boolean; puerto?: number; servicio?: string; en_linea?: boolean; ssl?: boolean | null }
interface LineaLog { hora: string; nivel: string; texto: string }

const COLOR: Record<string, string> = { ok: '#22c55e', error: '#ef4444', aviso: '#f59e0b', paso: '#38bdf8' };
const NUEVA = '__nueva__';

export function ServidorView({ call, toast }: { call: Call; toast: Toast }) {
  const [a, setA] = useState<any>(null);
  const [cargando, setCargando] = useState(false);
  const [pgElegido, setPgElegido] = useState<string>('');
  const [minioElegido, setMinioElegido] = useState<string>('');
  const [base, setBase] = useState<string>('');
  const [claveBase, setClaveBase] = useState('');
  const [puerto, setPuerto] = useState('');
  const [minio, setMinio] = useState(false);
  const [propio, setPropio] = useState(true);
  const [nativo, setNativo] = useState({ pg_usuario: 'postgres', pg_clave: '', pg_base: 'facturapro' });
  const [log, setLog] = useState<LineaLog[]>([]);
  const [tarea, setTarea] = useState<string>('');
  const [resultado, setResultado] = useState<any>(null);
  const [verClave, setVerClave] = useState(false);
  const [enlace, setEnlace] = useState('');
  const desde = useRef(0);

  const analizar = useCallback(async (pg?: string, mi?: string) => {
    setCargando(true);
    const q = new URLSearchParams();
    if (pg) q.set('pg', pg);
    if (mi) q.set('minio', mi);
    const r = await call('/api/servidor/analizar' + (q.toString() ? '?' + q : ''));
    setCargando(false);
    if (!r.ok) { toast('Servidor', r.message, 'danger'); return; }
    const d = r.data;
    setA(d);
    const bases: Base[] = d.postgres?.bases || [];
    setBase(prev => (prev && (prev === NUEVA || bases.some(b => b.nombre === prev))) ? prev : (bases[0]?.nombre || NUEVA));
    const previo = (d.bore?.contenedores || []).find((t: Tunel) => t.puerto)?.puerto || d.config?.bore_puerto_pg;
    setPuerto(p => p || (previo ? String(previo) : ''));
  }, [call, toast]);

  useEffect(() => { analizar(); }, []);

  // Avance de la tarea en curso (registro)
  useEffect(() => {
    if (!tarea) return;
    const id = setInterval(async () => {
      const r = await call('/api/servidor/progreso?desde=' + desde.current);
      if (!r.ok) return;
      desde.current = r.total;
      if (r.log?.length) setLog(l => [...l, ...r.log].slice(-300));
      if (!r.corriendo) {
        clearInterval(id);
        const nombre = tarea;
        setTarea('');
        if (r.error) toast('No se pudo terminar', r.error, 'danger');
        else if (nombre === 'configurar' && r.resultado) { setResultado(r.resultado); toast('¡Listo!', 'Tu base está en línea', 'success'); }
        analizar(pgElegido || undefined, minioElegido || undefined);
      }
    }, 700);
    return () => clearInterval(id);
  }, [tarea]);

  const empezar = async (nombre: string, ruta: string, cuerpo: any = {}) => {
    const r = await call(ruta, { method: 'POST', body: JSON.stringify(cuerpo) });
    if (!r.ok) { toast('Servidor', r.message, 'danger'); return; }
    setTarea(nombre);
  };

  const pg = a?.postgres || {};
  const dock = a?.docker || {};
  const bases: Base[] = pg.bases || [];
  const baseSel = bases.find(b => b.nombre === base);
  const pideClave = !!baseSel && (baseSel.dueno !== pg.usuario || !pg.tiene_clave);
  const listaPg: Contenedor[] = pg.contenedores || [];
  const listaMinio: Contenedor[] = a?.minio?.contenedores || [];
  const tuneles: Tunel[] = a?.bore?.contenedores || [];
  const vig = a?.vigilante || {};

  const configurar = () => {
    const o: any = { minio, detener_bore_viejo: true };
    if (puerto.trim()) o.puerto = parseInt(puerto, 10);
    if (pgElegido) o.pg_contenedor = pgElegido;
    if (minio && (minioElegido || listaMinio[0])) o.minio_contenedor = minioElegido || listaMinio[0].nombre;
    if (pg.estado === 'contenedor' && bases.length) {
      o.base = base;
      if (claveBase) o.clave_base = claveBase;
      if (base !== NUEVA) o.usuario_propio = propio;
    }
    if (pg.estado === 'nativo') Object.assign(o, nativo);
    setResultado(null);
    return empezar('configurar', '/api/servidor/configurar', o);
  };

  const estadoTunel = (t: Tunel) => !t.puerto ? 'sin puerto' : !t.en_linea ? 'no responde'
    : t.ssl === true ? 'en línea con SSL' : t.ssl === false ? 'en línea SIN SSL' : 'en línea';

  const url: string = resultado?.url || '';
  const urlOculta = url.replace(/:\/\/([^:]+):([^@]+)@/, '://$1:••••••••@');

  return (
    <div>
      <Card title="Servidor y túnel" icon={<span>🛰</span>}
            sub="Tu base de datos en este equipo, lista para FacturaPro por internet: SSL, usuario propio, túnel bore con puerto fijo y vigilante."
            right={<AsyncButton size="sm" onClick={() => analizar(pgElegido || undefined, minioElegido || undefined)}>↻ Revisar</AsyncButton>}>
        {!a && <div className="muted">{cargando ? 'Revisando Docker, PostgreSQL, MinIO y el túnel…' : 'Sin datos todavía.'}</div>}
        {a && (
          <div className="grid-3">
            <div className="stat-block">
              <div className="fw-700">🐳 Docker</div>
              <div className="fs-12 muted">
                {dock.sin_permiso ? 'Tu usuario no tiene permiso para usar Docker'
                  : dock.corriendo ? `Encendido · ${dock.version}${dock.motor ? ' · ' + dock.motor : ''}`
                  : dock.instalado ? 'Instalado pero apagado' : 'No está instalado'}
              </div>
              {!dock.instalado && <AsyncButton size="sm" variant="primary" onClick={() => empezar('instalar-docker', '/api/servidor/instalar-docker')}>Instalar Docker</AsyncButton>}
              {dock.instalado && !dock.corriendo && !dock.sin_permiso && <AsyncButton size="sm" variant="primary" onClick={() => empezar('encender-docker', '/api/servidor/encender-docker')}>Encender Docker</AsyncButton>}
            </div>
            <div className="stat-block">
              <div className="fw-700">🐘 PostgreSQL</div>
              <div className="fs-12 muted">
                {pg.estado === 'contenedor' ? `En Docker: ${pg.contenedor} · SSL ${pg.ssl === true ? 'activo' : pg.ssl === false ? 'apagado (se activa)' : '—'}`
                  : pg.estado === 'nativo' ? 'Instalado en el equipo (puerto 5432)'
                  : pg.estado === 'no' ? 'No existe: se crea en Docker con clave segura' : 'Se revisa con Docker encendido'}
              </div>
            </div>
            <div className="stat-block">
              <div className="fw-700">🌐 Internet</div>
              <div className="fs-12 muted">{a.internet?.bore_pub ? 'bore.pub responde' : 'No se llega a bore.pub'}</div>
              {a.conexion && <div className="fs-12" style={{ color: a.conexion.en_linea ? '#22c55e' : '#ef4444' }}>
                {a.conexion.en_linea ? 'Tu base responde desde internet con SSL' : 'Configurada pero no responde ahora'}</div>}
            </div>
          </div>
        )}
      </Card>

      {tuneles.length > 0 && (
        <Card title="Túneles abiertos" sub="Lo que está publicado en internet. Cerrar un túnel no apaga el contenedor." icon={<span>🔗</span>}>
          {tuneles.map(t => (
            <div key={t.contenedor} className="row between items-center" style={{ padding: '6px 0' }}>
              <span className="mono fs-12">{t.contenedor}: bore.pub:{t.puerto || '?'} → {t.servicio} · {t.corriendo ? estadoTunel(t) : 'apagado'}</span>
              <AsyncButton size="sm" variant="danger" confirmText={`El túnel «${t.contenedor}» dejará de verse desde internet.`}
                           onClick={() => empezar('cerrar-tunel', '/api/servidor/cerrar-tunel', { nombre: t.contenedor })}>Cerrar túnel</AsyncButton>
            </div>
          ))}
        </Card>
      )}

      {a && dock.corriendo && (
        <Card title="¿Qué configuro?" icon={<span>⚙</span>}>
          {listaPg.length > 1 && (
            <div className="form-row">
              <label className="form-label">PostgreSQL que usará FacturaPro</label>
              <select className="input" value={pgElegido || pg.contenedor}
                      onChange={e => { setPgElegido(e.target.value); setBase(''); analizar(e.target.value, minioElegido || undefined); }}>
                {listaPg.map(c => <option key={c.nombre} value={c.nombre}>{c.nombre} — {c.imagen}{c.corriendo ? '' : ' (apagado)'}</option>)}
              </select>
            </div>
          )}
          {pg.estado === 'contenedor' && bases.length > 0 && (
            <div className="form-row">
              <label className="form-label">Base de datos</label>
              <select className="input" value={base} onChange={e => setBase(e.target.value)}>
                {bases.map(b => <option key={b.nombre} value={b.nombre}>{b.nombre} — {b.tablas ?? '?'} tablas (dueño {b.dueno})</option>)}
                <option value={NUEVA}>➕ Crear base nueva «facturapro»</option>
              </select>
            </div>
          )}
          {pideClave && (
            <div className="form-row">
              <label className="form-label">Clave del usuario «{baseSel?.dueno}» (solo se usa en este equipo)</label>
              <input className="input" type="password" value={claveBase} onChange={e => setClaveBase(e.target.value)} />
            </div>
          )}
          {pg.estado === 'nativo' && (
            <div className="grid-3">
              {(['pg_usuario', 'pg_clave', 'pg_base'] as const).map(k => (
                <div key={k} className="form-row">
                  <label className="form-label">{k === 'pg_usuario' ? 'Usuario' : k === 'pg_clave' ? 'Clave' : 'Base'}</label>
                  <input className="input" type={k === 'pg_clave' ? 'password' : 'text'} value={(nativo as any)[k]}
                         onChange={e => setNativo({ ...nativo, [k]: e.target.value })} />
                </div>
              ))}
            </div>
          )}
          {pg.estado === 'contenedor' && base !== NUEVA && bases.length > 0 && (
            <label className="row items-center gap-4 fs-13" style={{ margin: '8px 0' }}>
              <input type="checkbox" checked={propio} onChange={e => setPropio(e.target.checked)} />
              <span><b>Usuario propio para FacturaPro</b> (recomendado): clave segura, sin superusuario, y por el túnel solo entra
                ese usuario y solo a esta base. Tu usuario actual queda bloqueado desde internet y su clave no cambia.</span>
            </label>
          )}
          <div className="form-row">
            <label className="form-label">Puerto fijo en bore.pub (vacío = automático)</label>
            <input className="input" style={{ maxWidth: 160 }} inputMode="numeric" value={puerto} onChange={e => setPuerto(e.target.value.replace(/\D/g, ''))} />
            <div className="fs-11 muted">Si ya usabas un puerto (por ejemplo 65300), déjalo para no cambiar la dirección en FacturaPro.</div>
          </div>
          <label className="row items-center gap-4 fs-13" style={{ margin: '8px 0' }}>
            <input type="checkbox" checked={minio} onChange={e => setMinio(e.target.checked)} />
            <span>Publicar también MinIO (opcional: tus archivos ya se guardan en tu base)</span>
          </label>
          {minio && listaMinio.length > 1 && (
            <div className="form-row">
              <label className="form-label">¿Qué MinIO publico?</label>
              <select className="input" value={minioElegido || listaMinio[0].nombre} onChange={e => setMinioElegido(e.target.value)}>
                {listaMinio.map(c => <option key={c.nombre} value={c.nombre}>{c.nombre} — {c.imagen}{c.corriendo ? '' : ' (apagado)'}</option>)}
              </select>
            </div>
          )}
          <div className="btn-row">
            <AsyncButton variant="success" disabled={!!tarea} onClick={configurar}>{tarea === 'configurar' ? 'Configurando…' : 'Configurar todo'}</AsyncButton>
          </div>
        </Card>
      )}

      {url && (
        <Card title="✔ ¡Listo! Tu base está en línea" icon={<span>🎉</span>}
              sub="Cópiala y pégala en FacturaPro → Conecta tu base de datos → «Probar conexión» y «Guardar y activar». Lleva la clave: por eso está oculta.">
          <div className="row gap-4 items-center">
            <input className="input mono flex-1" readOnly value={verClave ? url : urlOculta} />
            <button className="btn btn-sm" onClick={() => setVerClave(v => !v)}>{verClave ? 'Ocultar' : 'Mostrar'}</button>
            <AsyncButton size="sm" variant="primary" onClick={async () => { await navigator.clipboard.writeText(url); toast('Copiada', 'Pégala en FacturaPro', 'success'); }}>Copiar</AsyncButton>
          </div>
        </Card>
      )}

      {a && (
        <Card title="Que se arregle solo" icon={<span>🛡</span>}
              sub="Si bore.pub le da otro puerto al túnel, el vigilante lo levanta de nuevo y se lo avisa a FacturaPro con el código de enlace (FacturaPro → Conecta tu base de datos → Dirección de tu base → Generar código).">
          <div className="row gap-4 items-center">
            <input className="input mono flex-1" placeholder="FPENLACE.…" value={enlace} onChange={e => setEnlace(e.target.value)} />
            <AsyncButton size="sm" disabled={!enlace.trim()} onClick={async () => {
              const r = await call('/api/servidor/enlace', { method: 'POST', body: JSON.stringify({ codigo: enlace.trim() }) });
              toast('Enlace con FacturaPro', r.message, r.ok ? 'success' : 'danger');
              if (r.ok) { setEnlace(''); analizar(pgElegido || undefined, minioElegido || undefined); }
            }}>Guardar</AsyncButton>
          </div>
          <div className="fs-12" style={{ margin: '8px 0', color: vig.enlace && vig.instalado ? '#22c55e' : '#f59e0b' }}>
            {vig.enlace ? `✓ Enlazado con ${vig.facturapro}` : 'Sin enlace: si cambia el puerto tendrás que cambiarlo a mano en FacturaPro'}
            {' · '}{vig.instalado ? 'vigilante instalado' : 'vigilante no instalado'}
            {vig.informado ? ` · último aviso ${vig.informado} (puerto ${vig.puerto_informado})` : ''}
          </div>
          <div className="btn-row">
            <AsyncButton variant="success" disabled={!!tarea} onClick={() => empezar('vigilante', '/api/servidor/vigilante')}>Vigilar siempre (arranca con el equipo)</AsyncButton>
            <AsyncButton disabled={!!tarea} onClick={() => empezar('avisar', '/api/servidor/avisar')}>Avisar la dirección a FacturaPro ahora</AsyncButton>
          </div>
        </Card>
      )}

      <Card title="Registro" icon={<span>📜</span>} right={tarea ? <span className="badge">{tarea}…</span> : undefined}>
        <div className="log-box" style={{ maxHeight: 260, overflow: 'auto' }}>
          {log.length === 0 && <div className="muted fs-12">Aquí aparece lo que va haciendo.</div>}
          {log.map((l, i) => (
            <div key={i} className="log-line mono fs-12" style={{ color: COLOR[l.nivel] }}>{l.hora}  {l.texto}</div>
          ))}
        </div>
      </Card>
    </div>
  );
}
