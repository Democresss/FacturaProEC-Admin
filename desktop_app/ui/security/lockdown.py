"""lockdown — envoltorio del cerrojo de emergencia con auditoría.

El `ServiceRunner.emergency_lockdown()` existe y cierra firewall rules en
Windows (PowerShell `Remove-NetFirewallRule FacturaProEC_*` + disable
`OpenSSH-Server-In-TCP`) y en Linux (ufw deny 21/tcp / iptables). Pero es
fire-and-forget: el caller anterior no registraba QUÉ disparó el cerrojo,
ni a qué hora, ni por qué.

Este wrapper:
  1. Invoca `runner.emergency_lockdown()` y registra el resultado en log.
  2. Devuelve un `LockdownResult` con el detalle (ok, msg, disparador).
  3. Llama a `log_security_event` con el disparador, para que quede en
     `security.log` forever.

Usado por el `SecurityGuardian` cuando `auto_block` está activo y detecta
conexiones no autorizadas. Es seguro reutilizarlo desde el botón "Cerrojo
de Emergencia" de la UI si quiere logging consistente.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from ui.security.connection_audit import log_security_event


@dataclass
class LockdownResult:
    """Resultado del cerrojo de emergencia."""
    ok: bool
    message: str
    triggered_by_ip: Optional[str] = None
    triggered_by_port: Optional[int] = None
    triggered_at: str = ""
    reason: str = ""


def trigger_lockdown(runner, *, reason: str = "", ip: str | None = None,
                     port: int | None = None, log_to_file: bool = True) -> LockdownResult:
    """Ejecuta `ServiceRunner.emergency_lockdown()` y audita el disparador.

    `runner`: instancia de ServiceRunner.
    `reason`: texto libre ("conexión no autorizada", "fuerza bruta").
    `ip`/`port`: el sospechoso que disparó el cerrojo (puede ser None).
    Devuelve LockdownResult. Nunca lanza: si `emergency_lockdown` falla, lo
    registra y devuelve ok=False.
    """
    ts = datetime.utcnow().isoformat(timespec="seconds")
    ok = False
    msg = "Error desconocido"
    try:
        ok_raw, msg_raw = runner.emergency_lockdown()
        ok = bool(ok_raw)
        msg = str(msg_raw if msg_raw is not None else "")
    except Exception as e:
        msg = f"Excepción al activar cerrojo: {e}"
        ok = False

    result = LockdownResult(
        ok=ok, message=msg,
        triggered_by_ip=ip, triggered_by_port=port,
        triggered_at=ts, reason=reason or "Intrusión detectada",
    )
    if log_to_file:
        log_security_event({
            "ip": ip, "port": port,
            "kind": "lockdown", "action": "trigger_lockdown",
            "detail": f"{result.reason} — {result.message}",
        })
    return result
