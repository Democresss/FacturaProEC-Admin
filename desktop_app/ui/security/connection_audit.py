"""connection_audit — helpers de auditoría de red para el SecurityGuardian.

Cuatro piezas reutilizables, todas síncronas (sin tkinter):
  1. `whitelist_load(config) / whitelist_save(config, ips)` — persiste la
     lista de IPs permitidas en disco (key `security_whitelist` del
     ConfigManager). El guardian y el security_tab la leen/escriben.
  2. `BruteForceCounter` — deque por (ip, puerto) con ventana deslizante
     configurable (default: 5 intentos en 30s → fuerza bruta). Se le
     alimenta `record(ip, port)` y se le consulta `is_bruteforce(ip, port)`.
  3. `events_rotate(events, max=500)` — trunca la lista de eventos del
     guardian a los últimos `max` (rotación LIFO).
  4. `log_security_event(event, path=None)` — append con lock a
     `security.log` en `%APPDATA%/FacturaProEC/` (Win) o
     `~/.config/FacturaProEC/` (Linux). Crea el dir si no existe.

Todo desacoplado de la UI para poder probarlo sin tkinter.
"""
from __future__ import annotations

import os
import threading
import time
from collections import deque, defaultdict
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Iterable


# ═══════════════════════════════════════════════════════════════════════
#  Whitelist persistente
# ═══════════════════════════════════════════════════════════════════════

def whitelist_load(config) -> list[str]:
    """Carga la whitelist guardada como lista JSON en `security_whitelist`."""
    raw = config.get("security_whitelist", [])
    if isinstance(raw, str):
        # Por si alguien la guardó como string CSV por error, lo saneamos.
        raw = [s.strip() for s in raw.split(",") if s.strip()]
    if not isinstance(raw, list):
        return []
    # Filtrar no-strings y duplicados manteniendo orden
    seen = set()
    out = []
    for ip in raw:
        if isinstance(ip, str) and ip and ip not in seen:
            seen.add(ip)
            out.append(ip)
    return out


def whitelist_save(config, ips: Iterable[str]) -> None:
    """Persiste la whitelist normalizada (lista única de strings)."""
    seen = set()
    clean = []
    for s in (ips or []):
        s = str(s).strip()
        if s and s not in seen:
            seen.add(s)
            clean.append(s)
    config.set("security_whitelist", clean)


# ═══════════════════════════════════════════════════════════════════════
#  BruteForceCounter
# ═══════════════════════════════════════════════════════════════════════

class BruteForceCounter:
    """Cuenta intentos por (ip, puerto) en una ventana deslizante.

    Parámetros:
      threshold=5  : número de intentos en una ventana que disparan
      window_sec=30: ventana deslizante en segundos

    La estructura es `dict[(ip,port)] -> deque[timestamps]`. Cada put purga
    timestamps viejos fuera de la ventana antes de medir. Es hilo-seguro
    (usamos un Lock) porque el guardian y el tab pueden tocarlo al mismo
    tiempo.
    """

    def __init__(self, *, threshold: int = 5, window_sec: float = 30.0):
        self.threshold = max(1, int(threshold))
        self.window_sec = float(window_sec)
        self._counts: dict[tuple[str, int], deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def record(self, ip: str, port: int, now: float | None = None) -> int:
        """Registra un intento. Devuelve el total dentro de la ventana."""
        now = now if now is not None else time.time()
        key = (ip, int(port))
        with self._lock:
            dq = self._counts[key]
            # Purgar viejos
            cutoff = now - self.window_sec
            while dq and dq[0] < cutoff:
                dq.popleft()
            dq.append(now)
            return len(dq)

    def is_bruteforce(self, ip: str, port: int) -> bool:
        """True si esa dupla (ip, puerto) superó el threshold en la ventana."""
        with self._lock:
            dq = self._counts.get((ip, int(port)))
            if not dq:
                return False
            cutoff = time.time() - self.window_sec
            # Recontamos eliminando los viejos (sin tocar la deque original
            # salvo lo necesario para no inflar la memoria a largo plazo).
            live = sum(1 for t in dq if t >= cutoff)
            return live >= self.threshold

    def reset(self, ip: str | None = None, port: int | None = None) -> None:
        """Vacía contadores. Si ip/port dados, sólo esa dupla."""
        with self._lock:
            if ip is None and port is None:
                self._counts.clear()
            else:
                if ip is not None and port is not None:
                    self._counts.pop((ip, int(port)), None)
                elif ip is not None:
                    for k in list(self._counts.keys()):
                        if k[0] == ip:
                            self._counts.pop(k, None)


# ═══════════════════════════════════════════════════════════════════════
#  Eventos (rotación de los últimos N)
# ═══════════════════════════════════════════════════════════════════════

def events_rotate(events: list, max_events: int = 500) -> None:
    """Deja la lista in-place con los últimos `max_events` (mantiene orden)."""
    if len(events) > max_events:
        del events[: len(events) - max_events]


# ═══════════════════════════════════════════════════════════════════════
#  Log a security.log
# ═══════════════════════════════════════════════════════════════════════

_log_lock = threading.Lock()


def _log_dir() -> str:
    if os.name == "nt":
        base = os.getenv("APPDATA", os.path.expanduser("~"))
    else:
        base = os.path.expanduser("~/.config")
    d = os.path.join(base, "FacturaProEC")
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        pass
    return d


def log_security_event(event, path: str | None = None) -> bool:
    """Append-safe de un evento al log. `event` puede ser un dataclass o un
    dict ya serializable. Devuelve True si escribió."""
    if path is None:
        path = os.path.join(_log_dir(), "security.log")
    try:
        if hasattr(event, "__dict__") or hasattr(event, "__dataclass_fields__"):
            try:
                payload = asdict(event)
            except Exception:
                payload = vars(event)
        elif isinstance(event, dict):
            payload = event
        else:
            payload = {"msg": str(event)}
        payload.setdefault("logged_at", datetime.utcnow().isoformat(timespec="seconds"))
        line = (f"[{payload.get('logged_at')}] "
                f"ip={payload.get('ip')} port={payload.get('port')} "
                f"kind={payload.get('kind')} action={payload.get('action')} "
                f"detail={payload.get('detail', '')}\n")
        with _log_lock:
            with open(path, "a", encoding="utf-8") as f:
                f.write(line)
        return True
    except Exception:
        return False
