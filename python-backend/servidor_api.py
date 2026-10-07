"""
Servidor y túnel: deja la base de la empresa lista para FacturaPro (lo mismo que FacPro Servidor).

Reutiliza servidor/facpro_servidor.py (copia de FacProV2/herramientas/facpro_servidor, se sincroniza con
`npm run sync`): detecta Docker, PostgreSQL y MinIO (todos, para elegir), activa SSL, crea un usuario propio
para FacturaPro, levanta el túnel bore con puerto fijo, lo vigila y avisa a FacturaPro si cambia el puerto.

Las tareas largas corren en un hilo; la pantalla pide el avance en /api/servidor/progreso.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter
from pydantic import BaseModel

_AQUI = Path(__file__).resolve().parent / "servidor"
if str(_AQUI) not in sys.path:
    sys.path.insert(0, str(_AQUI))

import facpro_servidor as fs  # noqa: E402

router = APIRouter(prefix="/api/servidor", tags=["Servidor y túnel"])


class Configurar(BaseModel):
    base: Optional[str] = None
    clave_base: Optional[str] = None
    puerto: Optional[int] = None
    minio: bool = False
    pg_contenedor: Optional[str] = None
    minio_contenedor: Optional[str] = None
    usuario_propio: bool = True
    detener_bore_viejo: bool = True
    pg_usuario: Optional[str] = None
    pg_clave: Optional[str] = None
    pg_base: Optional[str] = None
    pg_puerto: Optional[int] = None


class Codigo(BaseModel):
    codigo: str


class Motor(BaseModel):
    host: str = ""


class Paquete(BaseModel):
    ruta: str
    con_clave: bool = False   # sin ayudante: pedir la clave (ventana del sistema o terminal) en una tarea
    clave: Optional[str] = None   # o la clave escrita en el aviso de actualización (no se guarda)


class Nombre(BaseModel):
    nombre: str
    host: Optional[str] = None   # túnel en otro Docker del equipo


class Accion(BaseModel):
    accion: str
    objetivo: Optional[str] = None
    clave: Optional[str] = None   # Linux: clave de administrador escrita en la app (solo se usa ahora, no se guarda)


ACCIONES = ("todo", "automatico", "docker-al-arrancar", "vigilante", "quitar-vigilante", "detener-suelto", "modo-admin")


def _pedir_admin(clave: Optional[str] = None):
    """Lo que necesita administrador se repite como administrador: en Linux con la clave escrita en la app (sudo) o,
    sin ella, el ayudante / la ventana de clave del sistema; en Windows con la ventana de permiso de Windows."""
    if clave:
        return lambda bandera: fs._abrir_como_admin(bandera, clave=clave)
    return fs._abrir_como_admin


def _sin_claves(resultado: Any) -> Any:
    """La dirección con la clave solo sale en el resultado de «configurar» (para copiarla); nunca en el análisis."""
    if isinstance(resultado, dict) and isinstance(resultado.get("conexion"), dict):
        resultado = dict(resultado, conexion={k: v for k, v in resultado["conexion"].items() if k != "url"})
    return resultado


@router.get("/analizar")
def analizar(pg: Optional[str] = None, minio: Optional[str] = None) -> Dict[str, Any]:
    try:
        return {"ok": True, "data": _sin_claves(fs.analizar(pg, minio))}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "message": "No se pudo revisar el equipo: %s" % e}


def _tarea(nombre: str, funcion, *args) -> Dict[str, Any]:
    if fs.ESTADO["corriendo"]:
        return {"ok": False, "message": "Ya hay una tarea en curso (%s). Espera a que termine." % fs.ESTADO["tarea"]}
    fs._en_hilo(nombre, funcion, *args)
    return {"ok": True, "message": "En curso"}


@router.post("/configurar")
def configurar(o: Configurar) -> Dict[str, Any]:
    opciones = {k: v for k, v in o.model_dump().items() if v not in (None, "")}
    return _tarea("configurar", fs.configurar, opciones)


@router.post("/motor")
def motor(m: Motor) -> Dict[str, Any]:
    """Cuando el equipo tiene más de un Docker (el del sistema, Docker Desktop, sin root): cuál usar."""
    try:
        return dict(fs.usar_motor(m.host), message="Docker cambiado")
    except RuntimeError as e:
        return {"ok": False, "message": str(e)}


@router.get("/ayudante")
def ayudante() -> Dict[str, Any]:
    """¿Está el ayudante con permisos de Linux (Modo administrador)?"""
    return {"ok": True, "disponible": fs.ayudante_disponible()}


@router.post("/instalar-actualizacion")
def instalar_actualizacion(p: Paquete) -> Dict[str, Any]:
    """Linux: la actualización descargada (.deb/.rpm) la instala el ayudante, sin pedir la clave."""
    if not fs.ayudante_disponible():
        if p.con_clave:
            r = _tarea("actualizar", fs.instalar_actualizacion_con_clave, p.ruta, p.clave or None)
            return dict(r, en_curso=bool(r.get("ok")))
        return {"ok": False, "sin_ayudante": True, "message": "Sin Modo administrador: se pedirá la clave del sistema."}
    r = fs.ayudante({"orden": "instalar-paquete", "ruta": p.ruta})
    return {"ok": bool(r.get("ok")), "message": r.get("error") or "Actualización instalada"}


@router.post("/instalar-docker")
def instalar_docker() -> Dict[str, Any]:
    return _tarea("instalar-docker", fs._instalar_docker_ui)


@router.post("/encender-docker")
def encender_docker() -> Dict[str, Any]:
    return _tarea("encender-docker", lambda: fs.iniciar_docker(manual=True))


@router.post("/cerrar-tunel")
def cerrar_tunel(n: Nombre) -> Dict[str, Any]:
    return _tarea("cerrar-tunel", fs.cerrar_tunel, n.nombre, n.host or None)


@router.get("/progreso")
def progreso(desde: int = 0) -> Dict[str, Any]:
    with fs._candado_log:
        nuevos = fs.LOG[desde:]
    return {"ok": True, "corriendo": fs.ESTADO["corriendo"], "tarea": fs.ESTADO["tarea"], "log": nuevos,
            "total": desde + len(nuevos), "resultado": fs.ESTADO["resultado"], "error": fs.ESTADO["error"]}


@router.post("/enlace")
def enlace(c: Codigo) -> Dict[str, Any]:
    try:
        r = fs.guardar_enlace(c.codigo)
        return dict(r, message="Enlace con FacturaPro guardado. " + (r.get("siguiente") or ""))
    except ValueError as e:
        return {"ok": False, "message": str(e)}


@router.post("/vigilante")
def vigilante() -> Dict[str, Any]:
    return _tarea("vigilante", fs.automatizar, "vigilante", None, _pedir_admin())


@router.get("/avisos")
def avisos(desde: float = 0) -> Dict[str, Any]:
    """Lo importante que pasó con el túnel (lo escribe el vigilante, el de la app o el servicio)."""
    return {"ok": True, "data": fs.leer_eventos(desde)[-100:]}


@router.get("/servicios")
def servicios() -> Dict[str, Any]:
    """Qué se levanta solo (Docker, túneles, base, vigilante) y qué no."""
    try:
        return {"ok": True, "data": fs.servicios()}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "message": "No se pudieron revisar los servicios: %s" % e}


@router.post("/servicios/accion")
def servicio_accion(a: Accion) -> Dict[str, Any]:
    if a.accion not in ACCIONES:
        return {"ok": False, "message": "Acción desconocida"}
    return _tarea("servicios", fs.automatizar, a.accion, a.objetivo, _pedir_admin(a.clave))


def arrancar_vigilante_de_la_app() -> None:
    """Mientras la app está abierta (también en la bandeja) vigila el túnel. Si el servicio del sistema ya lo
    vigila, la app espera y toma el relevo solo si ese servicio se detiene: nunca hay dos a la vez."""
    try:
        fs.encender_vigilante_aqui()
    except Exception:  # noqa: BLE001 - la app funciona igual sin vigilante
        pass


@router.post("/avisar")
def avisar() -> Dict[str, Any]:
    return _tarea("avisar", fs._avisar_ahora)


def modo_linea_de_comandos(argv) -> Optional[int]:
    """El mismo ejecutable del backend sirve para el vigilante y para las tareas de administrador:
    bridge [--datos CARPETA] --vigilar | --instalar-vigilante | --quitar-vigilante | --docker-al-arrancar | --servicios
    | --instalar-docker | --iniciar-docker | --modo-admin | --ayudante --uid N | --enlace CODIGO | --version.
    Antes «--ayudante» e «--iniciar-docker» no estaban en la lista: el servicio de root levantaba el servidor HTTP.
    Las banderas del ayudante salen de la misma herramienta para que no vuelva a pasar."""
    banderas = (("--vigilar", "--instalar-vigilante", "--servicios", "--enlace", "--version", "--cli", "--analizar",
                 "--ayudante") + tuple(fs.BANDERAS_AYUDANTE))
    if any(b in argv for b in banderas):
        return fs.main(list(argv))
    return None
