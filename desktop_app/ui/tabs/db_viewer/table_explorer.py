"""table_explorer — reflection y lectura paginada de tablas para el DB Viewer.

Métodos síncronos pensados para ejecutarse dentro de un hilo del
`AsyncActionRunner` (no tocan tkinter). La UI los invoca vía AsyncButton y
recibe los resultados como `(ok, msg, data)`-ish donde aplica.

Aprovecha SQLAlchemy `inspect()` para reflection:
  - get_table_names()
  - get_columns(table)
  - get_primary_keys(table) para ordenación por defecto de la paginación

El row count aproximado usa `pg_class.reltuples` en PostgreSQL (rápido,
sin contar) y `COUNT(*)` en SQLite u otros. Esto evita bloquear la UI en
tablas enormes.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy import inspect as sync_inspect, text
from sqlalchemy.ext.asyncio import AsyncEngine

from .connection_manager import DbConfig, get_default


@dataclass
class TableInfo:
    name: str
    columns: list[dict]            # [{name, type, nullable, primary_key}, ...]
    approx_rows: Optional[int] = None


@dataclass
class PageResult:
    columns: list[str]
    rows: list[list[Any]]
    offset: int
    limit: int
    total_approx: Optional[int]


class TableExplorer:
    """Operaciones read-only sobre un engine async."""

    def __init__(self, cfg: DbConfig):
        self.cfg = cfg
        self.cm = get_default()
        self.engine: AsyncEngine = self.cm.get_async_engine(cfg)

    # ─── Lista de tablas con row count aproximado ─────────────────
    def list_tables(self) -> tuple[bool, str, list[TableInfo]]:
        try:
            loop = asyncio.new_event_loop()
            try:
                infos = loop.run_until_complete(self._list_tables_async())
            finally:
                loop.close()
            names = [i.name for i in infos]
            return (True,
                    f"OK — {len(infos)} tablas detectadas en '{self.cfg.db}'.",
                    infos)
        except Exception as e:
            return (False, f"list_tables falló: {e.__class__.__name__}: {e}", [])

    async def _list_tables_async(self) -> list[TableInfo]:
        async with self.engine.connect() as conn:
            names = await conn.run_sync(
                lambda c: sync_inspect(c).get_table_names()
            )
            # row count aproximado por tabla (PG: pg_class.reltuples)
            counts = await self._approx_counts_async(conn, names)
            infos = []
            for n in names:
                cols = await conn.run_sync(
                    lambda c, name=n: [
                        {"name": col["name"],
                         "type": str(col["type"]),
                         "nullable": bool(col.get("nullable", True)),
                         "primary_key": False}
                        for col in sync_inspect(c).get_columns(name)
                    ]
                )
                # primary keys
                pks = await conn.run_sync(
                    lambda c, name=n: sync_inspect(c).get_pk_constraint(name).get(
                        "constrained_columns", [])
                )
                for col in cols:
                    col["primary_key"] = col["name"] in pks
                infos.append(TableInfo(name=n, columns=cols,
                                       approx_rows=counts.get(n)))
            return infos

    async def _approx_counts_async(self, conn, names: list[str]) -> dict:
        out: dict = {}
        # PostgreSQL: usar estadísticas (reltuples) — rápido y no bloqueante.
        if self.cfg.driver == "asyncpg" and names:
            def _pg_counts(c):
                from sqlalchemy import text as _t
                rs = c.execute(_t(
                    "SELECT relname, reltuples::bigint AS n FROM pg_class "
                    "WHERE relkind='r' AND relname = ANY(:names)"
                ).bindparams(names=list(names)))
                return {row[0]: int(row[1]) if row[1] is not None and int(row[1]) >= 0 else None
                        for row in rs}
            try:
                out = await conn.run_sync(_pg_counts)
                return out
            except Exception:
                pass  # cae a COUNT(*) abajo
        # Fallback: COUNT(*) por tabla (preciso pero costoso en tablas grandes).
        for n in names:
            try:
                qn = self._quote_ident(n)
                cnt = await conn.execute(text(f"SELECT COUNT(*) FROM {qn}"))
                val = cnt.scalar()
                out[n] = int(val) if val is not None else None
            except Exception:
                out[n] = None
        return out

    # ─── Lectura paginada de filas de una tabla ──────────────────
    def page(self, table: str, offset: int = 0, limit: int = 100,
             order_by: Optional[str] = None) -> tuple[bool, str, Optional[PageResult]]:
        try:
            loop = asyncio.new_event_loop()
            try:
                pres = loop.run_until_complete(self._page_async(table, offset, limit, order_by))
            finally:
                loop.close()
            return (True,
                    f"OK — Página {offset//limit + 1} de '{table}' "
                    f"({len(pres.rows)} filas, total≈{pres.total_approx}).",
                    pres)
        except Exception as e:
            return (False, f"page falló: {e.__class__.__name__}: {e}", None)

    async def _page_async(self, table, offset, limit, order_by) -> PageResult:
        qn = self._quote_ident(table)
        order_clause = ""
        if order_by:
            order_clause = f" ORDER BY {self._quote_ident(order_by)}"
        # Si no hay order_by y la tabla tiene PK, usarla como orden estable.
        if not order_clause:
            async with self.engine.connect() as conn:
                pks = await conn.run_sync(
                    lambda c, t=table: sync_inspect(c).get_pk_constraint(t).get(
                        "constrained_columns", []))
            if pks:
                order_clause = f" ORDER BY {self._quote_ident(pks[0])}"

        sql = f"SELECT * FROM {qn}{order_clause} LIMIT :limit OFFSET :offset"
        async with self.engine.connect() as conn:
            rows_result = await conn.execute(text(sql),
                                              {"limit": limit, "offset": offset})
            rows_raw = rows_result.fetchall()
            columns = list(rows_result.keys())
            # rows_raw sonRow(items) SQLAlchemy → convertibles a list/tuple
            rows = [list(r) for r in rows_raw]

            # total aproximado
            total = None
            try:
                counts = await self._approx_counts_async(conn, [table])
                total = counts.get(table)
            except Exception:
                pass
            if total is None:
                try:
                    cnt = (await conn.execute(text(f"SELECT COUNT(*) FROM {qn}"))).scalar()
                    total = int(cnt) if cnt is not None else None
                except Exception:
                    total = None

        return PageResult(columns=columns, rows=rows, offset=offset, limit=limit,
                          total_approx=total)

    # ─── Estructura de una tabla (columnas, tipos) ───────────────
    def describe(self, table: str) -> tuple[bool, str, Optional[list[dict]]]:
        try:
            loop = asyncio.new_event_loop()
            try:
                cols = loop.run_until_complete(self._describe_async(table))
            finally:
                loop.close()
            return (True, f"OK — {len(cols)} columnas en '{table}'.", cols)
        except Exception as e:
            return (False, f"describe falló: {e.__class__.__name__}: {e}", None)

    async def _describe_async(self, table) -> list[dict]:
        async with self.engine.connect() as conn:
            cols = await conn.run_sync(
                lambda c: [
                    {"name": col["name"],
                     "type": str(col["type"]),
                     "nullable": bool(col.get("nullable", True)),
                     "default": str(col.get("default", ""))}
                    for col in sync_inspect(c).get_columns(table)
                ]
            )
            pks = await conn.run_sync(
                lambda c: sync_inspect(c).get_pk_constraint(table).get(
                    "constrained_columns", []))
            for col in cols:
                col["primary_key"] = col["name"] in pks
            return cols

    @staticmethod
    def _quote_ident(name: str) -> str:
        """Cita un identificador de forma segura para SELECT/etc.
        Acepta nombres con schema: 'public.users' → '"public"."users"'."""
        if not name:
            return name
        return ".".join(f'"{part}"' for part in name.split("."))
