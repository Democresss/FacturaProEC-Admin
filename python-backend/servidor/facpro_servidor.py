#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FacPro Servidor — deja lista la base de datos de tu empresa para FacturaPro.

Revisa lo que ya tienes y configura solo lo que falta:
  1. Docker (si no está, lo instala; si está apagado, lo enciende).
  2. PostgreSQL (usa el tuyo si ya existe, en Docker o instalado en el equipo; si no, crea uno).
  3. La base de datos (eliges una existente o crea «facturapro»).
  4. SSL en PostgreSQL (cifra todo lo que sale a internet).
  5. MinIO (opcional: los archivos ya se guardan en tu base).
  6. El túnel bore (dirección fija en bore.pub, se levanta solo tras reinicios).
  7. La prueba desde internet y la dirección lista para pegar en FacturaPro.
  8. El vigilante: revisa el túnel cada minuto; si bore.pub le dio otro puerto, lo vuelve a levantar
     y, con el código de enlace, se lo avisa a FacturaPro (sin que nadie cambie nada a mano).

Funciona en Windows y Linux con Python 3.8+ y solo la biblioteca estándar (en Windows también como .exe).
Interfaz: programa con su propia ventana (Windows .exe y Linux). Sin pantalla: `--cli`; en el navegador: `--web`.
No necesita sudo: usa el Docker del usuario (también Docker Desktop). Para instalar Docker pide la clave del sistema.
Otros modos: `--vigilar` (vigilante), `--enlace CODIGO` (guardar el código de FacturaPro), `--instalar-vigilante`.
"""
from __future__ import annotations

import json
import os
import platform
import random
import re
import secrets
import shutil
import socket
import string
import struct
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlparse

VERSION = "1.4.0"
MARCA = "FacPro Servidor"
URL_FACTURAPRO = "https://facturadorproecuador.org/v2/conectar-bd"
BORE_HOST = "bore.pub"
BORE_PUERTO_CONTROL = 7835
ES_WINDOWS = os.name == "nt"
DOCKER = os.environ.get("FACPRO_DOCKER", "docker")

RED = "facpro-red"
C_PG, C_MINIO = "facpro-postgres", "facpro-minio"
C_BORE_PG, C_BORE_MINIO = "facpro-bore-postgres", "facpro-bore-minio"
IMG_PG, IMG_MINIO, IMG_BORE, IMG_ALPINE = "postgres:17", "minio/minio", "ekzhang/bore", "alpine:3"
BASE_NUEVA = "__nueva__"
PUERTOS_BORE = (20000, 64999)

# ─────────────────────────────── utilidades ───────────────────────────────

LOG = []
_candado_log = threading.Lock()


def log(texto, nivel="info"):
    with _candado_log:
        LOG.append({"hora": time.strftime("%H:%M:%S"), "nivel": nivel, "texto": texto})
    marca = {"ok": "✔", "error": "✖", "aviso": "!", "paso": "»"}.get(nivel, "·")
    linea = "  %s %s" % (marca, texto)
    try:
        print(linea, flush=True)
    except UnicodeEncodeError:   # consola sin UTF-8 (cmd de Windows): sin símbolos, pero sin caerse
        try:
            print(linea.encode("ascii", "replace").decode(), flush=True)
        except Exception:
            pass
    except Exception:            # sin consola (programa con ventana)
        pass


def run(cmd, timeout=180, entrada=None):
    """Ejecuta un comando. Devuelve (código, salida+errores). Nunca lanza excepción."""
    try:
        r = subprocess.run(cmd, input=entrada, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout)
        return r.returncode, ((r.stdout or "") + (r.stderr or "")).strip()
    except FileNotFoundError:
        return 127, "no encontrado: %s" % cmd[0]
    except subprocess.TimeoutExpired:
        return 124, "tardó demasiado: %s" % " ".join(cmd[:3])
    except Exception as e:  # noqa: BLE001 - la herramienta debe seguir y explicar
        return 1, "%s: %s" % (type(e).__name__, e)


def clave_segura(largo=32):
    alfabeto = string.ascii_letters + string.digits
    return "".join(secrets.choice(alfabeto) for _ in range(largo))


def puerto_abierto(host, puerto, timeout=2.0):
    try:
        with socket.create_connection((host, int(puerto)), timeout=timeout):
            return True
    except OSError:
        return False


def sonda_ssl(host, puerto, timeout=8.0):
    """¿Responde un PostgreSQL con SSL en host:puerto? True = sí, False = PostgreSQL sin SSL, None = no responde."""
    try:
        with socket.create_connection((host, int(puerto)), timeout=timeout) as s:
            s.settimeout(timeout)
            s.sendall(struct.pack("!ii", 8, 80877103))  # SSLRequest del protocolo de PostgreSQL
            r = s.recv(1)
            if r == b"S":
                return True
            if r == b"N":
                return False
            return None
    except OSError:
        return None


def usuario_real():
    """El usuario que abrió la herramienta (aunque se ejecute con sudo o con la ventana de clave del sistema)."""
    if os.environ.get("SUDO_USER"):
        return os.environ["SUDO_USER"]
    if os.environ.get("PKEXEC_UID") and not ES_WINDOWS:
        try:
            import pwd
            return pwd.getpwuid(int(os.environ["PKEXEC_UID"])).pw_name
        except Exception:
            return ""
    return ""


def carpeta_datos():
    if not ES_WINDOWS and usuario_real():
        base = os.path.expanduser("~" + usuario_real())
    else:
        base = os.path.expanduser("~")
    return os.path.join(base, "facpro-servidor")


def _devolver_dueno(ruta):
    """Con sudo, los archivos quedan a nombre del usuario (no de root)."""
    if ES_WINDOWS or not usuario_real():
        return
    try:
        import pwd
        p = pwd.getpwnam(usuario_real())
        os.chown(ruta, p.pw_uid, p.pw_gid)
    except Exception:
        pass


def leer_config():
    try:
        with open(os.path.join(carpeta_datos(), "config.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


CLAVES_NO_GUARDAR = ("pg_clave", "url_postgres", "minio_clave")


def guardar_config(datos):
    # La clave de la base (y la dirección que la lleva) no se guardan en ningún archivo: se muestran una vez
    # para copiarlas a FacturaPro, que las guarda cifradas. Se borran también las que dejaron versiones anteriores.
    datos = {k: v for k, v in (datos or {}).items() if k not in CLAVES_NO_GUARDAR}
    carpeta = carpeta_datos()
    os.makedirs(carpeta, exist_ok=True)
    _devolver_dueno(carpeta)
    ruta = os.path.join(carpeta, "config.json")
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)
    if not ES_WINDOWS:
        os.chmod(ruta, 0o600)
    _devolver_dueno(ruta)
    return ruta


def sin_secretos(config):
    return {k: ("••••" if "clave" in k or "password" in k or "secret" in k or k == "enlace_facturapro" else v)
            for k, v in (config or {}).items()}


# ─────────────────────────────── Docker ───────────────────────────────

RUTAS_DOCKER_WINDOWS = (r"C:\Program Files\Docker\Docker\resources\bin\docker.exe",)
DOCKER_DESKTOP_EXE = r"C:\Program Files\Docker\Docker\Docker Desktop.exe"


_MOTOR = {"elegido": False, "nombre": ""}


def _contar_contenedores(host=None):
    """Cuántos contenedores ve Docker en ese motor (-1 si no responde o no hay permiso)."""
    entorno = dict(os.environ)
    if host:
        entorno["DOCKER_HOST"] = host
    try:
        r = subprocess.run([DOCKER, "ps", "-aq"], capture_output=True, text=True, timeout=20, env=entorno)
    except Exception:
        return -1
    return len(r.stdout.split()) if r.returncode == 0 else -1


def elegir_docker():
    """En Linux puede haber más de un Docker: el del sistema (el que ve sudo), Docker Desktop del usuario
    o Docker sin root. Se usa el que tiene los contenedores; antes, con sudo, se veía el del sistema vacío
    y PostgreSQL y MinIO de la empresa aparecían como «instalados en el equipo»."""
    if _MOTOR["elegido"] or ES_WINDOWS or os.environ.get("DOCKER_HOST"):
        return
    _MOTOR["elegido"] = True
    usuario = usuario_real()
    try:
        import pwd
        datos = pwd.getpwnam(usuario) if usuario else pwd.getpwuid(os.getuid())
        casa, uid = datos.pw_dir, datos.pw_uid
    except Exception:
        casa, uid = os.path.expanduser("~"), os.getuid() if hasattr(os, "getuid") else 0
    candidatos = [("Docker Desktop", os.path.join(casa, ".docker", "desktop", "docker.sock")),
                  ("Docker del usuario (sin root)", "/run/user/%d/docker.sock" % uid)]
    candidatos = [(n, "unix://" + p) for n, p in candidatos if os.path.exists(p)]
    if not candidatos:
        return
    mejor, cuantos = None, _contar_contenedores()
    for nombre, host in candidatos:
        n = _contar_contenedores(host)
        if n > cuantos or (n >= 0 and cuantos < 0):
            mejor, cuantos = (nombre, host), n
    if mejor:
        os.environ["DOCKER_HOST"] = mejor[1]
        _MOTOR["nombre"] = mejor[0]
        log("Se usa %s (ahí están tus contenedores)." % mejor[0], "ok")


def docker_bin():
    global DOCKER
    if shutil.which(DOCKER):
        elegir_docker()
        return DOCKER
    if ES_WINDOWS:
        for ruta in RUTAS_DOCKER_WINDOWS:
            if os.path.exists(ruta):
                DOCKER = ruta
                return ruta
    return None


def dk(*args, timeout=180):
    return run([DOCKER] + list(args), timeout=timeout)


def docker_estado():
    if not docker_bin():
        return {"instalado": False, "corriendo": False, "version": ""}
    code, out = dk("info", "--format", "{{.ServerVersion}}", timeout=30)
    sin_permiso = code != 0 and "permission denied" in out.lower()
    return {"instalado": True, "corriendo": code == 0, "version": out.splitlines()[0] if code == 0 and out else "",
            "sin_permiso": sin_permiso, "motor": _MOTOR["nombre"]}


def contenedores():
    code, out = dk("ps", "-a", "--format", "{{.Names}}\t{{.Image}}\t{{.State}}\t{{.Ports}}\t{{.CreatedAt}}", timeout=30)
    if code != 0:
        return []
    lista = []
    for linea in out.splitlines():
        partes = linea.split("\t")
        if len(partes) >= 3:
            lista.append({"nombre": partes[0], "imagen": partes[1], "estado": partes[2],
                          "puertos": partes[3] if len(partes) > 3 else "", "creado": partes[4] if len(partes) > 4 else ""})
    return lista


def _ordenar(candidatos, *preferidos):
    """Primero el elegido, luego los encendidos y el más reciente (docker ps ya lista del más nuevo al más viejo)."""
    orden = {c["nombre"]: i for i, c in enumerate(candidatos)}
    return sorted(candidatos, key=lambda c: tuple(c["nombre"] != p for p in preferidos if p)
                  + (c["estado"] != "running", orden[c["nombre"]]))


def _resumen(c):
    return {"nombre": c["nombre"], "imagen": c["imagen"], "corriendo": c["estado"] == "running", "creado": c.get("creado", "")}


def inspeccionar(nombre):
    code, out = dk("inspect", nombre, timeout=30)
    if code != 0:
        return {}
    try:
        return json.loads(out)[0]
    except (ValueError, IndexError):
        return {}


def env_de(info):
    env = {}
    for par in ((info.get("Config") or {}).get("Env") or []):
        if "=" in par:
            k, v = par.split("=", 1)
            env[k] = v
    return env


def redes_de(info):
    return list(((info.get("NetworkSettings") or {}).get("Networks") or {}).keys())


def puerto_publicado(puertos_txt, interno):
    m = re.search(r":(\d+)->%s/tcp" % interno, puertos_txt or "")
    return int(m.group(1)) if m else None


def asegurar_red():
    code, out = dk("network", "ls", "--format", "{{.Name}}")
    if RED not in out.split():
        code, out = dk("network", "create", RED)
        if code != 0:
            raise RuntimeError("No se pudo crear la red de Docker %s: %s" % (RED, out))
        log("Red de Docker «%s» creada" % RED, "ok")


def conectar_a_red(nombre):
    if RED in redes_de(inspeccionar(nombre)):
        return
    code, out = dk("network", "connect", RED, nombre)
    if code != 0 and "already exists" not in out:
        raise RuntimeError("No se pudo conectar %s a la red %s: %s" % (nombre, RED, out))
    log("«%s» conectado a la red «%s» (no se modificó nada más del contenedor)" % (nombre, RED), "ok")


def iniciar_docker():
    """Enciende Docker si está instalado pero apagado."""
    if docker_estado()["corriendo"]:
        return True
    log("Docker está apagado: encendiéndolo…", "paso")
    if ES_WINDOWS:
        if os.path.exists(DOCKER_DESKTOP_EXE):
            subprocess.Popen([DOCKER_DESKTOP_EXE])
    else:
        run(["systemctl", "start", "docker"], timeout=60)
    for _ in range(45):
        time.sleep(2)
        if docker_estado()["corriendo"]:
            log("Docker encendido", "ok")
            return True
    return False


def instalar_docker():
    """Instala Docker con el gestor de paquetes del sistema."""
    if ES_WINDOWS:
        if not shutil.which("winget"):
            webbrowser.open("https://www.docker.com/products/docker-desktop/")
            raise RuntimeError("Este Windows no tiene winget. Se abrió la página de Docker Desktop: instálalo y vuelve a abrir FacPro Servidor.")
        log("Instalando Docker Desktop con winget (Windows pedirá permiso de administrador)…", "paso")
        code, out = run(["winget", "install", "-e", "--id", "Docker.DockerDesktop",
                         "--accept-package-agreements", "--accept-source-agreements"], timeout=1800)
        if code != 0 and "already installed" not in out.lower() and "ya está instalado" not in out.lower():
            raise RuntimeError("No se pudo instalar Docker Desktop: %s" % out[-400:])
        log("Docker Desktop instalado. Reinicia el equipo si Windows lo pide, abre Docker Desktop una vez y vuelve a abrir FacPro Servidor.", "ok")
        return
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        raise RuntimeError("Para instalar Docker hace falta la clave de administrador (el botón «Instalar Docker» la pide).")
    osr = {}
    try:
        with open("/etc/os-release", encoding="utf-8") as f:
            for linea in f:
                if "=" in linea:
                    k, v = linea.strip().split("=", 1)
                    osr[k] = v.strip('"')
    except OSError:
        pass
    ids = ("%s %s" % (osr.get("ID", ""), osr.get("ID_LIKE", ""))).lower()
    if any(x in ids for x in ("debian", "ubuntu", "linuxmint")):
        pasos = [["apt-get", "update"], ["apt-get", "install", "-y", "docker.io"]]
    elif "fedora" in ids:
        pasos = [["dnf", "install", "-y", "moby-engine"]]
    elif "arch" in ids:
        pasos = [["pacman", "-Sy", "--noconfirm", "docker"]]
    elif "suse" in ids:
        pasos = [["zypper", "-n", "install", "docker"]]
    else:
        pasos = [["sh", "-c", "curl -fsSL https://get.docker.com | sh"]]
    log("Instalando Docker para %s…" % (osr.get("PRETTY_NAME") or "Linux"), "paso")
    for paso in pasos:
        code, out = run(paso, timeout=1800)
        if code != 0:
            raise RuntimeError("Falló «%s»: %s" % (" ".join(paso), out[-400:]))
    run(["systemctl", "enable", "--now", "docker"], timeout=120)
    if usuario_real():
        run(["usermod", "-aG", "docker", usuario_real()])
    log("Docker instalado y encendido (arranca solo con el equipo)", "ok")


# ─────────────────────────────── análisis ───────────────────────────────

def _psql(cont, sql, db="postgres", usuario="postgres", clave=None, solo_tcp=False):
    """psql dentro del contenedor: primero por socket (sin clave), luego por TCP con clave.
    solo_tcp=True comprueba de verdad la clave (por el socket PostgreSQL suele entrar sin pedirla)."""
    salida = ""
    for por_tcp in ((True,) if solo_tcp else (False, True)):
        if por_tcp and not clave:
            continue
        cmd = ["exec"]
        if clave:
            cmd += ["-e", "PGPASSWORD=" + clave]
        cmd += [cont, "psql", "-X", "-q", "-v", "ON_ERROR_STOP=1"]
        if por_tcp:
            cmd += ["-h", "127.0.0.1"]
        cmd += ["-U", usuario, "-d", db, "-Atc", sql]
        code, salida = dk(*cmd, timeout=60)
        if code == 0:
            return True, salida
    return False, salida


def _credenciales_contenedor(env):
    usuario = env.get("POSTGRES_USER") or env.get("POSTGRESQL_USERNAME") or "postgres"
    clave = env.get("POSTGRES_PASSWORD") or env.get("POSTGRESQL_PASSWORD") or env.get("POSTGRESQL_POSTGRES_PASSWORD") or ""
    db = env.get("POSTGRES_DB") or env.get("POSTGRESQL_DATABASE") or usuario
    return usuario, clave, db


def analizar_postgres(lista, config, elegido=None):
    candidatos = [c for c in lista if re.search(r"postgres|postgis|timescale", c["imagen"], re.I)
                  and "bore" not in c["imagen"]]
    preferido = config.get("pg_contenedor")
    candidatos = _ordenar(candidatos, elegido, preferido)
    if candidatos:
        c = candidatos[0]
        info = inspeccionar(c["nombre"])
        env = env_de(info)
        usuario, clave, db_env = _credenciales_contenedor(env)
        pg = {"estado": "contenedor", "contenedor": c["nombre"], "imagen": c["imagen"], "corriendo": c["estado"] == "running",
              "usuario": usuario, "tiene_clave": bool(clave), "puerto_host": puerto_publicado(c["puertos"], 5432),
              "otros": [x["nombre"] for x in candidatos[1:]], "bases": [], "ssl": None, "ya_configurado": c["nombre"] == preferido,
              "contenedores": [_resumen(x) for x in candidatos]}
        if pg["corriendo"]:
            ok, out = _psql(c["nombre"], "select datname, pg_get_userbyid(datdba) from pg_database "
                                         "where not datistemplate and datname <> 'postgres' order by 1", usuario=usuario, clave=clave)
            if ok:
                for linea in out.splitlines()[:30]:
                    if "|" in linea:
                        nombre, dueno = linea.split("|", 1)
                        _, tablas = _psql(c["nombre"], "select count(*) from information_schema.tables where table_schema='public'",
                                          db=nombre, usuario=usuario, clave=clave)
                        pg["bases"].append({"nombre": nombre, "dueno": dueno,
                                            "tablas": int(tablas) if str(tablas).strip().isdigit() else None})
                ok_ssl, ssl = _psql(c["nombre"], "show ssl", usuario=usuario, clave=clave)
                pg["ssl"] = (ssl.strip() == "on") if ok_ssl else None
            else:
                pg["error"] = "No se pudo entrar a PostgreSQL con el usuario «%s»." % usuario
        return pg
    if puerto_abierto("127.0.0.1", 5432):
        return {"estado": "nativo", "puerto_host": 5432, "ssl": sonda_ssl("127.0.0.1", 5432, 3), "bases": [],
                "nota": "PostgreSQL instalado en el equipo (fuera de Docker). Escribe su usuario, clave y base."}
    return {"estado": "no", "bases": []}


def analizar_minio(lista, elegido=None, config=None):
    candidatos = [x for x in lista if re.search(r"minio/minio|bitnami/minio|quay.io/minio|(^|/)minio(:|$)", x["imagen"], re.I)]
    candidatos = _ordenar(candidatos, elegido, (config or {}).get("minio_contenedor"))
    c = candidatos[0] if candidatos else None
    if c:
        env = env_de(inspeccionar(c["nombre"]))
        return {"estado": "contenedor", "contenedor": c["nombre"], "corriendo": c["estado"] == "running",
                "puerto_host": puerto_publicado(c["puertos"], 9000),
                "tiene_clave": bool(env.get("MINIO_ROOT_PASSWORD") or env.get("MINIO_SECRET_KEY")),
                "contenedores": [_resumen(x) for x in candidatos]}
    if puerto_abierto("127.0.0.1", 9000):
        return {"estado": "nativo", "puerto_host": 9000}
    return {"estado": "no"}


def _puerto_bore_de_logs(nombre):
    code, out = dk("logs", "--tail", "80", nombre, timeout=30)
    out = re.sub(r"\x1b\[[0-9;]*m", "", out or "")  # bore escribe con colores
    puertos = re.findall(r"listening at [\w.\-]+:(\d+)|remote_port=(\d+)", out or "")
    ultimo = next((a or b for a, b in reversed(puertos) if a or b), None)
    return int(ultimo) if ultimo else None, out or ""


def procesos_bore():
    """bore corriendo FUERA de Docker (por ejemplo el que se lanzó a mano)."""
    encontrados = []
    if ES_WINDOWS:
        code, out = run(["powershell", "-NoProfile", "-Command",
                         "Get-CimInstance Win32_Process -Filter \"Name='bore.exe'\" | "
                         "Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress"], timeout=30)
        try:
            datos = json.loads(out) if out.strip() else []
            for d in (datos if isinstance(datos, list) else [datos]):
                encontrados.append({"pid": d.get("ProcessId"), "comando": d.get("CommandLine") or "bore"})
        except ValueError:
            pass
    else:
        code, out = run(["ps", "-eo", "pid=,args="], timeout=30)
        for linea in out.splitlines():
            partes = linea.strip().split(None, 1)
            if len(partes) == 2 and re.search(r"(^|/)bore\s+local\b", partes[1]):
                encontrados.append({"pid": int(partes[0]), "comando": partes[1]})
    for p in encontrados:
        m = re.search(r"--port[ =](\d+)", p["comando"] or "")
        p["puerto"] = int(m.group(1)) if m else None
    return encontrados


def _estado_tunel(puerto, destino):
    """¿El túnel responde desde internet? Para PostgreSQL (5432) también dice si tiene SSL."""
    if not puerto:
        return {"en_linea": False, "ssl": None, "servicio": _servicio(destino)}
    if destino in (None, 5432):
        r = sonda_ssl(BORE_HOST, puerto, 6)
        if r is not None or destino == 5432:
            return {"en_linea": r is not None, "ssl": r, "servicio": "PostgreSQL"}
    return {"en_linea": puerto_abierto(BORE_HOST, puerto, 5), "ssl": None, "servicio": _servicio(destino)}


def _servicio(destino):
    return {5432: "PostgreSQL", 9000: "MinIO", 9001: "Consola MinIO", 22: "SSH"}.get(destino, "puerto %s" % destino if destino else "?")


def analizar_bore(lista):
    tuneles = []
    for c in lista:
        if "bore" in c["imagen"]:
            puerto, _ = _puerto_bore_de_logs(c["nombre"]) if c["estado"] == "running" else (None, "")
            args = " ".join(((inspeccionar(c["nombre"]).get("Config") or {}).get("Cmd") or []))
            destino = re.search(r"local (\d+)", args)
            t = {"contenedor": c["nombre"], "corriendo": c["estado"] == "running", "puerto": puerto,
                 "destino": int(destino.group(1)) if destino else None, "args": args}
            t.update(_estado_tunel(puerto, t["destino"]))
            tuneles.append(t)
    procesos = procesos_bore()
    for p in procesos:
        destino = re.search(r"local (\d+)", p.get("comando") or "")
        p["destino"] = int(destino.group(1)) if destino else None
        p.update(_estado_tunel(p.get("puerto"), p["destino"]))
    return {"contenedores": tuneles, "procesos": procesos, "instalado": bool(shutil.which("bore"))}


def analizar(pg_elegido=None, minio_elegido=None):
    config = leer_config()
    resultado = {
        "version": VERSION,
        "sistema": {"so": "%s %s" % (platform.system(), platform.release()), "equipo": socket.gethostname(),
                    "python": platform.python_version(), "carpeta": carpeta_datos(),
                    "admin": (not ES_WINDOWS and hasattr(os, "geteuid") and os.geteuid() == 0)},
        "docker": docker_estado(),
        "internet": {"bore_pub": puerto_abierto(BORE_HOST, BORE_PUERTO_CONTROL, 5)},
        "config": sin_secretos(config),
    }
    if resultado["docker"]["corriendo"]:
        lista = contenedores()
        resultado["postgres"] = analizar_postgres(lista, config, pg_elegido)
        resultado["minio"] = analizar_minio(lista, minio_elegido, config)
        resultado["bore"] = analizar_bore(lista)
    else:
        resultado["postgres"] = {"estado": "desconocido", "bases": []}
        resultado["minio"] = {"estado": "desconocido"}
        resultado["bore"] = analizar_bore([])
    if config.get("bore_puerto_pg"):
        resultado["conexion"] = {"en_linea": sonda_ssl(BORE_HOST, config["bore_puerto_pg"], 6)}
    resultado["vigilante"] = {"enlace": bool(config.get("enlace_facturapro")), "facturapro": config.get("enlace_url") or "",
                              "informado": config.get("informado") or "", "puerto_informado": config.get("puerto_informado"),
                              "instalado": vigilante_instalado(), "corriendo": bool(VIGILANTE.get("hilo"))}
    return resultado


# ─────────────────────────────── configuración ───────────────────────────────

def _esperar_postgres(cont, usuario, clave, segundos=90):
    for _ in range(segundos // 2):
        ok, _ = _psql(cont, "select 1", usuario=usuario, clave=clave)
        if ok:
            return True
        time.sleep(2)
    return False


def crear_postgres():
    usuario, clave, db = "facturapro", clave_segura(), "facturapro"
    puerto = 5432 if not puerto_abierto("127.0.0.1", 5432) else 5433
    log("Creando PostgreSQL 17 en Docker («%s», puerto %d en esta red)…" % (C_PG, puerto), "paso")
    code, out = dk("run", "-d", "--name", C_PG, "--network", RED, "--restart", "unless-stopped",
                   "-p", "%d:5432" % puerto, "-e", "POSTGRES_USER=" + usuario, "-e", "POSTGRES_PASSWORD=" + clave,
                   "-e", "POSTGRES_DB=" + db, "-v", "facpro-pgdata:/var/lib/postgresql/data", IMG_PG, timeout=900)
    if code != 0:
        raise RuntimeError("No se pudo crear PostgreSQL: %s" % out[-400:])
    if not _esperar_postgres(C_PG, usuario, clave):
        raise RuntimeError("PostgreSQL se creó pero no respondió a tiempo. Revisa: docker logs %s" % C_PG)
    log("PostgreSQL listo con la base «%s» y una clave nueva de 32 caracteres" % db, "ok")
    return {"contenedor": C_PG, "usuario": usuario, "clave": clave, "base": db, "puerto_host": puerto}


def activar_ssl(cont, usuario, clave):
    ok, estado = _psql(cont, "show ssl", usuario=usuario, clave=clave)
    if ok and estado.strip() == "on":
        log("SSL ya estaba activo en PostgreSQL", "ok")
        return
    log("Activando SSL en PostgreSQL (certificado propio de 10 años)…", "paso")
    code, pgdata = dk("exec", cont, "sh", "-c", 'echo "$PGDATA"')
    pgdata = (pgdata or "").strip().splitlines()[-1] if code == 0 and pgdata.strip() else "/var/lib/postgresql/data"
    generar = ('openssl req -new -x509 -days 3650 -nodes -subj "/CN=facpro" '
               '-keyout "%s/server.key" -out "%s/server.crt" >/dev/null 2>&1' % (pgdata, pgdata))
    code, _ = dk("exec", "-u", "root", cont, "sh", "-c", "command -v openssl >/dev/null && " + generar)
    if code != 0:
        # La imagen no trae openssl: se genera con un contenedor Alpine que monta los mismos volúmenes
        code, out = dk("run", "--rm", "--volumes-from", cont, IMG_ALPINE, "sh", "-c",
                       "apk add --no-cache openssl >/dev/null && " + generar, timeout=600)
        if code != 0:
            raise RuntimeError("No se pudo generar el certificado SSL: %s" % out[-300:])
    code, out = dk("exec", "-u", "root", cont, "sh", "-c",
                   'chown postgres:postgres "{0}/server.key" "{0}/server.crt" && chmod 600 "{0}/server.key"'.format(pgdata))
    if code != 0:
        raise RuntimeError("No se pudieron ajustar los permisos del certificado: %s" % out[-300:])
    ok, out = _psql(cont, "ALTER SYSTEM SET ssl = 'on'", usuario=usuario, clave=clave)
    if not ok:
        raise RuntimeError("PostgreSQL no aceptó activar SSL (¿el usuario es administrador?): %s" % out[-300:])
    _psql(cont, "select pg_reload_conf()", usuario=usuario, clave=clave)
    time.sleep(2)
    ok, estado = _psql(cont, "show ssl", usuario=usuario, clave=clave)
    if not (ok and estado.strip() == "on"):
        raise RuntimeError("Se configuró SSL pero PostgreSQL no lo encendió. Revisa: docker logs %s" % cont)
    log("SSL activo: lo que viaje por internet va cifrado", "ok")


def preparar_base(pg, opciones):
    """Devuelve (usuario, clave, base) con los que FacturaPro entrará."""
    cont = pg["contenedor"]
    admin_usuario, admin_clave = pg["admin_usuario"], pg["admin_clave"]
    elegida = opciones.get("base") or BASE_NUEVA
    if elegida == BASE_NUEVA:
        base, usuario = "facturapro", "facturapro"
        ok, existe_rol = _psql(cont, "select 1 from pg_roles where rolname='%s'" % usuario, usuario=admin_usuario, clave=admin_clave)
        clave = opciones.get("clave_base") or ""
        if ok and existe_rol.strip() == "1":
            if not clave:
                if admin_usuario == usuario and admin_clave:
                    clave = admin_clave
                else:
                    raise RuntimeError("Ya existe el usuario «facturapro» en PostgreSQL: escribe su clave.")
        else:
            clave = clave or clave_segura()
            ok, out = _psql(cont, "CREATE ROLE %s LOGIN PASSWORD '%s'" % (usuario, clave.replace("'", "''")),
                            usuario=admin_usuario, clave=admin_clave)
            if not ok:
                raise RuntimeError("No se pudo crear el usuario «%s»: %s" % (usuario, out[-300:]))
            log("Usuario «%s» creado con una clave nueva" % usuario, "ok")
        ok, existe = _psql(cont, "select 1 from pg_database where datname='%s'" % base, usuario=admin_usuario, clave=admin_clave)
        if not (ok and existe.strip() == "1"):
            ok, out = _psql(cont, "CREATE DATABASE %s OWNER %s" % (base, usuario), usuario=admin_usuario, clave=admin_clave)
            if not ok:
                raise RuntimeError("No se pudo crear la base «%s»: %s" % (base, out[-300:]))
            log("Base «%s» creada (FacturaPro crea sus tablas al conectarse)" % base, "ok")
        else:
            log("La base «%s» ya existía: se usa tal cual" % base, "ok")
    else:
        base = elegida
        ok, dueno = _psql(cont, "select pg_get_userbyid(datdba) from pg_database where datname='%s'" % base.replace("'", "''"),
                          usuario=admin_usuario, clave=admin_clave)
        if not ok or not dueno.strip():
            raise RuntimeError("No existe la base «%s»." % base)
        usuario = dueno.strip()
        clave = opciones.get("clave_base") or (admin_clave if usuario == admin_usuario else "")
        if not clave:
            raise RuntimeError("Escribe la clave del usuario «%s» (dueño de la base «%s»)." % (usuario, base))
        log("Se usa la base existente «%s» (dueño: %s). No se toca ningún dato." % (base, usuario), "ok")
        ok, out = _psql(cont, "select 1", db=base, usuario=usuario, clave=clave, solo_tcp=True)
        if not ok:
            raise RuntimeError("La clave del usuario «%s» no es correcta para la base «%s»." % (usuario, base))
        if opciones.get("usuario_propio"):
            return usuario_propio(cont, admin_usuario, admin_clave, base, usuario)
        if clave_debil(clave):
            log("La clave de «%s» es débil y la base quedará en internet. Marca «Usuario propio para FacturaPro» "
                "(crea uno con clave segura) o cambia esa clave." % usuario, "aviso")
    ok, out = _psql(cont, "select 1", db=base, usuario=usuario, clave=clave, solo_tcp=True)
    if not ok:
        raise RuntimeError("La clave del usuario «%s» no es correcta para la base «%s»." % (usuario, base))
    return usuario, clave, base


USUARIO_FACTURAPRO = "facturapro_app"


def clave_debil(clave):
    """Menos de 16 caracteres, o con palabras típicas: con la base en internet se puede adivinar."""
    c = str(clave or "")
    return len(c) < 16 or any(p in c.lower() for p in ("password", "clave", "admin", "123", "qwerty", "secret", "postgres"))


def usuario_propio(cont, admin_usuario, admin_clave, base, dueno):
    """Crea (o renueva) un usuario solo para FacturaPro, con clave larga al azar y SIN superusuario.
    Es miembro del dueño de la base, así puede crear y modificar sus tablas; la clave del dueño no cambia
    ni sale del equipo."""
    usuario, clave = USUARIO_FACTURAPRO, clave_segura(40)
    q = clave.replace("'", "''")
    ok, existe = _psql(cont, "select 1 from pg_roles where rolname='%s'" % usuario, usuario=admin_usuario, clave=admin_clave)
    sql = ("ALTER ROLE %s LOGIN NOSUPERUSER NOCREATEROLE NOCREATEDB PASSWORD '%s'" if ok and existe.strip() == "1"
           else "CREATE ROLE %s LOGIN NOSUPERUSER NOCREATEROLE NOCREATEDB PASSWORD '%s'") % (usuario, q)
    for sentencia, db in ((sql, "postgres"), ('GRANT "%s" TO %s' % (dueno.replace('"', '""'), usuario), "postgres"),
                          ('GRANT CONNECT, TEMPORARY ON DATABASE "%s" TO %s' % (base.replace('"', '""'), usuario), "postgres")):
        ok, out = _psql(cont, sentencia, db=db, usuario=admin_usuario, clave=admin_clave)
        if not ok and "already a member" not in out:
            raise RuntimeError("No se pudo preparar el usuario «%s»: %s" % (usuario, out[-300:]))
    ok, out = _psql(cont, "select 1", db=base, usuario=usuario, clave=clave, solo_tcp=True)
    if not ok:
        raise RuntimeError("El usuario «%s» no pudo entrar a «%s»: %s" % (usuario, base, out[-200:]))
    log("Usuario «%s» listo para FacturaPro: clave nueva de 40 caracteres, sin permisos de superusuario "
        "(la clave de «%s» no cambió)." % (usuario, dueno), "ok")
    blindar_tunel(cont, admin_usuario, admin_clave, base, usuario)
    return usuario, clave, base


MARCA_HBA_INICIO, MARCA_HBA_FIN = "# >>> facpro-servidor (túnel)", "# <<< facpro-servidor (túnel)"


def blindar_tunel(cont, admin_usuario, admin_clave, base, usuario):
    """Por el túnel (red de Docker «facpro-red») solo puede entrar el usuario de FacturaPro y solo a su base:
    cualquier otro usuario, por ejemplo el superusuario con una clave débil, queda rechazado desde internet.
    Las conexiones locales y de otras redes de Docker siguen igual."""
    code, subred = dk("network", "inspect", RED, "-f", "{{range .IPAM.Config}}{{.Subnet}} {{end}}")
    subredes = [x for x in (subred or "").split() if re.match(r"^[0-9a-fA-F.:]+/\d+$", x)]
    if code != 0 or not subredes:
        log("No se pudo leer la red «%s»: el túnel no quedó limitado al usuario de FacturaPro." % RED, "aviso")
        return False
    ok, ruta = _psql(cont, "show hba_file", usuario=admin_usuario, clave=admin_clave)
    ruta = (ruta or "").strip()
    if not ok or not ruta.startswith("/"):
        log("No se encontró pg_hba.conf: el túnel no quedó limitado al usuario de FacturaPro.", "aviso")
        return False
    code, actual = dk("exec", cont, "cat", ruta)
    if code != 0:
        log("No se pudo leer pg_hba.conf: %s" % actual[-200:], "aviso")
        return False
    lineas, dentro = [], False
    for linea in actual.splitlines():
        if linea.strip() == MARCA_HBA_INICIO:
            dentro = True
            continue
        if linea.strip() == MARCA_HBA_FIN:
            dentro = False
            continue
        if not dentro:
            lineas.append(linea)
    bloque = [MARCA_HBA_INICIO, "# Por el túnel de bore solo entra FacturaPro (lo escribe FacPro Servidor)."]
    for red in subredes:
        bloque += ["host %s %s %s md5" % (base, usuario, red), "hostssl %s %s %s md5" % (base, usuario, red),
                   "host all all %s reject" % red, "hostssl all all %s reject" % red]
    bloque.append(MARCA_HBA_FIN)
    nuevo = "\n".join(bloque + lineas) + "\n"
    code, out = run([DOCKER, "exec", "-i", cont, "sh", "-c", "cat > '%s'" % ruta.replace("'", "")], entrada=nuevo, timeout=30)
    if code != 0:
        log("No se pudo escribir pg_hba.conf: %s" % out[-200:], "aviso")
        return False
    ok, out = _psql(cont, "select pg_reload_conf()", usuario=admin_usuario, clave=admin_clave)
    if not ok:
        log("pg_hba.conf quedó escrito pero PostgreSQL no lo recargó: %s" % out[-200:], "aviso")
        return False
    log("Por el túnel solo puede entrar «%s» y solo a «%s»: cualquier otro usuario queda rechazado desde internet."
        % (usuario, base), "ok")
    return True


def detener_bore_fuera_de_docker():
    for p in procesos_bore():
        if ES_WINDOWS:
            run(["taskkill", "/PID", str(p["pid"]), "/F"])
        else:
            run(["kill", str(p["pid"])])
        log("Se detuvo el bore anterior (fuera de Docker, puerto %s)" % (p.get("puerto") or "?"), "ok")


def cerrar_tunel(nombre):
    """Cierra un túnel de bore (contenedor). Lo que estaba publicado deja de verse desde internet."""
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$", nombre or ""):
        raise RuntimeError("Nombre de túnel inválido.")
    info = inspeccionar(nombre)
    if "bore" not in str((info.get("Config") or {}).get("Image") or ""):
        raise RuntimeError("«%s» no es un túnel de bore: no se toca." % nombre)
    code, out = dk("rm", "-f", nombre)
    if code != 0:
        raise RuntimeError("No se pudo cerrar el túnel: %s" % out[-200:])
    config = leer_config()
    if nombre == C_BORE_MINIO:
        for k in ("minio_endpoint", "bore_puerto_minio"):
            config.pop(k, None)
        guardar_config(config)
    log("Túnel «%s» cerrado: ya no se ve desde internet." % nombre, "ok")
    return {"ok": True}


def levantar_bore(nombre, destino_host, destino_puerto, preferido=None, extra=None):
    """Túnel en bore.pub con puerto fijo; si el puerto está ocupado, prueba otro. Devuelve el puerto."""
    dk("rm", "-f", nombre)
    intentos = [preferido] if preferido else []
    intentos += [random.randint(*PUERTOS_BORE) for _ in range(5)]
    for puerto in intentos:
        args = ["run", "-d", "--name", nombre, "--network", RED, "--restart", "always"] + (extra or [])
        args += [IMG_BORE, "local", str(destino_puerto), "--local-host", destino_host, "--to", BORE_HOST, "--port", str(puerto)]
        code, out = dk(*args, timeout=600)
        if code != 0:
            raise RuntimeError("No se pudo crear el túnel: %s" % out[-300:])
        for _ in range(15):
            time.sleep(1)
            asignado, logs = _puerto_bore_de_logs(nombre)
            if asignado:
                log("Túnel activo: %s:%d → %s:%d" % (BORE_HOST, asignado, destino_host, destino_puerto), "ok")
                return asignado
            if re.search(r"already in use|port .* not available|error", logs, re.I):
                break
        log("El puerto %d de bore.pub no está disponible; probando otro…" % puerto, "aviso")
        dk("rm", "-f", nombre)
    raise RuntimeError("bore.pub no asignó un puerto. Revisa tu internet o intenta de nuevo en unos minutos.")


def configurar(opciones):
    """Hace todo lo que falte. opciones: base, clave_base, minio (bool), puerto (int), detener_bore_viejo (bool),
    y para PostgreSQL fuera de Docker: pg_usuario, pg_clave, pg_base, pg_puerto."""
    config = leer_config()
    if not docker_estado()["instalado"]:
        raise RuntimeError("Docker no está instalado. Pulsa «Instalar Docker».")
    if not iniciar_docker():
        raise RuntimeError("Docker está instalado pero no enciende. Ábrelo a mano y vuelve a intentar.")
    asegurar_red()
    lista = contenedores()
    pg_info = analizar_postgres(lista, config, opciones.get("pg_contenedor"))
    extra_bore = []

    # 1. PostgreSQL
    if pg_info["estado"] == "no":
        creado = crear_postgres()
        pg = {"contenedor": creado["contenedor"], "admin_usuario": creado["usuario"], "admin_clave": creado["clave"]}
        opciones = dict(opciones, base=BASE_NUEVA, clave_base=creado["clave"])
        destino_host, destino_puerto = C_PG, 5432
    elif pg_info["estado"] == "contenedor":
        cont = pg_info["contenedor"]
        if not pg_info["corriendo"]:
            log("Encendiendo PostgreSQL («%s»)…" % cont, "paso")
            dk("start", cont)
        env = env_de(inspeccionar(cont))
        admin_usuario, admin_clave, _ = _credenciales_contenedor(env)
        admin_clave = admin_clave or opciones.get("clave_admin") or ""
        if not _esperar_postgres(cont, admin_usuario, admin_clave, 60):
            raise RuntimeError("PostgreSQL («%s») no responde." % cont)
        log("PostgreSQL encontrado en Docker: «%s» (%s)" % (cont, pg_info.get("imagen")), "ok")
        conectar_a_red(cont)
        pg = {"contenedor": cont, "admin_usuario": admin_usuario, "admin_clave": admin_clave}
        destino_host, destino_puerto = cont, 5432
    else:  # PostgreSQL instalado en el equipo, fuera de Docker
        if not (opciones.get("pg_usuario") and opciones.get("pg_clave") and opciones.get("pg_base")):
            raise RuntimeError("Tu PostgreSQL está instalado fuera de Docker: escribe su usuario, clave y base.")
        pg = None
        destino_host, destino_puerto = "host.docker.internal", int(opciones.get("pg_puerto") or 5432)
        if not ES_WINDOWS:
            extra_bore = ["--add-host", "host.docker.internal:host-gateway"]
        if sonda_ssl("127.0.0.1", destino_puerto, 3) is not True:
            log("Tu PostgreSQL (fuera de Docker) no tiene SSL. Actívalo (ssl = on en postgresql.conf) antes de usarlo por internet.", "aviso")

    # 2. Base de datos y SSL
    if pg:
        usuario, clave, base = preparar_base(pg, opciones)
        activar_ssl(pg["contenedor"], pg["admin_usuario"], pg["admin_clave"])
    else:
        usuario, clave, base = opciones["pg_usuario"], opciones["pg_clave"], opciones["pg_base"]

    # 3. Túnel bore
    if opciones.get("detener_bore_viejo"):
        detener_bore_fuera_de_docker()
    preferido = opciones.get("puerto") or config.get("bore_puerto_pg")
    puerto_pg = levantar_bore(C_BORE_PG, destino_host, destino_puerto, int(preferido) if preferido else None, extra_bore)

    # 4. MinIO (opcional)
    minio = {}
    if opciones.get("minio"):
        m_info = analizar_minio(contenedores(), opciones.get("minio_contenedor"), config)
        if m_info["estado"] == "no":
            m_usuario, m_clave = "facpro", clave_segura()
            log("Creando MinIO en Docker («%s»)…" % C_MINIO, "paso")
            code, out = dk("run", "-d", "--name", C_MINIO, "--network", RED, "--restart", "unless-stopped",
                           "-p", "9000:9000", "-p", "9001:9001", "-e", "MINIO_ROOT_USER=" + m_usuario,
                           "-e", "MINIO_ROOT_PASSWORD=" + m_clave, "-v", "facpro-minio:/data",
                           IMG_MINIO, "server", "/data", "--console-address", ":9001", timeout=900)
            if code != 0:
                raise RuntimeError("No se pudo crear MinIO: %s" % out[-300:])
            m_cont = C_MINIO
            minio = {"usuario": m_usuario, "clave": m_clave}
            log("MinIO creado (consola en este equipo: http://localhost:9001)", "ok")
        elif m_info["estado"] == "contenedor":
            m_cont = m_info["contenedor"]
            if not m_info["corriendo"]:
                dk("start", m_cont)
            conectar_a_red(m_cont)
            env = env_de(inspeccionar(m_cont))
            minio = {"usuario": env.get("MINIO_ROOT_USER") or env.get("MINIO_ACCESS_KEY") or "",
                     "clave": env.get("MINIO_ROOT_PASSWORD") or env.get("MINIO_SECRET_KEY") or ""}
            log("MinIO encontrado en Docker: «%s»" % m_cont, "ok")
        else:
            m_cont = "host.docker.internal"
        puerto_minio = levantar_bore(C_BORE_MINIO, m_cont, 9000, config.get("bore_puerto_minio"),
                                     ["--add-host", "host.docker.internal:host-gateway"] if (m_cont == "host.docker.internal" and not ES_WINDOWS) else None)
        minio.update({"endpoint": "http://%s:%d" % (BORE_HOST, puerto_minio), "puerto": puerto_minio, "contenedor": m_cont})

    # 5. Prueba desde internet
    log("Probando la conexión desde internet (%s:%d)…" % (BORE_HOST, puerto_pg), "paso")
    en_linea = None
    for _ in range(6):
        en_linea = sonda_ssl(BORE_HOST, puerto_pg, 8)
        if en_linea is not None:
            break
        time.sleep(2)
    if en_linea is None:
        raise RuntimeError("El túnel está creado pero PostgreSQL no responde desde internet. Revisa: docker logs %s" % C_BORE_PG)
    if en_linea is False:
        log("PostgreSQL responde desde internet pero SIN SSL: no lo uses así.", "aviso")
    else:
        log("PostgreSQL responde desde internet con SSL", "ok")

    url = "postgresql://%s:%s@%s:%d/%s?sslmode=require" % (quote(usuario, safe=""), quote(clave, safe=""), BORE_HOST, puerto_pg, quote(base, safe=""))
    nuevo = dict(config, version=VERSION, pg_contenedor=(pg or {}).get("contenedor", ""), pg_usuario=usuario,
                 pg_base=base, bore_puerto_pg=puerto_pg, actualizado=time.strftime("%Y-%m-%d %H:%M"))
    if minio:
        nuevo.update(minio_endpoint=minio["endpoint"], minio_usuario=minio.get("usuario", ""),
                     bore_puerto_minio=minio.get("puerto"), minio_contenedor=minio.get("contenedor", ""))
    ruta = guardar_config(nuevo)
    with open(os.path.join(carpeta_datos(), "conexion.txt"), "w", encoding="utf-8") as f:
        f.write("Dirección de tu base para FacturaPro → Conecta tu base de datos (%s).\n"
                "La clave NO se guarda en este archivo: se mostró una sola vez en FacPro Servidor.\n"
                "Si la perdiste, vuelve a pulsar «Configurar todo» con «Usuario propio» y te da una nueva.\n\n%s\n"
                % (URL_FACTURAPRO, url.replace(":%s@" % quote(clave, safe=""), ":<tu clave>@")))
        if minio:
            f.write("\nMinIO (Perfil → Almacenamiento → MinIO):\n  Endpoint: %s\n  Usuario: %s\n"
                    % (minio["endpoint"], minio.get("usuario", "")))
    if not ES_WINDOWS:
        os.chmod(os.path.join(carpeta_datos(), "conexion.txt"), 0o600)
    _devolver_dueno(os.path.join(carpeta_datos(), "conexion.txt"))
    log("Todo listo. Configuración guardada en %s" % ruta, "ok")
    if nuevo.get("enlace_facturapro"):
        informar_direccion(puerto_pg, nuevo)
    return {"url": url, "ssl": en_linea is True, "puerto": puerto_pg, "base": base, "usuario": usuario, "minio": minio or None,
            "facturapro": URL_FACTURAPRO}


# ─────────────────────────────── enlace con FacturaPro y vigilante del túnel ───────────────────────────────
# Si el túnel se cae, Docker lo reinicia (--restart always) con el mismo puerto. Pero si bore.pub le dio ese
# puerto a otro mientras tanto, el túnel se queda sin puerto para siempre. El vigilante lo revisa cada minuto
# desde internet; si no responde varias veces seguidas, lo vuelve a levantar (primero con el mismo puerto,
# si no se puede con otro) y, con el código de enlace, le avisa a FacturaPro la dirección nueva.

PREFIJO_ENLACE = "FPENLACE."
TAREA_WINDOWS = "FacPro Servidor - vigilante del tunel"
SERVICIO_LINUX = "/etc/systemd/system/facpro-vigilante.service"


def leer_enlace(codigo):
    """{u: FacturaPro, o: empresa, s: secreto} o ValueError con el motivo."""
    import base64
    c = str(codigo or "").strip()
    if not c.startswith(PREFIJO_ENLACE):
        raise ValueError("Ese no es un código de enlace de FacturaPro (empieza con FPENLACE.).")
    cuerpo = c[len(PREFIJO_ENLACE):]
    try:
        datos = json.loads(base64.urlsafe_b64decode(cuerpo + "=" * (-len(cuerpo) % 4)).decode("utf-8"))
    except Exception:
        raise ValueError("El código está incompleto: cópialo otra vez desde FacturaPro.")
    if not all(isinstance(datos.get(k), str) and datos.get(k) for k in ("u", "o", "s")):
        raise ValueError("El código está incompleto: cópialo otra vez desde FacturaPro.")
    destino = urlparse(datos["u"])
    if destino.scheme != "https" and not (destino.scheme == "http" and _es_red_local(destino.hostname)):
        raise ValueError("El código apunta a una dirección sin HTTPS: no se usa (el código viajaría sin cifrar).")
    return datos


def _es_red_local(host):
    """localhost o una IP de la red de la oficina (192.168.x, 10.x…): ahí se admite http (pruebas con el backend local)."""
    import ipaddress
    if (host or "") in ("localhost",):
        return True
    try:
        ip = ipaddress.ip_address(host or "")
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private


def guardar_enlace(codigo):
    datos = leer_enlace(codigo)
    config = leer_config()
    config.update(enlace_facturapro=str(codigo).strip(), enlace_empresa=datos["o"], enlace_url=datos["u"])
    guardar_config(config)
    log("Enlace con FacturaPro guardado (%s)" % datos["u"], "ok")
    return {"ok": True, "facturapro": datos["u"]}


def informar_direccion(puerto, config=None, host=None):
    """Le dice a FacturaPro la dirección nueva de la base. True si FacturaPro la aceptó."""
    import urllib.error
    import urllib.request
    config = config if config is not None else leer_config()
    codigo = config.get("enlace_facturapro") or ""
    if not codigo:
        log("Sin enlace con FacturaPro: cambia la dirección a mano en FacturaPro → Conecta tu base de datos: %s:%s"
            % (host or BORE_HOST, puerto), "aviso")
        return False
    try:
        datos = leer_enlace(codigo)
    except ValueError as e:
        log(str(e), "error")
        return False
    cuerpo = json.dumps({"codigo": codigo, "host": host or BORE_HOST, "puerto": int(puerto)}).encode("utf-8")
    peticion = urllib.request.Request(datos["u"].rstrip("/") + "/v2/servidor-empresa/direccion", data=cuerpo, method="POST",
                                      headers={"Content-Type": "application/json", "User-Agent": "FacProServidor/" + VERSION})
    try:
        with urllib.request.urlopen(peticion, timeout=40) as r:
            respuesta = json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        try:
            motivo = json.loads(e.read().decode("utf-8") or "{}").get("error") or e.reason
        except Exception:
            motivo = e.reason
        log("FacturaPro no aceptó la dirección nueva: %s" % motivo, "error")
        return False
    except Exception as e:  # noqa: BLE001 - sin internet, DNS…
        log("No se pudo avisar a FacturaPro (%s). Se reintentará." % e, "aviso")
        return False
    if not respuesta.get("success"):
        log("FacturaPro no aceptó la dirección nueva: %s" % respuesta.get("error"), "error")
        return False
    config = leer_config()
    config.update(puerto_informado=int(puerto), informado=time.strftime("%Y-%m-%d %H:%M"))
    guardar_config(config)
    log("FacturaPro ya usa %s:%s%s" % (host or BORE_HOST, puerto, " (sin cambios)" if respuesta.get("sin_cambios") else ""), "ok")
    return True


def _destino_tunel(nombre):
    """(host, puerto, extra) al que apunta el contenedor del túnel, leídos de su configuración."""
    info = inspeccionar(nombre)
    args = list((info.get("Config") or {}).get("Cmd") or [])
    destino_puerto = int(args[args.index("local") + 1]) if "local" in args else 5432
    destino_host = args[args.index("--local-host") + 1] if "--local-host" in args else "localhost"
    extra = []
    for h in ((info.get("HostConfig") or {}).get("ExtraHosts") or []):
        extra += ["--add-host", h]
    return destino_host, destino_puerto, extra or None


def reparar_tunel(config=None):
    """Vuelve a levantar el túnel de PostgreSQL. Devuelve el puerto con el que quedó (o None)."""
    config = config if config is not None else leer_config()
    anterior = config.get("bore_puerto_pg")
    if not iniciar_docker():
        log("Docker no enciende: no se puede reparar el túnel todavía.", "error")
        return None
    pg = config.get("pg_contenedor")
    if pg and any(c["nombre"] == pg and c["estado"] != "running" for c in contenedores()):
        log("PostgreSQL («%s») estaba apagado: encendiéndolo…" % pg, "paso")
        dk("start", pg)
    if any(c["nombre"] == C_BORE_PG for c in contenedores()):
        destino_host, destino_puerto, extra = _destino_tunel(C_BORE_PG)
    else:
        destino_host, destino_puerto, extra = (pg or C_PG), 5432, None
    try:
        puerto = levantar_bore(C_BORE_PG, destino_host, destino_puerto, anterior, extra)
    except RuntimeError as e:
        log(str(e), "error")
        return None
    if puerto != anterior:
        log("bore.pub dio otro puerto: %s → %s" % (anterior, puerto), "aviso")
        config = leer_config()
        config.update(bore_puerto_pg=puerto, actualizado=time.strftime("%Y-%m-%d %H:%M"))
        guardar_config(config)
    return puerto


def vuelta_vigilante(estado, fallos_para_reparar=3):
    """Una revisión. estado = {"fallos": n}. Devuelve lo que pasó (para el registro y las pruebas)."""
    config = leer_config()
    puerto = config.get("bore_puerto_pg")
    if not puerto:
        return "sin_tunel"
    if sonda_ssl(BORE_HOST, puerto, 8) is not None:
        estado["fallos"] = 0
        if config.get("enlace_facturapro") and config.get("puerto_informado") != puerto:
            informar_direccion(puerto, config)
        return "ok"
    estado["fallos"] = estado.get("fallos", 0) + 1
    log("El túnel %s:%s no responde desde internet (%d/%d)" % (BORE_HOST, puerto, estado["fallos"], fallos_para_reparar), "aviso")
    if estado["fallos"] < fallos_para_reparar:
        return "caido"
    estado["fallos"] = 0
    nuevo = reparar_tunel(config)
    if not nuevo:
        return "sin_reparar"
    for _ in range(6):
        if sonda_ssl(BORE_HOST, nuevo, 8) is not None:
            break
        time.sleep(2)
    if nuevo != puerto or leer_config().get("puerto_informado") != nuevo:
        informar_direccion(nuevo)
    return "reparado" if nuevo == puerto else "puerto_nuevo"


def vigilar(intervalo=60, vueltas=None):
    """Revisa el túnel cada `intervalo` segundos (para siempre, o `vueltas` veces)."""
    log("Vigilante del túnel encendido (cada %d s)." % intervalo, "ok")
    estado, n = {"fallos": 0}, 0
    while vueltas is None or n < vueltas:
        try:
            vuelta_vigilante(estado)
        except Exception as e:  # noqa: BLE001 - el vigilante no se detiene por un error
            log("Vigilante: %s" % e, "error")
        n += 1
        if vueltas is None or n < vueltas:
            time.sleep(intervalo)


def _comando_vigilante():
    if getattr(sys, "frozen", False):
        return [sys.executable, "--vigilar"]
    return [sys.executable, os.path.abspath(__file__), "--vigilar"]


def vigilante_instalado():
    if ES_WINDOWS:
        return run(["schtasks", "/Query", "/TN", TAREA_WINDOWS], timeout=20)[0] == 0
    return os.path.exists(SERVICIO_LINUX) or "facpro_servidor" in (run(["crontab", "-l"], timeout=20)[1] or "")


def instalar_vigilante():
    """Que el vigilante arranque solo con el equipo (tarea de Windows / servicio systemd / cron @reboot)."""
    comando = _comando_vigilante()
    if ES_WINDOWS:
        tr = " ".join('"%s"' % p if " " in p else p for p in comando)
        code, out = run(["schtasks", "/Create", "/F", "/SC", "ONSTART", "/RU", "SYSTEM", "/TN", TAREA_WINDOWS, "/TR", tr], timeout=30)
        if code != 0:   # sin permisos de administrador: al iniciar sesión
            code, out = run(["schtasks", "/Create", "/F", "/SC", "ONLOGON", "/TN", TAREA_WINDOWS, "/TR", tr], timeout=30)
        if code != 0:
            raise RuntimeError("No se pudo crear la tarea de Windows: %s" % out[-200:])
        log("El vigilante arrancará solo con Windows (tarea «%s»)." % TAREA_WINDOWS, "ok")
        return {"ok": True, "como": "tarea de Windows"}
    if os.geteuid() == 0 and shutil.which("systemctl"):
        texto = ("[Unit]\nDescription=FacPro Servidor - vigilante del tunel\nAfter=network-online.target docker.service\n"
                 "Wants=network-online.target\n\n[Service]\nExecStart=%s\nRestart=always\nRestartSec=30\n%s\n"
                 "[Install]\nWantedBy=multi-user.target\n") % (" ".join(comando),
                                                               ("User=%s\n" % usuario_real()) if usuario_real() else "")
        with open(SERVICIO_LINUX, "w", encoding="utf-8") as f:
            f.write(texto)
        run(["systemctl", "daemon-reload"])
        code, out = run(["systemctl", "enable", "--now", "facpro-vigilante"])
        if code != 0:
            raise RuntimeError("No se pudo activar el servicio: %s" % out[-200:])
        log("El vigilante quedó como servicio del sistema (facpro-vigilante).", "ok")
        return {"ok": True, "como": "servicio systemd"}
    linea = "@reboot %s >> %s 2>&1" % (" ".join(comando), os.path.join(carpeta_datos(), "vigilante.log"))
    actual = run(["crontab", "-l"], timeout=20)[1] if shutil.which("crontab") else ""
    if linea not in (actual or ""):
        nuevo = "\n".join(l for l in (actual or "").splitlines() if "facpro_servidor" not in l and "--vigilar" not in l) + "\n" + linea + "\n"
        code, out = run(["crontab", "-"], entrada=nuevo, timeout=20)
        if code != 0:
            raise RuntimeError("No se pudo programar el arranque (crontab): %s" % out[-200:])
    log("El vigilante arrancará solo al encender el equipo (cron @reboot).", "ok")
    return {"ok": True, "como": "cron"}


# ─────────────────────────────── interfaz web (solo este equipo) ───────────────────────────────

ESTADO = {"corriendo": False, "resultado": None, "error": None, "tarea": ""}
VIGILANTE = {"hilo": None}


def encender_vigilante_aqui():
    """Mientras esta ventana siga abierta, también vigila (la tarea/servicio lo hace tras reiniciar)."""
    if VIGILANTE["hilo"] is None:
        VIGILANTE["hilo"] = threading.Thread(target=vigilar, daemon=True)
        VIGILANTE["hilo"].start()
TOKEN = secrets.token_urlsafe(24)


def _en_hilo(tarea, funcion, *args):
    if ESTADO["corriendo"]:
        return False

    def correr():
        ESTADO.update(corriendo=True, resultado=None, error=None, tarea=tarea)
        try:
            ESTADO["resultado"] = funcion(*args)
        except Exception as e:  # noqa: BLE001
            ESTADO["error"] = str(e)
            log(str(e), "error")
        finally:
            ESTADO["corriendo"] = False
    threading.Thread(target=correr, daemon=True).start()
    return True


class Manejador(BaseHTTPRequestHandler):
    server_version = "FacProServidor/" + VERSION

    def log_message(self, *args):
        pass

    def _json(self, datos, codigo=200):
        cuerpo = json.dumps(datos, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def _autorizado(self):
        q = parse_qs(urlparse(self.path).query)
        return (q.get("t") or [""])[0] == TOKEN or self.headers.get("X-Token") == TOKEN

    def do_GET(self):
        ruta = urlparse(self.path).path
        if ruta == "/":
            if not self._autorizado():
                return self._json({"error": "Abre la dirección que muestra FacPro Servidor."}, 403)
            cuerpo = PAGINA.replace("__TOKEN__", TOKEN).replace("__VERSION__", VERSION).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(cuerpo)))
            self.end_headers()
            return self.wfile.write(cuerpo)
        if not self._autorizado():
            return self._json({"error": "no autorizado"}, 403)
        if ruta == "/api/analisis":
            return self._json(analizar())
        if ruta == "/api/progreso":
            desde = int((parse_qs(urlparse(self.path).query).get("desde") or ["0"])[0])
            with _candado_log:
                nuevos = LOG[desde:]
            return self._json({"corriendo": ESTADO["corriendo"], "tarea": ESTADO["tarea"], "log": nuevos, "total": desde + len(nuevos),
                               "resultado": ESTADO["resultado"], "error": ESTADO["error"]})
        return self._json({"error": "no existe"}, 404)

    def do_POST(self):
        if not self._autorizado():
            return self._json({"error": "no autorizado"}, 403)
        ruta = urlparse(self.path).path
        largo = int(self.headers.get("Content-Length") or 0)
        try:
            datos = json.loads(self.rfile.read(largo).decode("utf-8") or "{}") if largo else {}
        except ValueError:
            datos = {}
        if ruta == "/api/configurar":
            return self._json({"ok": _en_hilo("configurar", configurar, datos)})
        if ruta == "/api/instalar-docker":
            return self._json({"ok": _en_hilo("instalar-docker", instalar_docker)})
        if ruta == "/api/encender-docker":
            return self._json({"ok": _en_hilo("encender-docker", iniciar_docker)})
        if ruta == "/api/enlace":
            try:
                return self._json(guardar_enlace(datos.get("codigo")))
            except ValueError as e:
                return self._json({"ok": False, "error": str(e)}, 400)
        if ruta == "/api/avisar":
            puerto = leer_config().get("bore_puerto_pg")
            return self._json({"ok": bool(puerto) and informar_direccion(puerto)})
        if ruta == "/api/vigilante":
            try:
                r = instalar_vigilante()
            except RuntimeError as e:
                return self._json({"ok": False, "error": str(e)}, 400)
            encender_vigilante_aqui()
            return self._json(r)
        if ruta == "/api/salir":
            self._json({"ok": True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return None
        return self._json({"error": "no existe"}, 404)


def abrir_navegador(url):
    if not ES_WINDOWS and usuario_real():
        # Con sudo: se abre el navegador del usuario, no el de root
        if run(["sudo", "-u", usuario_real(), "xdg-open", url], timeout=15)[0] == 0:
            return
    try:
        webbrowser.open(url)
    except Exception:
        pass


def iniciar_interfaz(puerto=0):
    servidor = ThreadingHTTPServer(("127.0.0.1", puerto), Manejador)
    url = "http://127.0.0.1:%d/?t=%s" % (servidor.server_address[1], TOKEN)
    print("\n  %s %s" % (MARCA, VERSION))
    print("  Abre esta dirección en tu navegador (solo funciona en este equipo):\n\n    %s\n" % url)
    print("  Para cerrar: Ctrl+C o el botón «Cerrar» de la página.\n", flush=True)
    threading.Timer(0.8, abrir_navegador, args=(url,)).start()
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        servidor.server_close()


# ─────────────────────────────── ventana del programa (Windows y Linux) ───────────────────────────────
# Programa con su propia ventana (tkinter, incluido en el .exe y en el binario de Linux). Si el equipo
# no tiene pantalla o tkinter, se usa la página en el navegador (--web) o el modo texto (--cli).

C_FONDO, C_PANEL, C_PANEL2, C_BORDE = "#0b1120", "#111a2e", "#16223b", "#24324f"
C_TEXTO, C_TENUE, C_OK, C_AVISO, C_ERROR, C_AZUL = "#e6edf7", "#8ea0bd", "#22c55e", "#f59e0b", "#ef4444", "#38bdf8"
COLOR_ESTADO = {"ok": C_OK, "av": C_AVISO, "er": C_ERROR, "gi": C_AZUL, "": C_TENUE}


def hay_pantalla():
    return ES_WINDOWS or bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def tarjetas_de(a):
    """[(estado, título, [líneas])] con lo que hay en el equipo (mismo contenido que la página web)."""
    d, pg, mi, bo = a["docker"], a["postgres"], a["minio"], a["bore"]
    t = [("ok", "Equipo", ["%s · %s" % (a["sistema"]["so"], a["sistema"]["equipo"])])]
    if d.get("sin_permiso"):
        t.append(("er", "Docker", ["Tu usuario no tiene permiso para usar Docker"]))
    else:
        t.append(("ok" if d["corriendo"] else ("av" if d["instalado"] else "er"), "Docker",
                  ["Encendido · versión %s" % d["version"] if d["corriendo"] else ("Instalado pero apagado" if d["instalado"] else "No está instalado")]
                  + (["Motor: %s" % d["motor"]] if d.get("motor") else [])))
    if pg["estado"] == "contenedor":
        bases = ", ".join("%s (%s tablas)" % (b["nombre"], b["tablas"] if b["tablas"] is not None else "?") for b in pg.get("bases") or []) or "sin bases propias"
        ssl = "SSL: activo" if pg.get("ssl") is True else ("SSL: apagado → se activa" if pg.get("ssl") is False else "SSL: se revisa al configurar")
        t.append(("ok" if pg.get("corriendo") else "av", "PostgreSQL ✓ existe",
                  ["En Docker: %s (%s)" % (pg["contenedor"], pg.get("imagen", "")), "Bases: " + bases, ssl] + ([pg["error"]] if pg.get("error") else [])))
    elif pg["estado"] == "nativo":
        t.append(("ok", "PostgreSQL ✓ existe", ["Instalado en el equipo (puerto 5432)",
                                               "SSL: activo" if pg.get("ssl") else "SSL: apagado (actívalo en postgresql.conf)"]))
    elif pg["estado"] == "no":
        t.append(("av", "PostgreSQL", ["No existe → se crea en Docker con clave segura"]))
    else:
        t.append(("", "PostgreSQL", ["Se revisa cuando Docker esté encendido"]))
    if mi["estado"] == "contenedor":
        t.append(("ok", "MinIO ✓ existe", ["En Docker: %s" % mi["contenedor"]]))
    elif mi["estado"] == "nativo":
        t.append(("ok", "MinIO ✓ existe", ["En el equipo (puerto 9000)"]))
    else:
        t.append(("", "MinIO", ["No existe (opcional)" if mi["estado"] == "no" else "Se revisa cuando Docker esté encendido"]))

    def estado_t(x):
        if not x.get("puerto"):
            return "sin puerto asignado"
        if not x.get("en_linea"):
            return "no responde"
        return "en línea con SSL" if x.get("ssl") is True else ("en línea SIN SSL" if x.get("ssl") is False else "en línea")
    lineas = ["%s: bore.pub:%s → %s · %s" % (c["contenedor"], c.get("puerto") or "?", c.get("servicio"), estado_t(c) if c["corriendo"] else "apagado")
              for c in bo.get("contenedores") or []]
    lineas += ["Fuera de Docker: bore.pub:%s → %s · %s (no vuelve solo tras reiniciar)" % (p.get("puerto") or "?", p.get("servicio"), estado_t(p))
               for p in bo.get("procesos") or []]
    malo = any(not x.get("en_linea") or x.get("ssl") is False for x in (bo.get("contenedores") or []) + (bo.get("procesos") or []))
    t.append((("av" if malo else "ok") if lineas else "", "Túnel bore" + (" ✓ existe" if lineas else ""),
              lineas or ["No hay túnel → se crea"]))
    t.append(("ok" if a["internet"]["bore_pub"] else "er", "Internet",
              ["bore.pub responde" if a["internet"]["bore_pub"] else "No se llega a bore.pub: revisa tu internet"]))
    if a.get("conexion"):
        t.append(("ok" if a["conexion"]["en_linea"] else "er", "Conexión para FacturaPro",
                  ["En línea con SSL" if a["conexion"]["en_linea"] else "Configurada pero no responde ahora"]))
    return t


def _abrir_como_admin(argumento):
    """Linux sin permisos: repite la acción con la ventana de contraseña del sistema (pkexec)."""
    comando = (_comando_vigilante()[:-1]) + [argumento]
    if shutil.which("pkexec"):
        code, out = run(["pkexec"] + comando, timeout=3600)
        if code != 0:
            raise RuntimeError("No se pudo completar como administrador: %s" % out[-300:])
        return
    raise RuntimeError("Hace falta la clave de administrador: cierra y abre FacPro Servidor con «sudo».")


def interfaz_ventana():
    import tkinter as tk
    from tkinter import messagebox, ttk

    raiz = tk.Tk()
    raiz.title("%s %s" % (MARCA, VERSION))
    raiz.geometry("1020x760")
    raiz.minsize(640, 480)
    raiz.configure(bg=C_FONDO)
    estilo = ttk.Style(raiz)
    try:
        estilo.theme_use("clam")
    except tk.TclError:
        pass
    estilo.configure("TCombobox", fieldbackground=C_PANEL2, background=C_PANEL2, foreground=C_TEXTO, arrowcolor=C_TEXTO)
    raiz.option_add("*TCombobox*Listbox.background", C_PANEL2)
    raiz.option_add("*TCombobox*Listbox.foreground", C_TEXTO)
    fuente, negrita, chica = ("Segoe UI", 10), ("Segoe UI", 10, "bold"), ("Segoe UI", 9)
    titulo_f = ("Segoe UI", 12, "bold")

    def boton(padre, texto, orden, primario=False):
        return tk.Button(padre, text=texto, command=orden, font=negrita, relief="flat", cursor="hand2", padx=14, pady=6,
                         bg=C_OK if primario else C_PANEL2, fg="#052e12" if primario else C_TEXTO,
                         activebackground="#16a34a" if primario else C_BORDE, activeforeground=C_TEXTO, bd=0)

    def entrada(padre, secreto=False, ancho=30):
        return tk.Entry(padre, font=fuente, bg=C_PANEL2, fg=C_TEXTO, insertbackground=C_TEXTO, relief="flat", width=ancho,
                        highlightthickness=1, highlightbackground=C_BORDE, highlightcolor=C_AZUL, show="•" if secreto else "")

    def etiqueta(padre, texto="", color=C_TENUE, f=None, **kw):
        return tk.Label(padre, text=texto, bg=kw.pop("bg", C_PANEL), fg=color, font=f or fuente, justify="left", anchor="w", **kw)

    # Encabezado
    cab = tk.Frame(raiz, bg="#0f1a33", padx=16, pady=10)
    cab.pack(fill="x")
    tk.Label(cab, text="FP", bg=C_AZUL, fg="#06101f", font=("Segoe UI", 14, "bold"), width=3, pady=4).pack(side="left")
    tk.Label(cab, text="  FacPro Servidor", bg="#0f1a33", fg=C_TEXTO, font=("Segoe UI", 15, "bold")).pack(side="left")
    tk.Label(cab, text="  Tu base de datos lista para FacturaPro · v" + VERSION, bg="#0f1a33", fg=C_TENUE, font=chica).pack(side="left")

    # Cuerpo con desplazamiento
    lienzo = tk.Canvas(raiz, bg=C_FONDO, highlightthickness=0)
    barra = tk.Scrollbar(raiz, orient="vertical", command=lienzo.yview)
    lienzo.configure(yscrollcommand=barra.set)
    barra.pack(side="right", fill="y")
    lienzo.pack(side="left", fill="both", expand=True)
    cuerpo = tk.Frame(lienzo, bg=C_FONDO, padx=18, pady=10)
    ventana_id = lienzo.create_window((0, 0), window=cuerpo, anchor="nw")
    cuerpo.bind("<Configure>", lambda e: lienzo.configure(scrollregion=lienzo.bbox("all")))
    lienzo.bind("<Configure>", lambda e: lienzo.itemconfigure(ventana_id, width=e.width))
    raiz.bind_all("<MouseWheel>", lambda e: lienzo.yview_scroll(int(-e.delta / 120) or (-1 if e.delta > 0 else 1), "units"))
    raiz.bind_all("<Button-4>", lambda e: lienzo.yview_scroll(-3, "units"))
    raiz.bind_all("<Button-5>", lambda e: lienzo.yview_scroll(3, "units"))

    def seccion(texto):
        tk.Label(cuerpo, text=texto, bg=C_FONDO, fg=C_TEXTO, font=titulo_f, anchor="w").pack(fill="x", pady=(14, 6))

    def panel():
        f = tk.Frame(cuerpo, bg=C_PANEL, padx=14, pady=12, highlightthickness=1, highlightbackground=C_BORDE)
        f.pack(fill="x")
        return f

    seccion("1. Lo que hay en este equipo")
    cabeza1 = tk.Frame(cuerpo, bg=C_FONDO)
    cabeza1.pack(fill="x")
    zona_tarjetas = tk.Frame(cuerpo, bg=C_FONDO)
    zona_tarjetas.pack(fill="x")
    zona_tuneles = tk.Frame(cuerpo, bg=C_FONDO)
    zona_tuneles.pack(fill="x", pady=(6, 0))
    zona_docker = tk.Frame(cuerpo, bg=C_FONDO)
    zona_docker.pack(fill="x", pady=(8, 0))

    seccion("2. ¿Qué configuro?")
    op = panel()
    zona_pg = tk.Frame(op, bg=C_PANEL)
    zona_pg.pack(fill="x")
    zona_base = tk.Frame(op, bg=C_PANEL)
    zona_base.pack(fill="x")
    v_propio = tk.BooleanVar(value=True)
    ch_propio = tk.Checkbutton(op, text="Usuario propio para FacturaPro (recomendado): clave segura, sin superusuario, y por el túnel solo "
                                        "entra ese usuario y solo a esta base. Tu usuario actual queda bloqueado desde internet y su clave no cambia.",
                               variable=v_propio, bg=C_PANEL, fg=C_TEXTO, selectcolor=C_PANEL2, activebackground=C_PANEL,
                               activeforeground=C_TEXTO, font=fuente, wraplength=880, justify="left")
    fila_puerto = tk.Frame(op, bg=C_PANEL)
    fila_puerto.pack(fill="x", pady=(8, 0))
    etiqueta(fila_puerto, "Puerto fijo en bore.pub (vacío = automático)").pack(anchor="w")
    e_puerto = entrada(fila_puerto, ancho=16)
    e_puerto.pack(anchor="w", pady=(2, 0))
    etiqueta(op, "Si ya usabas bore con un puerto (por ejemplo 65300), escríbelo para no cambiar la dirección en FacturaPro.",
             f=chica, wraplength=880).pack(anchor="w", pady=(4, 0))
    v_minio, v_bore_viejo = tk.BooleanVar(value=False), tk.BooleanVar(value=True)
    tk.Checkbutton(op, text="Publicar también MinIO (opcional: tus archivos ya se guardan en tu base)", variable=v_minio, bg=C_PANEL,
                   fg=C_TEXTO, selectcolor=C_PANEL2, activebackground=C_PANEL, activeforeground=C_TEXTO, font=fuente,
                   command=lambda: pintar_minio()).pack(anchor="w", pady=(8, 0))
    zona_minio = tk.Frame(op, bg=C_PANEL)
    zona_minio.pack(fill="x")
    ch_bore = tk.Checkbutton(op, text="Reemplazar el bore que corre fuera de Docker por uno que arranca solo tras cada reinicio",
                             variable=v_bore_viejo, bg=C_PANEL, fg=C_TEXTO, selectcolor=C_PANEL2, activebackground=C_PANEL,
                             activeforeground=C_TEXTO, font=fuente)
    b_config = boton(op, "Configurar todo", lambda: configurar_todo(), primario=True)
    b_config.pack(anchor="w", pady=(12, 0))

    zona_res = tk.Frame(cuerpo, bg=C_FONDO)
    zona_res.pack(fill="x", pady=(10, 0))

    seccion("3. Que se arregle solo")
    vg = panel()
    etiqueta(vg, "Si el túnel se cae, Docker lo vuelve a levantar con el mismo puerto. Si bore.pub le dio ese puerto a otro, el "
                 "vigilante toma uno nuevo y se lo avisa a FacturaPro con el código de enlace (FacturaPro → Conecta tu base de datos → "
                 "Dirección de tu base → Generar código). El código solo sirve para cambiar la dirección de tu base.",
             f=chica, wraplength=880).pack(anchor="w")
    etiqueta(vg, "Código de enlace de FacturaPro", color=C_TENUE).pack(anchor="w", pady=(8, 2))
    fila_enl = tk.Frame(vg, bg=C_PANEL)
    fila_enl.pack(fill="x")
    e_enlace = entrada(fila_enl, ancho=70)
    e_enlace.pack(side="left", fill="x", expand=True, ipady=3)
    boton(fila_enl, "Guardar", lambda: guardar_enl()).pack(side="left", padx=(8, 0))
    l_vig = etiqueta(vg, "", f=chica, wraplength=880)
    l_vig.pack(anchor="w", pady=(8, 0))
    fila_vb = tk.Frame(vg, bg=C_PANEL)
    fila_vb.pack(anchor="w", pady=(8, 0))
    boton(fila_vb, "Vigilar siempre (arranca con el equipo)", lambda: vigilar_siempre(), primario=True).pack(side="left")
    boton(fila_vb, "Avisar la dirección a FacturaPro ahora", lambda: tarea("avisar", _avisar_ahora)).pack(side="left", padx=(8, 0))

    seccion("Registro")
    registro = tk.Text(cuerpo, height=12, bg="#060b16", fg=C_TEXTO, font=("Consolas", 9), relief="flat", wrap="word",
                       highlightthickness=1, highlightbackground=C_BORDE)
    registro.pack(fill="x")
    for nivel, color in (("ok", C_OK), ("error", C_ERROR), ("aviso", C_AVISO), ("paso", C_AZUL), ("info", C_TEXTO)):
        registro.tag_configure(nivel, foreground=color)
    registro.configure(state="disabled")

    st = {"A": None, "visto": 0, "bases": {}, "e_clave": None, "fila_clave": None, "e_pg": {}, "tarea": None,
          "pg_elegido": None, "minio_elegido": None}

    def tarjeta(padre, fila, col, estado, titulo, lineas):
        f = tk.Frame(padre, bg=C_PANEL, padx=12, pady=10, highlightthickness=1, highlightbackground=C_BORDE)
        f.grid(row=fila, column=col, sticky="nsew", padx=4, pady=4)
        arriba = tk.Frame(f, bg=C_PANEL)
        arriba.pack(anchor="w")
        tk.Label(arriba, text="●", bg=C_PANEL, fg=COLOR_ESTADO.get(estado, C_TENUE), font=negrita).pack(side="left")
        tk.Label(arriba, text=" " + titulo, bg=C_PANEL, fg=C_TEXTO, font=negrita).pack(side="left")
        for linea in lineas:
            tk.Label(f, text=linea, bg=C_PANEL, fg=C_TENUE, font=chica, wraplength=280, justify="left", anchor="w").pack(anchor="w")

    def limpiar(zona):
        for w in zona.winfo_children():
            w.destroy()

    def revisar():
        limpiar(zona_tarjetas)
        tarjeta(zona_tarjetas, 0, 0, "gi", "Revisando…", ["Docker, PostgreSQL, MinIO y el túnel."])

        def trabajo():
            try:
                st["A"] = analizar(st["pg_elegido"], st["minio_elegido"])
            except Exception as e:  # noqa: BLE001
                log("No se pudo revisar el equipo: %s" % e, "error")
                st["A"] = None
            st["pintar"] = True     # la ventana lo recoge en su hilo (Tk no se toca desde otro hilo)
        threading.Thread(target=trabajo, daemon=True).start()

    tk.Button(cabeza1, text="↻ Revisar", command=revisar, font=chica, relief="flat", bg=C_PANEL2, fg=C_TEXTO,
              activebackground=C_BORDE, cursor="hand2").pack(anchor="e")

    def pintar():
        a = st["A"]
        limpiar(zona_tarjetas)
        if not a:
            tarjeta(zona_tarjetas, 0, 0, "er", "No se pudo revisar", ["Mira el registro abajo y pulsa «Revisar»."])
            return
        for i, (estado, titulo, lineas) in enumerate(tarjetas_de(a)):
            tarjeta(zona_tarjetas, i // 3, i % 3, estado, titulo, lineas)
        for col in range(3):
            zona_tarjetas.grid_columnconfigure(col, weight=1, uniform="t")
        # Túneles abiertos (cada uno se puede cerrar)
        limpiar(zona_tuneles)
        for t in a["bore"].get("contenedores") or []:
            fila = tk.Frame(zona_tuneles, bg=C_PANEL, padx=10, pady=6, highlightthickness=1, highlightbackground=C_BORDE)
            fila.pack(fill="x", pady=2)
            etiqueta(fila, "Túnel %s: bore.pub:%s → %s%s" % (t["contenedor"], t.get("puerto") or "?", t.get("servicio"),
                                                          "" if t["corriendo"] else " (apagado)"), color=C_TEXTO).pack(side="left")
            boton(fila, "Cerrar túnel", lambda n=t["contenedor"]: cerrar(n)).pack(side="right")
        # Docker
        limpiar(zona_docker)
        d = a["docker"]
        if d.get("sin_permiso"):
            f = tk.Frame(zona_docker, bg=C_PANEL, padx=14, pady=10, highlightthickness=1, highlightbackground=C_ERROR)
            f.pack(fill="x")
            etiqueta(f, "Tu usuario no puede usar Docker. Cierra y abre FacPro Servidor con: sudo ./FacProServidor", color=C_TEXTO).pack(anchor="w")
        elif not d["instalado"] or not d["corriendo"]:
            f = tk.Frame(zona_docker, bg=C_PANEL, padx=14, pady=10, highlightthickness=1, highlightbackground=C_AVISO)
            f.pack(fill="x")
            etiqueta(f, "Falta Docker: FacPro Servidor lo instala por ti." if not d["instalado"] else "Docker está apagado.",
                     color=C_TEXTO, f=negrita).pack(anchor="w")
            if not d["instalado"]:
                boton(f, "Instalar Docker", lambda: tarea("instalar-docker", _instalar_docker_ui), primario=True).pack(anchor="w", pady=(6, 0))
            else:
                boton(f, "Encender Docker", lambda: tarea("encender-docker", iniciar_docker), primario=True).pack(anchor="w", pady=(6, 0))
        # Opciones
        limpiar(zona_base)
        limpiar(zona_pg)
        st["bases"], st["e_clave"], st["fila_clave"], st["e_pg"] = {}, None, None, {}
        pg = a["postgres"]
        lista_pg = pg.get("contenedores") or []
        if len(lista_pg) > 1:
            etiqueta(zona_pg, "PostgreSQL que usará FacturaPro").pack(anchor="w")
            nombres = ["%s — %s%s" % (x["nombre"], x["imagen"], "" if x["corriendo"] else " (apagado)") for x in lista_pg]
            combo_pg = ttk.Combobox(zona_pg, values=nombres, state="readonly", width=60, font=fuente)
            combo_pg.current(0)
            combo_pg.pack(anchor="w", pady=(2, 8))

            def elegir_pg(_=None):
                st["pg_elegido"] = lista_pg[combo_pg.current()]["nombre"]
                revisar()
            combo_pg.bind("<<ComboboxSelected>>", elegir_pg)
        if pg["estado"] == "contenedor" and pg.get("bases"):
            etiqueta(zona_base, "Base de datos para FacturaPro").pack(anchor="w")
            textos = []
            for b in pg["bases"]:
                txt = "%s — %s tablas (dueño %s)" % (b["nombre"], b["tablas"] if b["tablas"] is not None else "?", b["dueno"])
                st["bases"][txt] = b
                textos.append(txt)
            textos.append("➕ Crear base nueva «facturapro»")
            combo = ttk.Combobox(zona_base, values=textos, state="readonly", width=60, font=fuente)
            combo.current(0)
            combo.pack(anchor="w", pady=(2, 0))
            st["combo"] = combo
            fila = tk.Frame(zona_base, bg=C_PANEL)
            l_clave = etiqueta(fila, "")
            l_clave.pack(anchor="w", pady=(8, 2))
            st["e_clave"] = entrada(fila, secreto=True)
            st["e_clave"].pack(anchor="w")
            st["fila_clave"] = fila

            def al_elegir(_=None):
                b = st["bases"].get(combo.get())
                falta = bool(b) and (b["dueno"] != pg.get("usuario") or not pg.get("tiene_clave"))
                if falta:
                    l_clave.configure(text="Clave del usuario «%s» (se escribe solo aquí)" % b["dueno"])
                    fila.pack(fill="x")
                else:
                    fila.pack_forget()
            def al_elegir_todo(_=None):
                al_elegir()
                if st["bases"].get(combo.get()):
                    ch_propio.pack(anchor="w", pady=(8, 0), before=fila_puerto)
                else:
                    ch_propio.pack_forget()
            combo.bind("<<ComboboxSelected>>", al_elegir_todo)
            al_elegir_todo()
        elif pg["estado"] == "no":
            ch_propio.pack_forget()
            etiqueta(zona_base, "Se creará PostgreSQL 17 con la base «facturapro» y una clave nueva.").pack(anchor="w")
        elif pg["estado"] == "nativo":
            etiqueta(zona_base, "Tu PostgreSQL está instalado en el equipo (fuera de Docker): escribe su usuario, clave y base.").pack(anchor="w")
            fila = tk.Frame(zona_base, bg=C_PANEL)
            fila.pack(fill="x", pady=(4, 0))
            for i, (clave, texto, valor, secreto) in enumerate((("pg_usuario", "Usuario", "postgres", False), ("pg_clave", "Clave", "", True),
                                                                 ("pg_base", "Base", "facturapro", False))):
                c = tk.Frame(fila, bg=C_PANEL)
                c.grid(row=0, column=i, sticky="w", padx=(0, 10))
                etiqueta(c, texto).pack(anchor="w")
                e = entrada(c, secreto=secreto, ancho=22)
                e.insert(0, valor)
                e.pack(anchor="w")
                st["e_pg"][clave] = e
        previo = next((x.get("puerto") for x in (a["bore"].get("procesos") or []) + (a["bore"].get("contenedores") or []) if x.get("puerto")), None)
        previo = previo or (a.get("config") or {}).get("bore_puerto_pg")
        if previo and not e_puerto.get():
            e_puerto.insert(0, str(previo))
        if a["bore"].get("procesos"):
            ch_bore.pack(anchor="w", before=b_config)
        else:
            ch_bore.pack_forget()
        pintar_minio()
        b_config.configure(state="normal" if d["corriendo"] else "disabled")
        v = a.get("vigilante") or {}
        l_vig.configure(text=("✓ Enlazado con %s" % v.get("facturapro") if v.get("enlace") else
                              "Sin enlace: si cambia el puerto tendrás que cambiarlo a mano en FacturaPro")
                        + " · " + ("vigilante instalado" if v.get("instalado") else "vigilante no instalado")
                        + (" · último aviso %s (puerto %s)" % (v.get("informado"), v.get("puerto_informado")) if v.get("informado") else ""),
                        fg=C_OK if v.get("enlace") and v.get("instalado") else C_AVISO)

    def pintar_minio():
        limpiar(zona_minio)
        a = st["A"] or {}
        lista = (a.get("minio") or {}).get("contenedores") or []
        if not v_minio.get() or len(lista) < 2:
            return
        etiqueta(zona_minio, "¿Qué MinIO publico?").pack(anchor="w", pady=(6, 0))
        nombres = ["%s — %s%s" % (x["nombre"], x["imagen"], "" if x["corriendo"] else " (apagado)") for x in lista]
        combo_m = ttk.Combobox(zona_minio, values=nombres, state="readonly", width=60, font=fuente)
        combo_m.current(0)
        combo_m.pack(anchor="w", pady=(2, 0))
        st["minio_elegido"] = lista[0]["nombre"]

        def elegir_m(_=None):
            st["minio_elegido"] = lista[combo_m.current()]["nombre"]
        combo_m.bind("<<ComboboxSelected>>", elegir_m)

    def cerrar(nombre):
        if messagebox.askyesno(MARCA, "¿Cerrar el túnel «%s»? Lo que publica dejará de verse desde internet." % nombre):
            tarea("cerrar-tunel", cerrar_tunel, nombre)

    def opciones():
        o = {"minio": v_minio.get(), "detener_bore_viejo": v_bore_viejo.get()}
        if st["pg_elegido"]:
            o["pg_contenedor"] = st["pg_elegido"]
        if v_minio.get() and st["minio_elegido"]:
            o["minio_contenedor"] = st["minio_elegido"]
        if ch_propio.winfo_ismapped() and v_propio.get():
            o["usuario_propio"] = True
        p = e_puerto.get().strip()
        if p.isdigit():
            o["puerto"] = int(p)
        b = st["bases"].get(st["combo"].get()) if st.get("bases") and st.get("combo") else None
        if st.get("bases") and st.get("combo"):
            o["base"] = b["nombre"] if b else BASE_NUEVA
            if st["e_clave"] is not None and st["e_clave"].get():
                o["clave_base"] = st["e_clave"].get()
        for k, e in st["e_pg"].items():
            o[k] = e.get().strip()
        return o

    def tarea(nombre, funcion, *args):
        if ESTADO["corriendo"]:
            return
        for w in (b_config,):
            w.configure(state="disabled")
        st["tarea"] = nombre
        _en_hilo(nombre, funcion, *args)

    def configurar_todo():
        limpiar(zona_res)
        tarea("configurar", configurar, opciones())

    def mostrar(r):
        limpiar(zona_res)
        f = tk.Frame(zona_res, bg="#0d2318", padx=14, pady=12, highlightthickness=1, highlightbackground="#22c55e")
        f.pack(fill="x")
        tk.Label(f, text="✔ ¡Listo! Tu base está en línea" + (" con SSL" if r.get("ssl") else ""), bg="#0d2318", fg=C_OK,
                 font=titulo_f).pack(anchor="w")
        tk.Label(f, text="Pulsa «Copiar» y pégala en FacturaPro → Conecta tu base de datos → «Probar conexión» y «Guardar y activar». "
                          "Lleva la clave: por eso está oculta.",
                 bg="#0d2318", fg=C_TEXTO, font=chica, wraplength=880, justify="left").pack(anchor="w", pady=(2, 6))
        fila = tk.Frame(f, bg="#0d2318")
        fila.pack(fill="x")
        e = entrada(fila, secreto=True, ancho=90)
        e.insert(0, r["url"])
        e.configure(state="readonly", readonlybackground="#06140c")
        e.pack(side="left", fill="x", expand=True, ipady=3)

        def mostrar_ocultar():
            visible = e.cget("show") == ""
            e.configure(show="•" if visible else "")
            bm.configure(text="Mostrar" if visible else "Ocultar")
        bm = boton(fila, "Mostrar", mostrar_ocultar)
        bm.pack(side="left", padx=(8, 0))

        def copiar():
            raiz.clipboard_clear()
            raiz.clipboard_append(r["url"])
            b.configure(text="Copiado")
            raiz.after(1500, lambda: b.configure(text="Copiar"))
        b = boton(fila, "Copiar", copiar, primario=True)
        b.pack(side="left", padx=(8, 0))
        tk.Label(f, text="La clave no se guarda en ningún archivo: cópiala ahora. Si la pierdes, «Configurar todo» con usuario propio te da otra.",
                 bg="#0d2318", fg=C_TENUE, font=chica).pack(anchor="w", pady=(6, 0))

    def guardar_enl():
        try:
            guardar_enlace(e_enlace.get())
            e_enlace.delete(0, "end")
            revisar()
        except ValueError as e:
            messagebox.showerror(MARCA, str(e))

    def vigilar_siempre():
        def instalar():
            try:
                r = instalar_vigilante()
            except RuntimeError:
                if ES_WINDOWS or os.geteuid() == 0:
                    raise
                _abrir_como_admin("--instalar-vigilante")
                r = {"ok": True}
            encender_vigilante_aqui()
            return r
        tarea("vigilante", instalar)

    def seguir():
        with _candado_log:
            nuevos = LOG[st["visto"]:]
        if nuevos:
            registro.configure(state="normal")
            for l in nuevos:
                registro.insert("end", "%s  %s\n" % (l["hora"], l["texto"]), l["nivel"] if l["nivel"] in ("ok", "error", "aviso", "paso") else "info")
            registro.see("end")
            registro.configure(state="disabled")
            st["visto"] += len(nuevos)
        if st.pop("pintar", False):
            pintar()
        if st["tarea"] and not ESTADO["corriendo"]:
            nombre, st["tarea"] = st["tarea"], None
            b_config.configure(state="normal")
            if ESTADO["error"]:
                messagebox.showerror(MARCA, ESTADO["error"])
            elif nombre == "configurar" and ESTADO["resultado"]:
                mostrar(ESTADO["resultado"])
            revisar()
        raiz.after(400, seguir)

    revisar()
    seguir()
    raiz.mainloop()


def _instalar_docker_ui():
    if ES_WINDOWS or os.geteuid() == 0:
        return instalar_docker()
    return _abrir_como_admin("--instalar-docker")


def _avisar_ahora():
    puerto = leer_config().get("bore_puerto_pg")
    if not puerto:
        raise RuntimeError("Aún no hay túnel: primero pulsa «Configurar todo».")
    if not informar_direccion(puerto):
        raise RuntimeError("No se pudo avisar a FacturaPro: mira el registro.")
    return True


# ─────────────────────────────── modo texto (--cli) ───────────────────────────────

def _pregunta(texto, defecto="", secreto=False):
    try:
        if secreto:
            import getpass
            return getpass.getpass("  %s: " % texto).strip() or defecto
        r = input("  %s%s: " % (texto, (" [%s]" % defecto) if defecto else "")).strip()
    except EOFError:
        r = ""
    return r or defecto


def modo_texto():
    print("\n  %s %s — modo texto\n" % (MARCA, VERSION))
    a = analizar()
    d = a["docker"]
    print("  Docker: %s" % ("encendido (%s)" % d["version"] if d["corriendo"] else ("instalado, apagado" if d["instalado"] else "NO instalado")))
    if not d["instalado"]:
        if _pregunta("¿Instalar Docker ahora? (s/n)", "s").lower().startswith("s"):
            instalar_docker()
            a = analizar()
        else:
            return
    pg = a["postgres"]
    print("  PostgreSQL: %s" % {"contenedor": "en Docker («%s»)" % pg.get("contenedor"), "nativo": "instalado en el equipo",
                                "no": "no existe (se creará)"}.get(pg["estado"], pg["estado"]))
    for i, b in enumerate(pg.get("bases") or [], start=1):
        print("     %d) %s  (dueño %s, %s tablas)" % (i, b["nombre"], b["dueno"], b["tablas"] if b["tablas"] is not None else "?"))
    opciones = {}
    if pg["estado"] == "contenedor" and pg.get("bases"):
        r = _pregunta("Número de la base a usar, o Enter para crear «facturapro»")
        if r.isdigit() and 1 <= int(r) <= len(pg["bases"]):
            opciones["base"] = pg["bases"][int(r) - 1]["nombre"]
            if pg["bases"][int(r) - 1]["dueno"] != pg.get("usuario") or not pg.get("tiene_clave"):
                opciones["clave_base"] = _pregunta("Clave del usuario «%s»" % pg["bases"][int(r) - 1]["dueno"], secreto=True)
    elif pg["estado"] == "nativo":
        opciones.update(pg_usuario=_pregunta("Usuario de PostgreSQL", "postgres"), pg_clave=_pregunta("Clave", secreto=True),
                        pg_base=_pregunta("Base", "facturapro"))
    if a["bore"]["procesos"]:
        opciones["detener_bore_viejo"] = _pregunta("Hay un bore corriendo fuera de Docker. ¿Reemplazarlo? (s/n)", "s").lower().startswith("s")
        previo = next((p.get("puerto") for p in a["bore"]["procesos"] if p.get("puerto")), None)
        if previo:
            opciones["puerto"] = previo
    r = _pregunta("Puerto fijo en bore.pub (Enter = automático)", str(opciones.get("puerto") or a["config"].get("bore_puerto_pg") or ""))
    if r.isdigit():
        opciones["puerto"] = int(r)
    opciones["minio"] = _pregunta("¿Publicar también MinIO? (s/n)", "n").lower().startswith("s")
    print()
    res = configurar(opciones)
    print("\n  Dirección para FacturaPro (%s):\n\n    %s\n" % (URL_FACTURAPRO, res["url"]))
    if not leer_config().get("enlace_facturapro"):
        codigo = _pregunta("Código de enlace de FacturaPro (Conecta tu base → Dirección; Enter para omitir)")
        if codigo:
            try:
                guardar_enlace(codigo)
                informar_direccion(res["puerto"])
            except ValueError as e:
                print("  ✖ %s" % e)
    if _pregunta("¿Vigilar el túnel siempre, también tras reiniciar el equipo? (s/n)", "s").lower().startswith("s"):
        try:
            print("  ✔ Vigilante instalado (%s)." % instalar_vigilante()["como"])
        except RuntimeError as e:
            print("  ✖ %s" % e)
    if res.get("minio"):
        print("  MinIO: %s  usuario %s\n" % (res["minio"]["endpoint"], res["minio"].get("usuario", "")))


# ─────────────────────────────── página ───────────────────────────────

PAGINA = r"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>FacPro Servidor</title>
<style>
:root{--f:#0b1120;--p:#111a2e;--p2:#16223b;--b:#24324f;--t:#e6edf7;--m:#8ea0bd;--ok:#22c55e;--av:#f59e0b;--er:#ef4444;--az:#38bdf8}
*{box-sizing:border-box}body{margin:0;background:var(--f);color:var(--t);font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
body:after{content:"FacPro";position:fixed;right:-40px;bottom:30px;font-size:160px;font-weight:900;color:#fff;opacity:.025;transform:rotate(-12deg);pointer-events:none}
header{display:flex;flex-wrap:wrap;align-items:center;gap:14px;padding:16px 20px;border-bottom:1px solid var(--b);background:linear-gradient(90deg,#0f1a33,#0b1120)}
.logo{width:42px;height:42px;border-radius:12px;background:linear-gradient(135deg,#38bdf8,#22c55e);display:grid;place-items:center;font-weight:900;color:#06101f}
h1{font-size:19px;margin:0}header small{color:var(--m)}main{max-width:980px;margin:0 auto;padding:22px 16px 60px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px}
.card{background:var(--p);border:1px solid var(--b);border-radius:16px;padding:14px 16px}
.card h3{margin:0 0 4px;font-size:14px;display:flex;align-items:center;gap:8px}.card p{margin:2px 0;color:var(--m);font-size:13px}
.dot{width:10px;height:10px;border-radius:50%;background:var(--m);flex:none}.dot.ok{background:var(--ok)}.dot.av{background:var(--av)}.dot.er{background:var(--er)}
.dot.gi{animation:gi 1s infinite}@keyframes gi{50%{opacity:.3}}
h2{font-size:16px;margin:26px 0 10px}label{display:block;font-size:13px;color:var(--m);margin:10px 0 4px}
select,input{width:100%;background:var(--p2);color:var(--t);border:1px solid var(--b);border-radius:10px;padding:9px 10px;font:inherit}
.fila{display:flex;gap:10px;flex-wrap:wrap}.fila>*{flex:1;min-width:200px}.check{display:flex;align-items:center;gap:8px;color:var(--t);margin-top:12px}
.check input{width:auto}button{white-space:nowrap;border:0;border-radius:12px;padding:10px 16px;font-weight:700;cursor:pointer;font:inherit;font-weight:700}
.pri{background:var(--ok);color:#052e12}.sec{background:var(--p2);color:var(--t);border:1px solid var(--b)}button:disabled{opacity:.5;cursor:wait}
#log{background:#060b16;border:1px solid var(--b);border-radius:12px;padding:10px 12px;height:210px;overflow:auto;font:12.5px/1.55 ui-monospace,Consolas,monospace;white-space:pre-wrap}
.l-ok{color:var(--ok)}.l-error{color:var(--er)}.l-aviso{color:var(--av)}.l-paso{color:var(--az)}
.res{border-color:#22c55e66;background:#0d2318}.url{display:flex;gap:8px;margin-top:8px}.url code{flex:1;background:#06140c;border:1px solid #22c55e44;border-radius:10px;padding:9px;font-size:12.5px;word-break:break-all}
.nota{color:var(--m);font-size:12.5px}.oculto{display:none}a{color:var(--az)}
</style></head><body>
<header><div class="logo">FP</div><div><h1>FacPro Servidor</h1><small>Tu base de datos lista para FacturaPro · v__VERSION__</small></div>
<div style="margin-left:auto;display:flex;gap:8px"><button class="sec" onclick="analizar()">↻ Revisar</button><button class="sec" onclick="salir()">Cerrar</button></div></header>
<main>
  <h2>1. Lo que hay en este equipo</h2>
  <div class="grid" id="tarjetas"><div class="card"><h3><span class="dot gi"></span>Revisando…</h3><p>Docker, PostgreSQL, MinIO y el túnel.</p></div></div>

  <div id="bloqueDocker" class="card oculto" style="margin-top:12px"></div>

  <div id="bloqueOpciones" class="oculto">
    <h2>2. ¿Qué configuro?</h2>
    <div class="card">
      <div id="opBase"></div>
      <div id="opNativo" class="oculto"><div class="fila">
        <div><label>Usuario de PostgreSQL</label><input id="pgU" value="postgres"></div>
        <div><label>Clave</label><input id="pgC" type="password"></div>
        <div><label>Base</label><input id="pgB" value="facturapro"></div></div></div>
      <div class="fila">
        <div><label>Puerto fijo en bore.pub</label><input id="puerto" placeholder="automático"></div>
      </div>
      <p class="nota">Si ya usabas bore con un puerto (por ejemplo 65300), escríbelo aquí para no cambiar la dirección en FacturaPro.</p>
      <label class="check"><input type="checkbox" id="minio"> Publicar también MinIO (opcional: tus archivos ya se guardan en tu base)</label>
      <label class="check oculto" id="filaBore"><input type="checkbox" id="boreViejo" checked> <span id="txtBore"></span></label>
      <div style="margin-top:16px"><button class="pri" id="btn" onclick="configurar()">Configurar todo</button></div>
    </div>
  </div>

  <div id="bloqueRes" class="card res oculto" style="margin-top:18px"></div>

  <h2>3. Que se arregle solo</h2>
  <div class="card" id="bloqueVigilante">
    <p class="nota">Si el túnel se cae, Docker lo vuelve a levantar con el mismo puerto. Si bore.pub le dio ese puerto a otro,
      el vigilante toma uno nuevo y se lo avisa a FacturaPro con el código de enlace (FacturaPro → Conecta tu base de datos →
      Dirección de tu base → Generar código). El código solo sirve para cambiar la dirección de tu base.</p>
    <label>Código de enlace de FacturaPro</label>
    <div class="url" style="margin-top:0"><input id="enlace" placeholder="FPENLACE.…" autocomplete="off"><button class="sec" onclick="guardarEnlace()">Guardar</button></div>
    <p id="estadoVig" class="nota" style="margin-top:8px"></p>
    <div style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap">
      <button class="pri" onclick="instalarVigilante()">Vigilar siempre (arranca con el equipo)</button>
      <button class="sec" onclick="avisarAhora()">Avisar la dirección a FacturaPro ahora</button>
    </div>
  </div>

  <h2>Registro</h2>
  <div id="log"></div>
</main>
<script>
const T='__TOKEN__';let A=null,desde=0,sondeo=null;
const $=id=>document.getElementById(id);
const api=(r,o={})=>fetch(r+(r.includes('?')?'&':'?')+'t='+T,Object.assign({headers:{'X-Token':T,'Content-Type':'application/json'}},o)).then(x=>x.json());
function esc(s){return String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
function tarjeta(estado,titulo,lineas){return `<div class="card"><h3><span class="dot ${estado}"></span>${esc(titulo)}</h3>${lineas.map(l=>`<p>${l}</p>`).join('')}</div>`}
async function analizar(){
  $('tarjetas').innerHTML=tarjeta('gi','Revisando…',['Docker, PostgreSQL, MinIO y el túnel.']);
  A=await api('/api/analisis');pintar();
}
function pintar(){
  const d=A.docker,pg=A.postgres,mi=A.minio,bo=A.bore,t=[];
  t.push(tarjeta('ok','Equipo',[esc(A.sistema.so)+' · '+esc(A.sistema.equipo)]));
  t.push(tarjeta(d.corriendo?'ok':(d.instalado?'av':'er'),'Docker',[d.corriendo?'Encendido · versión '+esc(d.version):(d.instalado?'Instalado pero apagado':'No está instalado')]));
  if(pg.estado==='contenedor'){
    const b=(pg.bases||[]).map(x=>esc(x.nombre)+(x.tablas!=null?' ('+x.tablas+' tablas)':'')).join(', ')||'sin bases propias';
    t.push(tarjeta(pg.corriendo?'ok':'av','PostgreSQL ✓ existe',['En Docker: <b>'+esc(pg.contenedor)+'</b> ('+esc(pg.imagen)+')','Bases: '+b,
      pg.ssl===true?'SSL: activo':(pg.ssl===false?'SSL: apagado → se activa':'SSL: se revisa al configurar')].concat(pg.error?['<span style="color:var(--er)">'+esc(pg.error)+'</span>']:[])));
  }else if(pg.estado==='nativo'){t.push(tarjeta('ok','PostgreSQL ✓ existe',['Instalado en el equipo (puerto 5432)',pg.ssl?'SSL: activo':'SSL: apagado (actívalo en postgresql.conf)']))}
  else if(pg.estado==='no'){t.push(tarjeta('av','PostgreSQL',['No existe → se crea en Docker con clave segura']))}
  else t.push(tarjeta('','PostgreSQL',['Se revisa cuando Docker esté encendido']));
  if(mi.estado==='contenedor')t.push(tarjeta('ok','MinIO ✓ existe',['En Docker: <b>'+esc(mi.contenedor)+'</b>'+(mi.puerto_host?' · puerto '+mi.puerto_host:'')]));
  else if(mi.estado==='nativo')t.push(tarjeta('ok','MinIO ✓ existe',['En el equipo (puerto 9000)']));
  else if(mi.estado==='no')t.push(tarjeta('','MinIO',['No existe (opcional)']));
  else t.push(tarjeta('','MinIO',['Se revisa cuando Docker esté encendido']));
  const estadoT=x=>!x.puerto?'<span style="color:var(--av)">sin puerto asignado</span>':(x.en_linea?(x.ssl===true?'<span style="color:var(--ok)">en línea con SSL</span>':(x.ssl===false?'<span style="color:var(--er)">en línea SIN SSL</span>':'<span style="color:var(--ok)">en línea</span>')):'<span style="color:var(--er)">no responde</span>');
  const tun=(bo.contenedores||[]).map(c=>'<b>'+esc(c.contenedor)+'</b>: bore.pub:'+(c.puerto||'?')+' → '+esc(c.servicio)+' · '+(c.corriendo?estadoT(c):'apagado'));
  const pro=(bo.procesos||[]).map(p=>'Fuera de Docker: bore.pub:'+(p.puerto||'?')+' → '+esc(p.servicio)+' · '+estadoT(p)+' <span class="nota">(no vuelve solo tras reiniciar)</span>');
  const lineasB=tun.concat(pro);
  const hayMal=[].concat(bo.contenedores||[],bo.procesos||[]).some(x=>!x.en_linea||x.ssl===false);
  t.push(tarjeta(lineasB.length?(hayMal?'av':'ok'):'','Túnel bore'+(lineasB.length?' ✓ existe':''),lineasB.length?lineasB:[bo.instalado?'bore está instalado pero no hay túnel corriendo → se crea':'No hay túnel → se crea']));
  t.push(tarjeta(A.internet.bore_pub?'ok':'er','Internet',[A.internet.bore_pub?'bore.pub responde':'No se llega a bore.pub: revisa tu internet']));
  if(A.conexion)t.push(tarjeta(A.conexion.en_linea?'ok':'er','Conexión para FacturaPro',[A.conexion.en_linea?'En línea con SSL':'Configurada pero no responde ahora']));
  const v=A.vigilante||{};
  $('estadoVig').innerHTML=(v.enlace?'<span style="color:var(--ok)">✓ Enlazado con '+esc(v.facturapro)+'</span>':'<span style="color:var(--av)">Sin enlace: si cambia el puerto tendrás que cambiarlo a mano en FacturaPro</span>')
    +' · '+(v.instalado?'<span style="color:var(--ok)">vigilante instalado</span>':'vigilante no instalado')
    +(v.informado?' · último aviso '+esc(v.informado)+' (puerto '+esc(v.puerto_informado)+')':'');
  $('tarjetas').innerHTML=t.join('');
  // Docker
  const bd=$('bloqueDocker');
  if(!d.instalado){bd.innerHTML='<h3>Falta Docker</h3><p class="nota">FacPro Servidor lo instala por ti.</p><button class="pri" onclick="accion(\'/api/instalar-docker\')">Instalar Docker</button>';bd.classList.remove('oculto')}
  else if(!d.corriendo){bd.innerHTML='<h3>Docker está apagado</h3><button class="pri" onclick="accion(\'/api/encender-docker\')">Encender Docker</button>';bd.classList.remove('oculto')}
  else bd.classList.add('oculto');
  // Opciones
  $('bloqueOpciones').classList.toggle('oculto',!d.corriendo);
  let ob='';
  if(pg.estado==='contenedor'&&(pg.bases||[]).length){
    ob='<label>Base de datos para FacturaPro</label><select id="base" onchange="pedirClave()">'+pg.bases.map(b=>`<option value="${esc(b.nombre)}" data-dueno="${esc(b.dueno)}">${esc(b.nombre)} — ${b.tablas??'?'} tablas (dueño ${esc(b.dueno)})</option>`).join('')+'<option value="__nueva__">➕ Crear base nueva «facturapro»</option></select><div id="filaClave" class="oculto"><label id="lblClave"></label><input id="claveBase" type="password"></div>';
  }else if(pg.estado==='no'){ob='<p class="nota">Se creará PostgreSQL 17 con la base «facturapro» y una clave nueva.</p>'}
  $('opBase').innerHTML=ob;$('opNativo').classList.toggle('oculto',pg.estado!=='nativo');
  const previo=(bo.procesos||[]).find(p=>p.puerto)||(bo.contenedores||[]).find(c=>c.puerto);
  if(previo&&!$('puerto').value)$('puerto').value=previo.puerto;
  if(A.config&&A.config.bore_puerto_pg&&!$('puerto').value)$('puerto').value=A.config.bore_puerto_pg;
  $('filaBore').classList.toggle('oculto',!(bo.procesos||[]).length);
  $('txtBore').textContent='Reemplazar el bore que corre fuera de Docker por uno que arranca solo tras cada reinicio';
  pedirClave();
}
function pedirClave(){
  const s=$('base');if(!s)return;const o=s.options[s.selectedIndex],pg=A.postgres;
  const falta=s.value!=='__nueva__'&&(o.dataset.dueno!==pg.usuario||!pg.tiene_clave);
  $('filaClave').classList.toggle('oculto',!falta);$('lblClave').textContent='Clave del usuario «'+o.dataset.dueno+'»';
}
function opciones(){
  const o={minio:$('minio').checked,detener_bore_viejo:$('boreViejo').checked};
  const p=parseInt($('puerto').value,10);if(p)o.puerto=p;
  if($('base')){o.base=$('base').value;const c=$('claveBase');if(c&&c.value)o.clave_base=c.value}
  if(A.postgres.estado==='nativo'){o.pg_usuario=$('pgU').value;o.pg_clave=$('pgC').value;o.pg_base=$('pgB').value}
  return o;
}
async function configurar(){await accion('/api/configurar',opciones())}
async function accion(ruta,cuerpo){
  $('btn').disabled=true;$('bloqueRes').classList.add('oculto');
  const r=await api(ruta,{method:'POST',body:JSON.stringify(cuerpo||{})});
  if(!r.ok){$('btn').disabled=false;return}
  clearInterval(sondeo);sondeo=setInterval(progreso,700);
}
async function progreso(){
  const p=await api('/api/progreso?desde='+desde);desde=p.total;
  for(const l of p.log){const d=document.createElement('div');d.className='l-'+l.nivel;d.textContent=l.hora+'  '+l.texto;$('log').appendChild(d);$('log').scrollTop=1e9}
  if(p.corriendo)return;
  clearInterval(sondeo);$('btn').disabled=false;
  if(p.tarea==='configurar'&&p.resultado)mostrar(p.resultado);
  if(p.error){const b=$('bloqueRes');b.className='card';b.style.borderColor='#ef444466';b.innerHTML='<h3>No se pudo terminar</h3><p>'+esc(p.error)+'</p><p class="nota">Corrige lo indicado y pulsa «Configurar todo» de nuevo: lo que ya quedó hecho se respeta.</p>';b.classList.remove('oculto')}
  analizar();
}
function mostrar(r){
  const b=$('bloqueRes');b.className='card res';b.style.borderColor='';
  let h='<h3>✔ ¡Listo! Tu base está en línea'+(r.ssl?' con SSL':'')+'</h3><p class="nota">Pega esta dirección en FacturaPro → <a href="'+esc(r.facturapro)+'" target="_blank" rel="noopener">Conecta tu base de datos</a>, pulsa «Probar conexión» y luego «Guardar y activar».</p>';
  h+='<div class="url"><code id="u">'+esc(r.url)+'</code><button class="pri" onclick="copiar(\'u\',this)">Copiar</button></div>';
  if(r.minio)h+='<p style="margin-top:12px">MinIO (Perfil → Almacenamiento → MinIO)</p><div class="url"><code id="m">Endpoint: '+esc(r.minio.endpoint)+'   Usuario: '+esc(r.minio.usuario||'')+'   Clave: '+esc(r.minio.clave||'')+'</code><button class="sec" onclick="copiar(\'m\',this)">Copiar</button></div>';
  h+='<p class="nota" style="margin-top:10px">La clave no se guarda en ningún archivo: cópiala ahora. Si la pierdes, «Configurar todo» con usuario propio te da otra.</p>';
  b.innerHTML=h;b.classList.remove('oculto');
}
function copiar(id,btn){navigator.clipboard.writeText($(id).textContent).then(()=>{btn.textContent='Copiado';setTimeout(()=>btn.textContent='Copiar',1500)})}
async function guardarEnlace(){const r=await api('/api/enlace',{method:'POST',body:JSON.stringify({codigo:$('enlace').value.trim()})});
  if(r.ok){$('enlace').value='';analizar();progreso()}else alert(r.error||'No se pudo guardar')}
async function instalarVigilante(){const r=await api('/api/vigilante',{method:'POST'});if(!r.ok)alert(r.error||'No se pudo instalar');analizar();progreso()}
async function avisarAhora(){const r=await api('/api/avisar',{method:'POST'});progreso();if(!r.ok)alert('No se pudo avisar: mira el registro')}
async function salir(){await api('/api/salir',{method:'POST'});document.body.innerHTML='<main><h2>FacPro Servidor se cerró. Ya puedes cerrar esta pestaña.</h2></main>'}
analizar();progreso();
</script></body></html>"""


def main(argv=None):
    # Consolas sin UTF-8 (cmd de Windows): los símbolos ✔ ✖ se reemplazan en vez de hacer caer el programa
    for flujo in (sys.stdout, sys.stderr):
        try:
            flujo.reconfigure(errors="replace")
        except Exception:
            pass
    args = list(sys.argv[1:] if argv is None else argv)
    if "--version" in args:
        print(VERSION)
        return 0
    if "--analizar" in args:
        print(json.dumps(analizar(), ensure_ascii=False, indent=2))
        return 0
    if "--enlace" in args:
        i = args.index("--enlace")
        try:
            guardar_enlace(args[i + 1] if i + 1 < len(args) else "")
        except ValueError as e:
            print("  ✖ %s" % e)
            return 1
        print("  ✔ Enlace con FacturaPro guardado.")
        return 0
    if "--instalar-vigilante" in args:
        try:
            print("  ✔ Vigilante instalado (%s)." % instalar_vigilante()["como"])
            return 0
        except RuntimeError as e:
            print("  ✖ %s" % e)
            return 1
    if "--vigilar" in args:
        vigilar()
        return 0
    if "--instalar-docker" in args:
        try:
            instalar_docker()
            return 0
        except RuntimeError as e:
            print("  ✖ %s" % e)
            return 1
    if "--cli" in args:
        try:
            modo_texto()
            return 0
        except (RuntimeError, KeyboardInterrupt) as e:
            print("\n  ✖ %s" % e)
            return 1
    if "--web" in args:
        iniciar_interfaz()
        return 0
    if not hay_pantalla():
        print("  Este equipo no tiene pantalla: se usa el modo texto.")
        try:
            modo_texto()
            return 0
        except (RuntimeError, KeyboardInterrupt) as e:
            print("\n  ✖ %s" % e)
            return 1
    try:
        interfaz_ventana()
    except ImportError:
        print("  Falta tkinter (en Linux: sudo apt install python3-tk). Se abre en el navegador.")
        iniciar_interfaz()
    except Exception as e:  # noqa: BLE001 - p. ej. sin permiso para abrir ventanas: el navegador sirve igual
        if type(e).__name__ != "TclError":
            raise
        print("  No se pudo abrir la ventana (%s). Se abre en el navegador." % e)
        iniciar_interfaz()
    return 0


if __name__ == "__main__":
    sys.exit(main())
