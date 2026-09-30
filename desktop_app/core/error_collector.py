# -*- coding: utf-8 -*-
"""Módulo Centralizado de Recopilación de Errores y Telemetría.

Captura excepciones, fallos de servicios, conflictos de puertos y errores
de UI/backend, manteniendo un ring-buffer en memoria y persistencia JSON en:
  - Windows: %APPDATA%/FacturaProEC/logs/error_telemetry.json
  - Linux/Mac: ~/.config/FacturaProEC/logs/error_telemetry.json
"""
import os
import sys
import json
import time
import logging
import traceback
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger("error_collector")

def _get_default_log_dir() -> str:
    """Determina la carpeta de logs estándar de FacturaProEC según la plataforma."""
    if sys.platform == "win32":
        app_data = os.environ.get("APPDATA") or os.path.expanduser("~")
        base = os.path.join(app_data, "FacturaProEC", "logs")
    else:
        base = os.path.expanduser("~/.config/FacturaProEC/logs")
    try:
        os.makedirs(base, exist_ok=True)
    except Exception:
        base = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "logs"))
        os.makedirs(base, exist_ok=True)
    return base


class ErrorCollector:
    _instance: Optional["ErrorCollector"] = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(ErrorCollector, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, max_entries: int = 200, log_dir: Optional[str] = None):
        if getattr(self, "_initialized", False):
            return
        self.max_entries = max_entries
        self.log_dir = log_dir or _get_default_log_dir()
        self.log_file = os.path.join(self.log_dir, "error_telemetry.json")
        self.events: List[Dict[str, Any]] = []
        self._load_persisted_events()
        self._initialized = True

    def _load_persisted_events(self):
        """Carga eventos previos si existen en disco."""
        if os.path.exists(self.log_file):
            try:
                with open(self.log_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        self.events = data[-self.max_entries:]
            except Exception as e:
                logger.warning(f"No se pudo leer {self.log_file}: {e}")

    def _persist(self):
        """Guarda la lista de eventos en disco de forma segura."""
        try:
            temp_file = f"{self.log_file}.tmp"
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(self.events, f, indent=2, ensure_ascii=False)
            if os.path.exists(self.log_file):
                os.replace(temp_file, self.log_file)
            else:
                os.rename(temp_file, self.log_file)
        except Exception as e:
            logger.warning(f"No se pudo persistir telemetría de errores: {e}")

    def record_error(
        self,
        category: str = "SYSTEM",
        message: str = "",
        level: str = "ERROR",
        error_code: Optional[str] = None,
        details: Optional[Any] = None,
        context: Optional[Dict[str, Any]] = None,
        suggested_fix: Optional[str] = None,
        exc: Optional[BaseException] = None,
        # Argumentos alias para máxima interoperabilidad
        title: Optional[str] = None,
        detail: Optional[str] = None,
        severity: Optional[str] = None,
        source: Optional[str] = None,
        port: Optional[int] = None,
        code: Optional[str] = None,
        exception: Optional[BaseException] = None,
        stack_trace: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Registra un evento de error o advertencia con metadatos estructurados."""
        eff_msg = message or title or "Error no especificado"
        eff_level = (severity or level or "ERROR").upper()
        eff_details = details if details is not None else detail
        eff_exc = exc or exception
        eff_code = error_code or code or f"ERR_{category.upper()[:4]}"

        stack_str = ""
        if eff_exc is not None:
            stack_str = "".join(traceback.format_exception(type(eff_exc), eff_exc, eff_exc.__traceback__))
        elif stack_trace:
            stack_str = stack_trace
        elif eff_details and isinstance(eff_details, str) and "Traceback" in eff_details:
            stack_str = eff_details

        ctx = dict(context or {})
        if source:
            ctx["source"] = source
        if port:
            ctx["port"] = port
        for k, v in kwargs.items():
            ctx[k] = v

        event = {
            "id": f"err_{int(time.time() * 1000)}_{len(self.events) + 1}",
            "timestamp": datetime.now().isoformat(),
            "level": eff_level,  # INFO, WARNING, ERROR, CRITICAL
            "category": category.upper(),
            "error_code": eff_code,
            "message": str(eff_msg),
            "title": str(eff_msg),
            "details": eff_details if not isinstance(eff_details, Exception) else str(eff_details),
            "stack_trace": stack_str,
            "context": ctx,
            "source": source or "application",
            "port": port,
            "suggested_fix": suggested_fix or "Revisar logs y verificar estado de servicios y puertos.",
            "platform": sys.platform
        }

        self.events.append(event)
        if len(self.events) > self.max_entries:
            self.events = self.events[-self.max_entries:]

        self._persist()

        log_msg = f"[{event['level']}] [{event['category']}] {event['message']}"
        if event['level'] in ("CRITICAL", "ERROR"):
            logger.error(log_msg)
        elif event['level'] == "WARNING":
            logger.warning(log_msg)
        else:
            logger.info(log_msg)

        return event

    def get_errors(
        self,
        category: Optional[str] = None,
        level: Optional[str] = None,
        limit: int = 50,
        severity: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Devuelve los errores más recientes ordenados descendentemente por fecha."""
        filtered = self.events
        lvl_filter = (level or severity or "").upper()
        if category:
            cat_upper = category.upper()
            filtered = [e for e in filtered if e.get("category") == cat_upper]
        if lvl_filter:
            filtered = [e for e in filtered if e.get("level") == lvl_filter]

        return list(reversed(filtered))[:limit]

    def get_stats(self) -> Dict[str, Any]:
        """Calcula estadísticas rápidas de severidad de errores."""
        counts = {"CRITICAL": 0, "ERROR": 0, "WARNING": 0, "INFO": 0}
        for e in self.events:
            lvl = e.get("level", "ERROR").upper()
            counts[lvl] = counts.get(lvl, 0) + 1
        return {
            "total": len(self.events),
            "by_level": counts,
        }

    def clear_errors(self) -> bool:
        """Limpia el buffer de errores en memoria y en disco."""
        self.events = []
        self._persist()
        return True

    def export_diagnostics_report(self, extra_system_info: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Genera un reporte integral de diagnóstico de la aplicación listo para compartir."""
        counts = {"CRITICAL": 0, "ERROR": 0, "WARNING": 0, "INFO": 0}
        for e in self.events:
            lvl = e.get("level", "ERROR")
            counts[lvl] = counts.get(lvl, 0) + 1

        return {
            "report_generated_at": datetime.now().isoformat(),
            "application": "FacturaProEC Admin Platform",
            "version": "2.1.2",
            "platform": sys.platform,
            "python_version": sys.version,
            "log_path": self.log_file,
            "total_errors_recorded": len(self.events),
            "summary_by_level": counts,
            "system_info": extra_system_info or {},
            "recent_events": self.get_errors(limit=25),
        }


# Instancia singleton predeterminada
error_collector = ErrorCollector()
