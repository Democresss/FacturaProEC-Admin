"""
Cifrado de las claves que la app guarda en su config.json: solo tu usuario del sistema puede leerlas.

- Windows: DPAPI (CryptProtectData). Queda ligado a tu cuenta de Windows: otra cuenta, u otra PC con el
  archivo copiado, no puede descifrarlo.
- Linux / macOS: Fernet (AES + HMAC) con una llave aleatoria en ~/.config/FacturaProEC/.llave, con permiso 600
  (solo tu usuario la lee).

Se guarda como "enc1:<base64>". Un valor sin ese prefijo es de una versión anterior (texto en claro): se lee
igual y se cifra la próxima vez que se guarda la configuración.
"""
from __future__ import annotations

import base64
import os
from typing import Optional

PREFIJO = "enc1:"
_PALABRAS = ("pass", "token", "secret", "clave")


def es_secreto(nombre: str) -> bool:
    n = str(nombre or "").lower()
    return any(p in n for p in _PALABRAS)


def metodo() -> str:
    return "DPAPI de Windows (ligado a tu cuenta)" if os.name == "nt" else "llave local de tu usuario (permiso 600)"


# ─── Windows: DPAPI ────────────────────────────────────────────────────────────
def _dpapi(datos: bytes, proteger: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    buf = ctypes.create_string_buffer(datos, len(datos))
    entrada = BLOB(len(datos), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    salida = BLOB()
    funcion = ctypes.windll.crypt32.CryptProtectData if proteger else ctypes.windll.crypt32.CryptUnprotectData
    SIN_VENTANAS = 0x1   # CRYPTPROTECT_UI_FORBIDDEN
    if not funcion(ctypes.byref(entrada), None, None, None, None, SIN_VENTANAS, ctypes.byref(salida)):
        raise OSError("DPAPI no pudo %s la clave" % ("cifrar" if proteger else "descifrar"))
    try:
        return ctypes.string_at(salida.pbData, salida.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(salida.pbData)


# ─── Linux / macOS: Fernet con llave local 600 ────────────────────────────────
def _fernet(carpeta: str):
    from cryptography.fernet import Fernet
    ruta = os.path.join(carpeta, ".llave")
    if not os.path.exists(ruta):
        os.makedirs(carpeta, exist_ok=True)
        llave = Fernet.generate_key()
        fd = os.open(ruta, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(llave)
    else:
        try:
            os.chmod(ruta, 0o600)
        except OSError:
            pass
    with open(ruta, "rb") as f:
        return Fernet(f.read().strip())


def cifrar(texto: str, carpeta: str) -> str:
    if not texto or str(texto).startswith(PREFIJO):
        return texto
    datos = str(texto).encode("utf-8")
    bruto = _dpapi(datos, True) if os.name == "nt" else _fernet(carpeta).encrypt(datos)
    return PREFIJO + base64.b64encode(bruto).decode("ascii")


def descifrar(valor: str, carpeta: str) -> Optional[str]:
    """Texto en claro. None si no se pudo (p. ej. el archivo se copió de otra cuenta u otra PC)."""
    if not isinstance(valor, str) or not valor.startswith(PREFIJO):
        return valor
    try:
        bruto = base64.b64decode(valor[len(PREFIJO):])
        datos = _dpapi(bruto, False) if os.name == "nt" else _fernet(carpeta).decrypt(bruto)
        return datos.decode("utf-8")
    except Exception:
        return None

