"""guardian — SecurityGuardian desacoplado del loop de UI.

Reemplaza al `_security_guardian_loop` legacy (líneas 305-331 de
`ui/app_shell.py`) que tenía tres defectos:
  1. Hacía `break` tras el primer sospechoso → perdía el resto.
  2. Llamaba `Modal.error(...)` directamente desde el `after(5000)` →
     bloqueaba la UI con un messagebox/Toplevel.
  3. Era Windows-only (porque `check_active_net_connections` era Windows-only).

El nuevo `SecurityGuardian.scan()`:
  - Llama a `check_active_net_connections(ports, allowed_ips)` multiplataforma.
  - Filtra con `allowed_ips = known_safe_ips ∪ {remote_host} ∪ whitelist`.
  - Para CADA sospechoso: registra intento en `BruteForceCounter`, agrega
    un `Alert` a `self.events`, loguea en `security.log`.
  - NO muestra modales: el caller decide (modal si ventana visible, o
    notificación del tray si está oculta). El guardian es puro lógica.
  - Si `auto_block` activo y hay sospechosos: dispara
    `lockdown.trigger_lockdown(...)` una sola vez por tick (no por alert)
    y marca el primer IP+puerto como responsable.

El `SecurityGuardian` es hilo-seguro (los contadores usan locks) pero el
`scan()` se invoca desde el hilo de UI vía `root.after(5000, ...)` igual
que el original — no creamos un hilo nuevo, no agregamos concurrencia.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional

from sys_info import check_active_net_connections
from ui.security.connection_audit import (
    BruteForceCounter, whitelist_load, whitelist_save,
    events_rotate, log_security_event,
)
from ui.security.lockdown import trigger_lockdown, LockdownResult


@dataclass
class Alert:
    """Una alerta detectada por el guardian."""
    timestamp: str                  # ISO format
    ip: str
    port: int
    kind: str                      # 'unauthorized' | 'bruteforce'
    full_addr: str = ""
    detail: str = ""


@dataclass
class ScanResult:
    """Resultado de un tick de scan()."""
    alerts: list[Alert] = field(default_factory=list)
    lockdown: Optional[LockdownResult] = None
    bruteforce_pairs: list[tuple[str, int]] = field(default_factory=list)


def es_de_internet(ip: str) -> bool:
    """True solo para IPs públicas. Las de la red interna (192.168.x, 10.x, 172.16-31.x), Docker/WSL, loopback,
    link-local y 100.64/10 no son un intruso: antes disparaban el cerrojo y borraban las reglas del firewall."""
    import ipaddress
    try:
        d = ipaddress.ip_address(str(ip or "").split("%")[0].strip("[]"))
    except ValueError:
        return False
    if getattr(d, "ipv4_mapped", None):
        d = d.ipv4_mapped
    if d.is_private or d.is_loopback or d.is_link_local or d.is_unspecified or d.is_reserved or d.is_multicast:
        return False
    if d.version == 4 and d in ipaddress.ip_network("100.64.0.0/10"):   # CGNAT
        return False
    return True


class SecurityGuardian:
    """Watchdog de conexiones de red. Desacoplado de la UI.

    Constructor:
      config        : ConfigManager
      runner        : ServiceRunner
      known_safe_ips: set mutable compartido con AppShell (lo mutamos in-place
                      desde el security_tab para añadir IPs a la whitelist).
    Estado persistente (en ConfigManager):
      security_shield_active, security_auto_block, security_whitelist,
      security_ports.

    API principal: `scan() -> ScanResult`. Re-armar con `root.after(...)`.
    """

    def __init__(self, config, runner, known_safe_ips: set,
                 *, max_events: int = 500):
        self.config = config
        self.runner = runner
        self.known_safe_ips = known_safe_ips  # set compartido (mutamos in-place)
        self.events: list[Alert] = []
        self.max_events = max_events

        # Brute force: 5 intentos del mismo (ip, puerto) en 30s = alerta
        self.bf_counter = BruteForceCounter(threshold=5, window_sec=60.0)

        # Carga inicial de whitelist desde config
        # (la whitelist vive en config.security_whitelist, pero también la
        # sincronizamos con known_safe_ips en runtime para que el scan la
        # respete immediatamente sin releer disco en cada tick).
        self._sync_whitelist_into_safe_ips()

        # Estado in-memory. `auto_block` y `shield_active` se leen del
        # config en cada scan() (así un toggle desde el security_tab surte
        # efecto sin tener que reiniciar el guardian).
        self.last_scan_result: Optional[ScanResult] = None

        # Callback opcional para 'on_lockdown' (lo usa el AppShell para
        # disparar modal o notificación de tray). Se setea desde fuera.
        self.on_lockdown: Optional[Callable[[LockdownResult], None]] = None

    # ─── Config-aware accessors ───────────────────────────────────────

    @property
    def shield_active(self) -> bool:
        return bool(self.config.get("security_shield_active", True))

    @property
    def auto_block(self) -> bool:
        return bool(self.config.get("security_auto_block", True))

    def get_ports(self) -> list[int]:
        ports = self.config.get("security_ports", [21, 22, 2022, 5432])
        if not isinstance(ports, (list, tuple)):
            return [21, 22, 2022, 5432]
        return [int(p) for p in ports]

    def get_allowed_ips(self) -> set[str]:
        """Combina known_safe_ips + remote_host del config + whitelist."""
        allowed = set(self.known_safe_ips or set())
        allowed |= {"127.0.0.1", "0.0.0.0", "::1"}
        rgb = self.config.get("remote_host", "")
        if rgb and isinstance(rgb, str) and rgb.strip():
            allowed.add(rgb.strip())
        allowed |= set(whitelist_load(self.config))
        return allowed

    # ─── API pública: el tick del loop ────────────────────────────────

    def scan(self) -> ScanResult:
        """Un tick de vigilancia. Devuelve ScanResult con alerts y lockdown.

        No toca tkinter. El AppShell decide cómo mostrar el resultado.
        """
        result = ScanResult()
        if not self.shield_active:
            # Si el escudo está apagado, no hacemos nada pero registra que
            # se llamó (sin congelar nada).
            self.last_scan_result = result
            return result

        try:
            ports = self.get_ports()
            allowed = self.get_allowed_ips()
        except Exception:
            ports = [21, 22, 2022, 5432]
            allowed = self.known_safe_ips

        try:
            suspicious = check_active_net_connections(ports, allowed)
        except Exception as e:
            # No romper el loop por un fallo de netstat/ss
            suspicious = []
            log_security_event({
                "ip": None, "port": None,
                "kind": "scan_error", "action": "scan",
                "detail": f"{e.__class__.__name__}: {e}",
            })

        if not suspicious:
            self.last_scan_result = result
            return result

        # Defensa en profundidad: además del filtrado que ya hace
        # check_active_net_connections contra allowed_ips, volvemos a
        # filtrar aquí (algunos backends — p.ej. mock en tests, o un
        # futuro ss parser con bug— podrían no respetar el allowlist).
        suspicious = [s for s in suspicious
                       if (s.get("remote_ip") or "") not in allowed and es_de_internet(s.get("remote_ip") or "")]

        if not suspicious:
            self.last_scan_result = result
            return result

        # Por cada sospechoso: registramos intento + Alert
        bruteforce_pairs: list[tuple[str, int]] = []
        for s in suspicious:
            ip = s.get("remote_ip", "")
            port = int(s.get("port", 0))
            if not ip or port <= 0:
                continue
            # Registrar en contador de fuerza bruta
            count = self.bf_counter.record(ip, port)
            kind = "bruteforce" if self.bf_counter.is_bruteforce(ip, port) else "unauthorized"
            if kind == "bruteforce":
                bruteforce_pairs.append((ip, port))

            alert = Alert(
                timestamp=datetime.utcnow().isoformat(timespec="seconds"),
                ip=ip, port=port, kind=kind,
                full_addr=s.get("full_addr", ""),
                detail=f"conexión {kind} ({count} intentos en ventana)",
            )
            self.events.append(alert)
            # Log a archivo
            log_security_event({
                "ip": ip, "port": port,
                "kind": kind, "action": "detect",
                "detail": alert.detail,
            })

        # Rotación de eventos (evitar memoria infinita)
        events_rotate(self.events, self.max_events)

        result.alerts = list(self.events[-len(suspicious):])
        result.bruteforce_pairs = bruteforce_pairs

        # Auto-block: si hay sospechosos y el toggle está activo, disparamos
        # lockdown UNA vez por tick (usando el primer sospechoso como
        # responsable en el log).
        lock_res = None
        if self.auto_block and result.alerts:
            first = result.alerts[0]
            reason = ("Posible fuerza bruta detectada "
                      if bruteforce_pairs else
                      "Conexión no autorizada detectada")
            lock_res = trigger_lockdown(
                self.runner,
                reason=reason,
                ip=first.ip, port=first.port,
                log_to_file=True,
            )
            # Loguear cada uno restante como contexto adicional
            for a in result.alerts[1:]:
                log_security_event({
                    "ip": a.ip, "port": a.port,
                    "kind": a.kind, "action": "secondary_detected",
                    "detail": f"coincidía con el cerrojo disparado por {first.ip}:{first.port}",
                })

            # Notificar al caller (AppShell/tray) — pero no desde aquí
            if self.on_lockdown is not None:
                try:
                    self.on_lockdown(lock_res)
                except Exception:
                    pass

        result.lockdown = lock_res
        self.last_scan_result = result
        return result

    # ─── Mutadores (usados por el SecurityTab) ───────────────────────

    def add_safe_ip(self, ip: str) -> None:
        """Añadir IP a la whitelist persistente + known_safe_ips."""
        ip = (ip or "").strip()
        if not ip:
            return
        self.known_safe_ips.add(ip)  # mutable in-place
        wl = whitelist_load(self.config)
        if ip not in wl:
            wl.append(ip)
            whitelist_save(self.config, wl)

    def remove_safe_ip(self, ip: str) -> None:
        """Quitar una IP de la whitelist persistente + known_safe_ips."""
        ip = (ip or "").strip()
        if not ip:
            return
        self.known_safe_ips.discard(ip)  # mutable in-place
        wl = whitelist_load(self.config)
        wl = [x for x in wl if x != ip]
        whitelist_save(self.config, wl)

    def set_shield_active(self, active: bool) -> None:
        """Toggle del escudo. Persiste en config."""
        self.config.set("security_shield_active", bool(active))

    def set_auto_block(self, enabled: bool) -> None:
        self.config.set("security_auto_block", bool(enabled))

    def set_ports(self, ports: list[int]) -> None:
        try:
            ports = [int(p) for p in ports if int(p) > 0]
        except Exception:
            return
        if ports:
            self.config.set("security_ports", ports)

    def set_max_events(self, n: int):
        self.max_events = max(50, int(n))

    def clear_events(self) -> None:
        self.events.clear()

    def clear_bf_counter(self, ip: str | None = None, port: int | None = None):
        self.bf_counter.reset(ip=ip, port=port)

    # ─── Helpers internos ─────────────────────────────────────────────

    def _sync_whitelist_into_safe_ips(self) -> None:
        """Al construir el guardian, empuja la whitelist persistida dentro
        del set `known_safe_ips` compartido con AppShell. Así un reinicio
        no pierde las IPs que el usuario aprobó antes."""
        try:
            for ip in whitelist_load(self.config):
                self.known_safe_ips.add(ip)
        except Exception:
            pass
