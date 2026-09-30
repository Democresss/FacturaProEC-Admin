"""security_tab — Área "🛡️ Ciberseguridad" (Fase 3).

Panel del SecurityGuardian. NO contiene la lógica de detección (esa vive en
`ui/security/guardian.py`, desacoplada y pura). El tab es la ventana SQL+UI
para ver y operar el guardian:

  1. Switches: escudo activo (security_shield_active) y auto-block
     (security_auto_block). Mutan `ctx.root.security_shield_active` Y
     `ctx.security_shield_active` para corregir el bug del bool copiado, y
     persisten via guardian.set_*.
  2. Editor de whitelist de IPs (añadir/quitar). Muta `ctx.known_safe_ips`
     in-place + persiste security_whitelist.
  3. Puertos vigilados editables (security_ports).
  4. Bandeja de eventos (guardian.events, últimos 500).
  5. Botón "Disparar cerrojo ahora" — invoca `runner.emergency_lockdown`
     con auditoría vía `lockdown.trigger_lockdown`.
  6. Refresh del último scan vía ctx.root.guardian.last_scan_result.

Polling de eventos: usamos un `after(2000)` propio que relee
`guardian.events` y repinta la tabla. No competimos con el scan del
guardian (cada 5s) — sólamante leemos.
"""
from __future__ import annotations

from datetime import datetime

import customtkinter as ctk

from core.base_tab import TabBase, COLORS
from ui.widgets.async_button import AsyncButton
from ui.widgets.modal import Modal
from ui.security.connection_audit import whitelist_load
from ui.security.lockdown import trigger_lockdown


class SecurityTab(TabBase):
    title = "Ciberseguridad"
    icon = "🛡️"

    def build(self, parent):
        self.parent = parent
        c = self.color
        self._events_after_id = None

        scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        scroll.pack(fill="both", expand=True)

        ctk.CTkLabel(
            scroll,
            text="Panel de Ciberseguridad — Detección anti-intrusión y cerrojo de emergencia",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=c.c_text_title,
        ).pack(anchor="w", padx=16, pady=(16, 4))
        ctk.CTkLabel(
            scroll,
            text=("Vigila conexiones a puertos 21/22/2022/5432 (configurable). "
                  "Detecta IPs no autorizadas, cuenta fuerza bruta (5 intentos/60s), "
                  "y dispara el cerrojo automáticamente si el auto-block está activo."),
            font=ctk.CTkFont(size=11), text_color=c.c_text_sub,
        ).pack(anchor="w", padx=16, pady=(0, 8))

        self._build_toggles(scroll)
        self._build_whitelist(scroll)
        self._build_ports_lockdown(scroll)
        self._build_events(scroll)

        # Inicia polling de eventos
        self._schedule_events_refresh()

    # ════════════════════════════════════════════════════════════════════
    # 1. Toggles (escudo + auto-block)
    # ════════════════════════════════════════════════════════════════════
    def _build_toggles(self, scroll):
        c = self.color
        box = ctk.CTkFrame(scroll, fg_color=c.c_bg_box, corner_radius=10)
        box.pack(fill="x", padx=16, pady=(0, 12))
        ctk.CTkLabel(
            box, text="⚙️ Estado del escudo",
            font=ctk.CTkFont(size=13, weight="bold"), text_color="#10B981",
        ).pack(anchor="w", padx=12, pady=(10, 6))

        row = ctk.CTkFrame(box, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=(0, 6))
        self.switch_shield = ctk.CTkSwitch(
            row, text="Escudo activo (vigilar puertos)",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=c.c_text_title, command=self._on_toggle_shield,
        )
        if self._guardian() and self._guardian().shield_active:
            self.switch_shield.select()
        self.switch_shield.pack(side="left", padx=(0, 12))

        self.switch_auto = ctk.CTkSwitch(
            row, text="Auto-block (disparar cerrojo al detectar)",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=c.c_text_title, command=self._on_toggle_auto_block,
        )
        if self._guardian() and self._guardian().auto_block:
            self.switch_auto.select()
        self.switch_auto.pack(side="left")

        self.lbl_shield_status = ctk.CTkLabel(
            box, text="", font=ctk.CTkFont(size=11), text_color=c.c_text_sub,
        )
        self.lbl_shield_status.pack(anchor="w", padx=12, pady=(0, 10))
        self._update_shield_label()

    def _on_toggle_shield(self):
        active = self.switch_shield.get() == 1
        g = self._guardian()
        if g is not None:
            g.set_shield_active(active)
        # Sincroniza con AppShell (corregir el bug del bool copiado en ctx)
        try:
            self.ctx.root.security_shield_active = active
            self.ctx.security_shield_active = active
        except Exception:
            pass
        self._update_shield_label()
        self.status(f"Escudo {'activado' if active else 'desactivado'}.")

    def _on_toggle_auto_block(self):
        enabled = self.switch_auto.get() == 1
        g = self._guardian()
        if g is not None:
            g.set_auto_block(enabled)
        self._update_shield_label()
        self.status(f"Auto-block {'activado' if enabled else 'desactivado'}.")

    def _update_shield_label(self):
        g = self._guardian()
        if g is None:
            self.lbl_shield_status.configure(text="Guardian no disponible en este contexto.")
            return
        ports = ", ".join(str(p) for p in g.get_ports()) or "ninguno"
        wl = whitelist_load(self.config)
        self.lbl_shield_status.configure(
            text=f"Puertos vigilados: {ports} · Whitelist: {len(wl)} IPs · "
                 f"Escudo: {'ON' if g.shield_active else 'OFF'} · "
                 f"Auto-block: {'ON' if g.auto_block else 'OFF'}")

    # ════════════════════════════════════════════════════════════════════
    # 2. Whitelist editor
    # ════════════════════════════════════════════════════════════════════
    def _build_whitelist(self, scroll):
        c = self.color
        box = ctk.CTkFrame(scroll, fg_color=c.c_bg_box, corner_radius=10)
        box.pack(fill="x", padx=16, pady=(0, 12))
        ctk.CTkLabel(
            box, text="📋 Whitelist de IPs permitidas",
            font=ctk.CTkFont(size=13, weight="bold"), text_color="#0284C7",
        ).pack(anchor="w", padx=12, pady=(10, 4))
        ctk.CTkLabel(
            box,
            text="Las IPs en esta listanunca alertan. Añade la IP remota del "
                 "VPN/socio si te molesta que alerte '远程' del VPN directo.",
            font=ctk.CTkFont(size=11), text_color=c.c_text_sub,
        ).pack(anchor="w", padx=12, pady=(0, 6))

        # Input + añadir
        form = ctk.CTkFrame(box, fg_color="transparent")
        form.pack(fill="x", padx=12, pady=(0, 6))
        self.entry_wl_ip = ctk.CTkEntry(form, width=200, placeholder_text="192.168.1.50")
        self.entry_wl_ip.pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            form, text="➕ Añadir", width=100, height=32,
            fg_color="#10B981", hover_color="#059669",
            command=self._add_whitelist,
        ).pack(side="left")
        self.entry_wl_ip.bind("<Return>", lambda e: self._add_whitelist())

        # Lista scrollable de IPs en whitelist
        self.wl_list = ctk.CTkScrollableFrame(box, fg_color="transparent", height=120)
        self.wl_list.pack(fill="both", expand=True, padx=12, pady=(0, 10))
        self._refresh_whitelist()

    def _add_whitelist(self):
        ip = (self.entry_wl_ip.get() or "").strip()
        if not ip:
            return
        # Validacion mínima de formato
        if not self._is_valid_ip(ip):
            Modal.error(self.parent, "Whitelist", f"'{ip}' no parece una IP válida.")
            return
        g = self._guardian()
        if g is not None:
            g.add_safe_ip(ip)
        else:
            # Si no hay guardian, persistir directo
            from ui.security.connection_audit import whitelist_load, whitelist_save
            wl = whitelist_load(self.config)
            if ip not in wl:
                wl.append(ip)
                whitelist_save(self.config, wl)
        self.entry_wl_ip.delete(0, "end")
        self._refresh_whitelist()
        self._update_shield_label()
        self.status(f"IP {ip} añadida a whitelist.")

    def _remove_whitelist(self, ip: str):
        g = self._guardian()
        if g is not None:
            g.remove_safe_ip(ip)
        else:
            from ui.security.connection_audit import whitelist_load, whitelist_save
            wl = [x for x in whitelist_load(self.config) if x != ip]
            whitelist_save(self.config, wl)
        self._refresh_whitelist()
        self._update_shield_label()
        self.status(f"IP {ip} quitada de whitelist.")

    @staticmethod
    def _is_valid_ip(ip: str) -> bool:
        try:
            import ipaddress
            ipaddress.ip_address(ip)
            return True
        except ValueError:
            # Permitir hostnames simples (resolución bajo demanda)
            return ("." in ip) and ip.replace(".", "").isalnum() or ip == "*"

    def _refresh_whitelist(self):
        # Limpiar
        for child in self.wl_list.winfo_children():
            child.destroy()
        wl = whitelist_load(self.config)
        if not wl:
            ctk.CTkLabel(self.wl_list, text="(lista vacía — todas las IPs externas "
                                            "serán marcadas como sospechosas)",
                         font=ctk.CTkFont(size=11),
                         text_color=self.color.c_text_sub).pack(anchor="w", padx=8, pady=4)
            return
        for ip in wl:
            row = ctk.CTkFrame(self.wl_list, fg_color=self.color.c_bg_card, corner_radius=6)
            row.pack(fill="x", pady=2, padx=2)
            ctk.CTkLabel(row, text=f"✅ {ip}", anchor="w",
                         font=ctk.CTkFont(size=12)).pack(side="left", padx=8, pady=3)
            ctk.CTkButton(row, text="Quitar", width=70, height=24,
                          fg_color="#EF4444", hover_color="#DC2626",
                          command=lambda x=ip: self._remove_whitelist(x)
                          ).pack(side="right", padx=6, pady=3)

    # ════════════════════════════════════════════════════════════════════
    # 3. Puertos vigilados + cerrojo manual
    # ════════════════════════════════════════════════════════════════════
    def _build_ports_lockdown(self, scroll):
        c = self.color
        box = ctk.CTkFrame(scroll, fg_color=c.c_bg_box, corner_radius=10)
        box.pack(fill="x", padx=16, pady=(0, 12))
        ctk.CTkLabel(
            box, text="🔌 Puertos vigilados + Cerrojo de emergencia",
            font=ctk.CTkFont(size=13, weight="bold"), text_color="#F59E0B",
        ).pack(anchor="w", padx=12, pady=(10, 4))
        ctk.CTkLabel(
            box,
            text="Comma-separated. Defaults: 21 (FTP), 22 (SSH), 2022 (SFTPGo), 5432 (Postgres).",
            font=ctk.CTkFont(size=11), text_color=c.c_text_sub,
        ).pack(anchor="w", padx=12, pady=(0, 6))

        form = ctk.CTkFrame(box, fg_color="transparent")
        form.pack(fill="x", padx=12, pady=(0, 8))
        ports_now = self.config.get("security_ports", [21, 22, 2022, 5432])
        self.entry_ports = ctk.CTkEntry(form, width=180)
        self.entry_ports.insert(0, ", ".join(str(p) for p in ports_now))
        self.entry_ports.pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            form, text="Guardar puertos", width=140, height=32,
            fg_color="#475569", hover_color="#334155",
            command=self._save_ports,
        ).pack(side="left")

        AsyncButton(
            box, text="🔴 Disparar cerrojo de emergencia ahora",
            fg_color="#DC2626", hover_color="#991B1B", height=36,
            runner=self.ctx.async_runner,
            action=self._trigger_lockdown_action,
            confirm="¿Activar el cerrojo de emergencia? "
                    "Cierra todas las reglas de firewall FacturaProEC y FTP temporal.",
            confirm_title="Cerrojo de emergencia", dangerous=True,
            ok_title="Cerrojo",
            running_text="Activando cerrojo…",
            on_done=lambda res: self.modal().ok(
                self.parent, "Cerrojo de emergencia", res.message)
                if res.success else self.modal().error(
                self.parent, "Cerrojo de emergencia", res.message),
        ).pack(anchor="w", padx=12, pady=(4, 12))

    def _save_ports(self):
        raw = self.entry_ports.get().strip()
        try:
            ports = [int(p.strip()) for p in raw.split(",") if p.strip()]
        except ValueError:
            Modal.error(self.parent, "Puertos", "Sólo números separados por comas.")
            return
        if not ports:
            Modal.error(self.parent, "Puertos", "Debes indicar al menos un puerto.")
            return
        g = self._guardian()
        if g is not None:
            g.set_ports(ports)
        else:
            self.config.set("security_ports", ports)
        self._update_shield_label()
        self.status(f"Puertos vigilados: {ports}")

    def _trigger_lockdown_action(self) -> tuple[bool, str]:
        # Usar trigger_lockdown para logging consistente
        res = trigger_lockdown(self.runner, reason="Disparo manual desde panel",
                               ip=None, port=None, log_to_file=True)
        # Restaurar switch en la UI (auto-block puede haber sido apagado out-of-band)
        return (res.ok, res.message)

    # ════════════════════════════════════════════════════════════════════
    # 4. Bandeja de eventos
    # ════════════════════════════════════════════════════════════════════
    def _build_events(self, scroll):
        c = self.color
        box = ctk.CTkFrame(scroll, fg_color=c.c_bg_box, corner_radius=10)
        box.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        ctk.CTkLabel(
            box, text="🚨 Bandeja de eventos de seguridad",
            font=ctk.CTkFont(size=13, weight="bold"), text_color="#EF4444",
        ).pack(anchor="w", padx=12, pady=(10, 4))

        self.lbl_event_count = ctk.CTkLabel(
            box, text="—", font=ctk.CTkFont(size=11),
            text_color=c.c_text_sub)
        self.lbl_event_count.pack(anchor="w", padx=12, pady=(0, 4))

        self.events_list = ctk.CTkScrollableFrame(box, fg_color="transparent", height=200)
        self.events_list.pack(fill="both", expand=True, padx=12, pady=(0, 6))

        btns = ctk.CTkFrame(box, fg_color="transparent")
        btns.pack(fill="x", padx=12, pady=(0, 10))
        ctk.CTkButton(
            btns, text="🗑 Limpiar historial", width=160, height=30,
            fg_color="#475569", hover_color="#334155",
            command=self._clear_events,
        ).pack(side="left")
        ctk.CTkButton(
            btns, text="📁 Abrir security.log", width=180, height=30,
            fg_color="#475569", hover_color="#334155",
            command=self._open_log_file,
        ).pack(side="left", padx=8)

    def _schedule_events_refresh(self):
        """Polling: relee guardian.events cada 2s y repinta la bandeja."""
        try:
            self._refresh_events()
        except Exception:
            pass
        self._events_after_id = self.ctx.root.after(2000, self._schedule_events_refresh)

    def _refresh_events(self):
        g = self._guardian()
        if g is None:
            return
        # Limpiar lista
        for child in self.events_list.winfo_children():
            child.destroy()
        events = g.events[-50:]  # últimas 50 entries para la UI
        self.lbl_event_count.configure(
            text=f"Mostrando {len(events)} de {len(g.events)} eventos (último scan: "
                 f"{'detectadas' if g.last_scan_result and g.last_scan_result.alerts else 'limpio'})")
        if not events:
            ctk.CTkLabel(self.events_list, text="(sin eventos — escudo vigilando limpio)",
                         font=ctk.CTkFont(size=11), text_color=self.color.c_text_sub
                         ).pack(anchor="w", padx=8, pady=4)
            return
        # Mostrar en orden inverso (más reciente arriba)
        for ev in reversed(events):
            self._render_event(ev)

    def _render_event(self, ev):
        c = self.color
        # color según kind
        if ev.kind == "bruteforce":
            fg = "#7F1D1D"
            txt_color = "#FCA5A5"
            icon = "🔥"
        elif ev.kind == "lockdown":
            fg = "#7C2D12"
            txt_color = "#FED7AA"
            icon = "🔒"
        else:
            fg = c.c_bg_card
            txt_color = "#F59E0B"
            icon = "⚠️"
        row = ctk.CTkFrame(self.events_list, fg_color=fg, corner_radius=6)
        row.pack(fill="x", pady=2, padx=2)
        # Tratar ts (cobra un formato ISO con T)
        ts_str = ev.timestamp.replace("T", " ") if hasattr(ev, "timestamp") else "?"
        info = (f"{icon} {ts_str} · IP {ev.ip}:{ev.port} · {ev.kind}")
        ctk.CTkLabel(row, text=info, anchor="w",
                     font=ctk.CTkFont(size=11), text_color=txt_color
                     ).pack(side="left", padx=8, pady=4)
        if ev.detail:
            ctk.CTkLabel(row, text=ev.detail, anchor="w",
                         font=ctk.CTkFont(size=10), text_color=c.c_text_sub
                         ).pack(side="left", padx=8, pady=4)

    def _clear_events(self):
        g = self._guardian()
        if g is not None:
            g.clear_events()
        self._refresh_events()
        self.status("Historial de eventos limpiado.")

    def _open_log_file(self):
        """Abre security.log con el visor por defecto del SO."""
        import os
        if os.name == "nt":
            log_dir = os.path.join(os.getenv("APPDATA", "~"), "FacturaProEC")
        else:
            log_dir = os.path.expanduser("~/.config/FacturaProEC")
        log_path = os.path.join(log_dir, "security.log")
        if not os.path.exists(log_path):
            Modal.warn(self.parent, "security.log", "Aún no hay eventos registrados en log.")
            return
        try:
            if os.name == "nt":
                os.startfile(log_path)  # type: ignore
            else:
                import subprocess
                subprocess.Popen(["xdg-open", log_path])
            self.status("Abriendo security.log…")
        except Exception as e:
            Modal.error(self.parent, "security.log", f"No se pudo abrir: {e}")

    # ════════════════════════════════════════════════════════════════════
    # Helpers + lifecycle
    # ════════════════════════════════════════════════════════════════════
    def _guardian(self):
        """El SecurityGuardian lo construye AppShell. Si aún no está
        disponible (p.ej. tab montada antes de que se arme el guardián),
        devolvemos None y la tab funciona en modo degradado."""
        return getattr(self.ctx.root, "guardian", None)

    def collect_settings(self) -> dict:
        return {
            "security_shield_active": bool(self.switch_shield.get() == 1),
            "security_auto_block": bool(self.switch_auto.get() == 1),
        }

    def on_tab_destroyed(self):
        if self._events_after_id is not None:
            try:
                self.ctx.root.after_cancel(self._events_after_id)
            except Exception:
                pass
