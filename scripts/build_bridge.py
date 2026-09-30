#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compila el backend (python-backend/bridge.py) en un solo ejecutable con PyInstaller: dist-bridge/facpro-bridge[.exe].

Lleva Python y todas las librerías adentro, así la app funciona en cualquier Linux y en Windows 10/11 sin instalar
nada. Lo usa GitHub al compilar (y también sirve en tu PC):  python scripts/build_bridge.py
Requiere: pip install -r python-backend/requirements.txt customtkinter pyinstaller
"""
import os
import subprocess
import sys

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def main():
    os.chdir(RAIZ)
    ocultos = ["servidor_api", "facpro_servidor", "uvicorn.logging", "uvicorn.loops.auto", "uvicorn.protocols.http.auto",
               "uvicorn.protocols.websockets.auto", "uvicorn.lifespan.on", "asyncpg.pgproto.pgproto", "aiosqlite"]
    comando = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--onefile", "--console", "--name", "facpro-bridge",
               "--distpath", "dist-bridge", "--workpath", os.path.join("build-bridge", "work"), "--specpath", "build-bridge",
               "--paths", "python-backend", "--paths", os.path.join("python-backend", "servidor"), "--paths", "desktop_app"]
    for m in ocultos:
        comando += ["--hidden-import", m]
    comando.append(os.path.join("python-backend", "bridge.py"))
    print("$", " ".join(comando), flush=True)
    return subprocess.call(comando)


if __name__ == "__main__":
    sys.exit(main())
