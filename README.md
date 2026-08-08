# FacturaProEC Admin — Electron + Python

App de escritorio de administración local: BD PostgreSQL (local o VPN),
archivos (SFTP/FTP/Docker), módulo SRI (IMAP + RUC), y Security Guardian
(anti-intrusión). Compila para Windows 10/11 x64/x86, Linux (Mint, Arch,
Debian, etc.) y macOS (Intel + Apple Silicon).

## Arquitectura

```
┌──────────────────────────────────────────────────────────────┐
│  Electron (Chromium shell)                                    │
│  ├─ main process (Node) → lifecycle, tray, theme, spawn py    │
│  ├─ preload (contextBridge) → API segura al renderer          │
│  └─ renderer (React + Vite) → UI minimalista office           │
└──────────────────────────────────────────────────────────────┘
            ↕ HTTP 127.0.0.1:PUERTO_EFÍMERO
┌──────────────────────────────────────────────────────────────┐
│  Backend Python (FastAPI bridge)                              │
│  Reutiliza 100% del desktop_app/ existente:                   │
│  • sys_info.py → detección multiplataforma de servicios       │
│  • service_runner.py → Docker, firewall, SFTP, FTP, autostart │
│  • config_manager.py → persistencia %APPDATA%/~/.config      │
│  • db_viewer/ → SQLAlchemy async (PG + SQLite fallback)       │
│  • sri/ → IMAP + XML parser + RUC REST                       │
│  • security/guardian.py → watchdog anti-intrusión             │
└──────────────────────────────────────────────────────────────┘
```

El backend se lanza como child process del main de Electron, escucha en
un puerto efímero de 127.0.0.1 (lo elige el SO, lo imprime en stdout, y
el main lo parsea para dárselo al renderer via preload). El renderer
habla con el backend por `fetch` normal.

## Requisitos

- Node.js 18+ y npm
- Python 3.10+ con: `pip install -r python-backend/requirements.txt`
- El resto de dependencias Python (sqlalchemy, asyncpg, paramiko, etc.)
  ya están en el entorno del proyecto (las reutiliza de `desktop_app/`)

## Desarrollo

```bash
# 1. Instalar deps JS
npm install

# 2. Compilar main + preload TS → JS
npm run build:main

# 3. Lanzar Vite dev server (puerto 3000) y Electron en paralelo
npm run dev          # o por separado:
npm run dev:renderer   # vite, hot reload del renderer
npm start             # electron, carga http://localhost:3000

# El backend Python lo arranca el main de Electron automáticamente.
# Para probarlo aislado:
python python-backend/bridge.py
```

## Build (instaladores)

```bash
npm run build        # compila main + renderer
npm run dist:win      # Windows .exe (NSIS) + portable (x64 + ia32)
npm run dist:mac      # macOS .dmg (universal2)
npm run dist:linux     # Linux .AppImage + .deb (x64 + arm64)
```

Las salidas van a `admin-electron/release/`.

## Recursos

- `resources/icons/icon.{png,ico,icns}` — generados por
  `resources/scripts/icon_gen.py` (Pillow). Re-generar con:
  `python resources/scripts/icon_gen.py --all`
- `build/entitlements.mac.plist` — permisos para hardened runtime

## Vistas (renderer)

| Vista | Endpoint del bridge | Función |
|---|---|---|
| Dashboard | `/api/system/*` | IP, disco, servicios detectados, atajos |
| Base de Datos | `/api/db/*` | Conectar PG (local/VPN), listar tablas, ver estructura/datos, SQL libre, Exportar CSV, `pg_stat_activity` |
| SRI / Recepción | `/api/sri/*` | Probar/sincronizar IMAP, bandeja recibidos, consultar RUC, ver XML |
| Seguridad | `/api/security/*` | Escudo, whitelist, puertos, eventos, conexiones sospechosas, cerrojo |
| Almacenamiento | `/api/storage/*`, `/api/sftp/*`, `/api/docker/*`, `/api/firewall/*` | Carpeta, SFTP, OpenSSH, Docker 1-clic, firewall FTP/PG |
| VPN | `/api/sftp/test-full`, `/api/config` | Test SSH remoto, PG remoto, links a WireGuard/Tailscale |
| Configuración | `/api/config`, `/api/autostart` | Tema Dark/Light/System, autostart, minimizar a bandeja |

## Funcionalidades únicas (no en el ERP web)

- **Lista viva de conexiones PG** (`pg_stat_activity`): usuario, IP, query actual, duración
- **Security Guardian multiplataforma**: netstat (Win) + ss (Linux), whitelist persistente,
  detección de fuerza bruta, historial rotatorio, cerrojo de emergencia
- **System tray**: cerrar la ventana va al icono de bandeja; el backend y el
  guardian siguen corriendo en segundo plano
- **Command Palette (Ctrl+K)**: salto rápido entre vistas
- **Tema Dark/Light/System** con auto-detección del SO (vía `nativeTheme`)
- **Notificaciones desktop nativas**: toast al llegar sync SRI, lockdown, etc.

## Notas técnicas

- El `bridge.py` añade `../desktop_app` al `sys.path` para importar los
  módulos existentes sin duplicar ni mover código. En el build empaquetado,
  el `extraResources` copia `python-backend/` y `resources/` dentro del app.
- El icono de bandeja se minimiza siempre; "salir" realmente mata el backend.
- El el broker escucha en `127.0.0.1` (sólo loopback) — nunca expone puertos
  al exterior. El renderer hace fetch al mismo host.
