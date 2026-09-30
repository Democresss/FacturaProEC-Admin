"""vpn_tab — Área "Red Privada / VPN".

Migración 1:1 de `AppGUI._build_vpn_tab` (cards Cloudflare + Tailscale)
AMPLIADA con un formulario de PostgreSQL remoto (vía VPN): host, puerto,
usuario, contraseña, base. Esos campos los consume el DB Viewer de la
Fase 1 (connection_manager) cuando el usuario tiene túnel VPN activo y
quiere apuntar la BD a un servidor remoto en vez del Docker local.
"""
from __future__ import annotations

import webbrowser

import customtkinter as ctk

from core.base_tab import TabBase, COLORS
from ui.widgets.modal import Modal


class VpnTab(TabBase):
    title = "Red Privada / VPN"
    icon = "🔒"

    def build(self, parent):
        self.parent = parent
        c = self.color

        ctk.CTkLabel(parent,
            text="Conexión Segura mediante Red Privada (Cloudflare / Tailscale)",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=c.c_text_title).pack(anchor="w", padx=16, pady=(16, 6))

        ctk.CTkLabel(parent,
            text="Para máxima seguridad, conecta tu servidor sin exponer puertos públicos en tu router.",
            text_color=c.c_text_sub).pack(anchor="w", padx=16, pady=(0, 16))

        # Card Cloudflare
        card_cf = ctk.CTkFrame(parent, fg_color=c.c_bg_box, corner_radius=10)
        card_cf.pack(fill="x", padx=16, pady=8)
        ctk.CTkLabel(card_cf, text="☁️ Cloudflare Tunnel (Zero-Trust)",
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color="#0284C7").pack(anchor="w", padx=12, pady=(10, 2))
        ctk.CTkLabel(card_cf,
            text="Crea un túnel seguro con certificado SSL sin requerir apertura de puertos en el router.",
            font=ctk.CTkFont(size=11), text_color=c.c_text_sub).pack(
                anchor="w", padx=12, pady=(0, 8))
        ctk.CTkButton(card_cf, text="📥 Descargar Cloudflare Tunnel (cloudflared)",
                      fg_color="#0284C7", hover_color="#0369A1",
                      command=lambda: webbrowser.open(
                          "https://github.com/cloudflare/cloudflared/releases/latest")
                      ).pack(anchor="w", padx=12, pady=(0, 10))

        # Card Tailscale
        card_ts = ctk.CTkFrame(parent, fg_color=c.c_bg_box, corner_radius=10)
        card_ts.pack(fill="x", padx=16, pady=8)
        ctk.CTkLabel(card_ts, text="🔒 Tailscale Mesh VPN",
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color="#10B981").pack(anchor="w", padx=12, pady=(10, 2))
        ctk.CTkLabel(card_ts,
            text="Asigna una IP privada 100.x.y.z cifrada punto a punto con WireGuard (Gratis hasta 100 dispositivos).",
            font=ctk.CTkFont(size=11), text_color=c.c_text_sub).pack(
                anchor="w", padx=12, pady=(0, 8))
        ctk.CTkButton(card_ts, text="📥 Descargar Tailscale VPN",
                      fg_color="#059669", hover_color="#047857",
                      command=lambda: webbrowser.open("https://tailscale.com/download")
                      ).pack(anchor="w", padx=12, pady=(0, 10))

        # ─── PostgreSQL remoto vía VPN (NUEVO) ─────────────────────
        pg_box = ctk.CTkFrame(parent, fg_color=c.c_bg_box, corner_radius=10)
        pg_box.pack(fill="x", padx=16, pady=12)
        ctk.CTkLabel(pg_box, text="🗄️ Base de Datos Remota vía VPN (Opcional)",
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color="#0284C7").pack(anchor="w", padx=12, pady=(10, 2))
        ctk.CTkLabel(pg_box,
            text="Si tienes una VPN activa (Cloudflare/Tailscale) y tu PostgreSQL está en otro equipo, "
                 "configúralo aquí. El DB Viewer usará estos datos en lugar del local cuando estén presentes.",
            font=ctk.CTkFont(size=11), text_color=c.c_text_sub).pack(
                anchor="w", padx=12, pady=(0, 8))

        form = ctk.CTkFrame(pg_box, fg_color="transparent")
        form.pack(fill="x", padx=12, pady=4)

        ctk.CTkLabel(form, text="Host/IP remoto (vía VPN):",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=c.c_text_title).grid(row=0, column=0, padx=8, pady=6, sticky="w")
        self.entry_pg_remote_host = ctk.CTkEntry(form, width=220,
                                                 placeholder_text="ej: 100.64.0.10")
        self.entry_pg_remote_host.insert(0, self.config.get('pg_remote_host', ''))
        self.entry_pg_remote_host.grid(row=0, column=1, padx=8, pady=6, sticky="w")

        ctk.CTkLabel(form, text="Puerto:",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=c.c_text_title).grid(row=0, column=2, padx=8, pady=6, sticky="w")
        self.entry_pg_remote_port = ctk.CTkEntry(form, width=80)
        self.entry_pg_remote_port.insert(0, str(self.config.get('pg_remote_port', 5432)))
        self.entry_pg_remote_port.grid(row=0, column=3, padx=8, pady=6, sticky="w")

        ctk.CTkLabel(form, text="Base de datos:",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=c.c_text_title).grid(row=1, column=0, padx=8, pady=6, sticky="w")
        self.entry_pg_remote_db = ctk.CTkEntry(form, width=220)
        self.entry_pg_remote_db.insert(0, self.config.get('pg_remote_db', 'facturapro_db'))
        self.entry_pg_remote_db.grid(row=1, column=1, padx=8, pady=6, sticky="w")

        ctk.CTkLabel(form, text="Usuario:",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=c.c_text_title).grid(row=2, column=0, padx=8, pady=6, sticky="w")
        self.entry_pg_remote_user = ctk.CTkEntry(form, width=220)
        self.entry_pg_remote_user.insert(0, self.config.get('pg_remote_user', 'postgres_user'))
        self.entry_pg_remote_user.grid(row=2, column=1, padx=8, pady=6, sticky="w")

        ctk.CTkLabel(form, text="Contraseña:",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=c.c_text_title).grid(row=2, column=2, padx=8, pady=6, sticky="w")
        self.entry_pg_remote_pass = ctk.CTkEntry(form, width=180, show="*")
        self.entry_pg_remote_pass.insert(0, self.config.get('pg_remote_pass', ''))
        self.entry_pg_remote_pass.grid(row=2, column=3, padx=8, pady=6, sticky="w")

        info_row = ctk.CTkFrame(pg_box, fg_color="transparent")
        info_row.pack(fill="x", padx=12, pady=(0, 10))
        ctk.CTkLabel(info_row,
            text="Estos datos NO se mezclan con el PG local; el DB Viewer puede conmutar entre uno y otro.",
            font=ctk.CTkFont(size=10), text_color=c.c_text_sub).pack(side="left")

    # ─── Persistencia ────────────────────────────────────────────
    def collect_settings(self) -> dict:
        try:
            port = int(self.entry_pg_remote_port.get().strip() or 5432)
        except Exception:
            port = 5432
        return {
            'pg_remote_host': self.entry_pg_remote_host.get().strip(),
            'pg_remote_port': port,
            'pg_remote_db': self.entry_pg_remote_db.get().strip(),
            'pg_remote_user': self.entry_pg_remote_user.get().strip(),
            'pg_remote_pass': self.entry_pg_remote_pass.get().strip(),
        }
