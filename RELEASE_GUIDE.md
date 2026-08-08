# 📦 Guía de Releases — FacturaProEC Admin

Todo el flujo de control de versiones + empaquetado + auto-update está automatizado con **un solo comando**.

---

## TL;DR — lanzar una nueva versión

```bash
cd C:\Users\jloor\Proyectos\FacturaProEC\admin-electron
npm run release:patch      # 2.0.2 → 2.0.3  (bug fixes)
npm run release:minor      # 2.0.2 → 2.1.0  (nuevas features)
npm run release:major      # 2.0.2 → 3.0.0  (breaking changes)
```

Ese comando hace **todo**:

1. Bump de versión en `package.json`
2. Compila TypeScript (main + renderer Vite)
3. Empaqueta Windows NSIS x64 en `dist-build-X.Y.Z/`
4. Corrige `latest.yml` para que el **auto-updater use el NSIS x64** (no el portable)
5. Copia el instalador a `C:\Users\jloor\Downloads\` para que lo pruebes
6. Hace `git commit v + git tag vX.Y.Z`
7. Hace `git push origin main --tags` al repo de GitHub
8. Si hay `GH_TOKEN` → **sube el .exe + latest.yml automáticamente al GitHub Release** ✅
   Si no → te imprime las instrucciones para subirlo en 2 clics por el navegador

---

## 🔄 Auto-update — cómo funciona sin que el usuario toque nada

La app (en `src/main/main.ts`) usa `electron-updater`. Cuando un usuario abre la app:

1. A los 5s consulta `https://github.com/Democresss/FacturaProEC-Admin/releases/latest`
2. Lee el `latest.yml` ahí publicado → compara `version` con la instalada
3. Si hay versión mayor → **descarga solo el .exe automáticamente** (usando el blockmap para bajar pedazos incrementales, descarga rápida)
4. Avisa al usuario con notificación → al cerrar la app se **instala y reinicia sola**

> El campo `path` del `latest.yml` DEBE apuntar al NSIS x64. El script `release.mjs` se encarga de dejarlo así automáticamente (electron-builder por defecto lo apuntaría al portable, que no se instala con NSIS sino que es solo portable).

---

## 🔑 (Una vez) Configurar el token para que sea 100% automático

Sin token, el release se crea con `git push` pero el `.exe` se adjunta a mano. Con token, son cero clics:

```bash
npm run gh:auth
```

Te guía a crear un **Personal Access Token** en `https://github.com/settings/tokens/new`:
- Scopes: `repo` + `workflow`
- Copias el token (empieza con `ghp_…`)
- Lo pegas en la consola
- Se guarda en `C:\Users\jloor\.facturaproec-gh-token` (FUERA del repo — nunca va a git)

A partir de ahí, `npm run release:patch` sube el .exe automáticamente. Sin pasos manuales.

---

## ✅ Probar el instalador en tu PC

El instalador ya está en:

```
C:\Users\jloor\Downloads\FacturaProEC-Admin-2.0.2-win-x64.exe
```

1. Doble-clic → instalador NSIS
2. Elige carpeta (por defecto `C:\Users\jloor\AppData\Local\Programs\facturaproec-admin`)
3. Crea acceso en escritorio + menú inicio
4. Al abrirlo: primero spinner "Conectando con backend…", luego el Dashboard

> Si te falla "Error de conexión con el backend Python", son las deps Python. Una sola vez:
> ```bash
> cd C:\Users\jloor\Proyectos\FacturaProEC\admin-electron
> python -m pip install -r python-backend\requirements.txt
> python -m pip install sqlalchemy asyncpg psycopg2-binary aiosqlite paramiko requests
> ```

Para desinstalar: "Agregar o quitar programas" → FacturaProEC Admin.

---

## 🧪 Modo dev (sin instalar nada)

```bash
# Terminal 1
npm run dev:renderer      # Vite en http://localhost:3000 (hot reload)

# Terminal 2
npm start                 # Electron cargando localhost:3000
```

---

## 📁 Estructura del repo

```
admin-electron/
├── src/
│   ├── main/main.ts          # Electron main + auto-updater + bridge
│   ├── preload/preload.ts    # contextBridge seguro
│   └── renderer/             # React + TypeScript + Vite
├── python-backend/
│   ├── bridge.py             # FastAPI que reutiliza desktop_app/
│   └── requirements.txt
├── resources/                # iconos (win/mac/linux)
├── scripts/
│   ├── release.mjs           # ⭐ automatización de releases
│   └── gh-auth.mjs           # ⭐ configuración de GH_TOKEN
├── package.json              # config electron-builder + scripts release
└── .gitignore                # excluye binarios (van a GitHub Releases, no a git)
```

**Lo que NO entra a git** (porque está en `.gitignore`):
- `node_modules/`, `package-lock.json`
- `dist/`, `dist-build*/`, `release/`  → builds locales
- `*.exe`, `*.dmg`, `*.AppImage`, `*.deb`  → binarios (van a GitHub Releases)
- `latest.yml`, `*-unpacked/`  → outputs del builder
- Archivos efímeros: `.release-id`

---

## 🌍 Builds para Mac y Linux

En Windows solo se puede empaquetar de forma confiable para Windows.
Para Mac (`.dmg`) y Linux (`.AppImage`/`.deb`) hay que hacerlo en una VM/CI de cada OS:

```bash
# Mac (en macOS)
npm run dist:mac

# Linux (en Linux o WSL con permisos de symlink)
npm run dist:linux
```

Recomendación: configurar **GitHub Actions** (workflow) que en cada tag `v*` haga el build para los 3 OS en paralelo y suba todo al Release automáticamente. Si quieres, lo configuro.

---

## 📜 Historial de releases

Lo ves en: https://github.com/Democresss/FacturaProEC-Admin/releases

Cada tag `vX.Y.Z` está ahí. Al publicar uno nuevo, las instalaciones anteriores se actualizan solas.
