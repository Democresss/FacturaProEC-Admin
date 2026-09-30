import os
import sys
import time
import socket
import shutil
import subprocess
import ctypes

def is_admin():
    """¿La aplicación tiene permisos de administrador? (Windows: UAC; Linux/macOS: root)"""
    if os.name != "nt":
        return hasattr(os, "geteuid") and os.geteuid() == 0
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False

def get_local_ip():
    """Obtiene la IP local IPv4 principal de la máquina"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return "127.0.0.1"

def get_disk_info(path=r"C:\factura_uploads"):
    """Obtiene espacio total, usado y libre en GB"""
    target = path if os.path.exists(path) else "C:\\"
    try:
        total, used, free = shutil.disk_usage(target)
        gb = 1024 ** 3
        return {
            'total_gb': round(total / gb, 1),
            'used_gb': round(used / gb, 1),
            'free_gb': round(free / gb, 1),
            'used_pct': round((used / total) * 100, 1)
        }
    except Exception:
        return {'total_gb': 0, 'used_gb': 0, 'free_gb': 0, 'used_pct': 0}

def count_local_files(path=r"C:\factura_uploads"):
    """Cuenta el número de archivos almacenados localmente"""
    if not os.path.exists(path):
        return 0
    count = 0
    for root, dirs, files in os.walk(path):
        count += len(files)
    return count

def check_port_open(ip, port, timeout=1.2):
    """Verifica si un puerto está respondiendo en la IP especificada"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((ip, int(port)))
        sock.close()
        return result == 0
    except Exception:
        return False

def ping_host(host, timeout_ms=1000):
    """Realiza un ping a la IP/Host especificado"""
    try:
        if os.name == 'nt':
            cmd = f"ping -n 1 -w {timeout_ms} {host}"
        else:
            cmd = f"ping -c 1 -W 1 {host}"
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        return res.returncode == 0
    except Exception:
        return False

def detect_local_services():
    """Detecta todos los servicios SFTP, SSH, FTP, MinIO S3 y PostgreSQL en el equipo local"""
    ip = get_local_ip()
    services = {
        'openssh_22': check_port_open(ip, 22),
        'sftpgo_2022': check_port_open(ip, 2022),
        'ftp_21': check_port_open(ip, 21),
        'postgres_5432': check_port_open(ip, 5432),
        'minio_9000': check_port_open(ip, 9000),
        'sftpgo_web_8080': check_port_open(ip, 8080)
    }
    return services

def check_active_net_connections(target_ports=None, allowed_ips=None):
    """Monitorea conexiones de red activas en busca de IPs desconocidas.

    Multiplataforma:
      - Windows: `netstat -ano -p tcp`
      - Linux:   `ss -tunap` (preferido, iproute2) con fallback a `netstat -tunap`

    Retorna una lista de dicts `{'port', 'remote_ip', 'full_addr'}` para cada
    conexión ESTABLISHED sobre un puerto local en `target_ports` desde una IP
    remota que no esté en `allowed_ips`. Si `allowed_ips` es None, usa un
    mínimo interno (`127.0.0.1`, `0.0.0.0`, `::1`).

    Nota: el allowlist interno aquí es un piso mínimo; el caller (p.ej. el
    `SecurityGuardian`) debe pasar su propio `allowed_ips` extendido (IP local
    + remote_host + whitelist persistente) para no sobre-reportar.
    """
    if target_ports is None:
        target_ports = [21, 22, 2022, 5432]
    if allowed_ips is None:
        allowed_ips = {"127.0.0.1", "0.0.0.0", "::1"}
    suspicious = []
    try:
        if os.name == 'nt':
            suspicious = _scan_windows(target_ports, allowed_ips)
        else:
            suspicious = _scan_linux(target_ports, allowed_ips)
    except Exception:
        pass
    return suspicious


def _scan_windows(target_ports, allowed_ips):
    """netstat -ano -p tcp — formato: 'TCP  local:port  foreign:port  ESTABLISHED  pid'"""
    suspicious = []
    # Windows netstat saca salida en cp1252/latin-1 (caracteres no-ASCII en
    # nombres de proceso con tildes). Usamos errors='replace' para no
    # tronar el subprocess y aceptar cualquier encoding.
    res = subprocess.run("netstat -ano -p tcp", shell=True,
                         capture_output=True, text=True,
                         encoding="utf-8", errors="replace")
    if res.returncode != 0:
        return suspicious
    for line in res.stdout.splitlines():
        if "ESTABLISHED" not in line:
            continue
        parts = line.split()
        if len(parts) < 3:
            continue
        local_addr = parts[1]
        foreign_addr = parts[2]
        _check_line(suspicious, local_addr, foreign_addr,
                    target_ports, allowed_ips)
    return suspicious


def _scan_linux(target_ports, allowed_ips):
    """Prefiere `ss -tunap`; cae a `netstat -tunap` si falta ss.

    Salida de `ss` (con -tunap): cabecera + filas tipo
        tcp ESTAB 0 0 127.0.0.1:5432   192.168.1.5:51234 users:(("postgres",pid=1,fd=12))
    Las columnas separadas por espacios; tomamos Local Address (col 4) y
    Peer Address (col 5) cuando State es ESTAB.
    """
    suspicious = []
    out = None
    # Intentar ss primero (presente en arch/mint por defecto con iproute2)
    if shutil.which("ss"):
        res = subprocess.run(["ss", "-tunap"], capture_output=True,
                             text=True, encoding="utf-8", errors="replace")
        if res.returncode == 0:
            out = res.stdout
    # Fallback a netstat
    if not out and shutil.which("netstat"):
        res = subprocess.run(["netstat", "-tunap"], capture_output=True,
                             text=True, encoding="utf-8", errors="replace")
        if res.returncode == 0:
            out = res.stdout
    if not out:
        return suspicious

    in_states = ("ESTAB", "ESTABLISHED")
    for line in out.splitlines():
        # Saltar cabeceras (Netid State ...)
        if not line.strip() or line.startswith("Netid") or line.startswith("Proto"):
            continue
        tokens = line.split()
        if not tokens:
            continue
        if tokens[0] in ("tcp", "tcp6", "udp", "udp6"):
            # `ss`: tokens = [proto, state, ..., local, peer, ...]
            # `netstat -tunap`: 'tcp  0  0  local  peer  ESTABLISHED ...'
            if _parse_ss_line(tokens, suspicious, target_ports, allowed_ips):
                continue
            _parse_netstat_line(tokens, line, suspicious, target_ports, allowed_ips)
    return suspicious


def _parse_ss_line(tokens, suspicious, target_ports, allowed_ips):
    """Formato `ss -tunap`. La línea ópt es completada si era formato ss."""
    # proto=tcp/udp/tcp6/udp6, idx 1=State (ss), o saltado (netstat clásico)
    # Cabecera ss: tcp ESTAB 0 0  local:port  peer:port ...
    if len(tokens) < 5:
        return False
    state = tokens[1].upper()
    if state not in ("ESTAB", "ESTABLISHED"):
        return False
    local_addr = tokens[4]
    foreign_addr = tokens[5] if len(tokens) > 5 else ""
    _check_line(suspicious, local_addr, foreign_addr,
                target_ports, allowed_ips)
    return True


def _parse_netstat_line(tokens, line, suspicious, target_ports, allowed_ips):
    """`netstat -tunap` clásico: 'tcp 0 0 local peer ESTABLISHED 1/process'."""
    if "ESTABLISHED" not in line and "ESTAB" not in line:
        return
    # tokens: [proto, rx-q, tx-q, local, foreign, state, ...] (sin cabecera)
    if len(tokens) < 6:
        return
    local_addr = tokens[3]
    foreign_addr = tokens[4]
    _check_line(suspicious, local_addr, foreign_addr,
                target_ports, allowed_ips)


def _check_line(suspicious, local_addr, foreign_addr, target_ports, allowed_ips):
    """Filtra y agrega si la IP remota no está en allowed_ips."""
    try:
        for port in target_ports:
            if f":{port}" in (local_addr or ""):
                # foreign_addr puede ser '1.2.3.4:port' o '[::1]:port'
                rem_part = foreign_addr or ""
                # Quitar el bloque IPv6 [...]:port si existe
                if rem_part.startswith("[") and "]" in rem_part:
                    rem_ip = rem_part.split("]")[0].lstrip("[")
                else:
                    rem_ip = rem_part.split(":")[0]
                # Descartar vacíos y caracteres raros
                if rem_ip and rem_ip not in allowed_ips:
                    suspicious.append({
                        'port': port,
                        'remote_ip': rem_ip,
                        'full_addr': foreign_addr,
                    })
    except Exception:
        pass


def test_sftp_full_connection(host, port, user, password, folder):
    """Realiza una prueba completa de conectividad Ping + TCP + Diagnóstico"""
    host = host.strip() or "127.0.0.1"
    port = int(port or 22)

    ping_ok = ping_host(host)
    tcp_ok = check_port_open(host, port, timeout=2.0)

    if not tcp_ok:
        if not ping_ok:
            return False, f"❌ El servidor {host} no responde al Ping ni al puerto {port}. Verifica que la máquina esté encendida y conectada a la red."
        else:
            return False, f"⚠️ El servidor {host} responde al Ping pero el puerto SSH {port} está cerrado o bloqueado por Firewall."
    
    return True, f"✅ Servidor {host} alcanzado y respondiendo en el puerto SSH {port}."


# ─────────────────────────────────────────────────────────────────────────────
# RADAR DE PUERTOS ESPECIALES Y CONFLICTOS
# ─────────────────────────────────────────────────────────────────────────────

SPECIAL_PORTS_CATALOG = {
    5432: {"service": "PostgreSQL Principal", "type": "Database", "expected": ["postgres", "postgres.exe", "docker-proxy", "docker-proxy.exe"], "fallback": 5433},
    5433: {"service": "PostgreSQL Secundario / Docker", "type": "Database", "expected": ["postgres", "postgres.exe", "docker-proxy", "docker-proxy.exe"], "fallback": 5434},
    9000: {"service": "MinIO S3 API", "type": "Storage", "expected": ["minio", "minio.exe", "docker-proxy", "docker-proxy.exe"], "fallback": 9002},
    9001: {"service": "MinIO Web Console", "type": "Storage", "expected": ["minio", "minio.exe", "docker-proxy", "docker-proxy.exe"], "fallback": 9003},
    22: {"service": "OpenSSH / SFTP", "type": "FileTransfer", "expected": ["sshd", "sshd.exe"], "fallback": 2022},
    2022: {"service": "SFTPGo SFTP", "type": "FileTransfer", "expected": ["sftpgo", "sftpgo.exe", "docker-proxy", "docker-proxy.exe"], "fallback": 2023},
    8080: {"service": "SFTPGo Web Admin", "type": "Admin", "expected": ["sftpgo", "sftpgo.exe", "docker-proxy", "docker-proxy.exe"], "fallback": 8082},
    8000: {"service": "FacturaPro Web (FastAPI)", "type": "Web", "expected": ["python", "python.exe", "uvicorn", "uvicorn.exe"], "fallback": 8001},
    8001: {"service": "FacturaPro V2 Web / API", "type": "Web", "expected": ["python", "python.exe", "uvicorn", "uvicorn.exe"], "fallback": 8002},
    4040: {"service": "Ngrok Inspector", "type": "Tunnel", "expected": ["ngrok", "ngrok.exe"], "fallback": 4041},
    8081: {"service": "Zrok Web UI", "type": "Tunnel", "expected": ["zrok", "zrok.exe"], "fallback": 8082},
    7000: {"service": "FRP Server Control", "type": "Tunnel", "expected": ["frps", "frps.exe", "docker-proxy", "docker-proxy.exe"], "fallback": 7001},
    21: {"service": "FTP Temporal", "type": "FileTransfer", "expected": ["ftpd", "svchost.exe", "filezilla"], "fallback": 2121},
}


def find_next_free_port(start_port: int, max_tries: int = 15) -> int:
    """Busca el siguiente puerto TCP libre a partir de start_port."""
    for p in range(start_port, start_port + max_tries):
        if not check_port_open("127.0.0.1", p, timeout=0.3):
            return p
    return start_port + max_tries


def inspect_special_ports() -> dict:
    """Inspecciona todos los puertos especiales críticos de FacturaProEC,
    detectando si están escuchando, qué proceso y PID los tiene tomados,
    si existe algún conflicto con otra aplicación y qué puerto alternativo usar."""
    listening_map = {}   # port -> pid
    pid_name_map = {}    # pid -> process_name

    # 1. Obtener PIDs en escucha según OS
    if sys.platform == "win32":
        try:
            res_net = subprocess.run("netstat -ano -p tcp", shell=True, capture_output=True, text=True, timeout=5)
            for line in (res_net.stdout or "").splitlines():
                if "LISTENING" in line:
                    parts = line.split()
                    if len(parts) >= 5:
                        addr = parts[1]
                        pid = parts[-1]
                        if ":" in addr:
                            try:
                                port = int(addr.split(":")[-1])
                                listening_map[port] = pid
                            except ValueError:
                                pass
        except Exception:
            pass

        # Obtener nombres de procesos de esos PIDs
        try:
            import csv
            import io
            res_tasks = subprocess.run("tasklist /fo csv /nh", shell=True, capture_output=True, text=True, timeout=5)
            reader = csv.reader(io.StringIO(res_tasks.stdout or ""))
            for row in reader:
                if len(row) >= 2:
                    pid_name_map[str(row[1]).strip()] = str(row[0]).strip().lower()
        except Exception:
            pass

    else:
        # Linux / MacOS
        try:
            res_ss = subprocess.run("ss -tlpn", shell=True, capture_output=True, text=True, timeout=5)
            for line in (res_ss.stdout or "").splitlines():
                if "LISTEN" in line:
                    parts = line.split()
                    if len(parts) >= 4:
                        addr = parts[3]
                        port_str = addr.split(":")[-1]
                        proc_info = parts[-1] if len(parts) > 5 else ""
                        try:
                            port = int(port_str)
                            pid = ""
                            pname = "unknown"
                            if "pid=" in proc_info:
                                pid = proc_info.split("pid=")[1].split(",")[0].split(")")[0]
                            if 'users:(("' in proc_info:
                                pname = proc_info.split('users:(("')[1].split('"')[0]
                            listening_map[port] = pid or "active"
                            pid_name_map[pid or "active"] = pname
                        except ValueError:
                            pass
        except Exception:
            pass

    # 2. Analizar cada puerto del catálogo
    results = []
    conflict_count = 0
    open_count = 0

    for port, meta in SPECIAL_PORTS_CATALOG.items():
        is_open = port in listening_map or check_port_open("127.0.0.1", port, timeout=0.2)
        pid = listening_map.get(port, "")
        pname = pid_name_map.get(str(pid), "") if pid else ""

        is_conflict = False
        suggested_port = None
        status = "FREE"

        if is_open:
            open_count += 1
            status = "OPEN"
            expected_list = [x.lower() for x in meta.get("expected", [])]

            if pname:
                matches_expected = any(exp in pname for exp in expected_list)
                if not matches_expected:
                    is_conflict = True
                    status = "CONFLICT"
                    conflict_count += 1
            else:
                pname = "proceso_activo"

            if is_conflict:
                suggested_port = find_next_free_port(meta.get("fallback", port + 1))
                recommendation = f"Puerto ocupado por '{pname}' [PID {pid}]. Se sugiere remapear a puerto {suggested_port}."
            else:
                recommendation = f"Servicio activo y saludable ('{pname}' [PID {pid}])."
        else:
            recommendation = "Puerto disponible para iniciar servicio."

        results.append({
            "port": port,
            "service": meta["service"],
            "type": meta["type"],
            "status": status,
            "is_open": is_open,
            "is_conflict": is_conflict,
            "pid": pid or None,
            "process_name": pname or None,
            "suggested_port": suggested_port,
            "recommendation": recommendation,
        })

    return {
        "ok": True,
        "scanned_at": str(time.strftime("%Y-%m-%d %H:%M:%S")),
        "summary": {
            "total_scanned": len(SPECIAL_PORTS_CATALOG),
            "open_count": open_count,
            "conflict_count": conflict_count,
            "free_count": len(SPECIAL_PORTS_CATALOG) - open_count,
        },
        "ports": results,
    }
