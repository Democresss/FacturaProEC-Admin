/**
 * Servidor y túnel — deja la base de la empresa lista para FacturaPro (lo mismo que FacPro Servidor).
 *
 * Revisa Docker, PostgreSQL y MinIO (todos, para elegir), activa SSL, crea un usuario propio para
 * FacturaPro con clave segura, levanta el túnel bore con puerto fijo y lo vigila. Backend: /api/servidor/*.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Card } from '../components/Card';
import { AsyncButton } from '../components/Button';
import { Modal } from '../components/Modal';

type Call = (path: string, opts?: RequestInit) => Promise<any>;
type Toast = (title: string, body?: string, kind?: any) => void;

interface Contenedor { nombre: string; imagen: string; corriendo: boolean; creado?: string; puertos?: string; rol?: string; estado?: string;
                      motor?: string; host?: string; clave?: string }
interface MotorDocker { nombre: string; host: string; contenedores: number; elegido: boolean; sin_permiso?: boolean }
// «2024-05-01 12:00:00 -0500 -05» → «creado 2024-05-01»
const creado = (c: Contenedor) => c.creado ? ` · creado ${c.creado.slice(0, 10)}` : '';
const donde = (c: { motor?: string }) => c.motor ? ` · ${c.motor.replace(/ \(el de «sudo docker»\)/, '')}` : '';
const quien = (c: Contenedor) => `${c.nombre}${donde(c)} · ${c.corriendo ? 'encendido' : 'apagado'}${c.creado ? ' · creado ' + c.creado.slice(0, 10) : ''}`;
const ROL: Record<string, string> = { postgres: '🐘 PostgreSQL', minio: '🗄 MinIO', bore: '🔗 Túnel bore', otro: 'Otro' };
interface Base { nombre: string; dueno: string; tablas: number | null }
interface Tunel { contenedor: string; corriendo: boolean; puerto?: number; servicio?: string; en_linea?: boolean; ssl?: boolean | null;
                 motor?: string; host?: string }
const URL_ENLACE = 'https://facturadorproecuador.org/v2/conectar-bd#direccion';
interface LineaLog { hora: string; nivel: string; texto: string }
interface Servicio {
  id: string; tipo: string; nombre: string; detalle: string; corriendo: boolean; automatico: boolean | null;
  accion: string | null; contenedor?: string; pid?: number; instalado?: boolean; sin_enlace?: boolean;
}

const TEXTO_ACCION: Record<string, string> = {
  'automatico': 'Hacer automático', 'docker-al-arrancar': 'Encender con el equipo', 'vigilante': 'Instalar',
  'detener-suelto': 'Detener', 'app': 'Arrancar con la sesión', 'modo-admin': 'Activar (pide la clave una vez)',
};
const colorServicio = (s: Servicio) => s.automatico === null ? 'var(--text-muted)'
  : s.automatico && s.corriendo ? 'var(--success)' : s.automatico ? 'var(--warning)' : s.corriendo ? 'var(--warning)' : 'var(--danger)';

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
  const [servs, setServs] = useState<{ servicios: Servicio[]; todo_automatico: boolean } | null>(null);
  const [appAuto, setAppAuto] = useState<boolean | null>(null);
  const desde = useRef(0);

  const cargarServicios = useCallback(async () => {
    const r = await call('/api/servidor/servicios');
    if (r.ok) setServs(r.data);
    const ea = (window as any).electronAPI;
    if (ea?.autostart?.get) { try { setAppAuto(!!(await ea.autostart.get())); } catch { /* sin Electron */ } }
  }, [call]);

  // La lista se refresca sola (el vigilante deja su latido cada minuto)
  useEffect(() => {
    cargarServicios();
    const id = setInterval(cargarServicios, 30000);
    return () => clearInterval(id);
  }, [cargarServicios]);

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
        cargarServicios();
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
  // Túneles del Docker elegido y de los otros Docker del equipo (antes los de «sudo docker» no se veían)
  const tuneles: Tunel[] = [...(a?.bore?.contenedores || []), ...(a?.bore?.otros_docker || [])];
  const vig = a?.vigilante || {};

  const configurar = () => {
    const o: any = { minio, detener_bore_viejo: true };
    if (puerto.trim()) o.puerto = parseInt(puerto, 10);
    if (pgElegido) o.pg_contenedor = pgElegido;
    if (minio && (minioElegido || a?.minio?.clave || listaMinio[0])) o.minio_contenedor = minioElegido || a?.minio?.clave || listaMinio[0].nombre;
    if (pg.estado === 'contenedor' && bases.length) {
      o.base = base;
      if (claveBase) o.clave_base = claveBase;
      if (base !== NUEVA) o.usuario_propio = propio;
    }
    if (pg.estado === 'nativo') Object.assign(o, nativo);
    setResultado(null);
    return empezar('configurar', '/api/servidor/configurar', o);
  };

  const accionServicio = (accion: string, objetivo?: string | number, clave?: string) =>
    empezar('servicios', '/api/servidor/servicios/accion', { accion, objetivo: objetivo == null ? null : String(objetivo), clave: clave || null });

  // Linux sin Modo administrador: lo que necesita administrador pide la clave AQUÍ (la ventana de clave del sistema
  // y la terminal no funcionan por Escritorio remoto). Se usa una vez y no se guarda.
  const esLinux = String(a?.sistema?.so || '').startsWith('Linux');
  const adminActivo = (servs?.servicios || []).find(x => x.id === 'admin')?.automatico === true;
  const necesitaClave = (accion: string) => esLinux && !adminActivo &&
    (accion === 'modo-admin' || accion === 'docker-al-arrancar' ||
     (accion === 'todo' && (servs?.servicios || []).some(x => (x.accion === 'modo-admin' || x.accion === 'docker-al-arrancar'))));
  const [pidiendo, setPidiendo] = useState<{ accion: string; objetivo?: string | number } | null>(null);
  const [claveAdmin, setClaveAdmin] = useState('');
  const accionConClave = (accion: string, objetivo?: string | number) => {
    if (necesitaClave(accion)) { setClaveAdmin(''); setPidiendo({ accion, objetivo }); return; }
    return accionServicio(accion, objetivo);
  };
  const enviarClave = () => {
    if (!pidiendo || !claveAdmin) return;
    const { accion, objetivo } = pidiendo;
    const c = claveAdmin;
    setPidiendo(null);
    setClaveAdmin('');
    return accionServicio(accion, objetivo, c);
  };

  const appAutomatica = async () => {
    const ea = (window as any).electronAPI;
    if (!ea?.autostart?.set) return;
    const r = await ea.autostart.set(true);
    await call('/api/config', { method: 'POST', body: JSON.stringify({ data: { autostart: true } }) });
    toast('Arranque automático', r.message, r.ok ? 'success' : 'danger');
    cargarServicios();
  };

  const listaServicios: Servicio[] = [
    ...(servs?.servicios || []),
    ...(appAuto === null ? [] : [{
      id: 'app', tipo: 'app', nombre: 'FacPro Server Manager en segundo plano', corriendo: true, automatico: appAuto,
      accion: appAuto ? null : 'app',
      detalle: appAuto ? 'Arranca sola al iniciar sesión, en la bandeja: también vigila el túnel'
                       : 'No arranca sola: ábrela después de reiniciar (o instala el vigilante)',
    } as Servicio]),
  ];
  const todoAutomatico = !!servs?.todo_automatico && appAuto !== false;

  const hacerTodo = async () => {
    if (appAuto === false) await appAutomatica();
    await accionConClave('todo');
  };

  const motores: MotorDocker[] = dock.motores || [];
  const todos: Contenedor[] = a?.todos || [];
  const [verTodos, setVerTodos] = useState(false);
  const cambiarMotor = async (host: string) => {
    const r = await call('/api/servidor/motor', { method: 'POST', body: JSON.stringify({ host }) });
    toast('Docker', r.message, r.ok ? 'success' : 'danger');
    setPgElegido(''); setMinioElegido(''); setBase('');
    analizar();
    cargarServicios();
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
              {motores.length > 1 && (
                <div className="fs-12" style={{ marginTop: 4 }}>
                  {motores.map(m => (
                    <div key={m.host}>• {m.nombre}: {m.contenedores >= 0 ? `${m.contenedores} contenedores` : m.sin_permiso ? 'sin permiso' : 'no responde'}</div>
                  ))}
                  <div className="muted fs-11">Reviso todos a la vez: abajo ves todo junto.</div>
                </div>
              )}
              {motores.some(m => m.sin_permiso) && (
                <div className="fs-11" style={{ color: 'var(--warning)', marginTop: 4 }}>
                  Hay un Docker que tu usuario no puede ver (solo con «sudo»). Actívalo con «Modo administrador» en Servicios automáticos.
                </div>
              )}
              {!dock.instalado && <AsyncButton size="sm" variant="primary" onClick={() => empezar('instalar-docker', '/api/servidor/instalar-docker')}>Instalar Docker</AsyncButton>}
              {dock.instalado && !dock.corriendo && !dock.sin_permiso && <AsyncButton size="sm" variant="primary" onClick={() => empezar('encender-docker', '/api/servidor/encender-docker')}>Encender Docker</AsyncButton>}
            </div>
            <div className="stat-block">
              <div className="fw-700">🐘 PostgreSQL</div>
              <div className="fs-12 muted">
                {pg.estado === 'contenedor' ? `En Docker: ${pg.contenedor}${donde(pg)} · SSL ${pg.ssl === true ? 'activo' : pg.ssl === false ? 'apagado (se activa)' : '—'}`
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

      <Card title="Servicios automáticos" icon={<span>♻</span>}
            sub="Lo que tiene que levantarse solo para que FacturaPro nunca pierda tu base: tras un corte de luz, un reinicio o si algo se cae."
            right={<AsyncButton size="sm" onClick={cargarServicios}>↻</AsyncButton>}>
        {!servs && <div className="muted fs-12">Revisando servicios…</div>}
        {listaServicios.map(s => (
          <div key={s.id} className="row between items-center gap-8" style={{ padding: '8px 0', borderBottom: '1px solid var(--border)' }}>
            <div style={{ minWidth: 0 }}>
              <div className="fs-13 fw-700"><span style={{ color: colorServicio(s) }}>●</span> {s.nombre}</div>
              <div className="fs-12 muted">{s.detalle}</div>
            </div>
            <div className="row gap-4" style={{ flexShrink: 0 }}>
              {s.accion && (
                <AsyncButton size="sm" variant={s.accion === 'detener-suelto' ? 'danger' : 'primary'} disabled={!!tarea}
                             confirmText={s.accion === 'detener-suelto' ? 'Se detiene ese bore (lo que publica deja de verse desde internet).' : undefined}
                             onClick={() => s.accion === 'app' ? appAutomatica() : accionConClave(s.accion!, s.contenedor ?? s.pid)}>
                  {s.tipo === 'vigilante' && s.instalado ? 'Actualizar' : TEXTO_ACCION[s.accion] || s.accion}
                </AsyncButton>
              )}
              {s.tipo === 'vigilante' && s.instalado && (
                <AsyncButton size="sm" variant="danger" disabled={!!tarea}
                             confirmText="Si el túnel se cae con la app cerrada, nadie lo levantará solo."
                             onClick={() => accionServicio('quitar-vigilante')}>Quitar</AsyncButton>
              )}
            </div>
          </div>
        ))}
        {servs && (
          <div className="btn-row">
            <AsyncButton variant="success" disabled={!!tarea || todoAutomatico} onClick={hacerTodo}>
              {todoAutomatico ? '✓ Todo se levanta solo' : '♻ Hacer todo automático'}
            </AsyncButton>
          </div>
        )}
        {listaServicios.some(s => s.tipo === 'vigilante' && s.sin_enlace) && (
          <div className="fs-12" style={{ color: 'var(--warning)' }}>
            Falta el código de enlace (abajo): sin él, si bore.pub cambia el puerto, el vigilante lo levanta pero FacturaPro no se entera.
          </div>
        )}
      </Card>

      {a && dock.corriendo && (
        <Card title={`Contenedores en este equipo (${todos.length})`} icon={<span>🐳</span>}
              sub={motores.length > 1 ? 'De todos tus Docker, con sus puertos y de qué Docker es cada uno. Abajo eliges cuál PostgreSQL y cuál MinIO usa FacturaPro.'
                                      : 'Todo lo que tiene Docker, con sus puertos. Abajo eliges cuál PostgreSQL y cuál MinIO usa FacturaPro.'}
              right={todos.length > 6 ? <button className="btn btn-sm" onClick={() => setVerTodos(v => !v)}>{verTodos ? 'Ver menos' : 'Ver todos'}</button> : undefined}>
          {todos.length === 0 && <div className="muted fs-12">No hay contenedores en este Docker.</div>}
          {(verTodos ? todos : todos.slice(0, 6)).map(c => {
            const usado = !!c.clave && (c.clave === pg.clave || c.clave === a?.minio?.clave);
            return (
              <div key={c.clave || c.nombre} className="row between items-center gap-8" style={{ padding: '6px 0', borderBottom: '1px solid var(--border)' }}>
                <div style={{ minWidth: 0 }}>
                  <div className="fs-13"><span style={{ color: c.corriendo ? 'var(--success)' : 'var(--text-muted)' }}>●</span>{' '}
                    <b className="mono">{c.nombre}</b> <span className="muted fs-12">{c.imagen}</span></div>
                  <div className="fs-12 muted">{c.corriendo ? 'encendido' : (c.estado || 'apagado')}{c.puertos ? ` · puertos ${c.puertos}` : ' · sin puertos publicados'}{creado(c)}</div>
                </div>
                <div className="row gap-4" style={{ flexShrink: 0 }}>
                  {c.motor && <span className="badge neutral">{c.motor.replace(/ \(el de «sudo docker»\)/, '')}</span>}
                  {usado && <span className="badge ok">en uso</span>}
                  <span className={`badge ${c.rol === 'otro' ? 'neutral' : ''}`}>{ROL[c.rol || 'otro']}</span>
                </div>
              </div>
            );
          })}
        </Card>
      )}

      {tuneles.length > 0 && (
        <Card title="Túneles abiertos" sub="Lo que está publicado en internet. Cerrar un túnel no apaga el contenedor." icon={<span>🔗</span>}>
          {tuneles.map(t => (
            <div key={t.contenedor} className="row between items-center" style={{ padding: '6px 0' }}>
              <span className="mono fs-12">{t.contenedor}: bore.pub:{t.puerto || '?'} → {t.servicio} · {t.corriendo ? estadoTunel(t) : 'apagado'}
                {t.motor ? <span className="badge neutral" style={{ marginLeft: 6 }}>en {t.motor}</span> : null}</span>
              <AsyncButton size="sm" variant="danger" confirmText={`El túnel «${t.contenedor}» dejará de verse desde internet.`}
                           onClick={() => empezar('cerrar-tunel', '/api/servidor/cerrar-tunel', { nombre: t.contenedor, host: t.host || null })}>Cerrar túnel</AsyncButton>
            </div>
          ))}
        </Card>
      )}

      {a && dock.corriendo && (
        <Card title="¿Qué configuro?" icon={<span>⚙</span>}>
          {listaPg.length > 0 && (
            <div className="form-row">
              <label className="form-label">PostgreSQL que usará FacturaPro ({listaPg.length} encontrado{listaPg.length === 1 ? '' : 's'})</label>
              {listaPg.length > 1 && (
                <div className="fs-12" style={{ marginBottom: 6, padding: 8, borderRadius: 8, background: 'var(--primary-faint)' }}>
                  Encontré {listaPg.length}. Uso <b>{quien(listaPg.find(c => c.clave === pg.clave) || listaPg[0])}</b>.
                  {listaPg.filter(c => c.clave !== pg.clave).map(c => (
                    <div key={c.clave} className="row between items-center" style={{ marginTop: 4 }}>
                      <span>¿Usar <b>{quien(c)}</b>?</span>
                      <button className="btn btn-sm" onClick={() => { setPgElegido(c.clave || c.nombre); setBase(''); analizar(c.clave || c.nombre, minioElegido || undefined); }}>Usar este</button>
                    </div>
                  ))}
                </div>
              )}
              <select className="input" value={pgElegido || pg.clave || pg.contenedor}
                      onChange={e => { setPgElegido(e.target.value); setBase(''); analizar(e.target.value, minioElegido || undefined); }}>
                {listaPg.map(c => <option key={c.clave || c.nombre} value={c.clave || c.nombre}>{c.nombre}{donde(c)} — {c.imagen}{c.puertos ? ' · ' + c.puertos : ''}{creado(c)}{c.corriendo ? '' : ' (apagado)'}</option>)}
              </select>
              {pg.estado === 'contenedor' && (
                <div className="fs-12" style={{ marginTop: 4, color: pideClave ? 'var(--warning)' : 'var(--success)' }}>
                  {pideClave
                    ? `🔑 La base «${baseSel?.nombre}» es de «${baseSel?.dueno}»: escribe su clave abajo (solo se usa en este equipo).`
                    : `🔑 Usuario «${pg.usuario}» y su clave: los leo del contenedor. No tienes que escribir nada.`}
                </div>
              )}
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
          {listaMinio.length > 0 && (
            <div className="form-row">
              <label className="form-label">MinIO ({listaMinio.length} encontrado{listaMinio.length === 1 ? '' : 's'}){minio ? ': ¿cuál publico?' : ''}</label>
              {listaMinio.length > 1 && (
                <div className="fs-12" style={{ marginBottom: 6, padding: 8, borderRadius: 8, background: 'var(--primary-faint)' }}>
                  Encontré {listaMinio.length}. Uso <b>{quien(listaMinio.find(c => c.clave === a?.minio?.clave) || listaMinio[0])}</b>.
                  {listaMinio.filter(c => c.clave !== a?.minio?.clave).map(c => (
                    <div key={c.clave} className="row between items-center" style={{ marginTop: 4 }}>
                      <span>¿Usar <b>{quien(c)}</b>?</span>
                      <button className="btn btn-sm" onClick={() => { setMinioElegido(c.clave || c.nombre); analizar(pgElegido || undefined, c.clave || c.nombre); }}>Usar este</button>
                    </div>
                  ))}
                </div>
              )}
              <select className="input" value={minioElegido || a?.minio?.clave || listaMinio[0].nombre}
                      onChange={e => { setMinioElegido(e.target.value); analizar(pgElegido || undefined, e.target.value); }}>
                {listaMinio.map(c => <option key={c.clave || c.nombre} value={c.clave || c.nombre}>{c.nombre}{donde(c)} — {c.imagen}{c.puertos ? ' · ' + c.puertos : ''}{creado(c)}{c.corriendo ? '' : ' (apagado)'}</option>)}
              </select>
              {a?.minio?.estado === 'contenedor' && (
                <div className="fs-12" style={{ marginTop: 4, color: a.minio.tiene_clave ? 'var(--success)' : 'var(--warning)' }}>
                  {a.minio.tiene_clave
                    ? `🔑 Usuario «${a.minio.usuario}» y su clave: los leo del contenedor. No tienes que escribir nada.`
                    : '🔑 Este MinIO no tiene su usuario y clave en la configuración del contenedor: usa la que pusiste al crearlo.'}
                </div>
              )}
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
          {vig.problema && (
            <div className="fs-12" style={{ margin: '8px 0', color: 'var(--danger)' }}>⚠ {vig.problema}</div>
          )}
          {(!vig.enlace || vig.problema) && (
            <div className="fs-12" style={{ margin: '10px 0', padding: 10, borderRadius: 8, background: 'var(--warning-faint)' }}>
              <div className="fw-700" style={{ marginBottom: 4 }}>Cómo sacar el código de enlace (una sola vez)</div>
              <ol style={{ margin: '0 0 8px', paddingLeft: 18 }}>
                <li>Abre FacturaPro con tu usuario administrador → <b>Conecta tu base de datos</b> → <b>Dirección de tu base</b>.</li>
                <li>Pulsa <b>Generar código de enlace</b> y cópialo (empieza con <span className="mono">FPENLACE.</span>).</li>
                <li>Pégalo arriba y pulsa <b>Guardar</b>. Listo: si bore.pub cambia el puerto, FacturaPro se entera solo.</li>
              </ol>
              <button className="btn btn-sm btn-primary" onClick={() => (window as any).electronAPI?.openExternal?.(URL_ENLACE)}>
                Abrir FacturaPro → Conecta tu base de datos
              </button>
              <div className="fs-11 muted" style={{ marginTop: 6 }}>
                Si en esa página no aparece «Dirección de tu base», FacturaPro todavía no tiene la versión nueva: mientras tanto, cambia la
                dirección a mano ahí mismo{a?.config?.bore_puerto_pg ? ` (bore.pub:${a.config.bore_puerto_pg})` : ''}.
              </div>
            </div>
          )}
          <div className="fs-12" style={{ margin: '8px 0', color: vig.enlace && vig.instalado ? '#22c55e' : '#f59e0b' }}>
            {vig.enlace ? (vig.problema ? `✖ Enlazado con ${vig.facturapro}, pero no se llega` : `✓ Enlazado con ${vig.facturapro}`) : 'Sin enlace: si cambia el puerto tendrás que cambiarlo a mano en FacturaPro'}
            {' · '}{vig.instalado ? 'vigilante instalado' : 'vigilante no instalado'}
            {vig.informado ? ` · último aviso ${vig.informado} (puerto ${vig.puerto_informado})` : ''}
          </div>
          <div className="btn-row">
            <AsyncButton variant="success" disabled={!!tarea} onClick={() => empezar('vigilante', '/api/servidor/vigilante')}>Vigilar siempre (arranca con el equipo)</AsyncButton>
            <AsyncButton disabled={!!tarea} onClick={() => empezar('avisar', '/api/servidor/avisar')}>Avisar la dirección a FacturaPro ahora</AsyncButton>
          </div>
        </Card>
      )}

      <Modal open={!!pidiendo} title="Clave de administrador" onClose={() => { setPidiendo(null); setClaveAdmin(''); }} maxWidth={440}
             footer={<>
               <button className="btn" onClick={() => { setPidiendo(null); setClaveAdmin(''); }}>Cancelar</button>
               <button className="btn btn-primary" disabled={!claveAdmin} onClick={enviarClave}>Continuar</button>
             </>}>
        <div className="fs-13" style={{ marginBottom: 10 }}>
          Escribe la clave de tu usuario de Linux (la misma de «sudo»). Se usa <b>una sola vez</b> para dar los permisos y
          <b> no se guarda</b>. Con el Modo administrador activo, la app no la vuelve a pedir.
        </div>
        <input className="input" type="password" autoFocus value={claveAdmin} onChange={e => setClaveAdmin(e.target.value)}
               onKeyDown={e => { if (e.key === 'Enter') enviarClave(); }} />
      </Modal>

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
