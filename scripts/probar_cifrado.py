#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Las claves que guarda la app (config.json) van cifradas con tu usuario del sistema.

  python scripts/probar_cifrado.py   (Windows: DPAPI; Linux/macOS: llave local 600 — lo corre GitHub)

- Una config vieja con claves en texto claro se cifra sola al abrir la app, y la app las sigue leyendo.
- En el archivo no queda ninguna clave legible; lo que no es clave (host, puerto) queda igual.
- Guardar una clave nueva la cifra; otra instancia la lee.
- Linux: la llave y config.json solo los lee tu usuario (600); sin la llave, la clave no se puede leer.
"""
import json
import os
import shutil
import sys
import tempfile

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(RAIZ, "desktop_app"))
TMP = tempfile.mkdtemp()
os.environ["APPDATA"] = TMP
os.environ["HOME"] = TMP
os.environ["BRIDGE_PORT"] = "0"      # dentro de la app: no toca el arranque automático
ok = []


def c(cond, texto, detalle=""):
    ok.append(bool(cond))
    print("%s %-72s %s" % ("OK  " if cond else "FALLA", texto, str(detalle)[:100]), flush=True)


from config_manager import ConfigManager  # noqa: E402
from cifrado_local import PREFIJO, metodo  # noqa: E402

carpeta = os.path.join(TMP, "FacturaProEC") if os.name == "nt" else os.path.join(TMP, ".config", "FacturaProEC")
os.makedirs(carpeta, exist_ok=True)
archivo = os.path.join(carpeta, "config.json")
json.dump({"pg_host": "192.168.1.71", "pg_port": 5432, "pg_pass": "clave-vieja-en-claro", "sri_imap_pass": "imap-secreta",
           "remote_pass": ""}, open(archivo, "w", encoding="utf-8"))

cm = ConfigManager()
texto = open(archivo, encoding="utf-8").read()
guardado = json.loads(texto)
c(cm.get("pg_pass") == "clave-vieja-en-claro" and cm.get("sri_imap_pass") == "imap-secreta", "la app sigue leyendo las claves viejas")
c(guardado["pg_pass"].startswith(PREFIJO) and guardado["sri_imap_pass"].startswith(PREFIJO),
  "al abrir, las claves en texto claro se cifran solas (%s)" % metodo())
c("clave-vieja-en-claro" not in texto and "imap-secreta" not in texto, "en el archivo no queda ninguna clave legible")
c(guardado["pg_host"] == "192.168.1.71" and guardado["pg_port"] == 5432, "lo que no es clave queda igual")
cm.save_config({"pg_pass": "clave-nueva-2026"})
c("clave-nueva-2026" not in open(archivo, encoding="utf-8").read() and ConfigManager().get("pg_pass") == "clave-nueva-2026",
  "una clave nueva se guarda cifrada y otra instancia la lee")
e = cm.estado_cifrado()
c(e["cifradas"] == 2 and e["en_claro"] == 0, "estado: todas las claves cifradas", e)
c(ConfigManager()._defaults["pg_pass"] == "" and ConfigManager()._defaults["remote_pass"] == "", "sin claves por defecto en el código")
if os.name != "nt":
    llave = os.path.join(carpeta, ".llave")
    c(oct(os.stat(llave).st_mode & 0o777) == "0o600" and oct(os.stat(archivo).st_mode & 0o777) == "0o600",
      "la llave y config.json solo los lee tu usuario (600)")
    shutil.move(llave, llave + ".otra")
    c(ConfigManager().get("pg_pass") == "", "sin la llave (otra cuenta u otra PC) la clave no se puede leer")
print("\nRESULTADO: %s (%d/%d)" % ("TODO OK" if all(ok) else "HAY FALLOS", sum(ok), len(ok)))
sys.exit(0 if all(ok) else 1)
