import os
import sys
import webbrowser
import tkinter as tk
from tkinter import filedialog, messagebox
import customtkinter as ctk

from config_manager import ConfigManager
from service_runner import ServiceRunner
from sys_info import (
    get_local_ip, get_disk_info, count_local_files, check_port_open, 
    is_admin, detect_local_services, test_sftp_full_connection,
    check_active_net_connections
)

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

def evaluate_password_strength(password):
    """Evalúa la fortaleza de una contraseña"""
    if not password:
        return "⚪ Vacía", "#94A3B8"
    if len(password) < 6:
        return "🔴 Débil (Muy corta)", "#EF4444"
    
    has_upper = any(c.isupper() for c in password)
    has_lower = any(c.islower() for c in password)
    has_digit = any(c.isdigit() for c in password)
    has_spec = any(not c.isalnum() for c in password)

    score = sum([has_upper, has_lower, has_digit, has_spec])
    if len(password) >= 8 and score >= 3:
        return "🟢 Fuerte", "#10B981"
    elif len(password) >= 6 and score >= 2:
        return "🟡 Media", "#F59E0B"
    else:
        return "🔴 Débil", "#EF4444"

class AppGUI(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("FacturaProEC - Storage & Infrastructure Manager v2.0.0")
        
        self.config_mgr = ConfigManager()
        self.runner = ServiceRunner(self.config_mgr)
        self.current_ip = get_local_ip()

        # Restaurar posición y tamaño de la ventana
        saved_geom = self.config_mgr.get('window_geometry', '980x780')
        try:
            self.geometry(saved_geom)
        except Exception:
            self.geometry("980x780")
            
        self.minsize(880, 640)

        self.security_shield_active = True
        self.known_safe_ips = {"127.0.0.1", "0.0.0.0", "::1", self.current_ip}

        # Aplicar tema visual
        saved_theme = self.config_mgr.get('theme', 'Dark')
        ctk.set_appearance_mode(saved_theme)

        # Evento de cierre de ventana para guardar estado
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

        self._build_ui()
        self.refresh_stats()

        self.after(4000, self._auto_refresh_loop)
        self.after(5000, self._security_guardian_loop)

    def _build_ui(self):
        # Tokens de color adaptativos para Modo Claro / Modo Oscuro
        self.c_bg_card = ("#FFFFFF", "#1E293B")
        self.c_bg_box = ("#F1F5F9", "#0F172A")
        self.c_text_title = ("#0F172A", "#F8FAFC")
        self.c_text_sub = ("#475569", "#94A3B8")
        self.c_border = ("#CBD5E1", "#334155")

        # HEADER BAR
        self.header_frame = ctk.CTkFrame(self, corner_radius=12, fg_color=self.c_bg_card, border_color=self.c_border, border_width=1)
        self.header_frame.pack(fill="x", padx=16, pady=(16, 8))

        admin_badge = "🛡️ ADMIN" if is_admin() else "⚠️ USUARIO"
        admin_color = "#10B981" if is_admin() else "#F59E0B"

        self.header_title = ctk.CTkLabel(
            self.header_frame, 
            text="⚡ FacturaProEC Storage & Infrastructure Manager v2.0.0",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=self.c_text_title
        )
        self.header_title.pack(side="left", padx=16, pady=12)

        self.badge_admin = ctk.CTkLabel(
            self.header_frame,
            text=admin_badge,
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=admin_color,
            fg_color=self.c_bg_box,
            corner_radius=6,
            padx=8,
            pady=3
        )
        self.badge_admin.pack(side="left", padx=(0, 12), pady=12)

        self.btn_lockdown = ctk.CTkButton(
            self.header_frame,
            text="🔒 Cerrojo & Desconexión (1-Clic)",
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#DC2626",
            hover_color="#991B1B",
            height=28,
            command=self.trigger_emergency_lockdown
        )
        self.btn_lockdown.pack(side="left", padx=(0, 16), pady=12)

        self.theme_var = ctk.StringVar(value=self.config_mgr.get('theme', 'Dark'))
        self.theme_menu = ctk.CTkOptionMenu(
            self.header_frame,
            values=["Dark", "Light", "System"],
            variable=self.theme_var,
            width=100,
            command=self.change_theme
        )
        self.theme_menu.pack(side="right", padx=(0, 12), pady=10)

        self.ip_frame = ctk.CTkFrame(self.header_frame, fg_color=self.c_bg_box, corner_radius=8)
        self.ip_frame.pack(side="right", padx=12, pady=8)

        self.ip_label = ctk.CTkLabel(
            self.ip_frame, 
            text=f"📋 IP Servidor: {self.current_ip}",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#0284C7"
        )
        self.ip_label.pack(side="left", padx=10, pady=6)

        self.copy_ip_btn = ctk.CTkButton(
            self.ip_frame, 
            text="Copiar IP", 
            width=75, 
            height=26, 
            command=self.copy_ip,
            fg_color="#0284C7", 
            hover_color="#0369A1"
        )
        self.copy_ip_btn.pack(side="right", padx=(0, 6), pady=6)

        # DASHBOARD STATUS CARDS
        self.dash_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.dash_frame.pack(fill="x", padx=16, pady=8)

        self.card_storage = ctk.CTkFrame(self.dash_frame, fg_color=self.c_bg_card, border_color=self.c_border, border_width=1, corner_radius=12)
        self.card_storage.pack(side="left", expand=True, fill="both", padx=(0, 6))

        self.lbl_storage_title = ctk.CTkLabel(self.card_storage, text="📂 Almacenamiento Local", font=ctk.CTkFont(size=13, weight="bold"), text_color=self.c_text_sub)
        self.lbl_storage_title.pack(anchor="w", padx=12, pady=(10, 2))

        self.lbl_storage_path = ctk.CTkLabel(self.card_storage, text=self.config_mgr.get('storage_path'), font=ctk.CTkFont(size=11), text_color=self.c_text_title)
        self.lbl_storage_path.pack(anchor="w", padx=12, pady=0)

        self.progress_disk = ctk.CTkProgressBar(self.card_storage, height=8)
        self.progress_disk.pack(fill="x", padx=12, pady=6)

        self.lbl_disk_detail = ctk.CTkLabel(self.card_storage, text="Cargando espacio...", font=ctk.CTkFont(size=10), text_color=self.c_text_sub)
        self.lbl_disk_detail.pack(anchor="w", padx=12, pady=(0, 10))

        self.card_status = ctk.CTkFrame(self.dash_frame, fg_color=self.c_bg_card, border_color=self.c_border, border_width=1, corner_radius=12)
        self.card_status.pack(side="right", expand=True, fill="both", padx=(6, 0))

        self.lbl_status_title = ctk.CTkLabel(self.card_status, text="🟢 Estado de Servicios & Ciberseguridad", font=ctk.CTkFont(size=13, weight="bold"), text_color=self.c_text_sub)
        self.lbl_status_title.pack(anchor="w", padx=12, pady=(10, 4))

        self.status_sftp = ctk.CTkLabel(self.card_status, text="• SFTP / SSH (Puerto 22): Verificando...", font=ctk.CTkFont(size=11), text_color=self.c_text_title)
        self.status_sftp.pack(anchor="w", padx=12, pady=1)

        self.status_pg = ctk.CTkLabel(self.card_status, text="• Base de Datos PG (Puerto 5432): Verificando...", font=ctk.CTkFont(size=11), text_color=self.c_text_title)
        self.status_pg.pack(anchor="w", padx=12, pady=1)

        self.status_security = ctk.CTkLabel(self.card_status, text="• Escudo Anti-Intrusión: 🛡️ ACTIVO (Sin anomalías)", font=ctk.CTkFont(size=11), text_color="#10B981")
        self.status_security.pack(anchor="w", padx=12, pady=(1, 10))

        # Banner SSH
        self.ssh_warning_banner = ctk.CTkFrame(self, fg_color="#7C2D12", corner_radius=8)
        self.lbl_ssh_warn = ctk.CTkLabel(self.ssh_warning_banner, text="⚠️ El servicio OpenSSH (Puerto 22) está cerrado en este equipo. Actívalo para permitir conexión desde la Web.", font=ctk.CTkFont(size=11, weight="bold"), text_color="#FEF08A")
        self.lbl_ssh_warn.pack(side="left", padx=12, pady=6)

        # TABVIEW PRINCIPAL
        self.tabview = ctk.CTkTabview(self, corner_radius=12)
        self.tabview.pack(expand=True, fill="both", padx=16, pady=(0, 8))

        self.tab_storage = self.tabview.add("📂 Almacenamiento & SSH")
        self.tab_tester = self.tabview.add("📡 Probador de Servidor Remoto")
        self.tab_db = self.tabview.add("🗄️ Base de Datos & Docker")
        self.tab_ftp = self.tabview.add("⏱️ FTP Temporal / Permanente")
        self.tab_vpn = self.tabview.add("🔒 Red Privada / VPN")
        self.tab_config = self.tabview.add("⚙️ Configuración & Ciberseguridad")

        self._build_storage_tab()
        self._build_tester_tab()
        self._build_db_tab()
        self._build_ftp_tab()
        self._build_vpn_tab()
        self._build_config_tab()

        self.status_bar = ctk.CTkFrame(self, height=28, fg_color=self.c_bg_card, corner_radius=0)
        self.status_bar.pack(fill="x", side="bottom")

        self.lbl_status_bar = ctk.CTkLabel(self.status_bar, text="Sistema listo. Escudo de Ciberseguridad activo.", font=ctk.CTkFont(size=11), text_color=self.c_text_sub)
        self.lbl_status_bar.pack(side="left", padx=12, pady=4)

    def _build_storage_tab(self):
        lbl = ctk.CTkLabel(self.tab_storage, text="Directorio Local para Almacenamiento de Archivos y Facturas", font=ctk.CTkFont(size=14, weight="bold"), text_color=self.c_text_title)
        lbl.pack(anchor="w", padx=16, pady=(16, 6))

        box = ctk.CTkFrame(self.tab_storage, fg_color=self.c_bg_box, corner_radius=10)
        box.pack(fill="x", padx=16, pady=8)

        lbl_path_title = ctk.CTkLabel(box, text="Ruta de Almacenamiento en Disco:", font=ctk.CTkFont(size=12, weight="bold"), text_color=self.c_text_title)
        lbl_path_title.pack(anchor="w", padx=12, pady=(10, 4))

        path_row = ctk.CTkFrame(box, fg_color="transparent")
        path_row.pack(fill="x", padx=12, pady=(0, 10))

        self.entry_path = ctk.CTkEntry(path_row, width=480)
        self.entry_path.insert(0, self.config_mgr.get('storage_path', r'C:actura_uploads'))
        self.entry_path.pack(side="left", padx=(0, 8))

        btn_browse = ctk.CTkButton(path_row, text="Buscar Carpeta...", command=self.browse_folder)
        btn_browse.pack(side="left")

        btn_row_st = ctk.CTkFrame(self.tab_storage, fg_color="transparent")
        btn_row_st.pack(anchor="w", padx=16, pady=12)

        btn_create = ctk.CTkButton(btn_row_st, text="🚀 Crear y Configurar Ruta Local (1-Clic)", fg_color="#10B981", hover_color="#059669", font=ctk.CTkFont(size=13, weight="bold"), height=36, command=self.setup_storage)
        btn_create.pack(side="left", padx=(0, 8))

        btn_test = ctk.CTkButton(btn_row_st, text="🧪 Probar Lectura / Escritura Local", fg_color="#6366F1", hover_color="#4F46E5", height=36, command=self.test_local_storage)
        btn_test.pack(side="left")

        # Sección Servidor SSH + Usuario Restringido
        sftp_user_box = ctk.CTkFrame(self.tab_storage, fg_color=self.c_bg_box, corner_radius=10)
        sftp_user_box.pack(fill="x", padx=16, pady=16)

        lbl_sftp_title = ctk.CTkLabel(sftp_user_box, text="🔑 Servidor SFTP / SSH & Usuario Restringido (Recomendado)", font=ctk.CTkFont(size=13, weight="bold"), text_color="#0284C7")
        lbl_sftp_title.pack(anchor="w", padx=12, pady=(10, 2))

        desc_sftp_info = ctk.CTkLabel(sftp_user_box, text="Instala el servicio OpenSSH en el puerto 22 y crea un usuario dedicado restringido a la carpeta de facturas.", font=ctk.CTkFont(size=11), text_color=self.c_text_sub)
        desc_sftp_info.pack(anchor="w", padx=12, pady=(0, 8))

        form_sftp = ctk.CTkFrame(sftp_user_box, fg_color="transparent")
        form_sftp.pack(fill="x", padx=12, pady=4)

        lbl_u_sftp = ctk.CTkLabel(form_sftp, text="Usuario SFTP (Recomendado):", font=ctk.CTkFont(size=11, weight="bold"), text_color=self.c_text_title)
        lbl_u_sftp.grid(row=0, column=0, padx=(0, 8), pady=4, sticky="w")
        self.entry_sftp_user = ctk.CTkEntry(form_sftp, width=180)
        self.entry_sftp_user.insert(0, self.config_mgr.get('remote_user', 'factura_sftp'))
        self.entry_sftp_user.grid(row=0, column=1, padx=(0, 16), pady=4, sticky="w")

        lbl_p_sftp = ctk.CTkLabel(form_sftp, text="Contraseña SFTP:", font=ctk.CTkFont(size=11, weight="bold"), text_color=self.c_text_title)
        lbl_p_sftp.grid(row=0, column=2, padx=(0, 8), pady=4, sticky="w")
        self.entry_sftp_pass = ctk.CTkEntry(form_sftp, width=180, show="*")
        self.entry_sftp_pass.insert(0, self.config_mgr.get('remote_pass', 'ClaveSFTP123!'))
        self.entry_sftp_pass.grid(row=0, column=3, padx=(0, 8), pady=4, sticky="w")
        self.entry_sftp_pass.bind("<KeyRelease>", self.on_pass_change_sftp)

        self.lbl_strength_sftp = ctk.CTkLabel(form_sftp, text="🟢 Fuerte", font=ctk.CTkFont(size=11, weight="bold"), text_color="#10B981")
        self.lbl_strength_sftp.grid(row=0, column=4, padx=(8, 0), pady=4, sticky="w")

        btn_row_sftp = ctk.CTkFrame(sftp_user_box, fg_color="transparent")
        btn_row_sftp.pack(anchor="w", padx=12, pady=(8, 12))

        btn_create_sftp_u = ctk.CTkButton(btn_row_sftp, text="🚀 Activar OpenSSH & Crear Usuario SFTP (1-Clic)", fg_color="#10B981", hover_color="#059669", font=ctk.CTkFont(size=12, weight="bold"), command=self.create_sftp_user)
        btn_create_sftp_u.pack(side="left", padx=(0, 8))

        btn_open_sftp_port = ctk.CTkButton(btn_row_sftp, text="🔓 Abrir Puerto SFTP (22) en Firewall", fg_color="#0284C7", hover_color="#0369A1", font=ctk.CTkFont(size=12, weight="bold"), command=self.open_sftp_port_firewall)
        btn_open_sftp_port.pack(side="left", padx=(0, 8))

        btn_copy_sftp_info = ctk.CTkButton(btn_row_sftp, text="📋 Copiar Credenciales SFTP para la Web", fg_color="#475569", hover_color="#334155", command=self.copy_sftp_credentials)
        btn_copy_sftp_info.pack(side="left")

    def _build_tester_tab(self):
        lbl = ctk.CTkLabel(self.tab_tester, text="📡 Probador de Servidores SFTP / SSH Remotos (Otra PC o VPS)", font=ctk.CTkFont(size=14, weight="bold"), text_color=self.c_text_title)
        lbl.pack(anchor="w", padx=16, pady=(16, 6))

        desc = ctk.CTkLabel(self.tab_tester, text="Si tus archivos estarán en otro servidor o PC distinta, ingresa sus datos aquí para probar la conexión en tiempo real antes de guardar en la Web.", text_color=self.c_text_sub)
        desc.pack(anchor="w", padx=16, pady=(0, 16))

        test_box = ctk.CTkFrame(self.tab_tester, fg_color=self.c_bg_box, corner_radius=10)
        test_box.pack(fill="x", padx=16, pady=8)

        grid_t = ctk.CTkFrame(test_box, fg_color="transparent")
        grid_t.pack(fill="x", padx=12, pady=12)

        lbl_thost = ctk.CTkLabel(grid_t, text="HOST / IP Remota (Recomendado):", font=ctk.CTkFont(size=11, weight="bold"), text_color=self.c_text_title)
        lbl_thost.grid(row=0, column=0, padx=(0, 8), pady=6, sticky="w")
        self.entry_remote_host = ctk.CTkEntry(grid_t, width=220)
        self.entry_remote_host.insert(0, self.config_mgr.get('remote_host', '192.168.1.58'))
        self.entry_remote_host.grid(row=0, column=1, padx=(0, 16), pady=6, sticky="w")

        lbl_tport = ctk.CTkLabel(grid_t, text="Puerto SSH (Recomendado: 22):", font=ctk.CTkFont(size=11, weight="bold"), text_color=self.c_text_title)
        lbl_tport.grid(row=0, column=2, padx=(0, 8), pady=6, sticky="w")
        self.entry_remote_port = ctk.CTkEntry(grid_t, width=120)
        self.entry_remote_port.insert(0, str(self.config_mgr.get('remote_port', 22)))
        self.entry_remote_port.grid(row=0, column=3, padx=(0, 8), pady=6, sticky="w")

        lbl_tuser = ctk.CTkLabel(grid_t, text="Usuario SSH:", font=ctk.CTkFont(size=11, weight="bold"), text_color=self.c_text_title)
        lbl_tuser.grid(row=1, column=0, padx=(0, 8), pady=6, sticky="w")
        self.entry_remote_user = ctk.CTkEntry(grid_t, width=220)
        self.entry_remote_user.insert(0, self.config_mgr.get('remote_user', 'factura_sftp'))
        self.entry_remote_user.grid(row=1, column=1, padx=(0, 16), pady=6, sticky="w")

        lbl_tpass = ctk.CTkLabel(grid_t, text="Contraseña SSH:", font=ctk.CTkFont(size=11, weight="bold"), text_color=self.c_text_title)
        lbl_tpass.grid(row=1, column=2, padx=(0, 8), pady=6, sticky="w")
        self.entry_remote_pass = ctk.CTkEntry(grid_t, width=180, show="*")
        self.entry_remote_pass.insert(0, self.config_mgr.get('remote_pass', 'ClaveSFTP123!'))
        self.entry_remote_pass.grid(row=1, column=3, padx=(0, 8), pady=6, sticky="w")
        self.entry_remote_pass.bind("<KeyRelease>", self.on_pass_change_remote)

        self.lbl_strength_remote = ctk.CTkLabel(grid_t, text="🟢 Fuerte", font=ctk.CTkFont(size=11, weight="bold"), text_color="#10B981")
        self.lbl_strength_remote.grid(row=1, column=4, padx=(8, 0), pady=6, sticky="w")

        lbl_tpath = ctk.CTkLabel(grid_t, text="Ruta en Servidor:", font=ctk.CTkFont(size=11, weight="bold"), text_color=self.c_text_title)
        lbl_tpath.grid(row=2, column=0, padx=(0, 8), pady=6, sticky="w")
        self.entry_remote_path = ctk.CTkEntry(grid_t, width=220)
        self.entry_remote_path.insert(0, self.config_mgr.get('remote_path', r'C:actura_uploads'))
        self.entry_remote_path.grid(row=2, column=1, padx=(0, 16), pady=6, sticky="w")

        btn_row_tester = ctk.CTkFrame(test_box, fg_color="transparent")
        btn_row_tester.pack(anchor="w", padx=12, pady=(4, 12))

        btn_run_test_remote = ctk.CTkButton(btn_row_tester, text="⚡ Probar Conexión SFTP y Ping (1-Clic)", fg_color="#10B981", hover_color="#059669", font=ctk.CTkFont(size=12, weight="bold"), height=36, command=self.test_remote_sftp)
        btn_run_test_remote.pack(side="left", padx=(0, 8))

        btn_copy_remote_info = ctk.CTkButton(btn_row_tester, text="📋 Copiar Credenciales Probadas para la Web", fg_color="#0284C7", hover_color="#0369A1", height=36, command=self.copy_tested_credentials)
        btn_copy_remote_info.pack(side="left")

    def _build_db_tab(self):
        lbl = ctk.CTkLabel(self.tab_db, text="Configuración de Base de Datos PostgreSQL 17 & Docker Desktop", font=ctk.CTkFont(size=14, weight="bold"), text_color=self.c_text_title)
        lbl.pack(anchor="w", padx=16, pady=(16, 6))

        docker_box = ctk.CTkFrame(self.tab_db, fg_color=self.c_bg_box, corner_radius=10)
        docker_box.pack(fill="x", padx=16, pady=8)

        lbl_dk = ctk.CTkLabel(docker_box, text="🐳 Despliegue en 1-Clic con Docker Desktop", font=ctk.CTkFont(size=13, weight="bold"), text_color="#0284C7")
        lbl_dk.pack(anchor="w", padx=12, pady=(10, 2))

        desc_dk = ctk.CTkLabel(docker_box, text="Si no tienes PostgreSQL instalado, levanta PostgreSQL 17 + MinIO S3 + SFTPGo automáticamente en Docker Desktop.", font=ctk.CTkFont(size=11), text_color=self.c_text_sub)
        desc_dk.pack(anchor="w", padx=12, pady=(0, 8))

        btn_dk_row = ctk.CTkFrame(docker_box, fg_color="transparent")
        btn_dk_row.pack(anchor="w", padx=12, pady=(0, 10))

        btn_run_docker = ctk.CTkButton(btn_dk_row, text="🚀 Levantar Contenedores Docker (1-Clic)", fg_color="#0284C7", hover_color="#0369A1", font=ctk.CTkFont(size=12, weight="bold"), command=self.run_docker_stack)
        btn_run_docker.pack(side="left", padx=(0, 8))

        btn_dl_docker = ctk.CTkButton(btn_dk_row, text="📥 Descargar Docker Desktop", fg_color="#475569", hover_color="#334155", font=ctk.CTkFont(size=12), command=lambda: webbrowser.open("https://www.docker.com/products/docker-desktop/"))
        btn_dl_docker.pack(side="left")

        lbl_cmd_t = ctk.CTkLabel(docker_box, text="📋 Comando Manual CLI para Terminal (Si prefieres no usar la app):", font=ctk.CTkFont(size=11, weight="bold"), text_color=self.c_text_title)
        lbl_cmd_t.pack(anchor="w", padx=12, pady=(4, 2))

        self.box_docker_cmd = ctk.CTkEntry(docker_box, width=650, font=ctk.CTkFont(family="Courier", size=10), text_color="#0284C7")
        self.box_docker_cmd.insert(0, "docker run -d -p 5432:5432 -e POSTGRES_PASSWORD=ClaveSegura123! --name pg17 postgres:17-alpine")
        self.box_docker_cmd.pack(anchor="w", padx=12, pady=(0, 10))

        form = ctk.CTkFrame(self.tab_db, fg_color=self.c_bg_box, corner_radius=10)
        form.pack(fill="x", padx=16, pady=8)

        lbl_h = ctk.CTkLabel(form, text="Host / IP (Recomendado):", font=ctk.CTkFont(size=11, weight="bold"), text_color=self.c_text_title)
        lbl_h.grid(row=0, column=0, padx=12, pady=6, sticky="w")
        self.entry_db_host = ctk.CTkEntry(form, width=220)
        self.entry_db_host.insert(0, self.config_mgr.get('pg_host', self.current_ip))
        self.entry_db_host.grid(row=0, column=1, padx=12, pady=6, sticky="w")
        self.entry_db_host.bind("<KeyRelease>", self.update_conn_str)

        lbl_port = ctk.CTkLabel(form, text="Puerto PG (Recomendado: 5432):", font=ctk.CTkFont(size=11, weight="bold"), text_color=self.c_text_title)
        lbl_port.grid(row=0, column=2, padx=12, pady=6, sticky="w")
        self.entry_db_port = ctk.CTkEntry(form, width=120)
        self.entry_db_port.insert(0, str(self.config_mgr.get('pg_port', 5432)))
        self.entry_db_port.grid(row=0, column=3, padx=12, pady=6, sticky="w")
        self.entry_db_port.bind("<KeyRelease>", self.update_conn_str)

        lbl_db = ctk.CTkLabel(form, text="Base de Datos:", font=ctk.CTkFont(size=11, weight="bold"), text_color=self.c_text_title)
        lbl_db.grid(row=1, column=0, padx=12, pady=6, sticky="w")
        self.entry_db_name = ctk.CTkEntry(form, width=220)
        self.entry_db_name.insert(0, self.config_mgr.get('pg_db', 'facturapro_db'))
        self.entry_db_name.grid(row=1, column=1, padx=12, pady=6, sticky="w")
        self.entry_db_name.bind("<KeyRelease>", self.update_conn_str)

        lbl_u = ctk.CTkLabel(form, text="Usuario PG:", font=ctk.CTkFont(size=11, weight="bold"), text_color=self.c_text_title)
        lbl_u.grid(row=2, column=0, padx=12, pady=6, sticky="w")
        self.entry_db_user = ctk.CTkEntry(form, width=220)
        self.entry_db_user.insert(0, self.config_mgr.get('pg_user', 'postgres_user'))
        self.entry_db_user.grid(row=2, column=1, padx=12, pady=6, sticky="w")
        self.entry_db_user.bind("<KeyRelease>", self.update_conn_str)

        lbl_pass_db = ctk.CTkLabel(form, text="Contraseña PG:", font=ctk.CTkFont(size=11, weight="bold"), text_color=self.c_text_title)
        lbl_pass_db.grid(row=2, column=2, padx=12, pady=6, sticky="w")
        self.entry_db_pass = ctk.CTkEntry(form, width=180, show="*")
        self.entry_db_pass.insert(0, self.config_mgr.get('pg_pass', 'ClaveSegura123!'))
        self.entry_db_pass.grid(row=2, column=3, padx=12, pady=6, sticky="w")
        self.entry_db_pass.bind("<KeyRelease>", self.on_pass_change_db)

        self.lbl_strength_db = ctk.CTkLabel(form, text="🟢 Fuerte", font=ctk.CTkFont(size=11, weight="bold"), text_color="#10B981")
        self.lbl_strength_db.grid(row=2, column=4, padx=(8, 0), pady=6, sticky="w")

        lbl_conn = ctk.CTkLabel(self.tab_db, text="📋 Connection String para FacturaProEC:", font=ctk.CTkFont(size=12, weight="bold"), text_color=self.c_text_title)
        lbl_conn.pack(anchor="w", padx=16, pady=(8, 2))

        self.conn_str_box = ctk.CTkEntry(self.tab_db, width=650, font=ctk.CTkFont(family="Courier", size=11), text_color="#10B981")
        self.conn_str_box.pack(anchor="w", padx=16, pady=2)
        self.update_conn_str()

        btn_row_db = ctk.CTkFrame(self.tab_db, fg_color="transparent")
        btn_row_db.pack(anchor="w", padx=16, pady=6)

        btn_copy_conn = ctk.CTkButton(btn_row_db, text="📋 Copiar String", command=self.copy_conn_str)
        btn_copy_conn.pack(side="left", padx=(0, 8))

        btn_test_db = ctk.CTkButton(btn_row_db, text="🧪 Probar Conexión PG (Puerto 5432)", fg_color="#10B981", hover_color="#059669", command=self.test_pg_conn)
        btn_test_db.pack(side="left", padx=(0, 8))

        btn_open_pg_port = ctk.CTkButton(btn_row_db, text="🔓 Abrir Puerto PostgreSQL (5432) en Firewall", fg_color="#0284C7", hover_color="#0369A1", command=self.open_pg_port_firewall)
        btn_open_pg_port.pack(side="left")

    def _build_ftp_tab(self):
        lbl = ctk.CTkLabel(self.tab_ftp, text="Apertura de Puerto FTP (Temporal o Permanente)", font=ctk.CTkFont(size=14, weight="bold"), text_color=self.c_text_title)
        lbl.pack(anchor="w", padx=16, pady=(16, 6))

        desc = ctk.CTkLabel(self.tab_ftp, text="Abre el puerto 21 en el Firewall de Windows/Linux de forma temporal o permanente con filtro de IP.", text_color=self.c_text_sub)
        desc.pack(anchor="w", padx=16, pady=(0, 12))

        ctrl_frame = ctk.CTkFrame(self.tab_ftp, fg_color=self.c_bg_box, corner_radius=10)
        ctrl_frame.pack(fill="x", padx=16, pady=8)

        lbl_min = ctk.CTkLabel(ctrl_frame, text="Tiempo de apertura (minutos):", font=ctk.CTkFont(size=12, weight="bold"), text_color=self.c_text_title)
        lbl_min.pack(anchor="w", padx=12, pady=(12, 4))

        self.slider_min = ctk.CTkSlider(ctrl_frame, from_=5, to=120, number_of_steps=23, command=self.on_slider_change)
        self.slider_min.set(self.config_mgr.get('ftp_temp_minutes', 30))
        self.slider_min.pack(fill="x", padx=12, pady=4)

        self.lbl_min_val = ctk.CTkLabel(ctrl_frame, text="30 minutos", font=ctk.CTkFont(size=12, weight="bold"), text_color="#0284C7")
        self.lbl_min_val.pack(anchor="w", padx=12, pady=(0, 8))

        ip_temp_row = ctk.CTkFrame(ctrl_frame, fg_color="transparent")
        ip_temp_row.pack(anchor="w", padx=12, pady=(0, 10))

        lbl_t_ip = ctk.CTkLabel(ip_temp_row, text="IP Fija Permitida (Opcional):", font=ctk.CTkFont(size=11, weight="bold"), text_color=self.c_text_title)
        lbl_t_ip.pack(side="left", padx=(0, 8))

        self.entry_ftp_temp_ip = ctk.CTkEntry(ip_temp_row, width=180, placeholder_text="ej: 192.168.1.58")
        self.entry_ftp_temp_ip.insert(0, self.config_mgr.get('ftp_ip', ''))
        self.entry_ftp_temp_ip.pack(side="left")

        btn_frame = ctk.CTkFrame(self.tab_ftp, fg_color="transparent")
        btn_frame.pack(fill="x", padx=16, pady=12)

        self.btn_start_ftp = ctk.CTkButton(btn_frame, text="🔓 Abrir FTP Temporal Ahora", fg_color="#F59E0B", hover_color="#D97706", font=ctk.CTkFont(size=13, weight="bold"), height=36, command=self.start_ftp_temp)
        self.btn_start_ftp.pack(side="left", padx=(0, 12))

        self.btn_stop_ftp = ctk.CTkButton(btn_frame, text="🔒 Cerrar Puerto FTP Inmediatamente", fg_color="#EF4444", hover_color="#DC2626", height=36, command=self.stop_ftp_temp)
        self.btn_stop_ftp.pack(side="left")

        perm_frame = ctk.CTkFrame(self.tab_ftp, fg_color=self.c_bg_box, corner_radius=10)
        perm_frame.pack(fill="x", padx=16, pady=12)

        lbl_perm_title = ctk.CTkLabel(perm_frame, text="🌐 Apertura de Puerto FTP Permanente (IP Fija / Red Local)", font=ctk.CTkFont(size=12, weight="bold"), text_color="#0284C7")
        lbl_perm_title.pack(anchor="w", padx=12, pady=(10, 2))

        desc_perm = ctk.CTkLabel(perm_frame, text="Si no deseas usar temporizadores, abre el puerto 21 de forma permanente o restringido sólo a una IP Fija.", font=ctk.CTkFont(size=11), text_color=self.c_text_sub)
        desc_perm.pack(anchor="w", padx=12, pady=(0, 6))

        ip_row = ctk.CTkFrame(perm_frame, fg_color="transparent")
        ip_row.pack(anchor="w", padx=12, pady=(0, 10))

        lbl_remote_ip = ctk.CTkLabel(ip_row, text="IP Fija Permitida (Opcional):", font=ctk.CTkFont(size=11, weight="bold"), text_color=self.c_text_title)
        lbl_remote_ip.pack(side="left", padx=(0, 8))

        self.entry_ftp_remote_ip = ctk.CTkEntry(ip_row, width=180, placeholder_text="ej: 192.168.1.50")
        self.entry_ftp_remote_ip.insert(0, self.config_mgr.get('ftp_ip', ''))
        self.entry_ftp_remote_ip.pack(side="left", padx=(0, 12))

        btn_open_perm = ctk.CTkButton(ip_row, text="🔓 Abrir FTP Permanente", fg_color="#0284C7", hover_color="#0369A1", command=self.start_ftp_perm)
        btn_open_perm.pack(side="left")

        self.lbl_timer_status = ctk.CTkLabel(self.tab_ftp, text="Estado: Puerto 21 cerrado.", font=ctk.CTkFont(size=12, weight="bold"), text_color=self.c_text_sub)
        self.lbl_timer_status.pack(anchor="w", padx=16, pady=8)

        self.progress_ftp = ctk.CTkProgressBar(self.tab_ftp, height=10)
        self.progress_ftp.set(0)
        self.progress_ftp.pack(fill="x", padx=16, pady=4)

    def _build_vpn_tab(self):
        lbl = ctk.CTkLabel(self.tab_vpn, text="Conexión Segura mediante Red Privada (Cloudflare / Tailscale)", font=ctk.CTkFont(size=14, weight="bold"), text_color=self.c_text_title)
        lbl.pack(anchor="w", padx=16, pady=(16, 6))

        desc = ctk.CTkLabel(self.tab_vpn, text="Para máxima seguridad, conecta tu servidor sin exponer puertos públicos en tu router.", text_color=self.c_text_sub)
        desc.pack(anchor="w", padx=16, pady=(0, 16))

        card_cf = ctk.CTkFrame(self.tab_vpn, fg_color=self.c_bg_box, corner_radius=10)
        card_cf.pack(fill="x", padx=16, pady=8)

        lbl_cf = ctk.CTkLabel(card_cf, text="☁️ Cloudflare Tunnel (Zero-Trust)", font=ctk.CTkFont(size=13, weight="bold"), text_color="#0284C7")
        lbl_cf.pack(anchor="w", padx=12, pady=(10, 2))

        desc_cf = ctk.CTkLabel(card_cf, text="Crea un túnel seguro con certificado SSL sin requerir apertura de puertos en el router.", font=ctk.CTkFont(size=11), text_color=self.c_text_sub)
        desc_cf.pack(anchor="w", padx=12, pady=(0, 8))

        btn_dl_cf = ctk.CTkButton(card_cf, text="📥 Descargar Cloudflare Tunnel (cloudflared)", fg_color="#0284C7", hover_color="#0369A1", command=lambda: webbrowser.open("https://github.com/cloudflare/cloudflared/releases/latest"))
        btn_dl_cf.pack(anchor="w", padx=12, pady=(0, 10))

        card_ts = ctk.CTkFrame(self.tab_vpn, fg_color=self.c_bg_box, corner_radius=10)
        card_ts.pack(fill="x", padx=16, pady=8)

        lbl_ts = ctk.CTkLabel(card_ts, text="🔒 Tailscale Mesh VPN", font=ctk.CTkFont(size=13, weight="bold"), text_color="#10B981")
        lbl_ts.pack(anchor="w", padx=12, pady=(10, 2))

        desc_ts = ctk.CTkLabel(card_ts, text="Asigna una IP privada 100.x.y.z cifrada punto a punto con WireGuard (Gratis hasta 100 dispositivos).", font=ctk.CTkFont(size=11), text_color=self.c_text_sub)
        desc_ts.pack(anchor="w", padx=12, pady=(0, 8))

        btn_dl_ts = ctk.CTkButton(card_ts, text="📥 Descargar Tailscale VPN", fg_color="#059669", hover_color="#047857", command=lambda: webbrowser.open("https://tailscale.com/download"))
        btn_dl_ts.pack(anchor="w", padx=12, pady=(0, 10))

    def _build_config_tab(self):
        lbl = ctk.CTkLabel(self.tab_config, text="Configuración General del Sistema, Ciberseguridad y Temas", font=ctk.CTkFont(size=14, weight="bold"), text_color=self.c_text_title)
        lbl.pack(anchor="w", padx=16, pady=(16, 6))

        sec_box = ctk.CTkFrame(self.tab_config, fg_color=self.c_bg_box, corner_radius=10)
        sec_box.pack(fill="x", padx=16, pady=12)

        lbl_sec_t = ctk.CTkLabel(sec_box, text="🛡️ Escudo de Ciberseguridad & Anti-Intrusión", font=ctk.CTkFont(size=13, weight="bold"), text_color="#10B981")
        lbl_sec_t.pack(anchor="w", padx=12, pady=(10, 2))

        desc_sec = ctk.CTkLabel(sec_box, text="Monitorea activamente puertos de red (22, 21, 5432) en busca de conexiones no autorizadas o exploits de fuerza bruta.", font=ctk.CTkFont(size=11), text_color=self.c_text_sub)
        desc_sec.pack(anchor="w", padx=12, pady=(0, 8))

        self.switch_shield = ctk.CTkSwitch(sec_box, text="Activar Escudo de Ciberseguridad en Tiempo Real", font=ctk.CTkFont(size=12, weight="bold"), text_color=self.c_text_title, command=self.toggle_security_shield)
        self.switch_shield.select()
        self.switch_shield.pack(anchor="w", padx=12, pady=(0, 12))

        theme_frame = ctk.CTkFrame(self.tab_config, fg_color=self.c_bg_box, corner_radius=10)
        theme_frame.pack(fill="x", padx=16, pady=12)

        lbl_th_t = ctk.CTkLabel(theme_frame, text="🎨 Tema Visual de la Aplicación", font=ctk.CTkFont(size=12, weight="bold"), text_color="#0284C7")
        lbl_th_t.pack(anchor="w", padx=12, pady=(10, 4))

        theme_btn_row = ctk.CTkFrame(theme_frame, fg_color="transparent")
        theme_btn_row.pack(anchor="w", padx=12, pady=(0, 10))

        btn_th_dark = ctk.CTkButton(theme_btn_row, text="🌙 Modo Oscuro (Dark)", fg_color="#1E293B", hover_color="#334155", command=lambda: self.change_theme("Dark"))
        btn_th_dark.pack(side="left", padx=(0, 8))

        btn_th_light = ctk.CTkButton(theme_btn_row, text="☀️ Modo Claro (Light)", fg_color="#E2E8F0", text_color="#0F172A", hover_color="#CBD5E1", command=lambda: self.change_theme("Light"))
        btn_th_light.pack(side="left", padx=(0, 8))

        btn_th_sys = ctk.CTkButton(theme_btn_row, text="💻 Según el Sistema (System)", fg_color="#475569", hover_color="#334155", command=lambda: self.change_theme("System"))
        btn_th_sys.pack(side="left")

        self.switch_autostart = ctk.CTkSwitch(self.tab_config, text="Iniciar automáticamente con Windows", font=ctk.CTkFont(size=12, weight="bold"), text_color=self.c_text_title, command=self.toggle_autostart)
        if self.config_mgr.get('autostart', True):
            self.switch_autostart.select()
        self.switch_autostart.pack(anchor="w", padx=16, pady=16)

        btn_save_all = ctk.CTkButton(self.tab_config, text="💾 Guardar Toda la Configuración (1-Clic)", fg_color="#10B981", hover_color="#059669", font=ctk.CTkFont(size=13, weight="bold"), height=38, command=self.save_settings)
        btn_save_all.pack(anchor="w", padx=16, pady=8)

    # ─── ACCIONES DE UI Y EVENTOS ──────────────────────────────────────────

    def show_ftp_vpn_connection_error_modal(self, custom_msg=None):
        """Muestra un modal con banner amarillo brillante (#FEF08A / #FACC15), borde rojo y triángulo rojo 🔺"""
        modal = ctk.CTkToplevel(self)
        modal.title("⚠️ Alerta de Conexión FTP / VPN")
        modal.geometry("540x290")
        modal.resizable(False, False)
        modal.transient(self)
        modal.grab_set()

        try:
            x = self.winfo_x() + (self.winfo_width() // 2) - 270
            y = self.winfo_y() + (self.winfo_height() // 2) - 145
            modal.geometry(f"540x290+{max(0, x)}+{max(0, y)}")
        except Exception: pass

        banner_frame = ctk.CTkFrame(modal, fg_color="#FEF08A", border_color="#DC2626", border_width=3, corner_radius=12)
        banner_frame.pack(expand=True, fill="both", padx=16, pady=16)

        header_row = ctk.CTkFrame(banner_frame, fg_color="transparent")
        header_row.pack(anchor="w", padx=16, pady=(16, 8))

        lbl_triang = ctk.CTkLabel(header_row, text="🔺", font=ctk.CTkFont(size=28))
        lbl_triang.pack(side="left", padx=(0, 10))

        lbl_modal_title = ctk.CTkLabel(
            header_row,
            text="Fallo de Conexión FTP / VPN",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color="#991B1B"
        )
        lbl_modal_title.pack(side="left")

        msg_text = custom_msg or "No se logró conectar a la carpeta FTP o VPN. Pruebe nuevamente a activar y reintente."
        lbl_body = ctk.CTkLabel(
            banner_frame,
            text=msg_text,
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#854D0E",
            wraplength=460,
            justify="left"
        )
        lbl_body.pack(anchor="w", padx=16, pady=(0, 16))

        btn_row = ctk.CTkFrame(banner_frame, fg_color="transparent")
        btn_row.pack(fill="x", padx=16, pady=(0, 12))

        btn_retry = ctk.CTkButton(
            btn_row,
            text="🔁 Reintentar Conexión",
            fg_color="#D97706",
            hover_color="#B45309",
            text_color="#FFFFFF",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=lambda: (modal.destroy(), self.test_remote_sftp())
        )
        btn_retry.pack(side="left", padx=(0, 10))

        btn_close = ctk.CTkButton(
            btn_row,
            text="❌ Cerrar",
            fg_color="#475569",
            hover_color="#334155",
            text_color="#FFFFFF",
            command=modal.destroy
        )
        btn_close.pack(side="left")

    def open_sftp_port_firewall(self):
        ok, msg = self.runner.open_sftp_port_firewall()
        if ok:
            messagebox.showinfo("Firewall SFTP", msg)
        else:
            messagebox.showwarning("Firewall SFTP", msg)
        self.set_status(msg)
        self.refresh_stats()

    def open_pg_port_firewall(self):
        ok, msg = self.runner.open_pg_port_firewall()
        if ok:
            messagebox.showinfo("Firewall PostgreSQL", msg)
        else:
            messagebox.showwarning("Firewall PostgreSQL", msg)
        self.set_status(msg)
        self.refresh_stats()

    def trigger_emergency_lockdown(self):
        if messagebox.askyesno("🔒 Cerrojo de Emergencia", "¿Deseas cerrar inmediatamente todos los puertos de red (22, 21, 5432) y reglas de firewall por seguridad?"):
            ok, msg = self.runner.emergency_lockdown()
            messagebox.showwarning("Cerrojo Activado", msg)
            self.set_status("Cerrojo de emergencia activado.")
            self.refresh_stats()

    def copy_ip(self):
        self.clipboard_clear()
        self.clipboard_append(self.current_ip)
        self.set_status("IP copiada al portapapeles.")

    def change_theme(self, new_theme):
        ctk.set_appearance_mode(new_theme)
        self.config_mgr.set('theme', new_theme)
        self.set_status(f"Tema cambiado a: {new_theme}")

    def toggle_security_shield(self):
        self.security_shield_active = self.switch_shield.get() == 1
        st = "activado" if self.security_shield_active else "desactivado"
        self.set_status(f"Escudo de Ciberseguridad {st}.")

    def on_closing(self):
        """Guarda estado de la app y limpia recursos antes de salir."""
        try:
            self.config_mgr.set('window_geometry', self.geometry())
            self.save_settings_quiet()
        except Exception: pass
        self.destroy()

    def on_pass_change_sftp(self, event=None):
        pwd = self.entry_sftp_pass.get()
        txt, col = evaluate_password_strength(pwd)
        self.lbl_strength_sftp.configure(text=txt, text_color=col)

    def on_pass_change_remote(self, event=None):
        pwd = self.entry_remote_pass.get()
        txt, col = evaluate_password_strength(pwd)
        self.lbl_strength_remote.configure(text=txt, text_color=col)

    def on_pass_change_db(self, event=None):
        pwd = self.entry_db_pass.get()
        txt, col = evaluate_password_strength(pwd)
        self.lbl_strength_db.configure(text=txt, text_color=col)
        self.update_conn_str()

    def on_slider_change(self, value):
        mins = int(value)
        self.lbl_min_val.configure(text=f"{mins} minutos")

    def browse_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.entry_path.delete(0, tk.END)
            self.entry_path.insert(0, folder)
            self.save_settings_quiet()

    def setup_storage(self):
        path = self.entry_path.get().strip()
        ok, msg = self.runner.ensure_storage_folder(path)
        if ok:
            messagebox.showinfo("Éxito", msg)
            self.lbl_storage_path.configure(text=path)
            self.set_status(msg)
        else:
            messagebox.showerror("Error", msg)

    def test_local_storage(self):
        path = self.entry_path.get().strip()
        test_file = os.path.join(path, "_test_write.tmp")
        try:
            os.makedirs(path, exist_ok=True)
            with open(test_file, "w") as f:
                f.write("OK")
            if os.path.exists(test_file):
                os.remove(test_file)
                messagebox.showinfo("Prueba Local", f"✅ Permisos de Lectura/Escritura verificados correctamente en:\n{path}")
                self.set_status("Prueba local exitosa.")
        except Exception as e:
            messagebox.showerror("Error Local", f"❌ Fallo al escribir en la carpeta:\n{str(e)}")

    def create_sftp_user(self):
        self.save_settings_quiet()
        user = self.entry_sftp_user.get().strip()
        pwd = self.entry_sftp_pass.get().strip()
        path = self.entry_path.get().strip()

        ok, msg = self.runner.create_restricted_sftp_user(user, pwd, path)
        if ok:
            messagebox.showinfo("Servidor SFTP", msg)
        else:
            messagebox.showwarning("Alerta SFTP", msg)
        self.set_status(msg)
        self.refresh_stats()

    def copy_sftp_credentials(self):
        user = self.entry_sftp_user.get().strip() or "factura_sftp"
        pwd = self.entry_sftp_pass.get().strip() or "ClaveSFTP123!"
        ip = self.current_ip
        folder = self.entry_path.get().strip() or r"C:\factura_uploads"
        text = f"Host/IP: {ip}\nPuerto: 22\nUsuario SSH: {user}\nContraseña SSH: {pwd}\nRuta: {folder}"
        self.clipboard_clear()
        self.clipboard_append(text)
        messagebox.showinfo("Credenciales Copiadas", f"Credenciales SFTP copiadas al portapapeles:\n\n{text}")
        self.set_status("Credenciales SFTP copiadas al portapapeles.")

    def test_remote_sftp(self):
        self.save_settings_quiet()
        host = self.entry_remote_host.get().strip() or "127.0.0.1"
        port = self.entry_remote_port.get().strip() or "22"
        user = self.entry_remote_user.get().strip() or "factura_sftp"
        pwd = self.entry_remote_pass.get().strip() or "ClaveSFTP123!"
        folder = self.entry_remote_path.get().strip() or r"C:\factura_uploads"

        ok, msg = test_sftp_full_connection(host, port, user, pwd, folder)
        if ok:
            messagebox.showinfo("Prueba SFTP Exitosa", msg)
        else:
            self.show_ftp_vpn_connection_error_modal(f"No se logró conectar a la carpeta FTP o VPN ({host}:{port}).\n\nDetalle: {msg}")
        self.set_status(msg)

    def copy_tested_credentials(self):
        host = self.entry_remote_host.get().strip() or "127.0.0.1"
        port = self.entry_remote_port.get().strip() or "22"
        user = self.entry_remote_user.get().strip() or "factura_sftp"
        pwd = self.entry_remote_pass.get().strip() or "ClaveSFTP123!"
        folder = self.entry_remote_path.get().strip() or r"C:\factura_uploads"
        text = f"Host/IP: {host}\nPuerto: {port}\nUsuario SSH: {user}\nContraseña SSH: {pwd}\nRuta: {folder}"
        self.clipboard_clear()
        self.clipboard_append(text)
        messagebox.showinfo("Credenciales Copiadas", f"Credenciales SFTP para la Web copiadas:\n\n{text}")
        self.set_status("Credenciales remotas copiadas al portapapeles.")

    def run_docker_stack(self):
        ok, msg = self.runner.launch_docker_stack()
        if ok:
            messagebox.showinfo("Docker Compose", msg)
            self.set_status("Contenedores Docker creados e iniciados.")
            self.refresh_stats()
        else:
            messagebox.showerror("Error Docker", msg)

    def test_pg_conn(self):
        self.save_settings_quiet()
        host = self.entry_db_host.get().strip() or self.current_ip
        port = self.entry_db_port.get().strip() or "5432"
        ok, msg = self.runner.test_db_connection(host, int(port))
        if ok:
            messagebox.showinfo("Prueba PG Exitosa", msg)
        else:
            self.show_ftp_vpn_connection_error_modal(f"No se logró conectar a la Base de Datos o VPN ({host}:{port}).\n\nDetalle: {msg}")
        self.set_status(msg)

    def update_conn_str(self, event=None):
        ip = self.entry_db_host.get() or self.current_ip
        port = self.entry_db_port.get() or "5432"
        db = self.entry_db_name.get() or "facturapro_db"
        user = self.entry_db_user.get() or "postgres_user"
        pwd = self.entry_db_pass.get() or "ClaveSegura123!"
        conn = f"postgresql+asyncpg://{user}:{pwd}@{ip}:{port}/{db}"
        self.conn_str_box.delete(0, tk.END)
        self.conn_str_box.insert(0, conn)

    def copy_conn_str(self):
        self.update_conn_str()
        conn = self.conn_str_box.get()
        self.clipboard_clear()
        self.clipboard_append(conn)
        self.set_status("String de conexión copiado al portapapeles.")

    def start_ftp_temp(self):
        self.save_settings_quiet()
        mins = int(self.slider_min.get())
        ip = self.entry_ftp_temp_ip.get().strip()
        ok, msg = self.runner.open_temporary_ftp(mins, ip, self._ftp_tick, self._ftp_finish)
        if ok:
            messagebox.showinfo("FTP Temporal", msg)
        else:
            self.show_ftp_vpn_connection_error_modal(msg)
        self.set_status(msg)

    def stop_ftp_temp(self):
        ok, msg = self.runner.cancel_temporary_ftp()
        self._ftp_finish()
        messagebox.showinfo("FTP Temporal", msg)
        self.set_status(msg)

    def start_ftp_perm(self):
        self.save_settings_quiet()
        ip = self.entry_ftp_remote_ip.get().strip()
        ok, msg = self.runner.open_permanent_ftp(ip)
        if ok:
            messagebox.showinfo("FTP Permanente", msg)
        else:
            self.show_ftp_vpn_connection_error_modal(msg)
        self.set_status(msg)

    def _ftp_tick(self, rem_sec):
        mins = rem_sec // 60
        secs = rem_sec % 60
        total_sec = int(self.slider_min.get()) * 60
        pct = (total_sec - rem_sec) / total_sec if total_sec > 0 else 0
        self.progress_ftp.set(pct)
        self.lbl_timer_status.configure(text=f"🟢 Puerto 21 ABIERTO - Tiempo restante: {mins:02d}:{secs:02d}", text_color="#F59E0B")

    def _ftp_finish(self):
        self.progress_ftp.set(0)
        self.lbl_timer_status.configure(text="🔒 Puerto 21 cerrado.", text_color=self.c_text_sub)

    def toggle_autostart(self):
        enable = self.switch_autostart.get() == 1
        ok, msg = self.runner.set_autostart(enable)
        self.set_status(msg)

    def save_settings_quiet(self):
        data = {
            'storage_path': self.entry_path.get().strip(),
            'remote_host': self.entry_remote_host.get().strip(),
            'remote_port': int(self.entry_remote_port.get().strip() or 22),
            'remote_user': self.entry_remote_user.get().strip(),
            'remote_pass': self.entry_remote_pass.get().strip(),
            'remote_path': self.entry_remote_path.get().strip(),
            'pg_host': self.entry_db_host.get().strip(),
            'pg_port': int(self.entry_db_port.get().strip() or 5432),
            'pg_db': self.entry_db_name.get().strip(),
            'pg_user': self.entry_db_user.get().strip(),
            'pg_pass': self.entry_db_pass.get().strip(),
            'ftp_ip': self.entry_ftp_remote_ip.get().strip(),
            'window_geometry': self.geometry()
        }
        self.config_mgr.save_config(data)

    def save_settings(self):
        self.save_settings_quiet()
        messagebox.showinfo("Configuración", "✅ Toda la configuración fue guardada de forma permanente en disco.")
        self.set_status("Configuración guardada en config.json.")

    def set_status(self, msg):
        self.lbl_status_bar.configure(text=msg)

    def refresh_stats(self):
        path = self.config_mgr.get('storage_path', r'C:\factura_uploads')
        disk = get_disk_info(path)
        n_files = count_local_files(path)

        pct = disk['used_pct'] / 100.0
        self.progress_disk.set(pct)
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
            self.ssh_warning_banner.pack(fill="x", padx=16, pady=(0, 8), before=self.tabview)
        else:
            self.ssh_warning_banner.pack_forget()

    def _security_guardian_loop(self):
        if self.security_shield_active:
            try:
                remote_conn = self.config_mgr.get('remote_host', '')
                allowed = set(self.known_safe_ips)
                if remote_conn:
                    allowed.add(remote_conn)

                suspicious = check_active_net_connections([21, 22, 2022, 5432])
                for s in suspicious:
                    ip = s['remote_ip']
                    port = s['port']
                    if ip not in allowed:
                        self.status_security.configure(
                            text=f"🚨 ALERTA: Conexión no autorizada detectada desde IP {ip} (Puerto {port})",
                            text_color="#EF4444"
                        )
                        self.runner.emergency_lockdown()
                        
                        messagebox.showerror(
                            "🚨 ALERTA DE CIBERSEGURIDAD Y ANTI-INTRUSIÓN",
                            f"Se detectó una conexión no autorizada desde la IP externa: {ip} al puerto {port}.\n\n"
                            "Por seguridad, el Escudo de Ciberseguridad activó el CERROJO DE EMERGENCIA automáticamente y cerró todos los puertos."
                        )
                        break
            except Exception:
                pass
        self.after(5000, self._security_guardian_loop)

    def _auto_refresh_loop(self):
        try:
            self.refresh_stats()
        except Exception:
            pass
        self.after(4000, self._auto_refresh_loop)

if __name__ == "__main__":
    app = AppGUI()
    app.mainloop()
