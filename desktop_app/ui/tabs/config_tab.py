"""config_tab — Área "Configuración & Ciberseguridad".

Migración 1:1 de `AppGUI._build_config_tab` con sus callbacks
`toggle_security_shield`, `change_theme`, `toggle_autostart`, `save_settings`.

Novedad Fase 0: la acción "Guardar Toda la Configuración" se envuelve con
AsyncButton + modal de éxito. Recoge `collect_settings()` de cada área de
trabajo registrada (vía `ctx.root.tab_instances`) y funde los dicts antes
de persistir en disco.
"""
from __future__ import annotations

import customtkinter as ctk

from core.base_tab import TabBase, COLORS
from ui.widgets.async_button import AsyncButton
from ui.widgets.modal import Modal


class ConfigTab(TabBase):
    title = "Configuración & Ciberseguridad"
    icon = "⚙️"

    def build(self, parent):
        self.parent = parent
        c = self.color
        runner = self.ctx.async_runner

        ctk.CTkLabel(parent, text="Configuración General del Sistema, Ciberseguridad y Temas",
                     font=ctk.CTkFont(size=14, weight="bold"),
                     text_color=c.c_text_title).pack(anchor="w", padx=16, pady=(16, 6))

        # ─── Escudo anti-intrusión ───────────────────────────────
        sec_box = ctk.CTkFrame(parent, fg_color=c.c_bg_box, corner_radius=10)
        sec_box.pack(fill="x", padx=16, pady=12)

        ctk.CTkLabel(sec_box, text="🛡️ Escudo de Ciberseguridad & Anti-Intrusión",
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color="#10B981").pack(anchor="w", padx=12, pady=(10, 2))

        ctk.CTkLabel(sec_box,
            text="Monitorea activamente puertos de red (22, 21, 5432) en busca de conexiones "
                 "no autorizadas o exploits de fuerza bruta.",
            font=ctk.CTkFont(size=11), text_color=c.c_text_sub).pack(
                anchor="w", padx=12, pady=(0, 8))

        self.switch_shield = ctk.CTkSwitch(sec_box,
            text="Activar Escudo de Ciberseguridad en Tiempo Real",
            font=ctk.CTkFont(size=12, weight="bold"), text_color=c.c_text_title,
            command=self.toggle_security_shield)
        # Inicializar según estado de la shell
        if self.ctx.security_shield_active:
            self.switch_shield.select()
        self.switch_shield.pack(anchor="w", padx=12, pady=(0, 12))

        # ─── Temas ───────────────────────────────────────────────
        theme_frame = ctk.CTkFrame(parent, fg_color=c.c_bg_box, corner_radius=10)
        theme_frame.pack(fill="x", padx=16, pady=12)

        ctk.CTkLabel(theme_frame, text="🎨 Tema Visual de la Aplicación",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color="#0284C7").pack(anchor="w", padx=12, pady=(10, 4))

        theme_btn_row = ctk.CTkFrame(theme_frame, fg_color="transparent")
        theme_btn_row.pack(anchor="w", padx=12, pady=(0, 10))
        ctk.CTkButton(theme_btn_row, text="🌙 Modo Oscuro (Dark)",
                      fg_color="#1E293B", hover_color="#334155",
                      command=lambda: self.ctx.root.change_theme("Dark")).pack(
                          side="left", padx=(0, 8))
        ctk.CTkButton(theme_btn_row, text="☀️ Modo Claro (Light)",
                      fg_color="#E2E8F0", text_color="#0F172A",
                      hover_color="#CBD5E1",
                      command=lambda: self.ctx.root.change_theme("Light")).pack(
                          side="left", padx=(0, 8))
        ctk.CTkButton(theme_btn_row, text="💻 Según el Sistema (System)",
                      fg_color="#475569", hover_color="#334155",
                      command=lambda: self.ctx.root.change_theme("System")).pack(side="left")

        # ─── Autostart ────────────────────────────────────────────
        self.switch_autostart = ctk.CTkSwitch(parent,
            text="Iniciar automáticamente con Windows",
            font=ctk.CTkFont(size=12, weight="bold"), text_color=c.c_text_title,
            command=self.toggle_autostart)
        if self.config.get('autostart', True):
            self.switch_autostart.select()
        self.switch_autostart.pack(anchor="w", padx=16, pady=16)

        # ─── Guardar todo ──────────────────────────────────────────
        AsyncButton(parent,
            text="💾 Guardar Toda la Configuración (1-Clic)",
            fg_color="#10B981", hover_color="#059669",
            font=ctk.CTkFont(size=13, weight="bold"), height=38,
            runner=runner,
            action=self._save_all_action,
            ok_title="Configuración",
            running_text="Guardando configuración…",
            on_done=lambda res: self.status("Configuración guardada en config.json.")
            ).pack(anchor="w", padx=16, pady=8)

    # ─── Callbacks ────────────────────────────────────────────────
    def toggle_security_shield(self):
        active = self.switch_shield.get() == 1
        # Sincroniza con la shell (que tiene el loop activo).
        try:
            self.ctx.root.security_shield_active = active
        except Exception:
            pass
        self.ctx.security_shield_active = active
        self.status(f"Escudo de Ciberseguridad {'activado' if active else 'desactivado'}.")

    def toggle_autostart(self):
        enable = self.switch_autostart.get() == 1
        ok, msg = self.runner.set_autostart(enable)
        self.status(msg)

    def _save_all_action(self):
        """Recolecta `collect_settings()` de todas las áreas registradas y
        funde los dicts antes de persistir."""
        merged: dict = {}
        # Conservar también el estado de ventana (几何) desde la shell.
        try:
            merged['window_geometry'] = self.ctx.root.geometry()
        except Exception:
            pass
        try:
            for tab in self.ctx.root.tab_instances:
                getter = getattr(tab, "collect_settings", None)
                if callable(getter):
                    try:
                        merged.update(getter() or {})
                    except Exception:
                        pass
        except Exception:
            pass
        try:
            self.config.save_config(merged)
        except Exception as e:
            return (False, f"No se pudo guardar: {e}")
        return (True, "✅ Toda la configuración fue guardada de forma permanente en disco.")
