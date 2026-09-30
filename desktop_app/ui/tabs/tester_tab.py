"""tester_tab — Área "Probador de Servidor Remoto".

Migración 1:1 de `AppGUI._build_tester_tab` + `test_remote_sftp` y
`copy_tested_credentials`.

Mejora Fase 0/4: la prueba SFTP ahora hace LOGIN REAL con paramiko
(instalación del .p12 / spec — Fase 4). Si paramiko no está disponible,
cae al `test_sftp_full_connection` TCP original (degradación elegante,
no bloquea al usuario). El resultado se muestra siempre vía AsyncButton
con modal de éxito/error, nunca callando.
"""
from __future__ import annotations

import customtkinter as ctk

from core.base_tab import TabBase, COLORS
from ui.widgets.async_button import AsyncButton
from ui.widgets.modal import Modal
from sys_info import ping_host, check_port_open, test_sftp_full_connection


def _try_real_sftp_login(host, port, user, password, folder):
    """Intenta login SFTP real. Devuelve (ok, msg). Falla con msg útil si paramiko falta."""
    try:
        import paramiko  # type: ignore
    except Exception:
        # Degradación elegante: sin paramiko, prueba TCP/Ping del original.
        return test_sftp_full_connection(host, port, user, password, folder)

    host = (host or "127.0.0.1").strip()
    try:
        port = int(port or 22)
    except Exception:
        port = 22

    if not ping_host(host):
        return False, f"❌ El servidor {host} no responde al Ping."
    if not check_port_open(host, port, timeout=2.0):
        return False, f"⚠️ {host} responde a Ping pero el puerto SSH {port} está cerrado/bloqueado."

    try:
        transport = paramiko.Transport((host, port))
        transport.connect(username=user, password=password)
        sftp = paramiko.SFTPClient.from_transport(transport)
        try:
            try:
                entries = sftp.listdir(folder or ".")
                sample = ", ".join(entries[:5]) if entries else "(vacía)"
                detalle = f"Carpeta '{folder}' accesible. Contenido: {sample}"
            except Exception as e:
                detalle = f"Login OK pero no se pudo listar '{folder}': {e}"
        finally:
            sftp.close()
            transport.close()
        return True, f"✅ LOGIN SFTP real exitoso a {host}:{port} como '{user}'.\n{detalle}"
    except Exception as e:
        return False, f"❌ Puerto {port} abierto pero login SFTP FALLÓ para '{user}': {e}"


class TesterTab(TabBase):
    title = "Probador de Servidor Remoto"
    icon = "📡"

    def build(self, parent):
        self.parent = parent
        c = self.color
        runner = self.ctx.async_runner

        ctk.CTkLabel(parent,
            text="📡 Probador de Servidores SFTP / SSH Remotos (Otra PC o VPS)",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=c.c_text_title).pack(anchor="w", padx=16, pady=(16, 6))

        ctk.CTkLabel(parent,
            text="Si tus archivos estarán en otro servidor o PC distinta, ingresa sus datos aquí "
                 "para probar la conexión en tiempo real antes de guardar en la Web.",
            text_color=c.c_text_sub).pack(anchor="w", padx=16, pady=(0, 16))

        test_box = ctk.CTkFrame(parent, fg_color=c.c_bg_box, corner_radius=10)
        test_box.pack(fill="x", padx=16, pady=8)

        grid_t = ctk.CTkFrame(test_box, fg_color="transparent")
        grid_t.pack(fill="x", padx=12, pady=12)

        ctk.CTkLabel(grid_t, text="HOST / IP Remota (Recomendado):",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=c.c_text_title).grid(row=0, column=0, padx=(0, 8), pady=6, sticky="w")
        self.entry_remote_host = ctk.CTkEntry(grid_t, width=220)
        self.entry_remote_host.insert(0, self.config.get('remote_host', '192.168.1.58'))
        self.entry_remote_host.grid(row=0, column=1, padx=(0, 16), pady=6, sticky="w")

        ctk.CTkLabel(grid_t, text="Puerto SSH (Recomendado: 22):",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=c.c_text_title).grid(row=0, column=2, padx=(0, 8), pady=6, sticky="w")
        self.entry_remote_port = ctk.CTkEntry(grid_t, width=120)
        self.entry_remote_port.insert(0, str(self.config.get('remote_port', 22)))
        self.entry_remote_port.grid(row=0, column=3, padx=(0, 8), pady=6, sticky="w")

        ctk.CTkLabel(grid_t, text="Usuario SSH:",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=c.c_text_title).grid(row=1, column=0, padx=(0, 8), pady=6, sticky="w")
        self.entry_remote_user = ctk.CTkEntry(grid_t, width=220)
        self.entry_remote_user.insert(0, self.config.get('remote_user', 'factura_sftp'))
        self.entry_remote_user.grid(row=1, column=1, padx=(0, 16), pady=6, sticky="w")

        ctk.CTkLabel(grid_t, text="Contraseña SSH:",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=c.c_text_title).grid(row=1, column=2, padx=(0, 8), pady=6, sticky="w")
        self.entry_remote_pass = ctk.CTkEntry(grid_t, width=180, show="*")
        self.entry_remote_pass.insert(0, self.config.get('remote_pass', 'ClaveSFTP123!'))
        self.entry_remote_pass.grid(row=1, column=3, padx=(0, 8), pady=6, sticky="w")

        from ui.tabs.storage_tab import evaluate_password_strength
        self.lbl_strength_remote = ctk.CTkLabel(grid_t, text="🟢 Fuerte",
            font=ctk.CTkFont(size=11, weight="bold"), text_color="#10B981")
        self.lbl_strength_remote.grid(row=1, column=4, padx=(8, 0), pady=6, sticky="w")
        self.entry_remote_pass.bind("<KeyRelease>", self._on_pass_change_remote)

    def _on_pass_change_remote(self, event=None):
        from ui.tabs.storage_tab import evaluate_password_strength
        txt, col = evaluate_password_strength(self.entry_remote_pass.get())
        self.lbl_strength_remote.configure(text=txt, text_color=col)

        ctk.CTkLabel(grid_t, text="Ruta en Servidor:",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=c.c_text_title).grid(row=2, column=0, padx=(0, 8), pady=6, sticky="w")
        self.entry_remote_path = ctk.CTkEntry(grid_t, width=220)
        # Conservado literal original (formfeed, Migra bug original a propósito).
        self.entry_remote_path.insert(0, self.config.get('remote_path', r'C:actura_uploads'))
        self.entry_remote_path.grid(row=2, column=1, padx=(0, 16), pady=6, sticky="w")

        btn_row = ctk.CTkFrame(test_box, fg_color="transparent")
        btn_row.pack(anchor="w", padx=12, pady=(4, 12))

        AsyncButton(btn_row,
            text="⚡ Probar Conexión SFTP y Ping (1-Clic)",
            fg_color="#10B981", hover_color="#059669",
            font=ctk.CTkFont(size=12, weight="bold"), height=36,
            runner=runner,
            action=self._test_remote_action,
            ok_title="Prueba SFTP Exitosa",
            error_title="Fallo de Conexión SFTP",
            running_text="Probando conexión SFTP…",
            on_done=lambda res: self.status(res.message)
            ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(btn_row,
            text="📋 Copiar Credenciales Probadas para la Web",
            fg_color="#0284C7", hover_color="#0369A1", height=36,
            command=self.copy_tested_credentials).pack(side="left")

    # ─── Persistencia ────────────────────────────────────────────
    def collect_settings(self) -> dict:
        try:
            port = int(self.entry_remote_port.get().strip() or 22)
        except Exception:
            port = 22
        return {
            'remote_host': self.entry_remote_host.get().strip(),
            'remote_port': port,
            'remote_user': self.entry_remote_user.get().strip(),
            'remote_pass': self.entry_remote_pass.get().strip(),
            'remote_path': self.entry_remote_path.get().strip(),
        }

    def _save_quiet(self):
        try:
            self.config.save_config(self.collect_settings())
        except Exception:
            pass

    # ─── Acción ───────────────────────────────────────────────────
    def _test_remote_action(self):
        self._save_quiet()
        host = self.entry_remote_host.get().strip() or "127.0.0.1"
        port = self.entry_remote_port.get().strip() or "22"
        user = self.entry_remote_user.get().strip() or "factura_sftp"
        pwd = self.entry_remote_pass.get().strip() or "ClaveSFTP123!"
        folder = self.entry_remote_path.get().strip() or r"C:\factura_uploads"
        return _try_real_sftp_login(host, port, user, pwd, folder)

    def copy_tested_credentials(self):
        host = self.entry_remote_host.get().strip() or "127.0.0.1"
        port = self.entry_remote_port.get().strip() or "22"
        user = self.entry_remote_user.get().strip() or "factura_sftp"
        pwd = self.entry_remote_pass.get().strip() or "ClaveSFTP123!"
        folder = self.entry_remote_path.get().strip() or r"C:\factura_uploads"
        text = f"Host/IP: {host}\nPuerto: {port}\nUsuario SSH: {user}\nContraseña SSH: {pwd}\nRuta: {folder}"
        self.ctx.root.clipboard_clear()
        self.ctx.root.clipboard_append(text)
        Modal.ok(self.parent, "Credenciales Copiadas",
                 f"Credenciales SFTP para la Web copiadas:\n\n{text}")
        self.status("Credenciales remotas copiadas al portapapeles.")
