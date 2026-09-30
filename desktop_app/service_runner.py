import os
import sys
import time
import socket
import threading
import subprocess
try:
    import winreg          # solo existe en Windows: en Linux el backend no arrancaba
except ImportError:
    winreg = None
import secrets
import shutil
import re
from datetime import datetime
from config_manager import ConfigManager
from sys_info import check_port_open, find_next_free_port, inspect_special_ports

try:
    from core.error_collector import error_collector
except ImportError:
    try:
        from error_collector import error_collector
    except ImportError:
        error_collector = None

# Sin claves en el código: este archivo va dentro de los instaladores públicos. Las claves de los contenedores
# nuevos se generan al azar al crearlos y se muestran una vez; los tokens se escriben en la app.
DEFAULT_PROFILES = {
    "facturapro": {
        "name": "FacturaProEC Estándar",
        "pg_db": "facturapro_db",
        "pg_user": "postgres_user",
        "pg_pass": "",
        "minio_user": "admin",
        "minio_pass": "",
        "vps_ip": "",
        "frp_port": 7000,
        "frp_token": "",
    },
    "harpi": {
        "name": "Harpi Corp (Industrial)",
        "pg_db": "app_v2_db",
        "pg_user": "Harpi_postgres_",
        "pg_pass": "",
        "minio_user": "admin",
        "minio_pass": "",
        "vps_ip": "",
        "frp_port": 7000,
        "frp_token": "",
    },
}


def clave_aleatoria(largo=24):
    return secrets.token_urlsafe(largo)[:largo]

def generate_docker_compose(
    pg_db="facturapro_db", pg_user="postgres_user", pg_pass=None,
    minio_user="admin", minio_pass=None,
    include_frpc=True,
    pg_host_port=5432, minio_host_port=9000, minio_console_host_port=9001
):
    """Genera dinámicamente el contenido de docker-compose.yml con puertos anfitrión configurables"""
    pg_pass = pg_pass or clave_aleatoria()
    minio_pass = minio_pass or clave_aleatoria()
    frpc_block = """
  frpc:
    image: snowdreamtech/frpc:latest
    container_name: facturapro_frpc
    restart: always
    volumes:
      - ./frpc.toml:/etc/frp/frpc.toml
    extra_hosts:
      - "host.docker.internal:host-gateway"
    depends_on:
      - minio
      - postgres
""" if include_frpc else ""

    return f"""version: '3.8'

services:
  postgres:
    image: postgres:17
    container_name: facturapro_postgres
    restart: always
    environment:
      POSTGRES_DB: "{pg_db}"
      POSTGRES_USER: "{pg_user}"
      POSTGRES_PASSWORD: "{pg_pass}"
    ports:
      - "{pg_host_port}:5432"
    volumes:
      - ./data_postgres:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U {pg_user} -d {pg_db}"]
      interval: 10s
      timeout: 5s
      retries: 5

  minio:
    image: quay.io/minio/minio:latest
    container_name: facturapro_minio
    restart: always
    environment:
      MINIO_ROOT_USER: "{minio_user}"
      MINIO_ROOT_PASSWORD: "{minio_pass}"
    ports:
      - "{minio_host_port}:9000"
      - "{minio_console_host_port}:9001"
    volumes:
      - ./data_minio:/data
    command: server /data --console-address ":9001"
{frpc_block}"""

def generate_frpc_toml(
    vps_ip="", frp_port=7000, frp_token="",
    pg_port=5432, minio_port=9000, minio_console=9001,
    app_prefix="facturapro"
):
    """Genera dinámicamente la configuración del cliente FRP frpc.toml"""
    return f"""# FacturaProEC - frpc.toml generado dinámicamente ({app_prefix})
serverAddr = "{vps_ip}"
serverPort = {frp_port}
auth.token = "{frp_token}"

transport.tcpKeepalive = 10
transport.useCompression = true

[[proxies]]
name = "{app_prefix}_postgres_{pg_port}"
type = "tcp"
localIP = "postgres"
localPort = 5432
remotePort = {pg_port}

[[proxies]]
name = "{app_prefix}_minio_{minio_port}"
type = "tcp"
localIP = "minio"
localPort = 9000
remotePort = {minio_port}

[[proxies]]
name = "{app_prefix}_minio_console_{minio_console}"
type = "tcp"
localIP = "minio"
localPort = 9001
remotePort = {minio_console}
"""

DOCKER_COMPOSE_CONTENT = generate_docker_compose()


class ServiceRunner:
    """Manejador de ejecución de comandos, Docker, firewall y servicios"""
    def __init__(self, config: ConfigManager):
        self.config = config
        self.ftp_timer_thread = None
        self.ftp_remaining_seconds = 0
        self.ftp_active = False
        self.active_tunnels: dict = {}

    def ensure_storage_folder(self, path=None):
        """Crea o confirma la carpeta de almacenamiento con permisos completos"""
        target = path or self.config.get('storage_path', r'C:\factura_uploads')
        try:
            already_existed = os.path.exists(target)
            if not already_existed:
                os.makedirs(target, exist_ok=True)
            if sys.platform == 'win32':
                cmd = f'icacls "{target}" /grant Everyone:(OI)(CI)F /T /Q'
                subprocess.run(cmd, shell=True, capture_output=True)
            else:
                cmd = f'chmod 777 "{target}"'
                subprocess.run(cmd, shell=True, capture_output=True)
            self.config.set('storage_path', target)
            status_txt = "confirmada y lista" if already_existed else "creada e inicializada"
            return True, f"Ruta {status_txt}: {target}"
        except Exception as e:
            return False, f"Error preparando la ruta: {str(e)}"

    def install_and_start_openssh_server(self):
        """Instala y activa el servicio OpenSSH SSH Server en Windows/Linux de forma automática"""
        if sys.platform != 'win32':
            cmd = "sudo systemctl enable --now ssh || sudo systemctl enable --now sshd"
            subprocess.run(cmd, shell=True, capture_output=True)
            return True, "Servidor SSH activado en Linux."

        try:
            out = subprocess.check_output('sc query "sshd"', shell=True, text=True, stderr=subprocess.DEVNULL)
            if "RUNNING" in out:
                return True, "El servicio OpenSSH (SFTP) ya está instalado y ejecutándose en el puerto 22."
        except Exception:
            pass

        ps_script = """
        $ssh = Get-WindowsCapability -Online | Where-Object Name -like 'OpenSSH.Server*'
        if ($ssh.State -ne 'Installed') {
            Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0 -ErrorAction SilentlyContinue
        }
        Start-Service sshd -ErrorAction SilentlyContinue
        Set-Service -Name sshd -StartupType Automatic -ErrorAction SilentlyContinue
        if (!(Get-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -ErrorAction SilentlyContinue)) {
            New-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -DisplayName 'OpenSSH SSH Server' -Enabled True -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22 -ErrorAction SilentlyContinue
        }
        """
        cmd = f'powershell -ExecutionPolicy Bypass -Command "{ps_script.replace(chr(10), "; ")}"'
        subprocess.run(cmd, shell=True, capture_output=True, text=True)

        subprocess.run('powershell -Command "Start-Service sshd"', shell=True, capture_output=True)
        time.sleep(1.5)

        if check_port_open("127.0.0.1", 22):
            return True, "✅ Servidor OpenSSH (SFTP) instalado, activado y respondiendo en el puerto 22."

        try:
            out = subprocess.check_output('sc query "sshd"', shell=True, text=True, stderr=subprocess.DEVNULL)
            if "RUNNING" in out:
                return True, "✅ Servicio OpenSSH iniciado correctamente en el puerto 22."
        except Exception:
            pass

        return False, "No se pudo iniciar el servicio OpenSSH. Asegúrate de ejecutar la aplicación con Privilegios de Administrador."

    def create_restricted_sftp_user(self, username="factura_sftp", password=None, folder_path=r"C:\factura_uploads"):
        """Crea un usuario de SO/SFTP dedicado restringido exclusivamente a la carpeta especificada"""
        if not password:     # antes todos quedaban con la misma clave del código
            password = clave_aleatoria(20)
        folder = folder_path or self.config.get('storage_path', r'C:\factura_uploads')
        self.ensure_storage_folder(folder)

        if sys.platform == 'win32':
            cmd_check = f'net user "{username}"'
            res_check = subprocess.run(cmd_check, shell=True, capture_output=True, text=True)

            if res_check.returncode == 0:
                cmd_pass = f'net user "{username}" "{password}"'
                subprocess.run(cmd_pass, shell=True, capture_output=True)
                action_str = "actualizado"
            else:
                cmd_add = f'net user "{username}" "{password}" /add /fullname:"FacturaProEC SFTP User" /comment:"Usuario restringido para almacenamiento SFTP" /expires:never'
                res_add = subprocess.run(cmd_add, shell=True, capture_output=True, text=True)
                if res_add.returncode != 0:
                    return False, f"Error al crear usuario en Windows (requiere permisos Admin): {res_add.stderr or res_add.stdout}"
                action_str = "creado exitosamente"

            cmd_perm = f'icacls "{folder}" /grant {username}:(OI)(CI)F /T /Q'
            subprocess.run(cmd_perm, shell=True, capture_output=True)

            self.install_and_start_openssh_server()

            return True, (f"✅ Usuario SFTP '{username}' {action_str}.\nRestringido a la carpeta: {folder}\n"
                          f"Servidor OpenSSH verificado en puerto 22.\nClave: {password} (guárdala: no se vuelve a mostrar)")

        else:
            try:
                cmd_add = f'sudo useradd -m -s /sbin/nologin -d "{folder}" "{username}" 2>/dev/null || true'
                subprocess.run(cmd_add, shell=True, capture_output=True)
                cmd_pass = f'echo "{username}:{password}" | sudo chpasswd'
                subprocess.run(cmd_pass, shell=True, capture_output=True)
                cmd_perm = f'sudo chmod 777 "{folder}"'
                subprocess.run(cmd_perm, shell=True, capture_output=True)
                return True, f"✅ Usuario Linux SFTP '{username}' creado/actualizado.\nRestringido a: {folder}"
            except Exception as e:
                return False, f"Error creando usuario Linux: {str(e)}"

    def check_docker_installed(self):
        """Verifica si Docker CLI / Docker Desktop está instalado en el sistema"""
        try:
            res = subprocess.run("docker --version", shell=True, capture_output=True, text=True)
            return res.returncode == 0
        except Exception:
            return False

    def launch_docker_stack(
        self,
        pg_db="facturapro_db",
        pg_user="postgres_user",
        pg_pass=None,
        minio_user="admin",
        minio_pass=None,
        vps_ip="",
        frp_port=7000,
        frp_token="",
        include_frpc=True,
        profile="facturapro",
        pg_host_port=None,
        minio_host_port=None,
        minio_console_host_port=None,
        auto_remap=True,
    ):
        """Crea docker-compose.yml y frpc.toml con resolución autónoma de conflictos de puertos y levanta el stack"""
        if not self.check_docker_installed():
            msg = "Docker no está instalado o no se encuentra en el PATH. Instala Docker Desktop primero."
            if error_collector:
                error_collector.record_error(
                    title="Docker no encontrado",
                    detail=msg,
                    severity="error",
                    source="service_runner.launch_docker_stack",
                    suggested_fix="Descargar e instalar Docker Desktop para Windows"
                )
            return False, msg

        # Claves al azar para los contenedores nuevos (antes todos con la misma clave débil del código)
        pg_pass = pg_pass or clave_aleatoria()
        minio_pass = minio_pass or clave_aleatoria()
        if include_frpc and not (vps_ip and frp_token):
            include_frpc = False     # sin servidor ni token FRP propios no se crea el túnel FRP

        # Resolver puertos del anfitrión de manera autónoma
        actual_pg_port = pg_host_port or 5432
        actual_minio_port = minio_host_port or 9000
        actual_minio_console = minio_console_host_port or 9001
        remapped_msgs = []

        if auto_remap:
            if pg_host_port is None and check_port_open("127.0.0.1", 5432):
                actual_pg_port = find_next_free_port(5433)
                remapped_msgs.append(f"PostgreSQL: 5432 -> {actual_pg_port}")
                if error_collector:
                    error_collector.record_error(
                        title="Conflicto en puerto 5432 (PostgreSQL)",
                        detail=f"Puerto 5432 ocupado por otro servicio. Re-mapeando host a puerto libre {actual_pg_port}:5432.",
                        severity="warning",
                        source="service_runner.launch_docker_stack",
                        port=5432,
                        suggested_fix=f"Conectarse localmente mediante el puerto {actual_pg_port}."
                    )

            if minio_host_port is None and check_port_open("127.0.0.1", 9000):
                actual_minio_port = find_next_free_port(9002)
                remapped_msgs.append(f"MinIO API: 9000 -> {actual_minio_port}")
                if error_collector:
                    error_collector.record_error(
                        title="Conflicto en puerto 9000 (MinIO S3)",
                        detail=f"Puerto 9000 ocupado. Re-mapeando host a puerto libre {actual_minio_port}:9000.",
                        severity="warning",
                        source="service_runner.launch_docker_stack",
                        port=9000,
                        suggested_fix=f"Acceder al API S3 en el puerto {actual_minio_port}."
                    )

            if minio_console_host_port is None and check_port_open("127.0.0.1", 9001):
                actual_minio_console = find_next_free_port(9003)
                remapped_msgs.append(f"MinIO Consola: 9001 -> {actual_minio_console}")

        target_dir = r"C:\facturapro_docker" if sys.platform == 'win32' else os.path.expanduser("~/facturapro_docker")
        os.makedirs(target_dir, exist_ok=True)
        compose_file = os.path.join(target_dir, "docker-compose.yml")
        frpc_file = os.path.join(target_dir, "frpc.toml")

        # Generar contenido dinámico
        compose_content = generate_docker_compose(
            pg_db=pg_db, pg_user=pg_user, pg_pass=pg_pass,
            minio_user=minio_user, minio_pass=minio_pass,
            include_frpc=include_frpc,
            pg_host_port=actual_pg_port,
            minio_host_port=actual_minio_port,
            minio_console_host_port=actual_minio_console
        )
        with open(compose_file, "w", encoding="utf-8") as f:
            f.write(compose_content.strip())

        if include_frpc:
            frpc_content = generate_frpc_toml(
                vps_ip=vps_ip, frp_port=frp_port, frp_token=frp_token,
                pg_port=actual_pg_port, minio_port=actual_minio_port, minio_console=actual_minio_console,
                app_prefix=profile
            )
            with open(frpc_file, "w", encoding="utf-8") as f:
                f.write(frpc_content.strip())

        cmd = f'cd "{target_dir}" && docker compose up -d'
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True)

        if res.returncode == 0:
            msg = (
                f"Contenedores (PostgreSQL 17, MinIO S3 y Túnel FRP) iniciados exitosamente.\n"
                f"Ruta: {target_dir}\nBD: {pg_db} | Usuario: {pg_user} | Clave: {pg_pass}\n"
                f"MinIO: usuario {minio_user} | clave {minio_pass}  (guárdalas: también quedan en docker-compose.yml)\n"
                f"Puertos activos -> PG: {actual_pg_port}, MinIO: {actual_minio_port}, Consola: {actual_minio_console}"
            )
            if remapped_msgs:
                msg += f"\n[Auto-reparación de puertos]: {', '.join(remapped_msgs)}"
            return True, msg
        else:
            err_msg = res.stderr or res.stdout
            if error_collector:
                error_collector.record_error(
                    title="Error al levantar Docker Compose",
                    detail=err_msg,
                    severity="error",
                    source="service_runner.launch_docker_stack"
                )
            return False, f"Error al ejecutar Docker Compose: {err_msg}"

    def test_db_connection(self, host, port=5432):
        """Prueba la conectividad TCP a la base de datos PostgreSQL"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2.5)
            result = sock.connect_ex((host, int(port)))
            sock.close()
            if result == 0:
                return True, f"✅ Conexión TCP exitosa a la Base de Datos en {host}:{port}"
            else:
                return False, f"❌ No se pudo conectar a {host}:{port}. Verifica que la BD o el contenedor esté encendido."
        except Exception as e:
            return False, f"❌ Error de red: {str(e)}"

    def open_temporary_ftp(self, minutes=30, remote_ip=None, on_tick_callback=None, on_finish_callback=None):
        """Abre el puerto 21 en el firewall de Windows por X minutos (opcionalmente filtrado por IP)"""
        if self.ftp_active:
            return False, "Ya existe un temporizador FTP activo."

        rule_name = f"FacturaProEC_FTP_Temporal_{int(time.time())}"
        if remote_ip and remote_ip.strip():
            cmd_open = f'powershell -Command "New-NetFirewallRule -DisplayName \'{rule_name}\' -Direction Inbound -LocalPort 21 -Protocol TCP -RemoteAddress \'{remote_ip.strip()}\' -Action Allow"'
            msg = f"Puerto FTP (21) abierto por {minutes} min restringido a la IP: {remote_ip.strip()}"
        else:
            cmd_open = f'powershell -Command "New-NetFirewallRule -DisplayName \'{rule_name}\' -Direction Inbound -LocalPort 21 -Protocol TCP -Action Allow"'
            msg = f"Puerto FTP (21) abierto temporalmente por {minutes} minutos."

        res = subprocess.run(cmd_open, shell=True, capture_output=True, text=True)
        if res.returncode != 0:
            return False, f"Error en Firewall (requiere permisos de Administrador): {res.stderr or res.stdout}"

        self.ftp_active = True
        self.ftp_remaining_seconds = minutes * 60

        def _timer_worker():
            while self.ftp_remaining_seconds > 0 and self.ftp_active:
                if on_tick_callback:
                    on_tick_callback(self.ftp_remaining_seconds)
                time.sleep(1)
                self.ftp_remaining_seconds -= 1

            cmd_close = f'powershell -Command "Remove-NetFirewallRule -DisplayName \'{rule_name}\'"'
            subprocess.run(cmd_close, shell=True, capture_output=True)
            self.ftp_active = False
            if on_finish_callback:
                on_finish_callback()

        self.ftp_timer_thread = threading.Thread(target=_timer_worker, daemon=True)
        self.ftp_timer_thread.start()

        return True, msg

    def open_permanent_ftp(self, remote_ip=None):
        """Abre el puerto 21 de forma permanente en el firewall (opcionalmente restringido por IP)"""
        rule_name = "FacturaProEC_FTP_Permanente"
        cmd_del = f'powershell -Command "Remove-NetFirewallRule -DisplayName \'{rule_name}\' -ErrorAction SilentlyContinue"'
        subprocess.run(cmd_del, shell=True, capture_output=True)

        if remote_ip and remote_ip.strip():
            cmd_open = f'powershell -Command "New-NetFirewallRule -DisplayName \'{rule_name}\' -Direction Inbound -LocalPort 21 -Protocol TCP -RemoteAddress \'{remote_ip.strip()}\' -Action Allow"'
            msg = f"Puerto FTP (21) abierto PERMANENTEMENTE solo para la IP fija: {remote_ip.strip()}"
        else:
            cmd_open = f'powershell -Command "New-NetFirewallRule -DisplayName \'{rule_name}\' -Direction Inbound -LocalPort 21 -Protocol TCP -Action Allow"'
            msg = "Puerto FTP (21) abierto PERMANENTEMENTE para toda la red."

        res = subprocess.run(cmd_open, shell=True, capture_output=True, text=True)
        if res.returncode == 0:
            return True, msg
        else:
            return False, f"Error en Firewall: {res.stderr or res.stdout}"

    def cancel_temporary_ftp(self):
        """Cancela y cierra el FTP temporal e intesta limpiar reglas permanentes"""
        self.ftp_active = False
        cmd_close = 'powershell -Command "Remove-NetFirewallRule -DisplayName \'FacturaProEC_FTP_*\'"'
        subprocess.run(cmd_close, shell=True, capture_output=True)
        return True, "Reglas de puerto FTP cerradas manualmente."

    def emergency_lockdown(self):
        """Cierra inmediatamente todas las reglas de firewall y bloquea puertos"""
        try:
            if sys.platform == 'win32':
                cmd1 = 'powershell -Command "Remove-NetFirewallRule -DisplayName \'FacturaProEC_*\' -ErrorAction SilentlyContinue"'
                subprocess.run(cmd1, shell=True, capture_output=True)
                cmd2 = 'powershell -Command "Disable-NetFirewallRule -DisplayName \'OpenSSH-Server-In-TCP\' -ErrorAction SilentlyContinue"'
                subprocess.run(cmd2, shell=True, capture_output=True)
            else:
                cmd = "sudo ufw deny 21/tcp || sudo iptables -A INPUT -p tcp --dport 21 -j DROP"
                subprocess.run(cmd, shell=True, capture_output=True)
            self.cancel_temporary_ftp()
            return True, "🔒 CERROJO DE EMERGENCIA ACTIVADO: Se han cerrado todas las reglas de firewall y puertos de red."
        except Exception as e:
            return False, f"Error activando cerrojo: {str(e)}"

    def set_autostart(self, enable=True):
        """Habilita o deshabilita el inicio automático con Windows en el Registro"""
        if sys.platform != 'win32':
            return True, "Autoarranque en Linux configurado vía .desktop"

        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        app_name = "FacturaProECStorageManager"
        exe_path = sys.executable if getattr(sys, 'frozen', False) else os.path.abspath(sys.argv[0])

        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_ALL_ACCESS)
            if enable:
                winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, f'"{exe_path}" --minimized')
            else:
                try:
                    winreg.DeleteValue(key, app_name)
                except FileNotFoundError:
                    pass
            winreg.CloseKey(key)
            self.config.set('autostart', enable)
            return True, f"Inicio automático con Windows: {'Activado' if enable else 'Desactivado'}"
        except Exception as e:
            return False, f"Error configurando autoarranque: {str(e)}"

    def open_pg_port_firewall(self):
        """Abre el puerto 5432 (PostgreSQL) en el Firewall de Windows"""
        if sys.platform != 'win32':
            return True, "Puerto 5432 permitido en Linux."
        rule_name = "FacturaProEC_PG_5432"
        cmd = f'powershell -Command "New-NetFirewallRule -DisplayName \'{rule_name}\' -Direction Inbound -LocalPort 5432 -Protocol TCP -Action Allow -ErrorAction SilentlyContinue"'
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if res.returncode == 0:
            return True, "✅ Puerto 5432 (PostgreSQL) ABIERTO en el Firewall de Windows."
        else:
            return False, f"Error en Firewall: {res.stderr or res.stdout}"

    def open_sftp_port_firewall(self):
        """Abre el puerto 22 (SFTP/SSH) en el Firewall de Windows"""
        if sys.platform != 'win32':
            return True, "Puerto 22 permitido en Linux."
        rule_name = "FacturaProEC_SFTP_22"
        cmd = f'powershell -Command "New-NetFirewallRule -DisplayName \'{rule_name}\' -Direction Inbound -LocalPort 22 -Protocol TCP -Action Allow -ErrorAction SilentlyContinue"'
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if res.returncode == 0:
            return True, "✅ Puerto 22 (SFTP/SSH) ABIERTO en el Firewall de Windows."
        else:
            return False, f"Error en Firewall: {res.stderr or res.stdout}"

    def find_tunnel_binary(self, binary_name: str) -> str:
        """Busca binarios de túneles (zrok, ngrok, cloudflared) en PATH y rutas conocidas"""
        found = shutil.which(binary_name)
        if found:
            return found
        candidates = [
            rf"C:\FacturaProEC\bin\{binary_name}.exe",
            rf"C:\Program Files\{binary_name}\{binary_name}.exe",
            rf"C:\tools\{binary_name}\{binary_name}.exe",
            os.path.expanduser(rf"~\AppData\Local\bin\{binary_name}.exe"),
            os.path.expanduser(rf"~\{binary_name}\{binary_name}.exe"),
            os.path.join(os.path.dirname(__file__), "bin", f"{binary_name}.exe"),
        ]
        for c in candidates:
            if os.path.isfile(c):
                return c
        return None

    def start_tunnel(self, tunnel_type: str, port: int = 5432, extra_args: dict = None) -> tuple[bool, str, dict]:
        """Inicia un túnel en segundo plano con captura de logs y estado"""
        extra_args = extra_args or {}
        tunnel_id = f"{tunnel_type}_{port}_{int(time.time())}"

        bin_name = "zrok" if "zrok" in tunnel_type else ("ngrok" if "ngrok" in tunnel_type else "cloudflared")
        bin_path = self.find_tunnel_binary(bin_name)
        if not bin_path:
            msg = f"Binario '{bin_name}' no encontrado en el PATH ni en C:\\FacturaProEC\\bin. Instálalo para continuar."
            if error_collector:
                error_collector.record_error(
                    title=f"Binario de túnel no encontrado ({bin_name})",
                    detail=msg,
                    severity="warning",
                    source="service_runner.start_tunnel",
                    suggested_fix=f"Descargar {bin_name}.exe y colocarlo en C:\\FacturaProEC\\bin o en el PATH."
                )
            return False, msg, {}

        cmd = []
        if tunnel_type == "zrok_tcp":
            cmd = [bin_path, "share", "public", "--backend-mode", "tcpTunnel", str(port)]
        elif tunnel_type == "zrok_http":
            cmd = [bin_path, "share", "public", f"http://localhost:{port}"]
        elif tunnel_type == "zrok_reserved":
            token = extra_args.get("token", "")
            if not token:
                return False, "Se requiere un token reservado para iniciar el túnel zrok_reserved.", {}
            cmd = [bin_path, "share", "reserved", token]
        elif tunnel_type == "ngrok_tcp":
            cmd = [bin_path, "tcp", str(port)]
        elif tunnel_type == "ngrok_http":
            cmd = [bin_path, "http", str(port)]
        elif tunnel_type == "cloudflared_http":
            cmd = [bin_path, "tunnel", "--url", f"http://localhost:{port}"]
        else:
            return False, f"Tipo de túnel no soportado: {tunnel_type}", {}

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            )

            tunnel_info = {
                "id": tunnel_id,
                "type": tunnel_type,
                "port": port,
                "pid": proc.pid,
                "bin_path": bin_path,
                "start_time": datetime.now().isoformat(),
                "status": "running",
                "logs": [],
                "public_url": None,
                "process": proc
            }

            def _log_reader():
                url_patterns = [
                    re.compile(r'(https?://[^\s<>"]+|tcp://[^\s<>"]+)'),
                    re.compile(r'([a-zA-Z0-9-]+\.zrok\.io)'),
                    re.compile(r'([a-zA-Z0-9-]+\.ngrok-free\.app)'),
                    re.compile(r'([a-zA-Z0-9-]+\.trycloudflare\.com)'),
                ]
                for line in iter(proc.stdout.readline, ''):
                    clean = line.strip()
                    if clean:
                        tunnel_info["logs"].append(clean)
                        if len(tunnel_info["logs"]) > 200:
                            tunnel_info["logs"].pop(0)
                        if not tunnel_info["public_url"]:
                            for pat in url_patterns:
                                m = pat.search(clean)
                                if m:
                                    tunnel_info["public_url"] = m.group(1)
                                    break
                proc.stdout.close()
                tunnel_info["status"] = "stopped"

            t = threading.Thread(target=_log_reader, daemon=True)
            t.start()

            self.active_tunnels[tunnel_id] = tunnel_info
            time.sleep(1.0)
            return True, f"Túnel {tunnel_type} iniciado (PID: {proc.pid}) en puerto {port}", {
                "id": tunnel_id,
                "type": tunnel_type,
                "port": port,
                "pid": proc.pid,
                "status": "running"
            }
        except Exception as e:
            if error_collector:
                error_collector.record_error(
                    title=f"Error al iniciar túnel {tunnel_type}",
                    detail=str(e),
                    severity="error",
                    source="service_runner.start_tunnel",
                    exception=e
                )
            return False, f"Fallo al ejecutar {bin_name}: {str(e)}", {}

    def stop_tunnel(self, tunnel_id: str) -> tuple[bool, str]:
        """Detiene un túnel activo por su identificador"""
        if tunnel_id not in self.active_tunnels:
            return False, f"Túnel con ID '{tunnel_id}' no encontrado o ya inactivo."

        t_info = self.active_tunnels[tunnel_id]
        proc = t_info.get("process")
        try:
            if proc and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
            t_info["status"] = "terminated"
            del self.active_tunnels[tunnel_id]
            return True, f"Túnel '{tunnel_id}' detenido correctamente."
        except Exception as e:
            return False, f"Error deteniendo túnel: {str(e)}"

    def get_tunnels_status(self) -> list[dict]:
        """Devuelve lista de túneles registrados y su estado actual"""
        res = []
        dead = []
        for tid, t in list(self.active_tunnels.items()):
            proc = t.get("process")
            status = t["status"]
            if proc and proc.poll() is not None:
                status = f"exited ({proc.poll()})"
                dead.append(tid)
            res.append({
                "id": t["id"],
                "type": t["type"],
                "port": t["port"],
                "pid": t["pid"],
                "status": status,
                "start_time": t["start_time"],
                "public_url": t["public_url"],
                "last_logs": t["logs"][-6:] if t.get("logs") else [],
            })
        for d in dead:
            if d in self.active_tunnels:
                del self.active_tunnels[d]
        return res

    def auto_heal_conflicts(self) -> dict:
        """Inspecciona puertos especiales y propone / ejecuta acciones autónomas de auto-reparación"""
        inspection = inspect_special_ports()
        ports_list = inspection.get("ports", [])
        conflicts = [p for p in ports_list if p.get("is_conflict") or p.get("status") == "CONFLICT"]
        healing_actions = []

        for c in conflicts:
            port = c["port"]
            pid = c.get("pid")
            pname = c.get("process_name")
            fallback = c.get("suggested_port") or (port + 1)
            if port in (5432, 9000, 9001):
                healing_actions.append({
                    "port": port,
                    "issue": f"Puerto {port} ocupado por {pname} (PID: {pid})",
                    "action_taken": "reconfig_docker_host_port",
                    "suggested_port": fallback,
                    "detail": f"Docker Compose mapeará el anfitrión a {fallback}:{port} para evitar colisión sin detener el servicio existente."
                })
            else:
                healing_actions.append({
                    "port": port,
                    "issue": f"Puerto {port} ocupado por {pname} (PID: {pid})",
                    "action_taken": "suggest_fallback",
                    "suggested_port": fallback,
                    "detail": f"Conflicto con servicio ({pname}). Se recomienda redirigir tráfico al puerto libre {fallback}."
                })

        return {
            "ok": True,
            "total_conflicts": len(conflicts),
            "conflicts": conflicts,
            "healing_actions": healing_actions,
            "timestamp": datetime.now().isoformat()
        }


