import os
import sys
import json
import logging

logger = logging.getLogger("config_manager")

class ConfigManager:
    """Manejador de configuración persistente en %APPDATA%/FacturaProEC/config.json o ~/.config/FacturaProEC/config.json"""
    def __init__(self):
        if os.name == 'nt':
            appdata = os.getenv('APPDATA', os.path.expanduser('~'))
            self.config_dir = os.path.join(appdata, 'FacturaProEC')
        else:
            self.config_dir = os.path.expanduser('~/.config/FacturaProEC')

        self.config_file = os.path.join(self.config_dir, 'config.json')
        default_storage = r'C:\factura_uploads' if os.name == 'nt' else '/home/factura_uploads'
        
        self._defaults = {
            'storage_path': default_storage,
            'sftp_port': 22,
            'sftpgo_port': 2022,
            'pg_host': '127.0.0.1',
            'pg_port': 5432,
            'pg_db': 'facturapro_db',
            'pg_user': 'postgres_user',
            'pg_pass': 'ClaveSegura123!',
            'remote_host': '192.168.1.58',
            'remote_port': 22,
            'remote_user': 'factura_sftp',
            'remote_pass': 'ClaveSFTP123!',
            'remote_path': default_storage,
            'ftp_ip': '',
            'ftp_temp_minutes': 30,
            'autostart': True,
            'theme': 'Dark',
            'window_geometry': '980x780',
            # ── SRI / IMAP (Fase 2) ──────────────────────────────────
            'sri_imap_host': 'imap.gmail.com',
            'sri_imap_port': 993,
            'sri_imap_user': '',
            'sri_imap_pass': '',
            'sri_imap_folder': 'INBOX',
            'sri_auto_sync': False,
            'sri_sync_interval_min': 15,
            'sri_org_id_default': 'default',
            # ── Seguridad / anti-intrusión (Fase 3) ─────────────────
            'security_shield_active': True,
            'security_auto_block': True,
            'security_whitelist': [],
            'security_ports': [21, 22, 2022, 5432],
            # ── Recordar estado (Fase 5b) ───────────────────────────
            'last_tab': 0,
            'remember_forms': True,
            'db_last_table': '',
            # ── PG remoto por VPN — compartido con vpn_tab/db_tab ──
            # (vpn_tab.py ya lee pg_remote_*; mantenemos esos nombres)
            'pg_remote_host': '',
            'pg_remote_port': 5432,
            'pg_remote_db': 'facturapro_db',
            'pg_remote_user': '',
            'pg_remote_pass': '',
        }
        self.data = self.load_config()
        self._ensure_storage_dirs()
        self.apply_windows_autostart(self.get('autostart', True))

    def _ensure_storage_dirs(self):
        """Crea automáticamente los directorios locales de almacenamiento si no existen."""
        for key in ['storage_path', 'remote_path']:
            path = self.data.get(key)
            if path and isinstance(path, str):
                try:
                    os.makedirs(path, exist_ok=True)
                except Exception as e:
                    logger.warning(f"No se pudo crear carpeta {path}: {e}")

    def load_config(self):
        if not os.path.exists(self.config_dir):
            try:
                os.makedirs(self.config_dir, exist_ok=True)
            except Exception: pass
            
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    saved = json.load(f)
                    merged = self._defaults.copy()
                    merged.update(saved)
                    return merged
            except Exception as e:
                logger.error(f"Error leyendo {self.config_file}: {e}")
        
        merged = self._defaults.copy()
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(merged, f, indent=4, ensure_ascii=False)
        except Exception: pass
        return merged

    def save_config(self, new_data=None):
        if new_data:
            self.data.update(new_data)
        if not os.path.exists(self.config_dir):
            try:
                os.makedirs(self.config_dir, exist_ok=True)
            except Exception: pass
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Error guardando {self.config_file}: {e}")
        self._ensure_storage_dirs()

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value
        self.save_config()
        if key == 'autostart':
            self.apply_windows_autostart(bool(value))

    def apply_windows_autostart(self, enable: bool):
        """Registra o remueve la aplicación en el inicio automático de Windows (HKCU Run)."""
        if os.name != 'nt':
            return
        try:
            import winreg
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
            app_name = "FacturaProECStorageManager"
            exe_path = f'"{sys.executable}"'
            
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_ALL_ACCESS) as key:
                if enable:
                    winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, exe_path)
                else:
                    try:
                        winreg.DeleteValue(key, app_name)
                    except FileNotFoundError:
                        pass
        except Exception as e:
            logger.warning(f"No se pudo configurar Autostart en registro de Windows: {e}")

