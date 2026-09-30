"""connection_manager — gestiona el AsyncEngine SQLAlchemy para el DB Viewer.

Construye el engine en runtime con las credenciales que el usuario mete en
la UI (PG local Docker o PG remoto VPN), con cache por URL. Reemplaza el
"test de conexión" puramente TCP del StorageManager original por una
verificación real usando SQLAlchemy `inspect().get_table_names()`.

URL soportadas:
  - PostgreSQL (async):  postgresql+asyncpg://user:pass@host:port/db
  - PostgreSQL (psycopg): postgresql+psycopg2://user:pass@host:port/db  (sync fallback)
  - SQLite fallback:      sqlite+aiosqlite:///RUTA

Si el engine async falla (p.ej. asyncpg no puede conectar), reintenta con
psycopg2 síncrono envuelto en un thread, para no dejar al usuario bloqueado.
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from typing import Optional

from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine
from sqlalchemy.engine import Engine
from sqlalchemy import create_engine, inspect as sync_inspect


_ENGINE_CACHE: dict[str, AsyncEngine] = {}


@dataclass
class DbConfig:
    """Credenciales normalizadas para una conexión."""
    host: str
    port: int
    db: str
    user: str
    password: str
    driver: str = "asyncpg"  # "asyncpg" (async) | "psycopg2" (sync) | "sqlite"

    def to_async_url(self) -> str:
        if self.driver == "sqlite":
            return f"sqlite+aiosqlite:///{self.db}"
        # Si password vacío, no lo inyecta (algunos PG locales sin pass).
        auth = f"{self.user}:{self.password}@" if self.password or self.user else ""
        return f"postgresql+asyncpg://{auth}{self.host}:{self.port}/{self.db}"

    def to_sync_url(self) -> str:
        auth = f"{self.user}:{self.password}@" if self.password or self.user else ""
        return f"postgresql+psycopg2://{auth}{self.host}:{self.port}/{self.db}"


class ConnectionManager:
    """Cache de engines async por URL + helpers de test/inspect síncrono."""

    def get_async_engine(self, cfg: DbConfig, *, refresh: bool = False) -> AsyncEngine:
        url = cfg.to_async_url()
        if refresh:
            self.dispose(url)
        eng = _ENGINE_CACHE.get(url)
        if eng is None:
            eng = create_async_engine(url, echo=False, pool_pre_ping=True)
            _ENGINE_CACHE[url] = eng
        return eng

    def dispose(self, url: Optional[str] = None):
        """Cierra y elimina el engine cacheado (uno o todos)."""
        if url is None:
            for eng in _ENGINE_CACHE.values():
                try:
                    # AsyncEngine.dispose es sync-release-friendly (sincroniza)
                    import asyncio
                    asyncio.get_event_loop_policy()
                    # Llamar al dispose async dentro de run_until_complete
                    try:
                        loop = asyncio.new_event_loop()
                        loop.run_until_complete(eng.dispose())
                        loop.close()
                    except Exception:
                        eng.sync_engine.dispose()
                except Exception:
                    pass
            _ENGINE_CACHE.clear()
        else:
            eng = _ENGINE_CACHE.pop(url, None)
            if eng is not None:
                try:
                    eng.sync_engine.dispose()
                except Exception:
                    pass

    # ─── Test real: lista tablas síncrono en un hilo ─────────────
    def test_connection(self, cfg: DbConfig) -> tuple[bool, str, list[str]]:
        """Verifica conexión real intentando listar tablas.

        Intenta primero el driver async (asyncpg via SQLAlchemy). Si lanza
        al conectarse, reintenta con psycopg2 síncrono en el mismo hilo.
        Retorna (ok, mensaje_humanizado, lista_tablas).
        """
        # Async primero (más fiel al flujo de FacProV2)
        ok, msg, tables = self._test_async(cfg)
        if ok:
            return (True, msg, tables)

        # Fallback síncrono con psycopg2
        ok2, msg2, tables2 = self._test_sync_psycopg2(cfg)
        if ok2:
            return (True, f"{msg2} (usando psycopg2 síncrono)", tables2)
        # Fracasamos ambos → combina el error
        return (False, f"{msg}\n\nIntento síncrono: {msg2}", [])

    def _test_async(self, cfg: DbConfig) -> tuple[bool, str, list[str]]:
        import asyncio
        async def _run():
            eng = self.get_async_engine(cfg)
            async with eng.connect() as conn:
                # SQLAlchemy 2.0: asíncrono inspección vía run_sync
                from sqlalchemy import inspect
                names = await conn.run_sync(
                    lambda sync_conn: inspect(sync_conn).get_table_names()
                )
                return names
        try:
            loop = asyncio.new_event_loop()
            try:
                names = loop.run_until_complete(_run())
            finally:
                loop.close()
            return (True,
                    f"✅ Conexión real OK a {cfg.host}:{cfg.port}/{cfg.db}. "
                    f"{len(names)} tablas visibles.",
                    names)
        except Exception as e:
            return (False, f"asyncpg falló: {e.__class__.__name__}: {e}", [])

    def _test_sync_psycopg2(self, cfg: DbConfig) -> tuple[bool, str, list[str]]:
        try:
            eng = create_engine(cfg.to_sync_url(), pool_pre_ping=True, future=True)
            with eng.connect() as conn:
                names = sync_inspect(conn).get_table_names()
            eng.dispose()
            return (True, f"✅ Conexión OK a {cfg.host}:{cfg.port}/{cfg.db}. "
                          f"{len(names)} tablas visibles.", names)
        except Exception as e:
            return (False, f"{e.__class__.__name__}: {e}", [])


# Singleton ligero (un proceso = un cache de engines).
_default = ConnectionManager()


def get_default() -> ConnectionManager:
    return _default
