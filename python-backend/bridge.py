"""bridge — Backend FastAPI local que el renderer Electron consume.

Reutiliza TODA la lógica Python ya construida en desktop_app/:
  - sys_info (detección multiplataforma de servicios, netstat/ss)
  - service_runner (Docker, firewall, SFTP, FTP, PG, autostart)
  - config_manager (persistencia en %APPDATA%/~/.config)
  - connection_manager (AsyncEngine SQLAlchemy para DB Viewer)
  - table_explorer (reflection + paginación)
  - query_runner (SQL read-only + CSV)
  - sri_facade (IMAP + parse XML + RUC + persistencia inbox)
  - guardian (SecurityGuardian watchdog)

El bridge escucha en 127.0.0.1:PORT (PORT efímero: lo elige SO, lo
imprime el main de Electron al stdout y lo lee el preload).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import threading
from pathlib import Path
from typing import Any, Optional

# Añadir el desktop_app al path para importar los módulos existentes
# Dev: desde admin-electron/python-backend/ → ../../desktop_app
# Prod (empaquetado): el desktop_app se copia a resources/desktop-app (con guion)
#                     pero el código lo importa como "desktop_app" (con underscore).
# Manejamos ambos nombres para que funcione en dev y en build.
_HERE = Path(__file__).resolve().parent
_CANDIDATES = [
    _HERE.parent.parent / "desktop_app",                          # dev
    Path(__file__).resolve().parent.parent / "desktop_app",       # extraResources/python-backend/.. (underscore)
    Path(__file__).resolve().parent.parent / "desktop-app",       # idem pero con guion (empaquetado real)
    Path(os.environ.get("RESOURCES_PATH", "")) / "desktop-app",  # packaged resourcesPath
    Path(os.environ.get("RESOURCES_PATH", "")) / "desktop_app",  # idem underscore
]
for _c in _CANDIDATES:
    if _c.exists() and str(_c) not in sys.path:
        sys.path.insert(0, str(_c))
        break

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from config_manager import ConfigManager
from service_runner import ServiceRunner
from sys_info import (
    is_admin, get_local_ip, get_disk_info, count_local_files,
    check_port_open, ping_host, detect_local_services,
    check_active_net_connections, test_sftp_full_connection,
)
from ui.tabs.db_viewer.connection_manager import DbConfig, get_default as get_cm
from ui.tabs.db_viewer.table_explorer import TableExplorer
from ui.tabs.db_viewer.query_runner import QueryRunner, QueryResult
from ui.sri.sri_facade import SRIFacade
from ui.security.guardian import SecurityGuardian
from ui.security.connection_audit import (
    whitelist_load, whitelist_save,
)

logger = logging.getLogger("bridge")
logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(name)s %(levelname)s: %(message)s")

# ── Singletons globales (antes de la app para que el lifespan los vea) ─
_config = ConfigManager()
_runner = ServiceRunner(_config)
_known_safe_ips: set[str] = {"127.0.0.1", "0.0.0.0", "::1"}
_guardian = SecurityGuardian(_config, _runner, _known_safe_ips)
_sri_facade_cache: dict[str, SRIFacade] = {}
_guardian_thread: Optional[threading.Thread] = None
_guardian_stop = threading.Event()


# ── Guardian loop (definido antes del lifespan que lo arranca) ─────
def _guardian_loop():
    """Loop de vigilancia (cada 5s) en hilo daemon."""
    while not _guardian_stop.is_set():
        try:
            _guardian.scan()
        except Exception as e:
            logger.warning(f"guardian scan: {e}")
        _guardian_stop.wait(5.0)


# ── Lifespan (reemplaza on_event startup/shutdown) ────────────────
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app_: FastAPI):
    global _guardian_thread
    _guardian_thread = threading.Thread(target=_guardian_loop, daemon=True)
    _guardian_thread.start()
    logger.info("Guardian loop iniciado")
    yield
    _guardian_stop.set()
    get_cm().dispose()
    logger.info("Bridge cerrado")


app = FastAPI(title="FacturaProEC Admin Bridge", version="2.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # sólo 127.0.0.1 local
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ───────────────────────────── helpers ─────────────────────────────
def _dbcfg_from_payload(p: dict) -> DbConfig:
    """Construye DbConfig desde payload del renderer. Prioriza VPN si hay."""
    r_host = p.get("pg_remote_host") or ""
    if r_host:
        return DbConfig(
            host=r_host,
            port=int(p.get("pg_remote_port", 5432) or 5432),
            db=p.get("pg_remote_db") or p.get("pg_db", "facturapro_db"),
            user=p.get("pg_remote_user") or "",
            password=p.get("pg_remote_pass") or "",
            driver="asyncpg",
        )
    return DbConfig(
        host=p.get("pg_host", "127.0.0.1"),
        port=int(p.get("pg_port", 5432) or 5432),
        db=p.get("pg_db", "facturapro_db"),
        user=p.get("pg_user", "postgres_user"),
        password=p.get("pg_pass", "ClaveSegura123!"),
        driver="asyncpg",
    )


def _get_sri_facade(cfg: DbConfig) -> SRIFacade:
    key = cfg.to_async_url()
    if key not in _sri_facade_cache:
        _sri_facade_cache[key] = SRIFacade(cfg)
    return _sri_facade_cache[key]


def _run_async(coro):
    """Ejecuta una corrutina en un loop fresco (seguro desde hilo FastAPI)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ───────────────────────────── models ──────────────────────────────
class ConfigUpdate(BaseModel):
    data: dict[str, Any]


class DbConnectPayload(BaseModel):
    pg_host: str = "127.0.0.1"
    pg_port: int = 5432
    pg_db: str = "facturapro_db"
    pg_user: str = "postgres_user"
    pg_pass: str = ""
    pg_remote_host: str = ""
    pg_remote_port: int = 5432
    pg_remote_db: str = "facturapro_db"
    pg_remote_user: str = ""
    pg_remote_pass: str = ""


class SqlPayload(BaseModel):
    sql: str
    pg_host: str = "127.0.0.1"
    pg_port: int = 5432
    pg_db: str = "facturapro_db"
    pg_user: str = "postgres_user"
    pg_pass: str = ""
    pg_remote_host: str = ""
    pg_remote_port: int = 5432
    pg_remote_db: str = "facturapro_db"
    pg_remote_user: str = ""
    pg_remote_pass: str = ""
    max_rows: int = 500


class ImapPayload(BaseModel):
    host: str = "imap.gmail.com"
    port: int = 993
    user: str = ""
    password: str = ""
    folder: str = "INBOX"
    limit: int = 50
    org_id: str = "default"
    pg_host: str = "127.0.0.1"
    pg_port: int = 5432
    pg_db: str = "facturapro_db"
    pg_user: str = "postgres_user"
    pg_pass: str = ""
    pg_remote_host: str = ""
    pg_remote_port: int = 5432
    pg_remote_db: str = "facturapro_db"
    pg_remote_user: str = ""
    pg_remote_pass: str = ""


class RucPayload(BaseModel):
    ruc: str


class SftpTestPayload(BaseModel):
    host: str
    port: int = 22
    user: str = ""
    password: str = ""
    folder: str = ""


class FtpTempPayload(BaseModel):
    minutes: int = 30
    remote_ip: str = ""


class WhitelistPayload(BaseModel):
    ip: str


class GuardianConfigPayload(BaseModel):
    shield_active: Optional[bool] = None
    auto_block: Optional[bool] = None
    ports: Optional[list[int]] = None


# ───────────────────────────── endpoints: sistema ──────────────────
@app.get("/api/system/info")
def system_info():
    try:
        return {
            "ok": True,
            "is_admin": is_admin(),
            "local_ip": get_local_ip(),
            "disk": get_disk_info(),
            "file_count": count_local_files(),
            "services": detect_local_services(),
            "platform": sys.platform,
            "python": sys.version.split()[0],
        }
    except Exception as e:
        return {"ok": False, "error": f"{e.__class__.__name__}: {e}"}


@app.get("/api/system/ping")
def system_ping(host: str):
    return {"ok": ping_host(host)}


@app.get("/api/system/port")
def system_port(host: str, port: int):
    return {"ok": check_port_open(host, port)}


# ───────────────────────────── endpoints: config ───────────────────
@app.get("/api/config")
def get_config():
    return {"ok": True, "data": _config.data}


@app.post("/api/config")
def set_config(payload: ConfigUpdate):
    try:
        for k, v in payload.data.items():
            _config.set(k, v)
        return {"ok": True, "data": _config.data}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/config/{key}")
def set_config_key(key: str, payload: dict):
    try:
        _config.set(key, payload.get("value"))
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ───────────────────────────── endpoints: service runner ───────────
@app.post("/api/storage/ensure")
def storage_ensure(path: str = ""):
    return _result(_runner.ensure_storage_folder(path or None))


@app.post("/api/sftp/create-user")
def sftp_create_user(payload: dict):
    return _result(_runner.create_restricted_sftp_user(
        username=payload.get("username", "factura_sftp"),
        password=payload.get("password", "ClaveSFTP123!"),
        folder_path=payload.get("folder", ""),
    ))


@app.post("/api/sftp/install-openssh")
def sftp_install_openssh():
    return _result(_runner.install_and_start_openssh_server())


@app.post("/api/docker/launch")
def docker_launch():
    return _result(_runner.launch_docker_stack())


@app.get("/api/docker/installed")
def docker_installed():
    return {"ok": _runner.check_docker_installed()}


@app.post("/api/firewall/pg")
def firewall_pg():
    return _result(_runner.open_pg_port_firewall())


@app.post("/api/firewall/sftp")
def firewall_sftp():
    return _result(_runner.open_sftp_port_firewall())


@app.post("/api/firewall/ftp-temp")
def firewall_ftp_temp(payload: FtpTempPayload):
    return _result(_runner.open_temporary_ftp(
        minutes=payload.minutes, remote_ip=payload.remote_ip or None,
    ))


@app.post("/api/firewall/ftp-perm")
def firewall_ftp_perm(payload: dict):
    return _result(_runner.open_permanent_ftp(remote_ip=payload.get("remote_ip") or None))


@app.post("/api/firewall/ftp-cancel")
def firewall_ftp_cancel():
    return _result(_runner.cancel_temporary_ftp())


@app.post("/api/firewall/lockdown")
def firewall_lockdown():
    return _result(_runner.emergency_lockdown())


@app.post("/api/autostart")
def autostart(payload: dict):
    return _result(_runner.set_autostart(enable=bool(payload.get("enable", True))))


@app.post("/api/sftp/test-full")
def sftp_test_full(payload: SftpTestPayload):
    ok, msg = test_sftp_full_connection(
        payload.host, payload.port, payload.user, payload.password, payload.folder,
    )
    return {"ok": ok, "message": msg}


# ───────────────────────────── endpoints: DB Viewer ───────────────
@app.post("/api/db/connect")
def db_connect(payload: DbConnectPayload):
    """Lista tablas + test real de conexión."""
    try:
        cfg = _dbcfg_from_payload(payload.dict())
        ok, msg, tables = get_cm().test_connection(cfg)
        return {"ok": ok, "message": msg, "tables": tables}
    except Exception as e:
        return {"ok": False, "message": f"{e.__class__.__name__}: {e}", "tables": []}


@app.post("/api/db/refresh")
def db_refresh(payload: DbConnectPayload):
    cfg = _dbcfg_from_payload(payload.dict())
    get_cm().dispose(cfg.to_async_url())
    ok, msg, tables = get_cm().test_connection(cfg)
    return {"ok": ok, "message": msg, "tables": tables}


@app.post("/api/db/structure")
def db_structure(payload: dict):
    cfg = _dbcfg_from_payload(payload)
    table = payload.get("table", "")
    if not table:
        return {"ok": False, "message": "Falta nombre de tabla."}
    explorer = TableExplorer(cfg)
    ok, msg, cols = explorer.describe(table)
    if ok:
        # serializar: cols son dicts
        return {"ok": True, "message": msg, "columns": cols}
    return {"ok": False, "message": msg}


@app.post("/api/db/data")
def db_data(payload: dict):
    cfg = _dbcfg_from_payload(payload)
    table = payload.get("table", "")
    offset = int(payload.get("offset", 0))
    limit = int(payload.get("limit", 100))
    if not table:
        return {"ok": False, "message": "Falta tabla."}
    explorer = TableExplorer(cfg)
    try:
        ok, msg, page = explorer.page(table, offset=offset, limit=limit)
        if ok:
            return {
                "ok": True, "message": msg,
                "columns": page.columns,
                "rows": [_serialize_row(r) for r in page.rows],
                "total_approx": page.total_approx,
            }
        return {"ok": False, "message": msg}
    except Exception as e:
        return {"ok": False, "message": f"{e.__class__.__name__}: {e}"}


@app.post("/api/db/sql")
def db_sql(payload: SqlPayload):
    cfg = _dbcfg_from_payload(payload.dict())
    qr = QueryRunner(cfg, max_rows=payload.max_rows)
    ok, msg, res = qr.run(payload.sql)
    if ok and res:
        return {
            "ok": True, "message": msg,
            "columns": res.columns,
            "rows": [_serialize_row(r) for r in res.rows],
            "csv": QueryRunner.to_csv(res),
        }
    return {"ok": False, "message": msg}


@app.post("/api/db/export-csv")
def db_export_csv(payload: dict):
    cfg = _dbcfg_from_payload(payload)
    table = payload.get("table", "")
    if not table:
        return {"ok": False, "message": "Falta tabla."}
    explorer = TableExplorer(cfg)
    ok, msg, page = explorer.page(table, offset=0, limit=10000)
    if not ok:
        return {"ok": False, "message": msg}
    import csv as _csv
    import io as _io
    out = _io.StringIO()
    w = _csv.writer(out, lineterminator="\n")
    w.writerow(page.columns)
    for r in page.rows:
        w.writerow([_csv_cell(c) for c in r])
    return {"ok": True, "csv": out.getvalue(), "columns": page.columns, "rowcount": len(page.rows)}


@app.post("/api/db/active-connections")
def db_active_connections(payload: dict):
    """Lista viva de conexiones a PG vía pg_stat_activity."""
    cfg = _dbcfg_from_payload(payload)
    try:
        async def _run():
            from sqlalchemy import text
            eng = get_cm().get_async_engine(cfg)
            async with eng.connect() as conn:
                rows = (await conn.execute(text(
                    "SELECT pid, usename, client_addr, state, query, "
                    "now() - query_start AS duration "
                    "FROM pg_stat_activity WHERE datname IS NOT NULL "
                    "ORDER BY query_start DESC NULLS LAST LIMIT 50"
                ))).all()
                return [dict(r._mapping) for r in rows]
        data = _run_async(_run())
        # serializar
        for r in data:
            if r.get("client_addr") is not None:
                r["client_addr"] = str(r["client_addr"])
            if r.get("duration") is not None:
                r["duration"] = str(r["duration"])
        return {"ok": True, "connections": data}
    except Exception as e:
        return {"ok": False, "message": f"{e.__class__.__name__}: {e}"}


# ───────────────────────────── endpoints: SRI ─────────────────────
@app.post("/api/sri/test-imap")
def sri_test_imap(payload: ImapPayload):
    cfg = _dbcfg_from_payload(payload.dict())
    facade = _get_sri_facade(cfg)
    ok, msg = facade.test_imap(
        payload.host, payload.port, payload.user, payload.password, payload.folder,
    )
    return {"ok": ok, "message": msg}


@app.post("/api/sri/sync")
def sri_sync(payload: ImapPayload):
    cfg = _dbcfg_from_payload(payload.dict())
    facade = _get_sri_facade(cfg)
    stats = facade.sync_inbox(
        payload.host, payload.port, payload.user, payload.password,
        folder=payload.folder, limit=payload.limit or 50,
        org_id=payload.org_id or "default",
    )
    return {
        "ok": True,
        "stats": {
            "emails_processados": stats.emails_processados,
            "comprobantes_encontrados": stats.comprobantes_encontrados,
            "comprobantes_nuevos": stats.comprobantes_nuevos,
            "comprobantes_duplicados": stats.comprobantes_duplicados,
            "errores": stats.errores,
            "detalle": stats.detalle,
        }
    }


@app.get("/api/sri/inbox")
def sri_inbox(limit: int = 50, offset: int = 0,
              pg_host: str = "127.0.0.1", pg_port: int = 5432,
              pg_db: str = "facturapro_db", pg_user: str = "postgres_user",
              pg_pass: str = "",
              pg_remote_host: str = "", pg_remote_port: int = 5432,
              pg_remote_db: str = "facturapro_db", pg_remote_user: str = "",
              pg_remote_pass: str = ""):
    cfg = _dbcfg_from_payload({
        "pg_host": pg_host, "pg_port": pg_port, "pg_db": pg_db,
        "pg_user": pg_user, "pg_pass": pg_pass,
        "pg_remote_host": pg_remote_host, "pg_remote_port": pg_remote_port,
        "pg_remote_db": pg_remote_db, "pg_remote_user": pg_remote_user,
        "pg_remote_pass": pg_remote_pass,
    })
    facade = _get_sri_facade(cfg)
    ok, msg, rows = facade.list_inbox(limit=limit, offset=offset)
    return {"ok": ok, "message": msg, "rows": rows}


@app.post("/api/sri/ruc")
def sri_ruc(payload: RucPayload):
    cfg = _dbcfg_from_payload({
        "pg_host": "127.0.0.1", "pg_db": "facturapro_db",
        "pg_user": "postgres_user", "pg_pass": "ClaveSegura123!",
    })
    facade = _get_sri_facade(cfg)
    ok, msg, data = facade.consultar_ruc(payload.ruc)
    return {"ok": ok, "message": msg, "data": data}


# ───────────────────────────── endpoints: security ────────────────
@app.get("/api/security/status")
def security_status():
    return {
        "ok": True,
        "shield_active": _guardian.shield_active,
        "auto_block": _guardian.auto_block,
        "ports": _guardian.get_ports(),
        "whitelist": whitelist_load(_config),
        "events": [e.__dict__ if hasattr(e, "__dict__") else str(e)
                    for e in _guardian.events[-100:]],
    }


@app.post("/api/security/config")
def security_config_set(payload: GuardianConfigPayload):
    if payload.shield_active is not None:
        _guardian.set_shield_active(payload.shield_active)
    if payload.auto_block is not None:
        _guardian.set_auto_block(payload.auto_block)
    if payload.ports is not None:
        _guardian.set_ports(payload.ports)
    return {"ok": True}


@app.post("/api/security/whitelist/add")
def security_whitelist_add(payload: WhitelistPayload):
    _guardian.add_safe_ip(payload.ip)
    return {"ok": True, "whitelist": whitelist_load(_config)}


@app.post("/api/security/whitelist/remove")
def security_whitelist_remove(payload: WhitelistPayload):
    _guardian.remove_safe_ip(payload.ip)
    return {"ok": True, "whitelist": whitelist_load(_config)}


@app.post("/api/security/scan")
def security_scan():
    result = _guardian.scan()
    return {
        "ok": True,
        "alerts": [a.__dict__ for a in result.alerts],
        "bruteforce_pairs": result.bruteforce_pairs,
        "has_lockdown": result.lockdown is not None,
    }


@app.get("/api/security/check-connections")
def security_check_connections():
    """Ejecuta check_active_net_connections directamente."""
    ports = _guardian.get_ports()
    allowed = _guardian.get_allowed_ips()
    suspicious = check_active_net_connections(ports, allowed)
    return {"ok": True, "suspicious": suspicious, "allowed_ips": list(allowed)}


# ───────────────────────────── helpers ────────────────────────────
def _result(t: tuple):
    """Normaliza (ok_bool, msg) → dict."""
    if isinstance(t, tuple) and len(t) >= 2:
        return {"ok": bool(t[0]), "message": str(t[1])}
    return {"ok": False, "message": "Resultado inesperado"}


def _serialize_row(row) -> list:
    """Convierte una fila de SQLAlchemy a lista JSON-safe."""
    out = []
    for v in row:
        out.append(_csv_cell(v) if not isinstance(v, (int, float, bool, type(None))) else v)
    return out


def _csv_cell(v) -> str:
    if v is None:
        return None
    if isinstance(v, (bytes, bytearray)):
        try:
            return v.decode("utf-8", errors="replace")[:200]
        except Exception:
            return f"<{len(v)} bytes>"
    if isinstance(v, (int, float, bool)):
        return v
    s = str(v)
    return s if len(s) <= 300 else s[:297] + "…"


# ───────────────────────────── entrypoint ──────────────────────────
def main():
    import uvicorn
    port = int(os.environ.get("BRIDGE_PORT", "0"))
    if port == 0:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
    # Imprimir el puerto para que el Electron main lo lea del stdout
    print(f"BRIDGE_PORT={port}", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
