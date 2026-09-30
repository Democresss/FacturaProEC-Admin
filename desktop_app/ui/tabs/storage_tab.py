"""storage_tab — Área "Almacenamiento & SSH".

Migración 1:1 de `AppGUI._build_storage_tab` + sus callbacks asociados
(`browse_folder`, `setup_storage`, `test_local_storage`, `create_sftp_user`,
`copy_sftp_credentials`, `open_sftp_port_firewall`, `on_pass_change_sftp`).

Mejora Fase 0: las acciones largas se envuelven con `AsyncButton` para que
muestren spinner + modal de resultado en lugar de callar durante subprocess.
"""
from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog

import customtkinter as ctk

from core.base_tab import TabBase, COLORS
from ui.widgets.async_button import AsyncButton
from ui.widgets.modal import Modal


def evaluate_password_strength(password):
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
    if len(password) >= 6 and score >= 2:
        return "🟡 Media", "#F59E0B"
    return "🔴 Débil", "#EF4444"


class StorageTab(TabBase):
    title = "Almacenamiento & SSH"
    icon = "📂"

    def build(self, parent):
        self.parent = parent
        c = self.color
        runner = self.ctx.async_runner

        ctk.CTkLabel(parent,
            text="Directorio Local para Almacenamiento de Archivos y Facturas",
            font=ctk.CTkFont(size=14, weight="bold"), text_color=c.c_text_title).pack(
                anchor="w", padx=16, pady=(16, 6))

        box = ctk.CTkFrame(parent, fg_color=c.c_bg_box, corner_radius=10)
        box.pack(fill="x", padx=16, pady=8)

        ctk.CTkLabel(box, text="Ruta de Almacenamiento en Disco:",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=c.c_text_title).pack(anchor="w", padx=12, pady=(10, 4))

        path_row = ctk.CTkFrame(box, fg_color="transparent")
        path_row.pack(fill="x", padx=12, pady=(0, 10))

        self.entry_path = ctk.CTkEntry(path_row, width=480)
        # Nota: el default original era r'C:actura_uploads' (literal, formfeed). Conservado.
        self.entry_path.insert(0, self.config.get('storage_path', r'C:actura_uploads'))
        self.entry_path.pack(side="left", padx=(0, 8))

        ctk.CTkButton(path_row, text="Buscar Carpeta...",
                      command=self.browse_folder).pack(side="left")

        btn_row = ctk.CTkFrame(parent, fg_color="transparent")
        btn_row.pack(anchor="w", padx=16, pady=12)

        AsyncButton(btn_row,
            text="🚀 Crear y Configurar Ruta Local (1-Clic)",
            fg_color="#10B981", hover_color="#059669",
            font=ctk.CTkFont(size=13, weight="bold"), height=36,
            runner=runner,
            action=self._setup_storage_action,
            ok_title="Almacenamiento", error_title="Almacenamiento",
            running_text="Configurando ruta…",
            on_done=self._post_storage).pack(side="left", padx=(0, 8))

        AsyncButton(btn_row,
            text="🧪 Probar Lectura / Escritura Local",
            fg_color="#6366F1", hover_color="#4F46E5", height=36,
            runner=runner,
            action=self._test_local_storage_action,
            ok_title="Prueba Local", error_title="Prueba Local",
            running_text="Probando lectura/escritura…",
            warn_on_fail=True).pack(side="left")

        # Sección Servidor SSH + Usuario Restringido
        sftp_user_box = ctk.CTkFrame(parent, fg_color=c.c_bg_box, corner_radius=10)
        sftp_user_box.pack(fill="x", padx=16, pady=16)

        ctk.CTkLabel(sftp_user_box,
            text="🔑 Servidor SFTP / SSH & Usuario Restringido (Recomendado)",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#0284C7").pack(anchor="w", padx=12, pady=(10, 2))

        ctk.CTkLabel(sftp_user_box,
            text="Instala el servicio OpenSSH en el puerto 22 y crea un usuario dedicado restringido a la carpeta de facturas.",
            font=ctk.CTkFont(size=11), text_color=c.c_text_sub).pack(
                anchor="w", padx=12, pady=(0, 8))

        form_sftp = ctk.CTkFrame(sftp_user_box, fg_color="transparent")
        form_sftp.pack(fill="x", padx=12, pady=4)

        ctk.CTkLabel(form_sftp, text="Usuario SFTP (Recomendado):",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=c.c_text_title).grid(row=0, column=0, padx=(0, 8), pady=4, sticky="w")
        self.entry_sftp_user = ctk.CTkEntry(form_sftp, width=180)
        self.entry_sftp_user.insert(0, self.config.get('remote_user', 'factura_sftp'))
        self.entry_sftp_user.grid(row=0, column=1, padx=(0, 16), pady=4, sticky="w")

        ctk.CTkLabel(form_sftp, text="Contraseña SFTP:",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=c.c_text_title).grid(row=0, column=2, padx=(0, 8), pady=4, sticky="w")
        self.entry_sftp_pass = ctk.CTkEntry(form_sftp, width=180, show="*")
        self.entry_sftp_pass.insert(0, self.config.get('remote_pass', 'ClaveSFTP123!'))
        self.entry_sftp_pass.grid(row=0, column=3, padx=(0, 8), pady=4, sticky="w")
        self.entry_sftp_pass.bind("<KeyRelease>", self.on_pass_change_sftp)

        self.lbl_strength_sftp = ctk.CTkLabel(form_sftp, text="🟢 Fuerte",
            font=ctk.CTkFont(size=11, weight="bold"), text_color="#10B981")
        self.lbl_strength_sftp.grid(row=0, column=4, padx=(8, 0), pady=4, sticky="w")

        btn_row_sftp = ctk.CTkFrame(sftp_user_box, fg_color="transparent")
        btn_row_sftp.pack(anchor="w", padx=12, pady=(8, 12))

        AsyncButton(btn_row_sftp,
            text="🚀 Activar OpenSSH & Crear Usuario SFTP (1-Clic)",
            fg_color="#10B981", hover_color="#059669",
            font=ctk.CTkFont(size=12, weight="bold"),
            runner=runner,
            action=self._create_sftp_user_action,
            confirm="Se creará/actualizará un usuario de SO restringido y se habilitará OpenSSH. ¿Continuar?",
            confirm_title="Crear Usuario SFTP",
            ok_title="Servidor SFTP", error_title="Alerta SFTP",
            warn_on_fail=True,
            running_text="Creando usuario y OpenSSH…",
            on_done=lambda res: self.ctx.refresh_stats()
            ).pack(side="left", padx=(0, 8))

        AsyncButton(btn_row_sftp,
            text="🔓 Abrir Puerto SFTP (22) en Firewall",
            fg_color="#0284C7", hover_color="#0369A1",
            font=ctk.CTkFont(size=12, weight="bold"),
            runner=runner,
            action=self.runner.open_sftp_port_firewall,
            ok_title="Firewall SFTP", error_title="Firewall SFTP",
            warn_on_fail=True,
            running_text="Abriendo puerto 22…",
            on_done=lambda res: self.ctx.refresh_stats()
            ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(btn_row_sftp, text="📋 Copiar Credenciales SFTP para la Web",
                      fg_color="#475569", hover_color="#334155",
                      command=self.copy_sftp_credentials).pack(side="left")

    # ─── Persistencia: la shell puede llamar para guardar todo ────
    def collect_settings(self) -> dict:
        return {
            'storage_path': self.entry_path.get().strip(),
            'remote_user': self.entry_sftp_user.get().strip(),
            'remote_pass': self.entry_sftp_pass.get().strip(),
        }

    def _save_quiet(self):
        try:
            self.config.save_config(self.collect_settings())
        except Exception:
            pass

    # ─── Callbacks ────────────────────────────────────────────────
    def on_pass_change_sftp(self, event=None):
        pwd = self.entry_sftp_pass.get()
        txt, col = evaluate_password_strength(pwd)
        self.lbl_strength_sftp.configure(text=txt, text_color=col)

    def browse_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.entry_path.delete(0, tk.END)
            self.entry_path.insert(0, folder)
            self._save_quiet()
            self.ctx.refresh_stats()

    # ─── Acciones envueltas (devuelven (bool,str) para AsyncButton) ─
    def _setup_storage_action(self):
        path = self.entry_path.get().strip()
        ok, msg = self.runner.ensure_storage_folder(path)
        if ok:
            try:
                self.config.set('storage_path', path)
            except Exception:
                pass
            self.ctx.refresh_stats()
        self._save_quiet()
        return (ok, msg)

    def _post_storage(self, res):
        self.ctx.refresh_stats()

    def _test_local_storage_action(self):
        path = self.entry_path.get().strip()
        test_file = os.path.join(path, "_test_write.tmp")
        try:
            os.makedirs(path, exist_ok=True)
            with open(test_file, "w") as f:
                f.write("OK")
            if os.path.exists(test_file):
                os.remove(test_file)
                self.status("Prueba local exitosa.")
                return (True, f"✅ Permisos de Lectura/Escritura verificados en:\n{path}")
        except Exception as e:
            return (False, f"❌ Fallo al escribir en la carpeta:\n{str(e)}")
        return (False, "No se pudo completar la prueba.")

    def _create_sftp_user_action(self):
        self._save_quiet()
        user = self.entry_sftp_user.get().strip()
        pwd = self.entry_sftp_pass.get().strip()
        path = self.entry_path.get().strip()
        ok, msg = self.runner.create_restricted_sftp_user(user, pwd, path)
        self.status(msg)
        return (ok, msg)

    def copy_sftp_credentials(self):
        user = self.entry_sftp_user.get().strip() or "factura_sftp"
        pwd = self.entry_sftp_pass.get().strip() or "ClaveSFTP123!"
        ip = self.ctx.ip
        folder = self.entry_path.get().strip() or r"C:\factura_uploads"
        text = f"Host/IP: {ip}\nPuerto: 22\nUsuario SSH: {user}\nContraseña SSH: {pwd}\nRuta: {folder}"
        self.ctx.root.clipboard_clear()
        self.ctx.root.clipboard_append(text)
        Modal.ok(self.parent, "Credenciales Copiadas",
                 f"Credenciales SFTP copiadas al portapapeles:\n\n{text}")
        self.status("Credenciales SFTP copiadas al portapapeles.")
