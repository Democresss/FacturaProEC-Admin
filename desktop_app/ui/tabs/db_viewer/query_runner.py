"""query_runner — ejecuta SQL libre (sólo lectura) + exportar CSV.

Para el DB Viewer. Corta por seguridad cualquier DDL/DML:
sólo permite sentencias que empiecen con SELECT, EXPLAIN, WITH o
VALUES. Bloquea INSERT/UPDATE/DELETE/DROP/TRUNCATE/ALTER/etc.

El modo "tabla paginada" se hace en el TableExplorer; aquí es para SQL
libre de hasta `max_rows` filas. La exportación a CSV es estática, sin
pandas (stdlib `csv`).
"""
from __future__ import annotations

import asyncio
import csv
import io
import re
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import text

from .connection_manager import DbConfig, get_default


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[list]
    rowcount: int


_BLOCKED = re.compile(
    r"\b(insert\s+into|update\s+\w+\s+set|delete\s+from|drop\s+|truncate\s+|alter\s+|"
    r"create\s+|grant\s+|revoke\s+|vacuum\s+|copy\s+into|merge\s+into)\b",
    re.IGNORECASE,
)


def _is_safe_select(sql: str) -> bool:
    s = sql.strip().lower()
    if not s:
        return False
    if _BLOCKED.search(s):
        return False
    # Debe empezar por uno de los prefijos permitidos.
    return s.startswith(("select", "explain", "with", "values"))


class QueryRunner:
    """Ejecuta SQL read-only en el engine async. Reutiliza ConnectionManager."""

    def __init__(self, cfg: DbConfig, max_rows: int = 500):
        self.cfg = cfg
        self.max_rows = max_rows
        self.cm = get_default()
        self.engine = self.cm.get_async_engine(cfg)

    def validate(self, sql: str) -> tuple[bool, str]:
        if not _is_safe_select(sql):
            return (False,
                    "Sólo se permiten sentencias de LECTURA (SELECT, EXPLAIN, "
                    "WITH, VALUES). INSERT/UPDATE/DELETE/DDL están bloqueados "
                    "para proteger la base de datos.")
        return (True, "OK")

    def run(self, sql: str, *, max_rows: Optional[int] = None) -> tuple[bool, str, Optional[QueryResult]]:
        ok, msg = self.validate(sql)
        if not ok:
            return (False, msg, None)
        limit = max_rows or self.max_rows
        try:
            loop = asyncio.new_event_loop()
            try:
                res = loop.run_until_complete(self._run_async(sql, limit))
            finally:
                loop.close()
            return (True,
                    f"OK — {res.rowcount} fila(s) en {len(res.columns)} columna(s).",
                    res)
        except Exception as e:
            return (False, f"{e.__class__.__name__}: {e}", None)

    async def _run_async(self, sql: str, max_rows: int) -> QueryResult:
        # Inyectar LIMIT cuando no tenga uno explícito (detección simple).
        sql_with_limit = self._ensure_limit(sql, max_rows)
        async with self.engine.connect() as conn:
            result = await conn.execute(text(sql_with_limit))
            rows_raw = result.fetchall()
            columns = list(result.keys())
        rows = [list(r) for r in rows_raw]
        return QueryResult(columns=columns, rows=rows, rowcount=len(rows))

    @staticmethod
    def _ensure_limit(sql: str, max_rows: int) -> str:
        s = sql.strip()
        # Detección barata: si existe "limit" ya en la consulta, no añadir otro.
        if re.search(r"\blimit\b", s, re.IGNORECASE):
            return s
        # Quite ';' final antes de añadir LIMIT.
        s = s.rstrip(";").rstrip()
        # Para WITH/EXPLAIN/VALUES, añadir un wrapper SELECT * FROM (...) LIMIT.
        return f"{s} LIMIT {max_rows}"

    # ─── Exportación CSV (sin pandas; stdlib) ────────────────────
    @staticmethod
    def to_csv(res: QueryResult) -> str:
        """Devuelve contenido CSV como string (para escribir o pegar)."""
        out = io.StringIO()
        w = csv.writer(out, lineterminator="\n")
        w.writerow(res.columns)
        for row in res.rows:
            w.writerow([QueryRunner._csv_cell(c) for c in row])
        return out.getvalue()

    @staticmethod
    def _csv_cell(v) -> str:
        if v is None:
            return ""
        if isinstance(v, (bytes, bytearray)):
            try:
                return v.decode("utf-8", errors="replace")
            except Exception:
                return ""
        return str(v)
