"""db_tab — Área "Base de Datos & Docker".

Migración 1:1 de `AppGUI._build_db_tab` con sus callbacks `update_conn_str`,
`copy_conn_str`, `test_pg_conn`, `run_docker_stack`, `open_pg_port_firewall`,
`on_pass_change_db`.

Fase 0: feedback asíncrono en todas las acciones (AsyncButton + Modal).
Fase 1: DB Viewer integrado — combo de tablas (cualquiera), ver estructura,
ver datos paginados, SQL libre read-only, exportación CSV.
El usuario puede escribir el connection string, probar el puerto y abrir el
firewall con feedback real.
"""
from __future__ import annotations

import csv
import io
import os
import webbrowser
from tkinter import filedialog, messagebox

import customtkinter as ctk

from core.base_tab import TabBase, COLORS
from ui.widgets.async_button import AsyncButton
from ui.widgets.modal import Modal
from ui.tabs.db_viewer.connection_manager import DbConfig, get_default as get_connection_manager
from ui.tabs.db_viewer.table_explorer import TableExplorer, TableInfo
from ui.tabs.db_viewer.query_runner import QueryRunner, QueryResult


class DbTab(TabBase):
    title = "Base de Datos & Docker"
    icon = "🗄️"

    def build(self, parent):
        self.parent = parent
        c = self.color
        runner = self.ctx.async_runner

        ctk.CTkLabel(parent, text="Configuración de Base de Datos PostgreSQL 17 & Docker Desktop",
                     font=ctk.CTkFont(size=14, weight="bold"),
                     text_color=c.c_text_title).pack(anchor="w", padx=16, pady=(16, 6))

        # ─── Docker Desktop ───────────────────────────────────────
        docker_box = ctk.CTkFrame(parent, fg_color=c.c_bg_box, corner_radius=10)
        docker_box.pack(fill="x", padx=16, pady=8)
        ctk.CTkLabel(docker_box, text="🐳 Despliegue en 1-Clic con Docker Desktop",
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color="#0284C7").pack(anchor="w", padx=12, pady=(10, 2))
        ctk.CTkLabel(docker_box,
            text="Si no tienes PostgreSQL instalado, levanta PostgreSQL 17 + MinIO S3 + SFTPGo "
                 "automáticamente en Docker Desktop.",
            font=ctk.CTkFont(size=11), text_color=c.c_text_sub).pack(
                anchor="w", padx=12, pady=(0, 8))

        btn_dk_row = ctk.CTkFrame(docker_box, fg_color="transparent")
        btn_dk_row.pack(anchor="w", padx=12, pady=(0, 10))

        AsyncButton(btn_dk_row,
            text="🚀 Levantar Contenedores Docker (1-Clic)",
            fg_color="#0284C7", hover_color="#0369A1",
            font=ctk.CTkFont(size=12, weight="bold"),
            runner=runner,
            action=self.runner.launch_docker_stack,
            confirm="Se ejecutará `docker compose up -d` con PostgreSQL 17 + MinIO + SFTPGo. ¿Continuar?",
            confirm_title="Docker Compose",
            ok_title="Docker Compose", error_title="Error Docker",
            running_text="Levantando contenedores Docker…",
            on_done=lambda res: self.ctx.refresh_stats()
            ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(btn_dk_row, text="📥 Descargar Docker Desktop",
                      fg_color="#475569", hover_color="#334155",
                      font=ctk.CTkFont(size=12),
                      command=lambda: webbrowser.open(
                          "https://www.docker.com/products/docker-desktop/")
                      ).pack(side="left")

        ctk.CTkLabel(docker_box,
            text="📋 Comando Manual CLI para Terminal (Si prefieres no usar la app):",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=c.c_text_title).pack(anchor="w", padx=12, pady=(4, 2))

        self.box_docker_cmd = ctk.CTkEntry(docker_box, width=650,
            font=ctk.CTkFont(family="Courier", size=10), text_color="#0284C7")
        self.box_docker_cmd.insert(0,
            "docker run -d -p 5432:5432 -e POSTGRES_PASSWORD=ClaveSegura123! --name pg17 postgres:17-alpine")
        self.box_docker_cmd.pack(anchor="w", padx=12, pady=(0, 10))

        # ─── Form PG ───────────────────────────────────────────────
        form = ctk.CTkFrame(parent, fg_color=c.c_bg_box, corner_radius=10)
        form.pack(fill="x", padx=16, pady=8)

        ctk.CTkLabel(form, text="Host / IP (Recomendado):",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=c.c_text_title).grid(row=0, column=0, padx=12, pady=6, sticky="w")
        self.entry_db_host = ctk.CTkEntry(form, width=220)
        self.entry_db_host.insert(0, self.config.get('pg_host', self.ctx.ip))
        self.entry_db_host.grid(row=0, column=1, padx=12, pady=6, sticky="w")
        self.entry_db_host.bind("<KeyRelease>", self.update_conn_str)

        ctk.CTkLabel(form, text="Puerto PG (Recomendado: 5432):",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=c.c_text_title).grid(row=0, column=2, padx=12, pady=6, sticky="w")
        self.entry_db_port = ctk.CTkEntry(form, width=120)
        self.entry_db_port.insert(0, str(self.config.get('pg_port', 5432)))
        self.entry_db_port.grid(row=0, column=3, padx=12, pady=6, sticky="w")
        self.entry_db_port.bind("<KeyRelease>", self.update_conn_str)

        ctk.CTkLabel(form, text="Base de Datos:",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=c.c_text_title).grid(row=1, column=0, padx=12, pady=6, sticky="w")
        self.entry_db_name = ctk.CTkEntry(form, width=220)
        self.entry_db_name.insert(0, self.config.get('pg_db', 'facturapro_db'))
        self.entry_db_name.grid(row=1, column=1, padx=12, pady=6, sticky="w")
        self.entry_db_name.bind("<KeyRelease>", self.update_conn_str)

        ctk.CTkLabel(form, text="Usuario PG:",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=c.c_text_title).grid(row=2, column=0, padx=12, pady=6, sticky="w")
        self.entry_db_user = ctk.CTkEntry(form, width=220)
        self.entry_db_user.insert(0, self.config.get('pg_user', 'postgres_user'))
        self.entry_db_user.grid(row=2, column=1, padx=12, pady=6, sticky="w")
        self.entry_db_user.bind("<KeyRelease>", self.update_conn_str)

        ctk.CTkLabel(form, text="Contraseña PG:",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=c.c_text_title).grid(row=2, column=2, padx=12, pady=6, sticky="w")
        self.entry_db_pass = ctk.CTkEntry(form, width=180, show="*")
        self.entry_db_pass.insert(0, self.config.get('pg_pass', 'ClaveSegura123!'))
        self.entry_db_pass.grid(row=2, column=3, padx=12, pady=6, sticky="w")
        self.entry_db_pass.bind("<KeyRelease>", self.on_pass_change_db)

        from ui.tabs.storage_tab import evaluate_password_strength
        self.lbl_strength_db = ctk.CTkLabel(form, text="🟢 Fuerte",
            font=ctk.CTkFont(size=11, weight="bold"), text_color="#10B981")
        self.lbl_strength_db.grid(row=2, column=4, padx=(8, 0), pady=6, sticky="w")

        # ─── Connection string ─────────────────────────────────────
        ctk.CTkLabel(parent, text="📋 Connection String para FacturaProEC:",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=c.c_text_title).pack(anchor="w", padx=16, pady=(8, 2))
        self.conn_str_box = ctk.CTkEntry(parent, width=650,
            font=ctk.CTkFont(family="Courier", size=11), text_color="#10B981")
        self.conn_str_box.pack(anchor="w", padx=16, pady=2)
        self.update_conn_str()

        btn_row_db = ctk.CTkFrame(parent, fg_color="transparent")
        btn_row_db.pack(anchor="w", padx=16, pady=6)
        ctk.CTkButton(btn_row_db, text="📋 Copiar String",
                      command=self.copy_conn_str).pack(side="left", padx=(0, 8))

        AsyncButton(btn_row_db,
            text="🧪 Probar Conexión PG (Puerto 5432)",
            fg_color="#10B981", hover_color="#059669",
            runner=runner,
            action=self._test_pg_action,
            ok_title="Prueba PG Exitosa", error_title="Fallo de Conexión PG / VPN",
            running_text="Probando conexión PG…",
            warn_on_fail=False,
            on_done=lambda res: self.status(res.message)
            ).pack(side="left", padx=(0, 8))

        AsyncButton(btn_row_db,
            text="🔓 Abrir Puerto PostgreSQL (5432) en Firewall",
            fg_color="#0284C7", hover_color="#0369A1",
            runner=runner,
            action=self.runner.open_pg_port_firewall,
            ok_title="Firewall PostgreSQL", error_title="Firewall PostgreSQL",
            warn_on_fail=True,
            running_text="Abriendo puerto 5432…",
            on_done=lambda res: self.ctx.refresh_stats()
            ).pack(side="left")

        # ─── Explorador de Tablas (DB Viewer) ──────────────────────
        self.viewer_frame = ctk.CTkFrame(parent, fg_color=c.c_bg_box, corner_radius=10)
        self.viewer_frame.pack(fill="both", expand=True, padx=16, pady=12)
        ctk.CTkLabel(self.viewer_frame, text="🔎 Explorador de Tablas (DB Viewer)",
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color="#0284C7").pack(anchor="w", padx=12, pady=(10, 2))
        ctk.CTkLabel(self.viewer_frame,
            text="Conecta a PostgreSQL (local o VPN) y ve CUALQUIER tabla, sus columnas, "
                 "tipos y datos paginados. También SQL libre read-only y exportación CSV.",
            font=ctk.CTkFont(size=11), text_color=c.c_text_sub).pack(
                anchor="w", padx=12, pady=(0, 8))

        # Barra de acciones del viewer
        viewer_actions = ctk.CTkFrame(self.viewer_frame, fg_color="transparent")
        viewer_actions.pack(fill="x", padx=12, pady=4)

        AsyncButton(viewer_actions,
            text="🔌 Conectar y Listar Tablas",
            fg_color="#10B981", hover_color="#059669",
            font=ctk.CTkFont(size=12, weight="bold"), height=32,
            runner=runner,
            action=self._connect_viewer_action,
            ok_title="DB Viewer", error_title="DB Viewer",
            running_text="Conectando y listando tablas…",
            warn_on_fail=True,
            on_done=lambda res: self.status(res.message)
            ).pack(side="left", padx=(0, 8))

        AsyncButton(viewer_actions,
            text="🔄 Refrescar",
            fg_color="#475569", hover_color="#334155",
            font=ctk.CTkFont(size=12), height=32,
            runner=runner,
            action=self._refresh_tables_action,
            ok_title="DB Viewer", error_title="DB Viewer",
            warn_on_fail=True,
            running_text="Refrescando tablas…").pack(side="left", padx=(0, 8))

        # Combo de tablas
        self.combo_tables_var = ctk.StringVar(value="(sin conectar)")
        self.combo_tables = ctk.CTkOptionMenu(
            viewer_actions,
            variable=self.combo_tables_var,
            values=["(sin conectar)"],
            width=240, height=32,
            command=self._on_table_selected)
        self.combo_tables.pack(side="left", padx=(0, 8))

        AsyncButton(viewer_actions,
            text="👁️ Ver Datos (100)",
            fg_color="#0284C7", hover_color="#0369A1",
            font=ctk.CTkFont(size=12), height=32,
            runner=runner,
            action=self._view_data_action,
            ok_title="DB Viewer", error_title="DB Viewer",
            warn_on_fail=True,
            running_text="Cargando datos…").pack(side="left", padx=(0, 4))

        AsyncButton(viewer_actions,
            text="ℹ️ Ver Estructura",
            fg_color="#6366F1", hover_color="#4F46E5",
            font=ctk.CTkFont(size=12), height=32,
            runner=runner,
            action=self._view_structure_action,
            ok_title="Estructura de Tabla", error_title="DB Viewer",
            warn_on_fail=True,
            running_text="Cargando estructura…").pack(side="left", padx=(0, 4))

        # Paginación
        pager_row = ctk.CTkFrame(self.viewer_frame, fg_color="transparent")
        pager_row.pack(fill="x", padx=12, pady=(2, 4))
        ctk.CTkButton(pager_row, text="⬅ Anterior", width=100, height=28,
                      fg_color="#475569", hover_color="#334155",
                      command=self._prev_page).pack(side="left", padx=(0, 4))
        self.lbl_page = ctk.CTkLabel(pager_row, text="Página 0 de 0",
            font=ctk.CTkFont(size=11, weight="bold"), text_color=c.c_text_sub)
        self.lbl_page.pack(side="left", padx=8)
        ctk.CTkButton(pager_row, text="Siguiente ➡", width=100, height=28,
                      fg_color="#475569", hover_color="#334155",
                      command=self._next_page).pack(side="left", padx=(4, 12))

        AsyncButton(pager_row,
            text="💾 Exportar CSV",
            fg_color="#10B981", hover_color="#059669", height=28,
            font=ctk.CTkFont(size=11, weight="bold"),
            runner=runner,
            action=self._export_csv_action,
            ok_title="Exportar CSV", error_title="Exportar CSV",
            warn_on_fail=True,
            running_text="Exportando…").pack(side="left", padx=(0, 8))

        # SQL libre read-only
        sql_row = ctk.CTkFrame(self.viewer_frame, fg_color="transparent")
        sql_row.pack(fill="x", padx=12, pady=(2, 4))
        ctk.CTkLabel(sql_row, text="SQL libre (read-only):",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=c.c_text_title).pack(side="left", padx=(0, 6))
        self.sql_input = ctk.CTkTextbox(sql_row, height=64, width=520,
            font=ctk.CTkFont(family="Courier", size=11))
        self.sql_input.insert("1.0", "SELECT * FROM users LIMIT 50")
        self.sql_input.pack(side="left", padx=(0, 6))

        AsyncButton(sql_row,
            text="▶ Ejecutar SQL",
            fg_color="#F59E0B", hover_color="#D97706", height=64,
            font=ctk.CTkFont(size=11, weight="bold"),
            runner=runner,
            action=self._run_sql_action,
            ok_title="Consulta ejecutada", error_title="SQL erróneo",
            warn_on_fail=True,
            running_text="Ejecutando SQL…").pack(side="left")

        # Resultados en un grid scrollable
        self.results_frame = ctk.CTkScrollableFrame(self.viewer_frame,
            fg_color=("white", "#0F172A"), corner_radius=8, height=260)
        self.results_frame.pack(fill="both", expand=True, padx=12, pady=(4, 4))
        self.lbl_results_placeholder = ctk.CTkLabel(self.results_frame,
            text="(Pulsa “Conectar y Listar Tablas” para empezar)",
            font=ctk.CTkFont(size=11), text_color=c.c_text_sub)
        self.lbl_results_placeholder.pack(anchor="w", padx=8, pady=8)

        # Estado interno del viewer
        self.viewer_explorer = None      # TableExplorer
        self.viewer_query_runner = None  # QueryRunner
        self.viewer_cfg = None           # DbConfig
        self._last_query_result = None   # QueryResult
        self._viewer_offset = 0
        self._viewer_limit = 100
        self._viewer_total_approx = None
        self._viewer_current_table = None

    # ─── Persistencia ────────────────────────────────────────────
    def collect_settings(self) -> dict:
        try:
            port = int(self.entry_db_port.get().strip() or 5432)
        except Exception:
            port = 5432
        return {
            'pg_host': self.entry_db_host.get().strip(),
            'pg_port': port,
            'pg_db': self.entry_db_name.get().strip(),
            'pg_user': self.entry_db_user.get().strip(),
            'pg_pass': self.entry_db_pass.get().strip(),
        }

    def _save_quiet(self):
        try:
            self.config.save_config(self.collect_settings())
        except Exception:
            pass

    # ─── Callbacks ────────────────────────────────────────────────
    def on_pass_change_db(self, event=None):
        from ui.tabs.storage_tab import evaluate_password_strength
        pwd = self.entry_db_pass.get()
        txt, col = evaluate_password_strength(pwd)
        self.lbl_strength_db.configure(text=txt, text_color=col)
        self.update_conn_str()

    def update_conn_str(self, event=None):
        ip = self.entry_db_host.get() or self.ctx.ip
        port = self.entry_db_port.get() or "5432"
        db = self.entry_db_name.get() or "facturapro_db"
        user = self.entry_db_user.get() or "postgres_user"
        pwd = self.entry_db_pass.get() or "ClaveSegura123!"
        conn = f"postgresql+asyncpg://{user}:{pwd}@{ip}:{port}/{db}"
        self.conn_str_box.delete(0, "end")
        self.conn_str_box.insert(0, conn)

    def copy_conn_str(self):
        self.update_conn_str()
        conn = self.conn_str_box.get()
        self.ctx.root.clipboard_clear()
        self.ctx.root.clipboard_append(conn)
        self.status("String de conexión copiado al portapapeles.")

    def _test_pg_action(self):
        self._save_quiet()
        host = self.entry_db_host.get().strip() or self.ctx.ip
        port = self.entry_db_port.get().strip() or "5432"
        try:
            port_i = int(port)
        except Exception:
            port_i = 5432
        return self.runner.test_db_connection(host, port_i)

    # ─── DB Viewer — helpers de configuración ──────────────────────
    def _build_dbconfig(self) -> DbConfig:
        """Construye DbConfig desde los entries. Si la tab VPN tiene
        campos PG remoto rellenos, los usa (preferencia VPN); si no,
        usa los locales del formulario de esta tab."""
        # Priorizar VPN si está relleno
        try:
            r_host = self.config.get('pg_remote_host', '')
            if r_host:
                r_port = int(self.config.get('pg_remote_port', 5432) or 5432)
                return DbConfig(
                    host=r_host, port=r_port,
                    db=self.config.get('pg_remote_db', self.entry_db_name.get().strip() or 'facturapro_db'),
                    user=self.config.get('pg_remote_user', ''),
                    password=self.config.get('pg_remote_pass', ''),
                    driver="asyncpg",
                )
        except Exception:
            pass
        # Local
        try:
            port = int(self.entry_db_port.get().strip() or 5432)
        except Exception:
            port = 5432
        return DbConfig(
            host=self.entry_db_host.get().strip() or self.ctx.ip,
            port=port,
            db=self.entry_db_name.get().strip() or "facturapro_db",
            user=self.entry_db_user.get().strip() or "postgres_user",
            password=self.entry_db_pass.get().strip() or "ClaveSegura123!",
            driver="asyncpg",
        )

    def _ensure_viewers(self) -> None:
        cfg = self._build_dbconfig()
        if self.viewer_cfg is None or cfg != self.viewer_cfg:
            self.viewer_cfg = cfg
            self.viewer_explorer = TableExplorer(cfg)
            self.viewer_query_runner = QueryRunner(cfg)

    # ─── DB Viewer — acciones (devuelven (bool, str, data)) ───────
    def _connect_viewer_action(self):
        self._save_quiet()
        try:
            self._ensure_viewers()
        except Exception as e:
            return (False, f"No se pudo preparar la conexión: {e.__class__.__name__}: {e}")
        ok, msg, tables = get_connection_manager().test_connection(self.viewer_cfg)
        if not ok:
            # Resetear combo a estado sin conexión
            self._afterviewer_set_tables([], error=msg)
            return (False, msg)
        # Éxito: actualizar combo (en hilo UI)
        self.ctx.root.after(0, lambda: self._afterviewer_set_tables(tables))
        return (True, f"{msg}\n\nSelect una tabla en el combo y pulsa “Ver Datos”.")

    def _refresh_tables_action(self):
        # Forzar refresco del engine cacheado (si los creds cambiaron).
        if self.viewer_cfg is not None:
            get_connection_manager().dispose(self.viewer_cfg.to_async_url())
        return self._connect_viewer_action()

    def _view_data_action(self):
        table = self._viewer_current_table or self.combo_tables_var.get()
        if not table or table == "(sin conectar)":
            return (False, "Primero pulsa “Conectar y Listar Tablas” y elige una tabla.")
        self._ensure_viewers()
        ok, msg, page = self.viewer_explorer.page(table,
                                                    offset=self._viewer_offset,
                                                    limit=self._viewer_limit)
        if not ok:
            return (False, msg)
        self._viewer_total_approx = page.total_approx
        self._viewer_current_table = table
        # Render en hilo UI
        self.ctx.root.after(0, lambda: self._render_grid(page.columns, page.rows,
                                                          f"{table} (página {self._viewer_offset//self._viewer_limit + 1}, ≈{page.total_approx} filas)"))
        self.ctx.root.after(0, self._update_page_label)
        return (True, msg + "\n\nDatos mostrados en el grid inferior.")

    def _view_structure_action(self):
        table = self._viewer_current_table or self.combo_tables_var.get()
        if not table or table == "(sin conectar)":
            return (False, "Primero pulsa “Conectar y Listar Tablas” y elige una tabla.")
        self._ensure_viewers()
        ok, msg, cols = self.viewer_explorer.describe(table)
        if not ok:
            return (False, msg)
        # Render como tabla estructura
        rows = [[c["name"], c["type"], "NULL" if c["nullable"] else "NOT NULL",
                 "PK" if c["primary_key"] else "", c.get("default", "")]
                for c in cols]
        self.ctx.root.after(0, lambda: self._render_grid(
            ["Columna", "Tipo", "Null", "PK", "Default"],
            rows,
            f"Estructura de '{table}' ({len(cols)} columnas)"))
        self._last_query_result = QueryResult(
            columns=["Columna", "Tipo", "Null", "PK", "Default"], rows=rows, rowcount=len(rows))
        return (True, msg)

    def _run_sql_action(self):
        self._ensure_viewers()
        sql = self.sql_input.get("1.0", "end").strip()
        if not sql:
            return (False, "Escribe una consulta SQL (sólo SELECT/EXPLAIN/WITH/VALUES).")
        ok, msg, res = self.viewer_query_runner.run(sql)
        if not ok:
            return (False, msg)
        self._last_query_result = res
        self.ctx.root.after(0, lambda: self._render_grid(
            res.columns, res.rows,
            f"SQL ejecutado — {res.rowcount} fila(s) en {len(res.columns)} columna(s)"))
        return (True, msg)

    # ─── DB Viewer — paginación ───────────────────────────────────
    def _on_table_selected(self, choice: str):
        self._viewer_current_table = choice
        self._viewer_offset = 0
        # Auto-cargar datos al seleccionar
        self._view_data_async()

    def _view_data_async(self):
        """Dispara `_view_data_action` por el AsyncRunner sin生产能力 bloquear."""
        # Encontrar el botón correspondiente es engorroso; simplemente llamamos
        # al runner en modo directo usando su API:
        self.ctx.async_runner.run(
            action=self._view_data_action,
            on_done=self._after_data_load,
            status_msg="Cargando datos de la tabla…",
        )

    def _after_data_load(self, res):
        if not res.success:
            Modal.warn(self.parent, "DB Viewer", res.message)
        self.status(res.message)

    def _next_page(self):
        self._viewer_offset += self._viewer_limit
        self._view_data_async()

    def _prev_page(self):
        self._viewer_offset = max(0, self._viewer_offset - self._viewer_limit)
        self._view_data_async()

    def _update_page_label(self):
        total = self._viewer_total_approx
        size = self._viewer_limit
        current_page = (self._viewer_offset // size) + 1
        total_pages = (max(1, total or 1) + size - 1) // size if total else 0
        self.lbl_page.configure(
            text=f"Página {current_page} de {total_pages or '?'}" if total else f"Página {current_page}")

    # ─── DB Viewer — exporter ─────────────────────────────────────
    def _export_csv_action(self):
        if not isinstance(self._last_query_result, QueryResult) or not self._last_query_result.columns:
            # Si hay tabla seleccionada sin query realizada, ejecutar VIEW_DATA primero.
            if self._viewer_current_table and self._viewer_current_table != "(sin conectar)":
                self._ensure_viewers()
                ok, msg, page = self.viewer_explorer.page(self._viewer_current_table,
                                                            offset=0, limit=10000)
                if not ok:
                    return (False, msg)
                res = QueryResult(columns=page.columns, rows=page.rows, rowcount=len(page.rows))
            else:
                return (False, "No hay resultados para exportar. Ejecuta una query o visualiza datos primero.")
        else:
            res = self._last_query_result
        # Pedir ruta destino
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv"), ("Todos los archivos", "*.*")],
            title="Guardar CSV como…",
        )
        if not path:
            return (False, "Exportación cancelada por el usuario.")
        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.writer(f, lineterminator="\n")
                w.writerow(res.columns)
                for row in res.rows:
                    w.writerow([self._csv_cell(c) for c in row])
        except Exception as e:
            return (False, f"No se pudo escribir el CSV: {e.__class__.__name__}: {e}")
        return (True, f"✅ Exportadas {res.rowcount} fila(s) a:\n{path}")

    @staticmethod
    def _csv_cell(v):
        if v is None:
            return ""
        if isinstance(v, (bytes, bytearray)):
            try:
                return v.decode("utf-8", errors="replace")
            except Exception:
                return ""
        return str(v)

    # ─── DB Viewer — rendering del grid scrollable ────────────────
    def _afterviewer_set_tables(self, tables: list[str], error: str = ""):
        if error:
            self.combo_tables.configure(values=["(sin conectar)"])
            self.combo_tables_var.set("(sin conectar)")
            self.lbl_results_placeholder.configure(text=f"❌ {error[:200]}")
            return
        self.combo_tables.configure(values=tables or ["(sin tablas)"])
        if tables:
            self.combo_tables_var.set(tables[0])
            self._viewer_current_table = tables[0]
            self._viewer_offset = 0
            self.lbl_results_placeholder.configure(
                text=f"✅ {len(tables)} tablas detectadas. Selecciona una y pulsa “Ver Datos”.")
        else:
            self.combo_tables_var.set("(sin tablas)")
            self.lbl_results_placeholder.configure(text="Conexión OK pero no se hallaron tablas.")

    def _render_grid(self, columns: list[str], rows: list[list], title: str = ""):
        """Render en un CTkScrollableFrame: header + filas como CTkLabel."""
        # Limpiar grid anterior
        for w in self.results_frame.winfo_children():
            w.destroy()
        if not columns:
            lbl = ctk.CTkLabel(self.results_frame, text="(Sin resultados)",
                               font=ctk.CTkFont(size=11),
                               text_color=("black", "#94A3B8"))
            lbl.pack(anchor="w", padx=8, pady=8)
            return
        title_lbl = ctk.CTkLabel(self.results_frame, text=title,
                                 font=ctk.CTkFont(size=11, weight="bold"),
                                 text_color=("#0F172A", "#F8FAFC"))
        title_lbl.pack(anchor="w", padx=8, pady=(8, 4))

        grid = ctk.CTkFrame(self.results_frame, fg_color="transparent")
        grid.pack(fill="both", expand=True, padx=4, pady=4)

        # Cabecera
        for j, col in enumerate(columns):
            ctk.CTkLabel(grid, text=str(col), font=ctk.CTkFont(size=11, weight="bold"),
                         fg_color=("#1E293B", "#0F172A"),
                         text_color=("#F8FAFC", "#F8FAFC"),
                         corner_radius=4, padx=8, pady=4,
                         anchor="w").grid(row=0, column=j, padx=2, pady=2, sticky="ew")

        # Filas (limitamos render a 500 para no marear la UI)
        n = min(len(rows), 500)
        for i in range(n):
            for j, cell in enumerate(rows[i]):
                txt = self._format_cell(cell)
                ctk.CTkLabel(grid, text=txt, font=ctk.CTkFont(size=10),
                             text_color=("#0F172A", "#F8FAFC"),
                             anchor="w", padx=8, pady=3).grid(
                                 row=i + 1, column=j, padx=2, pady=1, sticky="w")
        if len(rows) > n:
            ctk.CTkLabel(self.results_frame,
                         text=f"… mostrando {n} de {len(rows)} filas.",
                         font=ctk.CTkFont(size=10), text_color=("black", "#94A3B8")).pack(
                             anchor="w", padx=8, pady=2)

    @staticmethod
    def _format_cell(v) -> str:
        if v is None:
            return "(NULL)"
        if isinstance(v, (bytes, bytearray)):
            try:
                return v.decode("utf-8", errors="replace")[:60]
            except Exception:
                return f"<{len(v)} bytes>"
        if isinstance(v, float):
            return f"{v:.4f}".rstrip("0").rstrip(".") if v != int(v) else str(int(v))
        s = str(v)
        return s if len(s) <= 80 else s[:77] + "…"
