#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Prueba de humo del backend de FacturaProEC Admin (script o ejecutable compilado).

  python scripts/probar_backend.py                          → python-backend/bridge.py con este Python
  python scripts/probar_backend.py dist-bridge/facpro-bridge → el ejecutable compilado (lo usa GitHub)

Comprueba: arranca y da su puerto; sin la clave responde 401; con la clave 200; una página web ajena no
recibe permiso CORS; la sección «Servidor y túnel» responde; el mismo ejecutable sirve de vigilante (--version).
"""
import json
import os
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request

AQUI = os.path.dirname(os.path.abspath(__file__))
ok = []


def c(cond, texto, detalle=""):
    ok.append(bool(cond))
    print("%s %-70s %s" % ("OK  " if cond else "FALLA", texto, str(detalle)[:120]), flush=True)


def pedir(url, clave=None, metodo="GET", cabeceras=None):
    req = urllib.request.Request(url, method=metodo, headers=dict(cabeceras or {}, **({"X-Bridge-Token": clave} if clave else {})))
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, dict(r.headers), r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read().decode("utf-8", "replace")


def main():
    if len(sys.argv) > 1:
        comando = [os.path.abspath(sys.argv[1])]
    else:
        comando = [sys.executable, os.path.join(AQUI, "..", "python-backend", "bridge.py")]
    clave = secrets.token_hex(16)
    entorno = dict(os.environ, BRIDGE_PORT="0", BRIDGE_TOKEN=clave, PYTHONUNBUFFERED="1")
    proc = subprocess.Popen(comando, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=entorno, text=True,
                            encoding="utf-8", errors="replace")
    puerto, salida = None, []
    try:
        fin = time.time() + 90
        while time.time() < fin and puerto is None:
            linea = proc.stdout.readline()
            if not linea:
                if proc.poll() is not None:
                    break
                continue
            salida.append(linea)
            if linea.startswith("BRIDGE_PORT="):
                puerto = int(linea.strip().split("=")[1])
        c(puerto is not None, "el backend arranca y da su puerto", "".join(salida[-8:]) if puerto is None else puerto)
        if puerto is None:
            return 1
        base = "http://127.0.0.1:%d" % puerto
        c(pedir(base + "/api/config")[0] == 401, "sin la clave: 401 (una página web no puede usarlo)")
        c(pedir(base + "/api/config", clave)[0] == 200, "con la clave de la app: 200")
        st, cab, _ = pedir(base + "/api/db/sql", metodo="OPTIONS",
                           cabeceras={"Origin": "https://pagina-maliciosa.example", "Access-Control-Request-Method": "POST"})
        c("access-control-allow-origin" not in {k.lower() for k in cab}, "una página web ajena no recibe permiso CORS", st)
        st, _, cuerpo = pedir(base + "/api/servidor/analizar", clave)
        datos = json.loads(cuerpo) if st == 200 else {}
        c(st == 200 and datos.get("ok") and "docker" in (datos.get("data") or {}), "«Servidor y túnel» revisa el equipo",
          (datos.get("data") or {}).get("docker") if st == 200 else cuerpo[:120])
        st, _, cuerpo = pedir(base + "/api/servidor/progreso", clave)
        c(st == 200 and json.loads(cuerpo).get("ok"), "«Servidor y túnel»: progreso")
    finally:
        proc.kill()
        try:
            proc.wait(timeout=10)
        except Exception:
            pass
    version = subprocess.run(comando + ["--version"], capture_output=True, text=True, timeout=60)
    c(version.returncode == 0 and version.stdout.strip()[:1].isdigit(), "el mismo ejecutable sirve de vigilante (--version)",
      version.stdout.strip() or version.stderr[-200:])
    print("\nRESULTADO: %s (%d/%d)" % ("TODO OK" if all(ok) else "HAY FALLOS", sum(ok), len(ok)))
    return 0 if all(ok) else 1


if __name__ == "__main__":
    sys.exit(main())
