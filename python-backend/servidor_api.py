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


class Nombre(BaseModel):
    nombre: str


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


@router.post("/instalar-docker")
def instalar_docker() -> Dict[str, Any]:
    return _tarea("instalar-docker", fs._instalar_docker_ui)


@router.post("/encender-docker")
def encender_docker() -> Dict[str, Any]:
    return _tarea("encender-docker", fs.iniciar_docker)


@router.post("/cerrar-tunel")
def cerrar_tunel(n: Nombre) -> Dict[str, Any]:
    return _tarea("cerrar-tunel", fs.cerrar_tunel, n.nombre)


@router.get("/progreso")
def progreso(desde: int = 0) -> Dict[str, Any]:
    with fs._candado_log:
        nuevos = fs.LOG[desde:]
    return {"ok": True, "corriendo": fs.ESTADO["corriendo"], "tarea": fs.ESTADO["tarea"], "log": nuevos,
            "total": desde + len(nuevos), "resultado": fs.ESTADO["resultado"], "error": fs.ESTADO["error"]}


@router.post("/enlace")
def enlace(c: Codigo) -> Dict[str, Any]:
    try:
        return dict(fs.guardar_enlace(c.codigo), message="Enlace con FacturaPro guardado")
    except ValueError as e:
        return {"ok": False, "message": str(e)}


@router.post("/vigilante")
def vigilante() -> Dict[str, Any]:
    def instalar():
        try:
            r = fs.instalar_vigilante()
        except RuntimeError:
            if fs.ES_WINDOWS or fs.os.geteuid() == 0:
                raise
            fs._abrir_como_admin("--instalar-vigilante")
            r = {"ok": True}
        return r
    return _tarea("vigilante", instalar)


@router.post("/avisar")
def avisar() -> Dict[str, Any]:
    return _tarea("avisar", fs._avisar_ahora)


def modo_linea_de_comandos(argv) -> Optional[int]:
    """El mismo ejecutable del backend sirve para el vigilante y para las tareas de administrador:
    bridge --vigilar | --instalar-vigilante | --instalar-docker | --enlace CODIGO | --version."""
    banderas = ("--vigilar", "--instalar-vigilante", "--instalar-docker", "--enlace", "--version", "--cli")
    if any(b in argv for b in banderas):
        return fs.main(list(argv))
    return None
