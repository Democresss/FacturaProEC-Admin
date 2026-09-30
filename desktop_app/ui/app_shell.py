"""AppShell — esqueleto reactivo de la app (sustituye al monolito AppGUI).

Reescribe `AppGUI` conservando el LOOK y el COMPORTAMIENTO originales:
- Header bar con título, badge ADMIN, cerrojo de emergencia, menú de tema,
  panel de IP con botón "Copiar IP".
- Dashboard de dos cards (Almacenamiento + Estado de Servicios).
- Banner SSH condicional si puerto 22 cerrado.
- Tabview central con las áreas de trabajo registradas en `TabRegistry`.
- Status bar inferior con barra de progreso (feedback de AsyncActionRunner).
- Loops de auto-refresh (4s) y security guardian (5s) — el guardian sigue
  aquí temporalmente en su forma mínima; se refactoriza en la Fase 3.

Diferencia con el original: las áreas de trabajo se registran vía
`TabRegistry` (una lista) y cada una es una clase `TabBase`; el feedback
de acción es asíncrono con la barra de progreso indeterminada.
"""
from __future__ import annotations

import webbrowser

import customtkinter as ctk
from tkinter import filedialog, messagebox

from config_manager import ConfigManager
from service_runner import ServiceRunner
from sys_info import (
    get_local_ip, get_disk_info, count_local_files, check_port_open,
    is_admin, check_active_net_connections,
)

from core.async_runner import AsyncActionRunner
from core.base_tab import AppContext, COLORS, TabBase
from ui.widgets.modal import Modal
from ui.security.guardian import SecurityGuardian
from ui.security.lockdown import trigger_lockdown


ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")


# ─── Registro estático de áreas de trabajo ────────────────────────────
# Pospuesto hasta resolver imports circulares: se llena desde `app_builder.py`.
TAB_REGISTRY: list = []


class AppShell(ctk.CTk):
    """Ventana principal de FacturaProEC AdminPanel."""

    def __init__(self, tab_classes: list = None):
        super().__init__()

        self.title("FacturaProEC - Storage & Infrastructure Manager v2.0.0")

        # ─── Servicios compartidos ──────────────────────────────────
        self.config_mgr = ConfigManager()
        self.runner = ServiceRunner(self.config_mgr)
        self.current_ip = get_local_ip()

        # Restaurar geometría
        saved_geom = self.config_mgr.get('window_geometry', '980x780')
        try:
            self.geometry(saved_geom)
        except Exception:
            self.geometry("980x780")
        self.minsize(880, 640)

        # Estado de seguridad (definitivo en Fase 3, aquí preserva compat)
        self.known_safe_ips = {"127.0.0.1", "0.0.0.0", "::1", self.current_ip}
        # security_shield_active ahora persiste en config (Fase 3)
        self.security_shield_active = bool(
            self.config_mgr.get('security_shield_active', True))

        # ─── SecurityGuardian (Fase 3) — desacoplado de la UI ────────
        # El guardián vive en AppShell y comparte known_safe_ips con las
        # tabs (vía AppContext). El loop _security_guardian_loop delega
        # toda la detección en guardian.scan().
        self.guardian = SecurityGuardian(
            config=self.config_mgr,
            runner=self.runner,
            known_safe_ips=self.known_safe_ips,
        )
        # El guardián nos avisa cuando dispara un cerrojo (autoblock): si
        # la ventana está visible, modal; si está oculta (bandeja), el
        # tray (si está disponible) muestra la notificación. El hook del
        # tray se setea en main.py (Fase 5a) — aquí dejamos el modal
        # como fallback robusto.
        self.guardian.on_lockdown = self._on_guardian_lockdown

        # Tema
        saved_theme = self.config_mgr.get('theme', 'Dark')
        ctk.set_appearance_mode(saved_theme)

        # Cierre
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

        # ─── Construcción UI ────────────────────────────────────────
        self._build_ui()
        self.refresh_stats()

        # ─── Runner compartido (feedback asíncrono) ─────────────────
        self.async_runner = AsyncActionRunner(
            root=self,
            status_label=self.lbl_status_bar,
            progress_bar=self.progress_action,
        )

        # ─── Contexto compartido para las áreas de trabajo ─────────
        self.ctx = AppContext(
            config=self.config_mgr,
            runner=self.runner,
            async_runner=self.async_runner,
            ip=self.current_ip,
            set_status=self.set_status,
            refresh_stats=self.refresh_stats,
            root=self,
            is_admin=is_admin(),
            known_safe_ips=self.known_safe_ips,
            security_shield_active=self.security_shield_active,
        )

        # ─── Montar áreas de trabajo ──────────────────────────────
        self.tab_instances: list[TabBase] = []
        registry = tab_classes or TAB_REGISTRY
        self._mount_tabs(registry)

        # ─── Loops de fondo ────────────────────────────────────────
        self.after(4000, self._auto_refresh_loop)
        self.after(5000, self._security_guardian_loop)

    # ─── UI ─────────────────────────────────────────────────────────
    def _build_ui(self):
        self.c_bg_card = COLORS.c_bg_card
        self.c_bg_box = COLORS.c_bg_box
        self.c_text_title = COLORS.c_text_title
        self.c_text_sub = COLORS.c_text_sub
        self.c_border = COLORS.c_border

        # HEADER BAR
        self.header_frame = ctk.CTkFrame(self, corner_radius=12, fg_color=self.c_bg_card,
                                         border_color=self.c_border, border_width=1)
        self.header_frame.pack(fill="x", padx=16, pady=(16, 8))

        admin_badge = "🛡️ ADMIN" if is_admin() else "⚠️ USUARIO"
        admin_color = "#10B981" if is_admin() else "#F59E0B"

        self.header_title = ctk.CTkLabel(
            self.header_frame, text="⚡ FacturaProEC Storage & Infrastructure Manager v2.0.0",
            font=ctk.CTkFont(size=16, weight="bold"), text_color=self.c_text_title)
        self.header_title.pack(side="left", padx=16, pady=12)

        self.badge_admin = ctk.CTkLabel(
            self.header_frame, text=admin_badge,
            font=ctk.CTkFont(size=11, weight="bold"), text_color=admin_color,
            fg_color=self.c_bg_box, corner_radius=6, padx=8, pady=3)
        self.badge_admin.pack(side="left", padx=(0, 12), pady=12)

        self.btn_lockdown = ctk.CTkButton(
            self.header_frame, text="🔒 Cerrojo & Desconexión (1-Clic)",
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#DC2626", hover_color="#991B1B", height=28,
            command=self.trigger_emergency_lockdown)
        self.btn_lockdown.pack(side="left", padx=(0, 16), pady=12)

        self.theme_var = ctk.StringVar(value=self.config_mgr.get('theme', 'Dark'))
        self.theme_menu = ctk.CTkOptionMenu(
            self.header_frame, values=["Dark", "Light", "System"],
            variable=self.theme_var, width=100, command=self.change_theme)
        self.theme_menu.pack(side="right", padx=(0, 12), pady=10)

        self.ip_frame = ctk.CTkFrame(self.header_frame, fg_color=self.c_bg_box, corner_radius=8)
        self.ip_frame.pack(side="right", padx=12, pady=8)

        self.ip_label = ctk.CTkLabel(
            self.ip_frame, text=f"📋 IP Servidor: {self.current_ip}",
            font=ctk.CTkFont(size=12, weight="bold"), text_color="#0284C7")
        self.ip_label.pack(side="left", padx=10, pady=6)

        self.copy_ip_btn = ctk.CTkButton(
            self.ip_frame, text="Copiar IP", width=75, height=26,
            command=self.copy_ip, fg_color="#0284C7", hover_color="#0369A1")
        self.copy_ip_btn.pack(side="right", padx=(0, 6), pady=6)

        # DASHBOARD STATUS CARDS
        self.dash_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.dash_frame.pack(fill="x", padx=16, pady=8)

        self.card_storage = ctk.CTkFrame(self.dash_frame, fg_color=self.c_bg_card,
                                         border_color=self.c_border, border_width=1, corner_radius=12)
        self.card_storage.pack(side="left", expand=True, fill="both", padx=(0, 6))

        self.lbl_storage_title = ctk.CTkLabel(self.card_storage, text="📂 Almacenamiento Local",
                                              font=ctk.CTkFont(size=13, weight="bold"), text_color=self.c_text_sub)
        self.lbl_storage_title.pack(anchor="w", padx=12, pady=(10, 2))

        self.lbl_storage_path = ctk.CTkLabel(self.card_storage, text=self.config_mgr.get('storage_path'),
                                             font=ctk.CTkFont(size=11), text_color=self.c_text_title)
        self.lbl_storage_path.pack(anchor="w", padx=12, pady=0)

        self.progress_disk = ctk.CTkProgressBar(self.card_storage, height=8)
        self.progress_disk.pack(fill="x", padx=12, pady=6)

        self.lbl_disk_detail = ctk.CTkLabel(self.card_storage, text="Cargando espacio...",
                                            font=ctk.CTkFont(size=10), text_color=self.c_text_sub)
        self.lbl_disk_detail.pack(anchor="w", padx=12, pady=(0, 10))

        self.card_status = ctk.CTkFrame(self.dash_frame, fg_color=self.c_bg_card,
                                        border_color=self.c_border, border_width=1, corner_radius=12)
        self.card_status.pack(side="right", expand=True, fill="both", padx=(6, 0))

        self.lbl_status_title = ctk.CTkLabel(self.card_status, text="🟢 Estado de Servicios & Ciberseguridad",
                                             font=ctk.CTkFont(size=13, weight="bold"), text_color=self.c_text_sub)
        self.lbl_status_title.pack(anchor="w", padx=12, pady=(10, 4))

        self.status_sftp = ctk.CTkLabel(self.card_status, text="• SFTP / SSH (Puerto 22): Verificando...",
                                        font=ctk.CTkFont(size=11), text_color=self.c_text_title)
        self.status_sftp.pack(anchor="w", padx=12, pady=1)

        self.status_pg = ctk.CTkLabel(self.card_status, text="• Base de Datos PG (Puerto 5432): Verificando...",
                                     font=ctk.CTkFont(size=11), text_color=self.c_text_title)
        self.status_pg.pack(anchor="w", padx=12, pady=1)

        self.status_security = ctk.CTkLabel(self.card_status, text="• Escudo Anti-Intrusión: 🛡️ ACTIVO (Sin anomalías)",
                                            font=ctk.CTkFont(size=11), text_color="#10B981")
        self.status_security.pack(anchor="w", padx=12, pady=(1, 10))

        # Banner SSH
        self.ssh_warning_banner = ctk.CTkFrame(self, fg_color="#7C2D12", corner_radius=8)
        self.lbl_ssh_warn = ctk.CTkLabel(self.ssh_warning_banner,
            text="⚠️ El servicio OpenSSH (Puerto 22) está cerrado en este equipo. Actívalo para permitir conexión desde la Web.",
            font=ctk.CTkFont(size=11, weight="bold"), text_color="#FEF08A")
        self.lbl_ssh_warn.pack(side="left", padx=12, pady=6)

        # TABVIEW PRINCIPAL
        self.tabview = ctk.CTkTabview(self, corner_radius=12)
        self.tabview.pack(expand=True, fill="both", padx=16, pady=(0, 8))

        # STATUS BAR (con barra de progreso de acción — la novedad reactiva)
        self.status_bar = ctk.CTkFrame(self, height=36, fg_color=self.c_bg_card, corner_radius=0)
        self.status_bar.pack(fill="x", side="bottom")

        self.lbl_status_bar = ctk.CTkLabel(self.status_bar, text="Sistema listo. Escudo de Ciberseguridad activo.",
                                          font=ctk.CTkFont(size=11), text_color=self.c_text_sub)
        self.lbl_status_bar.pack(side="left", padx=12, pady=6)

        # Barra de progreso para el AsyncActionRunner (inicialmente oculta)
        self.progress_action = ctk.CTkProgressBar(self.status_bar, width=140, height=8)
        self.progress_action.set(0)
        self.progress_action.pack(side="right", padx=12, pady=6)

    # ─── Montaje de áreas de trabajo ──────────────────────────────
    def _mount_tabs(self, tab_classes: list):
        for cls in tab_classes:
            instance = cls(self.ctx)
            label = f"{getattr(cls, 'icon', '📂')} {getattr(cls, 'title', cls.__name__)}"
            frame = self.tabview.add(label)
            instance.build(frame)
            self.tab_instances.append(instance)

    # ─── Acciones globales (header/statuses originales) ─────────
    def change_theme(self, new_theme):
        ctk.set_appearance_mode(new_theme)
        self.config_mgr.set('theme', new_theme)
        self.set_status(f"Tema cambiado a: {new_theme}")

    def trigger_emergency_lockdown(self):
        def _do():
            ok, msg = self.runner.emergency_lockdown()
            self.set_status("Cerrojo de emergencia activado.")
            self.refresh_stats()
            return (ok, msg)
        Modal.confirm(self, "🔒 Cerrojo de Emergencia",
                      "¿Deseas cerrar inmediatamente todos los puertos de red (22, 21, 5432) y reglas de firewall por seguridad?",
                      dangerous=True,
                      on_yes=lambda: self.async_runner.run(
                          action=_do,
                          on_done=lambda res: Modal.warn(self, "Cerrojo Activado", res.message),
                          status_msg="Activando cerrojo…"))

    def copy_ip(self):
        self.clipboard_clear()
        self.clipboard_append(self.current_ip)
        self.set_status("IP copiada al portapapeles.")

    def set_status(self, msg):
        self.lbl_status_bar.configure(text=msg)

    # ─── Refresh del dashboard (idéntico a AppGUI.refresh_stats) ──
    def refresh_stats(self):
        path = self.config_mgr.get('storage_path', r'C:\factura_uploads')
        disk = get_disk_info(path)
        n_files = count_local_files(path)

        pct = disk['used_pct'] / 100.0
        try:
            self.progress_disk.set(pct)
        except Exception:
            pass
        self.lbl_disk_detail.configure(
            text=f"Espacio Usado: {disk['used_gb']} GB de {disk['total_gb']} GB ({disk['used_pct']}%) | Archivos almacenados: {n_files}"
        )

        ip = self.current_ip
        sftp_ok = check_port_open(ip, 22)
        pg_ok = check_port_open(ip, 5432)

        self.status_sftp.configure(
            text=f"• SFTP / SSH (Puerto 22): {'🟢 Activo' if sftp_ok else '🔴 Inactivo / Cerrado'}",
            text_color="#10B981" if sftp_ok else "#F43F5E"
        )
        self.status_pg.configure(
            text=f"• Base de Datos PG (Puerto 5432): {'🟢 Activa' if pg_ok else '🔴 Inactiva / Cerrado'}",
            text_color="#10B981" if pg_ok else "#F43F5E"
        )

        if not sftp_ok:
            try:
                self.ssh_warning_banner.pack(fill="x", padx=16, pady=(0, 8), before=self.tabview)
            except Exception:
                self.ssh_warning_banner.pack(fill="x", padx=16, pady=(0, 8))
        else:
            self.ssh_warning_banner.pack_forget()

    # ─── Guardian (Fase 3) — delega la detección al SecurityGuardian ─
    def _security_guardian_loop(self):
        """Re-armable cada 5s. Delega toda la detección en el guardian.

        El guardián ya: escanea multiplataforma, filtra con whitelist+IPs
        locales, registra fuerza bruta, loguea a security.log, y dispara
        el cerrojo automáticamente si auto_block está activo. Aquí solo
        actualizamos el dashboard y, si hubo alertas, mostramos modal o
        notificación del tray (según la ventana esté visible/oculta).
        """
        try:
            if self.guardian is not None:
                result = self.guardian.scan()
                if result.alerts:
                    # Última alerta para el dashboard
                    a = result.alerts[-1]
                    self.status_security.configure(
                        text=f"🚨 {len(result.alerts)} ALERTA(S) — última: {a.ip}:{a.port} ({a.kind})",
                        text_color="#EF4444",
                    )
                else:
                    # Limpio: sólo si el escudo está activo (respetar)
                    if self.guardian.shield_active:
                        bf_n = sum(1 for e in self.guardian.events[-10:]
                                    if e.kind == "bruteforce")
                        suffix = f" · {bf_n} BF últimos" if bf_n else " (Sin anomalías)"
                        self.status_security.configure(
                            text=f"• Escudo Anti-Intrusión: 🛡️ ACTIVO{suffix}",
                            text_color="#10B981",
                        )
                    else:
                        self.status_security.configure(
                            text="• Escudo Anti-Intrusión: ⏸ PAUSADO",
                            text_color="#F59E0B",
                        )
        except Exception:
            # El loop nunca debe morir; capture genérico y re-arma abajo.
            pass
        self.after(5000, self._security_guardian_loop)

    def _on_guardian_lockdown(self, lock_res):
        """Callback que el guardian invoca (en el hilo UI, vía su caller
        `after(5000, ...)`) cuando dispara un cerrojo automático.

        Si la ventana está visible, modal; si está oculta (minimizada al
        tray de la Fase 5a), preferimos notificación del tray si está
        disponible; sino no rompemos.
        """
        try:
            if self.state() == "normal":
                # Moda visible, modal informativo (no bloqueante ux-wise es
                # un Toplevel con grab_set — el guardian ya actuó, este es
                # solo aviso).
                Modal.error(
                    self,
                    "🚨 Alerta de Ciberseguridad (cerrojo automático)",
                    f"El escudo detectó una conexión no autorizada y disparó el "
                    f"CERROJO DE EMERGENIA.\n\nResultado: {lock_res.message}",
                )
            else:
                # Ventana oculta: si tenemos tray (Fase 5a), notificación.
                tray = getattr(self, "system_tray", None)
                if tray is not None:
                    tray.notify(
                        "FacturaProEC — Alerta de seguridad",
                        f"Cerrojo automático activado: {lock_res.message[:100]}",
                    )
                else:
                    # Sin tray todavía: al menos hacer visible el dashboard
                    # repintando el label (lo verá cuando vuelva a abrir).
                    self.status_security.configure(
                        text=f"🚨 CERROJO AUTOACTIVADO (ver security.log)",
                        text_color="#EF4444",
                    )
        except Exception:
            pass

    def _auto_refresh_loop(self):
        try:
            self.refresh_stats()
        except Exception:
            pass
        self.after(4000, self._auto_refresh_loop)

    # ─── Cierre limpio ───────────────────────────────────────────
    def on_closing(self):
        try:
            self.config_mgr.set('window_geometry', self.geometry())
        except Exception:
            pass
        self.destroy()
