"""sri_tab — Área "🧾 SRI / Recepción" (Fase 2).

Tres sub-áreas en un `CTkScrollableFrame`:

  1. Recepción automática IMAP
     Form con creds IMAP (host/port/user/app-password/folder), botones
     "Probar conexión" y "Sincronizar ahora" (vía InboxSyncWorker → no
     congela la UI), switch "Auto-sync cada N minutos", log en vivo.
     Los comprobantes recibidos se guardan en la BD del DB Viewer
     (PG local Docker, PG remoto VPN, o fallback SQLite).

  2. Consulta RUC contribuyente
     Form con RUC de 13 dígitos → consulta REST pública al catastro del
     SRI (sin auth) → modal con ficha del contribuyente (razón social,
     estado, obligado, agente retención, establecimientos).

  3. Bandeja recibidos
     Lista paginada de los comprobantes guardados en `facturapro_inbox`,
     con botón "Ver XML" que abre un modal con el XML original.

Para la recepción NO se hace scraping del portal web del SRI (decisión
técnica/legal acordada con el usuario): usamos IMAP + el REST público de
catastro de RUC. Importamos los adapters autocontenidos desde
`integrations/` y el orquestador desde `ui/sri/`.
"""
from __future__ import annotations

from datetime import datetime

import customtkinter as ctk

from core.base_tab import TabBase, COLORS
from ui.sri.sri_facade import SRIFacade, SyncStats
from ui.sri.inbox_sync import InboxSyncWorker, ImapParams
from ui.widgets.async_button import AsyncButton
from ui.widgets.modal import Modal


class SriTab(TabBase):
    title = "SRI / Recepción"
    icon = "🧾"

    # Paginación de la bandeja
    _PAGE_SIZE = 50

    def build(self, parent):
        self.parent = parent
        c = self.color
        runner = self.ctx.async_runner
        self.facade: SRIFacade | None = None
        self._sync_worker: InboxSyncWorker | None = None
        self._inbox_offset = 0
        self._inbox_rows: list[dict] = []
        self._auto_sync_after_id = None  # id del after() para auto-sync

        scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        scroll.pack(fill="both", expand=True)

        ctk.CTkLabel(
            scroll,
            text="Módulo SRI — Recepción automática de comprobantes y consulta de contribuyentes",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=c.c_text_title,
        ).pack(anchor="w", padx=16, pady=(16, 4))
        ctk.CTkLabel(
            scroll,
            text=("Recepción por IMAP (vía oficial, no scraping del portal). "
                  "Los comprobantes llegan adjuntos al correo del contribuyente; "
                  "el módulo baja los XML, los parsea y los guarda en la base de datos."),
            font=ctk.CTkFont(size=11), text_color=c.c_text_sub,
        ).pack(anchor="w", padx=16, pady=(0, 8))

        self._build_recepcion(scroll, runner)
        self._build_consulta_ruc(scroll, runner)
        self._build_bandeja(scroll, runner)

        # Si auto-sync estaba activo, planificar primera sincronización
        if self.config.get("sri_auto_sync", False):
            self._schedule_auto_sync(initial=True)

    # ════════════════════════════════════════════════════════════════════
    #  Sub-área 1: Recepción automática IMAP
    # ════════════════════════════════════════════════════════════════════
    def _build_recepcion(self, scroll, runner):
        c = self.color
        box = ctk.CTkFrame(scroll, fg_color=c.c_bg_box, corner_radius=10)
        box.pack(fill="x", padx=16, pady=(0, 12))

        ctk.CTkLabel(
            box, text="📥 Recepción automática (IMAP)",
            font=ctk.CTkFont(size=13, weight="bold"), text_color="#10B981",
        ).pack(anchor="w", padx=12, pady=(10, 2))
        ctk.CTkLabel(
            box,
            text=("Usa una app-password (no tu clave normal) si es Gmail. "
                  "El módulo baja hasta 50 correos no leídos por sincronización."),
            font=ctk.CTkFont(size=11), text_color=c.c_text_sub,
        ).pack(anchor="w", padx=12, pady=(0, 8))

        form = ctk.CTkFrame(box, fg_color="transparent")
        form.pack(fill="x", padx=12, pady=(0, 8))

        row1 = ctk.CTkFrame(form, fg_color="transparent")
        row1.pack(fill="x", pady=(0, 6))
        ctk.CTkLabel(row1, text="Servidor IMAP:", width=120, anchor="w",
                     font=ctk.CTkFont(size=12)).pack(side="left")
        self.entry_imap_host = ctk.CTkEntry(row1, width=220)
        self.entry_imap_host.insert(0, self.config.get("sri_imap_host", "imap.gmail.com"))
        self.entry_imap_host.pack(side="left", padx=(0, 12))

        ctk.CTkLabel(row1, text="Puerto:", width=60, anchor="w",
                     font=ctk.CTkFont(size=12)).pack(side="left")
        self.entry_imap_port = ctk.CTkEntry(row1, width=70)
        self.entry_imap_port.insert(0, str(self.config.get("sri_imap_port", 993)))
        self.entry_imap_port.pack(side="left", padx=(0, 12))

        ctk.CTkLabel(row1, text="Carpeta:", width=70, anchor="w",
                     font=ctk.CTkFont(size=12)).pack(side="left")
        self.entry_imap_folder = ctk.CTkEntry(row1, width=140)
        self.entry_imap_folder.insert(0, self.config.get("sri_imap_folder", "INBOX"))
        self.entry_imap_folder.pack(side="left")

        row2 = ctk.CTkFrame(form, fg_color="transparent")
        row2.pack(fill="x", pady=(0, 6))
        ctk.CTkLabel(row2, text="Usuario (correo):", width=120, anchor="w",
                     font=ctk.CTkFont(size=12)).pack(side="left")
        self.entry_imap_user = ctk.CTkEntry(row2, width=260)
        self.entry_imap_user.insert(0, self.config.get("sri_imap_user", ""))
        self.entry_imap_user.pack(side="left", padx=(0, 12))

        row3 = ctk.CTkFrame(form, fg_color="transparent")
        row3.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(row3, text="App-password:", width=120, anchor="w",
                     font=ctk.CTkFont(size=12)).pack(side="left")
        self.entry_imap_pass = ctk.CTkEntry(row3, width=260, show="•")
        self.entry_imap_pass.insert(0, self.config.get("sri_imap_pass", ""))
        self.entry_imap_pass.pack(side="left", padx=(0, 12))

        # Switch auto-sync
        row_auto = ctk.CTkFrame(form, fg_color="transparent")
        row_auto.pack(fill="x", pady=(2, 6))
        self.switch_auto = ctk.CTkSwitch(
            row_auto, text="Auto-sync cada N minutos",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=c.c_text_title, command=self._on_toggle_auto_sync,
        )
        if self.config.get("sri_auto_sync", False):
            self.switch_auto.select()
        self.switch_auto.pack(side="left")
        self.entry_sync_interval = ctk.CTkEntry(row_auto, width=50)
        self.entry_sync_interval.insert(0, str(self.config.get("sri_sync_interval_min", 15)))
        self.entry_sync_interval.pack(side="left", padx=8)
        ctk.CTkLabel(row_auto, text="min", font=ctk.CTkFont(size=11),
                     text_color=c.c_text_sub).pack(side="left")

        # Botones + log
        btns = ctk.CTkFrame(box, fg_color="transparent")
        btns.pack(fill="x", padx=12, pady=(4, 6))
        AsyncButton(
            btns, text="🔗 Probar conexión IMAP",
            fg_color="#0284C7", hover_color="#0369A1", height=34,
            runner=runner, action=self._test_imap_action,
            ok_title="Conexión IMAP",
            running_text="Probando conexión…",
            on_done=lambda res: self.modal().ok(
                self.parent, "Conexión IMAP", res.message)
                if res.success else self.modal().error(
                self.parent, "Conexión IMAP", res.message),
        ).pack(side="left", padx=(0, 8))
        AsyncButton(
            btns, text="🔄 Sincronizar ahora",
            fg_color="#10B981", hover_color="#059669", height=34,
            runner=None,  # este usa InboxSyncWorker, no AsyncActionRunner
            action=self._sync_now_action,
            running_text="",
            on_done=lambda res: None,  # el worker maneja su propio feedback
        ).pack(side="left")

        self.log_box = ctk.CTkTextbox(box, height=160, font=ctk.CTkFont(size=11))
        self.log_box.pack(fill="x", padx=12, pady=(6, 12))
        self._log("Ready. Pulsa 'Probar conexión' con tus credenciales IMAP.")
        self.lbl_stats = ctk.CTkLabel(
            box, text="Último sync: —",
            font=ctk.CTkFont(size=11), text_color=c.c_text_sub,
        )
        self.lbl_stats.pack(anchor="w", padx=12, pady=(0, 10))

    def _test_imap_action(self) -> tuple[bool, str]:
        """Devuelve (ok, msg) — para AsyncButton 2-tuple."""
        self._save_imap_settings()
        host = self.entry_imap_host.get().strip()
        try:
            port = int(self.entry_imap_port.get().strip() or 993)
        except Exception:
            port = 993
        user = self.entry_imap_user.get().strip()
        pwd = self.entry_imap_pass.get()
        folder = self.entry_imap_folder.get().strip() or "INBOX"
        f = self._get_facade()
        return f.test_imap(host, port, user, pwd, folder=folder)

    def _sync_now_action(self):
        """Lanzadera del InboxSyncWorker. Devuelve 2-tuple para AsyncButton,
        aunque sea inmediato porque el resultado real llega por on_done."""
        if self._sync_worker is not None and self._sync_worker.is_running():
            self._log("⏳ Ya hay una sincronización en curso…")
            return (False, "Sincronización ya en curso.")
        self._save_imap_settings()
        host = self.entry_imap_host.get().strip()
        try:
            port = int(self.entry_imap_port.get().strip() or 993)
        except Exception:
            port = 993
        user = self.entry_imap_user.get().strip()
        pwd = self.entry_imap_pass.get()
        folder = self.entry_imap_folder.get().strip() or "INBOX"
        if not user or not pwd:
            return (False, "Falta usuario o contraseña IMAP.")
        params = ImapParams(host=host, port=port, user=user, password=pwd,
                            folder=folder, limit=50,
                            org_id=self.config.get("sri_org_id_default", "default"))
        facade = self._get_facade()
        self._sync_worker = InboxSyncWorker(
            root=self.ctx.root,
            facade=facade,
            on_progress=lambda clave: self._log(f"  · parseado comprobante {clave[:10]}…"),
            on_done=self._on_sync_done,
        )
        self._log(f"🔄 Sincronizando {host}:{port} carpeta '{folder}'…")
        self._sync_worker.start(params)
        self.status("Sincronizando SRI…")
        return (True, "Sincronización iniciada en segundo plano.")

    def _on_sync_done(self, stats: SyncStats):
        """Callback de UI cuando el worker termina."""
        msg = (f"✅ Sync OK: {stats.comprobantes_nuevos} nuevos, "
               f"{stats.comprobantes_duplicados} duplicados, "
               f"{stats.errores} errores — {stats.emails_processados} emails leídos.")
        if stats.detalle:
            msg += f"\nDetalle: {stats.detalle}"
        self._log(msg)
        self.lbl_stats.configure(text=f"Último sync: {datetime.now():%H:%M:%S} "
                                      f"— {stats.comprobantes_nuevos} nuevos")
        self.status(msg)
        # Refrescar bandeja automáticamente
        self._load_inbox()

    def _on_toggle_auto_sync(self):
        active = self.switch_auto.get() == 1
        try:
            interval = int(self.entry_sync_interval.get().strip() or 15)
        except Exception:
            interval = 15
        self.config.set("sri_auto_sync", active)
        self.config.set("sri_sync_interval_min", interval)
        if active:
            self._schedule_auto_sync()
            self._log(f"⏱ Auto-sync activado cada {interval} min.")
        else:
            self._cancel_auto_sync()
            self._log("⏱ Auto-sync desactivado.")

    def _schedule_auto_sync(self, initial: bool = False):
        """Programa la próxima sincronización automática."""
        self._cancel_auto_sync()
        try:
            interval = int(self.entry_sync_interval.get().strip() or 15)
        except Exception:
            interval = 15
        # En el primer arranque (initial=True), esperar 1 min; sino, el intervalo completo
        delay_ms = (60 if initial else interval * 60) * 1000
        self._auto_sync_after_id = self.ctx.root.after(
            delay_ms, self._auto_sync_tick)

    def _auto_sync_tick(self):
        if self.config.get("sri_auto_sync", False):
            self._log("⏱ Auto-sync: iniciando sincronización programada…")
            self._sync_now_action()
        self._schedule_auto_sync()

    def _cancel_auto_sync(self):
        if self._auto_sync_after_id is not None:
            try:
                self.ctx.root.after_cancel(self._auto_sync_after_id)
            except Exception:
                pass
            self._auto_sync_after_id = None

    # ════════════════════════════════════════════════════════════════════
    #  Sub-área 2: Consulta RUC contribuyente
    # ════════════════════════════════════════════════════════════════════
    def _build_consulta_ruc(self, scroll, runner):
        c = self.color
        box = ctk.CTkFrame(scroll, fg_color=c.c_bg_box, corner_radius=10)
        box.pack(fill="x", padx=16, pady=(0, 12))

        ctk.CTkLabel(
            box, text="🔎 Consulta RUC contribuyente (catastro SRI)",
            font=ctk.CTkFont(size=13, weight="bold"), text_color="#0284C7",
        ).pack(anchor="w", padx=12, pady=(10, 2))
        ctk.CTkLabel(
            box,
            text=("Consulta pública sin autenticación al REST del SRI. "
                  "Devuelve razón social, estado, obligado a llevar contabilidad, "
                  "agente de retención y establecimientos."),
            font=ctk.CTkFont(size=11), text_color=c.c_text_sub,
        ).pack(anchor="w", padx=12, pady=(0, 8))

        form = ctk.CTkFrame(box, fg_color="transparent")
        form.pack(fill="x", padx=12, pady=(0, 10))
        ctk.CTkLabel(form, text="RUC (13 dígitos):", width=140, anchor="w",
                     font=ctk.CTkFont(size=12)).pack(side="left")
        self.entry_ruc = ctk.CTkEntry(form, width=200)
        self.entry_ruc.pack(side="left", padx=(0, 12))
        self.entry_ruc.bind("<Return>", lambda e: self._do_consultar_ruc())
        AsyncButton(
            form, text="Consultar SRI",
            fg_color="#0284C7", hover_color="#0369A1", height=34,
            runner=runner, action=self._consultar_ruc_action,
            ok_title="Consulta RUC",
            running_text="Consultando catastro SRI…",
            on_done=self._after_consultar_ruc,
        ).pack(side="left")

    def _consultar_ruc_action(self) -> tuple[bool, str, dict | None]:
        """Devuelve (ok, msg, datos) — 3-tuple (AsyncButton normaliza)."""
        ruc = self.entry_ruc.get().strip()
        if len(ruc) != 13 or not ruc.isdigit():
            return (False, "El RUC debe tener 13 dígitos numéricos.", None)
        facade = self._get_facade()
        ok, msg, datos = facade.consultar_ruc(ruc)
        return (ok, msg, datos)

    def _after_consultar_ruc(self, res):
        if not res.success or not res.data:
            self.modal().error(self.parent, "Consulta RUC", res.message)
            return
        d = res.data
        # Construir ficha legible
        lines = [
            f"Razón social: {d.get('razonSocial', '—')}",
            f"RUC: {d.get('ruc', '—')}",
            f"Estado: {d.get('estado', '—')}",
            f"Obligado a llevar contabilidad: {d.get('obligadoContabilidad', '—')}",
            f"Agente de retención: {d.get('agenteRetencion', '—')}",
            f"Tipo contribuyente: {d.get('tipoContribuyente', '—')}",
        ]
        establecimientos = d.get("establecimientos") or []
        if establecimientos:
            lines.append(f"\nEstablecimientos ({len(establecimientos)}):")
            for est in establecimientos[:8]:
                lines.append(f"  · {est.get('numero')}: {est.get('direccion', '—')} "
                              f"({est.get('estado', '—')})")
            if len(establecimientos) > 8:
                lines.append(f"  · … y {len(establecimientos) - 8} más")
        body = "\n".join(lines)
        self.modal().ok(self.parent, "Ficha del contribuyente", body)

    # ════════════════════════════════════════════════════════════════════
    #  Sub-área 3: Bandeja recibidos
    # ════════════════════════════════════════════════════════════════════
    def _build_bandeja(self, scroll, runner):
        c = self.color
        box = ctk.CTkFrame(scroll, fg_color=c.c_bg_box, corner_radius=10)
        box.pack(fill="both", padx=16, pady=(0, 16), expand=True)

        header = ctk.CTkFrame(box, fg_color="transparent")
        header.pack(fill="x", padx=12, pady=(10, 4))
        ctk.CTkLabel(
            header, text="📂 Bandeja de comprobantes recibidos",
            font=ctk.CTkFont(size=13, weight="bold"), text_color="#A855F7",
        ).pack(side="left")
        btns = ctk.CTkFrame(header, fg_color="transparent")
        btns.pack(side="right")
        AsyncButton(
            btns, text="🔄 Refrescar", width=110, height=30,
            fg_color="#475569", hover_color="#334155",
            runner=runner,
            action=self._load_inbox_btn,
            ok_title="Bandeja",
            running_text="Cargando bandeja…",
            on_done=self._after_load_inbox,
        ).pack(side="left", padx=(0, 4))

        self.inbox_label = ctk.CTkLabel(
            box, text="(pulsa Refrescar para cargar)",
            font=ctk.CTkFont(size=11), text_color=c.c_text_sub,
        )
        self.inbox_label.pack(anchor="w", padx=12, pady=(0, 4))

        # Lista scrollable de filas
        self.inbox_list = ctk.CTkScrollableFrame(box, fg_color="transparent", height=220)
        self.inbox_list.pack(fill="both", expand=True, padx=12, pady=(0, 6))

        # Paginación
        nav = ctk.CTkFrame(box, fg_color="transparent")
        nav.pack(fill="x", padx=12, pady=(0, 10))
        self.btn_prev = ctk.CTkButton(
            nav, text="← Anterior", width=110, height=30,
            fg_color="#475569", hover_color="#334155",
            command=lambda: self._load_inbox(self._inbox_offset - self._PAGE_SIZE),
        )
        self.btn_prev.pack(side="left")
        self.btn_next = ctk.CTkButton(
            nav, text="Siguiente →", width=110, height=30,
            fg_color="#475569", hover_color="#334155",
            command=lambda: self._load_inbox(self._inbox_offset + self._PAGE_SIZE),
        )
        self.btn_next.pack(side="left", padx=6)
        self.lbl_page = ctk.CTkLabel(nav, text="", font=ctk.CTkFont(size=11),
                                     text_color=c.c_text_sub)
        self.lbl_page.pack(side="left")

        # Carga inicial
        self._load_inbox()

    def _load_inbox_btn(self) -> tuple[bool, str]:
        """Acción para el AsyncButton — sólo dispara load y retorna resultado plano."""
        return self._load_inbox()

    def _load_inbox(self, offset: int = 0) -> tuple[bool, str]:
        """Carga la página actual desde la BD local. Limpia y rellena la lista."""
        if offset < 0:
            offset = 0
        self._inbox_offset = offset
        facade = self._get_facade()
        ok, msg, rows = facade.list_inbox(limit=self._PAGE_SIZE, offset=offset)
        self._inbox_rows = rows
        # Limpiar lista
        for child in self.inbox_list.winfo_children():
            child.destroy()
        if not ok:
            self.inbox_label.configure(text=f"Error: {msg}",
                                       text_color="#EF4444")
            return (ok, msg)
        # Rellenar filas
        if not rows:
            self.inbox_label.configure(
                text=f"No hay comprobantes guardados (offset={offset}).",
                text_color=self.color.c_text_sub)
            self._update_nav(0)
            return (True, "Bandeja vacía.")
        for r in rows:
            self._render_inbox_row(r)
        texto = (f"{len(rows)} comprobantes (desde #{offset + 1}). "
                 f"Total última query: {len(rows)}.")
        self.inbox_label.configure(text=texto, text_color=self.color.c_text_sub)
        self._update_nav(len(rows))
        self.lbl_page.configure(text=f"Página {(offset // self._PAGE_SIZE) + 1}")
        return (True, texto)

    def _render_inbox_row(self, r: dict):
        """Una fila por comprobante: datos clave + botón 'Ver XML'."""
        c = self.color
        row_frame = ctk.CTkFrame(self.inbox_list, fg_color=c.c_bg_card,
                                 corner_radius=8)
        row_frame.pack(fill="x", pady=3, padx=2)
        tipo = r.get("tipo_comprobante", "—")
        tipo_str = {"01": "Factura", "04": "Nota crédito", "05": "Nota débito",
                    "07": "Comprobante retención"}.get(tipo, tipo)
        estado = r.get("estado_autorizacion") or "—"
        estado_color = "#10B981" if estado and "AUTORIZ" in estado.upper() else "#F59E0B"
        info = (f"{tipo_str} · {r.get('ruc_emisor', '—')} "
                f"· {r.get('razon_social_emisor', '—')[:40]} "
                f"· ${r.get('importe_total', 0):.2f} "
                f"· {r.get('fecha_emision', '—')}")
        ctk.CTkLabel(
            row_frame, text=info, anchor="w",
            font=ctk.CTkFont(size=11), text_color=c.c_text_title,
        ).pack(side="left", padx=8, pady=4)
        ctk.CTkLabel(row_frame, text=estado, text_color=estado_color,
                     font=ctk.CTkFont(size=10, weight="bold"),
                     ).pack(side="left", padx=8, pady=4)
        clave = r.get("clave_acceso", "")
        ctk.CTkButton(
            row_frame, text="Ver XML", width=70, height=24,
            fg_color="#475569", hover_color="#334155",
            command=lambda cl=clave: self._ver_xml(cl),
        ).pack(side="right", padx=6, pady=4)

    def _ver_xml(self, clave: str):
        """Abre modal con el XML del comprobante (carga desde BD)."""
        facade = self._get_facade()
        # Usar SQL directo para traer el xml_recibido
        try:
            import asyncio
            from sqlalchemy import text
            async def _run():
                async with facade.engine.connect() as conn:
                    res = (await conn.execute(
                        text("SELECT xml_recibido FROM facturapro_inbox "
                             "WHERE clave_acceso = :ca").bindparams(ca=clave)
                    )).scalar()
                    return res
            loop = asyncio.new_event_loop()
            try:
                xml = loop.run_until_complete(_run())
            finally:
                loop.close()
        except Exception as e:
            self.modal().error(self.parent, "Ver XML", f"No se pudo leer: {e}")
            return
        if not xml:
            self.modal().error(self.parent, "Ver XML",
                               "No se encontró el comprobante.")
            return
        # Modal con textbox scrollable para el XML
        top = ctk.CTkToplevel(self.parent)
        top.title(f"XML — {clave[:16]}…")
        top.geometry("780x520")
        top.transient(self.parent)
        try:
            top.grab_set()
        except Exception:
            pass
        txt = ctk.CTkTextbox(top, font=ctk.CTkFont(family="Consolas", size=11))
        txt.pack(fill="both", expand=True, padx=8, pady=8)
        txt.insert("1.0", xml)
        txt.configure(state="disabled")
        ctk.CTkButton(top, text="Cerrar", command=top.destroy,
                      fg_color="#475569", hover_color="#334155").pack(pady=8)

    def _after_load_inbox(self, res):
        if not res.success:
            self.status(res.message)

    def _update_nav(self, n_rows: int):
        # Habilitar/deshabilitar según posición
        self.btn_prev.configure(state="normal" if self._inbox_offset > 0 else "disabled")
        self.btn_next.configure(
            state="normal" if n_rows == self._PAGE_SIZE else "disabled")

    # ════════════════════════════════════════════════════════════════════
    #  Helpers
    # ════════════════════════════════════════════════════════════════════
    def _get_facade(self) -> SRIFacade:
        """Crea (con cache) el SRIFacade usando el DbConfig del DB Viewer.

        Esto reutiliza la misma configuración PG local/VPN que ya eligió el
        usuario en la tab "Base de Datos & Docker", así los comprobantes se
        guardan en la misma BD que el DB Viewer lista.
        """
        if self.facade is not None:
            return self.facade
        # Bastard: tomar el DbConfig del db_tab si está montado para no duplicar
        try:
            for tab in self.ctx.root.tab_instances:
                getter = getattr(tab, "_build_dbconfig", None)
                if callable(getter):
                    cfg = getter()
                    self.facade = SRIFacade(cfg)
                    return self.facade
        except Exception:
            pass
        # Fallback: construir desde config directo
        from ui.tabs.db_viewer.connection_manager import DbConfig
        cfg = DbConfig(
            host=self.config.get("pg_host", "127.0.0.1"),
            port=int(self.config.get("pg_port", 5432) or 5432),
            db=self.config.get("pg_db", "facturapro_db"),
            user=self.config.get("pg_user", "postgres_user"),
            password=self.config.get("pg_pass", "ClaveSegura123!"),
            driver="asyncpg",
        )
        self.facade = SRIFacade(cfg)
        return self.facade

    def _save_imap_settings(self):
        """Persiste las creds IMAP si remember_forms está activo."""
        if not self.config.get("remember_forms", True):
            return
        try:
            port = int(self.entry_imap_port.get().strip() or 993)
        except Exception:
            port = 993
        # No usar save_config (que escribe entero): usar set por-key (cada
        # uno disca a disco). Es más writes pero más simple que acumular.
        for k, v in {
            "sri_imap_host": self.entry_imap_host.get().strip(),
            "sri_imap_port": port,
            "sri_imap_user": self.entry_imap_user.get().strip(),
            "sri_imap_pass": self.entry_imap_pass.get(),
            "sri_imap_folder": self.entry_imap_folder.get().strip() or "INBOX",
        }.items():
            self.config.set(k, v)

    def _log(self, msg: str):
        """Anexa una línea al log en vivo del sub-área receptor IMAP."""
        try:
            ts = datetime.now().strftime("%H:%M:%S")
            self.log_box.insert("end", f"[{ts}] {msg}\n")
            self.log_box.see("end")
        except Exception:
            pass

    # ════════════════════════════════════════════════════════════════════
    #  Persistencia de estado (Fase 5b)
    # ════════════════════════════════════════════════════════════════════
    def collect_settings(self) -> dict:
        """Recolecta los valores para el 'Guardar Toda la Configuración'."""
        try:
            interval = int(self.entry_sync_interval.get().strip() or 15)
        except Exception:
            interval = 15
        return {
            "sri_imap_host": self.entry_imap_host.get().strip(),
            "sri_imap_port": int(self.entry_imap_port.get().strip() or 993),
            "sri_imap_user": self.entry_imap_user.get().strip(),
            "sri_imap_pass": self.entry_imap_pass.get(),
            "sri_imap_folder": self.entry_imap_folder.get().strip() or "INBOX",
            "sri_auto_sync": self.switch_auto.get() == 1,
            "sri_sync_interval_min": interval,
        }

    def on_tab_destroyed(self):
        """Limpieza cuando se cierra la app."""
        self._cancel_auto_sync()
