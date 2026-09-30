"""ftp_tab — Área "FTP Temporal / Permanente".

Migración 1:1 de `AppGUI._build_ftp_tab` + callbacks `_ftp_tick`, `_ftp_finish`,
`start_ftp_temp`, `stop_ftp_temp`, `start_ftp_perm`, `on_slider_change`.

Mejora Fase 0: las acciones de abrir/cerrar firewall se envuelven con
AsyncButton para evitar que la UI se congele mientras se ejecuta PowerShell.
"""
from __future__ import annotations

import customtkinter as ctk

from core.base_tab import TabBase, COLORS
from ui.widgets.async_button import AsyncButton
from ui.widgets.modal import Modal


class FtpTab(TabBase):
    title = "FTP Temporal / Permanente"
    icon = "⏱️"

    def build(self, parent):
        self.parent = parent
        c = self.color
        runner = self.ctx.async_runner

        ctk.CTkLabel(parent, text="Apertura de Puerto FTP (Temporal o Permanente)",
                     font=ctk.CTkFont(size=14, weight="bold"),
                     text_color=c.c_text_title).pack(anchor="w", padx=16, pady=(16, 6))

        ctk.CTkLabel(parent,
            text="Abre el puerto 21 en el Firewall de Windows/Linux de forma temporal o permanente con filtro de IP.",
            text_color=c.c_text_sub).pack(anchor="w", padx=16, pady=(0, 12))

        ctrl_frame = ctk.CTkFrame(parent, fg_color=c.c_bg_box, corner_radius=10)
        ctrl_frame.pack(fill="x", padx=16, pady=8)

        ctk.CTkLabel(ctrl_frame, text="Tiempo de apertura (minutos):",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=c.c_text_title).pack(anchor="w", padx=12, pady=(12, 4))

        self.slider_min = ctk.CTkSlider(ctrl_frame, from_=5, to=120, number_of_steps=23,
                                         command=self.on_slider_change)
        self.slider_min.set(self.config.get('ftp_temp_minutes', 30))
        self.slider_min.pack(fill="x", padx=12, pady=4)

        self.lbl_min_val = ctk.CTkLabel(ctrl_frame, text="30 minutos",
            font=ctk.CTkFont(size=12, weight="bold"), text_color="#0284C7")
        self.lbl_min_val.pack(anchor="w", padx=12, pady=(0, 8))

        ip_temp_row = ctk.CTkFrame(ctrl_frame, fg_color="transparent")
        ip_temp_row.pack(anchor="w", padx=12, pady=(0, 10))

        ctk.CTkLabel(ip_temp_row, text="IP Fija Permitida (Opcional):",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=c.c_text_title).pack(side="left", padx=(0, 8))

        self.entry_ftp_temp_ip = ctk.CTkEntry(ip_temp_row, width=180,
                                              placeholder_text="ej: 192.168.1.58")
        self.entry_ftp_temp_ip.insert(0, self.config.get('ftp_ip', ''))
        self.entry_ftp_temp_ip.pack(side="left")

        btn_frame = ctk.CTkFrame(parent, fg_color="transparent")
        btn_frame.pack(fill="x", padx=16, pady=12)

        AsyncButton(btn_frame,
            text="🔓 Abrir FTP Temporal Ahora",
            fg_color="#F59E0B", hover_color="#D97706",
            font=ctk.CTkFont(size=13, weight="bold"), height=36,
            runner=runner,
            action=self._start_ftp_temp_action,
            ok_title="FTP Temporal", error_title="FTP Temporal",
            running_text="Abriendo puerto 21…",
            on_done=lambda res: self.status(res.message)
            ).pack(side="left", padx=(0, 12))

        AsyncButton(btn_frame,
            text="🔒 Cerrar Puerto FTP Inmediatamente",
            fg_color="#EF4444", hover_color="#DC2626", height=36,
            runner=runner,
            action=self._stop_ftp_temp_action,
            confirm="¿Cerrar inmediatamente el puerto 21 y limpiar las reglas de firewall FTP?",
            confirm_title="Cerrar FTP",
            dangerous=True,
            ok_title="FTP Temporal", error_title="FTP Temporal",
            running_text="Cerrando puerto 21…",
            on_done=lambda res: self.status(res.message)
            ).pack(side="left")

        # Permanente
        perm_frame = ctk.CTkFrame(parent, fg_color=c.c_bg_box, corner_radius=10)
        perm_frame.pack(fill="x", padx=16, pady=12)

        ctk.CTkLabel(perm_frame,
            text="🌐 Apertura de Puerto FTP Permanente (IP Fija / Red Local)",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#0284C7").pack(anchor="w", padx=12, pady=(10, 2))

        ctk.CTkLabel(perm_frame,
            text="Si no deseas usar temporizadores, abre el puerto 21 de forma permanente o restringido sólo a una IP Fija.",
            font=ctk.CTkFont(size=11), text_color=c.c_text_sub).pack(
                anchor="w", padx=12, pady=(0, 6))

        ip_row = ctk.CTkFrame(perm_frame, fg_color="transparent")
        ip_row.pack(anchor="w", padx=12, pady=(0, 10))

        ctk.CTkLabel(ip_row, text="IP Fija Permitida (Opcional):",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=c.c_text_title).pack(side="left", padx=(0, 8))
        self.entry_ftp_remote_ip = ctk.CTkEntry(ip_row, width=180,
                                                 placeholder_text="ej: 192.168.1.50")
        self.entry_ftp_remote_ip.insert(0, self.config.get('ftp_ip', ''))
        self.entry_ftp_remote_ip.pack(side="left", padx=(0, 12))

        AsyncButton(ip_row,
            text="🔓 Abrir FTP Permanente",
            fg_color="#0284C7", hover_color="#0369A1",
            runner=runner,
            action=self._start_ftp_perm_action,
            ok_title="FTP Permanente", error_title="FTP Permanente",
            warn_on_fail=True,
            running_text="Abriendo FTP permanente…").pack(side="left")

        self.lbl_timer_status = ctk.CTkLabel(parent, text="Estado: Puerto 21 cerrado.",
            font=ctk.CTkFont(size=12, weight="bold"), text_color=c.c_text_sub)
        self.lbl_timer_status.pack(anchor="w", padx=16, pady=8)

        self.progress_ftp = ctk.CTkProgressBar(parent, height=10)
        self.progress_ftp.set(0)
        self.progress_ftp.pack(fill="x", padx=16, pady=4)

    # ─── Persistencia ────────────────────────────────────────────
    def collect_settings(self) -> dict:
        return {
            'ftp_ip': self.entry_ftp_remote_ip.get().strip(),
            'ftp_temp_minutes': int(self.slider_min.get()),
        }

    def _save_quiet(self):
        try:
            self.config.save_config(self.collect_settings())
        except Exception:
            pass

    # ─── Callbacks ────────────────────────────────────────────────
    def on_slider_change(self, value):
        self.lbl_min_val.configure(text=f"{int(value)} minutos")

    def _start_ftp_temp_action(self):
        self._save_quiet()
        mins = int(self.slider_min.get())
        ip = self.entry_ftp_temp_ip.get().strip()
        ok, msg = self.runner.open_temporary_ftp(mins, ip, self._ftp_tick, self._ftp_finish)
        return (ok, msg)

    def _stop_ftp_temp_action(self):
        ok, msg = self.runner.cancel_temporary_ftp()
        self._ftp_finish()
        return (ok, msg)

    def _start_ftp_perm_action(self):
        self._save_quiet()
        ip = self.entry_ftp_remote_ip.get().strip()
        ok, msg = self.runner.open_permanent_ftp(ip)
        return (ok, msg)

    def _ftp_tick(self, rem_sec):
        mins = rem_sec // 60
        secs = rem_sec % 60
        total_sec = int(self.slider_min.get()) * 60
        pct = (total_sec - rem_sec) / total_sec if total_sec > 0 else 0
        try:
            self.progress_ftp.set(pct)
        except Exception:
            pass
        self.lbl_timer_status.configure(
            text=f"🟢 Puerto 21 ABIERTO - Tiempo restante: {mins:02d}:{secs:02d}",
            text_color="#F59E0B")

    def _ftp_finish(self):
        try:
            self.progress_ftp.set(0)
        except Exception:
            pass
        self.lbl_timer_status.configure(text="🔒 Puerto 21 cerrado.", text_color=self.color.c_text_sub)
